"""Сервис распознавания речи.

Конфигурация движков — JSON в DOOMICH_ASR_ENGINES, например::

    [{"kind": "gigaam", "model_dir": "/models/gigaam-v3-ctc", "model_type": "ctc"},
     {"kind": "whisper", "model": "/models/whisper-large-v3-turbo-ct2", "device": "cuda", "compute_type": "float16"}]

Первый движок, поддерживающий язык запроса, обрабатывает его. Если язык не указан и есть
Whisper, он определяет язык. Дообученные модели вуза берутся из реестра моделей (kind=asr):
параметр ``tenant`` в запросе выбирает модель вуза, если она активирована.

Звук обрабатывается в памяти и не сохраняется.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from functools import lru_cache
from typing import Any

import numpy as np
from doomich_common.audio import AudioError, decode_any, split_on_silence
from doomich_common.registry import ModelKind, ModelRegistry, RegistryError
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic_settings import BaseSettings, SettingsConfigDict

from doomich_asr.engines import Engine, Result, WhisperEngine, build_engine

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOOMICH_ASR_", extra="ignore")

    engines: str = '[{"kind": "fake"}]'
    registry_dir: str = "./registry"
    max_seconds: int = 3 * 3600
    segment_seconds: float = 25.0
    workers: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()


class Router:
    """Выбор движка по языку и вузу. Модели вузов подгружаются лениво и кэшируются."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engines: list[Engine] = [build_engine(spec) for spec in json.loads(settings.engines)]
        if not self.engines:
            raise ValueError("Не задан ни один движок ASR (DOOMICH_ASR_ENGINES)")
        self._tenant_cache: dict[str, tuple[str, Engine]] = {}
        self._semaphore = asyncio.Semaphore(settings.workers)

    def detector(self) -> WhisperEngine | None:
        return next((e for e in self.engines if isinstance(e, WhisperEngine)), None)

    def tenant_engine(self, tenant: str | None) -> Engine | None:
        if not tenant:
            return None
        try:
            manifest = ModelRegistry(self.settings.registry_dir).active(tenant, ModelKind.ASR, fallback_global=False)
        except RegistryError:
            return None
        if manifest is None:
            return None
        cached = self._tenant_cache.get(tenant)
        if cached and cached[0] == manifest.version:
            return cached[1]
        registry = ModelRegistry(self.settings.registry_dir)
        fmt = manifest.params.get("format", "hf_ctc")
        path = str(registry.artifact_path(manifest, "model"))
        spec = {"kind": "whisper", "model": path} if fmt == "ctranslate2" else {"kind": "hf_ctc", "model_dir": path}
        spec["languages"] = manifest.params.get("languages", ["ru"])
        engine = build_engine(spec)
        self._tenant_cache[tenant] = (manifest.version, engine)
        log.info("Загружена модель ASR вуза %s версии %s", tenant, manifest.version)
        return engine

    def pick(self, language: str | None, tenant: str | None) -> Engine:
        custom = self.tenant_engine(tenant)
        if custom is not None and (language is None or language in custom.languages):
            return custom
        for engine in self.engines:
            if language is None or language in engine.languages:
                return engine
        return self.engines[0]

    async def transcribe(self, samples: np.ndarray, language: str | None, tenant: str | None) -> Result:
        async with self._semaphore:
            return await asyncio.to_thread(self._transcribe_sync, samples, language, tenant)

    def _transcribe_sync(self, samples: np.ndarray, language: str | None, tenant: str | None) -> Result:
        if language in {None, "", "auto"}:
            detector = self.detector()
            language = detector.detect_language(samples) if detector else None
        engine = self.pick(language, tenant)
        if samples.size <= self.settings.segment_seconds * 16000:
            result = engine.transcribe(samples, language)
            result.language = result.language or language
            return result
        # длинная запись: режем по паузам и склеиваем с таймкодами
        parts: list[dict[str, Any]] = []
        for start, end in split_on_silence(samples, max_segment_s=self.settings.segment_seconds):
            piece = engine.transcribe(samples[start:end], language)
            if piece.text:
                parts.append({"start": round(start / 16000, 2), "end": round(end / 16000, 2), "text": piece.text})
        return Result(" ".join(p["text"] for p in parts), language, parts)


def create_app() -> FastAPI:
    app = FastAPI(title="Думыч ASR", version="0.1.0")
    state: dict[str, Router] = {}

    def router() -> Router:
        if "router" not in state:
            state["router"] = Router(get_settings())
        return state["router"]

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "engines": [e.name for e in router().engines]}

    @app.post("/v1/transcribe")
    async def transcribe(
        file: UploadFile = File(...),
        language: str | None = Form(None),
        tenant: str | None = Form(None),
        format: str | None = Form(None),
    ) -> dict[str, Any]:
        data = await file.read()
        fmt = format or (file.filename or "audio.wav").rsplit(".", 1)[-1].lower()
        try:
            samples = await asyncio.to_thread(decode_any, data, fmt)
        except AudioError as exc:
            raise HTTPException(400, str(exc)) from exc
        duration = samples.size / 16000
        if duration > get_settings().max_seconds:
            raise HTTPException(413, "Запись слишком длинная")
        started = time.perf_counter()
        result = await router().transcribe(samples, language, tenant)
        return {
            "text": result.text,
            "language": result.language,
            "segments": result.segments,
            "duration": round(duration, 2),
            "rtf": round((time.perf_counter() - started) / max(duration, 1e-6), 4),
        }

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("doomich_asr.main:app", host="0.0.0.0", port=8010, access_log=False)  # noqa: S104
