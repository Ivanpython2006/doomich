"""LLM-провайдеры: OpenAI-совместимый (vLLM, Ollama, llama.cpp-server…) и детерминированный fake.

vLLM поддерживает несколько LoRA-адаптеров на одной базовой модели: адаптер вуза
выбирается полем ``model`` запроса (см. :func:`resolve_model`).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from doomich_api.config import Settings

log = logging.getLogger(__name__)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str

    def parsed_arguments(self) -> dict[str, Any]:
        try:
            value = json.loads(self.arguments or "{}")
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}


@dataclass
class LlmEvent:
    type: str  # delta | tool_calls | done
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    model: str | None = None


class LlmProvider(Protocol):
    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LlmEvent]: ...

    async def complete(self, messages: list[dict[str, Any]], *, model: str, max_tokens: int | None = None) -> str: ...


class ThinkFilter:
    """Вырезает рассуждения ``<think>…</think>`` из потока, если модель их всё же выдаёт."""

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out = []
        while self._buf:
            if self._inside:
                end = self._buf.find("</think>")
                if end == -1:
                    self._buf = self._buf[-8:]  # хвост может содержать начало закрывающего тега
                    return "".join(out)
                self._buf = self._buf[end + len("</think>") :]
                self._inside = False
            else:
                start = self._buf.find("<think>")
                if start == -1:
                    # держим возможное начало тега
                    keep = 0
                    for k in range(1, 7):
                        if self._buf.endswith("<think>"[:k]):
                            keep = k
                    out.append(self._buf[: len(self._buf) - keep])
                    self._buf = self._buf[len(self._buf) - keep :]
                    return "".join(out)
                out.append(self._buf[:start])
                self._buf = self._buf[start + len("<think>") :]
                self._inside = True
        return "".join(out)

    def flush(self) -> str:
        rest = "" if self._inside else self._buf
        self._buf = ""
        return rest


class OpenAICompatibleLlm:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.base_url = settings.llm_base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=settings.llm_timeout_s)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.llm_api_key.get_secret_value()}"}

    def _body(self, messages, model, tools, max_tokens, temperature, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": max_tokens or self.settings.llm_max_tokens,
            "temperature": self.settings.llm_temperature if temperature is None else temperature,
            # Qwen 3.x: отключаем «размышления» ради скорости ответа
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return body

    async def stream_chat(self, messages, *, model, tools=None, max_tokens=None, temperature=None):
        body = self._body(messages, model, tools, max_tokens, temperature, stream=True)
        calls: dict[int, dict[str, str]] = {}
        finish = None
        used_model = model
        think = ThinkFilter()
        async with self._client.stream(
            "POST", f"{self.base_url}/chat/completions", json=body, headers=self._headers()
        ) as resp:
            if resp.status_code >= 400:
                detail = (await resp.aread()).decode(errors="ignore")[:300]
                raise RuntimeError(f"LLM вернул {resp.status_code}: {detail}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                used_model = chunk.get("model", used_model)
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        visible = think.feed(content)
                        if visible:
                            yield LlmEvent("delta", text=visible)
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
        tail = think.flush()
        if tail:
            yield LlmEvent("delta", text=tail)
        if calls:
            yield LlmEvent(
                "tool_calls",
                tool_calls=[
                    ToolCall(id=c["id"] or f"call_{i}", name=c["name"], arguments=c["arguments"])
                    for i, c in sorted(calls.items())
                ],
            )
        yield LlmEvent("done", finish_reason=finish, model=used_model)

    async def complete(self, messages, *, model, max_tokens=None) -> str:
        body = self._body(messages, model, None, max_tokens, None, stream=False)
        resp = await self._client.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers())
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"].get("content") or ""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()

    async def load_lora(self, name: str, path: str) -> bool:
        """Подгрузить LoRA-адаптер вуза в vLLM (нужен VLLM_ALLOW_RUNTIME_LORA_UPDATING=True)."""
        root = self.base_url.removesuffix("/v1")
        resp = await self._client.post(
            f"{root}/v1/load_lora_adapter", json={"lora_name": name, "lora_path": path}, headers=self._headers()
        )
        if resp.status_code >= 400 and "already" not in resp.text:
            log.warning("vLLM не загрузил LoRA %s: %s", name, resp.text[:200])
            return False
        return True


# ---------------------------------------------------------------------------- fake
_SCHEDULE_WORDS = ("распис", "пара", "пары", "занят", "лекци", "schedule", "class", "lesson", "экзамен")
_DOC_WORDS = ("документ", "методичк", "файл", "в тексте", "по лекции", "document", "pdf", "таблиц")
_UNI_WORDS = ("деканат", "библиотек", "стипенд", "общежит", "правил", "вуз", "university")
_NAV_WORDS = ("как пройти", "где аудитор", "как дойти", "маршрут", "navigate", "how to get")


class FakeLlm:
    """Детерминированная «модель» для тестов и демо-режима без GPU.

    Умеет вызывать инструменты по ключевым словам и строить ответ из их результатов.
    Можно передать сценарий — список заранее заданных событий на каждый вызов.
    """

    def __init__(self, script: list[list[LlmEvent]] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[dict[str, Any]] = []

    async def stream_chat(self, messages, *, model, tools=None, max_tokens=None, temperature=None):
        self.calls.append({"messages": messages, "tools": tools, "model": model})
        if self.script:
            for ev in self.script.pop(0):
                yield ev
            return
        last = messages[-1]
        tool_names = {t["function"]["name"] for t in tools or []}
        if last["role"] == "tool":
            text = self._answer_from_tools(messages)
        else:
            user_text = str(last.get("content", "")).lower()
            system = str(messages[0].get("content", "")) if messages else ""
            call = None
            if "get_schedule" in tool_names and any(w in user_text for w in _SCHEDULE_WORDS):
                call = ToolCall("call_1", "get_schedule", json.dumps({"date_from": "", "date_to": ""}))
            elif "navigate" in tool_names and any(w in user_text for w in _NAV_WORDS):
                room = re.findall(r"\d{2,4}[а-яa-z]?", user_text)
                call = ToolCall("call_1", "navigate", json.dumps({"destination": room[-1] if room else user_text}))
            elif "search_documents" in tool_names and (
                any(w in user_text for w in _DOC_WORDS) or "DOCUMENT_SCOPE" in system
            ):
                call = ToolCall("call_1", "search_documents", json.dumps({"query": last.get("content", "")}))
            elif "university_info" in tool_names and any(w in user_text for w in _UNI_WORDS):
                call = ToolCall("call_1", "university_info", json.dumps({"query": last.get("content", "")}))
            if call is not None:
                yield LlmEvent("tool_calls", tool_calls=[call])
                yield LlmEvent("done", finish_reason="tool_calls", model=model)
                return
            text = (
                f"Думыч (демо-режим) услышал вопрос: «{last.get('content', '')}». "
                "Подключите LLM, чтобы получить настоящий ответ."
            )
        for word in re.findall(r"\S+\s*", text):
            yield LlmEvent("delta", text=word)
        yield LlmEvent("done", finish_reason="stop", model=model)

    @staticmethod
    def _answer_from_tools(messages: list[dict[str, Any]]) -> str:
        results = []
        for msg in reversed(messages):
            if msg["role"] != "tool":
                break
            results.append(str(msg.get("content", "")))
        content = "\n".join(reversed(results))
        if "[1]" in content:
            fragment = content.split("[1]", 1)[1].strip().split("\n\n", 1)[0]
            first = " ".join(line.strip() for line in fragment.splitlines()[:3])
            return f"Нашёл в документах: {first[:300]} [1]"
        return f"Вот что удалось найти:\n{content[:800]}"

    async def complete(self, messages, *, model, max_tokens=None) -> str:
        self.calls.append({"messages": messages, "model": model})
        text = str(messages[-1].get("content", ""))
        return "## Конспект\n\n" + "\n".join(
            f"- {line.strip()[:200]}" for line in text.splitlines()[:20] if line.strip()
        )

    async def load_lora(self, name: str, path: str) -> bool:
        return True
