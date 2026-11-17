"""Командная строка: миграции, первый администратор, демо-данные.

doomich-api migrate
doomich-api create-superadmin --login admin
doomich-api create-university --slug demo --name "Демо-университет"
doomich-api create-invites --university demo --count 10
doomich-api seed-demo
doomich-api run-job cleanup
"""

from __future__ import annotations

import asyncio
import getpass
from datetime import UTC, date, datetime, timedelta

import typer
from sqlalchemy import select

app = typer.Typer(help="Управление сервером «Думыча»", no_args_is_help=True)


def _run(coro):
    from doomich_api.db import dispose_engine

    async def wrapper():
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(wrapper())


@app.command()
def migrate(revision: str = "head") -> None:
    """Применить миграции БД."""
    from alembic import command

    from doomich_api.migrations import alembic_config

    command.upgrade(alembic_config(), revision)
    typer.echo("Миграции применены")


@app.command("create-superadmin")
def create_superadmin(login: str = typer.Option(...), password: str | None = None) -> None:
    """Создать суперадминистратора и вывести ссылку для приложения-аутентификатора (TOTP)."""
    from doomich_api.api.admin import create_admin_account
    from doomich_api.db import RlsContext, session_scope

    secret = password or getpass.getpass("Пароль (не короче 12 символов): ")
    if len(secret) < 12:
        raise typer.BadParameter("Пароль слишком короткий")

    async def go():
        async with session_scope(RlsContext.system()) as session:
            _admin, uri = await create_admin_account(session, login, secret, "superadmin", None)
            return uri

    uri = _run(go())
    typer.echo("Добавьте в приложение-аутентификатор (Google Authenticator, Яндекс Ключ и др.):")
    typer.echo(uri)


@app.command("create-university")
def create_university(
    slug: str = typer.Option(...), name: str = typer.Option(...), timezone: str = "Europe/Moscow"
) -> None:
    from doomich_api.db import RlsContext, session_scope
    from doomich_api.models import University

    async def go():
        async with session_scope(RlsContext.system()) as session:
            session.add(University(slug=slug, name=name, timezone=timezone, settings={}))

    _run(go())
    typer.echo(f"Вуз {slug} создан")


@app.command("create-invites")
def create_invites(
    university: str = typer.Option(..., help="slug вуза"),
    count: int = 10,
    role: str = "student",
    group: str | None = None,
    days: int = 60,
) -> None:
    """Выпустить коды приглашения (печатаются один раз)."""
    from doomich_api.db import RlsContext, session_scope
    from doomich_api.models import InviteBatch, InviteCode, StudyGroup, University
    from doomich_api.schedule.service import normalize_group
    from doomich_api.security import invite_code_hash, new_invite_code

    async def go():
        async with session_scope(RlsContext.system()) as session:
            uni = (await session.execute(select(University).where(University.slug == university))).scalar_one()
            group_id = None
            if group:
                g = (
                    await session.execute(
                        select(StudyGroup).where(
                            StudyGroup.university_id == uni.id, StudyGroup.code_norm == normalize_group(group)
                        )
                    )
                ).scalar_one_or_none()
                if g is None:
                    g = StudyGroup(university_id=uni.id, code=group, code_norm=normalize_group(group))
                    session.add(g)
                    await session.flush()
                group_id = g.id
            batch = InviteBatch(
                university_id=uni.id,
                role=role,
                group_id=group_id,
                count=count,
                expires_at=datetime.now(UTC) + timedelta(days=days),
            )
            session.add(batch)
            await session.flush()
            codes = []
            for _ in range(count):
                code = new_invite_code()
                codes.append(code)
                session.add(InviteCode(batch_id=batch.id, code_hash=invite_code_hash(code)))
            return codes

    for code in _run(go()):
        typer.echo(code)


@app.command("seed-demo")
def seed_demo() -> None:
    """Демо-вуз, группа, неделя расписания и коды приглашения — для локальной разработки."""
    from doomich_api.db import RlsContext, session_scope
    from doomich_api.models import InviteBatch, InviteCode, StudyGroup, University
    from doomich_api.schedule.importers import EventDraft, ImportResult
    from doomich_api.schedule.service import apply_import, normalize_group, tz_of
    from doomich_api.security import invite_code_hash, new_invite_code

    async def go():
        async with session_scope(RlsContext.system()) as session:
            uni = (await session.execute(select(University).where(University.slug == "demo"))).scalar_one_or_none()
            if uni is None:
                uni = University(
                    slug="demo",
                    name="Демо-университет",
                    timezone="Europe/Moscow",
                    settings={"store_teacher_names": False, "features": {"lectures": True}},
                )
                session.add(uni)
                await session.flush()
            group = StudyGroup(university_id=uni.id, code="ДМ-26-1", code_norm=normalize_group("ДМ-26-1"))
            existing = (
                await session.execute(
                    select(StudyGroup).where(
                        StudyGroup.university_id == uni.id, StudyGroup.code_norm == group.code_norm
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(group)
                await session.flush()
            else:
                group = existing
            tz = tz_of(uni)
            monday = date.today() - timedelta(days=date.today().weekday())
            subjects = ["Математический анализ", "Программирование", "Физика", "История", "Английский язык"]
            drafts = []
            for day in range(5):
                for slot, (h, m) in enumerate([(9, 0), (10, 40), (12, 40)]):
                    start = datetime.combine(monday + timedelta(days=day), datetime.min.time(), tz).replace(
                        hour=h, minute=m
                    )
                    drafts.append(
                        EventDraft(
                            group=group.code,
                            starts_at=start,
                            ends_at=start + timedelta(minutes=90),
                            subject=subjects[(day + slot) % 5],
                            kind="лекция" if slot == 0 else "практика",
                            room=f"{3 + slot}0{day + 1}",
                            building="А",
                        )
                    )
            await apply_import(session, uni, ImportResult(events=drafts), filename="seed-demo")
            batch = InviteBatch(
                university_id=uni.id,
                role="student",
                group_id=group.id,
                count=5,
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
            session.add(batch)
            await session.flush()
            codes = []
            for _ in range(5):
                code = new_invite_code()
                codes.append(code)
                session.add(InviteCode(batch_id=batch.id, code_hash=invite_code_hash(code)))
            return codes

    typer.echo("Демо-данные созданы. Коды приглашения:")
    for code in _run(go()):
        typer.echo(f"  {code}")


@app.command("run-job")
def run_job(name: str) -> None:
    """Выполнить фоновую задачу сейчас: cleanup | sync-schedules."""
    from doomich_api import jobs

    func = {"cleanup": jobs.cleanup, "sync-schedules": lambda: jobs.sync_schedules(force=True)}[name]
    typer.echo(_run(func()))


if __name__ == "__main__":
    app()
