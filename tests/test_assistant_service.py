"""Tests for the assistant service, its web API, the launcher and the voice loop (no devices)."""

from __future__ import annotations

import array
import base64
import http.client
import io
import json
import runpy
import sys
import threading
import time
import wave
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.assistant import app as app_mod
from spectre.assistant.brain import Reply
from spectre.assistant.config import AssistantConfig
from spectre.assistant.service import AssistantService
from spectre.assistant.voice import loop as loop_mod
from spectre.assistant.voice.listen import SAMPLE_RATE, UtteranceDetector, chime, rms, to_wav
from spectre.assistant.voice.loop import VoiceLoop
from spectre.web import assistant_api
from spectre.web import server as server_mod
from spectre.web.auth import Auth
from spectre.web.store import Store
from tests.test_assistant_brain import FakeCLI
from tests.test_web import Client


class FakeVoice:
    def __init__(self) -> None:
        self.stop = threading.Event()
        self.triggered = 0
        self.said: list[str] = []

    def trigger(self) -> None:
        self.triggered += 1

    def say(self, text: str) -> None:
        self.said.append(text)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


@pytest.fixture
def service(tmp_path: Path, home: Path) -> Iterator[AssistantService]:
    root = tmp_path / "assistant"
    config = AssistantConfig(allowed_roots=[str(home)])
    svc = AssistantService(root, config, cli=FakeCLI(root, *["Réponse."] * 5), fetch=lambda u: {})  # type: ignore[arg-type]
    svc.start(background=False)
    yield svc
    svc.stop()
    svc.db.close()


def _drain(q: Any) -> list[dict[str, Any]]:
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    return events


# ---- service ------------------------------------------------------------------------------


def test_chat_events_and_history(service: AssistantService) -> None:
    q = service.subscribe()
    assert service.chat(" Bonjour ") == "Réponse."
    kinds = [(e["type"], e.get("role") or e.get("state")) for e in _drain(q)]
    assert kinds == [
        ("state", "off"),
        ("message", "user"),
        ("state", "thinking"),
        ("state", "off"),
        ("message", "spectre"),
    ]
    assert service.voice_reply("Et toi ?") == "Réponse."
    assert [h["role"] for h in service.history()] == ["user", "spectre", "user", "spectre"]
    with pytest.raises(ValueError):
        service.chat("  ")
    _drain(q)
    service.unsubscribe(q)
    service.unsubscribe(q)
    service.publish({"type": "x"})
    assert q.empty()


def test_approvals_missions_initiatives(service: AssistantService, home: Path) -> None:
    from spectre.assistant import tools

    q = service.subscribe()
    (home / "a.txt").write_text("a", encoding="utf-8")
    tools.execute(service.gate, service.ctx, "delete_file", {"path": "a.txt"})
    tools.execute(service.gate, service.ctx, "delete_file", {"path": "a.txt"})
    service.poll_changes()
    assert [e["type"] for e in _drain(q)][1:] == ["approval", "approval"]
    assert len(service.approvals()) == 2
    assert "corbeille" in service.approve(1)
    service.deny(2)
    assert service.approvals() == [] and len(service.approvals("denied")) == 1
    assert "mission #1" in service.start_mission("Comparer", "mission")
    assert service.missions_list()[0]["status"] == "queued"
    assert service.status()["missions_running"] == 1
    iid = service.proactive.add_initiative("rappel", "Rappel : pain", "")
    assert service.initiatives()[0]["id"] == iid
    with pytest.raises(ValueError):
        service.resolve_initiative(iid, "peut-être")
    with pytest.raises(KeyError):
        service.resolve_initiative(99, "done")
    service.resolve_initiative(iid, "done")
    assert service.initiatives() == []
    assert len(service.audit()) >= 3


def test_memory_status_config(service: AssistantService) -> None:
    fact = service.memory.remember("Barth", "ville", "Lyon", category="lieu")
    assert service.facts("lyon")[0]["id"] == fact["id"]
    assert service.facts(category="lieu")[0]["value"] == "Lyon"
    assert service.correct(fact["id"], "Lille")["value"] == "Lille"
    assert "Lille" in (service.root / "memoire" / "lieu.md").read_text(encoding="utf-8")
    new_id = service.facts()[0]["id"]
    assert service.forget(new_id)["status"] == "forgotten"
    status = service.status()
    assert status["name"] == "Spectre" and status["facts"] == 0 and not status["voice_available"]
    updated = service.update_config({"auto_max_level": 1, "city": "Brest"})
    assert updated["city"] == "Brest" and service.gate.auto_max_level == 1
    assert AssistantConfig.load(service.root).city == "Brest"


