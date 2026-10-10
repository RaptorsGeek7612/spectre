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
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from spectre.assistant.voice.listen import SAMPLE_RATE, rms

Level = Callable[[float], None]

VOSK_MODEL = "vosk-model-small-fr-0.22"
VOSK_URL = f"https://alphacephei.com/vosk/models/{VOSK_MODEL}.zip"


def pick_microphone(wanted: str = "") -> tuple[int | None, str]:
    """The device to listen to (see `listen.pick_input`) and its name, for the console."""
    import sounddevice as sd

    from spectre.assistant.voice.listen import pick_input

    devices = list(sd.query_devices())
    default = sd.default.device[0]
    index = pick_input(devices, int(default) if default is not None else -1, wanted)
    name = devices[index]["name"] if index is not None else sd.query_devices(kind="input")["name"]
    return index, str(name)


class Microphone:
    """16 kHz mono int16 blocks from the default input device."""

    def __init__(
        self, block_s: float = 0.1, device: Any = None, on_level: Level | None = None
    ) -> None:
        self.block = int(SAMPLE_RATE * block_s)
        self.device = device
        self.on_level = on_level  # RMS of each heard block, for the UI's voice orb
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=200)
        self._stream: Any = None
        self.muted = threading.Event()  # set while Spectre speaks (no self-echo)

    def __enter__(self) -> Microphone:
        import sounddevice as sd

        def callback(indata: Any, _frames: int, _time: Any, _status: Any) -> None:
            if not self.muted.is_set():
                block = bytes(indata)
                with contextlib.suppress(queue.Full):
                    self._queue.put_nowait(block)
                if self.on_level is not None:
                    self.on_level(rms(block))

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


def play_pcm(
    pcm: bytes, rate: int, stop: threading.Event | None = None, on_level: Level | None = None
) -> None:
    """Play int16 mono PCM, interruptible by `stop`; report the playing loudness to `on_level`."""
    import numpy as np
    import sounddevice as sd

    data = np.frombuffer(pcm, dtype=np.int16)
    sd.play(data, rate)
    duration = len(data) / rate
    window = max(1, int(rate * 0.05))
    waited = 0.0
    while waited < duration + 0.2:
        if on_level is not None:
            start = int(waited * rate)
            on_level(rms(data[start : start + window].tobytes()))
        if stop is not None and stop.wait(0.05):
            sd.stop()
            return
        if stop is None:
            threading.Event().wait(0.05)
        waited += 0.05
    if on_level is not None:
        on_level(0.0)
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


# Names Whisper tends to mishear in French speech; the prompt biases it towards them.
# A short context for the recogniser. A long list of words gets copied out as if it had been
# said when the audio is unclear ("Ouvre YouTube, Google Chrome," heard from noise).
VOCABULARY = "Conversation en français avec Spectre, l'assistant personnel."


class WhisperSTT:
    """faster-whisper on CPU (int8)."""

    def __init__(self, model_size: str = "small", language: str = "fr") -> None:
        try:
            import av  # noqa: F401
        except ImportError:
            # Some Windows setups block PyAV's DLLs; it is only needed to decode files,
            # and Spectre passes raw arrays.
            sys.modules["av"] = types.ModuleType("av")
        from faster_whisper import WhisperModel

        self.language = language
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.lock = threading.Lock()  # the PC microphone and the phone may speak at once

    def transcribe(self, pcm: bytes) -> str:
        import numpy as np

        samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype=np.int16)
        audio = samples.astype(np.float32) / 32768.0
        with self.lock:
            return self._transcribe(audio)

    def _transcribe(self, audio: Any) -> str:
        segments, _info = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=5,  # a few tenths of a second more, fewer misheard words
            temperature=0.0,  # no fallback re-decoding: steady latency
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=True,  # drops the noise around the words (TV, fan), a source of inventions
            vad_parameters={"min_silence_duration_ms": 600, "speech_pad_ms": 300},
            initial_prompt=VOCABULARY,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return "" if text.strip(" .") in VOCABULARY else text  # the context echoed back


class PiperTTS:
    """Piper neural voice; falls back to the Windows voice if Piper fails."""

    def __init__(
        self,
        models: Path,
        voice: str = "fr_FR-upmc-medium",
        speaker: str = "pierre",
        effect: str = "futuriste",
        pace: str = "naturel",
    ) -> None:
        from piper import PiperVoice, SynthesisConfig

        from spectre.assistant.voice import fx

        path = ensure_piper_voice(models, voice)
        self.voice = PiperVoice.load(str(path))
        self.effect = effect
        self.on_level: Level | None = None
        speakers = getattr(self.voice.config, "speaker_id_map", None) or {}
        self.syn = SynthesisConfig(
            speaker_id=speakers.get(speaker),
            length_scale=fx.length_scale(effect, pace),  # chosen speed, offsets the deepening
            noise_w_scale=0.7,  # steadier rhythm between syllables: a smoother flow
        )
        self.lock = threading.Lock()

    def render(self, text: str, stop: threading.Event | None = None) -> tuple[bytes, int] | None:
        """The finished voice (with its timbre) as int16 PCM and its rate, without playing it."""
        from spectre.assistant.voice import fx

        sentences: list[bytes] = []
        rate = 22050
        with self.lock:
            for chunk in self.voice.synthesize(text, syn_config=self.syn):
                rate = chunk.sample_rate
                sentences.append(chunk.audio_int16_bytes)
                if stop is not None and stop.is_set():
                    return None
        pcm = fx.join_sentences(sentences, rate)
        return fx.apply(self.effect, pcm, rate), rate

    def speak(self, text: str, stop: threading.Event | None = None) -> None:
        rendered = self.render(text, stop)
        if rendered is not None:
            play_pcm(rendered[0], rendered[1], stop, self.on_level)


class WindowsTTS:
    """The built-in Windows voice through PowerShell (no download)."""

    on_level: Level | None = None  # not measurable here: the orb follows the state only

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


def make_tts(
    models: Path, voice: str, speaker: str = "", effect: str = "futuriste", pace: str = "naturel"
) -> Any:
    try:
        return PiperTTS(models, voice, speaker, effect, pace)
    except Exception:  # noqa: BLE001 - any Piper failure falls back to the system voice
        return WindowsTTS()
