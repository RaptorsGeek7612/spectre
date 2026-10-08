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

EFFECTS: Final = ("futuriste", "androide", "hologramme", "vaisseau", "aucun")
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


def _deepen(x: Signal, factor: float) -> Signal:
    """Lower the pitch by resampling (`factor` < 1); the voice also gets 1/factor longer, so
    the synthesiser speaks `factor` times faster beforehand (see `length_scale`)."""
    if factor >= 1.0 or x.size < 2:
        return x
    size = int(round(x.size / factor))
    return np.asarray(np.interp(np.arange(size) * factor, np.arange(x.size), x), dtype=np.float32)


def _stft(x: Signal, n: int, hop: int) -> npt.NDArray[np.complex128]:
    padded = np.concatenate([np.zeros(n, np.float32), x, np.zeros(n, np.float32)])
    count = 1 + (padded.size - n) // hop
    index = np.arange(n)[None, :] + hop * np.arange(count)[:, None]
    return np.fft.rfft(padded[index] * np.hanning(n), axis=1)


def _istft(spec: npt.NDArray[np.complex128], n: int, hop: int, size: int) -> Signal:
    frames = np.fft.irfft(spec, n, axis=1) * np.hanning(n)
    out = np.zeros(hop * (len(frames) - 1) + n)
    norm = np.zeros_like(out)
    for i, frame in enumerate(frames):
        out[i * hop : i * hop + n] += frame
        norm[i * hop : i * hop + n] += np.hanning(n) ** 2
    return (out / np.maximum(norm, 1e-3))[n : n + size].astype(np.float32)


def _smooth(mag: npt.NDArray[np.float64], width: int) -> npt.NDArray[np.float64]:
    """Moving average along frequency: the spectral envelope (formants) of each frame."""
    cum = np.cumsum(np.pad(mag, ((0, 0), (width, width)), mode="edge"), axis=1)
    return (cum[:, 2 * width :] - cum[:, : -2 * width]) / (2 * width)


def _vocode(x: Signal, rate: int, f0: float = 92.0) -> Signal:
    """Channel vocoder: a synth chord (root + fifth + air) shaped by the voice's formants."""
    t = np.arange(x.size) / rate

    def saw(freq: float) -> npt.NDArray[np.float64]:
        return 2 * ((t * freq) % 1.0) - 1

    noise = np.random.default_rng(3).standard_normal(x.size) * 0.15  # keeps consonants
    carrier = (saw(f0) + 0.6 * saw(f0 * 1.5) + 0.35 * saw(f0 * 2) + noise).astype(np.float32)
    n, hop = 1024, 256
    voice, synth = _stft(x, n, hop), _stft(carrier, n, hop)
    envelope = _smooth(np.abs(voice), 6) / (_smooth(np.abs(synth), 6) + 1e-6)
    out = _istft(synth * envelope, n, hop, x.size)
    gain = float(np.sqrt(np.mean(x**2)) / (np.sqrt(np.mean(out**2)) + 1e-9))
    return out * gain


def _metal(x: Signal, rate: int, k: float = 1.0) -> Signal:
    """Short hull resonances and a synthetic double."""
    x = x + 0.4 * k * _delay(x, int(0.0053 * rate)) - 0.28 * k * _delay(x, int(0.0089 * rate))
    return x + 0.2 * k * _delay(x, int(0.023 * rate))


def _master(x: Signal, rate: int) -> Signal:
    """Broadcast polish: RMS compressor (even, present voice) then gentle tape-like saturation."""
    if x.size == 0:
        return x
    win = max(1, min(x.size, int(0.012 * rate)))  # never longer than the signal
    power = np.convolve(x.astype(np.float64) ** 2, np.ones(win) / win, mode="same")
    level = np.sqrt(power) + 1e-6
    ref = float(np.percentile(level, 90))
    threshold = 0.35 * ref
    gain = np.where(level > threshold, (threshold / level) ** 0.6, 1.0)  # about 2.5:1 above
    y = x * gain.astype(np.float32)
    y /= float(np.max(np.abs(y))) or 1.0
    return np.tanh(1.6 * y).astype(np.float32)


def futuristic(pcm: bytes, rate: int) -> bytes:
    """Onboard AI, deeper: shifted harmonies layered on a metallic, spacious voice."""
    x = _deepen(_to_float(pcm), PITCH["futuriste"])
    if x.size == 0:
        return b""
    t = np.arange(x.size, dtype=np.float32) / rate
    x = 0.8 * x + 0.2 * x * np.sin(2 * np.pi * 48 * t).astype(np.float32)
    sub_octave = _deepen(x, 0.5)[: x.size]  # gravitas, an octave below
    x = x + 0.34 * _freq_shift(x, rate, 110) + 0.3 * _freq_shift(x, rate, -55) + 0.22 * sub_octave
    x = _master(_equalise(_metal(x, rate), rate), rate)
    return _to_pcm(_reverb(x, rate, seconds=0.7, mix=0.24))


def android(pcm: bytes, rate: int) -> bytes:
    """Film robot: vocoder chord blended with the (deepened) voice to stay intelligible."""
    x = _deepen(_to_float(pcm), PITCH["androide"])
    if x.size == 0:
        return b""
    x = 0.6 * _vocode(x, rate) + 0.45 * x
    x = _master(_equalise(_metal(x, rate, 0.7), rate), rate)
    return _to_pcm(_reverb(x, rate, seconds=0.6, mix=0.2))


def hologram(pcm: bytes, rate: int) -> bytes:
    """Shimmering projection: detuned chorus, a faint upper ghost, tremolo and a vast space."""
    x = _deepen(_to_float(pcm), PITCH["hologramme"])
    if x.size == 0:
        return b""
    t = np.arange(x.size, dtype=np.float32) / rate
    x = (
        x
        + 0.5 * _freq_shift(x, rate, 6)
        + 0.5 * _freq_shift(x, rate, -7)
        + 0.22 * _freq_shift(x, rate, 190)
    )
    x = x * (1 + 0.12 * np.sin(2 * np.pi * 7.5 * t)).astype(np.float32)
    x = _master(_equalise(x, rate), rate)
    return _to_pcm(_reverb(x, rate, seconds=1.3, mix=0.3))


PITCH: Final = {"futuriste": 0.9, "androide": 0.93, "hologramme": 0.92}
CHAINS: Final = {
    "futuriste": futuristic,
    "androide": android,
    "hologramme": hologram,
    "vaisseau": ship,
}


def length_scale(effect: str) -> float | None:
    """Piper speaking pace for an effect: calm, and faster to make up for the deepening."""
    if effect not in CHAINS:
        return None
    return round(1.08 * PITCH.get(effect, 1.0), 3)


def apply(effect: str, pcm: bytes, rate: int) -> bytes:
    """Apply a named effect (`aucun` or unknown names leave the voice untouched)."""
    chain = CHAINS.get(effect)
    return chain(pcm, rate) if chain else pcm
