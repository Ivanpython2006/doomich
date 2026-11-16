from __future__ import annotations

import json

import numpy as np
from doomich_common.registry import ModelKind, ModelRegistry
from doomich_ml.common import Run, register_run, write_jsonl

from tests.conftest import COLORS, CORPUS, chirp, jpeg, make_campus, write_wav


def test_wakeword_pipeline(tmp_path):
    from doomich_ml.wakeword import WakeConfig, train

    data = tmp_path / "ww"
    for i in range(20):
        write_wav(data / "pos" / f"p{i}.wav", chirp(True, seed=i))
        write_wav(data / "neg" / f"n{i}.wav", chirp(False, seed=100 + i))
    config = WakeConfig(data_dir=str(data), epochs=4, train_size=640, val_size=200, batch_size=32, channels=16)
    run = Run(tmp_path / "runs", "wakeword")
    run.save_config(config)
    metrics = train(config, run)
    assert metrics["val_auc"] > 0.9, metrics
    assert (run.artifacts / "wakeword.onnx").stat().st_size > 1000
    params = json.loads((run.artifacts / "wakeword.json").read_text(encoding="utf-8"))
    assert params["window_samples"] == 24000 and 0 < params["threshold"] < 1

    import onnxruntime as ort
    from doomich_ml.wakeword import WINDOW_SAMPLES

    session = ort.InferenceSession(str(run.artifacts / "wakeword.onnx"))
    window = np.zeros((1, WINDOW_SAMPLES), np.float32)
    up = chirp(True, seed=999)
    window[0, 5000 : 5000 + up.size] = up
    logit = session.run(None, {"audio": window})[0][0]
    assert 1 / (1 + np.exp(-logit)) > params["threshold"]

    manifest = register_run(
        registry_dir=tmp_path / "registry",
        run_dir=run.dir,
        kind=ModelKind.WAKEWORD,
        tenant="_global",
        artifacts={"onnx": "wakeword.onnx", "config": "wakeword.json"},
        base_model=None,
        base_model_license=None,
        params=params,
        activate=True,
    )
    active = ModelRegistry(tmp_path / "registry").active("any-uni", ModelKind.WAKEWORD)
    assert active is not None and active.version == manifest.version  # общий для всех вузов


def test_vpr_pipeline_feeds_navigation_service(tmp_path, tiny_vit):
    from doomich_ml.vpr import VprConfig, registry_params, train

    campus = make_campus(tmp_path / "campus")
    config = VprConfig(
        campus_dir=str(campus),
        base_model=str(tiny_vit),
        input_size=32,
        dim=16,
        epochs=4,
        nodes_per_batch=4,
        photos_per_node=3,
        train_blocks=2,
        lr=1e-3,
        val_fraction=0.34,
    )
    run = Run(tmp_path / "runs", "vpr")
    metrics = train(config, run)
    assert "recall_at_1" in metrics and "baseline_recall_at_1" in metrics
    assert metrics["recall_at_1"] >= 0.75, metrics
    captions = json.loads((run.artifacts / "captions.json").read_text(encoding="utf-8"))
    assert captions["aud-305"]["ocr"] == ["305"]

    register_run(
        registry_dir=tmp_path / "registry",
        run_dir=run.dir,
        kind=ModelKind.VPR,
        tenant="testuni",
        scope="main",
        artifacts={"descriptor": "descriptor.onnx", "index": "index.npz", "captions": "captions.json"},
        base_model="tiny",
        base_model_license="Apache-2.0",
        params=registry_params(config),
        activate=True,
    )

    # результат обучения сразу пригоден для сервиса навигации
    from doomich_nav.localizer import Localizer

    registry = ModelRegistry(tmp_path / "registry")
    manifest = registry.active("testuni", ModelKind.VPR, "main")
    localizer = Localizer(registry.version_dir("testuni", ModelKind.VPR, "main", manifest.version), manifest.params)
    result = localizer.locate([jpeg(COLORS["aud-305"], seed=s) for s in (501, 502, 503)], None)
    assert result["candidates"][0]["node"] == "aud-305"
    by_text = localizer.locate([], "я возле столовой")
    assert by_text["candidates"][0]["node"] == "stolovaya"


