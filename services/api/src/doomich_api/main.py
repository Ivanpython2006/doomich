"""Приложение FastAPI."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import text

from doomich_api import __version__
from doomich_api.api import (
    admin,
    auth,
    chats,
    courses,
    documents,
    lectures,
    me,
    models_api,
    nav,
    schedule,
    voice,
)
from doomich_api.config import get_settings
from doomich_api.db import RlsContext, dispose_engine, session_scope

REQUESTS = Counter("doomich_http_requests_total", "HTTP-запросы", ["route", "method", "status"])
LATENCY = Histogram("doomich_http_request_seconds", "Длительность запросов", ["route", "method"])


def configure_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )
    # журнал доступа uvicorn пишет IP-адреса — отключаем, у нас свой журнал без IP
    logging.getLogger("uvicorn.access").disabled = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Думыч API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    access_log = logging.getLogger("doomich.access")

    @app.middleware("http")
    async def observe(request: Request, call_next):
        start = time.perf_counter()
        response: Response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        elapsed = time.perf_counter() - start
        REQUESTS.labels(path, request.method, response.status_code).inc()
        LATENCY.labels(path, request.method).observe(elapsed)
        # без IP, без параметров запроса и без тела — только шаблон маршрута
        access_log.info("%s %s %s %.0fms", request.method, path, response.status_code, elapsed * 1000)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    for module in (auth, me, chats, voice, schedule, documents, lectures, nav, courses, models_api, admin):
        app.include_router(module.router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> dict[str, str]:
        async with session_scope(RlsContext.system()) as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        # закрыто снаружи на уровне Nginx: доступно только из внутренней сети
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
