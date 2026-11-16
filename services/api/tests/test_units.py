from __future__ import annotations

import numpy as np
import pytest
from doomich_api.ai.llm import ThinkFilter
from doomich_api.ai.text import SentenceSplitter, strip_markdown
from doomich_api.rag.chunking import chunk_blocks
from doomich_api.rag.parsing import Block, ParseError, sniff_mime
from doomich_api.security import (
    Crypto,
    format_groups,
    looks_like_real_name,
    new_recovery_code,
    normalize_code,
    password_problems,
)


def test_sentence_splitter_streaming():
    splitter = SentenceSplitter(min_chars=10)
    out = []
    for part in ["Привет! Сегодня у тебя ", "три пары, т.е. ", "занятий много. Удачи", " на парах."]:
        out += splitter.feed(part)
    out += splitter.flush()
    assert out == ["Привет! Сегодня у тебя три пары, т.е. занятий много.", "Удачи на парах."]


def test_strip_markdown():
    text = "## Итог\n- **Закон** Ома: $U = IR$ [1]\n```py\nprint(1)\n```\n[ссылка](http://x)"
    assert strip_markdown(text) == "Итог\nЗакон Ома: (формула)\nссылка"


def test_think_filter():
    f = ThinkFilter()
    out = f.feed("<thi") + f.feed("nk>скрыто</th") + f.feed("ink>Видно") + f.flush()
    assert out == "Видно"


def test_chunking_keeps_tables_and_pages():
    blocks = [
        Block("Короткий абзац.", page=1),
        Block("Ещё абзац " * 200, page=1),
        Block(
            "| a | b |\n| --- | --- |\n" + "\n".join(f"| {i} | {i * 2} |" for i in range(300)), page=2, is_table=True
        ),
    ]
    chunks = chunk_blocks(blocks, size=500, overlap=50)
    assert all(len(c.body) <= 1100 for c in chunks)
    table_chunks = [c for c in chunks if c.page == 2]
    assert len(table_chunks) > 1 and all(c.body.startswith("| a | b |") for c in table_chunks)


def test_sniff_mime():
    with pytest.raises(ParseError):
        sniff_mime("x.exe", b"MZ")
    assert sniff_mime("x.txt", "привет".encode()) == "text/plain"


def test_codes_and_names():
    code = new_recovery_code()
    assert len(normalize_code(code)) == 20 and format_groups(normalize_code(code)) == code
    assert looks_like_real_name("Иванов Сергей")
    assert looks_like_real_name("maria")
    assert not looks_like_real_name("ТихийЕнот42")
    assert password_problems("1234567890")
    assert not password_problems("очень-надёжный-пароль-1")


def test_crypto_roundtrip_and_tamper():
    import uuid

    crypto = Crypto(b"k" * 32)
    user = uuid.uuid4()
    wrapped = crypto.new_wrapped_dek(user)
    blob = crypto.encrypt_text(wrapped, user, "привет", "msg:1")
    assert crypto.decrypt_text(wrapped, user, blob, "msg:1") == "привет"
    with pytest.raises(Exception):  # noqa: B017 — неверное назначение (AAD) должно ломать расшифровку
        crypto.decrypt_text(wrapped, user, blob, "msg:2")
    with pytest.raises(Exception):  # noqa: B017 — чужой пользователь не расшифрует ключ
        crypto.decrypt_text(wrapped, uuid.uuid4(), blob, "msg:1")
    rotated = Crypto(b"n" * 32)
    rewrapped = crypto.rewrap(wrapped, user, rotated)
    assert rotated.decrypt_text(rewrapped, user, blob, "msg:1") == "привет"


def test_split_on_silence():
    from doomich_common.audio import split_on_silence

    sr = 16000
    tone = 0.3 * np.sin(2 * np.pi * 200 * np.arange(sr * 3) / sr)
    silence = np.zeros(sr)
    audio = np.concatenate([tone, silence, tone, silence, tone]).astype(np.float32)
    segments = split_on_silence(audio, sr, max_segment_s=4.0)
    assert len(segments) == 3
    assert all((end - start) / sr <= 4.0 for start, end in segments)
