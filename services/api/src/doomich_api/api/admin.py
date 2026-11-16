"""Админ-API: вузы, кампусы, группы, коды приглашения, расписание, база знаний, граф кампуса,
реестр моделей, статус системы, журнал действий. Доступ — только через VPN и с 2FA (TOTP)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from doomich_common.registry import ModelKind, ModelRegistry, RegistryError
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.ai import get_providers
from doomich_api.api.deps import AdminPrincipal, current_admin, limit, system_session
from doomich_api.api.documents import document_out, read_upload
from doomich_api.api.schemas import DocumentOut, GroupOut, OkOut
from doomich_api.config import get_settings
from doomich_api.models import (
    AdminUser,
    AppUser,
    AuditLog,
    Building,
    Campus,
    Document,
    Feedback,
    Floor,
    InviteBatch,
    InviteCode,
    NavEdge,
    NavNode,
    ScheduleImport,
    ScheduleSource,
    StudyGroup,
    University,
)
from doomich_api.rag.parsing import ParseError, sniff_mime
from doomich_api.schedule.importers import ImportErrorFatal, template_xlsx
from doomich_api.schedule.service import apply_import, normalize_group, parse_file, sync_source
from doomich_api.security import (
    create_admin_token,
    get_crypto,
    hash_secret,
    invite_code_hash,
    new_invite_code,
    new_totp_secret,
    totp_uri,
    verify_secret,
    verify_totp,
)
from doomich_api.storage import delete_file, save_org_file
from doomich_api.tasks import dispatch

router = APIRouter(prefix="/admin/v1", tags=["admin"])


async def audit(
    session: AsyncSession, admin: AdminPrincipal, action: str, target: str | None = None, **details: Any
) -> None:
    session.add(
        AuditLog(admin_id=admin.id, university_id=admin.university_id, action=action, target=target, details=details)
    )


async def _university(session: AsyncSession, admin: AdminPrincipal, university_id: uuid.UUID) -> University:
    admin.check_university(university_id)
    university = await session.get(University, university_id)
    if university is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вуз не найден")
    return university


# ------------------------------------------------------------------ вход
class AdminLoginIn(BaseModel):
    login: str = Field(max_length=64)
    password: str = Field(max_length=256)
    totp: str = Field(max_length=10)


class AdminLoginOut(BaseModel):
    access_token: str
    role: str
    university_id: uuid.UUID | None


@router.post("/auth/login", response_model=AdminLoginOut)
async def admin_login(body: AdminLoginIn, request: Request, session: AsyncSession = Depends(system_session)):
    limit(request, "admin-login", 10, 300)
    admin = (await session.execute(select(AdminUser).where(AdminUser.login == body.login))).scalar_one_or_none()
    if admin is None or admin.disabled or not verify_secret(admin.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверные данные для входа")
    secret = get_crypto().unseal(admin.totp_secret_enc, f"totp:{admin.id}").decode()
    if not verify_totp(secret, body.totp):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный код из приложения-аутентификатора")
    session.add(AuditLog(admin_id=admin.id, university_id=admin.university_id, action="login"))
    return AdminLoginOut(
        access_token=create_admin_token(admin.id, admin.role, admin.university_id),
        role=admin.role,
        university_id=admin.university_id,
    )


class AdminCreateIn(BaseModel):
    login: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["superadmin", "university_admin"] = "university_admin"
    university_id: uuid.UUID | None = None


@router.post("/admins")
async def create_admin(
    body: AdminCreateIn, admin: AdminPrincipal = Depends(current_admin), session: AsyncSession = Depends(system_session)
):
    admin.require_super()
    created, uri = await create_admin_account(session, body.login, body.password, body.role, body.university_id)
    await audit(session, admin, "admin.create", body.login, role=body.role)
    return {"id": str(created.id), "totp_uri": uri}


async def create_admin_account(
    session: AsyncSession, login: str, password: str, role: str, university_id: uuid.UUID | None
) -> tuple[AdminUser, str]:
    if (await session.execute(select(AdminUser.id).where(AdminUser.login == login))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой администратор уже есть")
    secret = new_totp_secret()
    admin = AdminUser(
        id=uuid.uuid4(), login=login, password_hash=hash_secret(password), role=role, university_id=university_id
    )
    admin.totp_secret_enc = get_crypto().seal(secret.encode(), f"totp:{admin.id}")
    session.add(admin)
    await session.flush()
    return admin, totp_uri(secret, login)


# ------------------------------------------------------------------ вузы и кампусы
class UniversityIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(max_length=255)
    timezone: str = "Europe/Moscow"
    settings: dict[str, Any] = Field(default_factory=dict)


class UniversityPatch(BaseModel):
    name: str | None = None
    timezone: str | None = None
    settings: dict[str, Any] | None = None


class CampusIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(max_length=255)
    address: str | None = Field(default=None, max_length=500)


def _uni_dict(u: University) -> dict[str, Any]:
    return {"id": str(u.id), "slug": u.slug, "name": u.name, "timezone": u.timezone, "settings": u.settings}


@router.get("/universities")
async def list_universities(
    admin: AdminPrincipal = Depends(current_admin), session: AsyncSession = Depends(system_session)
):
    stmt = select(University).order_by(University.name)
    if not admin.is_super:
        stmt = stmt.where(University.id == admin.university_id)
    return [_uni_dict(u) for u in (await session.execute(stmt)).scalars()]


@router.post("/universities", status_code=status.HTTP_201_CREATED)
async def create_university(
    body: UniversityIn, admin: AdminPrincipal = Depends(current_admin), session: AsyncSession = Depends(system_session)
):
    admin.require_super()
    if (await session.execute(select(University.id).where(University.slug == body.slug))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой slug уже занят")
    university = University(slug=body.slug, name=body.name, timezone=body.timezone, settings=body.settings)
    session.add(university)
    await session.flush()
    await audit(session, admin, "university.create", body.slug)
    return _uni_dict(university)


@router.patch("/universities/{university_id}")
async def patch_university(
    university_id: uuid.UUID,
    body: UniversityPatch,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    university = await _university(session, admin, university_id)
    if body.name:
        university.name = body.name
    if body.timezone:
        university.timezone = body.timezone
    if body.settings is not None:
        university.settings = {**(university.settings or {}), **body.settings}
    await audit(session, admin, "university.update", university.slug, changes=body.model_dump(exclude_none=True))
    return _uni_dict(university)


@router.get("/universities/{university_id}/campuses")
async def list_campuses(
    university_id: uuid.UUID,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    await _university(session, admin, university_id)
    rows = await session.execute(select(Campus).where(Campus.university_id == university_id).order_by(Campus.name))
    return [{"id": str(c.id), "slug": c.slug, "name": c.name, "address": c.address} for c in rows.scalars()]


@router.post("/universities/{university_id}/campuses", status_code=status.HTTP_201_CREATED)
async def create_campus(
    university_id: uuid.UUID,
    body: CampusIn,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    await _university(session, admin, university_id)
    campus = Campus(university_id=university_id, slug=body.slug, name=body.name, address=body.address)
    session.add(campus)
    await session.flush()
    await audit(session, admin, "campus.create", body.slug)
    return {"id": str(campus.id), "slug": campus.slug, "name": campus.name}


# ------------------------------------------------------------------ группы
class GroupIn(BaseModel):
    code: str = Field(max_length=64)
    name: str | None = None
    faculty: str | None = None


@router.get("/universities/{university_id}/groups", response_model=list[GroupOut])
async def list_groups(
    university_id: uuid.UUID,
    q: str = "",
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    await _university(session, admin, university_id)
    stmt = select(StudyGroup).where(StudyGroup.university_id == university_id)
    if q:
        stmt = stmt.where(StudyGroup.code_norm.contains(normalize_group(q)))
    rows = await session.execute(stmt.order_by(StudyGroup.code).limit(500))
    return [GroupOut(id=g.id, code=g.code, name=g.name, faculty=g.faculty) for g in rows.scalars()]


@router.post("/universities/{university_id}/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    university_id: uuid.UUID,
    body: GroupIn,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    await _university(session, admin, university_id)
    group = StudyGroup(
        university_id=university_id,
        code=body.code.strip(),
        code_norm=normalize_group(body.code),
        name=body.name,
        faculty=body.faculty,
    )
    session.add(group)
    await session.flush()
    return GroupOut(id=group.id, code=group.code, name=group.name, faculty=group.faculty)


# ------------------------------------------------------------------ коды приглашения
class InviteBatchIn(BaseModel):
    count: int = Field(ge=1, le=2000)
    role: Literal["student", "teacher"] = "student"
    group_id: uuid.UUID | None = None
    max_uses_per_code: int = Field(default=1, ge=1, le=1000)
    expires_days: int | None = Field(default=60, ge=1, le=400)
    note: str | None = Field(default=None, max_length=255)


@router.post("/universities/{university_id}/invite-batches", status_code=status.HTTP_201_CREATED)
async def create_invites(
    university_id: uuid.UUID,
    body: InviteBatchIn,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    """Коды показываются один раз: в БД хранятся только их хэши. Распечатайте листы с QR сразу."""
    await _university(session, admin, university_id)
    if body.group_id:
        group = await session.get(StudyGroup, body.group_id)
        if group is None or group.university_id != university_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Группа не найдена")
    batch = InviteBatch(
        university_id=university_id,
        role=body.role,
        group_id=body.group_id,
        count=body.count,
        max_uses_per_code=body.max_uses_per_code,
        note=body.note,
        created_by=admin.id,
        expires_at=datetime.now(UTC) + timedelta(days=body.expires_days) if body.expires_days else None,
    )
    session.add(batch)
    await session.flush()
    codes = []
    for _ in range(body.count):
        code = new_invite_code()
        codes.append(code)
        session.add(InviteCode(batch_id=batch.id, code_hash=invite_code_hash(code), max_uses=body.max_uses_per_code))
    await audit(session, admin, "invites.create", str(batch.id), count=body.count, role=body.role)
    base = get_settings().public_base_url.rstrip("/")
    return {
        "batch_id": str(batch.id),
        "codes": [{"code": c, "link": f"{base}/invite/{c}", "app_link": f"doomich://invite/{c}"} for c in codes],
    }


@router.get("/universities/{university_id}/invite-batches")
async def list_invites(
    university_id: uuid.UUID,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    await _university(session, admin, university_id)
    used = func.coalesce(func.sum(InviteCode.uses), 0)
    rows = await session.execute(
        select(InviteBatch, used.label("used"))
        .outerjoin(InviteCode, InviteCode.batch_id == InviteBatch.id)
        .where(InviteBatch.university_id == university_id)
        .group_by(InviteBatch.id)
        .order_by(InviteBatch.created_at.desc())
    )
    return [
        {
            "id": str(b.id),
            "role": b.role,
            "group_id": str(b.group_id) if b.group_id else None,
            "count": b.count,
            "activations": int(u),
            "max_uses_per_code": b.max_uses_per_code,
            "note": b.note,
            "expires_at": b.expires_at.isoformat() if b.expires_at else None,
            "revoked": b.revoked,
            "created_at": b.created_at.isoformat(),
        }
        for b, u in rows
    ]


@router.post("/invite-batches/{batch_id}/revoke", response_model=OkOut)
async def revoke_invites(
    batch_id: uuid.UUID, admin: AdminPrincipal = Depends(current_admin), session: AsyncSession = Depends(system_session)
):
    batch = await session.get(InviteBatch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пачка не найдена")
    admin.check_university(batch.university_id)
    batch.revoked = True
    await audit(session, admin, "invites.revoke", str(batch_id))
    return OkOut()


# ------------------------------------------------------------------ расписание
@router.get("/schedule/template")
async def schedule_template(admin: AdminPrincipal = Depends(current_admin)):
    return Response(
        template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=schedule-template.xlsx"},
    )


@router.post("/universities/{university_id}/schedule/import")
async def import_schedule(
    university_id: uuid.UUID,
    file: UploadFile,
    preview: bool = Form(True),
    semester_start: str | None = Form(None),
    group: str | None = Form(None),
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    university = await _university(session, admin, university_id)
    data = await read_upload(file, 20)
    try:
        result = parse_file(
            university, file.filename or "schedule.xlsx", data, {"semester_start": semester_start, "group": group}
        )
    except ImportErrorFatal as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    summary: dict[str, Any] = {
        "events": len(result.events),
        "groups": sorted(result.groups),
        "errors": result.errors[:200],
    }
    if preview:
        return {"preview": True, **summary}
    stats = await apply_import(session, university, result, filename=file.filename)
    await audit(session, admin, "schedule.import", file.filename, **stats)
    return {"preview": False, **summary, "stats": stats}


class SourceIn(BaseModel):
    name: str = Field(max_length=255)
    kind: Literal["json", "html", "ics", "excel", "csv"]
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    interval_hours: int = Field(default=24, ge=1, le=24 * 30)


def _source_dict(s: ScheduleSource) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "kind": s.kind,
        "config": s.config,
        "enabled": s.enabled,
        "interval_hours": s.interval_hours,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "last_status": s.last_status,
        "last_error": s.last_error,
    }


@router.get("/universities/{university_id}/schedule/sources")
async def list_sources(
    university_id: uuid.UUID,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    await _university(session, admin, university_id)
    rows = await session.execute(select(ScheduleSource).where(ScheduleSource.university_id == university_id))
    return [_source_dict(s) for s in rows.scalars()]


@router.post("/universities/{university_id}/schedule/sources", status_code=status.HTTP_201_CREATED)
async def create_source(
    university_id: uuid.UUID,
    body: SourceIn,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    await _university(session, admin, university_id)
    if "url" not in body.config:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "В config нужен url источника")
    source = ScheduleSource(university_id=university_id, **body.model_dump())
    session.add(source)
    await session.flush()
    await audit(session, admin, "schedule.source.create", body.name)
    return _source_dict(source)


@router.delete("/schedule/sources/{source_id}", response_model=OkOut)
async def delete_source(
    source_id: uuid.UUID,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    source = await session.get(ScheduleSource, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Источник не найден")
    admin.check_university(source.university_id)
    await session.delete(source)
    await audit(session, admin, "schedule.source.delete", str(source_id))
    return OkOut()


@router.post("/schedule/sources/{source_id}/sync")
async def sync_now(
    source_id: uuid.UUID,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    source = await session.get(ScheduleSource, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Источник не найден")
    admin.check_university(source.university_id)
    source.last_hash = None  # принудительно
    return await sync_source(session, source)


@router.get("/universities/{university_id}/schedule/imports")
async def list_imports(
    university_id: uuid.UUID,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    await _university(session, admin, university_id)
    rows = await session.execute(
        select(ScheduleImport)
        .where(ScheduleImport.university_id == university_id)
        .order_by(ScheduleImport.created_at.desc())
        .limit(50)
    )
    return [
        {
            "id": str(i.id),
            "filename": i.filename,
            "status": i.status,
            "stats": i.stats,
            "errors": i.errors[:20],
            "created_at": i.created_at.isoformat(),
        }
        for i in rows.scalars()
    ]


# ------------------------------------------------------------------ база знаний вуза
@router.post("/universities/{university_id}/kb", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_kb(
    university_id: uuid.UUID,
    file: UploadFile,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    await _university(session, admin, university_id)
    data = await read_upload(file, 50)
    try:
        mime = sniff_mime(file.filename or "doc", data)
    except ParseError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    doc = Document(
        owner_type="university",
        university_id=university_id,
        title=(file.filename or "Документ")[:300],
        mime=mime,
        size_bytes=len(data),
        status="queued",
        storage_key=save_org_file(f"uni-{university_id}", data),
    )
    session.add(doc)
    await session.flush()
    await audit(session, admin, "kb.upload", doc.title)
    await session.commit()
    await dispatch("ingest_document", str(doc.id))
    await session.refresh(doc)
    return document_out(None, doc)


@router.get("/universities/{university_id}/kb", response_model=list[DocumentOut])
async def list_kb(
    university_id: uuid.UUID,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    await _university(session, admin, university_id)
    rows = await session.execute(
        select(Document)
        .where(Document.university_id == university_id, Document.owner_type == "university")
        .order_by(Document.created_at.desc())
    )
    return [document_out(None, d) for d in rows.scalars()]


@router.delete("/kb/{document_id}", response_model=OkOut)
async def delete_kb(
    document_id: uuid.UUID,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    doc = await session.get(Document, document_id)
    if doc is None or doc.owner_type != "university":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    admin.check_university(doc.university_id)
    delete_file(doc.storage_key)
    await session.delete(doc)
    await audit(session, admin, "kb.delete", doc.title)
    return OkOut()


# ------------------------------------------------------------------ граф кампуса (R2)
class GraphNodeIn(BaseModel):
    key: str = Field(max_length=64)
    kind: Literal["corridor", "room", "stairs", "elevator", "entrance", "poi"]
    name: str | None = None
    room: str | None = None
    x: float
    y: float
    tags: list[str] = Field(default_factory=list)


class GraphFloorIn(BaseModel):
    level: int
    name: str | None = None
    meters_per_px: float | None = None
    nodes: list[GraphNodeIn]


class GraphBuildingIn(BaseModel):
    slug: str
    name: str
    floors: list[GraphFloorIn]


class GraphEdgeIn(BaseModel):
    a: str  # ключ узла
    b: str
    length_m: float | None = None
    kind: Literal["walk", "stairs", "elevator"] = "walk"
    accessible: bool = True


class CampusGraphIn(BaseModel):
    buildings: list[GraphBuildingIn]
    edges: list[GraphEdgeIn]


@router.put("/campuses/{campus_id}/graph")
async def put_graph(
    campus_id: uuid.UUID,
    body: CampusGraphIn,
    admin: AdminPrincipal = Depends(current_admin),
    session: AsyncSession = Depends(system_session),
):
    """Заменить граф кампуса целиком (формат редактора кампуса)."""
    campus = await session.get(Campus, campus_id)
    if campus is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Кампус не найден")
    admin.check_university(campus.university_id)
    await session.execute(delete(Building).where(Building.campus_id == campus_id))
    nodes: dict[str, NavNode] = {}
    for b in body.buildings:
        building = Building(campus_id=campus_id, slug=b.slug, name=b.name)
        session.add(building)
        await session.flush()
        for f in b.floors:
            floor = Floor(building_id=building.id, level=f.level, name=f.name, meters_per_px=f.meters_per_px)
            session.add(floor)
            await session.flush()
            for n in f.nodes:
                if n.key in nodes:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Повторяется ключ узла {n.key}")
                node = NavNode(floor_id=floor.id, **n.model_dump())
                session.add(node)
                nodes[n.key] = node
    await session.flush()
    floors_scale = {}
    for e in body.edges:
        a, b = nodes.get(e.a), nodes.get(e.b)
        if a is None or b is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Ребро ссылается на неизвестный узел {e.a}–{e.b}"
            )
        length = e.length_m
        if length is None:
            scale = floors_scale.get(a.floor_id)
            if scale is None:
                floor = await session.get(Floor, a.floor_id)
                scale = floor.meters_per_px or 0.05
                floors_scale[a.floor_id] = scale
            length = ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5 * scale
        session.add(NavEdge(from_id=a.id, to_id=b.id, length_m=length, kind=e.kind, accessible=e.accessible))
    await audit(session, admin, "campus.graph.replace", campus.slug, nodes=len(nodes), edges=len(body.edges))
    return {"nodes": len(nodes), "edges": len(body.edges)}


# ------------------------------------------------------------------ реестр моделей
class ActivateIn(BaseModel):
    tenant: str
    kind: ModelKind
    scope: str = "default"
    version: str


@router.get("/models")
async def models(admin: AdminPrincipal = Depends(current_admin), session: AsyncSession = Depends(system_session)):
    rows = ModelRegistry(get_settings().registry_dir).summary()
    if not admin.is_super:
        university = await session.get(University, admin.university_id)
        rows = [r for r in rows if r["tenant"] in {university.slug, "_global"}]
    return rows


@router.post("/models/activate")
async def activate_model(
    body: ActivateIn, admin: AdminPrincipal = Depends(current_admin), session: AsyncSession = Depends(system_session)
):
    if not admin.is_super:
        university = await session.get(University, admin.university_id)
        if body.tenant != university.slug:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Можно активировать только модели своего вуза")
    try:
        pointer = ModelRegistry(get_settings().registry_dir).activate(
            body.tenant, body.kind, body.scope, body.version, by=str(admin.id)
        )
    except RegistryError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await audit(session, admin, "model.activate", f"{body.tenant}/{body.kind}/{body.scope}", version=body.version)
    return pointer.model_dump(mode="json")


# ------------------------------------------------------------------ статус и журнал
@router.get("/status")
async def system_status(
    admin: AdminPrincipal = Depends(current_admin), session: AsyncSession = Depends(system_session)
):
    settings = get_settings()
    checks: dict[str, Any] = {}
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
    async with httpx.AsyncClient(timeout=3) as client:
        for name, url in {
            "llm": settings.llm_base_url.removesuffix("/v1") + "/health",
            "asr": settings.asr_base_url + "/healthz",
            "tts": settings.tts_base_url + "/healthz",
            "nav": settings.nav_base_url + "/healthz",
        }.items():
            if getattr(settings, f"{name}_provider", "http") == "fake":
                checks[name] = "fake"
                continue
            try:
                resp = await client.get(url)
                checks[name] = "ok" if resp.status_code < 400 else f"http {resp.status_code}"
            except httpx.HTTPError as exc:
                checks[name] = f"unreachable: {type(exc).__name__}"
    uni_filter = [] if admin.is_super else [Document.university_id == admin.university_id]
    docs = dict(
        (
            await session.execute(select(Document.status, func.count()).where(*uni_filter).group_by(Document.status))
        ).all()
    )
    users_q = select(func.count()).select_from(AppUser)
    if not admin.is_super:
        users_q = users_q.where(AppUser.university_id == admin.university_id)
    feedback_q = select(Feedback.rating, func.count()).group_by(Feedback.rating)
    if not admin.is_super:
        feedback_q = feedback_q.where(Feedback.university_id == admin.university_id)
    return {
        "checks": checks,
        "documents": docs,
        "users": (await session.execute(users_q)).scalar_one(),
        "feedback": {str(k): v for k, v in (await session.execute(feedback_q)).all()},
        "embedder": get_providers().embedder.model_name,
    }


@router.get("/audit")
async def audit_log(
    limit_: int = 100, admin: AdminPrincipal = Depends(current_admin), session: AsyncSession = Depends(system_session)
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit_, 500))
    if not admin.is_super:
        stmt = stmt.where(AuditLog.university_id == admin.university_id)
    return [
        {
            "id": a.id,
            "admin_id": str(a.admin_id) if a.admin_id else None,
            "action": a.action,
            "target": a.target,
            "details": a.details,
            "created_at": a.created_at.isoformat(),
        }
        for a in (await session.execute(stmt)).scalars()
    ]
