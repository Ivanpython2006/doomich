"""Зашифрованное файловое хранилище.

Личные файлы шифруются ключом пользователя, файлы вуза — мастер-ключом сервиса.
Путь не содержит имени файла: только идентификаторы.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from doomich_api.config import get_settings
from doomich_api.security import get_crypto


def _root() -> Path:
    root = get_settings().storage_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(key: str) -> Path:
    path = (_root() / key).resolve()
    if not str(path).startswith(str(_root().resolve())):
        raise ValueError("Недопустимый ключ хранилища")
    return path


def save_user_file(user_id: uuid.UUID, wrapped_dek: bytes, data: bytes, kind: str) -> str:
    key = f"u/{user_id}/{kind}/{uuid.uuid4()}.bin"
    blob = get_crypto().encrypt(wrapped_dek, user_id, data, purpose=f"file:{key}")
    _write(key, blob)
    return key


def load_user_file(user_id: uuid.UUID, wrapped_dek: bytes, key: str) -> bytes:
    return get_crypto().decrypt(wrapped_dek, user_id, _path(key).read_bytes(), purpose=f"file:{key}")


def save_org_file(owner: str, data: bytes) -> str:
    key = f"org/{owner}/{uuid.uuid4()}.bin"
    _write(key, get_crypto().seal(data, purpose=f"file:{key}"))
    return key


def load_org_file(key: str) -> bytes:
    return get_crypto().unseal(_path(key).read_bytes(), purpose=f"file:{key}")


def delete_file(key: str | None) -> None:
    if key:
        _path(key).unlink(missing_ok=True)


def delete_user_tree(user_id: uuid.UUID) -> None:
    base = _path(f"u/{user_id}")
    if base.exists():
        for path in sorted(base.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        base.rmdir()


def _write(key: str, blob: bytes) -> None:
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, path)
