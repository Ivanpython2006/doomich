"""Обработка текста ответа: очистка разметки для озвучки, разбиение на предложения."""

from __future__ import annotations

import re

_ABBREVIATIONS = (
    "т.е.",
    "т.к.",
    "т.д.",
    "т.п.",
    "др.",
    "г.",
    "гг.",
    "ул.",
    "д.",
    "стр.",
    "см.",
    "им.",
    "ауд.",
    "корп.",
    "e.g.",
    "i.e.",
    "etc.",
    "mr.",
    "dr.",
    "vs.",
    "рис.",
    "табл.",
)
_SENTENCE_END = re.compile(r"([.!?…]+[»\")\]]?)(\s+)")


def strip_markdown(text: str) -> str:
    """Убрать Markdown, LaTeX и ссылки на источники — для синтеза речи."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\$\$.*?\$\$", " (формула) ", text, flags=re.S)
    text = re.sub(r"\$[^$\n]+\$", " (формула) ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", text)  # [1], [1, 2]
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.M)
    text = re.sub(r"(\*\*|__|\*|_|~~)(.+?)\1", r"\2", text)
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


class SentenceSplitter:
    """Потоковое разбиение текста на предложения для озвучки по мере генерации."""

    def __init__(self, min_chars: int = 25) -> None:
        self.buffer = ""
        self.min_chars = min_chars

    def feed(self, chunk: str) -> list[str]:
        self.buffer += chunk
        sentences = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            sentence, self.buffer = self.buffer[:cut].strip(), self.buffer[cut:]
            if sentence:
                sentences.append(sentence)
        return sentences

    def _find_cut(self) -> int | None:
        for match in _SENTENCE_END.finditer(self.buffer):
            end = match.end(1)
            if end < self.min_chars:
                continue
            tail = self.buffer[:end].lower()
            if any(tail.endswith(abbr) for abbr in _ABBREVIATIONS):
                continue
            if re.search(r"\d\.$", tail) and match.group(2) == " ":  # «1. пункт», «2.5»
                continue
            return match.end()
        newline = self.buffer.find("\n")
        if newline >= self.min_chars:
            return newline + 1
        return None

    def flush(self) -> list[str]:
        rest, self.buffer = self.buffer.strip(), ""
        return [rest] if rest else []


def make_title(text: str, limit: int = 60) -> str:
    title = " ".join(text.split())
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"
