"""The voice conversation loop: sleep → wake word → listen → think → speak → follow-up.

Components are injected (microphone, wake detector, STT, TTS, the assistant's reply function),
so the state machine is tested with fakes and runs for real with `engines`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Protocol

from spectre.assistant.voice.listen import SAMPLE_RATE, UtteranceDetector, chime

STOP_WORDS = {"stop", "arrête", "arrete", "tais-toi", "silence", "merci c'est tout"}
ACK_AFTER_S = 2.5


class Mic(Protocol):
    muted: threading.Event

    def blocks(self, stop: threading.Event) -> Iterator[bytes]: ...
    def flush(self) -> None: ...


class Wake(Protocol):
    def heard(self, block: bytes) -> bool: ...


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
    ) -> None:
        self.mic, self.wake, self.stt, self.tts = mic, wake, stt, tts
        self.reply = reply
        self.on_state = on_state
        self.play = play
        self.follow_up_s = follow_up_s
        self.ack = ack
        self.stop = threading.Event()
        self.interrupt = threading.Event()
        self._triggered = threading.Event()
        self.state = "sleeping"

    def trigger(self) -> None:
        self._triggered.set()

    def say(self, text: str) -> None:
        """Speak an announcement (initiative, reminder) between turns."""
        self._speak(text)

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
            detector = UtteranceDetector(wait_s=8.0 if first else self.follow_up_s)
            for block in blocks:
                if detector.feed(block):
                    break
            if not detector.heard_speech:
                return
            self._set("thinking", "")
            text = self.stt.transcribe(detector.audio()).strip()
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
        try:
            self.interrupt.clear()
            self.tts.speak(text, self.interrupt)
        finally:
            self.mic.flush()
            self.mic.muted.clear()
