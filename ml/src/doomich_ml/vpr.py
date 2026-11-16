"""Распознавание места по фото для навигации по кампусу (Visual Place Recognition).

Пайплайн для каждого кампуса:

1. Данные: ``<campus>/photos/<ключ узла графа>/*.jpg`` + ``nodes.json`` (название, этаж, корпус, теги).
   Фото снимаются в режиме «съёмщик» приложения: 8 кадров по кругу в каждом узле, днём и вечером.
   Угол съёмки можно указать в имени файла: ``…_h090.jpg``.
2. Дообучение дескриптора на фото кампуса (метрическое обучение, SupCon): кадры одного узла
   притягиваются, разных — отталкиваются. Основа — DINOv2 (Apache-2.0) из Hugging Face.
3. Оценка Recall@1/5 на отложенных фото (до и после дообучения).
4. Индекс эталонных дескрипторов + подписи узлов (можно дополнить описаниями от VLM).
5. Экспорт дескриптора в ONNX → реестр моделей (tenant = вуз, scope = кампус) → сервис навигации.
"""

from __future__ import annotations

import base64
import io
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageEnhance, ImageFilter
from torch import nn

from doomich_ml.common import Run, log, pick_device, seed_everything

MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]
_HEADING = re.compile(r"_h(\d{1,3})", re.IGNORECASE)


@dataclass
class Photo:
    path: Path
    node: str
    heading: float


def load_campus(campus_dir: Path) -> tuple[list[Photo], dict[str, dict[str, Any]]]:
    photos = []
    for node_dir in sorted((campus_dir / "photos").iterdir()):
        if not node_dir.is_dir():
            continue
        for path in sorted(node_dir.glob("*")):
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                match = _HEADING.search(path.stem)
                photos.append(Photo(path, node_dir.name, float(match.group(1)) if match else float("nan")))
    nodes_path = campus_dir / "nodes.json"
    nodes = json.loads(nodes_path.read_text(encoding="utf-8")) if nodes_path.exists() else {}
    if not photos:
        raise ValueError(f"В {campus_dir}/photos нет фотографий")
    return photos, nodes


def preprocess(image: Image.Image, size: int) -> torch.Tensor:
    """Те же шаги, что в сервисе навигации: короткая сторона → size, центральный кроп, нормализация."""
    image = image.convert("RGB")
    w, h = image.size
    scale = size / min(w, h)
    image = image.resize((max(1, round(w * scale)), max(1, round(h * scale))))
    w, h = image.size
    left, top = (w - size) // 2, (h - size) // 2
    image = image.crop((left, top, left + size, top + size))
    array = np.asarray(image, dtype=np.float32).transpose(2, 0, 1) / 255.0
    array = (array - np.asarray(MEAN, np.float32)[:, None, None]) / np.asarray(STD, np.float32)[:, None, None]
    return torch.from_numpy(array)


def augment(image: Image.Image, rng: random.Random) -> Image.Image:
    w, h = image.size
    scale = rng.uniform(0.6, 1.0)
    cw, ch = int(w * scale), int(h * scale)
    left, top = rng.randint(0, w - cw), rng.randint(0, h - ch)
    image = image.crop((left, top, left + cw, top + ch))
    image = ImageEnhance.Brightness(image).enhance(rng.uniform(0.6, 1.4))  # день/вечер
    image = ImageEnhance.Contrast(image).enhance(rng.uniform(0.7, 1.3))
    image = ImageEnhance.Color(image).enhance(rng.uniform(0.7, 1.3))
    if rng.random() < 0.2:
        image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.5)))  # смазанный кадр
    return image


class PlaceDescriptor(nn.Module):
    """Основа (ViT) → [CLS ‖ среднее патчей] → проекция → L2-нормализация."""

    def __init__(self, backbone: nn.Module, hidden: int, dim: int) -> None:
        super().__init__()
        self.backbone = backbone
        self.head = nn.Linear(hidden * 2, dim)

    def features(self, pixel_values: torch.Tensor) -> torch.Tensor:
        tokens = self.backbone(pixel_values=pixel_values).last_hidden_state
        return torch.cat([tokens[:, 0], tokens[:, 1:].mean(dim=1)], dim=-1)

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        return F.normalize(self.head(self.features(pixel_values)), dim=-1)


