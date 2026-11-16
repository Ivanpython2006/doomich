"""Выбор модели под вуз: LoRA-адаптер из реестра моделей или базовая модель."""

from __future__ import annotations

import logging

from doomich_common.registry import ModelKind, ModelRegistry, RegistryError

from doomich_api.ai import Providers
from doomich_api.config import Settings
from doomich_api.context import UserContext

log = logging.getLogger(__name__)
_loaded: set[str] = set()


async def resolve_llm_model(user: UserContext, providers: Providers, settings: Settings) -> str:
    """Порядок: активный LoRA вуза в реестре → модель из настроек вуза → модель по умолчанию."""
    fallback = str(user.tenant_settings.get("llm_model") or settings.llm_model)
    try:
        manifest = ModelRegistry(settings.registry_dir).active(
            user.university_slug, ModelKind.LLM_LORA, fallback_global=False
        )
    except RegistryError:
        return fallback
    if manifest is None:
        return fallback
    name = f"{manifest.tenant}-{manifest.version}"
    if name in _loaded:
        return name
    # путь к адаптеру так, как его видит контейнер vLLM (реестр смонтирован в /registry)
    adapter = (
        f"{settings.vllm_registry_dir}/{manifest.tenant}/llm_lora/{manifest.scope}/versions/"
        f"{manifest.version}/{manifest.artifacts.get('adapter', 'adapter')}"
    )
    loader = getattr(providers.llm, "load_lora", None)
    if loader is not None and await loader(name, adapter):
        _loaded.add(name)
        return name
    log.warning("LoRA %s недоступен, используем базовую модель", name)
    return fallback
