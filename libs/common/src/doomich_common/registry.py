"""Реестр моделей «Думыча».

Модели, обученные под конкретный вуз или кампус, хранятся в файловом реестре:

    <root>/<tenant>/<kind>/<scope>/versions/<version>/manifest.json
    <root>/<tenant>/<kind>/<scope>/versions/<version>/<артефакты>
    <root>/<tenant>/<kind>/<scope>/active.json

* ``tenant`` — slug вуза или ``_global`` для общих моделей (например, слово активации);
* ``kind`` — тип модели (см. :class:`ModelKind`);
* ``scope`` — область применения: slug кампуса для навигации, ``default`` для остального.

Сервер и сервисы инференса только читают реестр; ML-платформа пишет в него
(``doomich-ml registry ...``). Запись атомарная: версия сначала собирается во
временном каталоге, затем переименовывается.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

GLOBAL_TENANT = "_global"
DEFAULT_SCOPE = "default"
_SLUG_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,63}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class ModelKind(StrEnum):
    """Типы моделей, которые умеет создавать ML-платформа."""

    WAKEWORD = "wakeword"  # слово активации «Думыч» (ONNX для устройств)
    VPR = "vpr"  # распознавание места по фото: дескриптор + индекс кампуса
    LLM_LORA = "llm_lora"  # LoRA-адаптер LLM под вуз (подключается к vLLM)
    ASR = "asr"  # дообученная модель распознавания речи
    EMBEDDINGS = "embeddings"  # дообученная модель эмбеддингов для поиска


class Manifest(BaseModel):
    """Описание версии модели."""

    kind: ModelKind
    tenant: str
    scope: str = DEFAULT_SCOPE
    version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    base_model: str | None = None
    base_model_license: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    parent: str | None = None
    notes: str | None = None


class ActivePointer(BaseModel):
    version: str
    activated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    activated_by: str | None = None


class RegistryError(RuntimeError):
    pass


def _check_slug(value: str, what: str) -> str:
    if not _SLUG_RE.match(value):
        raise RegistryError(f"Недопустимое значение {what}: {value!r}")
    return value


def _check_version(value: str) -> str:
    if not _VERSION_RE.match(value):
        raise RegistryError(f"Недопустимая версия: {value!r}")
    return value


def new_version_id(now: datetime | None = None) -> str:
    """Версия по времени создания: ``20261116T120000Z``."""
    now = now or datetime.now(UTC)
    return now.strftime("%Y%m%dT%H%M%SZ")


class ModelRegistry:
    """Файловый реестр моделей."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    # ---- пути -------------------------------------------------------------
    def scope_dir(self, tenant: str, kind: ModelKind | str, scope: str = DEFAULT_SCOPE) -> Path:
        kind = ModelKind(kind)
        return self.root / _check_slug(tenant, "tenant") / kind.value / _check_slug(scope, "scope")

    def version_dir(self, tenant: str, kind: ModelKind | str, scope: str, version: str) -> Path:
        return self.scope_dir(tenant, kind, scope) / "versions" / _check_version(version)

    # ---- чтение -----------------------------------------------------------
    def get(self, tenant: str, kind: ModelKind | str, scope: str, version: str) -> Manifest:
        path = self.version_dir(tenant, kind, scope, version) / "manifest.json"
        if not path.is_file():
            raise RegistryError(f"Версия не найдена: {tenant}/{kind}/{scope}/{version}")
        return Manifest.model_validate_json(path.read_text(encoding="utf-8"))

    def versions(self, tenant: str, kind: ModelKind | str, scope: str = DEFAULT_SCOPE) -> list[Manifest]:
        base = self.scope_dir(tenant, kind, scope) / "versions"
        if not base.is_dir():
            return []
        result = []
        for child in sorted(base.iterdir()):
            manifest = child / "manifest.json"
            if manifest.is_file():
                result.append(Manifest.model_validate_json(manifest.read_text(encoding="utf-8")))
        return sorted(result, key=lambda m: m.created_at)

    def iter_all(self) -> Iterator[Manifest]:
        if not self.root.is_dir():
            return
        for manifest in sorted(self.root.glob("*/*/*/versions/*/manifest.json")):
            yield Manifest.model_validate_json(manifest.read_text(encoding="utf-8"))

    def active_pointer(self, tenant: str, kind: ModelKind | str, scope: str = DEFAULT_SCOPE) -> ActivePointer | None:
        path = self.scope_dir(tenant, kind, scope) / "active.json"
        if not path.is_file():
            return None
        return ActivePointer.model_validate_json(path.read_text(encoding="utf-8"))

    def active(
        self,
        tenant: str,
        kind: ModelKind | str,
        scope: str = DEFAULT_SCOPE,
        *,
        fallback_global: bool = True,
    ) -> Manifest | None:
        """Активная версия для вуза; если её нет — общая (``_global``)."""
        candidates = [tenant]
        if fallback_global and tenant != GLOBAL_TENANT:
            candidates.append(GLOBAL_TENANT)
        for candidate in candidates:
            pointer = self.active_pointer(candidate, kind, scope)
            if pointer is not None:
                return self.get(candidate, kind, scope, pointer.version)
        return None

    def artifact_path(self, manifest: Manifest, name: str) -> Path:
        if name not in manifest.artifacts:
            raise RegistryError(f"У версии {manifest.version} нет артефакта {name!r}")
        base = self.version_dir(manifest.tenant, manifest.kind, manifest.scope, manifest.version)
        path = (base / manifest.artifacts[name]).resolve()
        if not str(path).startswith(str(base.resolve())):
            raise RegistryError("Путь артефакта выходит за пределы каталога версии")
        return path

    # ---- запись -----------------------------------------------------------
    def register(self, manifest: Manifest, artifacts_dir: str | os.PathLike[str]) -> Path:
        """Скопировать артефакты в реестр и записать манифест (атомарно)."""
        target = self.version_dir(manifest.tenant, manifest.kind, manifest.scope, manifest.version)
        if target.exists():
            raise RegistryError(f"Версия уже существует: {target}")
        source = Path(artifacts_dir)
        for name, rel in manifest.artifacts.items():
            if not (source / rel).exists():
                raise RegistryError(f"Артефакт {name!r} не найден: {source / rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=target.parent))
        try:
            for rel in manifest.artifacts.values():
                src = source / rel
                dst = tmp / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            (tmp / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
            tmp.rename(target)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return target

    def activate(
        self,
        tenant: str,
        kind: ModelKind | str,
        scope: str,
        version: str,
        *,
        by: str | None = None,
    ) -> ActivePointer:
        self.get(tenant, kind, scope, version)  # проверка существования
        pointer = ActivePointer(version=version, activated_by=by)
        path = self.scope_dir(tenant, kind, scope) / "active.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(pointer.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)
        return pointer

    def deactivate(self, tenant: str, kind: ModelKind | str, scope: str = DEFAULT_SCOPE) -> None:
        path = self.scope_dir(tenant, kind, scope) / "active.json"
        path.unlink(missing_ok=True)

    def summary(self) -> list[dict[str, Any]]:
        """Сводка для админ-панели: все версии и отметка активной."""
        rows = []
        for manifest in self.iter_all():
            pointer = self.active_pointer(manifest.tenant, manifest.kind, manifest.scope)
            rows.append(
                {
                    "tenant": manifest.tenant,
                    "kind": manifest.kind.value,
                    "scope": manifest.scope,
                    "version": manifest.version,
                    "created_at": manifest.created_at.isoformat(),
                    "base_model": manifest.base_model,
                    "metrics": manifest.metrics,
                    "active": pointer is not None and pointer.version == manifest.version,
                }
            )
        return rows


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