def supcon_loss(z: torch.Tensor, labels: torch.Tensor, temperature: float = 0.07) -> torch.Tensor:
    sim = z @ z.T / temperature
    self_mask = torch.eye(len(z), dtype=torch.bool, device=z.device)
    sim = sim.masked_fill(self_mask, -1e9)
    positives = (labels[:, None] == labels[None, :]) & ~self_mask
    log_prob = sim - torch.logsumexp(sim, dim=1, keepdim=True)
    count = positives.sum(1)
    valid = count > 0
    loss = -(log_prob * positives).sum(1)[valid] / count[valid]
    return loss.mean()


@dataclass
class VprConfig:
    campus_dir: str
    base_model: str = "facebook/dinov2-small"
    base_model_license: str = "Apache-2.0"
    input_size: int = 224
    dim: int = 256
    epochs: int = 10
    nodes_per_batch: int = 16
    photos_per_node: int = 4
    lr: float = 1e-4
    train_blocks: int = 2
    val_fraction: float = 0.2
    seed: int = 42
    device: str = "auto"
    caption_url: str | None = None  # OpenAI-совместимый VLM для описаний и надписей
    caption_model: str | None = None


def _build_model(config: VprConfig) -> PlaceDescriptor:
    from transformers import AutoModel

    backbone = AutoModel.from_pretrained(config.base_model)
    hidden = backbone.config.hidden_size
    for p in backbone.parameters():
        p.requires_grad = False
    layers = getattr(getattr(backbone, "encoder", None), "layer", [])
    for block in list(layers)[-config.train_blocks :] if config.train_blocks else []:
        for p in block.parameters():
            p.requires_grad = True
    if hasattr(backbone, "layernorm"):
        for p in backbone.layernorm.parameters():
            p.requires_grad = True
    return PlaceDescriptor(backbone, hidden, config.dim)


def _split(photos: list[Photo], fraction: float, seed: int) -> tuple[list[Photo], list[Photo]]:
    rng = random.Random(seed)
    by_node: dict[str, list[Photo]] = {}
    for photo in photos:
        by_node.setdefault(photo.node, []).append(photo)
    train, val = [], []
    for items in by_node.values():
        items = items[:]
        rng.shuffle(items)
        n_val = int(len(items) * fraction) if len(items) >= 3 else 0
        val += items[:n_val]
        train += items[n_val:]
    return train, val


@torch.inference_mode()
def embed(model: PlaceDescriptor, photos: list[Photo], size: int, device: str, *, raw: bool = False) -> np.ndarray:
    model.eval()
    out = []
    for i in range(0, len(photos), 32):
        batch = torch.stack([preprocess(Image.open(p.path), size) for p in photos[i : i + 32]]).to(device)
        z = F.normalize(model.features(batch), dim=-1) if raw else model(batch)
        out.append(z.cpu().numpy())
    return np.concatenate(out).astype(np.float32)


def recall_at(
    db: np.ndarray, db_nodes: list[str], queries: np.ndarray, q_nodes: list[str], ks=(1, 5)
) -> dict[str, float]:
    if len(queries) == 0:
        return {}
    sims = queries @ db.T
    order = np.argsort(-sims, axis=1)
    result = {}
    for k in ks:
        hits = 0
        for i, row in enumerate(order):
            seen: list[str] = []
            for j in row:
                if db_nodes[j] not in seen:
                    seen.append(db_nodes[j])
                if len(seen) >= k:
                    break
            hits += q_nodes[i] in seen
        result[f"recall_at_{k}"] = hits / len(queries)
    return result


