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
        self._echo: queue.Queue[bytes] = queue.Queue(maxsize=50)  # heard while muted: barge-in
        self._stream: Any = None
        self.muted = threading.Event()  # set while Spectre speaks (no self-echo)

    def __enter__(self) -> Microphone:
        import sounddevice as sd

        def callback(indata: Any, _frames: int, _time: Any, _status: Any) -> None:
            block = bytes(indata)
            if self.muted.is_set():  # never the conversation, only the cut-off watch
                with contextlib.suppress(queue.Full):
                    self._echo.put_nowait(block)
                return
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

    def muted_blocks(self, done: threading.Event) -> Iterator[bytes]:
        """What the microphone hears while Spectre speaks, until `done` (barge-in watch)."""
        while not self._echo.empty():  # left over from an earlier sentence
            self._echo.get_nowait()
        while not done.is_set():
            try:
                yield self._echo.get(timeout=0.2)
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


class VoskBarge:
    """Spots a cut-off word (its name) while Spectre speaks. The microphone also hears the
    loudspeakers: measured on this PC (2026-11-09), 45 s of Spectre's own voice never gave
    "spectre" with a one-word grammar, while "stop"/"attends"/"pardon" came up at 0.97-1.0,
    so only the name is used; a voice said over it was recognised at 0.56."""

    def __init__(self, model: Any, words: tuple[str, ...], min_conf: float = 0.5) -> None:
        self.model = model  # shared with the wake word: one model in memory
        self.words = words
        self.min_conf = min_conf
        self.reset()

    def reset(self) -> None:
        import vosk

        self.rec = vosk.KaldiRecognizer(self.model, SAMPLE_RATE, json.dumps([*self.words, "[unk]"]))
        self.rec.SetWords(True)  # per-word confidence, only in final results

    def heard(self, block: bytes) -> str:
        if not self.rec.AcceptWaveform(block):
            return ""
        for item in json.loads(self.rec.Result()).get("result", []):
            if item.get("word") in self.words and float(item.get("conf", 0)) >= self.min_conf:
                return str(item["word"])
        return ""


def _shim_av() -> None:
    """Some Windows setups block PyAV's DLLs; faster-whisper only needs it to decode files,
    and Spectre passes raw arrays."""
    try:
        import av  # noqa: F401
    except ImportError:
        sys.modules["av"] = types.ModuleType("av")


