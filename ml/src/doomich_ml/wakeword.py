"""Слово активации «Думыч»: данные → аугментации → обучение → оценка → ONNX → реестр.

Модель маленькая (≈60 тыс. параметров) и принимает окно сырого звука 1,5 с (24000 сэмплов 16 кГц).
На устройстве окно сдвигается каждые 0,1–0,2 с, срабатывание — когда вероятность выше порога
несколько окон подряд. Звук никуда не отправляется до срабатывания.

Источники данных:
* синтез фраз через сервис TTS «Думыча» разными голосами и скоростями (``synthesize``);
* записи добровольцев (только с их согласия) — WAV в каталоге ``recordings/``;
* негативы: похожие слова, обычная речь, шум.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from doomich_common.audio import TARGET_SAMPLE_RATE, float_to_pcm16, normalize_wav, pcm16_to_wav
from torch import nn

from doomich_ml.audio_features import LogMel
from doomich_ml.common import Run, log, pick_device, seed_everything

LOG = logging.getLogger(__name__)

WINDOW_SAMPLES = int(1.5 * TARGET_SAMPLE_RATE)
POSITIVE_TEXTS = ["Думыч", "Думыч!", "Думыч,", "Эй, Думыч", "Слушай, Думыч"]
NEGATIVE_TEXTS = [
    "думаю",
    "дума",
    "думать",
    "Дмитрич",
    "домик",
    "дымок",
    "ну мы ж",
    "тумач",
    "Кузьмич",
    "думающий",
    "привет",
    "расписание",
    "какая следующая пара",
    "открой документ",
    "спасибо",
    "доброе утро",
    "лекция",
]


# ---------------------------------------------------------------------------- данные
def synthesize(
    out_dir: Path,
    *,
    tts_url: str,
    voices: list[str],
    speeds: tuple[float, ...] = (0.8, 0.9, 1.0, 1.1, 1.25),
    positive_texts: list[str] | None = None,
    negative_texts: list[str] | None = None,
) -> dict[str, int]:
    """Синтезировать позитивы и негативы через сервис TTS «Думыча» (POST /v1/speak)."""
    import httpx

    counts = {"pos": 0, "neg": 0}
    with httpx.Client(timeout=60) as client:
        for label, texts in (("pos", positive_texts or POSITIVE_TEXTS), ("neg", negative_texts or NEGATIVE_TEXTS)):
            target = out_dir / label
            target.mkdir(parents=True, exist_ok=True)
            for voice in voices:
                for speed in speeds:
                    for i, text in enumerate(texts):
                        resp = client.post(
                            f"{tts_url.rstrip('/')}/v1/speak",
                            json={"text": text, "voice": voice, "speed": speed, "format": "wav", "normalize": False},
                        )
                        resp.raise_for_status()
                        name = f"{voice}_{speed:.2f}_{i}.wav"
                        (target / name).write_bytes(resp.content)
                        counts[label] += 1
    LOG.info("Синтезировано: %s", counts)
    return counts


def load_folder(folder: Path) -> list[np.ndarray]:
    clips = []
    for path in sorted(folder.glob("**/*.wav")):
        try:
            clips.append(normalize_wav(path.read_bytes()))
        except Exception:  # повреждённые файлы пропускаем
            LOG.warning("Не удалось прочитать %s", path)
    return clips


@dataclass
class Augment:
    noise: list[np.ndarray] = field(default_factory=list)
    snr_db: tuple[float, float] = (5.0, 30.0)
    gain_db: tuple[float, float] = (-12.0, 4.0)
    speed: tuple[float, float] = (0.9, 1.1)
    reverb_prob: float = 0.3

    def _speed(self, clip: np.ndarray, rng: random.Random) -> np.ndarray:
        factor = rng.uniform(*self.speed)
        idx = np.arange(0, clip.size - 1, factor)
        return np.interp(idx, np.arange(clip.size), clip).astype(np.float32) if idx.size > 1 else clip

    def _reverb(self, clip: np.ndarray, rng: random.Random) -> np.ndarray:
        length = int(TARGET_SAMPLE_RATE * rng.uniform(0.05, 0.3))
        ir = np.exp(-np.linspace(0, rng.uniform(4, 9), length)).astype(np.float32)
        ir *= np.random.default_rng(rng.randint(0, 10**6)).normal(size=length).astype(np.float32)
        ir[0] = 1.0
        wet = np.convolve(clip, ir)[: clip.size]
        return wet / (np.abs(wet).max() + 1e-6) * (np.abs(clip).max() + 1e-6)

    def place(self, clip: np.ndarray, rng: random.Random, *, positive: bool) -> np.ndarray:
        """Положить фрагмент в окно 1,5 с. Позитив кладём так, чтобы слово заканчивалось в окне целиком."""
        clip = self._speed(clip, rng)
        if rng.random() < self.reverb_prob:
            clip = self._reverb(clip, rng)
        window = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
        if clip.size >= WINDOW_SAMPLES:
            start = rng.randint(0, clip.size - WINDOW_SAMPLES) if not positive else clip.size - WINDOW_SAMPLES
            window[:] = clip[start : start + WINDOW_SAMPLES]
        else:
            offset = rng.randint(0, WINDOW_SAMPLES - clip.size)
            window[offset : offset + clip.size] = clip
        window *= 10 ** (rng.uniform(*self.gain_db) / 20)
        signal_power = float(np.mean(window**2)) + 1e-9
        if self.noise and rng.random() < 0.8:
            noise = self.noise[rng.randrange(len(self.noise))]
            if noise.size < WINDOW_SAMPLES:
                noise = np.tile(noise, WINDOW_SAMPLES // max(1, noise.size) + 1)
            start = rng.randint(0, noise.size - WINDOW_SAMPLES)
            noise = noise[start : start + WINDOW_SAMPLES]
        else:
            noise = np.random.default_rng(rng.randint(0, 10**6)).normal(size=WINDOW_SAMPLES).astype(np.float32)
        noise_power = float(np.mean(noise**2)) + 1e-9
        snr = rng.uniform(*self.snr_db)
        window = window + noise * np.sqrt(signal_power / (noise_power * 10 ** (snr / 10)))
        return np.clip(window, -1.0, 1.0).astype(np.float32)


class WakeDataset(torch.utils.data.Dataset):
    def __init__(self, positives, negatives, augment: Augment, *, size: int, seed: int, pos_fraction: float = 0.4):
        self.positives, self.negatives, self.augment = positives, negatives, augment
        self.size, self.seed, self.pos_fraction = size, seed, pos_fraction

    def __len__(self) -> int:
        return self.size

    def __getitem__(self, idx: int):
        rng = random.Random(self.seed * 1_000_003 + idx)
        positive = rng.random() < self.pos_fraction
        if positive:
            clip = self.positives[rng.randrange(len(self.positives))]
        elif self.negatives and rng.random() < 0.85:
            clip = self.negatives[rng.randrange(len(self.negatives))]
        else:
            clip = np.zeros(TARGET_SAMPLE_RATE // 2, dtype=np.float32)  # «тишина» с шумом
        return torch.from_numpy(self.augment.place(clip, rng, positive=positive)), torch.tensor(float(positive))


# ---------------------------------------------------------------------------- модель
class DSConv(nn.Module):
    def __init__(self, cin: int, cout: int, stride: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(cin, cin, 3, stride=stride, padding=1, groups=cin, bias=False),
            nn.BatchNorm2d(cin),
            nn.ReLU(),
            nn.Conv2d(cin, cout, 1, bias=False),
            nn.BatchNorm2d(cout),
            nn.ReLU(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class WakeWordNet(nn.Module):
    def __init__(self, n_mels: int = 40, channels: int = 48) -> None:
        super().__init__()
        self.features = LogMel(n_mels=n_mels)
        self.body = nn.Sequential(
            nn.Conv2d(1, channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(channels),
            nn.ReLU(),
            DSConv(channels, channels, 2),
            DSConv(channels, channels * 2, 2),
            DSConv(channels * 2, channels * 2, 1),
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
            nn.Dropout(0.2),
            nn.Linear(channels * 2, 1),
        )

    def forward(self, audio: torch.Tensor) -> torch.Tensor:  # [B, 24000] → логит [B]
        return self.body(self.features(audio)[:, None]).squeeze(-1)


# ---------------------------------------------------------------------------- обучение
@dataclass
class WakeConfig:
    data_dir: str
    noise_dir: str | None = None
    epochs: int = 20
    batch_size: int = 64
    lr: float = 1e-3
    train_size: int = 8000
    val_size: int = 1500
    channels: int = 48
    target_frr: float = 0.05
    seed: int = 42
    device: str = "auto"


def _evaluate(model, loader, device) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    scores, labels = [], []
    with torch.inference_mode():
        for audio, label in loader:
            scores.append(torch.sigmoid(model(audio.to(device))).cpu().numpy())
            labels.append(label.numpy())
    return np.concatenate(scores), np.concatenate(labels)


def pick_threshold(scores: np.ndarray, labels: np.ndarray, target_frr: float) -> tuple[float, float, float]:
    """Порог: минимальные ложные срабатывания при пропусках не больше target_frr."""
    pos = np.sort(scores[labels == 1])
    neg = scores[labels == 0]
    if pos.size == 0:
        return 0.5, 1.0, 0.0
    threshold = float(pos[int(np.floor(target_frr * pos.size))]) if pos.size > 1 else float(pos[0])
    threshold = min(max(threshold, 0.05), 0.99)
    frr = float(np.mean(pos < threshold))
    far = float(np.mean(neg >= threshold)) if neg.size else 0.0
    return threshold, frr, far


def false_alarms_per_hour(
    model, negatives: list[np.ndarray], threshold: float, device: str, hop_s: float = 0.2
) -> float:
    """Прогоняем длинный «негативный» поток скользящим окном, как на устройстве."""
    if not negatives:
        return 0.0
    stream = np.concatenate([*negatives, np.zeros(TARGET_SAMPLE_RATE, np.float32)])
    hop = int(hop_s * TARGET_SAMPLE_RATE)
    windows = [stream[i : i + WINDOW_SAMPLES] for i in range(0, max(1, stream.size - WINDOW_SAMPLES), hop)]
    if not windows:
        return 0.0
    alarms, cooldown = 0, 0
    model.eval()
    with torch.inference_mode():
        for chunk in range(0, len(windows), 256):
            batch = torch.from_numpy(np.stack(windows[chunk : chunk + 256])).to(device)
            for p in torch.sigmoid(model(batch)).cpu().numpy():
                if cooldown > 0:
                    cooldown -= 1
                elif p >= threshold:
                    alarms += 1
                    cooldown = int(2.0 / hop_s)
    hours = stream.size / TARGET_SAMPLE_RATE / 3600
    return alarms / max(hours, 1e-9)


def train(config: WakeConfig, run: Run) -> dict[str, float]:
    seed_everything(config.seed)
    device = pick_device(config.device)
    data = Path(config.data_dir)
    positives = load_folder(data / "pos") + load_folder(data / "recordings")
    negatives = load_folder(data / "neg")
    noise = load_folder(Path(config.noise_dir)) if config.noise_dir else []
    if not positives:
        raise ValueError(f"Нет позитивных примеров в {data}/pos или {data}/recordings")
    log.info("Позитивов: %d, негативов: %d, шумов: %d", len(positives), len(negatives), len(noise))
    rng = random.Random(config.seed)
    rng.shuffle(positives)
    rng.shuffle(negatives)
    cut_p, cut_n = max(1, len(positives) // 5), max(1, len(negatives) // 5) if negatives else 0
    train_set = WakeDataset(
        positives[cut_p:] or positives,
        negatives[cut_n:] or negatives,
        Augment(noise=noise),
        size=config.train_size,
        seed=config.seed,
    )
    val_set = WakeDataset(
        positives[:cut_p],
        negatives[:cut_n] or negatives,
        Augment(noise=noise, reverb_prob=0.0),
        size=config.val_size,
        seed=config.seed + 1,
    )
    train_loader = torch.utils.data.DataLoader(train_set, batch_size=config.batch_size, shuffle=True)
    val_loader = torch.utils.data.DataLoader(val_set, batch_size=config.batch_size)

    model = WakeWordNet(channels=config.channels).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=config.lr, total_steps=config.epochs * len(train_loader)
    )
    loss_fn = nn.BCEWithLogitsLoss()
    best_auc, best_state = -1.0, None
    for epoch in range(config.epochs):
        model.train()
        total = 0.0
        for audio, label in train_loader:
            optimizer.zero_grad()
            loss = loss_fn(model(audio.to(device)), label.to(device))
            loss.backward()
            optimizer.step()
            scheduler.step()
            total += loss.item() * audio.size(0)
        scores, labels = _evaluate(model, val_loader, device)
        auc = _auc(scores, labels)
        log.info("Эпоха %d: loss=%.4f val_auc=%.4f", epoch + 1, total / len(train_set), auc)
        if auc > best_auc:
            best_auc, best_state = auc, {k: v.detach().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    scores, labels = _evaluate(model, val_loader, device)
    threshold, frr, far = pick_threshold(scores, labels, config.target_frr)
    fah = false_alarms_per_hour(model, negatives[:cut_n] or negatives, threshold, device)
    metrics = {"val_auc": best_auc, "threshold": threshold, "frr": frr, "far_window": far, "false_alarms_per_hour": fah}
    run.save_metrics(metrics)
    torch.save(model.state_dict(), run.dir / "model.pt")
    export_onnx(model.cpu(), run.artifacts / "wakeword.onnx")
    (run.artifacts / "wakeword.json").write_text(
        json.dumps(
            {
                "sample_rate": TARGET_SAMPLE_RATE,
                "window_samples": WINDOW_SAMPLES,
                "hop_ms": 160,
                "threshold": threshold,
                "trigger_windows": 2,
                "phrase": "Думыч",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return metrics


def _auc(scores: np.ndarray, labels: np.ndarray) -> float:
    pos, neg = scores[labels == 1], scores[labels == 0]
    if pos.size == 0 or neg.size == 0:
        return 0.0
    ranks = np.argsort(np.argsort(np.concatenate([pos, neg]))) + 1
    return float((ranks[: pos.size].sum() - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def export_onnx(model: WakeWordNet, path: Path) -> None:
    model.eval()
    dummy = torch.zeros(1, WINDOW_SAMPLES)
    torch.onnx.export(
        model,
        (dummy,),
        str(path),
        input_names=["audio"],
        output_names=["logit"],
        dynamic_axes={"audio": {0: "batch"}, "logit": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    # сверка ONNX и PyTorch
    import onnxruntime as ort

    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    probe = torch.randn(2, WINDOW_SAMPLES) * 0.1
    with torch.inference_mode():
        expected = model(probe).numpy()
    got = session.run(None, {"audio": probe.numpy()})[0]
    if not np.allclose(expected, got, atol=1e-3):
        raise RuntimeError(f"ONNX расходится с PyTorch: {np.abs(expected - got).max()}")


def write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pcm16_to_wav(float_to_pcm16(samples), TARGET_SAMPLE_RATE))
