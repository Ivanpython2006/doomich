"""Сервис синтеза речи.

Конфигурация — JSON в DOOMICH_TTS_ENGINES (движки) и DOOMICH_TTS_VOICES (голоса)::

    DOOMICH_TTS_ENGINES='{"ru": {"kind": "sherpa", "model_dir": "/models/tts-ru", "model_type": "vits"},
                          "en": {"kind": "sherpa", "model_dir": "/models/kokoro-en", "model_type": "kokoro"}}'
    DOOMICH_TTS_VOICES='[{"id": "ru-1", "engine": "ru", "language": "ru", "speaker": 0, "title": "Голос 1"}]'
"""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from functools import lru_cache
from typing import Any, Literal

from doomich_common.audio import AudioError, encode_with_ffmpeg, float_to_pcm16, pcm16_to_wav
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from doomich_tts.engines import Engine, build_engine
from doomich_tts.textnorm import normalize


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOOMICH_TTS_", extra="ignore")

    engines: str = '{"ru": {"kind": "fake"}, "en": {"kind": "fake"}}'
    voices: str = (
        '[{"id": "ru-default", "engine": "ru", "language": "ru", "speaker": 0, "title": "Думыч"},'
        ' {"id": "en-default", "engine": "en", "language": "en", "speaker": 0, "title": "Doomich"}]'
    )
    cache_size: int = 512
    workers: int = 2
    max_chars: int = 1000


@lru_cache
def get_settings() -> Settings:
    return Settings()


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: str = "ru"
    voice: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    format: Literal["wav", "ogg"] = "wav"
    normalize: bool = True


class Synthesizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engines: dict[str, Engine] = {
            name: build_engine(spec) for name, spec in json.loads(settings.engines).items()
        }
        self.voices: list[dict[str, Any]] = json.loads(settings.voices)
        self._cache: OrderedDict[tuple, tuple[bytes, int]] = OrderedDict()
        self._semaphore = asyncio.Semaphore(settings.workers)

    def voice_for(self, language: str, voice_id: str | None) -> dict[str, Any]:
        if voice_id:
            for voice in self.voices:
                if voice["id"] == voice_id:
                    return voice
        lang = language[:2]
        for voice in self.voices:
            if voice.get("language") == lang:
                return voice
        return self.voices[0]

    async def speak(self, body: SpeakIn) -> tuple[bytes, int]:
        voice = self.voice_for(body.language, body.voice)
        text = normalize(body.text, voice.get("language", body.language)) if body.normalize else body.text
        text = text[: self.settings.max_chars]
        key = (text, voice["id"], round(body.speed, 2), body.format)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        engine = self.engines[voice["engine"]]
        async with self._semaphore:
            samples, rate = await asyncio.to_thread(
                engine.synthesize, text, speaker=voice.get("speaker"), speed=body.speed
            )
        pcm = float_to_pcm16(samples)
        audio = (
            pcm16_to_wav(pcm, rate) if body.format == "wav" else await asyncio.to_thread(encode_with_ffmpeg, pcm, rate)
        )
        self._cache[key] = (audio, rate)
        if len(self._cache) > self.settings.cache_size:
            self._cache.popitem(last=False)
        return audio, rate


def create_app() -> FastAPI:
    app = FastAPI(title="Думыч TTS", version="0.1.0")
    state: dict[str, Synthesizer] = {}

    def synth() -> Synthesizer:
        if "s" not in state:
            state["s"] = Synthesizer(get_settings())
        return state["s"]

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "engines": list(synth().engines)}

    @app.get("/v1/voices")
    async def voices() -> list[dict[str, Any]]:
        return [{k: v for k, v in voice.items() if k != "engine"} for voice in synth().voices]

    @app.post("/v1/speak")
    async def speak(body: SpeakIn) -> Response:
        try:
            audio, rate = await synth().speak(body)
        except AudioError as exc:
            raise HTTPException(500, str(exc)) from exc
        media = "audio/wav" if body.format == "wav" else "audio/ogg"
        return Response(audio, media_type=media, headers={"X-Sample-Rate": str(rate)})

    @app.post("/v1/normalize")
    async def normalize_text(body: SpeakIn) -> dict[str, str]:
        return {"text": normalize(body.text, body.language)}

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("doomich_tts.main:app", host="0.0.0.0", port=8020, access_log=False)  # noqa: S104
