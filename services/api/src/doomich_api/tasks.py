"""Celery: очередь фоновых задач и расписание периодических работ.

Запуск воркера::

    celery -A doomich_api.tasks worker -l info -Q default,heavy
    celery -A doomich_api.tasks beat -l info
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from celery import Celery

from doomich_api import jobs
from doomich_api.config import get_settings

settings = get_settings()
celery_app = Celery("doomich", broker=settings.redis_url, backend=None)
celery_app.conf.update(
    task_default_queue="default",
    task_routes={"doomich.process_lecture": {"queue": "heavy"}},
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "sync-schedules": {"task": "doomich.sync_schedules", "schedule": 3600.0},
        "cleanup": {"task": "doomich.cleanup", "schedule": 6 * 3600.0},
    },
)


def _run(coro) -> Any:
    from doomich_api.db import dispose_engine

    async def wrapper():
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(wrapper())


@celery_app.task(name="doomich.ingest_document", autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=3)
def ingest_document(document_id: str) -> str:
    return _run(jobs.ingest_document(uuid.UUID(document_id)))


@celery_app.task(name="doomich.process_lecture", time_limit=3 * 3600)
def process_lecture(lecture_id: str) -> str:
    return _run(jobs.process_lecture(uuid.UUID(lecture_id)))


@celery_app.task(name="doomich.sync_schedules")
def sync_schedules() -> list[dict]:
    return _run(jobs.sync_schedules())


@celery_app.task(name="doomich.cleanup")
def cleanup() -> dict[str, int]:
    return _run(jobs.cleanup())


async def dispatch(task: str, *args: str) -> None:
    """Поставить задачу в очередь или (dev/тесты) выполнить сразу."""
    if get_settings().run_tasks_inline:
        func = {"ingest_document": jobs.ingest_document, "process_lecture": jobs.process_lecture}[task]
        await func(*(uuid.UUID(a) for a in args))
        return
    celery_app.send_task(f"doomich.{task}", args=list(args))
