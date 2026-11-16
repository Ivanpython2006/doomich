"""Зависимости FastAPI: аутентификация пользователей и администраторов, сессии БД."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.context import UserContext, load_user_context
from doomich_api.db import RlsContext, session_scope
from doomich_api.security import decode_access_token, decode_admin_token, rate_limiter

bearer = HTTPBearer(auto_error=False)


def client_key(request: Request) -> str:
    """Ключ для лимитов: IP используется только в памяти процесса и нигде не сохраняется."""
    forwarded = request.headers.get("x-real-ip")
    return forwarded or (request.client.host if request.client else "unknown")


def limit(request: Request, bucket: str, count: int, window_s: float) -> None:
    if not rate_limiter.hit(f"{bucket}:{client_key(request)}", count, window_s):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много запросов, попробуйте позже")


async def system_session() -> AsyncIterator[AsyncSession]:
    async with session_scope(RlsContext.system()) as session:
        yield session


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> UserContext:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход", headers={"WWW-Authenticate": "Bearer"})
    return await user_from_token(creds.credentials)


async def user_from_token(token: str) -> UserContext:
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия истекла, войдите снова") from exc
    async with session_scope(RlsContext(user_id=claims.user_id, university_id=claims.university_id)) as session:
        ctx = await load_user_context(session, claims.user_id)
    if ctx is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Аккаунт недоступен")
    return ctx


async def user_session(user: UserContext = Depends(current_user)) -> AsyncIterator[AsyncSession]:
    async with session_scope(user.rls) as session:
        yield session


@dataclass
class AdminPrincipal:
    id: uuid.UUID
    role: str
    university_id: uuid.UUID | None

    @property
    def is_super(self) -> bool:
        return self.role == "superadmin"

    def check_university(self, university_id: uuid.UUID) -> None:
        if not self.is_super and self.university_id != university_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к этому вузу")

    def require_super(self) -> None:
        if not self.is_super:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права суперадминистратора")


async def current_admin(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> AdminPrincipal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход администратора")
    try:
        payload = decode_admin_token(creds.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия администратора истекла") from exc
    uni = payload.get("uni")
    return AdminPrincipal(uuid.UUID(payload["sub"]), payload["role"], uuid.UUID(uni) if uni else None)
