"""Оркестратор диалога: промпт, история, вызовы инструментов, потоковый ответ, ссылки на источники."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from doomich_api.ai import Providers
from doomich_api.ai.prompts import system_prompt
from doomich_api.ai.tools import ToolBox
from doomich_api.config import Settings
from doomich_api.context import UserContext
from doomich_api.rag.search import Hit

log = logging.getLogger(__name__)
MAX_TOOL_ROUNDS = 3
_CITE = re.compile(r"\[(\d{1,2})\]")


@dataclass
class TurnEvent:
    type: str  # delta | tool | citations | done
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def trim_history(history: list[dict[str, str]], budget_chars: int) -> list[dict[str, str]]:
    """Оставляем последние сообщения, пока помещаются в бюджет контекста."""
    kept: list[dict[str, str]] = []
    used = 0
    for message in reversed(history):
        size = len(message.get("content") or "")
        if used + size > budget_chars and kept:
            break
        kept.append(message)
        used += size
    return list(reversed(kept))


def build_citations(text: str, fragments: list[Hit]) -> list[dict[str, Any]]:
    seen: set[int] = set()
    citations = []
    for match in _CITE.finditer(text):
        n = int(match.group(1))
        if n in seen or not 1 <= n <= len(fragments):
            continue
        seen.add(n)
        hit = fragments[n - 1]
        citations.append(
            {
                "n": n,
                "document_id": str(hit.document_id),
                "chunk_id": str(hit.chunk_id),
                "title": hit.title,
                "page": hit.page,
                "section": hit.section,
                "snippet": hit.body[:240],
            }
        )
    return citations


class Orchestrator:
    def __init__(self, providers: Providers, settings: Settings) -> None:
        self.providers = providers
        self.settings = settings

    async def run(
        self,
        *,
        user: UserContext,
        toolbox: ToolBox,
        history: list[dict[str, str]],
        user_text: str,
        model: str,
        voice: bool = False,
    ) -> AsyncIterator[TurnEvent]:
        system = system_prompt(
            locale=user.locale,
            university=user.university_name,
            role=user.role,
            group=user.group_code,
            now=user.now(),
            voice=voice,
            document_scope=bool(toolbox.document_ids),
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            *trim_history(history, self.settings.llm_context_chars),
            {"role": "user", "content": user_text},
        ]
        visible: list[str] = []
        used_model = model
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            tools = toolbox.definitions() if round_no < MAX_TOOL_ROUNDS else None
            round_text: list[str] = []
            calls = []
            async for event in self.providers.llm.stream_chat(
                messages, model=model, tools=tools, max_tokens=300 if voice else None
            ):
                if event.type == "delta" and event.text:
                    round_text.append(event.text)
                    visible.append(event.text)
                    yield TurnEvent("delta", text=event.text)
                elif event.type == "tool_calls":
                    calls = event.tool_calls
                elif event.type == "done" and event.model:
                    used_model = event.model
            if not calls:
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": "".join(round_text) or None,
                    "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments or "{}"}}
                        for c in calls
                    ],
                }
            )
            for call in calls:
                yield TurnEvent("tool", data={"name": call.name})
                result = await toolbox.execute(call.name, call.parsed_arguments())
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        final = "".join(visible).strip()
        citations = build_citations(final, toolbox.fragments)
        if citations:
            yield TurnEvent("citations", data={"citations": citations})
        yield TurnEvent("done", text=final, data={"model": used_model, "citations": citations})
