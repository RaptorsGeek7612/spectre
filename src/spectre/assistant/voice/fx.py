"""Voice effects applied to synthesised speech (int16 mono PCM in, int16 mono PCM out).

`ship` makes Spectre sound like a starship's onboard computer: a band-limited "intercom"
timbre with a presence lift, a faint ring-modulated metallic edge, short hull resonances and a
small, dark reverberation. Everything is done in the frequency domain or with vector maths, so a
sentence takes a few milliseconds.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import numpy.typing as npt

EFFECTS: Final = ("futuriste", "vaisseau", "aucun")
Signal = npt.NDArray[np.float32]


def _to_float(pcm: bytes) -> Signal:
    samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2")
    return (samples / 32768).astype(np.float32)


def _to_pcm(x: Signal, peak: float = 0.89) -> bytes:
    top = float(np.max(np.abs(x))) if x.size else 0.0
    if top > 0:
        x = x * (peak / top)
    return (np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def _delay(x: Signal, samples: int) -> Signal:
    out = np.zeros_like(x)
    if 0 < samples < x.size:
        out[samples:] = x[:-samples]
    return out


def _equalise(x: Signal, rate: int) -> Signal:
    """High-pass 170 Hz, low-pass 7 kHz, +4 dB presence around 2.2 kHz (one FFT)."""
    n = 1 << (x.size - 1).bit_length()  # power of two: a prime length makes the FFT crawl
    spectrum = np.fft.rfft(x, n)
    freqs = np.fft.rfftfreq(n, 1 / rate)
    gain = 1 / (1 + (170 / np.maximum(freqs, 1.0)) ** 4)  # 4th-order-like high-pass
    gain *= 1 / (1 + (freqs / 7000) ** 6)  # steep low-pass
    gain *= 1 + 0.6 * np.exp(-(((freqs - 2200) / 700) ** 2))  # presence
    return np.fft.irfft(spectrum * gain, n)[: x.size].astype(np.float32)


def _reverb(x: Signal, rate: int, seconds: float = 0.45, mix: float = 0.16) -> Signal:
    """Short dark room: decaying noise impulse response, convolved by FFT."""
    length = int(rate * seconds)
    t = np.arange(length, dtype=np.float32) / rate
    rng = np.random.default_rng(7)  # deterministic: same voice every time
    ir = rng.standard_normal(length).astype(np.float32) * np.exp(-t / 0.11)
    ir[0] = 0.0
    ir /= float(np.sqrt(np.sum(ir**2))) or 1.0
    size = x.size + length
    n = 1 << (size - 1).bit_length()
    wet = np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(ir, n), n)[:size].astype(np.float32)
    dry = np.concatenate([x, np.zeros(length, dtype=np.float32)])
    return (1 - mix) * dry + mix * wet


def _freq_shift(x: Signal, rate: int, hz: float) -> Signal:
    """Single-sideband frequency shift (inharmonic, the classic sci-fi robot colour)."""
    n = 1 << (x.size - 1).bit_length()
    spectrum = np.fft.fft(x, n)
    spectrum[n // 2 + 1 :] = 0  # analytic signal: keep positive frequencies only
    spectrum[1 : n // 2] *= 2
    analytic = np.fft.ifft(spectrum)[: x.size]
    t = np.arange(x.size) / rate
    return np.real(analytic * np.exp(2j * np.pi * hz * t)).astype(np.float32)


def ship(pcm: bytes, rate: int, intensity: float = 1.0) -> bytes:
    """Onboard-computer voice. `intensity` 0 keeps the voice almost natural, 1 is the default."""
    x = _to_float(pcm)
    if x.size == 0:
        return b""
    k = float(np.clip(intensity, 0.0, 1.5))
    t = np.arange(x.size, dtype=np.float32) / rate
    ring = 0.14 * k
    x = (1 - ring) * x + ring * x * np.sin(2 * np.pi * 62 * t).astype(np.float32)
    x = x + 0.32 * k * _delay(x, int(0.0061 * rate)) - 0.22 * k * _delay(x, int(0.0107 * rate))
    x = x + 0.18 * k * _delay(x, int(0.019 * rate))  # synthetic doubling
    x = _equalise(x, rate)
    x = _reverb(x, rate, mix=0.16 * k)
    return _to_pcm(x)


def futuristic(pcm: bytes, rate: int) -> bytes:
    """The onboard AI, pushed further: shifted harmonies layered on a metallic, spacious voice."""
    x = _to_float(pcm)
    if x.size == 0:
        return b""
    t = np.arange(x.size, dtype=np.float32) / rate
    x = 0.8 * x + 0.2 * x * np.sin(2 * np.pi * 48 * t).astype(np.float32)
    x = x + 0.34 * _freq_shift(x, rate, 110) + 0.3 * _freq_shift(x, rate, -55)
    x = x + 0.4 * _delay(x, int(0.0053 * rate)) - 0.28 * _delay(x, int(0.0089 * rate))
    x = x + 0.2 * _delay(x, int(0.023 * rate))
    x = _equalise(x, rate)
    x = _reverb(x, rate, seconds=0.7, mix=0.24)
    return _to_pcm(x)


def apply(effect: str, pcm: bytes, rate: int) -> bytes:
    """Apply a named effect (`aucun` or unknown names leave the voice untouched)."""
    if effect == "futuriste":
        return futuristic(pcm, rate)
    return ship(pcm, rate) if effect == "vaisseau" else pcm
