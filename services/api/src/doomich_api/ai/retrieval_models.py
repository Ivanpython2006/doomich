"""Модели для поиска: эмбеддинги и реранкер (OpenAI-совместимые API vLLM) и их fake-версии."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx
import numpy as np

from doomich_api.config import Settings

QUERY_INSTRUCTION = "Instruct: Given a question from a university student, retrieve passages that answer it\nQuery: "


class Embedder(Protocol):
    model_name: str

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    async def rerank(self, query: str, texts: list[str]) -> list[float]: ...


def _fit_dim(vec: list[float], dim: int) -> list[float]:
    """Matryoshka-усечение до размерности колонки pgvector и повторная нормализация."""
    arr = np.asarray(vec[:dim], dtype=np.float32)
    if arr.size < dim:
        arr = np.pad(arr, (0, dim - arr.size))
    norm = float(np.linalg.norm(arr))
    return (arr / norm).tolist() if norm > 0 else arr.tolist()


class OpenAIEmbedder:
    def __init__(self, settings: Settings, model: str | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.model_name = model or settings.embeddings_model
        self.base_url = settings.embeddings_base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=60)

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        step = self.settings.embeddings_batch
        for i in range(0, len(texts), step):
            batch = texts[i : i + step]
            resp = await self._client.post(
                f"{self.base_url}/embeddings", json={"model": self.model_name, "input": batch}
            )
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            out.extend(_fit_dim(d["embedding"], self.settings.embedding_dim) for d in data)
        return out

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([QUERY_INSTRUCTION + text]))[0]


_WORD = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    # грубая «стемминг»-нормализация: первые 6 букв слова — для русского этого хватает в тестах
    return [w[:6] for w in _WORD.findall(text.lower()) if len(w) > 1]


class HashingEmbedder:
    """Детерминированные эмбеддинги без модели: хэширование слов. Для тестов и демо."""

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.model_name = f"hashing-{dim}"

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in _tokens(text):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        norm = float(np.linalg.norm(v))
        if norm == 0:
            v[0] = 1.0
            norm = 1.0
        return (v / norm).tolist()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class OpenAIReranker:
    """vLLM: эндпоинт /v1/rerank (совместим с Jina/Cohere)."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.AsyncClient(timeout=30)

    async def rerank(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        resp = await self._client.post(
            f"{self.settings.reranker_base_url.rstrip('/')}/v1/rerank",
            json={"model": self.settings.reranker_model, "query": query, "documents": texts},
        )
        resp.raise_for_status()
        scores = [0.0] * len(texts)
        for item in resp.json().get("results", []):
            scores[item["index"]] = float(item.get("relevance_score", 0.0))
        return scores


class OverlapReranker:
    """Fake-реранкер: доля слов запроса, найденных во фрагменте."""

    async def rerank(self, query: str, texts: list[str]) -> list[float]:
        q = set(_tokens(query))
        if not q:
            return [0.0] * len(texts)
        return [len(q & set(_tokens(t))) / math.sqrt(len(q)) for t in texts]
