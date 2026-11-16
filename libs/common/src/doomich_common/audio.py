"""Утилиты для звука: WAV, PCM16, декодирование через ffmpeg, простое разбиение по паузам."""

from __future__ import annotations

import io
import shutil
import subprocess
import wave

import numpy as np

TARGET_SAMPLE_RATE = 16_000


class AudioError(ValueError):
    pass


def pcm16_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def wav_to_pcm16(data: bytes) -> tuple[bytes, int, int]:
    """Вернуть (pcm16, частота, каналы). Поддерживается только 16-битный PCM WAV."""
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if wav.getsampwidth() != 2:
                raise AudioError("Ожидается 16-битный WAV")
            return wav.readframes(wav.getnframes()), wav.getframerate(), wav.getnchannels()
    except wave.Error as exc:
        raise AudioError(f"Некорректный WAV: {exc}") from exc


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def to_mono(samples: np.ndarray, channels: int) -> np.ndarray:
    if channels == 1:
        return samples
    return samples.reshape(-1, channels).mean(axis=1)


def resample_linear(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Линейная передискретизация (достаточно для речи 8–48 кГц → 16 кГц)."""
    if src_rate == dst_rate or samples.size == 0:
        return samples
    duration = samples.size / src_rate
    dst_len = max(1, round(duration * dst_rate))
    src_idx = np.linspace(0, samples.size - 1, num=dst_len)
    return np.interp(src_idx, np.arange(samples.size), samples).astype(np.float32)


def normalize_wav(data: bytes, target_rate: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    pcm, rate, channels = wav_to_pcm16(data)
    samples = to_mono(pcm16_to_float(pcm), channels)
    return resample_linear(samples, rate, target_rate)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def decode_with_ffmpeg(data: bytes, target_rate: int = TARGET_SAMPLE_RATE, timeout: float = 120.0) -> bytes:
    """Любой формат (ogg/opus, m4a, mp3, webm, mp4…) → PCM16 моно с частотой target_rate."""
    if not ffmpeg_available():
        raise AudioError("ffmpeg не найден — установите его для декодирования сжатого звука")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        "pipe:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(target_rate),
        "-f",
        "s16le",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout, check=False)  # noqa: S603
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg не смог декодировать звук: {proc.stderr.decode(errors='ignore')[:300]}")
    return proc.stdout


def encode_with_ffmpeg(pcm: bytes, sample_rate: int, fmt: str = "ogg", timeout: float = 60.0) -> bytes:
    """PCM16 моно → сжатый формат (ogg/opus по умолчанию)."""
    if not ffmpeg_available():
        raise AudioError("ffmpeg не найден")
    codec = {"ogg": ["-c:a", "libopus", "-b:a", "32k", "-f", "ogg"], "mp3": ["-f", "mp3"]}.get(fmt)
    if codec is None:
        raise AudioError(f"Неподдерживаемый формат: {fmt}")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-f",
        "s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "-i",
        "pipe:0",
        *codec,
        "pipe:1",
    ]
    proc = subprocess.run(cmd, input=pcm, capture_output=True, timeout=timeout, check=False)  # noqa: S603
    if proc.returncode != 0:
        raise AudioError(proc.stderr.decode(errors="ignore")[:300])
    return proc.stdout


def decode_any(data: bytes, fmt: str, sample_rate: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    """Декодировать звук в float32 моно 16 кГц.

    ``fmt``: ``pcm16`` (сырые сэмплы с частотой ``sample_rate``), ``wav`` или любой формат ffmpeg.
    """
    fmt = fmt.lower()
    if fmt in {"pcm16", "pcm", "s16le"}:
        if len(data) % 2:
            data = data[:-1]
        return resample_linear(pcm16_to_float(data), sample_rate, TARGET_SAMPLE_RATE)
    if fmt == "wav":
        try:
            return normalize_wav(data)
        except AudioError:
            pass  # не PCM16 — пусть разберётся ffmpeg
    return pcm16_to_float(decode_with_ffmpeg(data))


def frame_energy_db(samples: np.ndarray, frame: int) -> np.ndarray:
    usable = samples[: samples.size - samples.size % frame]
    if usable.size == 0:
        return np.zeros(0, dtype=np.float32)
    frames = usable.reshape(-1, frame)
    rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-12)


def split_on_silence(
    samples: np.ndarray,
    sample_rate: int = TARGET_SAMPLE_RATE,
    *,
    max_segment_s: float = 25.0,
    min_silence_s: float = 0.4,
    threshold_db: float = -40.0,
) -> list[tuple[int, int]]:
    """Разбить длинную запись на сегменты не длиннее max_segment_s, резать по паузам.

    Простой энергетический детектор пауз: в проде его заменяет Silero VAD/сервис ASR,
    но для конспектов лекций этого достаточно и он не требует моделей.
    Возвращает список (начало, конец) в сэмплах.
    """
    frame = int(sample_rate * 0.02)
    energy = frame_energy_db(samples, frame)
    silent = energy < threshold_db
    min_frames = max(1, int(min_silence_s / 0.02))
    max_frames = int(max_segment_s / 0.02)

    # кандидаты на разрез — середины длинных пауз
    cut_points: list[int] = []
    run_start = None
    for i, is_silent in enumerate(silent):
        if is_silent and run_start is None:
            run_start = i
        elif not is_silent and run_start is not None:
            if i - run_start >= min_frames:
                cut_points.append((run_start + i) // 2)
            run_start = None

    segments: list[tuple[int, int]] = []
    start = 0
    total = len(energy)
    while start < total:
        limit = min(total, start + max_frames)
        if limit == total:
            end = total
        else:
            inside = [c for c in cut_points if start < c <= limit]
            end = inside[-1] if inside else limit
        if not silent[start:end].all():
            segments.append((start * frame, min(end * frame, samples.size)))
        start = end
    return segments
