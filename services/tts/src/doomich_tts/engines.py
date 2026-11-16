"""Движки синтеза речи. Возвращают float32 моно и частоту дискретизации.

* ``sherpa``  — ONNX-модели через sherpa-onnx (VITS/Piper, Kokoro, Matcha): быстро, работает на CPU;
* ``openai``  — внешний OpenAI-совместимый сервер ``/v1/audio/speech`` (например, Qwen3-TTS в vLLM-Omni);
* ``fake``    — тон для тестов.

Какую модель ставить, решает бенчмарк из docs/01-stage-1-design.md: только лицензии,
допускающие коммерческое использование.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from doomich_common.audio import normalize_wav


class Engine(Protocol):
    def synthesize(self, text: str, *, speaker: int | str | None, speed: float) -> tuple[np.ndarray, int]: ...


class FakeEngine:
    def __init__(self, sample_rate: int = 22050) -> None:
        self.sample_rate = sample_rate

    def synthesize(self, text, *, speaker, speed):
        duration = min(5.0, 0.06 * max(1, len(text)) / max(speed, 0.1))
        t = np.arange(int(self.sample_rate * duration)) / self.sample_rate
        return (0.1 * np.sin(2 * math.pi * 330 * t)).astype(np.float32), self.sample_rate


class SherpaEngine:
    def __init__(self, model_dir: str, *, model_type: str = "vits", threads: int = 2, provider: str = "cpu") -> None:
        import sherpa_onnx

        base = Path(model_dir)
        tokens = str(base / "tokens.txt")
        data_dir = str(base / "espeak-ng-data") if (base / "espeak-ng-data").exists() else ""
        model_cfg: dict[str, Any] = {"num_threads": threads, "provider": provider}
        if model_type == "vits":
            model_cfg["vits"] = sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(next(base.glob("*.onnx"))), tokens=tokens, data_dir=data_dir
            )
        elif model_type == "kokoro":
            model_cfg["kokoro"] = sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=str(base / "model.onnx"), voices=str(base / "voices.bin"), tokens=tokens, data_dir=data_dir
            )
        elif model_type == "matcha":
            model_cfg["matcha"] = sherpa_onnx.OfflineTtsMatchaModelConfig(
                acoustic_model=str(base / "model.onnx"),
                vocoder=str(base / "vocoder.onnx"),
                tokens=tokens,
                data_dir=data_dir,
            )
        else:
            raise ValueError(f"Неизвестный тип модели sherpa-onnx: {model_type}")
        config = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(**model_cfg), max_num_sentences=2)
        self._tts = sherpa_onnx.OfflineTts(config)

    def synthesize(self, text, *, speaker, speed):
        audio = self._tts.generate(text, sid=int(speaker or 0), speed=speed)
        return np.asarray(audio.samples, dtype=np.float32), audio.sample_rate


class OpenAIEngine:
    def __init__(self, base_url: str, model: str, *, api_key: str = "none", default_voice: str = "default") -> None:
        import httpx

        self._client = httpx.Client(timeout=60)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.default_voice = default_voice

    def synthesize(self, text, *, speaker, speed):
        resp = self._client.post(
            f"{self.base_url}/audio/speech",
            json={
                "model": self.model,
                "input": text,
                "voice": speaker or self.default_voice,
                "response_format": "wav",
                "speed": speed,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        resp.raise_for_status()
        samples = normalize_wav(resp.content, target_rate=24000)
        return samples, 24000


def build_engine(spec: dict[str, Any]) -> Engine:
    kind = spec["kind"]
    options = {k: v for k, v in spec.items() if k != "kind"}
    if kind == "fake":
        return FakeEngine(**options)
    if kind == "sherpa":
        return SherpaEngine(**options)
    if kind == "openai":
        return OpenAIEngine(**options)
    raise ValueError(f"Неизвестный движок TTS: {kind}")
