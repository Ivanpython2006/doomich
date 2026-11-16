"""Общие схемы ответов API."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class UniversityOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    timezone: str
    utc_offset_minutes: int = 0  # текущее смещение часового пояса вуза от UTC


class GroupOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str | None = None
    faculty: str | None = None


class MeOut(BaseModel):
    id: uuid.UUID
    login: str
    role: str
    locale: str
    history_days: int
    university: UniversityOut
    group: GroupOut | None = None
    created_on: date
    features: dict[str, bool] = Field(default_factory=dict)


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — тип токена, а не пароль
    expires_in: int
    user: MeOut
    recovery_code: str | None = None


class ChatOut(BaseModel):
    id: uuid.UUID
    title: str
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    author: Literal["user", "assistant"]
    content: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    mode: str
    created_at: datetime


class EventOut(BaseModel):
    id: uuid.UUID
    uid: str
    group_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    subject: str
    kind: str | None = None
    room: str | None = None
    building: str | None = None
    teacher: str | None = None
    subgroup: str | None = None
    note: str | None = None


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    owner_type: str
    mime: str
    size_bytes: int
    pages: int | None = None
    status: str
    error: str | None = None
    created_at: datetime


class OkOut(BaseModel):
    ok: bool = True
