"""Нарезка блоков на фрагменты для поиска с учётом структуры."""

from __future__ import annotations

import re
from dataclasses import dataclass

from doomich_api.rag.parsing import Block


@dataclass
class ChunkDraft:
    body: str
    page: int | None
    section: str | None


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    """Режем длинный текст по предложениям, а если их нет — по символам."""
    sentences = re.split(r"(?<=[.!?…])\s+|\n+", text)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > size:  # очень длинное «предложение»
            head, sentence = sentence[:size], sentence[size - overlap :]
            if current:
                parts.append(current)
                current = ""
            parts.append(head)
        if len(current) + len(sentence) + 1 > size and current:
            parts.append(current)
            tail = current[-overlap:] if overlap else ""
            current = (tail + " " + sentence).strip() if tail else sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def _split_table(text: str, size: int) -> list[str]:
    lines = text.splitlines()
    if len(lines) <= 2:
        return [text]
    header, rows = lines[:2], lines[2:]
    parts, current = [], list(header)
    for row in rows:
        if sum(len(x) + 1 for x in current) + len(row) > size and len(current) > 2:
            parts.append("\n".join(current))
            current = list(header)
        current.append(row)
    if len(current) > 2:
        parts.append("\n".join(current))
    return parts


def chunk_blocks(blocks: list[Block], size: int = 900, overlap: int = 120) -> list[ChunkDraft]:
    """Склеиваем мелкие блоки одной страницы/раздела, режем крупные; таблицы — с заголовком."""
    chunks: list[ChunkDraft] = []
    pending = ""
    pending_key: tuple[int | None, str | None] | None = None

    def flush() -> None:
        nonlocal pending, pending_key
        if pending.strip() and pending_key is not None:
            for part in _split_long(pending.strip(), size, overlap):
                chunks.append(ChunkDraft(part, pending_key[0], pending_key[1]))
        pending, pending_key = "", None

    for block in blocks:
        key = (block.page, block.section)
        if block.is_table:
            flush()
            for part in _split_table(block.text, size * 2):
                chunks.append(ChunkDraft(part, block.page, block.section))
            continue
        if pending_key != key:
            flush()
            pending_key = key
        pending = f"{pending}\n{block.text}" if pending else block.text
        if len(pending) >= size * 3:
            flush()
            pending_key = key
    flush()
    return chunks
