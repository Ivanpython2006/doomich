"""Сервис определения места в кампусе (R2). Модели и индексы — из реестра моделей (kind=vpr)."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from doomich_common.registry import ModelKind, ModelRegistry, RegistryError
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic_settings import BaseSettings, SettingsConfigDict

from doomich_nav.localizer import Localizer


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOOMICH_NAV_", extra="ignore")

    registry_dir: str = "./registry"
    max_images: int = 8
    max_image_mb: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()


class LocalizerCache:
    def __init__(self, registry_dir: str) -> None:
        self.registry = ModelRegistry(registry_dir)
        self._cache: dict[tuple[str, str], tuple[str, Localizer]] = {}

    def get(self, tenant: str, campus: str) -> Localizer:
        try:
            manifest = self.registry.active(tenant, ModelKind.VPR, campus, fallback_global=False)
        except RegistryError as exc:
            raise HTTPException(404, str(exc)) from exc
        if manifest is None:
            raise HTTPException(404, "Для этого кампуса ещё нет модели навигации")
        cached = self._cache.get((tenant, campus))
        if cached and cached[0] == manifest.version:
            return cached[1]
        directory = self.registry.version_dir(tenant, ModelKind.VPR, campus, manifest.version)
        localizer = Localizer(directory, manifest.params)
        self._cache[(tenant, campus)] = (manifest.version, localizer)
        return localizer


def create_app() -> FastAPI:
    app = FastAPI(title="Думыч Navigation", version="0.1.0")
    cache: dict[str, LocalizerCache] = {}

    def localizers() -> LocalizerCache:
        if "c" not in cache:
            cache["c"] = LocalizerCache(get_settings().registry_dir)
        return cache["c"]

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/locate")
    async def locate(
        tenant: str = Form(...),
        campus: str = Form(...),
        text: str | None = Form(None),
        images: list[UploadFile] | None = File(None),
    ) -> dict[str, Any]:
        settings = get_settings()
        frames = []
        for image in (images or [])[: settings.max_images]:
            data = await image.read(settings.max_image_mb * 1024 * 1024 + 1)
            if len(data) > settings.max_image_mb * 1024 * 1024:
                raise HTTPException(413, "Кадр слишком большой")
            frames.append(data)
        if not frames and not text:
            raise HTTPException(400, "Нужны кадры или описание")
        localizer = localizers().get(tenant, campus)
        return await asyncio.to_thread(localizer.locate, frames, text)

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("doomich_nav.main:app", host="0.0.0.0", port=8030, access_log=False)  # noqa: S104
