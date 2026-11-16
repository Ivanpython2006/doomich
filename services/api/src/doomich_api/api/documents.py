"""Документы пользователя: загрузка, статус обработки, просмотр фрагмента-источника, удаление."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.api.deps import current_user, user_session
from doomich_api.api.schemas import DocumentOut, OkOut
from doomich_api.config import get_settings
from doomich_api.context import UserContext
from doomich_api.db import RlsContext, session_scope
from doomich_api.models import Chunk, Document
from doomich_api.rag.antivirus import VirusFound, scan
from doomich_api.rag.parsing import ParseError, sniff_mime
from doomich_api.security import get_crypto
from doomich_api.storage import delete_file, save_user_file
from doomich_api.tasks import dispatch

router = APIRouter(prefix="/v1", tags=["documents"])


class ChunkOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    page: int | None
    section: str | None
    body: str


def document_out(user: UserContext | None, doc: Document) -> DocumentOut:
    if doc.title_enc and user is not None and doc.user_id == user.user_id:
        title = get_crypto().decrypt_text(user.wrapped_dek, user.user_id, doc.title_enc, f"doctitle:{doc.id}")
    else:
        title = doc.title or "Документ"
    return DocumentOut(
        id=doc.id,
        title=title,
        owner_type=doc.owner_type,
        mime=doc.mime,
        size_bytes=doc.size_bytes,
        pages=doc.pages,
        status=doc.status,
        error=doc.error,
        created_at=doc.created_at,
    )


async def read_upload(file: UploadFile, max_mb: int) -> bytes:
    data = await file.read(max_mb * 1024 * 1024 + 1)
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Файл больше {max_mb} МБ")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл")
    return data


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload(file: UploadFile, user: UserContext = Depends(current_user)):
    settings = get_settings()
    data = await read_upload(file, settings.max_upload_mb)
    filename = file.filename or "document"
    try:
        mime = sniff_mime(filename, data)
        await scan(data)
    except (ParseError, VirusFound) as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    async with session_scope(user.rls) as session:
        count = (
            await session.execute(select(func.count()).select_from(Document).where(Document.user_id == user.user_id))
        ).scalar_one()
        if count >= settings.max_documents_per_user:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Можно хранить до {settings.max_documents_per_user} документов"
            )
        doc = Document(
            id=uuid.uuid4(),
            owner_type="user",
            user_id=user.user_id,
            university_id=user.university_id,
            mime=mime,
            size_bytes=len(data),
            status="queued",
            storage_key=save_user_file(user.user_id, user.wrapped_dek, data, "docs"),
        )
        doc.title_enc = get_crypto().encrypt_text(user.wrapped_dek, user.user_id, filename[:300], f"doctitle:{doc.id}")
        session.add(doc)
    await dispatch("ingest_document", str(doc.id))
    async with session_scope(user.rls) as session:
        fresh = await session.get(Document, doc.id)
        return document_out(user, fresh)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)):
    rows = await session.execute(
        select(Document).where(Document.user_id == user.user_id).order_by(Document.created_at.desc())
    )
    return [document_out(user, d) for d in rows.scalars()]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID, user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)
):
    doc = await session.get(Document, document_id)
    if doc is None:  # RLS не покажет чужой документ
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    return document_out(user, doc)


@router.get("/documents/{document_id}/chunks/{chunk_id}", response_model=ChunkOut)
async def get_chunk(
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
    user: UserContext = Depends(current_user),
    session: AsyncSession = Depends(user_session),
):
    chunk = await session.get(Chunk, chunk_id)
    if chunk is None or chunk.document_id != document_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Фрагмент не найден")
    return ChunkOut(id=chunk.id, document_id=chunk.document_id, page=chunk.page, section=chunk.section, body=chunk.body)


@router.delete("/documents/{document_id}", response_model=OkOut)
async def delete_document(document_id: uuid.UUID, user: UserContext = Depends(current_user)):
    async with session_scope(user.rls) as session:
        doc = await session.get(Document, document_id)
        if doc is None or doc.user_id != user.user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
        key = doc.storage_key
        await session.delete(doc)  # фрагменты и векторы удаляются каскадно
    delete_file(key)
    return OkOut()


async def org_document_status(document_id: uuid.UUID) -> Document | None:
    async with session_scope(RlsContext.system()) as session:
        return await session.get(Document, document_id)
