"""Настройки сервиса. Все параметры задаются переменными окружения с префиксом ``DOOMICH_``."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOOMICH_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    public_base_url: str = "http://localhost:8000"
    # страница загрузки приложений — ссылка на публичной странице приглашения
    downloads_url: str | None = None
    # серверы расписания во внутренней сети вуза, к которым можно обращаться (JSON-список имён или IP).
    # Остальные внутренние адреса для источников расписания запрещены (защита от SSRF).
    schedule_source_private_hosts: list[str] = Field(default_factory=list)

    # --- БД и очереди ---
    database_url: str = "postgresql+asyncpg://doomich:doomich@localhost:5432/doomich"
    redis_url: str = "redis://localhost:6379/0"
    db_pool_size: int = 10

    # --- секреты ---
    jwt_secret: SecretStr = SecretStr("dev-only-jwt-secret-change-me-0123456789")
    # 32 байта в base64 — мастер-ключ, которым шифруются ключи пользователей
    master_key: SecretStr = SecretStr(base64.b64encode(b"dev-only-master-key-change-me!!!").decode())
    # «перец» для хэшей кодов приглашения
    invite_pepper: SecretStr = SecretStr("dev-only-invite-pepper")

    access_token_ttl_s: int = 15 * 60
    refresh_token_ttl_s: int = 30 * 24 * 3600
    admin_token_ttl_s: int = 8 * 3600

    # Argon2id (в тестах уменьшаем, чтобы не тормозить)
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 64 * 1024
    argon2_parallelism: int = 2

    # --- хранилище файлов ---
    storage_dir: Path = Path("./storage")
    registry_dir: Path = Path("./registry")
    # где реестр моделей смонтирован внутри контейнера vLLM (для LoRA-адаптеров вузов)
    vllm_registry_dir: str = "/registry"

    # --- ИИ-провайдеры ---
    llm_provider: Literal["openai", "fake"] = "openai"
    llm_base_url: str = "http://localhost:8001/v1"
    llm_api_key: SecretStr = SecretStr("not-needed")
    llm_model: str = "doomich-llm"
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.4
    llm_timeout_s: float = 120.0
    llm_context_chars: int = 24_000

    embeddings_provider: Literal["openai", "fake"] = "openai"
    embeddings_base_url: str = "http://localhost:8001/v1"
    embeddings_model: str = "doomich-embed"
    embedding_dim: int = 1024
    embeddings_batch: int = 32

    reranker_provider: Literal["openai", "none", "fake"] = "openai"
    reranker_base_url: str = "http://localhost:8001"
    reranker_model: str = "doomich-rerank"

    asr_provider: Literal["http", "fake"] = "http"
    asr_base_url: str = "http://localhost:8010"
    tts_provider: Literal["http", "fake"] = "http"
    tts_base_url: str = "http://localhost:8020"
    tts_format: Literal["wav", "ogg"] = "wav"
    nav_base_url: str = "http://localhost:8030"

    # --- ограничения ---
    max_upload_mb: int = 20
    max_documents_per_user: int = 50
    max_pages_per_document: int = 300
    max_lecture_mb: int = 500
    max_lecture_minutes: int = 120
    max_voice_seconds: int = 60
    default_history_days: int = 90
    messages_per_day_limit: int = 300

    clamav_host: str | None = None
    clamav_port: int = 3310

    # --- прочее ---
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    log_level: str = "INFO"
    run_tasks_inline: bool = False  # выполнять фоновые задачи сразу (dev/тесты без Celery)

    @field_validator("master_key")
    @classmethod
    def _check_master_key(cls, value: SecretStr) -> SecretStr:
        raw = base64.b64decode(value.get_secret_value())
        if len(raw) != 32:
            raise ValueError("DOOMICH_MASTER_KEY должен быть 32 байтами в base64")
        return value

    @property
    def master_key_bytes(self) -> bytes:
        return base64.b64decode(self.master_key.get_secret_value())

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
