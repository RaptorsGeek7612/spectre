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
    deep = int(round(len(dry) // 2 / fx.PITCH["futuriste"]))
    assert len(wet) == 2 * (deep + int(RATE * 0.7))
    assert wet == fx.futuristic(dry, RATE) and wet != fx.ship(dry, RATE)
    assert fx.futuristic(b"", RATE) == b""
    shifted = fx._freq_shift(
        np.sin(2 * np.pi * 1000 * np.arange(RATE) / RATE).astype(np.float32), RATE, 100
    )
    peak = np.argmax(np.abs(np.fft.rfft(shifted))) * RATE / (RATE)  # 1 Hz bins over one second
    assert abs(peak - 1100) <= 2


def test_android_hologram_and_pace() -> None:
    dry = _tone(0.4)
    for effect, tail in (("androide", 0.6), ("hologramme", 1.3)):
        wet = fx.apply(effect, dry, RATE)
        deep = int(round(len(dry) // 2 / fx.PITCH[effect]))
        assert len(wet) == 2 * (deep + int(RATE * tail))
        assert wet == fx.apply(effect, dry, RATE)
        assert fx.CHAINS[effect](b"", RATE) == b""
    assert fx.length_scale("futuriste") == round(1.08 * 0.9, 3)
    assert fx.length_scale("vaisseau") == 1.08 and fx.length_scale("aucun") is None
    tone = np.sin(2 * np.pi * 400 * np.arange(RATE) / RATE).astype(np.float32)
    lowered = fx._deepen(tone, 0.8)
    assert lowered.size == int(RATE / 0.8)
    peak = np.argmax(np.abs(np.fft.rfft(lowered))) * RATE / lowered.size
    assert abs(peak - 320) < 3
    assert fx._deepen(tone, 1.0) is tone


def test_master() -> None:
    loud = np.concatenate([np.full(2000, 0.9), np.full(2000, 0.05)]).astype(np.float32)
    out = fx._master(loud, RATE)
    assert np.max(np.abs(out)) <= 1.0
    assert out[1000] / out[3000] < loud[1000] / loud[3000]  # dynamics evened out
    silent = fx._master(np.zeros(100, np.float32), RATE)
    assert not np.any(silent)
    assert fx._master(np.zeros(0, np.float32), RATE).size == 0
