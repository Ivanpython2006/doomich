"""Чаты: список, история, потоковый ответ (SSE), режим «инкогнито»."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.ai.conversation import PreparedTurn, prepare_turn, run_turn
from doomich_api.api.deps import current_user, user_session
from doomich_api.api.schemas import ChatOut, MessageOut, OkOut
from doomich_api.context import UserContext
from doomich_api.db import utcnow
from doomich_api.models import Chat, Document, Message
from doomich_api.security import get_crypto

router = APIRouter(prefix="/v1", tags=["chats"])
log = logging.getLogger(__name__)


class ChatIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class ChatPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    mode: str = Field(default="text", pattern="^(text|voice)$")


class HistoryItem(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=16000)


class IncognitoIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=60)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    mode: str = Field(default="text", pattern="^(text|voice)$")


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _chat_out(user: UserContext, chat: Chat) -> ChatOut:
    title = get_crypto().decrypt_text(user.wrapped_dek, user.user_id, chat.title_enc, f"chat:{chat.id}")
    return ChatOut(
        id=chat.id,
        title=title,
        document_ids=[uuid.UUID(d) for d in chat.document_ids or []],
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        expires_at=chat.expires_at,
    )


async def _check_documents(session: AsyncSession, user: UserContext, ids: list[uuid.UUID]) -> None:
    if not ids:
        return
    found = set(
        (
            await session.execute(select(Document.id).where(Document.id.in_(ids), Document.user_id == user.user_id))
        ).scalars()
    )
    if found != set(ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")


@router.get("/chats", response_model=list[ChatOut])
async def list_chats(
    limit: int = Query(50, le=200),
    before: datetime | None = None,
    user: UserContext = Depends(current_user),
    session: AsyncSession = Depends(user_session),
):
    stmt = select(Chat).where(Chat.user_id == user.user_id)
    if before:
        stmt = stmt.where(Chat.updated_at < before)
    rows = await session.execute(stmt.order_by(Chat.updated_at.desc()).limit(limit))
    return [_chat_out(user, c) for c in rows.scalars()]


@router.post("/chats", response_model=ChatOut, status_code=status.HTTP_201_CREATED)
async def create_chat(
    body: ChatIn, user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)
):
    await _check_documents(session, user, body.document_ids)
    chat = Chat(id=uuid.uuid4(), user_id=user.user_id, document_ids=[str(d) for d in body.document_ids])
    chat.title_enc = get_crypto().encrypt_text(
        user.wrapped_dek,
        user.user_id,
        body.title or ("Новый чат" if user.locale == "ru" else "New chat"),
        f"chat:{chat.id}",
    )
    chat.expires_at = utcnow() + timedelta(days=max(1, user.history_days))
    session.add(chat)
    await session.flush()
    return _chat_out(user, chat)


async def _own_chat(session: AsyncSession, user: UserContext, chat_id: uuid.UUID) -> Chat:
    chat = await session.get(Chat, chat_id)
    if chat is None or chat.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    return chat


@router.patch("/chats/{chat_id}", response_model=ChatOut)
async def patch_chat(
    chat_id: uuid.UUID,
    body: ChatPatch,
    user: UserContext = Depends(current_user),
    session: AsyncSession = Depends(user_session),
):
    chat = await _own_chat(session, user, chat_id)
    if body.title:
        chat.title_enc = get_crypto().encrypt_text(user.wrapped_dek, user.user_id, body.title, f"chat:{chat.id}")
    if body.document_ids is not None:
        await _check_documents(session, user, body.document_ids)
        chat.document_ids = [str(d) for d in body.document_ids]
    return _chat_out(user, chat)


@router.delete("/chats/{chat_id}", response_model=OkOut)
async def delete_chat(
    chat_id: uuid.UUID, user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)
):
    await session.delete(await _own_chat(session, user, chat_id))
    return OkOut()


@router.get("/chats/{chat_id}/messages", response_model=list[MessageOut])
async def list_messages(
    chat_id: uuid.UUID,
    limit: int = Query(100, le=500),
    before: datetime | None = None,
    user: UserContext = Depends(current_user),
    session: AsyncSession = Depends(user_session),
):
    await _own_chat(session, user, chat_id)
    stmt = select(Message).where(Message.chat_id == chat_id)
    if before:
        stmt = stmt.where(Message.created_at < before)
    rows = list((await session.execute(stmt.order_by(Message.created_at.desc()).limit(limit))).scalars())
    crypto = get_crypto()
    return [
        MessageOut(
            id=m.id,
            author=m.author,
            content=crypto.decrypt_text(user.wrapped_dek, user.user_id, m.content_enc, f"msg:{m.id}"),
            citations=m.citations or [],
            mode=m.mode,
            created_at=m.created_at,
        )
        for m in reversed(rows)
    ]


async def _stream(user: UserContext, turn: PreparedTurn, text: str, voice: bool) -> AsyncIterator[str]:
    yield sse("start", {"chat_id": str(turn.chat_id) if turn.chat_id else None})
    try:
        async for event in run_turn(user, turn, text, voice=voice):
            if event.type == "delta":
                yield sse("delta", {"text": event.text})
            elif event.type == "tool":
                yield sse("tool", event.data)
            elif event.type == "citations":
                yield sse("citations", event.data)
            elif event.type == "done":
                yield sse("done", {"text": event.text, **event.data})
    except Exception:
        log.exception("Ошибка генерации ответа")
        yield sse("error", {"message": "Не удалось получить ответ. Попробуйте ещё раз."})


def _sse_response(gen: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/chats/{chat_id}/messages")
async def post_message(chat_id: uuid.UUID, body: MessageIn, user: UserContext = Depends(current_user)):
    turn = await prepare_turn(user, chat_id=chat_id, text=body.text, mode=body.mode)
    return _sse_response(_stream(user, turn, body.text, body.mode == "voice"))


@router.post("/chat/incognito")
async def incognito(body: IncognitoIn, user: UserContext = Depends(current_user)):
    """Ответ без сохранения на сервере: история хранится только на устройстве."""
    turn = await prepare_turn(
        user,
        chat_id=None,
        text=body.text,
        mode=body.mode,
        incognito_history=[h.model_dump() for h in body.history],
        document_ids=body.document_ids,
    )
    return _sse_response(_stream(user, turn, body.text, body.mode == "voice"))
