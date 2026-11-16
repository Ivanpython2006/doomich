"""Лог-мел спектрограмма как слой PyTorch, который экспортируется в ONNX без операции STFT.

ДПФ реализовано свёрткой с фиксированными ядрами (cos/sin × окно Ханна), поэтому модель
слова активации принимает «сырой» звук 16 кГц и одинаково работает в PyTorch, onnxruntime
на сервере и onnxruntime в мобильном приложении.
"""

from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn


def hz_to_mel(f: np.ndarray | float) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + np.asarray(f) / 700.0)


def mel_to_hz(m: np.ndarray | float) -> np.ndarray:
    return 700.0 * (10 ** (np.asarray(m) / 2595.0) - 1.0)


def mel_filterbank(sample_rate: int, n_fft: int, n_mels: int, fmin: float, fmax: float) -> np.ndarray:
    n_freqs = n_fft // 2 + 1
    freqs = np.linspace(0, sample_rate / 2, n_freqs)
    mel_points = mel_to_hz(np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2))
    bank = np.zeros((n_mels, n_freqs), dtype=np.float32)
    for i in range(n_mels):
        left, center, right = mel_points[i], mel_points[i + 1], mel_points[i + 2]
        up = (freqs - left) / max(center - left, 1e-6)
        down = (right - freqs) / max(right - center, 1e-6)
        bank[i] = np.maximum(0.0, np.minimum(up, down))
    return bank


class LogMel(nn.Module):
    def __init__(
        self,
        sample_rate: int = 16000,
        n_fft: int = 400,
        hop: int = 160,
        n_mels: int = 40,
        fmin: float = 20.0,
        fmax: float = 7600.0,
    ) -> None:
        super().__init__()
        self.hop = hop
        self.n_freqs = n_fft // 2 + 1
        n = torch.arange(n_fft, dtype=torch.float32)
        k = torch.arange(self.n_freqs, dtype=torch.float32)
        window = 0.5 - 0.5 * torch.cos(2 * math.pi * n / n_fft)
        angle = 2 * math.pi * k[:, None] * n[None, :] / n_fft
        kernels = torch.cat([torch.cos(angle) * window, -torch.sin(angle) * window])[:, None, :]
        self.register_buffer("dft", kernels, persistent=False)
        self.register_buffer(
            "mel", torch.from_numpy(mel_filterbank(sample_rate, n_fft, n_mels, fmin, fmax)), persistent=False
        )

    def forward(self, wav: torch.Tensor) -> torch.Tensor:  # [B, S] → [B, n_mels, T]
        spec = F.conv1d(wav[:, None, :], self.dft, stride=self.hop)
        real, imag = spec[:, : self.n_freqs], spec[:, self.n_freqs :]
        power = real * real + imag * imag
        mel = torch.matmul(self.mel, power)
        logmel = torch.log(mel + 1e-6)
        # нормализация на уровне примера: модель не зависит от громкости
        return logmel - logmel.mean(dim=(1, 2), keepdim=True)
