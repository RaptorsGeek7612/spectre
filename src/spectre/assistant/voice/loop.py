"""The voice conversation loop: sleep → wake word → listen → think → speak → follow-up.

Components are injected (microphone, wake detector, STT, TTS, the assistant's reply function),
so the state machine is tested with fakes and runs for real with `engines`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Protocol

from spectre.assistant.voice.listen import (
    SAMPLE_RATE,
    UtteranceDetector,
    chime,
    looks_unfinished,
)

STOP_WORDS = {"stop", "arrête", "arrete", "tais-toi", "silence", "merci c'est tout"}
ACK_AFTER_S = 2.5
CONTINUE_S = 4.0  # after an unfinished sentence: how long Spectre waits for the rest


class Mic(Protocol):
    muted: threading.Event

    def blocks(self, stop: threading.Event) -> Iterator[bytes]: ...
    def flush(self) -> None: ...


class Wake(Protocol):
    def heard(self, block: bytes) -> bool: ...


class Barge(Protocol):
    """Spots a cut-off word in what the microphone hears while Spectre speaks."""

    def reset(self) -> None: ...
    def heard(self, block: bytes) -> str: ...  # the word, or ""


class VAD(Protocol):
    """Tells a voice from noise, block by block (Silero)."""

    def reset(self) -> None: ...
    def speech(self, block: bytes) -> bool: ...


class Turn(Protocol):
    """Has the speaker finished? (Smart Turn, from the audio so far)."""

    def done(self, pcm: bytes) -> bool: ...


class STT(Protocol):
    def transcribe(self, pcm: bytes) -> str: ...


class TTS(Protocol):
    def speak(self, text: str, stop: threading.Event | None = None) -> None: ...


StateFn = Callable[[str, str], None]  # (state, detail)


class VoiceLoop:
    """Runs until `stop` is set; `trigger()` skips the wake word (push-to-talk)."""

    def __init__(
        self,
        mic: Mic,
        wake: Wake,
        stt: STT,
        tts: TTS,
        reply: Callable[[str], str],
        on_state: StateFn,
        *,
        play: Callable[[bytes, int], None] | None = None,
        follow_up_s: float = 6.0,
        ack: str = "",  # optional filler while the brain thinks; off, users found it grating
        barge: Barge | None = None,
        vad: VAD | None = None,
        turn: Turn | None = None,
    ) -> None:
        self.mic, self.wake, self.stt, self.tts = mic, wake, stt, tts
        self.reply = reply
        self.on_state = on_state
        self.play = play
        self.follow_up_s = follow_up_s
        self.ack = ack
        self.barge = barge
        self.vad = vad
        self.turn = turn
        self.stop = threading.Event()
        self.interrupt = threading.Event()
        self.barged = False  # the user cut Spectre off during its last sentence
        self._triggered = threading.Event()
        self.state = "sleeping"

    def trigger(self) -> None:
        self._triggered.set()

    def say(self, text: str) -> None:
        """Speak an announcement (initiative, reminder) between turns."""
        self._speak(text)
        # back to sleep: left "speaking", the orb stayed on "je parle" and Spectre kept silent
        # (typed replies and initiatives are only spoken while the voice is "sleeping")
        self._set("sleeping", "")
        if self.barged:  # cut off: the user wants to speak, listen without the wake word
            self.trigger()

    def _set(self, state: str, detail: str = "") -> None:
        self.state = state
        self.on_state(state, detail)

    def run(self) -> None:
        self._set("sleeping", "")
        blocks = self.mic.blocks(self.stop)
        for block in blocks:
            if self.stop.is_set():
                break
            if self._triggered.is_set() or self.wake.heard(block):
                self._triggered.clear()
                self.conversation(blocks)
                self._set("sleeping", "")
        self._set("off", "")

    def conversation(self, blocks: Iterable[bytes]) -> None:
        """One or more turns until a pause longer than `follow_up_s`."""
        first = True
        while not self.stop.is_set():
            if self.play is not None:
                self.play(chime(), SAMPLE_RATE)
            self._set("listening", "")
            detector = self._detector(8.0 if first else self.follow_up_s)
            for block in blocks:
                if detector.feed(block):
                    break
            if not detector.heard_speech:
                return
            self._set("thinking", "")
            text = self.stt.transcribe(detector.audio()).strip()
            text = self._rest_of(text, blocks)
            if not text:
                return
            self.on_state("heard", text)
            if text.lower().strip(" .!?") in STOP_WORDS:
                self._speak("D'accord.")
                return
            answer = self._reply_with_ack(text)
            if answer:
                self._speak(answer)
            first = False

    def _detector(self, wait_s: float) -> UtteranceDetector:
        """Listens for one utterance, with the voice and end-of-turn models when loaded."""
        if self.vad is not None:
            self.vad.reset()
        return UtteranceDetector(
            wait_s=wait_s,
            vad=self.vad.speech if self.vad is not None else None,
            turn=self.turn.done if self.turn is not None else None,
        )

    def _rest_of(self, text: str, blocks: Iterable[bytes]) -> str:
        """The user paused mid-sentence ("je voudrais que tu…"): keep listening, without a
        chime, and add what comes next, until the sentence ends or nothing more is said."""
        while text and looks_unfinished(text) and not self.stop.is_set():
            self._set("listening", "")
            more = self._detector(CONTINUE_S)
            for block in blocks:
                if more.feed(block):
                    break
            if not more.heard_speech:
                break
            self._set("thinking", "")
            rest = self.stt.transcribe(more.audio()).strip()
            if not rest:
                break
            text = f"{text} {rest}"
        return text

    def _reply_with_ack(self, text: str) -> str:
        result: dict[str, Any] = {}
        done = threading.Event()

        def work() -> None:
            try:
                result["text"] = self.reply(text)
            except Exception as exc:  # noqa: BLE001 - spoken, never crashes the loop
                result["text"] = f"Désolé, une erreur est survenue : {exc}"
            done.set()

        threading.Thread(target=work, name="spectre-voice-reply", daemon=True).start()
        if not done.wait(ACK_AFTER_S) and self.ack:
            self._speak(self.ack)
        done.wait()
        return str(result.get("text", ""))

    def _speak(self, text: str) -> None:
        self._set("speaking", text)
        self.mic.muted.set()
        self.interrupt.clear()
        self.barged = False
        done = threading.Event()
        watcher = None
        if self.barge is not None and hasattr(self.mic, "muted_blocks"):
            watcher = threading.Thread(
                target=self._watch_barge, args=(text, done), name="spectre-barge", daemon=True
            )
            watcher.start()
        try:
            self.tts.speak(text, self.interrupt)
        finally:
            done.set()
            if watcher is not None:
                watcher.join(1.0)
            self.mic.flush()
            self.mic.muted.clear()

    def _watch_barge(self, text: str, done: threading.Event) -> None:
        """While Spectre speaks, listen for a cut-off word and stop its voice at once. A word
        that Spectre is saying itself is ignored: the microphone hears the loudspeakers.
        The microphone (`engines.Microphone`) hands its blocks over through `muted_blocks`."""
        assert self.barge is not None
        said = {w.strip(".,;:!?«»\"'()…").lower() for w in text.replace("’", "'").split()}
        self.barge.reset()
        for block in self.mic.muted_blocks(done):  # type: ignore[attr-defined]
            word = self.barge.heard(block)
            if word and word not in said:
                self.barged = True
                self.interrupt.set()
                return