def train(config: VprConfig, run: Run) -> dict[str, float]:
    seed_everything(config.seed)
    device = pick_device(config.device)
    photos, nodes = load_campus(Path(config.campus_dir))
    train_photos, val_photos = _split(photos, config.val_fraction, config.seed)
    node_ids = {n: i for i, n in enumerate(sorted({p.node for p in photos}))}
    log.info(
        "Узлов: %d, фото: %d (обучение %d, проверка %d)", len(node_ids), len(photos), len(train_photos), len(val_photos)
    )

    model = _build_model(config).to(device)
    metrics: dict[str, float] = {}
    if val_photos:
        db, q = (
            embed(model, train_photos, config.input_size, device, raw=True),
            embed(model, val_photos, config.input_size, device, raw=True),
        )
        base = recall_at(db, [p.node for p in train_photos], q, [p.node for p in val_photos])
        metrics.update({f"baseline_{k}": v for k, v in base.items()})

    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=config.lr, weight_decay=0.01)
    by_node: dict[str, list[Photo]] = {}
    for photo in train_photos:
        by_node.setdefault(photo.node, []).append(photo)
    usable = [n for n, items in by_node.items() if len(items) >= 2]
    rng = random.Random(config.seed)
    steps_per_epoch = max(1, len(train_photos) // (config.nodes_per_batch * config.photos_per_node))
    for epoch in range(config.epochs):
        model.train()
        total = 0.0
        for _ in range(steps_per_epoch):
            chosen = rng.sample(usable, min(config.nodes_per_batch, len(usable)))
            images, labels = [], []
            for node in chosen:
                for photo in rng.choices(by_node[node], k=config.photos_per_node):
                    images.append(preprocess(augment(Image.open(photo.path).convert("RGB"), rng), config.input_size))
                    labels.append(node_ids[node])
            z = model(torch.stack(images).to(device))
            loss = supcon_loss(z, torch.tensor(labels, device=device))
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total += loss.item()
        log.info("Эпоха %d: loss=%.4f", epoch + 1, total / steps_per_epoch)

    if val_photos:
        db, q = (
            embed(model, train_photos, config.input_size, device),
            embed(model, val_photos, config.input_size, device),
        )
        metrics.update(recall_at(db, [p.node for p in train_photos], q, [p.node for p in val_photos]))

    # индекс по всем фото, подписи узлов, экспорт
    all_emb = embed(model, photos, config.input_size, device)
    np.savez(
        run.artifacts / "index.npz",
        embeddings=all_emb,
        node_keys=np.array([p.node for p in photos]),
        headings=np.array([p.heading for p in photos], dtype=np.float32),
    )
    captions = build_captions(photos, nodes, config)
    (run.artifacts / "captions.json").write_text(json.dumps(captions, ensure_ascii=False, indent=2), encoding="utf-8")
    export_onnx(model.cpu(), run.artifacts / "descriptor.onnx", config.input_size)
    run.save_metrics(metrics)
    return metrics


def build_captions(
    photos: list[Photo], nodes: dict[str, dict[str, Any]], config: VprConfig
) -> dict[str, dict[str, Any]]:
    captions = {key: dict(info) for key, info in nodes.items()}
    for photo in photos:
        captions.setdefault(photo.node, {"title": photo.node})
    if config.caption_url and config.caption_model:
        for node in sorted({p.node for p in photos}):
            sample = next(p for p in photos if p.node == node)
            try:
                described = describe_with_vlm(sample.path, config.caption_url, config.caption_model)
            except Exception:  # подписи — улучшение, а не обязательная часть
                log.warning("VLM не описал узел %s", node, exc_info=True)
                continue
            entry = captions[node]
            entry["text"] = " ".join(filter(None, [entry.get("text", ""), described.get("description", "")]))
            entry["ocr"] = sorted(set(entry.get("ocr", [])) | set(described.get("signs", [])))
    return captions


def describe_with_vlm(path: Path, url: str, model: str) -> dict[str, Any]:
    """Описание места и надписи в кадре от мультимодальной LLM (например, Qwen 3.x в vLLM)."""
    import httpx

    image = Image.open(path).convert("RGB")
    image.thumbnail((768, 768))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    data_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    prompt = (
        "Это фото коридора или помещения университета. Ответь JSON без пояснений: "
        '{"description": "что видно: ориентиры, двери, лестницы, стенды", "signs": ["все надписи и номера"]}'
    )
    resp = httpx.post(
        f"{url.rstrip('/')}/chat/completions",
        json={
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        },
        timeout=120,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", text, flags=re.S)
    return json.loads(match.group(0)) if match else {"description": text}


class _Export(nn.Module):
    def __init__(self, model: PlaceDescriptor) -> None:
        super().__init__()
        self.model = model

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.model(x)


def export_onnx(model: PlaceDescriptor, path: Path, size: int) -> None:
    model.eval()
    wrapper = _Export(model)
    dummy = torch.zeros(1, 3, size, size)
    torch.onnx.export(
        wrapper,
        (dummy,),
        str(path),
        input_names=["image"],
        output_names=["descriptor"],
        dynamic_axes={"image": {0: "batch"}, "descriptor": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    import onnxruntime as ort

    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    probe = torch.randn(2, 3, size, size)
    with torch.inference_mode():
        expected = wrapper(probe).numpy()
    got = session.run(None, {"image": probe.numpy()})[0]
    if not np.allclose(expected, got, atol=1e-3):
        raise RuntimeError(f"ONNX-дескриптор расходится с PyTorch: {np.abs(expected - got).max():.5f}")


def registry_params(config: VprConfig) -> dict[str, Any]:
    return {
        "input_size": config.input_size,
        "mean": MEAN,
        "std": STD,
        "dim": config.dim,
        "temperature": 0.05,
        "min_confidence": 0.55,
        "min_margin": 0.15,
    }
