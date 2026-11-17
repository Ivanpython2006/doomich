"""Миграции БД (Alembic). Лежат внутри пакета: работают и из исходников, и из установленного пакета."""

from __future__ import annotations

from alembic.config import Config


def alembic_config() -> Config:
    """Конфигурация Alembic без alembic.ini: адрес БД берётся из настроек (см. env.py)."""
    cfg = Config()
    cfg.set_main_option("script_location", "doomich_api:migrations")
    cfg.set_main_option("path_separator", "os")
    return cfg
