"""Pure-Python audio logic (no device): end-of-utterance detection and a short chime."""

from __future__ import annotations

import array
import io
import math
import wave
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

SAMPLE_RATE = 16_000


def rms(block: bytes) -> float:
    """Root mean square of little-endian int16 PCM (0-32768)."""
    samples = array.array("h")
    samples.frombytes(block[: len(block) - len(block) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


@dataclass
class UtteranceDetector:
    """Collects audio blocks until the speaker pauses.

    Starts after speech is heard (energy above the adaptive noise floor), stops after
    `silence_s` of quiet, or at `max_s`. `feed` returns True when the utterance is complete.
    """

    block_s: float = 0.1
    silence_s: float = 0.9
    max_s: float = 15.0
    wait_s: float = 6.0  # give up if nothing is said after the wake word
    min_speech_s: float = 0.3
    floor: float = 300.0
    chunks: list[bytes] = field(default_factory=list)
    speaking: bool = False
    speech_blocks: int = 0
    quiet_blocks: int = 0
    total_blocks: int = 0

    def feed(self, block: bytes) -> bool:
        self.total_blocks += 1
        level = rms(block)
        threshold = max(self.floor * 2.5, 500.0)
        if not self.speaking:
            self.floor = 0.9 * self.floor + 0.1 * level if level < threshold else self.floor
            if level >= threshold:
                self.speaking = True
            elif self.total_blocks * self.block_s >= self.wait_s:
                return True
        if self.speaking:
            self.chunks.append(block)
            if level >= threshold:
                self.speech_blocks += 1
                self.quiet_blocks = 0
            else:
                self.quiet_blocks += 1
            if self.quiet_blocks * self.block_s >= self.silence_s:
                return True
        return self.total_blocks * self.block_s >= self.max_s

    @property
    def heard_speech(self) -> bool:
        return self.speech_blocks * self.block_s >= self.min_speech_s

    def audio(self) -> bytes:
        return b"".join(self.chunks)


def to_wav(pcm: bytes, rate: int) -> bytes:
    """Mono int16 PCM as a WAV file (what a browser can decode and play)."""
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm[: len(pcm) - len(pcm) % 2])
    return out.getvalue()


def chime(freq: float = 880.0, seconds: float = 0.12, volume: float = 0.25) -> bytes:
    """A short sine 'I'm listening' tone as int16 PCM at SAMPLE_RATE."""
    count = int(SAMPLE_RATE * seconds)
    data = array.array("h")
    for i in range(count):
        fade = min(1.0, i / 200, (count - i) / 200)
        data.append(int(32767 * volume * fade * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))
    return data.tobytes()


# Inputs that record what the PC plays, not the person: never listen to those by default.
NOT_A_MICROPHONE = ("mixage stéréo", "stereo mix", "what u hear", "loopback", "mappeur", "mapper")


def pick_input(devices: Sequence[dict[str, Any]], default: int, wanted: str = "") -> int | None:
    """Index of the input device to open; None keeps the system default.

    `wanted` (part of a name) wins. Otherwise the default is kept when it is a real microphone,
    else the first input whose name says "micro" (Windows often defaults to "Stereo Mix").
    """
    inputs = [(i, str(d["name"]).lower()) for i, d in enumerate(devices) if d["max_input_channels"]]
    if wanted.strip():
        match = next((i for i, name in inputs if wanted.strip().lower() in name), None)
        if match is None:
            raise ValueError(f"micro introuvable : {wanted}")
        return match
    names = dict(inputs)
    if default in names and not any(word in names[default] for word in NOT_A_MICROPHONE):
        return None
    return next(
        (
            i
            for i, name in inputs
            if "micro" in name and not any(word in name for word in NOT_A_MICROPHONE)
        ),
        None,
    )
