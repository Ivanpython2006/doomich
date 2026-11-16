"""Подключение к PostgreSQL, сессии и контекст Row-Level Security.

Изоляция данных пользователей обеспечивается дважды: фильтрами в коде и политиками RLS
в PostgreSQL. Политики читают параметры транзакции ``app.user_id``, ``app.university_id``
и ``app.bypass_rls``. Мы выставляем их в начале каждой транзакции (событие ``after_begin``),
поэтому контекст не теряется после ``commit()``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import NullPool

from doomich_api.config import get_settings

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


@dataclass(frozen=True)
class RlsContext:
    """Кто выполняет запросы: пользователь, вуз или системная задача (bypass)."""

    user_id: uuid.UUID | None = None
    university_id: uuid.UUID | None = None
    bypass: bool = False

    @classmethod
    def system(cls) -> RlsContext:
        return cls(bypass=True)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        if settings.env == "test":
            # без пула: соединения не привязываются к одному event loop (тестовые клиенты WebSocket)
            _engine = create_async_engine(settings.database_url, poolclass=NullPool)
        else:
            _engine = create_async_engine(settings.database_url, pool_size=settings.db_pool_size, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


@event.listens_for(Session, "after_begin")
def _apply_rls(session: Session, transaction, connection) -> None:
    ctx: RlsContext | None = session.info.get("rls")
    if ctx is None:
        return
    connection.execute(
        text(
            "SELECT set_config('app.user_id', :uid, true), "
            "set_config('app.university_id', :tid, true), "
            "set_config('app.bypass_rls', :bypass, true)"
        ),
        {
            "uid": str(ctx.user_id) if ctx.user_id else "",
            "tid": str(ctx.university_id) if ctx.university_id else "",
            "bypass": "on" if ctx.bypass else "off",
        },
    )


@asynccontextmanager
async def session_scope(ctx: RlsContext) -> AsyncIterator[AsyncSession]:
    """Сессия с RLS-контекстом. Коммит при успешном выходе, откат при исключении."""
    session = get_sessionmaker()()
    session.info["rls"] = ctx
    try:
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    finally:
        await session.close()