class SileroVAD:
    """Silero VAD (MIT), the copy shipped with faster-whisper: tells speech from noise, block
    by block, where a loudness threshold mistakes a door or a fan for a voice. Streaming:
    512-sample windows with 64 samples of context and the LSTM state carried over."""

    WINDOW = 512
    CONTEXT = 64

    def __init__(self, threshold: float = 0.5) -> None:
        _shim_av()
        import faster_whisper
        import numpy as np
        import onnxruntime

        path = Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self.session = onnxruntime.InferenceSession(
            str(path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.np = np
        self.threshold = threshold
        self.lock = threading.Lock()  # the PC loop and the phone share it
        self.reset()

    def reset(self) -> None:
        np = self.np
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context = np.zeros(self.CONTEXT, dtype=np.float32)
        self.pending = np.zeros(0, dtype=np.float32)

    def prob(self, block: bytes) -> float:
        """Highest speech probability in this block (0-1)."""
        np = self.np
        with self.lock:
            audio = np.frombuffer(block, dtype=np.int16).astype(np.float32) / 32768.0
            self.pending = np.concatenate([self.pending, audio])
            best = 0.0
            while self.pending.size >= self.WINDOW:
                window, self.pending = self.pending[: self.WINDOW], self.pending[self.WINDOW :]
                frame = np.concatenate([self.context, window])[None, :]
                out, self.h, self.c = self.session.run(
                    None, {"input": frame, "h": self.h, "c": self.c}
                )
                self.context = window[-self.CONTEXT :]
                best = max(best, float(np.asarray(out).reshape(-1)[0]))
            return best

    def speech(self, block: bytes) -> bool:
        return self.prob(block) >= self.threshold


SMART_TURN = "smart-turn-v3.2-cpu.onnx"
SMART_TURN_URL = f"https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/{SMART_TURN}"
SMART_TURN_SHA256 = "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f"


def ensure_smart_turn(models: Path) -> Path:
    """Smart Turn v3.2 (Pipecat, BSD-2-Clause, 8 MB), checked against its published hash."""
    import hashlib

    path = models / "smart-turn" / SMART_TURN
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(SMART_TURN_URL, timeout=120) as response:  # noqa: S310 - fixed host
        data = response.read()
    if hashlib.sha256(data).hexdigest() != SMART_TURN_SHA256:
        raise ValueError("Smart Turn : empreinte inattendue, modèle refusé")
    path.write_bytes(data)
    return path


class SmartTurn:
    """Has the speaker finished? Smart Turn v3 listens to the last 8 s (intonation, rhythm,
    words) and answers in ~10-60 ms on a CPU, where a fixed silence either cuts a speaker who
    is thinking or makes everyone wait. Same input as the official `inference.py`: 8 s padded
    at the start, waveform normalised, Whisper log-mel (80 x 800) — checked against
    transformers' WhisperFeatureExtractor (max difference 1e-5)."""

    SECONDS = 8

    def __init__(self, models: Path, threshold: float = 0.5) -> None:
        _shim_av()
        import numpy as np
        import onnxruntime
        from faster_whisper.feature_extractor import FeatureExtractor

        opts = onnxruntime.SessionOptions()
        opts.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.log_severity_level = 4
        self.session = onnxruntime.InferenceSession(
            str(ensure_smart_turn(models)), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.features = FeatureExtractor(chunk_length=self.SECONDS)
        self.np = np
        self.threshold = threshold
        self.lock = threading.Lock()

    def prob(self, pcm: bytes) -> float:
        """Probability that the turn is complete (0-1), from 16 kHz mono int16 PCM."""
        np = self.np
        size = self.SECONDS * SAMPLE_RATE
        audio = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype=np.int16)[-size:].astype(
            np.float32
        )
        audio = np.pad(audio / 32768.0, (size - audio.size, 0))
        audio = (audio - audio.mean()) / np.sqrt(audio.var() + 1e-7)
        mel = self.features(audio, padding=0)[:, : self.SECONDS * 100].astype(np.float32)
        with self.lock:
            out = self.session.run(None, {"input_features": mel[None, :, :]})
        return float(np.asarray(out[0]).reshape(-1)[0])

    def done(self, pcm: bytes) -> bool:
        return self.prob(pcm) >= self.threshold


# Names Whisper tends to mishear in French speech; the prompt biases it towards them.
# A short context for the recogniser. A long list of words gets copied out as if it had been
# said when the audio is unclear ("Ouvre YouTube, Google Chrome," heard from noise).
VOCABULARY = "Conversation en français avec Spectre, l'assistant personnel."


class WhisperSTT:
    """faster-whisper on CPU (int8)."""

    def __init__(self, model_size: str = "small", language: str = "fr") -> None:
        _shim_av()
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
        """Say `text` in flux: the first sentence plays as soon as it is ready (0.2 s measured
        here, against 2.2 s when the whole answer was rendered first) while the next ones are
        synthesised. If Piper breaks before any sound (Windows sometimes blocks its DLL), the
        Windows voice says it instead: Spectre never stays silent."""
        from spectre.assistant.voice import fx

        ready: queue.Queue[bytes | BaseException | None] = queue.Queue()
        gave_up = threading.Event()
        rate = self.voice.config.sample_rate

        def sentences() -> Iterator[bytes]:
            for chunk in self.voice.synthesize(text, syn_config=self.syn):
                if gave_up.is_set() or (stop is not None and stop.is_set()):
                    return
                yield chunk.audio_int16_bytes

        def produce() -> None:
            try:
                with self.lock:
                    for piece in fx.stream(self.effect, sentences(), rate):
                        ready.put(piece)
                ready.put(None)
            except BaseException as err:  # noqa: BLE001 - handed to the speaking thread
                ready.put(err)

        threading.Thread(target=produce, name="spectre-tts", daemon=True).start()
        played = False
        failure: BaseException | None = None

        def pieces() -> Iterator[bytes]:
            nonlocal played, failure
            while True:
                try:
                    piece = ready.get(timeout=0.05)
                except queue.Empty:
                    if stop is not None and stop.is_set():
                        return  # cut off while the next sentence was being made
                    continue
                if isinstance(piece, BaseException):
                    failure = piece
                    return
                if piece is None:
                    return
                played = True
                yield piece

        try:
            play_stream(pieces(), rate, stop, self.on_level)
        finally:
            gave_up.set()
        if failure is not None and not played and not (stop is not None and stop.is_set()):
            print(
                f"Voix Piper en panne ({failure}) : voix de Windows.", file=sys.stderr, flush=True
            )
            WindowsTTS().speak(text, stop)


def play_stream(
    pieces: Iterator[bytes],
    rate: int,
    stop: threading.Event | None = None,
    on_level: Level | None = None,
) -> None:
    """Play int16 mono PCM pieces one after the other through one output stream, without a gap,
    cut at once by `stop`; report the loudness being played to `on_level`."""
    import sounddevice as sd

    step = int(rate * 0.05) * 2  # 50 ms: how fast a cut-off is obeyed
    stream = sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16")
    try:
        stream.start()
        for piece in pieces:
            for start in range(0, len(piece), step):
                if stop is not None and stop.is_set():
                    stream.abort()
                    return
                block = piece[start : start + step]
                if on_level is not None:
                    on_level(rms(block))
                stream.write(block)
        stream.stop()  # lets the last buffer play to its end
    finally:
        stream.close()
        if on_level is not None:
            on_level(0.0)


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
    # Piper loads its phonemizer DLL at the first word only, and Windows (Smart App Control)
    # sometimes blocks it for a moment: say a word in silence now, so a blocked DLL is seen
    # here (and retried) instead of crashing the first greeting.
    error: Exception | None = None
    for attempt in range(3):
        try:
            tts = PiperTTS(models, voice, speaker, effect, pace)
            for _ in tts.voice.synthesize("Prêt.", syn_config=tts.syn):
                pass
            return tts
        except Exception as err:  # noqa: BLE001 - any Piper failure falls back to the system voice
            error = err
            if attempt < 2:
                threading.Event().wait(1.5)
    print(f"Voix Piper indisponible ({error}) : voix de Windows.", file=sys.stderr, flush=True)
    return WindowsTTS()
