"""ORM-модели. Персональных данных здесь нет по построению (см. docs/07-privacy-and-registration.md)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from doomich_api.config import get_settings
from doomich_api.db import Base, TimestampMixin, utcnow

EMBEDDING_DIM = get_settings().embedding_dim


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# --------------------------------------------------------------------------- вузы
class University(TimestampMixin, Base):
    """Вуз — арендатор (tenant). Данные разных вузов изолированы."""

    __tablename__ = "universities"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    # store_teacher_names, llm_model, features и т. п.
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    campuses: Mapped[list[Campus]] = relationship(back_populates="university", cascade="all, delete-orphan")


class Campus(TimestampMixin, Base):
    __tablename__ = "campuses"
    __table_args__ = (UniqueConstraint("university_id", "slug"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    university_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(500))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    university: Mapped[University] = relationship(back_populates="campuses")


class StudyGroup(TimestampMixin, Base):
    __tablename__ = "study_groups"
    __table_args__ = (UniqueConstraint("university_id", "code_norm"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    university_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64))
    code_norm: Mapped[str] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(255))
    faculty: Mapped[str | None] = mapped_column(String(255))
    campus_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campuses.id", ondelete="SET NULL"))


# --------------------------------------------------------------------------- аккаунты
class AppUser(Base):
    """Аккаунт без ПД: псевдоним, хэш пароля, роль, группа (по желанию)."""

    __tablename__ = "app_users"

    id: Mapped[uuid.UUID] = uuid_pk()
    university_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    login: Mapped[str] = mapped_column(String(32))
    login_norm: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    recovery_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="student")
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("study_groups.id", ondelete="SET NULL"))
    locale: Mapped[str] = mapped_column(String(8), default="ru")
    history_days: Mapped[int] = mapped_column(Integer, default=90)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    dek_key_version: Mapped[int] = mapped_column(SmallInteger, default=1)
    # только даты, без времени — меньше метаданных о поведении
    created_on: Mapped[date] = mapped_column(Date, default=lambda: utcnow().date())
    last_seen_on: Mapped[date | None] = mapped_column(Date)
    failed_logins: Mapped[int] = mapped_column(SmallInteger, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)

    university: Mapped[University] = relationship()
    group: Mapped[StudyGroup | None] = relationship()


class InviteBatch(TimestampMixin, Base):
    __tablename__ = "invite_batches"

    id: Mapped[uuid.UUID] = uuid_pk()
    university_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16), default="student")
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("study_groups.id", ondelete="SET NULL"))
    count: Mapped[int] = mapped_column(Integer)
    max_uses_per_code: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: Mapped[uuid.UUID] = uuid_pk()
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invite_batches.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    batch: Mapped[InviteBatch] = relationship()


class RefreshToken(TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginChallenge(TimestampMixin, Base):
    """Вход на ПК по QR: ПК показывает код, телефон подтверждает (R2.0)."""

    __tablename__ = "login_challenges"

    id: Mapped[uuid.UUID] = uuid_pk()
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True)
    approved_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class AdminUser(TimestampMixin, Base):
    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = uuid_pk()
    login: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret_enc: Mapped[bytes] = mapped_column(LargeBinary)
    role: Mapped[str] = mapped_column(String(32), default="university_admin")  # или superadmin
    university_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    university_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# --------------------------------------------------------------------------- чаты
class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (Index("ix_chats_user_updated", "user_id", "updated_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"))
    title_enc: Mapped[bytes] = mapped_column(LargeBinary)
    document_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_chat_created", "chat_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    chat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(16))  # user | assistant
    content_enc: Mapped[bytes] = mapped_column(LargeBinary)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    mode: Mapped[str] = mapped_column(String(8), default="text")
    model_version: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Feedback(TimestampMixin, Base):
    """Оценка ответа. Текст диалога сохраняется, только если пользователь сам это разрешил."""

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = uuid_pk()
    university_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(String(1000))
    dialog_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_version: Mapped[str | None] = mapped_column(String(128))


class DailyUsage(Base):
    """Счётчик сообщений за день — для лимитов. Хранится только число, не содержимое."""

    __tablename__ = "daily_usage"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    messages: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- расписание
class ScheduleSource(TimestampMixin, Base):
    __tablename__ = "schedule_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    university_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))  # excel | csv | ics | json | html
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_hash: Mapped[str | None] = mapped_column(String(64))


class ScheduleEvent(Base):
    __tablename__ = "schedule_events"
    __table_args__ = (
        UniqueConstraint("group_id", "uid"),
        Index("ix_schedule_events_group_start", "group_id", "starts_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    university_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("study_groups.id", ondelete="CASCADE"))
    uid: Mapped[str] = mapped_column(String(128))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    subject: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str | None] = mapped_column(String(64))
    room: Mapped[str | None] = mapped_column(String(64))
    building: Mapped[str | None] = mapped_column(String(128))
    # ФИО — персональные данные: сохраняются, только если вуз это разрешил (settings.store_teacher_names)
    teacher: Mapped[str | None] = mapped_column(String(255))
    subgroup: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(String(500))
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schedule_sources.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScheduleChange(Base):
    __tablename__ = "schedule_changes"
    __table_args__ = (Index("ix_schedule_changes_group_created", "group_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("study_groups.id", ondelete="CASCADE"))
    event_uid: Mapped[str] = mapped_column(String(128))
    change: Mapped[str] = mapped_column(String(16))  # added | removed | changed
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScheduleImport(TimestampMixin, Base):
    __tablename__ = "schedule_imports"

    id: Mapped[uuid.UUID] = uuid_pk()
    university_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schedule_sources.id", ondelete="SET NULL"))
    filename: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16))
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


# --------------------------------------------------------------------------- документы
class Course(TimestampMixin, Base):
    """Курс преподавателя (R2): материалы курса доступны его участникам."""

    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = uuid_pk()
    university_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    join_code_hash: Mapped[str] = mapped_column(String(64), unique=True)


class CourseMember(Base):
    __tablename__ = "course_members"

    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), default="student")


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_type: Mapped[str] = mapped_column(String(16), default="user")  # user | university | course
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), index=True)
    university_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("universities.id", ondelete="CASCADE"))
    course_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    title_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # личные документы
    title: Mapped[str | None] = mapped_column(String(500))  # документы вуза и курсов
    mime: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    pages: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[str | None] = mapped_column(String(500))
    storage_key: Mapped[str] = mapped_column(String(255))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Chunk(Base):
    """Фрагмент документа для поиска.

    Текст фрагмента, вектор и полнотекстовый индекс нужны для поиска, поэтому прикладного
    шифрования у них нет — их защищают шифрование диска и RLS (осознанный компромисс).
    """

    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_fts", "fts", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    owner_type: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"))
    university_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    course_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ord: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    embed_model: Mapped[str] = mapped_column(String(128))
    embedding = mapped_column(Vector(EMBEDDING_DIM))
    fts = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('russian', coalesce(section, '') || ' ' || body) || "
            "to_tsvector('english', coalesce(section, '') || ' ' || body)",
            persisted=True,
        ),
    )


# --------------------------------------------------------------------------- лекции (R1.1)
class Lecture(TimestampMixin, Base):
    __tablename__ = "lectures"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), index=True)
    title_enc: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    template: Mapped[str] = mapped_column(String(32), default="detailed")
    duration_s: Mapped[float | None] = mapped_column(Float)
    audio_key: Mapped[str | None] = mapped_column(String(255))
    transcript_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    notes_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    error: Mapped[str | None] = mapped_column(String(500))
    progress: Mapped[float] = mapped_column(Float, default=0.0)


# --------------------------------------------------------------------------- кампус (R2)
class Building(TimestampMixin, Base):
    __tablename__ = "buildings"
    __table_args__ = (UniqueConstraint("campus_id", "slug"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    campus_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campuses.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))


class Floor(Base):
    __tablename__ = "floors"
    __table_args__ = (UniqueConstraint("building_id", "level"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    building_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"))
    level: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(64))
    plan_key: Mapped[str | None] = mapped_column(String(255))
    meters_per_px: Mapped[float | None] = mapped_column(Float)


class NavNode(Base):
    __tablename__ = "nav_nodes"
    __table_args__ = (UniqueConstraint("floor_id", "key"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    floor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("floors.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))  # стабильный ключ из редактора и из эталонных фото
    kind: Mapped[str] = mapped_column(String(16))  # corridor | room | stairs | elevator | entrance | poi
    name: Mapped[str | None] = mapped_column(String(255))
    room: Mapped[str | None] = mapped_column(String(32), index=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)


class NavEdge(Base):
    __tablename__ = "nav_edges"

    id: Mapped[uuid.UUID] = uuid_pk()
    from_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nav_nodes.id", ondelete="CASCADE"), index=True)
    to_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nav_nodes.id", ondelete="CASCADE"), index=True)
    length_m: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(16), default="walk")  # walk | stairs | elevator
    accessible: Mapped[bool] = mapped_column(Boolean, default=True)
