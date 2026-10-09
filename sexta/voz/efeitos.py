"""Efeito "IA do traje" na voz: o timbre de assistente de filme, sem distorcer as palavras.

Tudo vetorizado em numpy (FFT), leva poucos milissegundos por frase:

1. equalização: corta graves embolados e agudos chiados, realça a "presença" (2–4 kHz)
   e um brilho fino em 6–7 kHz;
2. duplicação: uma cópia 9 ms atrasada, com atraso oscilando devagar (chorus leve) —
   é o que dá o ar "sintético";
3. ambiente: reflexões curtas, como a voz saindo de dentro do capacete.
"""

from __future__ import annotations

import numpy as np


def _equalizar(audio: np.ndarray, taxa: int) -> np.ndarray:
    n = len(audio)
    tamanho = 1 << (n - 1).bit_length()
    espectro = np.fft.rfft(audio, tamanho)
    f = np.fft.rfftfreq(tamanho, 1 / taxa)
    ganho = np.ones_like(f)
    ganho *= 1 / np.sqrt(1 + (110 / np.maximum(f, 1)) ** 4)              # passa-altas ~110 Hz
    ganho *= 1 / np.sqrt(1 + (f / 9500) ** 6)                             # passa-baixas ~9,5 kHz
    ganho *= 1 + 0.35 * np.exp(-0.5 * ((f - 3000) / 900) ** 2)           # presença
    ganho *= 1 + 0.25 * np.exp(-0.5 * ((f - 6500) / 700) ** 2)           # brilho
    ganho *= 1 - 0.18 * np.exp(-0.5 * ((f - 350) / 150) ** 2)           # tira o "abafado"
    return np.fft.irfft(espectro * ganho, tamanho)[:n]


def _duplicar(audio: np.ndarray, taxa: int) -> np.ndarray:
    t = np.arange(len(audio))
    atraso = (0.009 + 0.0015 * np.sin(2 * np.pi * 0.6 * t / taxa)) * taxa
    copia = np.interp(t - atraso, t, audio, left=0.0)
    return audio + 0.22 * copia


def _ambiente(audio: np.ndarray, taxa: int) -> np.ndarray:
    rng = np.random.default_rng(7)  # fixo: a mesma frase soa sempre igual
    duracao = int(0.09 * taxa)
    impulso = rng.standard_normal(duracao) * np.exp(-np.arange(duracao) / (0.022 * taxa))
    impulso[: int(0.004 * taxa)] = 0  # sem reflexão colada no som direto
    impulso *= 0.10 / np.sqrt(np.sum(impulso ** 2))
    n = len(audio) + duracao - 1
    tamanho = 1 << (n - 1).bit_length()
    molhado = np.fft.irfft(np.fft.rfft(audio, tamanho) * np.fft.rfft(impulso, tamanho), tamanho)[: len(audio)]
    return audio + molhado


def traje(audio: np.ndarray, taxa: int, intensidade: float = 1.0) -> np.ndarray:
    """Aplica o efeito. ``audio`` float32 mono em [-1, 1]; devolve no mesmo formato."""
    if audio.size < taxa * 0.05 or intensidade <= 0:
        return audio
    seco = audio.astype(np.float64)
    pico_original = float(np.max(np.abs(seco))) or 1.0
    processado = _ambiente(_duplicar(_equalizar(seco, taxa), taxa), taxa)
    saida = (1 - intensidade) * seco + intensidade * processado
    saida *= min(pico_original, 0.95) / (float(np.max(np.abs(saida))) or 1.0)  # mesmo volume, sem estourar
    return saida.astype(np.float32)


def para_wav(audio: np.ndarray, taxa: int) -> bytes:
    """float32 mono -> WAV PCM 16 bits (para tocar no celular)."""
    import io
    import wave

    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(pcm)
    return buffer.getvalue()
