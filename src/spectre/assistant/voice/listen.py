"""Pure-Python audio logic (no device): end-of-utterance detection and a short chime."""

from __future__ import annotations

import array
import io
import math
import wave
from collections.abc import Callable, Sequence
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

    Starts after speech is heard (energy above the adaptive noise floor, and a voice for
    `vad` when given), stops after `silence_s` of quiet, or at `max_s`. `feed` returns True
    when the utterance is complete.

    With `turn` (Smart Turn: "has the speaker finished?", from the audio so far), as the
    leading voice assistants do: at the first `turn_after_s` of each pause the model is asked;
    finished, the turn ends at once; not finished (a pause to think), it waits for the voice
    to come back, up to `turn_cap_s`. A failing model falls back to `silence_s`.
    """

    block_s: float = 0.1
    silence_s: float = 1.8  # a pause to think must not end the turn (see `looks_unfinished`)
    max_s: float = 25.0
    pre_roll_s: float = 0.4  # keep the audio just before speech: the first syllable
    wait_s: float = 6.0  # give up if nothing is said after the wake word
    min_speech_s: float = 0.3
    floor: float = 300.0
    chunks: list[bytes] = field(default_factory=list)
    speaking: bool = False
    speech_blocks: int = 0
    quiet_blocks: int = 0
    total_blocks: int = 0
    before: list[bytes] = field(default_factory=list)
    vad: Callable[[bytes], bool] | None = None  # is this block a voice (not a fan, a door)?
    turn: Callable[[bytes], bool] | None = None  # has the speaker finished?
    turn_after_s: float = 0.3
    turn_cap_s: float = 2.5
    asked: bool = False  # the model was asked during this pause
    verdicts: list[bool] = field(default_factory=list)  # its answers, for the log

    def _voiced(self, block: bytes, level: float, threshold: float) -> bool:
        if level < threshold:
            return False
        if self.vad is None:
            return True
        try:
            return self.vad(block)
        except Exception:  # noqa: BLE001 - a broken model must not deafen Spectre
            self.vad = None
            return True

    def _finished(self) -> bool:
        assert self.turn is not None
        try:
            done = bool(self.turn(self.audio()))
        except Exception:  # noqa: BLE001 - back to the plain pause
            self.turn = None
            return False
        self.verdicts.append(done)
        return done

    def feed(self, block: bytes) -> bool:
        self.total_blocks += 1
        level = rms(block)
        threshold = max(self.floor * 2.5, 500.0)
        if not self.speaking:
            self.floor = 0.9 * self.floor + 0.1 * level if level < threshold else self.floor
            if self._voiced(block, level, threshold):
                self.speaking = True
                self.chunks.extend(self.before)  # the onset was quieter than the threshold
            elif self.total_blocks * self.block_s >= self.wait_s:
                return True
            else:
                self.before = [*self.before, block][
                    -max(0, round(self.pre_roll_s / self.block_s)) :
                ]
        if self.speaking:
            self.chunks.append(block)
            if self._voiced(block, level, threshold):
                self.speech_blocks += 1
                self.quiet_blocks = 0
                self.asked = False
            else:
                self.quiet_blocks += 1
            quiet = self.quiet_blocks * self.block_s
            if self.turn is not None and self.heard_speech:
                if not self.asked and quiet >= self.turn_after_s - 1e-9:
                    self.asked = True
                    if self._finished():
                        return True
                if self.turn is not None:
                    return quiet >= self.turn_cap_s - 1e-9 or self._too_long()
            if quiet >= self.silence_s - 1e-9:
                return True
        return self._too_long()

    def _too_long(self) -> bool:
        return self.total_blocks * self.block_s >= self.max_s

    @property
    def heard_speech(self) -> bool:
        return self.speech_blocks * self.block_s >= self.min_speech_s

    def audio(self) -> bytes:
        return b"".join(self.chunks)


# Last words after which a French sentence cannot be over: the speaker paused to think.
_ENDINGS = (
    "et ou mais donc car ni puis alors ensuite parce puisque que qu dont si quand comme "
    "lorsque de d du des le la l les un une au aux à en pour avec sans sur sous dans par chez "
    "vers entre mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs ce cet cette "
    "ces je j tu il on ils me m te t se s ne n euh heu hum bah ben genre est-ce "
    "c'est-à-dire notamment très"
)  # not "quoi", "qui", "où", "vous"…: "c'est quoi ?", "merci à vous" are whole sentences
UNFINISHED_ENDINGS = frozenset(_ENDINGS.split())


def looks_unfinished(text: str) -> bool:
    """True when a transcript stops mid-sentence ("je voudrais que tu…", "et euh,"): the
    speaker is thinking, so Spectre keeps listening instead of answering half a request."""
    words = text.strip().lower()
    if not words:
        return False
    if words.endswith(("…", "...", ",", ":", ";", "-")):
        return True
    last = words.rstrip(" .!?").replace("’", "'").split()
    if not last:
        return False
    word = last[-1].strip("\"'«»()")
    return word in UNFINISHED_ENDINGS or word.endswith("'")


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
