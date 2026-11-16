"""Применение импорта расписания к БД: группы, сравнение версий, журнал изменений."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.config import get_settings
from doomich_api.db import utcnow
from doomich_api.models import (
    ScheduleChange,
    ScheduleEvent,
    ScheduleImport,
    ScheduleSource,
    StudyGroup,
    University,
)
from doomich_api.schedule.importers import (
    EventDraft,
    ImportErrorFatal,
    ImportResult,
    html_table_to_events,
    ics_to_events,
    json_to_events,
    read_csv,
    read_excel,
    rows_to_events,
)

log = logging.getLogger(__name__)


def normalize_group(code: str) -> str:
    return "".join(code.split()).replace("—", "-").replace("–", "-").upper()


def keep_teacher_names(university: University) -> bool:
    return bool((university.settings or {}).get("store_teacher_names", False))


def tz_of(university: University) -> ZoneInfo:
    return ZoneInfo(university.timezone or "Europe/Moscow")


def parse_file(university: University, filename: str, data: bytes, options: dict[str, Any]) -> ImportResult:
    tz = tz_of(university)
    keep = keep_teacher_names(university)
    name = filename.lower()
    semester_start = date.fromisoformat(options["semester_start"]) if options.get("semester_start") else None
    if name.endswith((".xlsx", ".xlsm")):
        return rows_to_events(read_excel(data), tz, keep_teacher=keep, semester_start=semester_start)
    if name.endswith(".csv"):
        return rows_to_events(read_csv(data), tz, keep_teacher=keep, semester_start=semester_start)
    if name.endswith(".ics"):
        group = options.get("group")
        if not group:
            raise ImportErrorFatal("Для файла .ics укажите группу")
        today = datetime.now(tz).date()
        window = (today - timedelta(days=30), today + timedelta(days=200))
        return ics_to_events(data, tz, group=group, window=window, keep_teacher=keep)
    raise ImportErrorFatal("Поддерживаются .xlsx, .csv и .ics")


async def _groups_by_code(
    session: AsyncSession, university_id: uuid.UUID, codes: set[str], *, create: bool
) -> dict[str, StudyGroup]:
    norms = {normalize_group(c): c for c in codes}
    rows = (
        await session.execute(
            select(StudyGroup).where(StudyGroup.university_id == university_id, StudyGroup.code_norm.in_(norms))
        )
    ).scalars()
    found = {g.code_norm: g for g in rows}
    if create:
        for norm, original in norms.items():
            if norm not in found:
                group = StudyGroup(university_id=university_id, code=original.strip(), code_norm=norm)
                session.add(group)
                found[norm] = group
        await session.flush()
    return {code: found[normalize_group(code)] for code in codes if normalize_group(code) in found}


async def apply_import(
    session: AsyncSession,
    university: University,
    result: ImportResult,
    *,
    source_id: uuid.UUID | None = None,
    filename: str | None = None,
    create_groups: bool = True,
) -> dict[str, Any]:
    """Заменить события (группа, источник) в периоде импорта и записать изменения."""
    stats = {"groups": 0, "added": 0, "removed": 0, "changed": 0, "unchanged": 0, "errors": len(result.errors)}
    groups = await _groups_by_code(session, university.id, result.groups, create=create_groups)
    by_group: dict[str, list[EventDraft]] = {}
    for draft in result.events:
        by_group.setdefault(draft.group, []).append(draft)

    for code, drafts in by_group.items():
        group = groups.get(code)
        if group is None:
            result.errors.append({"row": None, "error": f"неизвестная группа «{code}»"})
            continue
        stats["groups"] += 1
        # заменяем расписание целыми днями: всё, что было в эти дни из этого источника и не пришло снова, удаляется
        tz = tz_of(university)
        first_day = min(d.starts_at.astimezone(tz).date() for d in drafts)
        last_day = max(d.starts_at.astimezone(tz).date() for d in drafts)
        window_start, window_end = local_day_bounds(first_day, last_day, tz)
        source_cond = ScheduleEvent.source_id == source_id if source_id else ScheduleEvent.source_id.is_(None)
        existing = {
            e.uid: e
            for e in (
                await session.execute(
                    select(ScheduleEvent).where(
                        ScheduleEvent.group_id == group.id,
                        source_cond,
                        ScheduleEvent.starts_at >= window_start,
                        ScheduleEvent.starts_at < window_end,
                    )
                )
            ).scalars()
        }
        incoming = {d.uid: d for d in drafts}

        for uid, event in existing.items():
            if uid not in incoming:
                session.add(
                    ScheduleChange(group_id=group.id, event_uid=uid, change="removed", payload=_snapshot(event))
                )
                await session.delete(event)
                stats["removed"] += 1

        for uid, draft in incoming.items():
            event = existing.get(uid)
            if event is None:
                # тот же uid мог прийти из другого источника — тогда обновляем его
                event = (
                    await session.execute(
                        select(ScheduleEvent).where(ScheduleEvent.group_id == group.id, ScheduleEvent.uid == uid)
                    )
                ).scalar_one_or_none()
                if event is None:
                    session.add(_new_event(university.id, group.id, draft, source_id))
                    session.add(
                        ScheduleChange(group_id=group.id, event_uid=uid, change="added", payload=draft.comparable())
                    )
                    stats["added"] += 1
                    continue
            before = _snapshot(event)
            after = draft.comparable()
            if before != after:
                _update_event(event, draft, source_id)
                session.add(
                    ScheduleChange(
                        group_id=group.id, event_uid=uid, change="changed", payload={"before": before, "after": after}
                    )
                )
                stats["changed"] += 1
            else:
                stats["unchanged"] += 1

    session.add(
        ScheduleImport(
            university_id=university.id,
            source_id=source_id,
            filename=filename,
            status="ok" if not result.errors else "partial",
            stats=stats,
            errors=result.errors[:500],
        )
    )
    await session.flush()
    return stats


def _new_event(university_id: uuid.UUID, group_id: uuid.UUID, d: EventDraft, source_id) -> ScheduleEvent:
    event = ScheduleEvent(university_id=university_id, group_id=group_id, uid=d.uid, source_id=source_id)
    _update_event(event, d, source_id)
    return event


def _update_event(event: ScheduleEvent, d: EventDraft, source_id) -> None:
    event.starts_at = d.starts_at
    event.ends_at = d.ends_at
    event.subject = d.subject
    event.kind = d.kind
    event.room = d.room
    event.building = d.building
    event.teacher = d.teacher
    event.subgroup = d.subgroup
    event.note = d.note
    event.source_id = source_id
    event.updated_at = utcnow()


def _snapshot(event: ScheduleEvent) -> dict[str, Any]:
    return {
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat(),
        "subject": event.subject,
        "kind": event.kind,
        "room": event.room,
        "building": event.building,
        "teacher": event.teacher,
        "subgroup": event.subgroup,
        "note": event.note,
    }


async def events_for(
    session: AsyncSession,
    group_id: uuid.UUID | None,
    start: datetime,
    end: datetime,
    *,
    university_id: uuid.UUID,
    teacher: str | None = None,
) -> list[ScheduleEvent]:
    cond = [
        ScheduleEvent.university_id == university_id,
        ScheduleEvent.starts_at >= start,
        ScheduleEvent.starts_at < end,
    ]
    if teacher:
        cond.append(ScheduleEvent.teacher == teacher)
    elif group_id:
        cond.append(ScheduleEvent.group_id == group_id)
    else:
        return []
    rows = await session.execute(select(ScheduleEvent).where(and_(*cond)).order_by(ScheduleEvent.starts_at))
    return list(rows.scalars())


def local_day_bounds(day_from: date, day_to: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day_from, datetime.min.time(), tz)
    end = datetime.combine(day_to + timedelta(days=1), datetime.min.time(), tz)
    return start.astimezone(UTC), end.astimezone(UTC)


# ---------------------------------------------------------------- синхронизация источников
def validate_source_url(url: str) -> tuple[str, int]:
    """Проверить вид адреса источника; вернуть хост и порт."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ImportErrorFatal("Адрес источника должен начинаться с http:// или https://")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise ImportErrorFatal("Неверный порт в адресе источника") from exc
    return parts.hostname, port


