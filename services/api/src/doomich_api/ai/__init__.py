"""Доступ к ИИ-моделям. Провайдеры создаются один раз и могут быть подменены в тестах."""

from __future__ import annotations

from dataclasses import dataclass

from doomich_api.ai.llm import FakeLlm, LlmProvider, OpenAICompatibleLlm
from doomich_api.ai.retrieval_models import (
    Embedder,
    HashingEmbedder,
    OpenAIEmbedder,
    OpenAIReranker,
    OverlapReranker,
    Reranker,
)
from doomich_api.ai.speech import AsrClient, FakeAsr, FakeTts, HttpAsrClient, HttpTtsClient, TtsClient
from doomich_api.config import Settings, get_settings


@dataclass
class Providers:
    llm: LlmProvider
    embedder: Embedder
    reranker: Reranker | None
    asr: AsrClient
    tts: TtsClient


def build_providers(settings: Settings) -> Providers:
    llm = FakeLlm() if settings.llm_provider == "fake" else OpenAICompatibleLlm(settings)
    embedder = (
        HashingEmbedder(settings.embedding_dim) if settings.embeddings_provider == "fake" else OpenAIEmbedder(settings)
    )
    reranker: Reranker | None
    if settings.reranker_provider == "openai":
        reranker = OpenAIReranker(settings)
    elif settings.reranker_provider == "fake":
        reranker = OverlapReranker()
    else:
        reranker = None
    asr = FakeAsr() if settings.asr_provider == "fake" else HttpAsrClient(settings)
    tts = FakeTts() if settings.tts_provider == "fake" else HttpTtsClient(settings)
    return Providers(llm=llm, embedder=embedder, reranker=reranker, asr=asr, tts=tts)


_providers: Providers | None = None


def get_providers() -> Providers:
    global _providers
    if _providers is None:
        _providers = build_providers(get_settings())
    return _providers


def set_providers(providers: Providers | None) -> None:
    global _providers
    _providers = providers
