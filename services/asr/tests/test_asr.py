from __future__ import annotations

import json

import numpy as np
from doomich_common.audio import float_to_pcm16, pcm16_to_wav
from fastapi.testclient import TestClient


def _wav(seconds: float) -> bytes:
    t = np.arange(int(16000 * seconds)) / 16000
    return pcm16_to_wav(float_to_pcm16((0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)), 16000)


def _client(monkeypatch, engines: list[dict]) -> TestClient:
    from doomich_asr import main

    main.get_settings.cache_clear()
    monkeypatch.setenv("DOOMICH_ASR_ENGINES", json.dumps(engines))
    monkeypatch.setenv("DOOMICH_ASR_SEGMENT_SECONDS", "2")
    return TestClient(main.create_app())


def test_transcribe_and_language_routing(monkeypatch):
    client = _client(
        monkeypatch,
        [
            {"kind": "fake", "text": "привет", "languages": ["ru"]},
            {"kind": "fake", "text": "hello", "languages": ["en"]},
        ],
    )
    assert client.get("/healthz").json()["engines"] == ["fake", "fake"]
    ru = client.post("/v1/transcribe", files={"file": ("a.wav", _wav(1))}, data={"language": "ru"}).json()
    en = client.post("/v1/transcribe", files={"file": ("a.wav", _wav(1))}, data={"language": "en"}).json()
    assert ru["text"] == "привет" and en["text"] == "hello"
    assert ru["duration"] == 1.0


def test_long_audio_is_segmented(monkeypatch):
    client = _client(monkeypatch, [{"kind": "fake", "text": "фраза"}])
    t = np.arange(16000 * 3) / 16000
    tone = (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    audio = np.concatenate([tone, np.zeros(16000, np.float32), tone])
    wav = pcm16_to_wav(float_to_pcm16(audio), 16000)
    body = client.post("/v1/transcribe", files={"file": ("long.wav", wav)}, data={"language": "ru"}).json()
    assert len(body["segments"]) >= 2
    assert body["text"].startswith("фраза фраза")


def test_bad_audio(monkeypatch):
    client = _client(monkeypatch, [{"kind": "fake"}])
    resp = client.post("/v1/transcribe", files={"file": ("a.ogg", b"not audio")})
    assert resp.status_code == 400