async def check_source_url(url: str) -> None:
    """Защита от SSRF: источник расписания не должен вести во внутреннюю сеть сервиса.

    Разрешены публичные адреса и явно перечисленные в DOOMICH_SCHEDULE_SOURCE_PRIVATE_HOSTS.
    Проверяется и каждый адрес перенаправления.
    """
    host, port = validate_source_url(url)
    if host.lower() in {h.lower() for h in get_settings().schedule_source_private_hosts}:
        return
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ImportErrorFatal(f"Не удалось найти сервер {host}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise ImportErrorFatal(
                f"Сервер {host} находится во внутренней сети. Если это сервер расписания вуза, "
                "добавьте его в DOOMICH_SCHEDULE_SOURCE_PRIVATE_HOSTS"
            )


async def _check_request(request: httpx.Request) -> None:
    await check_source_url(str(request.url))


async def fetch_source(source: ScheduleSource, university: University) -> ImportResult:
    cfg = source.config or {}
    tz = tz_of(university)
    keep = keep_teacher_names(university)
    async with httpx.AsyncClient(
        timeout=60, follow_redirects=True, max_redirects=5, event_hooks={"request": [_check_request]}
    ) as client:
        # только GET: источник читается, а не изменяется
        resp = await client.get(cfg["url"], headers=cfg.get("headers") or {})
        resp.raise_for_status()
    if source.kind == "json":
        return json_to_events(resp.json(), tz, cfg, keep_teacher=keep)
    if source.kind == "html":
        return html_table_to_events(resp.text, tz, cfg, keep_teacher=keep)
    if source.kind == "ics":
        today = datetime.now(tz).date()
        return ics_to_events(
            resp.content,
            tz,
            group=cfg["group"],
            window=(today - timedelta(days=7), today + timedelta(days=200)),
            keep_teacher=keep,
        )
    if source.kind in {"excel", "csv"}:
        rows = read_excel(resp.content) if source.kind == "excel" else read_csv(resp.content)
        return rows_to_events(rows, tz, keep_teacher=keep)
    raise ImportErrorFatal(f"Неизвестный тип источника: {source.kind}")


async def sync_source(session: AsyncSession, source: ScheduleSource) -> dict[str, Any]:
    university = await session.get(University, source.university_id)
    assert university is not None
    source.last_run_at = utcnow()
    try:
        result = await fetch_source(source, university)
        digest = result.content_hash()
        if digest == source.last_hash:
            source.last_status = "unchanged"
            source.last_error = None
            return {"status": "unchanged"}
        stats = await apply_import(session, university, result, source_id=source.id, filename=source.name)
        source.last_hash = digest
        source.last_status = "ok" if not result.errors else "partial"
        source.last_error = "; ".join(e["error"] for e in result.errors[:5]) or None
        return stats
    except Exception as exc:
        log.warning("Синхронизация расписания «%s» не удалась: %s", source.name, exc)
        source.last_status = "error"
        source.last_error = str(exc)[:1000]
        return {"status": "error", "error": str(exc)}


async def purge_old_changes(session: AsyncSession, days: int = 60) -> None:
    await session.execute(delete(ScheduleChange).where(ScheduleChange.created_at < utcnow() - timedelta(days=days)))
