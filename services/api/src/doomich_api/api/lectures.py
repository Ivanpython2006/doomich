"""Конспекты лекций (R1.1): загрузка записи → расшифровка → конспект → экспорт."""

from __future__ import annotations

import io
import re
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.api.deps import current_user, user_session
from doomich_api.api.documents import read_upload
from doomich_api.api.schemas import OkOut
from doomich_api.config import get_settings
from doomich_api.context import UserContext
from doomich_api.db import session_scope
from doomich_api.models import Document, Lecture
from doomich_api.security import get_crypto
from doomich_api.storage import delete_file, save_user_file
from doomich_api.tasks import dispatch

router = APIRouter(prefix="/v1/lectures", tags=["lectures"])

Template = Literal["detailed", "short", "glossary", "questions"]


class LectureOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    template: str
    progress: float
    duration_s: float | None = None
    notes: str | None = None
    transcript: str | None = None
    document_id: uuid.UUID | None = None
    error: str | None = None
    created_at: datetime


def _out(user: UserContext, lecture: Lecture, *, full: bool) -> LectureOut:
    crypto = get_crypto()

    def dec(blob: bytes | None, purpose: str) -> str | None:
        return crypto.decrypt_text(user.wrapped_dek, user.user_id, blob, purpose) if blob else None

    return LectureOut(
        id=lecture.id,
        title=dec(lecture.title_enc, f"lecture:{lecture.id}") or "",
        status=lecture.status,
        template=lecture.template,
        progress=lecture.progress,
        duration_s=lecture.duration_s,
        notes=dec(lecture.notes_enc, f"notes:{lecture.id}") if full else None,
        transcript=dec(lecture.transcript_enc, f"transcript:{lecture.id}") if full else None,
        document_id=lecture.document_id,
        error=lecture.error,
        created_at=lecture.created_at,
    )


@router.post("", response_model=LectureOut, status_code=status.HTTP_201_CREATED)
async def upload_lecture(
    file: UploadFile,
    title: str = Form(..., max_length=200),
    template: Template = Form("detailed"),
    teacher_consent: bool = Form(...),
    user: UserContext = Depends(current_user),
):
    if not teacher_consent:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Запись лекции возможна только с разрешения преподавателя")
    data = await read_upload(file, get_settings().max_lecture_mb)
    async with session_scope(user.rls) as session:
        lecture = Lecture(id=uuid.uuid4(), user_id=user.user_id, template=template, status="queued")
        lecture.title_enc = get_crypto().encrypt_text(user.wrapped_dek, user.user_id, title, f"lecture:{lecture.id}")
        lecture.audio_key = save_user_file(user.user_id, user.wrapped_dek, data, "lectures")
        session.add(lecture)
    await dispatch("process_lecture", str(lecture.id))
    async with session_scope(user.rls) as session:
        return _out(user, await session.get(Lecture, lecture.id), full=False)


@router.get("", response_model=list[LectureOut])
async def list_lectures(user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)):
    rows = await session.execute(
        select(Lecture).where(Lecture.user_id == user.user_id).order_by(Lecture.created_at.desc())
    )
    return [_out(user, lec, full=False) for lec in rows.scalars()]


async def _own(session: AsyncSession, user: UserContext, lecture_id: uuid.UUID) -> Lecture:
    lecture = await session.get(Lecture, lecture_id)
    if lecture is None or lecture.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
    return lecture


@router.get("/{lecture_id}", response_model=LectureOut)
async def get_lecture(
    lecture_id: uuid.UUID, user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)
):
    return _out(user, await _own(session, user, lecture_id), full=True)


@router.get("/{lecture_id}/export")
async def export_lecture(
    lecture_id: uuid.UUID,
    format: Literal["md", "docx"] = "md",
    user: UserContext = Depends(current_user),
    session: AsyncSession = Depends(user_session),
):
    out = _out(user, await _own(session, user, lecture_id), full=True)
    if not out.notes:
        raise HTTPException(status.HTTP_409_CONFLICT, "Конспект ещё не готов")
    safe = re.sub(r"[^\w\- ]+", "", out.title)[:60] or "lecture"
    if format == "md":
        return Response(
            out.notes.encode(),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_quote(safe)}.md"},
        )
    return Response(
        markdown_to_docx(out.title, out.notes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_quote(safe)}.docx"},
    )


@router.delete("/{lecture_id}", response_model=OkOut)
async def delete_lecture(
    lecture_id: uuid.UUID, user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)
):
    lecture = await _own(session, user, lecture_id)
    delete_file(lecture.audio_key)
    if lecture.document_id:
        doc = await session.get(Document, lecture.document_id)
        if doc is not None:
            await session.delete(doc)
    await session.delete(lecture)
    return OkOut()


def _quote(name: str) -> str:
    from urllib.parse import quote

    return quote(name)


def markdown_to_docx(title: str, markdown: str) -> bytes:
    """Простая конвертация Markdown → DOCX: заголовки, списки, абзацы, жирный текст."""
    import docx

    document = docx.Document()
    document.add_heading(title, level=0)
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)", stripped)
        if heading:
            document.add_heading(heading.group(2), level=min(len(heading.group(1)), 4))
            continue
        bullet = re.match(r"^[-*+]\s+(.*)", stripped)
        numbered = re.match(r"^\d+[.)]\s+(.*)", stripped)
        paragraph = document.add_paragraph(style="List Bullet" if bullet else "List Number" if numbered else None)
        text = (bullet or numbered).group(1) if (bullet or numbered) else stripped
        for part in re.split(r"(\*\*[^*]+\*\*)", text):
            if part.startswith("**") and part.endswith("**"):
                paragraph.add_run(part[2:-2]).bold = True
            elif part:
                paragraph.add_run(part)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()
