from __future__ import annotations

import io
import json

import numpy as np
import onnx
from doomich_common.registry import Manifest, ModelKind, ModelRegistry
from fastapi.testclient import TestClient
from onnx import TensorProto, helper
from PIL import Image

COLORS = {"hall": (220, 40, 40), "stairs": (40, 200, 60), "r305": (40, 60, 220)}


def _tiny_descriptor(path) -> None:
    """Игрушечный «дескриптор»: средний цвет картинки → линейная проекция в 8 измерений."""
    rng = np.random.default_rng(0)
    weights = rng.normal(size=(3, 8)).astype(np.float32)
    graph = helper.make_graph(
        [
            helper.make_node("GlobalAveragePool", ["x"], ["pooled"]),
            helper.make_node("Flatten", ["pooled"], ["flat"]),
            helper.make_node("MatMul", ["flat", "w"], ["y"]),
        ],
        "descriptor",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 32, 32])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 8])],
        [helper.make_tensor("w", TensorProto.FLOAT, [3, 8], weights.flatten().tolist())],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.save(model, str(path))


def _jpeg(color, noise: int = 10, seed: int = 0) -> bytes:
    rng = np.random.default_rng(seed)
    pixels = np.clip(np.array(color)[None, None, :] + rng.integers(-noise, noise, (48, 64, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format="JPEG")
    return buf.getvalue()


def _describe(color):
    from doomich_nav.localizer import Localizer  # noqa: F401 — проверяем импорт

    return color


def build_registry(tmp_path):
    import onnxruntime as ort

    art = tmp_path / "art"
    art.mkdir()
    _tiny_descriptor(art / "descriptor.onnx")
    session = ort.InferenceSession(str(art / "descriptor.onnx"))
    mean = np.array([0.485, 0.456, 0.406], np.float32).reshape(1, 3, 1, 1)
    std = np.array([0.229, 0.224, 0.225], np.float32).reshape(1, 3, 1, 1)
    embeddings, keys, headings = [], [], []
    for node, color in COLORS.items():
        for k in range(3):
            img = Image.open(io.BytesIO(_jpeg(color, seed=k))).convert("RGB").resize((32, 32))
            x = (np.asarray(img, np.float32).transpose(2, 0, 1)[None] / 255.0 - mean) / std
            vec = session.run(None, {"x": x})[0].reshape(-1)
            embeddings.append(vec / np.linalg.norm(vec))
            keys.append(node)
            headings.append(k * 120.0)
    np.savez(
        art / "index.npz",
        embeddings=np.array(embeddings, np.float32),
        node_keys=np.array(keys),
        headings=np.array(headings),
    )
    captions = {
        "hall": {"text": "главный вход, гардероб, охрана", "floor": 1, "building": "a", "title": "Главный вход"},
        "stairs": {
            "text": "лестница возле столовой",
            "tags": ["столовая"],
            "floor": 1,
            "building": "a",
            "title": "Лестница",
        },
        "r305": {
            "text": "коридор третьего этажа",
            "ocr": ["305", "Кафедра физики"],
            "floor": 3,
            "building": "a",
            "title": "Аудитория 305",
        },
    }
    (art / "captions.json").write_text(json.dumps(captions, ensure_ascii=False), encoding="utf-8")
    registry = ModelRegistry(tmp_path / "registry")
    manifest = Manifest(
        kind=ModelKind.VPR,
        tenant="testuni",
        scope="main",
        version="v1",
        artifacts={"descriptor": "descriptor.onnx", "index": "index.npz", "captions": "captions.json"},
        params={"input_size": 32, "temperature": 0.02},
    )
    registry.register(manifest, art)
    registry.activate("testuni", ModelKind.VPR, "main", "v1")
    return tmp_path / "registry"


def test_locate_by_camera_and_text(tmp_path, monkeypatch):
    from doomich_nav import main

    monkeypatch.setenv("DOOMICH_NAV_REGISTRY_DIR", str(build_registry(tmp_path)))
    main.get_settings.cache_clear()
    client = TestClient(main.create_app())

    frames = [("images", (f"f{i}.jpg", _jpeg(COLORS["stairs"], seed=10 + i), "image/jpeg")) for i in range(3)]
    body = client.post("/v1/locate", data={"tenant": "testuni", "campus": "main"}, files=frames).json()
    assert body["candidates"][0]["node"] == "stairs"
    assert body["confidence"] > 0.5 and body["need_clarification"] is False

    text = client.post("/v1/locate", data={"tenant": "testuni", "campus": "main", "text": "я у двери 305"}).json()
    assert text["candidates"][0]["node"] == "r305" and text["candidates"][0]["floor"] == 3

    food = client.post("/v1/locate", data={"tenant": "testuni", "campus": "main", "text": "вижу столовую"}).json()
    assert food["candidates"][0]["node"] == "stairs"

    missing = client.post("/v1/locate", data={"tenant": "other", "campus": "main", "text": "305"})
    assert missing.status_code == 404
