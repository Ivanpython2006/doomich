"""Профиль, настройки, удаление аккаунта, группы, обратная связь."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.api.auth import me_out
from doomich_api.api.deps import current_user, system_session, user_session
from doomich_api.api.schemas import GroupOut, MeOut, OkOut
from doomich_api.context import UserContext
from doomich_api.models import AppUser, Chat, Document, Feedback, Lecture, Message, StudyGroup
from doomich_api.schedule.service import normalize_group
from doomich_api.security import get_crypto, verify_secret
from doomich_api.storage import delete_user_tree

router = APIRouter(prefix="/v1", tags=["me"])


class MePatch(BaseModel):
    locale: Literal["ru", "en"] | None = None
    group_id: uuid.UUID | None = None
    clear_group: bool = False
    history_days: Literal[1, 7, 30, 90] | None = None


class DeleteAccountIn(BaseModel):
    password: str = Field(max_length=256)


class FeedbackIn(BaseModel):
    message_id: uuid.UUID | None = None
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=1000)
    include_dialog: bool = False


@router.get("/me", response_model=MeOut)
async def get_me(user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)):
    record = await session.get(AppUser, user.user_id)
    return await me_out(session, record)


@router.patch("/me", response_model=MeOut)
async def patch_me(
    body: MePatch, user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)
):
    record = await session.get(AppUser, user.user_id)
    if body.locale:
        record.locale = body.locale
    if body.history_days:
        record.history_days = body.history_days
    if body.clear_group:
        record.group_id = None
    elif body.group_id:
        group = await session.get(StudyGroup, body.group_id)
        if group is None or group.university_id != user.university_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Группа не найдена")
        record.group_id = group.id
    await session.flush()
    return await me_out(session, record)


@router.delete("/account", response_model=OkOut)
async def delete_account(
    body: DeleteAccountIn, user: UserContext = Depends(current_user), session: AsyncSession = Depends(system_session)
):
    record = await session.get(AppUser, user.user_id)
    if record is None or not verify_secret(record.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный пароль")
    # всё личное удаляется каскадно: чаты, сообщения, документы, фрагменты, лекции
    await session.execute(delete(Document).where(Document.user_id == user.user_id))
    await session.delete(record)
    await session.flush()
    delete_user_tree(user.user_id)
    return OkOut()


@router.get("/groups", response_model=list[GroupOut])
async def groups(q: str = "", user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)):
    stmt = select(StudyGroup).where(StudyGroup.university_id == user.university_id)
    if q.strip():
        stmt = stmt.where(StudyGroup.code_norm.contains(normalize_group(q)))
    rows = await session.execute(stmt.order_by(StudyGroup.code).limit(50))
    return [GroupOut(id=g.id, code=g.code, name=g.name, faculty=g.faculty) for g in rows.scalars()]


@router.post("/feedback", response_model=OkOut)
async def feedback(
    body: FeedbackIn, user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)
):
    snapshot = None
    model_version = None
    if body.message_id:
        message = await session.get(Message, body.message_id)
        if message is None or message.user_id != user.user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Сообщение не найдено")
        model_version = message.model_version
        if body.include_dialog:
            # пользователь сам разрешил приложить диалог к оценке
            crypto = get_crypto()
            previous = (
                await session.execute(
                    select(Message)
                    .where(Message.chat_id == message.chat_id, Message.created_at <= message.created_at)
                    .order_by(Message.created_at.desc())
                    .limit(2)
                )
            ).scalars()
            snapshot = {
                "messages": [
                    {
                        "author": m.author,
                        "content": crypto.decrypt_text(user.wrapped_dek, user.user_id, m.content_enc, f"msg:{m.id}"),
                    }
                    for m in reversed(list(previous))
                ]
            }
    session.add(
        Feedback(
            university_id=user.university_id,
            message_id=body.message_id,
            rating=body.rating,
            comment=body.comment,
            dialog_snapshot=snapshot,
            model_version=model_version,
        )
    )
    return OkOut()


@router.delete("/me/data", response_model=OkOut)
async def delete_my_data(user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)):
    """Удалить чаты, документы и лекции, сохранив аккаунт."""
    await session.execute(delete(Chat).where(Chat.user_id == user.user_id))
    await session.execute(delete(Document).where(Document.user_id == user.user_id))
    await session.execute(delete(Lecture).where(Lecture.user_id == user.user_id))
    delete_user_tree(user.user_id)
    return OkOut()
