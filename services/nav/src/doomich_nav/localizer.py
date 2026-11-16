"""Определение места в кампусе по кадрам камеры и/или текстовому описанию.

Артефакты кампуса создаёт ML-платформа (``doomich-ml vpr build``) и кладёт в реестр моделей:

* ``descriptor.onnx`` — сеть «изображение → дескриптор места» (DINOv2/MegaLoc, дообученная на кампусе);
* ``index.npz``       — дескрипторы эталонных фото: ``embeddings`` [N, D], ``node_keys`` [N], ``headings`` [N];
* ``captions.json``   — описания узлов: текст, теги, надписи (номера аудиторий), этаж, корпус.

Кадры обрабатываются в памяти и не сохраняются.
"""

from __future__ import annotations

import io
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

_WORD = re.compile(r"[a-zа-яё]+|\d+[a-zа-я]?", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    tokens = []
    for raw in _WORD.findall(text.lower().replace("ё", "е")):
        tokens.append(raw if raw[0].isdigit() else raw[:6])  # грубый стемминг: «столовую» → «столов»
    return tokens


@dataclass
class Candidate:
    node: str
    score: float
    floor: int | None = None
    building: str | None = None
    heading: float | None = None
    title: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class TextIndex:
    """BM25 по описаниям узлов; номера аудиторий и надписи весят больше слов."""

    def __init__(self, captions: dict[str, dict[str, Any]], k1: float = 1.2, b: float = 0.75) -> None:
        self.captions = captions
        self.docs: dict[str, Counter[str]] = {}
        for node, info in captions.items():
            tokens = tokenize(" ".join([info.get("text", ""), *info.get("tags", [])]))
            tokens += [t for ocr in info.get("ocr", []) for t in tokenize(ocr)] * 3
            self.docs[node] = Counter(tokens)
        self.avg_len = np.mean([sum(c.values()) for c in self.docs.values()]) if self.docs else 1.0
        df: Counter[str] = Counter()
        for counter in self.docs.values():
            df.update(counter.keys())
        n = max(1, len(self.docs))
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query: str) -> dict[str, float]:
        terms = tokenize(query)
        result: dict[str, float] = {}
        for node, counter in self.docs.items():
            length = sum(counter.values())
            score = 0.0
            for term in terms:
                tf = counter.get(term, 0)
                if not tf:
                    continue
                boost = 3.0 if term[0].isdigit() else 1.0
                score += (
                    boost
                    * self.idf.get(term, 0.0)
                    * tf
                    * (self.k1 + 1)
                    / (tf + self.k1 * (1 - self.b + self.b * length / self.avg_len))
                )
            if score > 0:
                result[node] = score
        return result


class Localizer:
    def __init__(self, directory: Path, params: dict[str, Any]) -> None:
        import onnxruntime as ort

        self.params = params
        self.input_size = int(params.get("input_size", 224))
        self.mean = np.asarray(params.get("mean", [0.485, 0.456, 0.406]), dtype=np.float32).reshape(1, 3, 1, 1)
        self.std = np.asarray(params.get("std", [0.229, 0.224, 0.225]), dtype=np.float32).reshape(1, 3, 1, 1)
        self.session = ort.InferenceSession(str(directory / "descriptor.onnx"), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        data = np.load(directory / "index.npz", allow_pickle=False)
        self.embeddings = data["embeddings"].astype(np.float32)
        self.node_keys = [str(k) for k in data["node_keys"]]
        self.headings = data["headings"] if "headings" in data else np.full(len(self.node_keys), np.nan)
        captions_path = directory / "captions.json"
        self.captions: dict[str, dict[str, Any]] = (
            json.loads(captions_path.read_text(encoding="utf-8")) if captions_path.exists() else {}
        )
        self.text_index = TextIndex(self.captions)
        self.temperature = float(params.get("temperature", 0.05))

    def _preprocess(self, image_bytes: bytes) -> np.ndarray:
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = image.size
        scale = self.input_size / min(w, h)
        image = image.resize((max(1, round(w * scale)), max(1, round(h * scale))))
        w, h = image.size
        left, top = (w - self.input_size) // 2, (h - self.input_size) // 2
        image = image.crop((left, top, left + self.input_size, top + self.input_size))
        array = np.asarray(image, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        return (array - self.mean) / self.std

    def describe(self, image_bytes: bytes) -> np.ndarray:
        out = self.session.run(None, {self.input_name: self._preprocess(image_bytes)})[0].reshape(-1)
        norm = np.linalg.norm(out)
        return out / norm if norm > 0 else out

    def image_scores(self, images: list[bytes]) -> tuple[dict[str, float], dict[str, float]]:
        """Сумма по кадрам лучших сходств с фото каждого узла и угол лучшего совпадения."""
        per_node: dict[str, float] = defaultdict(float)
        best_heading: dict[str, tuple[float, float]] = {}
        for image in images:
            sims = self.embeddings @ self.describe(image)
            frame_best: dict[str, float] = {}
            for idx, sim in enumerate(sims):
                node = self.node_keys[idx]
                if sim > frame_best.get(node, -1.0):
                    frame_best[node] = float(sim)
                    if sim > best_heading.get(node, (-1.0, 0.0))[0]:
                        best_heading[node] = (float(sim), float(self.headings[idx]))
            for node, value in frame_best.items():
                per_node[node] += value
        count = max(1, len(images))
        return {n: v / count for n, v in per_node.items()}, {n: h for n, (_s, h) in best_heading.items()}

    def locate(self, images: list[bytes], text: str | None, top_k: int = 3) -> dict[str, Any]:
        combined: dict[str, float] = {}
        headings: dict[str, float] = {}
        if images:
            sims, headings = self.image_scores(images)
            values = np.asarray(list(sims.values()))
            exps = np.exp((values - values.max()) / self.temperature)
            probs = exps / exps.sum()
            combined = dict(zip(sims.keys(), probs.tolist(), strict=True))
        if text:
            bm25 = self.text_index.scores(text)
            if bm25:
                total = sum(bm25.values())
                text_probs = {n: s / total for n, s in bm25.items()}
                weight = 0.5 if combined else 1.0
                for node in set(combined) | set(text_probs):
                    combined[node] = (1 - weight) * combined.get(node, 0.0) + weight * text_probs.get(node, 0.0)
        if not combined:
            return {
                "candidates": [],
                "confidence": 0.0,
                "need_clarification": True,
                "question": "Не узнаю это место. Опишите, что видите рядом, или наведите камеру на номер двери.",
            }
        ranked = sorted(combined.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        candidates = []
        for node, score in ranked:
            info = self.captions.get(node, {})
            heading = headings.get(node)
            candidates.append(
                Candidate(
                    node=node,
                    score=round(float(score), 4),
                    floor=info.get("floor"),
                    building=info.get("building"),
                    heading=None if heading is None or math.isnan(heading) else float(heading),
                    title=info.get("title"),
                ).as_dict()
            )
        top = float(ranked[0][1])
        margin = top - float(ranked[1][1] if len(ranked) > 1 else 0.0)
        min_conf = float(self.params.get("min_confidence", 0.55))
        min_margin = float(self.params.get("min_margin", 0.15))
        need = bool(top < min_conf or margin < min_margin)
        question = None
        if need and len(candidates) > 1:
            a = candidates[0].get("title") or candidates[0]["node"]
            b = candidates[1].get("title") or candidates[1]["node"]
            question = f"Вы рядом с «{a}» или «{b}»? Можно навести камеру на номер ближайшей двери."
        return {"candidates": candidates, "confidence": round(top, 4), "need_clarification": need, "question": question}
