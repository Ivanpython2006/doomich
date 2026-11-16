"""Клиенты сервисов распознавания (ASR) и синтеза (TTS) речи."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import httpx
import numpy as np
from doomich_common.audio import TARGET_SAMPLE_RATE, float_to_pcm16, pcm16_to_wav

from doomich_api.config import Settings


@dataclass
class Transcript:
    text: str
    language: str | None = None
    segments: list[dict] | None = None


class AsrClient(Protocol):
    async def transcribe(self, samples: np.ndarray, *, language: str | None = None) -> Transcript: ...


class TtsClient(Protocol):
    async def speak(
        self, text: str, *, language: str, speed: float = 1.0, voice: str | None = None
    ) -> tuple[bytes, str, int]:
        """Вернуть (аудио, формат, частота)."""
        ...


class HttpAsrClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = settings.asr_base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=300)

    async def transcribe(self, samples: np.ndarray, *, language: str | None = None) -> Transcript:
        wav = pcm16_to_wav(float_to_pcm16(samples), TARGET_SAMPLE_RATE)
        data = {"language": language} if language and language != "auto" else {}
        resp = await self._client.post(
            f"{self.base_url}/v1/transcribe", files={"file": ("audio.wav", wav, "audio/wav")}, data=data
        )
        resp.raise_for_status()
        body = resp.json()
        return Transcript(body.get("text", "").strip(), body.get("language"), body.get("segments"))


class HttpTtsClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = settings.tts_base_url.rstrip("/")
        self.format = settings.tts_format
        self._client = client or httpx.AsyncClient(timeout=60)

    async def speak(self, text, *, language, speed=1.0, voice=None):
        resp = await self._client.post(
            f"{self.base_url}/v1/speak",
            json={"text": text, "language": language, "speed": speed, "voice": voice, "format": self.format},
        )
        resp.raise_for_status()
        rate = int(resp.headers.get("x-sample-rate", "24000"))
        return resp.content, self.format, rate


class FakeAsr:
    """Возвращает заранее заданный текст (тесты) или описание длины записи (демо)."""

    def __init__(self, text: str | None = None) -> None:
        self.text = text

    async def transcribe(self, samples: np.ndarray, *, language: str | None = None) -> Transcript:
        if self.text is not None:
            return Transcript(self.text, language or "ru")
        seconds = samples.size / TARGET_SAMPLE_RATE
        return Transcript(f"(демо-распознавание: {seconds:.1f} с звука)", language or "ru")


class FakeTts:
    """Короткий тон вместо речи: проверяет конвейер без моделей."""

    async def speak(self, text, *, language, speed=1.0, voice=None):
        rate = 16000
        duration = min(2.0, 0.05 * max(1, len(text.split())))
        t = np.arange(int(rate * duration)) / rate
        tone = 0.1 * np.sin(2 * math.pi * 440 * t)
        return pcm16_to_wav(float_to_pcm16(tone.astype(np.float32)), rate), "wav", rate
