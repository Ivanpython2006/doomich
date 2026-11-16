"""Общее для пайплайнов: воспроизводимость, устройство, JSONL, каталоги запусков, регистрация в реестре."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from collections.abc import Iterable, Iterator
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from doomich_common.registry import Manifest, ModelKind, ModelRegistry, new_version_id

log = logging.getLogger("doomich_ml")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )


def seed_everything(seed: int = 42) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


def pick_device(preferred: str = "auto") -> str:
    import torch

    if preferred != "auto":
        return preferred
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def read_jsonl(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: str | os.PathLike[str], rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def split(items: list[Any], val_fraction: float, seed: int = 42) -> tuple[list[Any], list[Any]]:
    rng = random.Random(seed)
    shuffled = items[:]
    rng.shuffle(shuffled)
    n_val = max(1, int(len(shuffled) * val_fraction)) if len(shuffled) > 1 else 0
    return shuffled[n_val:], shuffled[:n_val]


def batched(items: list[Any], size: int) -> Iterator[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def file_digest(paths: Iterable[Path]) -> str:
    """Отпечаток набора данных: попадает в манифест, чтобы версия модели была воспроизводима."""
    h = hashlib.sha256()
    for path in sorted(paths):
        h.update(str(path.name).encode())
        h.update(path.read_bytes() if path.is_file() else b"")
    return h.hexdigest()[:16]


class Run:
    """Каталог запуска обучения: конфиг, метрики, артефакты."""

    def __init__(self, root: str | os.PathLike[str], kind: str, name: str | None = None) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.dir = Path(root) / kind / (name or stamp)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.artifacts = self.dir / "artifacts"
        self.artifacts.mkdir(exist_ok=True)

    def save_config(self, config: Any) -> None:
        data = asdict(config) if is_dataclass(config) else dict(config)
        (self.dir / "config.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

    def save_metrics(self, metrics: dict[str, float]) -> None:
        (self.dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Метрики: %s", metrics)

    def load_metrics(self) -> dict[str, float]:
        path = self.dir / "metrics.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def register_run(
    *,
    registry_dir: str | os.PathLike[str],
    run_dir: Path,
    kind: ModelKind,
    tenant: str,
    scope: str = "default",
    artifacts: dict[str, str],
    base_model: str | None,
    base_model_license: str | None,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    activate: bool = False,
    notes: str | None = None,
) -> Manifest:
    registry = ModelRegistry(registry_dir)
    previous = registry.active(tenant, kind, scope, fallback_global=False)
    metrics_path = run_dir / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    manifest = Manifest(
        kind=kind,
        tenant=tenant,
        scope=scope,
        version=new_version_id(),
        base_model=base_model,
        base_model_license=base_model_license,
        artifacts=artifacts,
        metrics={k: float(v) for k, v in metrics.items() if isinstance(v, int | float)},
        params=params or {},
        data=data or {},
        parent=previous.version if previous else None,
        notes=notes,
    )
    registry.register(manifest, run_dir / "artifacts")
    if activate:
        registry.activate(tenant, kind, scope, manifest.version, by="doomich-ml")
    log.info("Зарегистрирована модель %s/%s/%s версии %s", tenant, kind.value, scope, manifest.version)
    return manifest
