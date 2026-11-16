"""Контекст пользователя для обработки запросов и фоновых задач."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.db import RlsContext
from doomich_api.models import AppUser, StudyGroup, University


@dataclass
class UserContext:
    user_id: uuid.UUID
    university_id: uuid.UUID
    university_slug: str
    university_name: str
    timezone: str
    role: str
    locale: str
    group_id: uuid.UUID | None
    group_code: str | None
    wrapped_dek: bytes
    history_days: int
    tenant_settings: dict[str, Any] = field(default_factory=dict)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    @property
    def rls(self) -> RlsContext:
        return RlsContext(user_id=self.user_id, university_id=self.university_id)


async def load_user_context(session: AsyncSession, user_id: uuid.UUID) -> UserContext | None:
    user = await session.get(AppUser, user_id)
    if user is None or user.disabled:
        return None
    university = await session.get(University, user.university_id)
    group = await session.get(StudyGroup, user.group_id) if user.group_id else None
    assert university is not None
    return UserContext(
        user_id=user.id,
        university_id=university.id,
        university_slug=university.slug,
        university_name=university.name,
        timezone=university.timezone,
        role=user.role,
        locale=user.locale,
        group_id=group.id if group else None,
        group_code=group.code if group else None,
        wrapped_dek=user.wrapped_dek,
        history_days=user.history_days,
        tenant_settings=dict(university.settings or {}),
    )
