from __future__ import annotations

import base64
import secrets

import pytest
from doomich_api.config import Settings
from pydantic import ValidationError


def test_prod_refuses_example_secrets(monkeypatch):
    for name in ("DOOMICH_JWT_SECRET", "DOOMICH_MASTER_KEY", "DOOMICH_INVITE_PEPPER"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError, match=r"DOOMICH_JWT_SECRET.*DOOMICH_MASTER_KEY.*DOOMICH_INVITE_PEPPER"):
        Settings(env="prod", _env_file=None)


def test_prod_accepts_generated_secrets():
    settings = Settings(
        env="prod",
        jwt_secret=secrets.token_hex(32),
        master_key=base64.b64encode(secrets.token_bytes(32)).decode(),
        invite_pepper=secrets.token_hex(16),
        _env_file=None,
    )
    assert settings.env == "prod"
    # в разработке примеры секретов допустимы
    assert Settings(env="dev", _env_file=None).env == "dev"
