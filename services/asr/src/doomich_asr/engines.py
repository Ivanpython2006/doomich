"""Движки распознавания речи. Каждый принимает float32 моно 16 кГц и возвращает текст.

* ``gigaam``  — GigaAM (Сбер, MIT) в формате ONNX через sherpa-onnx: CTC или RNN-T;
* ``whisper`` — Whisper / дообученные модели в формате CTranslate2 через faster-whisper;
* ``hf_ctc``  — дообученная CTC-модель Hugging Face (выход ML-платформы ``doomich-ml asr``);
* ``openai``  — внешний OpenAI-совместимый сервер ``/v1/audio/transcriptions`` (например, vLLM);
* ``fake``    — для тестов.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from doomich_common.audio import TARGET_SAMPLE_RATE, float_to_pcm16, pcm16_to_wav

log = logging.getLogger(__name__)


@dataclass
class Result:
    text: str
    language: str | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)


class Engine(Protocol):
    name: str
    languages: set[str]

    def transcribe(self, samples: np.ndarray, language: str | None) -> Result: ...


class FakeEngine:
    def __init__(self, text: str = "тестовая расшифровка", languages: set[str] | None = None) -> None:
        self.name = "fake"
        self.text = text
        self.languages = languages or {"ru", "en"}

    def transcribe(self, samples, language):
        return Result(self.text if samples.size else "", language or "ru")


class GigaAmEngine:
    """GigaAM через sherpa-onnx. Файлы модели — из релизов sherpa-onnx или экспорт ``doomich-ml``."""

    def __init__(self, model_dir: str, *, model_type: str = "ctc", threads: int = 4, provider: str = "cpu") -> None:
        import sherpa_onnx

        self.name = "gigaam"
        self.languages = {"ru"}
        base = Path(model_dir)
        tokens = str(base / "tokens.txt")
        if model_type == "ctc":
            self._rec = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
                model=str(next(base.glob("model*.onnx"))), tokens=tokens, num_threads=threads, provider=provider
            )
        else:
            self._rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(next(base.glob("encoder*.onnx"))),
                decoder=str(next(base.glob("decoder*.onnx"))),
                joiner=str(next(base.glob("joiner*.onnx"))),
                tokens=tokens,
                num_threads=threads,
                provider=provider,
                model_type="nemo_transducer",
            )

    def transcribe(self, samples, language):
        stream = self._rec.create_stream()
        stream.accept_waveform(TARGET_SAMPLE_RATE, samples)
        self._rec.decode_stream(stream)
        return Result(stream.result.text.strip(), "ru")


class WhisperEngine:
    def __init__(self, model: str, *, device: str = "auto", compute_type: str = "default", beam_size: int = 5) -> None:
        from faster_whisper import WhisperModel

        self.name = "whisper"
        self.languages = {"ru", "en", "auto"}
        self.beam_size = beam_size
        self._model = WhisperModel(model, device=device, compute_type=compute_type)

    def detect_language(self, samples: np.ndarray) -> str:
        _segments, info = self._model.transcribe(
            samples[: TARGET_SAMPLE_RATE * 30], beam_size=1, without_timestamps=True
        )
        return info.language

    def transcribe(self, samples, language):
        segments, info = self._model.transcribe(
            samples, language=language, beam_size=self.beam_size, vad_filter=True, condition_on_previous_text=False
        )
        parts = [
            {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in segments
            if s.text.strip()
        ]
        return Result(" ".join(p["text"] for p in parts), info.language, parts)


class HfCtcEngine:
    """CTC-модель в формате Hugging Face (Wav2Vec2ForCTC и совместимые) — результат дообучения."""

    def __init__(self, model_dir: str, *, device: str = "cpu", languages: set[str] | None = None) -> None:
        import torch
        from transformers import AutoModelForCTC, AutoProcessor

        self.name = "hf_ctc"
        self.languages = languages or {"ru"}
        self._torch = torch
        self._processor = AutoProcessor.from_pretrained(model_dir)
        self._model = AutoModelForCTC.from_pretrained(model_dir).to(device).eval()
        self._device = device

    def transcribe(self, samples, language):
        inputs = self._processor(samples, sampling_rate=TARGET_SAMPLE_RATE, return_tensors="pt")
        with self._torch.inference_mode():
            logits = self._model(inputs.input_values.to(self._device)).logits
        ids = logits.argmax(dim=-1)
        text = self._processor.batch_decode(ids)[0]
        return Result(text.strip(), language)


class OpenAIEngine:
    def __init__(self, base_url: str, model: str, *, api_key: str = "none") -> None:
        import httpx

        self.name = "openai"
        self.languages = {"ru", "en", "auto"}
        self._client = httpx.Client(timeout=300)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    def transcribe(self, samples, language):
        wav = pcm16_to_wav(float_to_pcm16(samples), TARGET_SAMPLE_RATE)
        data = {"model": self.model, "response_format": "json"}
        if language:
            data["language"] = language
        resp = self._client.post(
            f"{self.base_url}/audio/transcriptions",
            files={"file": ("audio.wav", io.BytesIO(wav), "audio/wav")},
            data=data,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        resp.raise_for_status()
        return Result(resp.json().get("text", "").strip(), language)


def build_engine(spec: dict[str, Any]) -> Engine:
    kind = spec["kind"]
    options = {k: v for k, v in spec.items() if k not in {"kind", "languages"}}
    if kind == "fake":
        engine: Engine = FakeEngine(**options)
    elif kind == "gigaam":
        engine = GigaAmEngine(**options)
    elif kind == "whisper":
        engine = WhisperEngine(**options)
    elif kind == "hf_ctc":
        engine = HfCtcEngine(**options)
    elif kind == "openai":
        engine = OpenAIEngine(**options)
    else:
        raise ValueError(f"Неизвестный движок ASR: {kind}")
    if spec.get("languages"):
        engine.languages = set(spec["languages"])
    return engine
