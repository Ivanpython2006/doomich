"""Голосовой канал (WebSocket): звук → распознавание → ответ ИИ → озвучка по предложениям.

Протокол (JSON-сообщения и бинарные кадры):

Клиент → сервер:
    {"type": "auth", "token": "..."}                      — если токен не передан в заголовке
    {"type": "start", "chat_id": "...|null", "lang": "ru|en|auto",
     "format": "pcm16|wav|opus|ogg|aac|m4a", "sample_rate": 16000, "speak": true,
     "history": [...]}                                     — history только для инкогнито
    <бинарные кадры со звуком>
    {"type": "end"}                                        — конец фразы
    {"type": "cancel"}                                     — прервать ответ

Сервер → клиент:
    {"type": "ready"}
    {"type": "transcript", "text": "...", "final": true}
    {"type": "answer_delta", "text": "..."}
    {"type": "tool", "name": "get_schedule"}
    {"type": "audio", "seq": 0, "format": "wav", "sample_rate": 24000, "text": "..."}, затем бинарный кадр
    {"type": "citations", "citations": [...]}
    {"type": "done", "message_id": "...", "text": "..."}
    {"type": "error", "code": "...", "message": "..."}

Звук обрабатывается только в памяти и не сохраняется.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any

from doomich_common.audio import AudioError, decode_any
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from doomich_api.ai import get_providers
from doomich_api.ai.conversation import prepare_turn, run_turn
from doomich_api.ai.text import SentenceSplitter, strip_markdown
from doomich_api.api.deps import current_user, limit, user_from_token
from doomich_api.config import get_settings
from doomich_api.context import UserContext

router = APIRouter(tags=["voice"])
log = logging.getLogger(__name__)
MAX_COMPRESSED_BYTES = 4 * 1024 * 1024


class VoiceSession:
    def __init__(self, ws: WebSocket, user: UserContext) -> None:
        self.ws = ws
        self.user = user
        self.buffer = bytearray()
        self.params: dict[str, Any] = {}
        self.task: asyncio.Task | None = None
        self.send_lock = asyncio.Lock()

    async def send(self, payload: dict[str, Any], binary: bytes | None = None) -> None:
        async with self.send_lock:
            await self.ws.send_json(payload)
            if binary is not None:
                await self.ws.send_bytes(binary)

    def max_bytes(self) -> int:
        seconds = get_settings().max_voice_seconds
        if self.params.get("format", "pcm16") in {"pcm16", "pcm"}:
            return seconds * int(self.params.get("sample_rate", 16000)) * 2
        return MAX_COMPRESSED_BYTES

    async def process(self, audio: bytes, params: dict[str, Any]) -> None:
        providers = get_providers()
        lang = params.get("lang") or self.user.locale
        try:
            samples = await asyncio.to_thread(
                decode_any, audio, params.get("format", "pcm16"), int(params.get("sample_rate", 16000))
            )
        except AudioError as exc:
            await self.send({"type": "error", "code": "bad_audio", "message": str(exc)})
            return
        if samples.size < 16000 * 0.3:
            await self.send({"type": "error", "code": "too_short", "message": "Запись слишком короткая"})
            return
        transcript = await providers.asr.transcribe(samples, language=None if lang == "auto" else lang)
        text = transcript.text.strip()
        await self.send({"type": "transcript", "text": text, "final": True, "language": transcript.language})
        if not text:
            await self.send({"type": "error", "code": "no_speech", "message": "Не удалось распознать речь"})
            return

        chat_id = uuid.UUID(params["chat_id"]) if params.get("chat_id") else None
        try:
            turn = await prepare_turn(
                self.user, chat_id=chat_id, text=text, mode="voice", incognito_history=params.get("history") or []
            )
        except HTTPException as exc:
            await self.send({"type": "error", "code": str(exc.status_code), "message": exc.detail})
            return

        speak = params.get("speak", True)
        speech_lang = transcript.language or (lang if lang != "auto" else self.user.locale)
        splitter = SentenceSplitter()
        seq = 0
        tts_queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def tts_worker() -> None:
            nonlocal seq
            while (sentence := await tts_queue.get()) is not None:
                clean = strip_markdown(sentence)
                if not clean:
                    continue
                try:
                    audio_bytes, fmt, rate = await providers.tts.speak(
                        clean, language=speech_lang, speed=float(params.get("speed", 1.0))
                    )
                except Exception:
                    log.exception("TTS недоступен")
                    continue
                await self.send(
                    {"type": "audio", "seq": seq, "format": fmt, "sample_rate": rate, "text": clean}, audio_bytes
                )
                seq += 1

        worker = asyncio.create_task(tts_worker()) if speak else None
        try:
            async for event in run_turn(self.user, turn, text, voice=True):
                if event.type == "delta":
                    await self.send({"type": "answer_delta", "text": event.text})
                    if worker:
                        for sentence in splitter.feed(event.text):
                            await tts_queue.put(sentence)
                elif event.type == "tool":
                    await self.send({"type": "tool", **event.data})
                elif event.type == "citations":
                    await self.send({"type": "citations", **event.data})
                elif event.type == "done":
                    if worker:
                        for sentence in splitter.flush():
                            await tts_queue.put(sentence)
                        await tts_queue.put(None)
                        await worker
                    await self.send({"type": "done", "text": event.text, **event.data})
        finally:
            if worker and not worker.done():
                worker.cancel()

    async def handle(self) -> None:
        await self.send({"type": "ready"})
        while True:
            message = await self.ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                self.buffer.extend(message["bytes"])
                if len(self.buffer) > self.max_bytes():
                    self.buffer.clear()
                    await self.send({"type": "error", "code": "too_long", "message": "Фраза слишком длинная"})
                continue
            data = _json(message.get("text"))
            kind = data.get("type")
            if kind == "start":
                await self._cancel()
                self.buffer.clear()
                self.params = data
            elif kind == "end":
                audio, params = bytes(self.buffer), dict(self.params)
                self.buffer.clear()
                await self._cancel()
                self.task = asyncio.create_task(self._safe_process(audio, params))
            elif kind == "cancel":
                await self._cancel()
                self.buffer.clear()
                await self.send({"type": "cancelled"})
            elif kind == "ping":
                await self.send({"type": "pong"})

    async def _safe_process(self, audio: bytes, params: dict[str, Any]) -> None:
        try:
            await self.process(audio, params)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка голосового запроса")
            with contextlib.suppress(Exception):
                await self.send({"type": "error", "code": "internal", "message": "Не удалось обработать запрос"})

    async def _cancel(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
        self.task = None


def _json(text: str | None) -> dict[str, Any]:
    import json

    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


@router.websocket("/v1/voice")
async def voice(ws: WebSocket) -> None:
    await ws.accept()
    token = None
    auth = ws.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
    try:
        if token is None:
            first = _json(await asyncio.wait_for(ws.receive_text(), timeout=10))
            token = first.get("token") if first.get("type") == "auth" else None
        if not token:
            await ws.close(code=4401, reason="auth required")
            return
        try:
            user = await user_from_token(token)
        except HTTPException:
            await ws.close(code=4401, reason="invalid token")
            return
        session = VoiceSession(ws, user)
        try:
            await session.handle()
        finally:
            await session._cancel()
    except (WebSocketDisconnect, TimeoutError):
        return


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: str | None = Field(default=None, pattern="^(ru|en)$")


@router.post("/v1/tts")
async def tts(body: TtsIn, request: Request, user: UserContext = Depends(current_user)) -> Response:
    """Озвучить готовый текст (кнопка «Озвучить» у ответа). Текст не сохраняется."""
    limit(request, "tts", 30, 60)
    clean = strip_markdown(body.text)
    if not clean:
        raise HTTPException(400, "Нечего озвучивать")
    audio, fmt, rate = await get_providers().tts.speak(clean[:2000], language=body.language or user.locale)
    return Response(audio, media_type=f"audio/{fmt}", headers={"X-Sample-Rate": str(rate)})
