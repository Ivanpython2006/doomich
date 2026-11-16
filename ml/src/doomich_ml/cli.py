"""Командная строка ML-платформы «Думыча».

Примеры:

    doomich-ml registry list --registry ./registry
    doomich-ml wakeword synth --tts-url http://localhost:8020 --voice ru-1 --voice ru-2 --out data/wakeword
    doomich-ml wakeword train --data data/wakeword --runs runs
    doomich-ml vpr train --campus data/msu/main --base-model facebook/dinov2-small --runs runs
    doomich-ml llm train --base-model Qwen/Qwen3.5-9B --data data/msu/chat.jsonl --runs runs
    doomich-ml register runs/vpr/20261116T120000Z --kind vpr --tenant msu --scope main --activate
    doomich-ml build ml/configs/demo.toml          # все модели вуза по одному конфигу с проверкой качества
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import fields
from pathlib import Path
from typing import Any

import typer
from doomich_common.registry import ModelKind, ModelRegistry

from doomich_ml.common import Run, read_jsonl, register_run, setup_logging, write_jsonl

app = typer.Typer(help="ML-платформа «Думыча»: модели под вузы и кампусы", no_args_is_help=True)
registry_app = typer.Typer(help="Реестр версий моделей", no_args_is_help=True)
wake_app = typer.Typer(help="Слово активации «Думыч»", no_args_is_help=True)
vpr_app = typer.Typer(help="Навигация: распознавание места по фото", no_args_is_help=True)
llm_app = typer.Typer(help="LoRA-адаптеры LLM под вуз", no_args_is_help=True)
asr_app = typer.Typer(help="Дообучение распознавания речи", no_args_is_help=True)
embed_app = typer.Typer(help="Дообучение эмбеддингов для поиска", no_args_is_help=True)
for sub, name in (
    (registry_app, "registry"),
    (wake_app, "wakeword"),
    (vpr_app, "vpr"),
    (llm_app, "llm"),
    (asr_app, "asr"),
    (embed_app, "embed"),
):
    app.add_typer(sub, name=name)

REGISTRY = typer.Option("./registry", "--registry", envvar="DOOMICH_REGISTRY_DIR", help="Каталог реестра моделей")
RUNS = typer.Option("./runs", "--runs", help="Каталог запусков обучения")

# Минимальные требования к качеству, без которых версия не активируется
DEFAULT_GATES: dict[str, dict[str, tuple[str, float]]] = {
    "wakeword": {"frr": ("<=", 0.08), "false_alarms_per_hour": ("<=", 1.0)},
    "vpr": {"recall_at_1": (">=", 0.80)},
    "llm_lora": {},
    "asr": {},
    "embeddings": {},
}


@app.callback()
def main(verbose: bool = typer.Option(False, "-v", "--verbose")) -> None:
    setup_logging(verbose)


# ------------------------------------------------------------------ реестр
@registry_app.command("list")
def registry_list(registry: Path = REGISTRY) -> None:
    rows = ModelRegistry(registry).summary()
    if not rows:
        typer.echo("Реестр пуст")
    for r in rows:
        mark = "*" if r["active"] else " "
        typer.echo(
            f"{mark} {r['tenant']:<16} {r['kind']:<11} {r['scope']:<12} {r['version']}  {json.dumps(r['metrics'])}"
        )


@registry_app.command("activate")
def registry_activate(
    tenant: str, kind: ModelKind, version: str, scope: str = "default", registry: Path = REGISTRY
) -> None:
    ModelRegistry(registry).activate(tenant, kind, scope, version, by="cli")
    typer.echo(f"Активирована {tenant}/{kind.value}/{scope} → {version}")


@registry_app.command("show")
def registry_show(
    tenant: str, kind: ModelKind, version: str, scope: str = "default", registry: Path = REGISTRY
) -> None:
    typer.echo(ModelRegistry(registry).get(tenant, kind, scope, version).model_dump_json(indent=2))


# ------------------------------------------------------------------ регистрация
ARTIFACTS: dict[ModelKind, dict[str, str]] = {
    ModelKind.WAKEWORD: {"onnx": "wakeword.onnx", "config": "wakeword.json"},
    ModelKind.VPR: {"descriptor": "descriptor.onnx", "index": "index.npz", "captions": "captions.json"},
    ModelKind.LLM_LORA: {"adapter": "adapter"},
    ModelKind.ASR: {"model": "model"},
    ModelKind.EMBEDDINGS: {"model": "model"},
}


def check_gates(kind: str, metrics: dict[str, float], gates: dict[str, Any] | None = None) -> list[str]:
    failures = []
    rules = dict(DEFAULT_GATES.get(kind, {}))
    for name, rule in (gates or {}).items():
        rules[name] = tuple(rule)
    for name, (op, value) in rules.items():
        actual = metrics.get(name)
        if actual is None:
            failures.append(f"нет метрики {name}")
        elif (op == ">=" and actual < value) or (op == "<=" and actual > value):
            failures.append(f"{name}={actual:.4f}, нужно {op} {value}")
    return failures


@app.command()
def register(
    run_dir: Path,
    kind: ModelKind = typer.Option(...),
    tenant: str = typer.Option(..., help="slug вуза или _global"),
    scope: str = "default",
    activate: bool = False,
    force: bool = typer.Option(False, help="Активировать, даже если метрики ниже порогов"),
    registry: Path = REGISTRY,
) -> None:
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    metrics = (
        json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        if (run_dir / "metrics.json").exists()
        else {}
    )
    failures = check_gates(kind.value, metrics)
    if failures and activate and not force:
        typer.echo("Качество ниже порогов, версия будет зарегистрирована без активации: " + "; ".join(failures))
        activate = False
    params = (
        json.loads((run_dir / "params.json").read_text(encoding="utf-8")) if (run_dir / "params.json").exists() else {}
    )
    manifest = register_run(
        registry_dir=registry,
        run_dir=run_dir,
        kind=kind,
        tenant=tenant,
        scope=scope,
        artifacts=ARTIFACTS[kind],
        base_model=config.get("base_model"),
        base_model_license=config.get("base_model_license"),
        params=params,
        data={"source": config.get("data_dir") or config.get("campus_dir") or config.get("data_file")},
        activate=activate,
    )
    typer.echo(
        f"{manifest.tenant}/{manifest.kind.value}/{manifest.scope} версия {manifest.version}"
        + (" (активна)" if activate else "")
    )


# ------------------------------------------------------------------ слово активации
@wake_app.command("synth")
def wake_synth(
    out: Path = typer.Option(...),
    tts_url: str = typer.Option("http://localhost:8020"),
    voice: list[str] = typer.Option(..., help="Идентификаторы голосов сервиса TTS"),
) -> None:
    from doomich_ml.wakeword import synthesize

    typer.echo(synthesize(out, tts_url=tts_url, voices=voice))


@wake_app.command("train")
def wake_train(data: Path = typer.Option(...), noise: Path | None = None, epochs: int = 20, runs: Path = RUNS) -> str:
    from doomich_ml.wakeword import WakeConfig, train

    config = WakeConfig(data_dir=str(data), noise_dir=str(noise) if noise else None, epochs=epochs)
    run = Run(runs, "wakeword")
    run.save_config(config)
    metrics = train(config, run)
    (run.dir / "params.json").write_text(
        (run.artifacts / "wakeword.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    typer.echo(f"Готово: {run.dir}\n{json.dumps(metrics, ensure_ascii=False)}")
    return str(run.dir)


# ------------------------------------------------------------------ навигация
@vpr_app.command("train")
def vpr_train(
    campus: Path = typer.Option(..., help="Каталог кампуса: photos/<узел>/*.jpg и nodes.json"),
    base_model: str = "facebook/dinov2-small",
    input_size: int = 224,
    epochs: int = 10,
    caption_url: str | None = None,
    caption_model: str | None = None,
    runs: Path = RUNS,
) -> str:
    from doomich_ml.vpr import VprConfig, registry_params, train

    config = VprConfig(
        campus_dir=str(campus),
        base_model=base_model,
        input_size=input_size,
        epochs=epochs,
        caption_url=caption_url,
        caption_model=caption_model,
    )
    run = Run(runs, "vpr")
    run.save_config(config)
    metrics = train(config, run)
    (run.dir / "params.json").write_text(json.dumps(registry_params(config)), encoding="utf-8")
    typer.echo(f"Готово: {run.dir}\n{json.dumps(metrics, ensure_ascii=False)}")
    return str(run.dir)


# ------------------------------------------------------------------ LLM
@llm_app.command("prepare")
def llm_prepare(
    out: Path = typer.Option(...),
    university: str = typer.Option(..., help="Название вуза для системного промпта"),
    faq: Path | None = None,
    docs: Path | None = typer.Option(None, help="Каталог .txt/.md документов вуза для синтетических вопросов"),
    llm_url: str | None = None,
    llm_model: str | None = None,
) -> None:
    from doomich_ml.llm_lora import faq_to_chat, synth_qa

    rows = faq_to_chat(faq, university) if faq else []
    if docs and llm_url and llm_model:
        texts = [p.read_text(encoding="utf-8") for p in sorted(docs.glob("**/*")) if p.suffix in {".txt", ".md"}]
        rows += synth_qa(texts, llm_url=llm_url, model=llm_model, university=university)
    typer.echo(f"Примеров: {write_jsonl(out, rows)} → {out}")


@llm_app.command("train")
def llm_train(
    base_model: str = typer.Option(...),
    data: Path = typer.Option(...),
    epochs: int = 2,
    rank: int = 16,
    runs: Path = RUNS,
) -> str:
    from doomich_ml.llm_lora import LoraTrainConfig, train

    config = LoraTrainConfig(base_model=base_model, data_file=str(data), epochs=epochs, rank=rank)
    run = Run(runs, "llm_lora")
    run.save_config(config)
    metrics = train(config, run)
    (run.dir / "params.json").write_text(json.dumps({"rank": rank, "base_model": base_model}), encoding="utf-8")
    typer.echo(f"Готово: {run.dir}\n{json.dumps(metrics, ensure_ascii=False)}")
    return str(run.dir)


# ------------------------------------------------------------------ ASR
@asr_app.command("train")
def asr_train(
    base_model: str = typer.Option(...),
    train_manifest: Path = typer.Option(...),
    val_manifest: Path | None = None,
    backend: str = "ctc",
    new_vocab: bool = False,
    epochs: int = 5,
    runs: Path = RUNS,
) -> str:
    from doomich_ml.asr import AsrTrainConfig, train_ctc, train_whisper

    config = AsrTrainConfig(
        base_model=base_model,
        train_manifest=str(train_manifest),
        val_manifest=str(val_manifest) if val_manifest else None,
        backend=backend,
        new_vocab=new_vocab,
        epochs=epochs,
    )
    run = Run(runs, "asr")
    run.save_config(config)
    metrics = (train_ctc if backend == "ctc" else train_whisper)(config, run)
    fmt = "hf_ctc" if backend == "ctc" else "hf_whisper"
    (run.dir / "params.json").write_text(json.dumps({"format": fmt, "languages": [config.language]}), encoding="utf-8")
    typer.echo(f"Готово: {run.dir}\n{json.dumps(metrics, ensure_ascii=False)}")
    return str(run.dir)


@asr_app.command("glossary")
def asr_glossary(docs: Path = typer.Option(...), out: Path = typer.Option(...), top: int = 300) -> None:
    from doomich_ml.asr import build_glossary

    texts = [p.read_text(encoding="utf-8") for p in sorted(docs.glob("**/*")) if p.suffix in {".txt", ".md"}]
    terms = build_glossary(texts, top=top)
    out.write_text(json.dumps(terms, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"Терминов: {len(terms)} → {out}")


# ------------------------------------------------------------------ эмбеддинги
@embed_app.command("synth")
def embed_synth(
    chunks: Path = typer.Option(..., help="JSONL с полем text"),
    out: Path = typer.Option(...),
    llm_url: str = typer.Option(...),
    llm_model: str = typer.Option(...),
) -> None:
    from doomich_ml.embeddings import synth_queries

    pairs = synth_queries([r["text"] for r in read_jsonl(chunks)], llm_url=llm_url, model=llm_model)
    typer.echo(f"Пар: {write_jsonl(out, pairs)} → {out}")


@embed_app.command("train")
def embed_train(
    base_model: str = typer.Option(...),
    pairs: Path = typer.Option(...),
    pooling: str = "mean",
    epochs: int = 2,
    runs: Path = RUNS,
) -> str:
    from doomich_ml.embeddings import EmbedConfig, train

    config = EmbedConfig(base_model=base_model, pairs_file=str(pairs), pooling=pooling, epochs=epochs)
    run = Run(runs, "embeddings")
    run.save_config(config)
    metrics = train(config, run)
    (run.dir / "params.json").write_text(
        json.dumps({"pooling": pooling, "query_instruction": config.query_instruction}), encoding="utf-8"
    )
    typer.echo(f"Готово: {run.dir}\n{json.dumps(metrics, ensure_ascii=False)}")
    return str(run.dir)


# ------------------------------------------------------------------ сборка всех моделей вуза
def _dataclass_kwargs(cls, values: dict[str, Any]) -> dict[str, Any]:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in values.items() if k in names}


@app.command()
def build(
    config_path: Path,
    registry: Path = REGISTRY,
    runs: Path = RUNS,
    activate: bool = typer.Option(True, help="Активировать версии, прошедшие пороги качества"),
) -> None:
    """Обучить и зарегистрировать все модели вуза, описанные в TOML-конфиге (см. ml/configs/example.toml)."""
    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
    tenant = cfg["tenant"]
    gates = cfg.get("gates", {})
    summary = []

    def finish(
        kind: ModelKind,
        run: Run,
        metrics: dict[str, float],
        scope: str,
        params: dict[str, Any],
        base: str | None,
        license_: str | None,
    ) -> None:
        failures = check_gates(kind.value, metrics, gates.get(kind.value))
        ok = not failures
        manifest = register_run(
            registry_dir=registry,
            run_dir=run.dir,
            kind=kind,
            tenant=cfg.get(kind.value, {}).get("tenant", tenant) if kind == ModelKind.WAKEWORD else tenant,
            scope=scope,
            artifacts=ARTIFACTS[kind],
            base_model=base,
            base_model_license=license_,
            params=params,
            activate=activate and ok,
        )
        summary.append(
            (
                kind.value,
                scope,
                manifest.version,
                "активна" if activate and ok else "; ".join(failures) or "не активирована",
            )
        )

    if section := cfg.get("wakeword"):
        from doomich_ml.wakeword import WakeConfig
        from doomich_ml.wakeword import train as train_wake

        config = WakeConfig(**_dataclass_kwargs(WakeConfig, section))
        run = Run(runs, "wakeword")
        run.save_config(config)
        metrics = train_wake(config, run)
        params = json.loads((run.artifacts / "wakeword.json").read_text(encoding="utf-8"))
        finish(ModelKind.WAKEWORD, run, metrics, "default", params, None, None)

    for campus, section in cfg.get("vpr", {}).items():
        from doomich_ml.vpr import VprConfig, registry_params
        from doomich_ml.vpr import train as train_vpr

        config = VprConfig(**_dataclass_kwargs(VprConfig, section))
        run = Run(runs, "vpr", f"{tenant}-{campus}")
        run.save_config(config)
        metrics = train_vpr(config, run)
        finish(
            ModelKind.VPR, run, metrics, campus, registry_params(config), config.base_model, config.base_model_license
        )

    if section := cfg.get("llm_lora"):
        from doomich_ml.llm_lora import LoraTrainConfig
        from doomich_ml.llm_lora import train as train_lora

        config = LoraTrainConfig(**_dataclass_kwargs(LoraTrainConfig, section))
        run = Run(runs, "llm_lora", tenant)
        run.save_config(config)
        metrics = train_lora(config, run)
        finish(
            ModelKind.LLM_LORA,
            run,
            metrics,
            "default",
            {"rank": config.rank},
            config.base_model,
            config.base_model_license,
        )

    if section := cfg.get("asr"):
        from doomich_ml.asr import AsrTrainConfig, train_ctc, train_whisper

        config = AsrTrainConfig(**_dataclass_kwargs(AsrTrainConfig, section))
        run = Run(runs, "asr", tenant)
        run.save_config(config)
        metrics = (train_ctc if config.backend == "ctc" else train_whisper)(config, run)
        fmt = "hf_ctc" if config.backend == "ctc" else "hf_whisper"
        finish(
            ModelKind.ASR,
            run,
            metrics,
            "default",
            {"format": fmt, "languages": [config.language]},
            config.base_model,
            config.base_model_license,
        )

    if section := cfg.get("embeddings"):
        from doomich_ml.embeddings import EmbedConfig
        from doomich_ml.embeddings import train as train_embed

        config = EmbedConfig(**_dataclass_kwargs(EmbedConfig, section))
        run = Run(runs, "embeddings", tenant)
        run.save_config(config)
        metrics = train_embed(config, run)
        finish(
            ModelKind.EMBEDDINGS,
            run,
            metrics,
            "default",
            {"pooling": config.pooling, "query_instruction": config.query_instruction},
            config.base_model,
            config.base_model_license,
        )

    for kind, scope, version, status in summary:
        typer.echo(f"{kind:<11} {scope:<12} {version}  {status}")


if __name__ == "__main__":
    app()
