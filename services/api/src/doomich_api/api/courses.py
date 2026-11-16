"""Курсы преподавателей (R2): курс, код для студентов, материалы курса в общем поиске."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.api.deps import current_user, user_session
from doomich_api.api.documents import document_out, read_upload
from doomich_api.api.schemas import DocumentOut
from doomich_api.config import get_settings
from doomich_api.context import UserContext
from doomich_api.db import session_scope
from doomich_api.models import Course, CourseMember, Document
from doomich_api.rag.parsing import ParseError, sniff_mime
from doomich_api.security import invite_code_hash, new_invite_code
from doomich_api.storage import save_org_file
from doomich_api.tasks import dispatch

router = APIRouter(prefix="/v1/courses", tags=["courses"])


class CourseIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)


class CourseOut(BaseModel):
    id: uuid.UUID
    title: str
    role: str
    join_code: str | None = None


class JoinIn(BaseModel):
    code: str = Field(max_length=32)


@router.post("", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
async def create_course(
    body: CourseIn, user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)
):
    if user.role != "teacher":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Курсы создают преподаватели")
    code = new_invite_code()
    course = Course(
        university_id=user.university_id, owner_id=user.user_id, title=body.title, join_code_hash=invite_code_hash(code)
    )
    session.add(course)
    await session.flush()
    session.add(CourseMember(course_id=course.id, user_id=user.user_id, role="teacher"))
    return CourseOut(id=course.id, title=course.title, role="teacher", join_code=code)


@router.post("/join", response_model=CourseOut)
async def join(body: JoinIn, user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)):
    course = (
        await session.execute(select(Course).where(Course.join_code_hash == invite_code_hash(body.code)))
    ).scalar_one_or_none()
    if course is None or course.university_id != user.university_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Курс не найден")
    if await session.get(CourseMember, (course.id, user.user_id)) is None:
        session.add(CourseMember(course_id=course.id, user_id=user.user_id, role="student"))
    return CourseOut(id=course.id, title=course.title, role="student")


@router.get("", response_model=list[CourseOut])
async def my_courses(user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)):
    rows = await session.execute(
        select(Course, CourseMember.role)
        .join(CourseMember, CourseMember.course_id == Course.id)
        .where(CourseMember.user_id == user.user_id)
    )
    return [CourseOut(id=c.id, title=c.title, role=role) for c, role in rows]


@router.post("/{course_id}/materials", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_material(course_id: uuid.UUID, file: UploadFile, user: UserContext = Depends(current_user)):
    data = await read_upload(file, get_settings().max_upload_mb)
    try:
        mime = sniff_mime(file.filename or "material", data)
    except ParseError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    async with session_scope(user.rls) as session:
        course = await session.get(Course, course_id)
        if course is None or course.owner_id != user.user_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Материалы добавляет преподаватель курса")
        doc = Document(
            owner_type="course",
            university_id=user.university_id,
            course_id=course.id,
            title=(file.filename or "Материал")[:300],
            mime=mime,
            size_bytes=len(data),
            status="queued",
            storage_key=save_org_file(f"course-{course.id}", data),
        )
        session.add(doc)
        await session.flush()
        doc_id = doc.id
    await dispatch("ingest_document", str(doc_id))
    async with session_scope(user.rls) as session:
        return document_out(user, await session.get(Document, doc_id))
