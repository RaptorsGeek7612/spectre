"""Device and model adapters: microphone, speaker, Vosk wake word, Whisper STT, Piper TTS.

These need audio hardware and downloaded models, so they are exercised manually, not in CI.
Models are downloaded on first use into `<assistant dir>/models`.
"""
# pragma: no cover-start  (coverage config omits this module; see pyproject)

from __future__ import annotations

import contextlib
import io
import json
import queue
import subprocess
import sys
import threading
import types
import urllib.request
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from spectre.assistant.voice.listen import SAMPLE_RATE

VOSK_MODEL = "vosk-model-small-fr-0.22"
VOSK_URL = f"https://alphacephei.com/vosk/models/{VOSK_MODEL}.zip"


class Microphone:
    """16 kHz mono int16 blocks from the default input device."""

    def __init__(self, block_s: float = 0.1, device: Any = None) -> None:
        self.block = int(SAMPLE_RATE * block_s)
        self.device = device
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=200)
        self._stream: Any = None
        self.muted = threading.Event()  # set while Spectre speaks (no self-echo)

    def __enter__(self) -> Microphone:
        import sounddevice as sd

        def callback(indata: Any, _frames: int, _time: Any, _status: Any) -> None:
            if not self.muted.is_set():
                with contextlib.suppress(queue.Full):
                    self._queue.put_nowait(bytes(indata))

        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=self.block,
            dtype="int16",
            channels=1,
            callback=callback,
            device=self.device,
        )
        self._stream.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()

    def blocks(self, stop: threading.Event) -> Iterator[bytes]:
        while not stop.is_set():
            try:
                yield self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

    def flush(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()


def play_pcm(pcm: bytes, rate: int, stop: threading.Event | None = None) -> None:
    """Play int16 mono PCM, interruptible by `stop`."""
    import numpy as np
    import sounddevice as sd

    data = np.frombuffer(pcm, dtype=np.int16)
    sd.play(data, rate)
    duration = len(data) / rate
    waited = 0.0
    while waited < duration + 0.2:
        if stop is not None and stop.wait(0.05):
            sd.stop()
            return
        waited += 0.05
    sd.wait()


class VoskWake:
    """Detects the wake word with a one-word grammar (cheap, offline)."""

    def __init__(self, models: Path, word: str = "spectre") -> None:
        import vosk

        vosk.SetLogLevel(-1)
        path = ensure_vosk(models)
        self.word = word.lower()
        self.model = vosk.Model(str(path))
        self._new()

    def _new(self) -> None:
        import vosk

        grammar = json.dumps([self.word, "[unk]"])
        self.rec = vosk.KaldiRecognizer(self.model, SAMPLE_RATE, grammar)

    def heard(self, block: bytes) -> bool:
        if self.rec.AcceptWaveform(block):
            text = json.loads(self.rec.Result()).get("text", "")
        else:
            text = json.loads(self.rec.PartialResult()).get("partial", "")
        if self.word in text.split():
            self._new()
            return True
        return False


class WhisperSTT:
    """faster-whisper on CPU (int8)."""

    def __init__(self, model_size: str = "base", language: str = "fr") -> None:
        try:
            import av  # noqa: F401
        except ImportError:
            # Some Windows setups block PyAV's DLLs; it is only needed to decode files,
            # and Spectre passes raw arrays.
            sys.modules["av"] = types.ModuleType("av")
        from faster_whisper import WhisperModel

        self.language = language
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe(self, pcm: bytes) -> str:
        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=1,
            vad_filter=False,
            initial_prompt="Spectre, assistant personnel.",
        )
        return " ".join(s.text.strip() for s in segments).strip()


class PiperTTS:
    """Piper neural voice; falls back to the Windows voice if Piper fails."""

    def __init__(
        self,
        models: Path,
        voice: str = "fr_FR-tom-medium",
        speaker: str = "",
        effect: str = "futuriste",
    ) -> None:
        from piper import PiperVoice, SynthesisConfig

        from spectre.assistant.voice import fx

        path = ensure_piper_voice(models, voice)
        self.voice = PiperVoice.load(str(path))
        self.effect = effect
        speakers = getattr(self.voice.config, "speaker_id_map", None) or {}
        self.syn = SynthesisConfig(
            speaker_id=speakers.get(speaker),
            length_scale=fx.length_scale(effect),  # calm cadence, offsets the deepening
        )

    def speak(self, text: str, stop: threading.Event | None = None) -> None:
        buffer = io.BytesIO()
        rate = 22050
        for chunk in self.voice.synthesize(text, syn_config=self.syn):
            rate = chunk.sample_rate
            buffer.write(chunk.audio_int16_bytes)
            if stop is not None and stop.is_set():
                return
        from spectre.assistant.voice import fx

        play_pcm(fx.apply(self.effect, buffer.getvalue(), rate), rate, stop)


class WindowsTTS:
    """The built-in Windows voice through PowerShell (no download)."""

    def speak(self, text: str, stop: threading.Event | None = None) -> None:
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'fr*' } "
            "| Select-Object -First 1; if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
            "$s.Speak([Console]::In.ReadToEnd())"
        )
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", script],
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        assert proc.stdin is not None
        proc.stdin.write(text)
        proc.stdin.close()
        while proc.poll() is None:
            if stop is not None and stop.wait(0.1):
                proc.kill()
                return


def ensure_vosk(models: Path) -> Path:
    target = models / VOSK_MODEL
    if target.is_dir():
        return target
    models.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(VOSK_URL, timeout=120) as response:  # noqa: S310 - fixed host
        data = response.read()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(models)
    return target


def ensure_piper_voice(models: Path, voice: str) -> Path:
    folder = models / "piper"
    path = folder / f"{voice}.onnx"
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "piper.download_voices", voice, "--download-dir", str(folder)],
            check=True,
            capture_output=True,
        )
    return path


def make_tts(models: Path, voice: str, speaker: str = "", effect: str = "futuriste") -> Any:
    try:
        return PiperTTS(models, voice, speaker, effect)
    except Exception:  # noqa: BLE001 - any Piper failure falls back to the system voice
        return WindowsTTS()
