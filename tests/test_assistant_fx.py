"""Tests for the voice effects (pure signal processing, no audio device)."""

from __future__ import annotations

import numpy as np

from spectre.assistant.voice import fx

RATE = 22050


def _tone(seconds: float = 0.5, freq: float = 440.0) -> bytes:
    t = np.arange(int(RATE * seconds)) / RATE
    return (0.5 * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2").tobytes()


def test_ship_shapes_and_extends_the_voice() -> None:
    dry = _tone()
    wet = fx.ship(dry, RATE)
    assert len(wet) == len(dry) + 2 * int(RATE * 0.45)  # reverb tail
    samples = np.frombuffer(wet, dtype="<i2")
    assert 0.85 < np.max(np.abs(samples)) / 32767 < 0.9  # normalised, no clipping
    assert wet != fx.ship(dry, RATE, intensity=0.0)
    assert fx.ship(dry, RATE) == wet  # deterministic


def test_ship_edge_cases_and_apply() -> None:
    assert fx.ship(b"", RATE) == b""
    assert fx.ship(b"\x01", RATE) == b""
    silent = fx.ship(bytes(2000), RATE)
    assert not np.any(np.frombuffer(silent, dtype="<i2"))
    dry = _tone(0.1)
    assert fx.apply("aucun", dry, RATE) == dry
    assert fx.apply("inconnu", dry, RATE) == dry
    assert fx.apply("vaisseau", dry, RATE) == fx.ship(dry, RATE)
    assert fx._delay(np.ones(3, dtype=np.float32), 5).tolist() == [0, 0, 0]
    assert fx.EFFECTS[0] == "futuriste"


def test_futuristic() -> None:
    dry = _tone()
    wet = fx.apply("futuriste", dry, RATE)
    assert len(wet) == len(dry) + 2 * int(RATE * 0.7)
    assert wet == fx.futuristic(dry, RATE) and wet != fx.ship(dry, RATE)
    assert fx.futuristic(b"", RATE) == b""
    shifted = fx._freq_shift(
        np.sin(2 * np.pi * 1000 * np.arange(RATE) / RATE).astype(np.float32), RATE, 100
    )
    peak = np.argmax(np.abs(np.fft.rfft(shifted))) * RATE / (RATE)  # 1 Hz bins over one second
    assert abs(peak - 1100) <= 2
