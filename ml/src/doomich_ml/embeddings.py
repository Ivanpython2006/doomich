"""Дообучение модели эмбеддингов под документы вуза (поиск в RAG).

Пары «вопрос → фрагмент» берутся из FAQ и генерируются по документам вуза учительской LLM
(``synth_queries``). Обучение — InfoNCE с негативами из батча. Оценка Recall@1/5 и MRR
до и после дообучения на отложенных парах.

После смены модели эмбеддингов документы вуза нужно переиндексировать: сервер хранит в каждом
фрагменте имя модели, которой он векторизован, и ищет только по совпадающей.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from doomich_ml.common import Run, batched, log, pick_device, read_jsonl, seed_everything, split

QUERY_INSTRUCTION = "Instruct: Given a question from a university student, retrieve passages that answer it\nQuery: "


def synth_queries(chunks: list[str], *, llm_url: str, model: str, per_chunk: int = 2) -> list[dict[str, str]]:
    import httpx

    pairs = []
    prompt = (
        "Придумай {n} разных вопроса студента, на которые отвечает этот фрагмент. "
        "Ответ — JSON-массив строк.\n\nФрагмент:\n{chunk}"
    )
    with httpx.Client(timeout=120) as client:
        for chunk in chunks:
            resp = client.post(
                f"{llm_url.rstrip('/')}/chat/completions",
                json={
                    "model": model,
                    "temperature": 0.5,
                    "messages": [{"role": "user", "content": prompt.format(n=per_chunk, chunk=chunk[:2500])}],
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
            match = re.search(r"\[.*\]", text, flags=re.S)
            for query in json.loads(match.group(0)) if match else []:
                if isinstance(query, str) and query.strip():
                    pairs.append({"query": query.strip(), "positive": chunk})
    return pairs


@dataclass
class EmbedConfig:
    base_model: str
    pairs_file: str
    base_model_license: str = "Apache-2.0"
    pooling: str = "mean"  # mean | last | cls
    query_instruction: str = QUERY_INSTRUCTION
    epochs: int = 2
    lr: float = 2e-5
    batch_size: int = 32
    temperature: float = 0.05
    max_len: int = 256
    val_fraction: float = 0.1
    seed: int = 42
    device: str = "auto"


class Encoder:
    def __init__(self, model, tokenizer, pooling: str, max_len: int, device: str) -> None:
        self.model, self.tokenizer, self.pooling, self.max_len, self.device = model, tokenizer, pooling, max_len, device

    def __call__(self, texts: list[str]) -> torch.Tensor:
        batch = self.tokenizer(texts, padding=True, truncation=True, max_length=self.max_len, return_tensors="pt").to(
            self.device
        )
        hidden = self.model(**batch).last_hidden_state
        mask = batch["attention_mask"].unsqueeze(-1).float()
        if self.pooling == "cls":
            pooled = hidden[:, 0]
        elif self.pooling == "last":
            last = batch["attention_mask"].sum(1) - 1
            pooled = hidden[torch.arange(hidden.size(0), device=hidden.device), last]
        else:
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
        return F.normalize(pooled, dim=-1)


def retrieval_metrics(encoder: Encoder, pairs: list[dict[str, str]], instruction: str) -> dict[str, float]:
    if not pairs:
        return {}
    corpus = sorted({p["positive"] for p in pairs})
    index = {text: i for i, text in enumerate(corpus)}
    with torch.inference_mode():
        docs = torch.cat([encoder(b) for b in batched(corpus, 64)])
        queries = torch.cat([encoder([instruction + p["query"] for p in b]) for b in batched(pairs, 64)])
    ranks = []
    order = torch.argsort(queries @ docs.T, dim=1, descending=True).cpu().numpy()
    for i, pair in enumerate(pairs):
        ranks.append(int(np.where(order[i] == index[pair["positive"]])[0][0]) + 1)
    ranks_arr = np.asarray(ranks)
    return {
        "recall_at_1": float(np.mean(ranks_arr <= 1)),
        "recall_at_5": float(np.mean(ranks_arr <= 5)),
        "mrr": float(np.mean(1.0 / ranks_arr)),
    }


def train(config: EmbedConfig, run: Run) -> dict[str, float]:
    from transformers import AutoModel, AutoTokenizer

    seed_everything(config.seed)
    device = pick_device(config.device)
    tokenizer = AutoTokenizer.from_pretrained(config.base_model)
    model = AutoModel.from_pretrained(config.base_model).to(device)
    encoder = Encoder(model, tokenizer, config.pooling, config.max_len, device)
    pairs = [p for p in read_jsonl(config.pairs_file) if p.get("query") and p.get("positive")]
    train_pairs, val_pairs = split(pairs, config.val_fraction, config.seed)
    model.eval()
    metrics: dict[str, Any] = {
        f"before_{k}": v for k, v in retrieval_metrics(encoder, val_pairs, config.query_instruction).items()
    }
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.lr, weight_decay=0.01)
    rng = np.random.default_rng(config.seed)
    for epoch in range(config.epochs):
        model.train()
        order = rng.permutation(len(train_pairs))
        total, steps = 0.0, 0
        for chunk in batched([train_pairs[i] for i in order], config.batch_size):
            if len(chunk) < 2:
                continue
            q = encoder([config.query_instruction + p["query"] for p in chunk])
            d = encoder([p["positive"] for p in chunk])
            logits = q @ d.T / config.temperature
            target = torch.arange(len(chunk), device=device)
            loss = (F.cross_entropy(logits, target) + F.cross_entropy(logits.T, target)) / 2
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total, steps = total + loss.item(), steps + 1
        log.info("Эпоха %d: loss=%.4f", epoch + 1, total / max(1, steps))
    model.eval()
    metrics.update(retrieval_metrics(encoder, val_pairs, config.query_instruction))
    model.save_pretrained(run.artifacts / "model")
    tokenizer.save_pretrained(run.artifacts / "model")
    run.save_metrics(metrics)
    return metrics
