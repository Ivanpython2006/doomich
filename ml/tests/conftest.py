"""Крошечные модели и данные для проверки пайплайнов на CPU без скачивания весов."""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest
import torch
from doomich_common.audio import float_to_pcm16, pcm16_to_wav
from PIL import Image

torch.set_num_threads(2)

CORPUS = [
    "Где находится деканат факультета информатики?",
    "Деканат находится в корпусе А на втором этаже, кабинет 210.",
    "Когда выплачивают стипендию?",
    "Стипендию выплачивают двадцать пятого числа каждого месяца.",
    "Как записаться в библиотеку?",
    "В библиотеку записываются по студенческому билету в корпусе Б.",
    "What time does the library open?",
    "The library opens at nine in the morning.",
]


def word_tokenizer(tmp: Path, *, chat: bool = True, bert: bool = False):
    """Маленький токенизатор, обученный на месте (без загрузки из интернета)."""
    from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, trainers
    from transformers import PreTrainedTokenizerFast

    specials = ["<pad>", "<unk>", "<s>", "</s>", "<|im_start|>", "<|im_end|>", "[CLS]", "[SEP]"]
    tok = Tokenizer(models.WordLevel(unk_token="<unk>"))
    tok.normalizer = normalizers.Lowercase()
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    words = " ".join(CORPUS * 3 + ["system user assistant ты думыч помощник вуза отвечай"]).split()
    tok.train_from_iterator([" ".join(words)], trainers.WordLevelTrainer(special_tokens=specials, vocab_size=500))
    fast = PreTrainedTokenizerFast(
        tokenizer_object=tok,
        unk_token="<unk>",
        pad_token="<pad>",
        bos_token="<s>",
        eos_token="</s>",
        cls_token="[CLS]",
        sep_token="[SEP]",
    )
    if chat:
        fast.chat_template = (
            "{% for m in messages %}<|im_start|> {{ m['role'] }} {{ m['content'] }} <|im_end|> {% endfor %}"
            "{% if add_generation_prompt %}<|im_start|> assistant {% endif %}"
        )
    path = tmp / ("bert-tok" if bert else "tok")
    fast.save_pretrained(path)
    return fast


@pytest.fixture
def tiny_llm(tmp_path):
    from transformers import Qwen2Config, Qwen2ForCausalLM

    tok = word_tokenizer(tmp_path)
    config = Qwen2Config(
        vocab_size=len(tok),
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=256,
        pad_token_id=tok.pad_token_id,
        eos_token_id=tok.eos_token_id,
        bos_token_id=tok.bos_token_id,
    )
    model = Qwen2ForCausalLM(config)
    out = tmp_path / "tiny-llm"
    model.save_pretrained(out)
    tok.save_pretrained(out)
    return out


@pytest.fixture
def tiny_encoder(tmp_path):
    from transformers import BertConfig, BertModel

    tok = word_tokenizer(tmp_path, chat=False, bert=True)
    config = BertConfig(
        vocab_size=len(tok),
        hidden_size=32,
        num_hidden_layers=2,
        num_attention_heads=2,
        intermediate_size=64,
        max_position_embeddings=128,
        pad_token_id=tok.pad_token_id,
    )
    out = tmp_path / "tiny-encoder"
    BertModel(config).save_pretrained(out)
    tok.save_pretrained(out)
    return out


@pytest.fixture
def tiny_vit(tmp_path):
    from transformers import Dinov2Config, Dinov2Model

    config = Dinov2Config(
        hidden_size=32, num_hidden_layers=2, num_attention_heads=2, intermediate_size=64, patch_size=8, image_size=32
    )
    out = tmp_path / "tiny-vit"
    Dinov2Model(config).save_pretrained(out)
    return out


COLORS = {"vhod": (220, 40, 40), "lestnica": (40, 200, 60), "aud-305": (40, 60, 220), "stolovaya": (220, 200, 40)}


def make_campus(root: Path, photos_per_node: int = 6) -> Path:
    rng = np.random.default_rng(0)
    for node, color in COLORS.items():
        folder = root / "photos" / node
        folder.mkdir(parents=True)
        for k in range(photos_per_node):
            base = np.array(color, dtype=np.int32)[None, None, :]
            stripes = (np.arange(48)[:, None, None] % (8 + 4 * list(COLORS).index(node)) < 3) * 60
            pixels = np.clip(base + stripes + rng.integers(-25, 25, (48, 64, 3)), 0, 255).astype(np.uint8)
            Image.fromarray(pixels).save(folder / f"{node}_{k}_h{k * 45:03d}.jpg", quality=90)
    nodes = {
        "vhod": {"title": "Главный вход", "floor": 1, "building": "a", "tags": ["гардероб"]},
        "lestnica": {"title": "Лестница", "floor": 1, "building": "a"},
        "aud-305": {"title": "Аудитория 305", "floor": 3, "building": "a", "ocr": ["305"]},
        "stolovaya": {"title": "Столовая", "floor": 1, "building": "a", "tags": ["столовая", "еда"]},
    }
    (root / "nodes.json").write_text(json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
    return root


def jpeg(color, seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    node = next(k for k, v in COLORS.items() if v == color)
    base = np.array(color, dtype=np.int32)[None, None, :]
    stripes = (np.arange(48)[:, None, None] % (8 + 4 * list(COLORS).index(node)) < 3) * 60
    pixels = np.clip(base + stripes + rng.integers(-25, 25, (48, 64, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format="JPEG")
    return buf.getvalue()


def chirp(up: bool, seconds: float = 0.6, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sr = 16000
    t = np.arange(int(sr * seconds * rng.uniform(0.85, 1.15))) / sr
    f0, f1 = (300, 1800) if up else (1800, 300)
    f0 *= rng.uniform(0.9, 1.1)
    phase = 2 * np.pi * (f0 * t + (f1 - f0) * t**2 / (2 * t[-1]))
    return (0.4 * np.sin(phase) * np.hanning(t.size)).astype(np.float32)


def write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pcm16_to_wav(float_to_pcm16(samples), 16000))
