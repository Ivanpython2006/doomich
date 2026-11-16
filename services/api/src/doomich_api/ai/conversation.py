"""Один «ход» диалога: подготовка, запуск оркестратора, сохранение ответа.

Используется и текстовым чатом (SSE), и голосовым каналом (WebSocket).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert

from doomich_api.ai import get_providers
from doomich_api.ai.model_routing import resolve_llm_model
from doomich_api.ai.orchestrator import Orchestrator, TurnEvent
from doomich_api.ai.text import make_title
from doomich_api.ai.tools import ToolBox
from doomich_api.config import get_settings
from doomich_api.context import UserContext
from doomich_api.db import RlsContext, session_scope, utcnow
from doomich_api.models import Building as BuildingModel
from doomich_api.models import Campus, Chat, DailyUsage, Document, Floor, Message, NavNode
from doomich_api.security import get_crypto

HISTORY_LIMIT = 40
_flags_cache: dict[uuid.UUID, tuple[float, bool, bool]] = {}


async def tenant_flags(university_id: uuid.UUID) -> tuple[bool, bool]:
    """(есть ли база знаний вуза, есть ли граф кампуса) — с кэшем на минуту."""
    cached = _flags_cache.get(university_id)
    if cached and time.monotonic() - cached[0] < 60:
        return cached[1], cached[2]
    async with session_scope(RlsContext.system()) as session:
        has_kb = bool(
            (
                await session.execute(
                    select(
                        exists().where(
                            Document.university_id == university_id,
                            Document.owner_type == "university",
                            Document.status == "ready",
                        )
                    )
                )
            ).scalar()
        )
        has_graph = bool(
            (
                await session.execute(
                    select(
                        exists()
                        .where(NavNode.floor_id == Floor.id)
                        .where(Floor.building_id == BuildingModel.id)
                        .where(BuildingModel.campus_id == Campus.id)
                        .where(Campus.university_id == university_id)
                    )
                )
            ).scalar()
        )
    _flags_cache[university_id] = (time.monotonic(), has_kb, has_graph)
    return has_kb, has_graph


async def check_daily_limit(session, user: UserContext) -> None:
    today = utcnow().date()
    stmt = (
        insert(DailyUsage)
        .values(user_id=user.user_id, day=today, messages=1)
        .on_conflict_do_update(index_elements=["user_id", "day"], set_={"messages": DailyUsage.messages + 1})
        .returning(DailyUsage.messages)
    )
    count = (await session.execute(stmt)).scalar_one()
    if count > get_settings().messages_per_day_limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Дневной лимит сообщений исчерпан")


@dataclass
class PreparedTurn:
    chat_id: uuid.UUID | None
    history: list[dict[str, str]]
    document_ids: list[uuid.UUID]


async def prepare_turn(
    user: UserContext,
    *,
    chat_id: uuid.UUID | None,
    text: str,
    mode: str,
    incognito_history: list[dict[str, str]] | None = None,
    document_ids: list[uuid.UUID] | None = None,
) -> PreparedTurn:
    """Проверить лимиты, сохранить сообщение пользователя (если не инкогнито), собрать историю."""
    crypto = get_crypto()
    async with session_scope(user.rls) as session:
        await check_daily_limit(session, user)
        if chat_id is None:
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in (incognito_history or [])[-HISTORY_LIMIT:]
                if m.get("role") in {"user", "assistant"} and m.get("content")
            ]
            return PreparedTurn(None, history, document_ids or [])
        chat = await session.get(Chat, chat_id)
        if chat is None or chat.user_id != user.user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
        rows = (
            await session.execute(
                select(Message)
                .where(Message.chat_id == chat.id)
                .order_by(Message.created_at.desc())
                .limit(HISTORY_LIMIT)
            )
        ).scalars()
        history = [
            {
                "role": m.author,
                "content": crypto.decrypt_text(user.wrapped_dek, user.user_id, m.content_enc, f"msg:{m.id}"),
            }
            for m in reversed(list(rows))
        ]
        message = Message(id=uuid.uuid4(), chat_id=chat.id, user_id=user.user_id, author="user", mode=mode)
        message.content_enc = crypto.encrypt_text(user.wrapped_dek, user.user_id, text, f"msg:{message.id}")
        session.add(message)
        if not history:
            chat.title_enc = crypto.encrypt_text(user.wrapped_dek, user.user_id, make_title(text), f"chat:{chat.id}")
        chat.updated_at = utcnow()
        chat.expires_at = utcnow() + timedelta(days=max(1, user.history_days))
        scope = [uuid.UUID(d) for d in chat.document_ids or []]
        return PreparedTurn(chat.id, history, document_ids or scope)


async def run_turn(user: UserContext, turn: PreparedTurn, text: str, *, voice: bool) -> AsyncIterator[TurnEvent]:
    """Запустить оркестратор и сохранить ответ ассистента. Событие done дополняется message_id."""
    providers = get_providers()
    settings = get_settings()
    has_kb, has_graph = await tenant_flags(user.university_id)
    toolbox = ToolBox(
        user, providers, document_ids=turn.document_ids, has_university_kb=has_kb, has_campus_graph=has_graph
    )
    model = await resolve_llm_model(user, providers, settings)
    orchestrator = Orchestrator(providers, settings)
    async for event in orchestrator.run(
        user=user, toolbox=toolbox, history=turn.history, user_text=text, model=model, voice=voice
    ):
        if event.type == "done" and turn.chat_id is not None:
            event.data["message_id"] = str(await save_assistant_message(user, turn.chat_id, event, voice))
        yield event


async def save_assistant_message(user: UserContext, chat_id: uuid.UUID, event: TurnEvent, voice: bool) -> uuid.UUID:
    crypto = get_crypto()
    async with session_scope(user.rls) as session:
        message = Message(
            id=uuid.uuid4(),
            chat_id=chat_id,
            user_id=user.user_id,
            author="assistant",
            mode="voice" if voice else "text",
            citations=event.data.get("citations", []),
            model_version=event.data.get("model"),
        )
        message.content_enc = crypto.encrypt_text(user.wrapped_dek, user.user_id, event.text, f"msg:{message.id}")
        session.add(message)
        chat = await session.get(Chat, chat_id)
        if chat is not None:
            chat.updated_at = utcnow()
        return message.id
