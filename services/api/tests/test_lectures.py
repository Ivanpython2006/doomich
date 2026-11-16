from __future__ import annotations

import numpy as np
from doomich_api.ai.speech import FakeAsr
from doomich_common.audio import float_to_pcm16, pcm16_to_wav

from tests.conftest import register


def _lecture_wav() -> bytes:
    sr = 16000
    tone = 0.3 * np.sin(2 * np.pi * 180 * np.arange(sr * 2) / sr)
    audio = np.concatenate([tone, np.zeros(sr), tone]).astype(np.float32)
    return pcm16_to_wav(float_to_pcm16(audio), sr)


async def test_lecture_notes_pipeline(client, tenant, providers):
    providers.asr = FakeAsr("Производная показывает скорость изменения функции.")
    user = await register(client, tenant)
    resp = await client.post(
        "/v1/lectures",
        files={"file": ("lecture.wav", _lecture_wav(), "audio/wav")},
        data={"title": "Матанализ, лекция 1", "template": "short", "teacher_consent": "false"},
        headers=user["headers"],
    )
    assert resp.status_code == 400  # без разрешения преподавателя запись не принимаем

    resp = await client.post(
        "/v1/lectures",
        files={"file": ("lecture.wav", _lecture_wav(), "audio/wav")},
        data={"title": "Матанализ, лекция 1", "template": "short", "teacher_consent": "true"},
        headers=user["headers"],
    )
    assert resp.status_code == 201, resp.text
    lecture = (await client.get(f"/v1/lectures/{resp.json()['id']}", headers=user["headers"])).json()
    assert lecture["status"] == "ready", lecture
    assert "[00:00]" in lecture["transcript"] and "Производная" in lecture["transcript"]
    assert lecture["notes"].startswith("## Конспект")
    assert lecture["document_id"]

    docx = await client.get(f"/v1/lectures/{lecture['id']}/export", params={"format": "docx"}, headers=user["headers"])
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    md = await client.get(f"/v1/lectures/{lecture['id']}/export", params={"format": "md"}, headers=user["headers"])
    assert "Конспект" in md.text

    # расшифровка доступна для «чата с лекцией» как документ
    docs = (await client.get("/v1/documents", headers=user["headers"])).json()
    assert docs[0]["title"] == "Лекция: Матанализ, лекция 1"