def test_voice_hooks(service: AssistantService) -> None:
    with pytest.raises(ValueError):
        service.push_to_talk()
    voice = FakeVoice()
    service.attach_voice(voice)
    service.push_to_talk()
    assert voice.triggered == 1 and service.status()["voice_available"]
    q = service.subscribe()
    service.set_voice_state("sleeping")
    service.set_voice_state("heard", "bonjour")
    assert service.voice_state == "sleeping"
    service.proactive.add_initiative("briefing", "Briefing", "Beau temps.")
    deadline = time.monotonic() + 2
    while not voice.said and time.monotonic() < deadline:
        time.sleep(0.01)
    assert voice.said == ["Briefing. Beau temps."]
    assert [e["type"] for e in _drain(q)][-1] == "initiative"
    service.stop()
    assert voice.stop.is_set()


# ---- web API ------------------------------------------------------------------------------


@pytest.fixture
def api(
    service: AssistantService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Client]:
    monkeypatch.setattr(assistant_api, "HEARTBEAT_S", 0.05)
    store = Store(tmp_path / "state")
    server = server_mod.make_server(
        "127.0.0.1", 0, store=store, auth=Auth(None, store.root / "secret.key"), assistant=service
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield Client(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()


def test_api_routes(api: Client, service: AssistantService, home: Path) -> None:
    from spectre.assistant import tools

    assert api.json("GET", "/api/status")[1]["assistant"] is True
    assert api.json("GET", "/api/assistant/status")[1]["brain_label"] == "Opus 5.5"
    assert api.json("POST", "/api/assistant/chat", {"text": "Salut"}) == (
        200,
        {"reply": "Réponse."},
    )
    assert api.json("POST", "/api/assistant/chat", {"text": ""})[0] == 400
    assert len(api.json("GET", "/api/assistant/history")[1]) == 2
    assert api.json("POST", "/api/assistant/talk", {})[0] == 400
    service.attach_voice(FakeVoice())
    assert api.json("POST", "/api/assistant/talk", {}) == (200, {"ok": True})
    (home / "b.txt").write_text("b", encoding="utf-8")
    tools.execute(service.gate, service.ctx, "delete_file", {"path": "b.txt"})
    tools.execute(service.gate, service.ctx, "delete_file", {"path": "b.txt"})
    assert len(api.json("GET", "/api/assistant/approvals")[1]) == 2
    assert "corbeille" in api.json("POST", "/api/assistant/approvals/1/approve", {})[1]["result"]
    assert api.json("POST", "/api/assistant/approvals/2/deny", {"reason": "non"})[1] == {"ok": True}
    assert api.json("GET", "/api/assistant/approvals?status=denied")[1][0]["result"] == "non"
    assert api.json("POST", "/api/assistant/approvals/9/approve", {})[0] == 404
    assert "mission #1" in api.json("POST", "/api/assistant/missions", {"goal": "But"})[1]["result"]
    assert api.json("GET", "/api/assistant/missions")[1][0]["goal"] == "But"
    iid = service.proactive.add_initiative("rappel", "R", "")
    assert len(api.json("GET", "/api/assistant/initiatives")[1]) == 1
    assert api.json("POST", f"/api/assistant/initiatives/{iid}", {"status": "dismissed"})[1] == {
        "ok": True
    }
    assert api.json("GET", "/api/assistant/initiatives?status=dismissed")[1][0]["id"] == iid
    fact = service.memory.remember("Barth", "ville", "Lyon", category="lieu")
    assert api.json("GET", "/api/assistant/memory?q=lyon")[1][0]["id"] == fact["id"]
    assert api.json("GET", "/api/assistant/memory?category=lieu")[1][0]["value"] == "Lyon"
    fixed = api.json("POST", f"/api/assistant/memory/{fact['id']}/correct", {"value": "Lille"})[1]
    assert fixed["value"] == "Lille"
    assert (
        api.json("POST", f"/api/assistant/memory/{fixed['id']}/forget", {})[1]["status"]
        == "forgotten"
    )
    assert len(api.json("GET", "/api/assistant/audit")[1]) >= 3
    assert api.json("GET", "/api/assistant/config")[1]["city"] == "Paris"
    assert api.json("POST", "/api/assistant/config", {"city": "Caen"})[1]["city"] == "Caen"
    assert api.json("POST", "/api/assistant/config", {"bogus": 1})[0] == 400
    assert api.json("GET", "/api/assistant/nope")[0] == 404
    status, _, page = api.request("GET", "/assistant.html")
    assert status == 200 and b"assistant.js" in page


def test_api_events_stream(api: Client, service: AssistantService) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
    conn.request("GET", "/api/assistant/events")
    resp = conn.getresponse()
    assert resp.status == 200 and resp.getheader("Content-Type").startswith("text/event-stream")
    first = resp.fp.readline() + resp.fp.readline()
    assert first == b"event: state\n" + b'data: {"type": "state", "state": "off", "detail": ""}\n'
    service.set_voice_state("listening")
    seen = b""
    while b"listening" not in seen:
        seen += resp.fp.readline()
    resp.close()
    conn.close()
    deadline = time.monotonic() + 3
    while service._subscribers and time.monotonic() < deadline:
        time.sleep(0.02)
    assert service._subscribers == []


def test_api_without_assistant(tmp_path: Path) -> None:
    store = Store(tmp_path / "state")
    server = server_mod.make_server("127.0.0.1", 0, store=store, auth=Auth(None, store.root / "k"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = Client(server.server_address[1])
        assert client.json("GET", "/api/status")[1]["assistant"] is False
        assert client.json("GET", "/api/assistant/status")[0] == 404
    finally:
        server.shutdown()
        server.server_close()


# ---- launcher -----------------------------------------------------------------------------


class FakeServer:
    def __init__(self, *a: Any, **kw: Any) -> None:
        self.kw = kw
        self.closed = False

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def server_close(self) -> None:
        self.closed = True


class QuietService(AssistantService):
    def __init__(self, root: Path, config: AssistantConfig) -> None:
        super().__init__(root, config, cli=FakeCLI(root))  # type: ignore[arg-type]

    def start(self, *, background: bool = True) -> None:
        super().start(background=False)


@pytest.fixture
def launcher(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.setenv("SPECTRE_ASSISTANT_DIR", str(tmp_path / "unused"))  # restored after
    opened: list[str] = []
    servers: list[FakeServer] = []

    def make(*a: Any, **kw: Any) -> FakeServer:
        servers.append(FakeServer(*a, **kw))
        return servers[-1]

    monkeypatch.setattr(app_mod.shutil, "which", lambda name: "claude")
    monkeypatch.setattr(app_mod, "AssistantService", QuietService)
    monkeypatch.setattr(server_mod, "make_server", make)
    monkeypatch.setattr(app_mod.webbrowser, "open", opened.append)
    monkeypatch.setattr("spectre.web.store.default_state_dir", lambda: tmp_path / "state")
    return {"opened": opened, "servers": servers}


def test_main_runs_and_stops(
    launcher: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert app_mod.main(["--dir", str(tmp_path / "a"), "--port", "9999"]) == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:9999/assistant.html" in out and "Arrêt de Spectre" in out
    assert launcher["opened"] == ["http://127.0.0.1:9999/assistant.html"]
    assert launcher["servers"][0].closed and launcher["servers"][0].kw["assistant"] is not None
    assert (tmp_path / "a" / "config.json").exists()


def test_main_errors(
    launcher: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = ["--dir", str(tmp_path / "a")]
    assert app_mod.main([*root, "--host", "0.0.0.0"]) == 2
    assert app_mod.main([*root, "--allow-host", "pc.tailnet.ts.net"]) == 2  # needs a password

    def refuse(*a: Any, **kw: Any) -> Any:
        raise OSError("port pris")

    monkeypatch.setattr(server_mod, "make_server", refuse)
    assert app_mod.main([*root, "--no-browser"]) == 1
    monkeypatch.setattr(app_mod.shutil, "which", lambda name: None)
    assert app_mod.main(root) == 1


def test_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["spectre-assistant", "--version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("spectre.assistant", run_name="__main__")
    assert exc.value.code == 0


# ---- voice --------------------------------------------------------------------------------

LOUD = array.array("h", [6000] * 1600).tobytes()
QUIET = bytes(3200)
WAKE = array.array("h", [1] * 1600).tobytes()


class FakeMic:
    def __init__(self, blocks: list[bytes]) -> None:
        self.muted = threading.Event()
        self._blocks = blocks
        self.flushed = 0

    def blocks(self, stop: threading.Event) -> Iterator[bytes]:
        yield from self._blocks

    def flush(self) -> None:
        self.flushed += 1


class FakeWake:
    def heard(self, block: bytes) -> bool:
        return block == WAKE


class FakeSTT:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)

    def transcribe(self, pcm: bytes) -> str:
        assert pcm
        return self.texts.pop(0)


class FakeTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak(self, text: str, stop: threading.Event | None = None) -> None:
        self.spoken.append(text)


def _utterance() -> list[bytes]:
    return [LOUD] * 5 + [QUIET] * 10


def _loop(
    blocks: list[bytes], stt: FakeSTT, reply: Any = None, ack: str = ""
) -> tuple[VoiceLoop, FakeTTS, list[str]]:
    states: list[str] = []
    tts = FakeTTS()
    plays: list[int] = []
    voice = VoiceLoop(
        FakeMic(blocks),
        FakeWake(),
        stt,
        tts,
        reply or (lambda text: f"Tu as dit {text}."),
        lambda state, detail: states.append(state),
        play=lambda pcm, rate: plays.append(rate),
        follow_up_s=0.5,
        ack=ack,
    )
    return voice, tts, states


def test_voice_conversation_with_follow_up() -> None:
    blocks = [QUIET, WAKE, *_utterance(), *_utterance(), *[QUIET] * 8, QUIET]
    voice, tts, states = _loop(blocks, FakeSTT("quelle heure", "merci"))
    voice.run()
    assert tts.spoken == ["Tu as dit quelle heure.", "Tu as dit merci."]
    assert states == [
        "sleeping",
        "listening",
        "thinking",
        "heard",
        "speaking",
        "listening",
        "thinking",
        "heard",
        "speaking",
        "listening",
        "sleeping",
        "off",
    ]
    assert voice.mic.flushed == 2  # type: ignore[attr-defined]
    assert not voice.mic.muted.is_set()


def test_voice_stop_word_empty_and_trigger() -> None:
    voice, tts, _ = _loop([WAKE, *_utterance()], FakeSTT("Stop."))
    voice.run()
    assert tts.spoken == ["D'accord."]
    voice, tts, states = _loop([QUIET, *_utterance()], FakeSTT("  "))
    voice.trigger()
    voice.run()
    assert tts.spoken == [] and "thinking" in states
    voice, tts, states = _loop([WAKE], FakeSTT())
    voice.stop.set()
    voice.run()
    assert states == ["sleeping", "off"]


def test_voice_ack_error_and_say(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loop_mod, "ACK_AFTER_S", 0.01)

    def slow(text: str) -> str:
        time.sleep(0.2)
        raise RuntimeError("panne")

    voice, tts, _ = _loop(
        [WAKE, *_utterance()], FakeSTT("fais un truc"), reply=slow, ack="Je m'en occupe."
    )
    voice.run()
    assert tts.spoken == ["Je m'en occupe.", "Désolé, une erreur est survenue : panne"]
    quiet, quiet_tts, _ = _loop([WAKE, *_utterance()], FakeSTT("encore"), reply=slow)
    quiet.run()
    assert quiet_tts.spoken == ["Désolé, une erreur est survenue : panne"]  # no filler by default
    voice.say("Rappel : pain")
    assert tts.spoken[-1] == "Rappel : pain"


def test_listen_helpers() -> None:
    assert rms(b"") == 0.0 and rms(b"\x01") == 0.0
    assert round(rms(LOUD)) == 6000
    detector = UtteranceDetector(max_s=0.3)
    assert [detector.feed(LOUD) for _ in range(3)] == [False, False, True]
    assert detector.heard_speech and len(detector.audio()) == 3 * len(LOUD)
    waiting = UtteranceDetector(wait_s=0.2)
    assert [waiting.feed(QUIET) for _ in range(2)] == [False, True]
    assert not waiting.heard_speech
    assert len(chime()) == int(SAMPLE_RATE * 0.12) * 2
    assert json.dumps(Reply("a", "b", False).text) == '"a"'


def test_pick_input_avoids_stereo_mix() -> None:
    from spectre.assistant.voice.listen import pick_input

    devices = [
        {"name": "Mappeur de sons Microsoft - Input", "max_input_channels": 2},
        {"name": "Mixage stéréo (Realtek(R) Audio", "max_input_channels": 2},
        {"name": "Haut-parleurs (Realtek)", "max_input_channels": 0},
        {"name": "Microphone Array (AMD Audio Dev", "max_input_channels": 2},
        {"name": "Casque USB", "max_input_channels": 1},
    ]
    assert pick_input(devices, default=1) == 3
    assert pick_input(devices, default=3) is None
    assert pick_input(devices, default=4) is None
    assert pick_input(devices, default=1, wanted="casque") == 4
    with pytest.raises(ValueError):
        pick_input(devices, default=1, wanted="inexistant")
    assert pick_input(devices[:3], default=1) is None


def test_level_events_are_throttled(
    service: AssistantService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spectre.assistant import service as service_mod

    clock = iter([10.0, 10.01, 10.2, 10.21])
    monkeypatch.setattr(service_mod.time, "monotonic", lambda: next(clock))
    q = service.subscribe()
    service.set_level(6000)  # published (full scale)
    service.set_level(3000)  # dropped: too soon
    service.set_level(1500)  # published
    service.set_level(0)  # silence is always published
    levels = [e["v"] for e in _drain(q) if e["type"] == "level"]
    assert levels == [1.0, round(0.25**0.6, 3), 0.0]


def test_main_allow_host_behind_a_relay(
    launcher: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SPECTRE_WEBUI_PASSWORD", "secret")
    args = ["--dir", str(tmp_path / "a"), "--allow-host", "pc.tailnet.ts.net", "--no-browser"]
    assert app_mod.main(args) == 0
    server = launcher["servers"][0]
    assert server.kw["extra_hosts"] == ["pc.tailnet.ts.net"] and server.kw["auth"].enabled


# ---- voice from the phone -----------------------------------------------------------------


class PhoneVoice(FakeVoice):
    """A voice stack whose recognition and synthesis are fakes."""

    def __init__(self, heard: str = "Quelle heure est-il ?", render: bool = True) -> None:
        super().__init__()
        self.stt = SimpleNamespace(transcribe=lambda pcm: heard)
        self.tts = SimpleNamespace(render=lambda text: (b"\x01\x00" * 100, 22050))
        if not render:
            self.tts = SimpleNamespace()  # the Windows fallback voice cannot render


def test_remote_voice(service: AssistantService) -> None:
    pcm = b"\x00\x10" * SAMPLE_RATE  # one second
    with pytest.raises(ValueError, match="voix"):
        service.remote_voice(pcm)
    service.attach_voice(PhoneVoice())
    empty = {"heard": "", "reply": "", "audio": ""}
    assert service.remote_voice(b"\x00" * 100) == empty  # too short
    out = service.remote_voice(pcm)
    assert out["heard"] == "Quelle heure est-il ?" and out["reply"] == "Réponse."
    wav = base64.b64decode(out["audio"])
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    assert service.history()[-2]["text"] == "Quelle heure est-il ?"
    service.attach_voice(PhoneVoice(heard="  "))
    assert service.remote_voice(pcm) == empty
    service.attach_voice(PhoneVoice(render=False))
    out = service.remote_voice(pcm)
    assert out["reply"] == "Réponse." and out["audio"] == ""


def test_api_voice_route(api: Client, service: AssistantService) -> None:
    pcm = b"\x00\x10" * SAMPLE_RATE
    headers = {"Content-Type": "application/octet-stream"}
    status, _, body = api.request("POST", "/api/assistant/voice", raw=pcm, headers=headers)
    assert status == 400 and "voix" in json.loads(body)["error"]
    service.attach_voice(PhoneVoice())
    status, _, body = api.request("POST", "/api/assistant/voice", raw=pcm, headers=headers)
    assert status == 200 and json.loads(body)["heard"] == "Quelle heure est-il ?"
    status, _, _ = api.request("POST", "/api/assistant/voice", raw=b"", headers=headers)
    assert status == 200
    big = {**headers, "Content-Length": str(server_mod.MAX_BODY + 2)}  # announced, not sent
    assert api.request("POST", "/api/assistant/voice", raw=b"x", headers=big)[0] == 413


def test_to_wav() -> None:
    wav = to_wav(b"\x01\x00\x02\x00\x03", 16000)  # the odd byte is dropped
    with wave.open(io.BytesIO(wav)) as reader:
        assert reader.getframerate() == 16000 and reader.getnframes() == 2
