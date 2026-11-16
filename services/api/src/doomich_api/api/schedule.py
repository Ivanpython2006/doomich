"""Расписание для пользователя: события по группе или преподавателю, изменения, список преподавателей."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.api.deps import current_user, user_session
from doomich_api.api.schemas import EventOut
from doomich_api.context import UserContext
from doomich_api.models import ScheduleChange, ScheduleEvent, StudyGroup
from doomich_api.schedule.service import events_for, local_day_bounds

router = APIRouter(prefix="/v1", tags=["schedule"])


class ChangeOut(BaseModel):
    id: int
    event_uid: str
    change: str
    payload: dict
    created_at: datetime


async def _group_for(session: AsyncSession, user: UserContext, group_id: uuid.UUID | None) -> uuid.UUID | None:
    if group_id is None:
        return user.group_id
    group = await session.get(StudyGroup, group_id)
    if group is None or group.university_id != user.university_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Группа не найдена")
    return group.id


@router.get("/schedule", response_model=list[EventOut])
async def schedule(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    group_id: uuid.UUID | None = None,
    teacher: str | None = Query(None, max_length=255),
    user: UserContext = Depends(current_user),
    session: AsyncSession = Depends(user_session),
):
    today = user.now().date()
    start = date_from or today - timedelta(days=today.weekday())
    end = date_to or start + timedelta(days=13)
    if (end - start).days > 120:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Слишком большой период")
    gid = await _group_for(session, user, group_id)
    lo, hi = local_day_bounds(start, end, user.tz)
    events = await events_for(session, gid, lo, hi, university_id=user.university_id, teacher=teacher)
    return [
        EventOut(
            id=e.id,
            uid=e.uid,
            group_id=e.group_id,
            starts_at=e.starts_at,
            ends_at=e.ends_at,
            subject=e.subject,
            kind=e.kind,
            room=e.room,
            building=e.building,
            teacher=e.teacher,
            subgroup=e.subgroup,
            note=e.note,
        )
        for e in events
    ]


@router.get("/schedule/changes", response_model=list[ChangeOut])
async def changes(
    since: datetime,
    group_id: uuid.UUID | None = None,
    user: UserContext = Depends(current_user),
    session: AsyncSession = Depends(user_session),
):
    gid = await _group_for(session, user, group_id)
    if gid is None:
        return []
    rows = await session.execute(
        select(ScheduleChange)
        .where(ScheduleChange.group_id == gid, ScheduleChange.created_at > since)
        .order_by(ScheduleChange.created_at)
        .limit(200)
    )
    return [
        ChangeOut(id=c.id, event_uid=c.event_uid, change=c.change, payload=c.payload, created_at=c.created_at)
        for c in rows.scalars()
    ]


@router.get("/teachers", response_model=list[str])
async def teachers(
    q: str = Query("", max_length=100),
    user: UserContext = Depends(current_user),
    session: AsyncSession = Depends(user_session),
):
    """Список преподавателей (только если вуз разрешил хранить ФИО). Выбор хранится на устройстве."""
    stmt = select(distinct(ScheduleEvent.teacher)).where(
        ScheduleEvent.university_id == user.university_id, ScheduleEvent.teacher.is_not(None)
    )
    if q.strip():
        stmt = stmt.where(ScheduleEvent.teacher.ilike(f"%{q.strip()}%"))
    rows = await session.execute(stmt.order_by(ScheduleEvent.teacher).limit(50))
    return [t for t in rows.scalars() if t]
