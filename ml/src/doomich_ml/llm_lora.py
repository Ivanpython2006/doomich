"""LoRA-адаптер LLM под конкретный вуз.

Зачем: базовая модель не знает терминов, правил и стиля конкретного вуза. Факты по-прежнему
лучше давать через поиск по базе знаний (RAG), а адаптер учит модель формату и лексике вуза:
названиям подразделений, принятым сокращениям, тону ответов.

Данные — чат-примеры в JSONL: {"messages": [{"role": "system"|"user"|"assistant", "content": ...}]}.
Их собирают из FAQ вуза (``faq_to_chat``) и синтетических вопросов по документам (``synth_qa``,
генерирует учительская модель через OpenAI-совместимый API).

Результат — каталог адаптера PEFT (adapter_config.json + adapter_model.safetensors), который
vLLM подключает к базовой модели на лету (multi-LoRA): один GPU обслуживает все вузы.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch

from doomich_ml.common import Run, log, pick_device, read_jsonl, seed_everything, split, write_jsonl

PERSONA = (
    "Ты — Думыч, дружелюбный ИИ-помощник студентов и преподавателей {university}. "
    "Отвечай кратко и по делу, на языке вопроса."
)


def faq_to_chat(faq_path: Path, university: str) -> list[dict[str, Any]]:
    """FAQ в JSONL {"question", "answer"} → чат-примеры с системным промптом «Думыча»."""
    system = PERSONA.format(university=university)
    return [
        {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": row["question"]},
                {"role": "assistant", "content": row["answer"]},
            ]
        }
        for row in read_jsonl(faq_path)
        if row.get("question") and row.get("answer")
    ]


def synth_qa(
    texts: list[str], *, llm_url: str, model: str, university: str, per_chunk: int = 3, chunk_chars: int = 3000
) -> list[dict[str, Any]]:
    """Сгенерировать пары «вопрос–ответ» по документам вуза учительской моделью."""
    import httpx

    system = PERSONA.format(university=university)
    examples = []
    prompt = (
        "По тексту ниже составь {n} вопросов, которые реально задал бы студент, и точные ответы только по тексту. "
        'Ответ — JSON-массив: [{{"question": "...", "answer": "..."}}].\n\nТекст:\n{chunk}'
    )
    with httpx.Client(timeout=180) as client:
        for text in texts:
            for start in range(0, len(text), chunk_chars):
                chunk = text[start : start + chunk_chars]
                resp = client.post(
                    f"{llm_url.rstrip('/')}/chat/completions",
                    json={
                        "model": model,
                        "temperature": 0.3,
                        "messages": [{"role": "user", "content": prompt.format(n=per_chunk, chunk=chunk)}],
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                match = re.search(r"\[.*\]", content, flags=re.S)
                for pair in json.loads(match.group(0)) if match else []:
                    if pair.get("question") and pair.get("answer"):
                        examples.append(
                            {
                                "messages": [
                                    {"role": "system", "content": system},
                                    {"role": "user", "content": pair["question"]},
                                    {"role": "assistant", "content": pair["answer"]},
                                ]
                            }
                        )
    return examples


@dataclass
class LoraTrainConfig:
    base_model: str
    data_file: str
    base_model_license: str = "Apache-2.0"
    val_fraction: float = 0.1
    rank: int = 16
    alpha: int = 32
    dropout: float = 0.05
    target_modules: list[str] = field(
        default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    )
    epochs: int = 2
    lr: float = 2e-4
    batch_size: int = 4
    grad_accum: int = 4
    max_len: int = 1024
    eval_generate: int = 20
    seed: int = 42
    device: str = "auto"


def encode_example(tokenizer, messages: list[dict[str, str]], max_len: int) -> dict[str, list[int]] | None:
    """Токены диалога; лосс считается только по последнему ответу ассистента."""
    if not messages or messages[-1]["role"] != "assistant":
        return None
    prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages, tokenize=False)
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    full_ids = tokenizer(full, add_special_tokens=False)["input_ids"][:max_len]
    if len(full_ids) <= len(prompt_ids):
        return None
    labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids) :]
    return {"input_ids": full_ids, "labels": labels[: len(full_ids)]}


def _collate(batch: list[dict[str, list[int]]], pad_id: int) -> dict[str, torch.Tensor]:
    width = max(len(x["input_ids"]) for x in batch)
    ids = torch.full((len(batch), width), pad_id, dtype=torch.long)
    labels = torch.full((len(batch), width), -100, dtype=torch.long)
    mask = torch.zeros((len(batch), width), dtype=torch.long)
    for i, x in enumerate(batch):
        n = len(x["input_ids"])
        ids[i, :n] = torch.tensor(x["input_ids"])
        labels[i, :n] = torch.tensor(x["labels"])
        mask[i, :n] = 1
    return {"input_ids": ids, "labels": labels, "attention_mask": mask}


def token_f1(prediction: str, reference: str) -> float:
    pred, ref = prediction.lower().split(), reference.lower().split()
    if not pred or not ref:
        return float(pred == ref)
    common = sum(min(pred.count(t), ref.count(t)) for t in set(pred))
    if common == 0:
        return 0.0
    precision, recall = common / len(pred), common / len(ref)
    return 2 * precision * recall / (precision + recall)


def train(config: LoraTrainConfig, run: Run) -> dict[str, float]:
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    seed_everything(config.seed)
    device = pick_device(config.device)
    tokenizer = AutoTokenizer.from_pretrained(config.base_model)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else torch.float32
    model = AutoModelForCausalLM.from_pretrained(config.base_model, torch_dtype=dtype).to(device)
    present = {name.rsplit(".", 1)[-1] for name, _ in model.named_modules()}
    targets = [m for m in config.target_modules if m in present]
    model = get_peft_model(
        model,
        LoraConfig(
            r=config.rank,
            lora_alpha=config.alpha,
            lora_dropout=config.dropout,
            target_modules=targets,
            task_type="CAUSAL_LM",
        ),
    )
    rows = read_jsonl(config.data_file)
    train_rows, val_rows = split(rows, config.val_fraction, config.seed)
    encode = [encode_example(tokenizer, r["messages"], config.max_len) for r in train_rows]
    train_set = [e for e in encode if e]
    val_set = [e for e in (encode_example(tokenizer, r["messages"], config.max_len) for r in val_rows) if e]
    if not train_set:
        raise ValueError("Нет обучающих примеров с ответом ассистента")
    log.info("Примеров: обучение %d, проверка %d; LoRA на %s", len(train_set), len(val_set), targets)

    pad = tokenizer.pad_token_id
    loader = torch.utils.data.DataLoader(
        train_set, batch_size=config.batch_size, shuffle=True, collate_fn=lambda b: _collate(b, pad)
    )
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=config.lr)
    total_steps = max(1, math.ceil(len(loader) / config.grad_accum) * config.epochs)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda s: min(1.0, (s + 1) / max(1, total_steps // 10)) * max(0.0, 1 - s / total_steps)
    )

    def evaluate() -> float:
        if not val_set:
            return float("nan")
        model.eval()
        losses = []
        with torch.inference_mode():
            for i in range(0, len(val_set), config.batch_size):
                batch = {k: v.to(device) for k, v in _collate(val_set[i : i + config.batch_size], pad).items()}
                losses.append(model(**batch).loss.item())
        return float(sum(losses) / len(losses))

    metrics = {"val_loss_before": evaluate()}
    step = 0
    for epoch in range(config.epochs):
        model.train()
        for i, batch in enumerate(loader):
            batch = {k: v.to(device) for k, v in batch.items()}
            loss = model(**batch).loss / config.grad_accum
            loss.backward()
            if (i + 1) % config.grad_accum == 0 or i + 1 == len(loader):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
                step += 1
        log.info("Эпоха %d, шаг %d, val_loss=%.4f", epoch + 1, step, evaluate())
    metrics["val_loss"] = evaluate()

    if val_rows and config.eval_generate:
        model.eval()
        scores = []
        for row in val_rows[: config.eval_generate]:
            messages = row["messages"]
            prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
            ids = tokenizer(prompt, return_tensors="pt", add_special_tokens=False).to(device)
            with torch.inference_mode():
                out = model.generate(**ids, max_new_tokens=128, do_sample=False, pad_token_id=pad)
            answer = tokenizer.decode(out[0, ids["input_ids"].shape[1] :], skip_special_tokens=True)
            scores.append(token_f1(answer, messages[-1]["content"]))
        metrics["val_token_f1"] = float(sum(scores) / len(scores))

    model.save_pretrained(run.artifacts / "adapter")
    tokenizer.save_pretrained(run.artifacts / "adapter")
    run.save_metrics(metrics)
    write_jsonl(run.dir / "val.jsonl", val_rows)
    return metrics
