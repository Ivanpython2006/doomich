"""Регистрация и вход без персональных данных: код приглашения, псевдоним, пароль, код восстановления."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.api.deps import current_user, limit, system_session
from doomich_api.api.schemas import GroupOut, MeOut, OkOut, TokensOut, UniversityOut
from doomich_api.config import get_settings
from doomich_api.context import UserContext
from doomich_api.db import utcnow
from doomich_api.models import (
    AppUser,
    InviteBatch,
    InviteCode,
    LoginChallenge,
    RefreshToken,
    StudyGroup,
    University,
)
from doomich_api.security import (
    create_access_token,
    dummy_verify,
    get_crypto,
    hash_secret,
    invite_code_hash,
    looks_like_real_name,
    new_recovery_code,
    new_refresh_token,
    normalize_login,
    password_problems,
    refresh_expiry,
    sha256_hex,
    suggest_pseudonyms,
    verify_secret,
)

router = APIRouter(prefix="/v1/auth", tags=["auth"])

LOGIN_MIN, LOGIN_MAX = 3, 24
MAX_FAILED = 10
LOCK_MINUTES = 15


class InviteCheckIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)


class InviteCheckOut(BaseModel):
    valid: bool
    university: str | None = None
    role: str | None = None
    group: str | None = None


class LoginCheckIn(BaseModel):
    login: str = Field(min_length=1, max_length=64)


class LoginCheckOut(BaseModel):
    available: bool
    valid: bool
    looks_like_name: bool
    problem: str | None = None


class RegisterIn(BaseModel):
    invite_code: str = Field(min_length=4, max_length=32)
    login: str = Field(min_length=LOGIN_MIN, max_length=LOGIN_MAX)
    password: str = Field(min_length=10, max_length=256)
    locale: str = Field(default="ru", pattern="^(ru|en)$")


class LoginIn(BaseModel):
    login: str = Field(max_length=64)
    password: str = Field(max_length=256)


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=200)


class RecoverIn(BaseModel):
    login: str = Field(max_length=64)
    recovery_code: str = Field(max_length=64)
    new_password: str = Field(min_length=10, max_length=256)


class PasswordIn(BaseModel):
    old_password: str = Field(max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


def _login_problem(login: str) -> str | None:
    stripped = login.strip()
    if not LOGIN_MIN <= len(stripped) <= LOGIN_MAX:
        return f"Псевдоним должен быть от {LOGIN_MIN} до {LOGIN_MAX} символов"
    if not all(ch.isalnum() or ch in "_-." for ch in stripped):
        return "Допустимы буквы, цифры, «_», «-» и «.»"
    return None


async def _find_invite(session: AsyncSession, code: str) -> tuple[InviteCode, InviteBatch] | None:
    row = (
        await session.execute(
            select(InviteCode, InviteBatch)
            .join(InviteBatch, InviteCode.batch_id == InviteBatch.id)
            .where(InviteCode.code_hash == invite_code_hash(code))
        )
    ).first()
    if row is None:
        return None
    invite, batch = row
    if invite.revoked or batch.revoked or invite.uses >= invite.max_uses:
        return None
    if batch.expires_at and batch.expires_at < utcnow():
        return None
    return invite, batch


async def me_out(session: AsyncSession, user: AppUser) -> MeOut:
    university = await session.get(University, user.university_id)
    group = await session.get(StudyGroup, user.group_id) if user.group_id else None
    features = (university.settings or {}).get("features", {}) if university else {}
    return MeOut(
        id=user.id,
        login=user.login,
        role=user.role,
        locale=user.locale,
        history_days=user.history_days,
        university=UniversityOut(
            id=university.id, slug=university.slug, name=university.name, timezone=university.timezone
        ),
        group=GroupOut(id=group.id, code=group.code, name=group.name, faculty=group.faculty) if group else None,
        created_on=user.created_on,
        features={
            "lectures": bool(features.get("lectures", True)),
            "navigation": bool(features.get("navigation", False)),
            "courses": bool(features.get("courses", False)),
            "wakeword": bool(features.get("wakeword", False)),
        },
    )


async def _issue_tokens(session: AsyncSession, user: AppUser, family: uuid.UUID | None = None) -> tuple[str, str]:
    token, token_hash = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id, token_hash=token_hash, family_id=family or uuid.uuid4(), expires_at=refresh_expiry()
        )
    )
    return create_access_token(user.id, user.university_id, user.role), token


@router.get("/pseudonyms")
async def pseudonyms(locale: str = "ru") -> dict[str, list[str]]:
    return {"suggestions": suggest_pseudonyms(locale)}


@router.post("/check-login", response_model=LoginCheckOut)
async def check_login(body: LoginCheckIn, request: Request, session: AsyncSession = Depends(system_session)):
    limit(request, "check-login", 60, 60)
    problem = _login_problem(body.login)
    exists = (
        await session.execute(select(AppUser.id).where(AppUser.login_norm == normalize_login(body.login)))
    ).first()
    return LoginCheckOut(
        available=exists is None,
        valid=problem is None,
        looks_like_name=looks_like_real_name(body.login),
        problem=problem,
    )


@router.post("/invite/check", response_model=InviteCheckOut)
async def check_invite(body: InviteCheckIn, request: Request, session: AsyncSession = Depends(system_session)):
    limit(request, "invite", 20, 60)
    found = await _find_invite(session, body.code)
    if found is None:
        return InviteCheckOut(valid=False)
    _invite, batch = found
    university = await session.get(University, batch.university_id)
    group = await session.get(StudyGroup, batch.group_id) if batch.group_id else None
    return InviteCheckOut(valid=True, university=university.name, role=batch.role, group=group.code if group else None)


@router.post("/register", response_model=TokensOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, request: Request, session: AsyncSession = Depends(system_session)):
    limit(request, "register", 10, 3600)
    if problem := _login_problem(body.login):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    if problems := password_problems(body.password):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problems[0])
    found = await _find_invite(session, body.invite_code)
    if found is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Код приглашения недействителен или уже использован")
    invite, batch = found
    login_norm = normalize_login(body.login)
    if (await session.execute(select(AppUser.id).where(AppUser.login_norm == login_norm))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой псевдоним уже занят")

    # атомарно «тратим» код: защита от гонки двух регистраций по одному коду
    used = await session.execute(
        update(InviteCode)
        .where(InviteCode.id == invite.id, InviteCode.uses < InviteCode.max_uses)
        .values(uses=InviteCode.uses + 1)
    )
    if used.rowcount != 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Код приглашения уже использован")

    recovery = new_recovery_code()
    user_id = uuid.uuid4()
    user = AppUser(
        id=user_id,
        university_id=batch.university_id,
        login=body.login.strip(),
        login_norm=login_norm,
        password_hash=hash_secret(body.password),
        recovery_hash=hash_secret(recovery.replace("-", "")),
        role=batch.role,
        group_id=batch.group_id,
        locale=body.locale,
        history_days=get_settings().default_history_days,
        wrapped_dek=get_crypto().new_wrapped_dek(user_id),
    )
    session.add(user)
    await session.flush()
    access, refresh = await _issue_tokens(session, user)
    return TokensOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=get_settings().access_token_ttl_s,
        user=await me_out(session, user),
        recovery_code=recovery,
    )


@router.post("/login", response_model=TokensOut)
async def login(body: LoginIn, request: Request, session: AsyncSession = Depends(system_session)):
    limit(request, "login", 20, 300)
    user = (
        await session.execute(select(AppUser).where(AppUser.login_norm == normalize_login(body.login)))
    ).scalar_one_or_none()
    if user is None:
        dummy_verify()  # одинаковое время ответа — нельзя перебором узнать, есть ли псевдоним
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный псевдоним или пароль")
    if user.disabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Аккаунт заблокирован")
    if user.locked_until and user.locked_until > utcnow():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток, попробуйте позже")
    if not verify_secret(user.password_hash, body.password):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED:
            user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный псевдоним или пароль")
    user.failed_logins = 0
    user.locked_until = None
    user.last_seen_on = utcnow().date()
    access, refresh = await _issue_tokens(session, user)
    return TokensOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=get_settings().access_token_ttl_s,
        user=await me_out(session, user),
    )


@router.post("/refresh", response_model=TokensOut)
async def refresh(body: RefreshIn, request: Request, session: AsyncSession = Depends(system_session)):
    limit(request, "refresh", 60, 60)
    token = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(body.refresh_token)))
    ).scalar_one_or_none()
    if token is None or token.expires_at < utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия истекла, войдите снова")
    if token.revoked_at is not None:
        # повторное использование старого токена — признак кражи: отзываем всю цепочку
        await session.execute(
            update(RefreshToken).where(RefreshToken.family_id == token.family_id).values(revoked_at=utcnow())
        )
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия отозвана, войдите снова")
    user = await session.get(AppUser, token.user_id)
    if user is None or user.disabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Аккаунт недоступен")
    token.revoked_at = utcnow()
    user.last_seen_on = utcnow().date()
    access, new_refresh = await _issue_tokens(session, user, family=token.family_id)
    return TokensOut(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=get_settings().access_token_ttl_s,
        user=await me_out(session, user),
    )


@router.post("/logout", response_model=OkOut)
async def logout(body: RefreshIn, session: AsyncSession = Depends(system_session)):
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == sha256_hex(body.refresh_token))
        .values(revoked_at=utcnow())
    )
    return OkOut()


@router.post("/recover", response_model=TokensOut)
async def recover(body: RecoverIn, request: Request, session: AsyncSession = Depends(system_session)):
    limit(request, "recover", 5, 3600)
    if problems := password_problems(body.new_password):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problems[0])
    user = (
        await session.execute(select(AppUser).where(AppUser.login_norm == normalize_login(body.login)))
    ).scalar_one_or_none()
    code = "".join(ch for ch in body.recovery_code.upper() if ch.isalnum())
    if user is None or not verify_secret(user.recovery_hash, code):
        if user is None:
            dummy_verify()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный псевдоним или код восстановления")
    recovery = new_recovery_code()
    user.password_hash = hash_secret(body.new_password)
    user.recovery_hash = hash_secret(recovery.replace("-", ""))
    user.failed_logins = 0
    user.locked_until = None
    await session.execute(update(RefreshToken).where(RefreshToken.user_id == user.id).values(revoked_at=utcnow()))
    access, refresh_token = await _issue_tokens(session, user)
    return TokensOut(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=get_settings().access_token_ttl_s,
        user=await me_out(session, user),
        recovery_code=recovery,
    )


@router.post("/password", response_model=OkOut)
async def change_password(
    body: PasswordIn, user: UserContext = Depends(current_user), session: AsyncSession = Depends(system_session)
):
    if problems := password_problems(body.new_password):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problems[0])
    record = await session.get(AppUser, user.user_id)
    if record is None or not verify_secret(record.password_hash, body.old_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный текущий пароль")
    record.password_hash = hash_secret(body.new_password)
    return OkOut()


# ------------------------------------------------------------------ вход на ПК по QR (R2.0)
class QrStartOut(BaseModel):
    challenge_id: uuid.UUID
    secret: str
    expires_at: datetime


class QrApproveIn(BaseModel):
    secret: str = Field(max_length=128)


class QrPollIn(BaseModel):
    challenge_id: uuid.UUID
    secret: str = Field(max_length=128)


@router.post("/qr/start", response_model=QrStartOut)
async def qr_start(request: Request, session: AsyncSession = Depends(system_session)):
    limit(request, "qr", 20, 300)
    secret = secrets.token_urlsafe(24)
    challenge = LoginChallenge(secret_hash=sha256_hex(secret), expires_at=datetime.now(UTC) + timedelta(minutes=3))
    session.add(challenge)
    await session.flush()
    return QrStartOut(challenge_id=challenge.id, secret=secret, expires_at=challenge.expires_at)


@router.post("/qr/approve", response_model=OkOut)
async def qr_approve(
    body: QrApproveIn, user: UserContext = Depends(current_user), session: AsyncSession = Depends(system_session)
):
    challenge = (
        await session.execute(select(LoginChallenge).where(LoginChallenge.secret_hash == sha256_hex(body.secret)))
    ).scalar_one_or_none()
    if challenge is None or challenge.expires_at < utcnow() or challenge.consumed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Код устарел, обновите QR на компьютере")
    challenge.approved_user_id = user.user_id
    return OkOut()


@router.post("/qr/poll", response_model=TokensOut | None)
async def qr_poll(body: QrPollIn, session: AsyncSession = Depends(system_session)):
    challenge = await session.get(LoginChallenge, body.challenge_id)
    if challenge is None or challenge.secret_hash != sha256_hex(body.secret) or challenge.expires_at < utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Код устарел")
    if challenge.approved_user_id is None or challenge.consumed:
        return None
    challenge.consumed = True
    user = await session.get(AppUser, challenge.approved_user_id)
    access, refresh_token = await _issue_tokens(session, user)
    return TokensOut(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=get_settings().access_token_ttl_s,
        user=await me_out(session, user),
    )
