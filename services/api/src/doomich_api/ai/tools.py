"""Инструменты ассистента: расписание, поиск по документам, справка о вузе, маршрут (R2)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from doomich_api.ai import Providers
from doomich_api.context import UserContext
from doomich_api.db import session_scope
from doomich_api.models import CourseMember, Document, StudyGroup
from doomich_api.nav.routing import describe_route, find_node, load_graph, shortest_path
from doomich_api.rag.search import Hit, SearchScope, format_hits_for_llm, hybrid_search
from doomich_api.schedule.service import events_for, local_day_bounds, normalize_group
from doomich_api.security import get_crypto

log = logging.getLogger(__name__)

_WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

SCHEDULE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_schedule",
        "description": "Расписание занятий группы пользователя (или указанной группы) на диапазон дат.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Начало периода, YYYY-MM-DD. Пусто — сегодня."},
                "date_to": {"type": "string", "description": "Конец периода, YYYY-MM-DD. Пусто — как date_from."},
                "group": {"type": "string", "description": "Код другой группы, если спросили про неё."},
            },
        },
    },
}
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_documents",
        "description": "Поиск по документам, которые загрузил пользователь (и материалам его курсов).",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Поисковый запрос по смыслу вопроса."}},
            "required": ["query"],
        },
    },
}
UNIVERSITY_TOOL = {
    "type": "function",
    "function": {
        "name": "university_info",
        "description": "Справка о вузе: правила, службы, контакты, стипендии, общежития.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}
NAVIGATE_TOOL = {
    "type": "function",
    "function": {
        "name": "navigate",
        "description": "Маршрут по кампусу до аудитории или места.",
        "parameters": {
            "type": "object",
            "properties": {
                "destination": {"type": "string", "description": "Номер аудитории или название места."},
                "origin": {"type": "string", "description": "Где пользователь сейчас, если известно."},
                "accessible": {"type": "boolean", "description": "Без лестниц (доступная среда)."},
            },
            "required": ["destination"],
        },
    },
}


class ToolBox:
    def __init__(
        self,
        user: UserContext,
        providers: Providers,
        *,
        document_ids: list[uuid.UUID] | None = None,
        has_university_kb: bool = False,
        has_campus_graph: bool = False,
    ) -> None:
        self.user = user
        self.providers = providers
        self.document_ids = document_ids or None
        self.has_university_kb = has_university_kb
        self.has_campus_graph = has_campus_graph
        self.fragments: list[Hit] = []

    def definitions(self) -> list[dict[str, Any]]:
        tools = [SCHEDULE_TOOL, SEARCH_TOOL]
        if self.has_university_kb:
            tools.append(UNIVERSITY_TOOL)
        if self.has_campus_graph:
            tools.append(NAVIGATE_TOOL)
        return tools

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        try:
            if name == "get_schedule":
                return await self.get_schedule(**_only(args, "date_from", "date_to", "group"))
            if name == "search_documents":
                return await self.search(str(args.get("query", "")), university=False)
            if name == "university_info":
                return await self.search(str(args.get("query", "")), university=True)
            if name == "navigate":
                return await self.navigate(**_only(args, "destination", "origin", "accessible"))
        except Exception:
            log.exception("Ошибка инструмента %s", name)
            return "Инструмент временно недоступен. Скажи пользователю, что данные сейчас получить не удалось."
        return f"Неизвестный инструмент {name}"

    # ------------------------------------------------------------------ расписание
    async def get_schedule(
        self, date_from: str | None = None, date_to: str | None = None, group: str | None = None
    ) -> str:
        today = self.user.now().date()
        start = _date_or(date_from, today)
        end = _date_or(date_to, start)
        if end < start:
            start, end = end, start
        end = min(end, start + timedelta(days=31))
        async with session_scope(self.user.rls) as session:
            group_id, group_code = self.user.group_id, self.user.group_code
            if group:
                found = (
                    await session.execute(
                        select(StudyGroup).where(
                            StudyGroup.university_id == self.user.university_id,
                            StudyGroup.code_norm == normalize_group(group),
                        )
                    )
                ).scalar_one_or_none()
                if found is None:
                    return f"Группа «{group}» не найдена в расписании вуза."
                group_id, group_code = found.id, found.code
            if group_id is None:
                return (
                    "У пользователя не выбрана группа. Попроси выбрать её в разделе «Расписание» "
                    "или назвать код группы."
                )
            lo, hi = local_day_bounds(start, end, self.user.tz)
            events = await events_for(session, group_id, lo, hi, university_id=self.user.university_id)
        header = f"Расписание группы {group_code} с {start:%d.%m.%Y} по {end:%d.%m.%Y}:"
        if not events:
            return header + "\nЗанятий нет."
        lines = [header]
        for e in events:
            s, f = e.starts_at.astimezone(self.user.tz), e.ends_at.astimezone(self.user.tz)
            parts = [f"{s:%d.%m} ({_WEEKDAYS[s.weekday()]}) {s:%H:%M}–{f:%H:%M} — {e.subject}"]
            if e.kind:
                parts.append(f"({e.kind})")
            if e.room:
                parts.append(f"ауд. {e.room}")
            if e.building:
                parts.append(f"корп. {e.building}")
            if e.subgroup:
                parts.append(f"подгруппа {e.subgroup}")
            if e.teacher:
                parts.append(f"преп. {e.teacher}")
            lines.append(", ".join(parts))
        return "\n".join(lines)

    # ------------------------------------------------------------------ документы
    async def search(self, query: str, *, university: bool) -> str:
        if not query.strip():
            return "Пустой запрос."
        crypto = get_crypto()
        vec = await self.providers.embedder.embed_query(query)

        def title_of(doc: Document) -> str:
            if doc.title_enc and doc.user_id == self.user.user_id:
                return crypto.decrypt_text(
                    self.user.wrapped_dek, self.user.user_id, doc.title_enc, f"doctitle:{doc.id}"
                )
            return doc.title or "документ"

        async with session_scope(self.user.rls) as session:
            course_ids = []
            if not university:
                course_ids = list(
                    (
                        await session.execute(
                            select(CourseMember.course_id).where(CourseMember.user_id == self.user.user_id)
                        )
                    ).scalars()
                )
            scope = SearchScope(
                university_id=self.user.university_id,
                user_id=self.user.user_id,
                include_user=not university,
                include_university=university,
                course_ids=course_ids,
                document_ids=None if university else self.document_ids,
            )
            hits = await hybrid_search(
                session,
                scope=scope,
                query=query,
                query_vec=vec,
                embed_model=self.providers.embedder.model_name,
                reranker=self.providers.reranker,
                title_of=title_of,
            )
        start = len(self.fragments) + 1
        self.fragments.extend(hits)
        if not hits:
            return "В документах ничего не найдено по этому запросу."
        return format_hits_for_llm(hits, start=start)

    # ------------------------------------------------------------------ маршрут
    async def navigate(self, destination: str, origin: str | None = None, accessible: bool = False) -> str:
        async with session_scope(self.user.rls) as session:
            graph = await load_graph(session, self.user.university_id)
        if not graph.nodes:
            return "Карта кампуса ещё не загружена."
        goal = find_node(graph, destination)
        if goal is None:
            return f"Не нашёл на карте «{destination}»."
        if not origin:
            return (
                f"Цель найдена: {destination} ({goal.building}, {goal.floor_level} этаж). "
                "Спроси, где пользователь сейчас, или предложи режим «Где я?» с камерой."
            )
        start = find_node(graph, origin)
        if start is None:
            return f"Не нашёл на карте точку «{origin}». Уточни у пользователя, что он видит рядом."
        route = shortest_path(graph, start.id, goal.id, accessible_only=bool(accessible))
        if route is None:
            return "Маршрут не найден (возможно, нет прохода без лестниц)."
        path, length = route
        steps = describe_route(graph, path, locale=self.user.locale)
        return json.dumps({"length_m": round(length), "steps": steps}, ensure_ascii=False)


def _only(args: dict[str, Any], *names: str) -> dict[str, Any]:
    return {k: v for k, v in args.items() if k in names and v not in (None, "")}


def _date_or(value: str | None, default: date) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return default