def test_llm_lora_pipeline(tmp_path, tiny_llm):
    from doomich_ml.llm_lora import LoraTrainConfig, encode_example, train

    rows = []
    for i in range(0, len(CORPUS) - 1, 2):
        rows.append(
            {
                "messages": [
                    {"role": "system", "content": "ты думыч помощник вуза"},
                    {"role": "user", "content": CORPUS[i]},
                    {"role": "assistant", "content": CORPUS[i + 1]},
                ]
            }
        )
    write_jsonl(tmp_path / "chat.jsonl", rows * 6)
    config = LoraTrainConfig(
        base_model=str(tiny_llm),
        data_file=str(tmp_path / "chat.jsonl"),
        epochs=3,
        lr=5e-3,
        batch_size=4,
        grad_accum=1,
        rank=4,
        alpha=8,
        eval_generate=2,
        max_len=128,
    )
    run = Run(tmp_path / "runs", "llm_lora")
    metrics = train(config, run)
    assert metrics["val_loss"] < metrics["val_loss_before"], metrics
    adapter = run.artifacts / "adapter"
    assert (adapter / "adapter_config.json").exists() and (adapter / "adapter_model.safetensors").exists()
    cfg = json.loads((adapter / "adapter_config.json").read_text())
    assert cfg["r"] == 4 and "q_proj" in cfg["target_modules"]

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(tiny_llm)
    encoded = encode_example(tok, rows[0]["messages"], 128)
    assert encoded["labels"].count(-100) > 0 and any(x != -100 for x in encoded["labels"])  # лосс только по ответу


def test_embeddings_pipeline(tmp_path, tiny_encoder):
    from doomich_ml.embeddings import EmbedConfig, train

    pairs = [{"query": CORPUS[i], "positive": CORPUS[i + 1]} for i in range(0, len(CORPUS) - 1, 2)]
    write_jsonl(tmp_path / "pairs.jsonl", pairs * 5)
    config = EmbedConfig(
        base_model=str(tiny_encoder),
        pairs_file=str(tmp_path / "pairs.jsonl"),
        epochs=3,
        batch_size=4,
        lr=1e-3,
        val_fraction=0.3,
    )
    run = Run(tmp_path / "runs", "embeddings")
    metrics = train(config, run)
    assert {"before_recall_at_1", "recall_at_1", "mrr"} <= set(metrics)
    assert (run.artifacts / "model" / "config.json").exists()


def test_asr_ctc_pipeline_feeds_asr_service(tmp_path):
    from doomich_ml.asr import AsrTrainConfig, cer, train_ctc, wer
    from transformers import Wav2Vec2Config, Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC

    base = tmp_path / "tiny-ctc"
    config = Wav2Vec2Config(
        vocab_size=8,
        hidden_size=32,
        num_hidden_layers=2,
        num_attention_heads=2,
        intermediate_size=64,
        conv_dim=(16, 16),
        conv_stride=(5, 4),
        conv_kernel=(10, 8),
        num_conv_pos_embeddings=8,
        num_conv_pos_embedding_groups=2,
        do_stable_layer_norm=True,
    )
    Wav2Vec2ForCTC(config).save_pretrained(base)
    Wav2Vec2FeatureExtractor(feature_size=1, sampling_rate=16000).save_pretrained(base)
    rows = []
    for i in range(6):
        path = tmp_path / "audio" / f"{i}.wav"
        write_wav(path, chirp(i % 2 == 0, seconds=0.5, seed=i))
        rows.append({"audio": str(path), "text": "да" if i % 2 == 0 else "нет"})
    write_jsonl(tmp_path / "train.jsonl", rows)
    cfg = AsrTrainConfig(
        base_model=str(base),
        train_manifest=str(tmp_path / "train.jsonl"),
        new_vocab=True,
        epochs=2,
        batch_size=3,
        grad_accum=1,
        lr=1e-3,
    )
    run = Run(tmp_path / "runs", "asr")
    metrics = train_ctc(cfg, run)
    assert {"wer_before", "wer", "cer"} <= set(metrics)

    from doomich_asr.engines import HfCtcEngine

    engine = HfCtcEngine(str(run.artifacts / "model"))
    assert isinstance(engine.transcribe(chirp(True, seed=7), "ru").text, str)

    assert wer(["Привет, мир!"], ["привет мир"]) == 0.0
    assert wer(["раз два три"], ["раз три"]) == 1 / 3
    assert cer(["кот"], ["код"]) == 1 / 3


def test_quality_gates():
    from doomich_ml.cli import check_gates

    assert check_gates("vpr", {"recall_at_1": 0.9}) == []
    assert check_gates("vpr", {"recall_at_1": 0.5})
    assert check_gates("wakeword", {"frr": 0.03, "false_alarms_per_hour": 0.2}, {"frr": ["<=", 0.02]})
