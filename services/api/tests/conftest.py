"""Тестовое окружение: отдельная БД PostgreSQL (с pgvector) и fake-модели вместо GPU.

Нужен запущенный PostgreSQL c расширением pgvector. Адрес суперпользователя задаётся
переменной DOOMICH_TEST_PG (по умолчанию postgresql://postgres@localhost:5432).
Приложение подключается под отдельной ролью без прав суперпользователя — иначе
политики Row-Level Security не применялись бы и не тестировались.
"""

from __future__ import annotations

import base64
import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="doomich-test-"))
_DB = f"doomich_test_{uuid.uuid4().hex[:8]}"
_ROLE = "doomich_test"
_PG = os.environ.get("DOOMICH_TEST_PG", "postgresql://postgres@localhost:5432")
_HOSTPART = _PG.split("@", 1)[1]

os.environ.update(
    {
        "DOOMICH_ENV": "test",
        "DOOMICH_DATABASE_URL": f"postgresql+asyncpg://{_ROLE}:{_ROLE}@{_HOSTPART}/{_DB}",
        "DOOMICH_LLM_PROVIDER": "fake",
        "DOOMICH_EMBEDDINGS_PROVIDER": "fake",
        "DOOMICH_RERANKER_PROVIDER": "fake",
        "DOOMICH_ASR_PROVIDER": "fake",
        "DOOMICH_TTS_PROVIDER": "fake",
        "DOOMICH_EMBEDDING_DIM": "64",
        "DOOMICH_ARGON2_TIME_COST": "1",
        "DOOMICH_ARGON2_MEMORY_KIB": "1024",
        "DOOMICH_ARGON2_PARALLELISM": "1",
        "DOOMICH_STORAGE_DIR": str(_TMP / "storage"),
        "DOOMICH_REGISTRY_DIR": str(_TMP / "registry"),
        "DOOMICH_RUN_TASKS_INLINE": "true",
        "DOOMICH_MASTER_KEY": base64.b64encode(b"t" * 32).decode(),
        "DOOMICH_MESSAGES_PER_DAY_LIMIT": "1000",
    }
)

import psycopg  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


def _admin_exec(sql: str, db: str = "postgres") -> None:
    with psycopg.connect(f"{_PG}/{db}", autocommit=True) as conn:
        conn.execute(sql)


@pytest.fixture(scope="session", autouse=True)
def database():
    with psycopg.connect(f"{_PG}/postgres", autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (_ROLE,)).fetchone()
        if not exists:
            conn.execute(f"CREATE ROLE {_ROLE} LOGIN PASSWORD '{_ROLE}' NOSUPERUSER")
        conn.execute(f"CREATE DATABASE {_DB} OWNER {_ROLE}")
    _admin_exec("CREATE EXTENSION IF NOT EXISTS vector", _DB)

    from alembic import command
    from doomich_api.migrations import alembic_config

    command.upgrade(alembic_config(), "head")
    yield
    from doomich_api.db import dispose_engine  # noqa: F401

    _admin_exec(f"DROP DATABASE IF EXISTS {_DB} WITH (FORCE)")


@pytest.fixture(scope="session")
def app(database):
    from doomich_api.main import create_app

    return create_app()


@pytest.fixture
async def client(app):
    from doomich_api.security import rate_limiter

    rate_limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest.fixture
def providers():
    """Свежие fake-провайдеры на каждый тест (можно подменять сценарий LLM)."""
    from doomich_api.ai import build_providers, set_providers
    from doomich_api.config import get_settings

    fresh = build_providers(get_settings())
    set_providers(fresh)
    yield fresh
    set_providers(None)


class Tenant:
    def __init__(self, university_id: uuid.UUID, slug: str, group_id: uuid.UUID, group_code: str):
        self.university_id = university_id
        self.slug = slug
        self.group_id = group_id
        self.group_code = group_code

    async def invites(self, count: int = 1, role: str = "student", max_uses: int = 1) -> list[str]:
        from doomich_api.db import RlsContext, session_scope
        from doomich_api.models import InviteBatch, InviteCode
        from doomich_api.security import invite_code_hash, new_invite_code

        codes = []
        async with session_scope(RlsContext.system()) as session:
            batch = InviteBatch(
                university_id=self.university_id,
                role=role,
                group_id=self.group_id,
                count=count,
                max_uses_per_code=max_uses,
            )
            session.add(batch)
            await session.flush()
            for _ in range(count):
                code = new_invite_code()
                codes.append(code)
                session.add(InviteCode(batch_id=batch.id, code_hash=invite_code_hash(code), max_uses=max_uses))
        return codes


@pytest.fixture
async def tenant(database) -> Tenant:
    from doomich_api.db import RlsContext, session_scope
    from doomich_api.models import StudyGroup, University
    from doomich_api.schedule.service import normalize_group

    slug = f"uni-{uuid.uuid4().hex[:6]}"
    async with session_scope(RlsContext.system()) as session:
        uni = University(
            slug=slug, name="Тестовый университет", timezone="Europe/Moscow", settings={"store_teacher_names": True}
        )
        session.add(uni)
        await session.flush()
        group = StudyGroup(university_id=uni.id, code="ИВТ-21-1", code_norm=normalize_group("ИВТ-21-1"))
        session.add(group)
        await session.flush()
        return Tenant(uni.id, slug, group.id, group.code)


async def register(client: AsyncClient, tenant: Tenant, login: str | None = None, role: str = "student") -> dict:
    code = (await tenant.invites(role=role))[0]
    resp = await client.post(
        "/v1/auth/register",
        json={
            "invite_code": code,
            "login": login or f"Енот{uuid.uuid4().hex[:6]}",
            "password": "очень-надёжный-пароль-1",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    data["headers"] = {"Authorization": f"Bearer {data['access_token']}"}
    return data


def parse_sse(text: str) -> list[tuple[str, dict]]:
    import json

    events = []
    for block in text.strip().split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            events.append((name, data))
    return events
