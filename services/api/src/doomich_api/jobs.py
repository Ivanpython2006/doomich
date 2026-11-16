"""Фоновые задачи. Вызываются из Celery (tasks.py) или напрямую (dev/тесты, run_tasks_inline)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta

from doomich_common.audio import decode_any, split_on_silence
from sqlalchemy import delete, select

from doomich_api.ai import get_providers
from doomich_api.ai.prompts import NOTES_MAP_PROMPT, NOTES_REDUCE_PROMPT, NOTES_TEMPLATES
from doomich_api.config import get_settings
from doomich_api.db import RlsContext, session_scope, utcnow
from doomich_api.models import (
    AppUser,
    Chat,
    Chunk,
    DailyUsage,
    Document,
    Lecture,
    LoginChallenge,
    RefreshToken,
    ScheduleSource,
)
from doomich_api.rag.chunking import chunk_blocks
from doomich_api.rag.parsing import Block, ParseError, parse_document
from doomich_api.schedule.service import purge_old_changes, sync_source
from doomich_api.security import get_crypto
from doomich_api.storage import delete_file, load_org_file, load_user_file

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ документы
async def ingest_document(document_id: uuid.UUID) -> str:
    settings = get_settings()
    providers = get_providers()
    async with session_scope(RlsContext.system()) as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return "missing"
        doc.status = "processing"
        user = await session.get(AppUser, doc.user_id) if doc.user_id else None
        storage_key = doc.storage_key
        mime = doc.mime
    try:
        data = load_user_file(user.id, user.wrapped_dek, storage_key) if user else load_org_file(storage_key)
        blocks, pages = await asyncio.to_thread(parse_document, data, mime, settings.max_pages_per_document)
        drafts = chunk_blocks(blocks)
        if not drafts:
            raise ParseError("В документе не найден текст")
        vectors = await providers.embedder.embed_documents(
            [f"{d.section}\n{d.body}" if d.section else d.body for d in drafts]
        )
    except ParseError as exc:
        return await _fail_document(document_id, str(exc))
    except Exception as exc:
        log.exception("Ошибка обработки документа %s", document_id)
        return await _fail_document(document_id, f"Не удалось обработать документ: {type(exc).__name__}")

    async with session_scope(RlsContext.system()) as session:
        doc = await session.get(Document, document_id)
        if doc is None:  # удалили, пока обрабатывали
            return "missing"
        await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
        for order, (draft, vector) in enumerate(zip(drafts, vectors, strict=True)):
            session.add(
                Chunk(
                    document_id=doc.id,
                    owner_type=doc.owner_type,
                    user_id=doc.user_id,
                    university_id=doc.university_id,
                    course_id=doc.course_id,
                    ord=order,
                    page=draft.page,
                    section=draft.section,
                    body=draft.body,
                    embed_model=providers.embedder.model_name,
                    embedding=vector,
                )
            )
        doc.status = "ready"
        doc.pages = pages
        doc.error = None
        doc.processed_at = utcnow()
    return "ready"


async def _fail_document(document_id: uuid.UUID, error: str) -> str:
    async with session_scope(RlsContext.system()) as session:
        doc = await session.get(Document, document_id)
        if doc is not None:
            doc.status = "failed"
            doc.error = error[:500]
    return "failed"


async def index_text_document(
    *, user: AppUser, title: str, blocks: list[Block], mime: str = "text/markdown"
) -> uuid.UUID:
    """Проиндексировать уже готовый текст (например, расшифровку лекции) как личный документ."""
    providers = get_providers()
    crypto = get_crypto()
    drafts = chunk_blocks(blocks)
    vectors = await providers.embedder.embed_documents([d.body for d in drafts]) if drafts else []
    async with session_scope(RlsContext.system()) as session:
        doc = Document(
            owner_type="user",
            user_id=user.id,
            university_id=user.university_id,
            mime=mime,
            size_bytes=sum(len(b.text) for b in blocks),
            status="ready",
            storage_key="",
            pages=1,
            processed_at=utcnow(),
        )
        doc.id = uuid.uuid4()
        doc.title_enc = crypto.encrypt_text(user.wrapped_dek, user.id, title, f"doctitle:{doc.id}")
        session.add(doc)
        await session.flush()
        for order, (draft, vector) in enumerate(zip(drafts, vectors, strict=True)):
            session.add(
                Chunk(
                    document_id=doc.id,
                    owner_type="user",
                    user_id=user.id,
                    university_id=user.university_id,
                    ord=order,
                    page=draft.page,
                    section=draft.section,
                    body=draft.body,
                    embed_model=providers.embedder.model_name,
                    embedding=vector,
                )
            )
        return doc.id


# ------------------------------------------------------------------ лекции (R1.1)
def _timecode(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    return f"{minutes:02d}:{sec:02d}"


async def process_lecture(lecture_id: uuid.UUID) -> str:
    settings = get_settings()
    providers = get_providers()
    crypto = get_crypto()
    async with session_scope(RlsContext.system()) as session:
        lecture = await session.get(Lecture, lecture_id)
        if lecture is None or lecture.audio_key is None:
            return "missing"
        user = await session.get(AppUser, lecture.user_id)
        lecture.status = "transcribing"
        audio_key, template = lecture.audio_key, lecture.template
        title = crypto.decrypt_text(user.wrapped_dek, user.id, lecture.title_enc, f"lecture:{lecture.id}")
    try:
        raw = load_user_file(user.id, user.wrapped_dek, audio_key)
        samples = await asyncio.to_thread(decode_any, raw, "auto")
        duration = samples.size / 16000
        if duration > settings.max_lecture_minutes * 60:
            raise ValueError(f"Запись длиннее {settings.max_lecture_minutes} минут")
        segments = split_on_silence(samples)
        lines: list[str] = []
        for index, (start, end) in enumerate(segments):
            piece = await providers.asr.transcribe(samples[start:end], language=None)
            if piece.text:
                lines.append(f"[{_timecode(start / 16000)}] {piece.text}")
            if index % 5 == 0:
                await _lecture_progress(lecture_id, 0.8 * (index + 1) / max(1, len(segments)))
        transcript = "\n".join(lines)
        if not transcript:
            raise ValueError("В записи не удалось распознать речь")

        async with session_scope(RlsContext.system()) as session:
            lecture = await session.get(Lecture, lecture_id)
            lecture.status = "summarizing"
        model = settings.llm_model
        parts = []
        for start in range(0, len(transcript), 6000):
            chunk = transcript[start : start + 6000]
            parts.append(
                await providers.llm.complete(
                    [{"role": "user", "content": NOTES_MAP_PROMPT.format(chunk=chunk)}], model=model, max_tokens=900
                )
            )
        instruction = NOTES_TEMPLATES.get(template, NOTES_TEMPLATES["detailed"])
        notes = await providers.llm.complete(
            [
                {
                    "role": "user",
                    "content": NOTES_REDUCE_PROMPT.format(instruction=instruction, parts="\n\n".join(parts)),
                }
            ],
            model=model,
            max_tokens=2500,
        )
        document_id = await index_text_document(
            user=user,
            title=f"Лекция: {title}",
            blocks=[Block(text=line, section=line[1:6]) for line in lines],
        )
    except Exception as exc:
        log.exception("Ошибка обработки лекции %s", lecture_id)
        async with session_scope(RlsContext.system()) as session:
            lecture = await session.get(Lecture, lecture_id)
            if lecture is not None:
                lecture.status = "failed"
                lecture.error = str(exc)[:500]
        return "failed"

    async with session_scope(RlsContext.system()) as session:
        lecture = await session.get(Lecture, lecture_id)
        lecture.transcript_enc = crypto.encrypt_text(user.wrapped_dek, user.id, transcript, f"transcript:{lecture.id}")
        lecture.notes_enc = crypto.encrypt_text(user.wrapped_dek, user.id, notes, f"notes:{lecture.id}")
        lecture.duration_s = duration
        lecture.document_id = document_id
        lecture.status = "ready"
        lecture.progress = 1.0
        delete_file(lecture.audio_key)  # аудио по умолчанию не храним
        lecture.audio_key = None
    return "ready"


async def _lecture_progress(lecture_id: uuid.UUID, value: float) -> None:
    async with session_scope(RlsContext.system()) as session:
        lecture = await session.get(Lecture, lecture_id)
        if lecture is not None:
            lecture.progress = round(value, 3)


# ------------------------------------------------------------------ расписание
async def sync_schedules(force: bool = False) -> list[dict]:
    results = []
    async with session_scope(RlsContext.system()) as session:
        sources = list(
            (
                await session.execute(
                    select(ScheduleSource).where(
                        ScheduleSource.enabled.is_(True),
                        ScheduleSource.kind.in_(["json", "html", "ics", "excel", "csv"]),
                    )
                )
            ).scalars()
        )
        for source in sources:
            if not (source.config or {}).get("url"):
                continue
            due = source.last_run_at is None or utcnow() - source.last_run_at >= timedelta(hours=source.interval_hours)
            if force or due:
                results.append({"source": str(source.id), **(await sync_source(session, source))})
    return results


# ------------------------------------------------------------------ уборка
async def cleanup() -> dict[str, int]:
    now = utcnow()
    counts = {}
    async with session_scope(RlsContext.system()) as session:
        counts["chats"] = (await session.execute(delete(Chat).where(Chat.expires_at < now))).rowcount
        counts["refresh_tokens"] = (
            await session.execute(delete(RefreshToken).where(RefreshToken.expires_at < now))
        ).rowcount
        counts["login_challenges"] = (
            await session.execute(delete(LoginChallenge).where(LoginChallenge.expires_at < now))
        ).rowcount
        counts["daily_usage"] = (
            await session.execute(delete(DailyUsage).where(DailyUsage.day < (now - timedelta(days=7)).date()))
        ).rowcount
        await purge_old_changes(session)
    return counts
