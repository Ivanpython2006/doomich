from __future__ import annotations

import json

import numpy as np
from doomich_api.ai.speech import FakeAsr
from starlette.testclient import TestClient

from tests.conftest import register


def _pcm(seconds: float = 1.0) -> bytes:
    t = np.arange(int(16000 * seconds)) / 16000
    return (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2").tobytes()


async def test_voice_roundtrip(app, client, tenant, providers):
    providers.asr = FakeAsr("Какая сегодня погода в мире математики?")
    user = await register(client, tenant)
    chat = (await client.post("/v1/chats", json={}, headers=user["headers"])).json()

    def scenario():
        with TestClient(app) as sync, sync.websocket_connect("/v1/voice") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": user["access_token"]}))
            assert ws.receive_json()["type"] == "ready"
            ws.send_text(
                json.dumps(
                    {
                        "type": "start",
                        "chat_id": chat["id"],
                        "lang": "ru",
                        "format": "pcm16",
                        "sample_rate": 16000,
                        "speak": True,
                    }
                )
            )
            pcm = _pcm()
            for i in range(0, len(pcm), 3200):
                ws.send_bytes(pcm[i : i + 3200])
            ws.send_text(json.dumps({"type": "end"}))
            got: list[dict] = []
            audio_frames = 0
            while True:
                msg = ws.receive_json()
                got.append(msg)
                if msg["type"] == "audio":
                    blob = ws.receive_bytes()
                    assert blob[:4] == b"RIFF"
                    audio_frames += 1
                if msg["type"] in {"done", "error"}:
                    break
            return got, audio_frames

    import asyncio

    got, audio_frames = await asyncio.to_thread(scenario)
    types = [m["type"] for m in got]
    assert types[0] == "transcript" and got[0]["text"].startswith("Какая сегодня")
    assert "answer_delta" in types and types[-1] == "done"
    assert audio_frames >= 1
    assert got[-1]["message_id"]

    history = (await client.get(f"/v1/chats/{chat['id']}/messages", headers=user["headers"])).json()
    assert [m["mode"] for m in history] == ["voice", "voice"]


async def test_voice_rejects_bad_token(app):
    import asyncio

    def scenario():
        with TestClient(app) as sync, sync.websocket_connect("/v1/voice") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": "garbage"}))
            try:
                ws.receive_json()
            except Exception as exc:
                return getattr(exc, "code", None)
        return None

    assert await asyncio.to_thread(scenario) == 4401


async def test_tts_endpoint(client, tenant, providers):
    user = await register(client, tenant)
    resp = await client.post("/v1/tts", json={"text": "## Итог\n**Пара** в 9:00 [1]"}, headers=user["headers"])
    assert resp.status_code == 200 and resp.content[:4] == b"RIFF"
    empty = await client.post("/v1/tts", json={"text": "[1]"}, headers=user["headers"])
    assert empty.status_code == 400
