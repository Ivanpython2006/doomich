"""Дообучение распознавания речи под вуз: лекции, термины дисциплин, акустика аудиторий.

Два варианта:
* ``ctc``     — CTC-модели Hugging Face (Wav2Vec2/HuBERT/GigaAM-CTC в формате HF). Выход читает
                сервис ASR (движок ``hf_ctc``).
* ``whisper`` — Whisper (seq2seq). Выход можно сконвертировать в CTranslate2 для faster-whisper.

Данные — JSONL: {"audio": "путь/к/файлу.wav", "text": "эталонная расшифровка"}.
Собирайте только записи, на которые есть согласие (например, лекции, которые преподаватель
разрешил использовать, и их выверенные расшифровки).

Плюс «лёгкая» адаптация без обучения — глоссарий терминов вуза (``build_glossary``),
который подаётся в LLM для исправления распознанного текста.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from doomich_common.audio import TARGET_SAMPLE_RATE, decode_any

from doomich_ml.common import Run, log, pick_device, read_jsonl, seed_everything


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def normalize_text(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def wer(references: list[str], hypotheses: list[str]) -> float:
    errors = sum(
        edit_distance(normalize_text(r).split(), normalize_text(h).split())
        for r, h in zip(references, hypotheses, strict=True)
    )
    words = sum(len(normalize_text(r).split()) for r in references)
    return errors / max(1, words)


def cer(references: list[str], hypotheses: list[str]) -> float:
    errors = sum(
        edit_distance(list(normalize_text(r)), list(normalize_text(h)))
        for r, h in zip(references, hypotheses, strict=True)
    )
    chars = sum(len(normalize_text(r)) for r in references)
    return errors / max(1, chars)


def load_audio(path: str) -> np.ndarray:
    data = Path(path).read_bytes()
    return decode_any(data, Path(path).suffix.lstrip(".").lower() or "wav")


def build_glossary(texts: list[str], top: int = 300, min_len: int = 5) -> list[str]:
    """Термины вуза: слова с заглавной буквы и редкие длинные слова из документов вуза."""
    counter: Counter[str] = Counter()
    for text in texts:
        for word in re.findall(rf"[A-Za-zА-Яа-яЁё][\w-]{{{min_len - 1},}}", text):
            counter[word] += 1
    common = {"который", "которые", "является", "студентов", "университета", "должен", "необходимо"}
    return [w for w, _ in counter.most_common(top * 3) if w.lower() not in common][:top]


@dataclass
class AsrTrainConfig:
    base_model: str
    train_manifest: str
    val_manifest: str | None = None
    backend: str = "ctc"  # ctc | whisper
    base_model_license: str = "MIT"
    new_vocab: bool = False  # собрать алфавит из текстов (для основы без нужного алфавита)
    epochs: int = 5
    lr: float = 3e-5
    batch_size: int = 8
    grad_accum: int = 2
    freeze_feature_encoder: bool = True
    language: str = "ru"
    seed: int = 42
    device: str = "auto"


def _char_vocab(texts: list[str]) -> dict[str, int]:
    chars = sorted({c for t in texts for c in normalize_text(t)} - {" "})
    vocab = {"<pad>": 0, "<unk>": 1, "|": 2}
    for c in chars:
        vocab.setdefault(c, len(vocab))
    return vocab


def train_ctc(config: AsrTrainConfig, run: Run) -> dict[str, float]:
    from transformers import (
        AutoFeatureExtractor,
        AutoModelForCTC,
        AutoProcessor,
        Wav2Vec2CTCTokenizer,
        Wav2Vec2Processor,
    )

    seed_everything(config.seed)
    device = pick_device(config.device)
    train_rows = read_jsonl(config.train_manifest)
    val_rows = read_jsonl(config.val_manifest) if config.val_manifest else train_rows[: max(1, len(train_rows) // 10)]
    if config.new_vocab:
        vocab_path = run.dir / "vocab.json"
        vocab_path.write_text(json.dumps(_char_vocab([r["text"] for r in train_rows]), ensure_ascii=False))
        tokenizer = Wav2Vec2CTCTokenizer(
            str(vocab_path),
            unk_token="<unk>",
            pad_token="<pad>",
            word_delimiter_token="|",
        )
        extractor = AutoFeatureExtractor.from_pretrained(config.base_model)
        processor = Wav2Vec2Processor(feature_extractor=extractor, tokenizer=tokenizer)
        model = AutoModelForCTC.from_pretrained(
            config.base_model,
            vocab_size=len(tokenizer),
            pad_token_id=tokenizer.pad_token_id,
            ctc_loss_reduction="mean",
            ignore_mismatched_sizes=True,
        )
    else:
        processor = AutoProcessor.from_pretrained(config.base_model)
        model = AutoModelForCTC.from_pretrained(config.base_model, ctc_loss_reduction="mean")
    if config.freeze_feature_encoder and hasattr(model, "freeze_feature_encoder"):
        model.freeze_feature_encoder()
    model.to(device)

    def encode(row: dict[str, Any]) -> dict[str, Any]:
        audio = load_audio(row["audio"])
        values = processor(audio, sampling_rate=TARGET_SAMPLE_RATE).input_values[0]
        labels = processor.tokenizer(normalize_text(row["text"])).input_ids
        return {"input_values": np.asarray(values, np.float32), "labels": labels, "text": row["text"]}

    train_set = [encode(r) for r in train_rows]
    val_set = [encode(r) for r in val_rows]

    def collate(batch):
        width = max(len(x["input_values"]) for x in batch)
        lwidth = max(len(x["labels"]) for x in batch)
        values = torch.zeros(len(batch), width)
        mask = torch.zeros(len(batch), width, dtype=torch.long)
        labels = torch.full((len(batch), lwidth), -100, dtype=torch.long)
        for i, x in enumerate(batch):
            values[i, : len(x["input_values"])] = torch.from_numpy(x["input_values"])
            mask[i, : len(x["input_values"])] = 1
            labels[i, : len(x["labels"])] = torch.tensor(x["labels"])
        return {"input_values": values, "attention_mask": mask, "labels": labels}

    def transcribe(items) -> list[str]:
        model.eval()
        out = []
        with torch.inference_mode():
            for x in items:
                logits = model(torch.from_numpy(x["input_values"])[None].to(device)).logits
                out.append(processor.batch_decode(logits.argmax(-1))[0])
        return out

    metrics = {"wer_before": wer([x["text"] for x in val_set], transcribe(val_set))}
    loader = torch.utils.data.DataLoader(train_set, batch_size=config.batch_size, shuffle=True, collate_fn=collate)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=config.lr)
    for epoch in range(config.epochs):
        model.train()
        total = 0.0
        for i, batch in enumerate(loader):
            loss = model(**{k: v.to(device) for k, v in batch.items()}).loss / config.grad_accum
            if torch.isfinite(loss):
                loss.backward()
            if (i + 1) % config.grad_accum == 0 or i + 1 == len(loader):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                optimizer.zero_grad()
            total += loss.item() * config.grad_accum
        log.info("Эпоха %d: loss=%.4f", epoch + 1, total / max(1, len(loader)))
    hyps = transcribe(val_set)
    refs = [x["text"] for x in val_set]
    metrics.update({"wer": wer(refs, hyps), "cer": cer(refs, hyps)})
    model.save_pretrained(run.artifacts / "model")
    processor.save_pretrained(run.artifacts / "model")
    run.save_metrics(metrics)
    return metrics


def train_whisper(config: AsrTrainConfig, run: Run) -> dict[str, float]:
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    seed_everything(config.seed)
    device = pick_device(config.device)
    processor = WhisperProcessor.from_pretrained(config.base_model, language=config.language, task="transcribe")
    model = WhisperForConditionalGeneration.from_pretrained(config.base_model).to(device)
    model.generation_config.language = config.language
    model.generation_config.task = "transcribe"
    train_rows = read_jsonl(config.train_manifest)
    val_rows = read_jsonl(config.val_manifest) if config.val_manifest else train_rows[: max(1, len(train_rows) // 10)]

    def features(row):
        audio = load_audio(row["audio"])[: TARGET_SAMPLE_RATE * 30]
        return processor.feature_extractor(audio, sampling_rate=TARGET_SAMPLE_RATE, return_tensors="pt").input_features[
            0
        ]

    def transcribe(rows) -> list[str]:
        model.eval()
        out = []
        with torch.inference_mode():
            for row in rows:
                ids = model.generate(features(row)[None].to(device), max_new_tokens=225)
                out.append(processor.batch_decode(ids, skip_special_tokens=True)[0])
        return out

    refs = [r["text"] for r in val_rows]
    metrics = {"wer_before": wer(refs, transcribe(val_rows))}
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.lr)
    for epoch in range(config.epochs):
        model.train()
        for i in range(0, len(train_rows), config.batch_size):
            batch = train_rows[i : i + config.batch_size]
            inputs = torch.stack([features(r) for r in batch]).to(device)
            labels = processor.tokenizer([r["text"] for r in batch], return_tensors="pt", padding=True).input_ids
            labels = labels.masked_fill(labels == processor.tokenizer.pad_token_id, -100).to(device)
            loss = model(input_features=inputs, labels=labels).loss
            loss.backward()
            optimizer.step()
            optimizer.zero_grad()
        log.info("Эпоха %d завершена", epoch + 1)
    metrics.update({"wer": wer(refs, transcribe(val_rows))})
    model.save_pretrained(run.artifacts / "model")
    processor.save_pretrained(run.artifacts / "model")
    run.save_metrics(metrics)
    return metrics


def convert_to_ctranslate2(model_dir: Path, out_dir: Path, quantization: str = "float16") -> Path:
    """Whisper → CTranslate2 (faster-whisper). Требует пакет ctranslate2 (``doomich-ml[whisper]``)."""
    from ctranslate2.converters import TransformersConverter

    TransformersConverter(str(model_dir)).convert(str(out_dir), quantization=quantization, force=True)
    return out_dir
