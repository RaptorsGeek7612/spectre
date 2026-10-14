"""Meeting mode: local listening, chunked transcription, summary into tasks and decisions."""

from __future__ import annotations

import io
import json
import threading
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import meeting as meeting_module
from spectre.assistant import tools
from spectre.assistant.brain import Reply
from spectre.assistant.company import Companies
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate
from spectre.assistant.meeting import (
    RATE,
    REQUEST_KV,
    MeetingError,
    Meetings,
    Recorder,
    chunks,
    wav_pcm,
)
from spectre.assistant.missions import MissionEngine
from spectre.assistant.service import AssistantService
from tests.test_assistant_engines import Rooted
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone(timedelta(hours=2)))
SECOND = b"\x01\x00" * RATE  # one second of 16 kHz mono int16


def wav(seconds: float, rate: int = RATE, channels: int = 1, width: int = 2) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x01" * width * channels * int(rate * seconds))
    return out.getvalue()


class FakeSTT:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def transcribe(self, pcm: bytes) -> str:
        self.calls.append(len(pcm))
        return "" if len(self.calls) == 2 else f"morceau {len(self.calls)}"


class FakeMic:
    def __init__(self, seconds: int, fail: bool = False) -> None:
        self.seconds, self.fail = seconds, fail

    def __enter__(self) -> FakeMic:
        if self.fail:
            raise OSError("micro débranché")
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def blocks(self, stop: threading.Event) -> Any:
        for _ in range(self.seconds):
            if stop.is_set():
                return
            yield SECOND


SUMMARY = {
    "resume": "On a parlé du lancement.",
    "decisions": ["Lancer la bêta le 1er décembre", " "],
    "taches": [
        {
            "titre": "Préparer la page de prix",
            "departement": "marketing",
            "detail": "Léa, vendredi",
        },
        {"titre": "OK", "departement": "inconnu"},
        "pas une tâche",
        {"titre": " "},
    ],
    "questions_ouvertes": ["Quel prix ?"],
}


def test_wav_and_chunks() -> None:
    assert len(wav_pcm(wav(1.0))) == RATE * 2
    assert len(wav_pcm(wav(1.0, rate=8000, channels=2))) == RATE * 2  # resampled and mixed down
    with pytest.raises(MeetingError, match="WAV attendu"):
        wav_pcm(b"pas un wav")
    with pytest.raises(MeetingError, match="16 bits"):
        wav_pcm(wav(0.1, width=1))
    assert [len(c) for c in chunks(SECOND * 70)] == [RATE * 2 * 30, RATE * 2 * 30, RATE * 2 * 10]


def test_recorder_live(tmp_path: Path) -> None:
    db = Database(tmp_path / "spectre.db")
    company = Companies(db).create("Acme")
    stt, notes = FakeSTT(), []
    recorder = Recorder(Meetings(db), lambda: stt, lambda: FakeMic(65), lambda *a: notes.append(a))
    meeting = recorder.start("Point hebdo", company["id"], background=False)
    done = Meetings(db).get(meeting["id"])
    pad = RATE * 2  # a second of silence after each chunk
    assert stt.calls == [RATE * 2 * 30 + pad, RATE * 2 * 30 + pad, RATE * 2 * 5 + pad]
    assert done["transcript"] == "morceau 1\nmorceau 3" and done["seconds"] == 65
    assert done["status"] == "summarizing" and done["mission_id"]
    plan = json.loads(db.one("SELECT plan FROM missions")["plan"])
    assert plan == {"kind": "meeting", "meeting": meeting["id"], "company": company["id"]}
    assert (
        notes[-1][1] == "Réunion terminée : Point hebdo"
        and notes[-1][2] == "Compte rendu en préparation."
    )
    with pytest.raises(MeetingError, match="aucune réunion"):
        recorder.stop()
    # nothing heard
    silent = Recorder(
        Meetings(db),
        lambda: type("S", (), {"transcribe": lambda s, p: ""})(),
        lambda: FakeMic(3),
        lambda *a: notes.append(a),
    )
    quiet = silent.start("", None, background=False)
    assert (
        Meetings(db).get(quiet["id"])["status"] == "done"
        and notes[-1][2] == "Rien n'a été entendu."
    )
    assert quiet["title"].startswith("Réunion du ")
    # a broken microphone ends the meeting cleanly
    broken = Recorder(
        Meetings(db), lambda: stt, lambda: FakeMic(1, fail=True), lambda *a: notes.append(a)
    )
    broken.start("Panne", None, background=False)
    assert "micro débranché" in notes[-1][2]


def test_recorder_limit_and_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(tmp_path / "spectre.db")
    monkeypatch.setattr(meeting_module, "MAX_HOURS", 1 / 3600)  # one second
    notes: list[Any] = []
    recorder = Recorder(Meetings(db), FakeSTT, lambda: FakeMic(5), lambda *a: notes.append(a))
    recorder.start("Long", None, background=False)
    assert "limite" in notes[-1][2]
    recorder.thread = threading.Thread(target=lambda: None)
    recorder.thread.start()
    recorder.thread.join()
    with pytest.raises(MeetingError, match="aucune réunion"):
        recorder.stop()
    alive = threading.Event()
    recorder.thread = threading.Thread(target=alive.wait)
    recorder.thread.start()
    with pytest.raises(MeetingError, match="déjà en cours"):
        recorder.start("Encore")
    recorder.meeting_id = 1
    recorder.stop_event.clear()
    threading.Timer(0.05, alive.set).start()
    assert recorder.stop() == 1 and recorder.stop_event.is_set()


def test_upload_and_storage(tmp_path: Path) -> None:
    db = Database(tmp_path / "spectre.db")
    meetings = Meetings(db)
    recorder = Recorder(meetings, FakeSTT, lambda: FakeMic(0))
    done = recorder.transcribe_file(wav(40), "Enregistrement", None)
    assert done["source"] == "fichier" and done["status"] == "summarizing" and done["seconds"] == 40
    with pytest.raises(MeetingError, match="200 Mo"):
        recorder.transcribe_file(b"x" * (meeting_module.MAX_UPLOAD + 1), "x", None)
    live = meetings.create("En direct", None, "micro")
    with pytest.raises(MeetingError, match="déjà en cours"):
        meetings.create("Autre", None, "micro")
    with pytest.raises(MeetingError, match="arrête d'abord"):
        meetings.delete(live["id"])
    assert meetings.active()["id"] == live["id"]
    assert [m["title"] for m in meetings.all()] == ["En direct", "Enregistrement"]
    meetings.delete(done["id"])
    with pytest.raises(MeetingError, match="introuvable"):
        meetings.get(done["id"])


def test_summary_files_tasks_and_decisions(tmp_path: Path) -> None:
    db = Database(tmp_path / "spectre.db")
    company = Companies(db).create("Acme")
    meetings = Meetings(db)
    meeting = meetings.create("Lancement", company["id"], "micro")
    meetings.append(meeting["id"], "a" * 40_000, 600)
    calls: list[str] = []

    def ask(prompt: str, system: str) -> Reply:
        calls.append(system[:30])
        if system == meeting_module.PARTIAL:
            return Reply(f"partie de {len(prompt)}", "", False)
        return Reply(json.dumps(SUMMARY, ensure_ascii=False), "", False)

    report = meetings.summarize(meeting["id"], ask, NOW)
    assert len(calls) == 3  # two slices, then the whole
    assert (
        "## Décisions\n- Lancer la bêta le 1er décembre" in report
        and "Durée écoutée : 10 min" in report
    )
    assert "Ajouté à l'entreprise : 2 tâche(s) au tableau, 1 décision(s) au journal." in report
    tasks = Companies(db).tasks(company["id"])
    assert [(t["title"], t["department"]) for t in tasks] == [
        ("Préparer la page de prix", "marketing"),
        ("Tâche : OK", ""),
    ]
    assert "Issue de la réunion « Lancement »" in tasks[0]["detail"]
    decision = db.one("SELECT * FROM decisions")
    assert decision["status"] == "decided" and decision["review_at"].startswith("2026-11-13")
    done = meetings.get(meeting["id"])
    assert done["status"] == "done" and done["summary"] == "On a parlé du lancement."
    assert json.loads(done["result"])["tasks"] == [t["id"] for t in tasks]
    # without a company: only the report
    solo = meetings.create("Perso", None, "fichier")
    meetings.append(solo["id"], "bonjour", 5)
    meetings.append(solo["id"], " ", 5)
    assert "Ajouté à l'entreprise" not in meetings.summarize(solo["id"], ask, NOW)
    for answer, error in [
        (Reply("panne", "", True), "panne"),
        (Reply("[1]", "", False), "illisible"),
    ]:
        with pytest.raises(MeetingError, match=error):
            meetings.summarize(solo["id"], lambda p, s, a=answer: a, NOW)
    long = meetings.create("Longue", None, "fichier")
    meetings.append(long["id"], "b" * 31_000, 1)
    with pytest.raises(MeetingError, match="down"):
        meetings.summarize(long["id"], lambda p, s: Reply("down", "", True), NOW)
    meetings.failed(long["id"], "down")
    assert meetings.get(long["id"])["status"] == "failed"


def test_meeting_mission(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    meetings = Meetings(db)
    meeting = meetings.create("Point", None, "fichier")
    meetings.append(meeting["id"], "on avance", 30)
    mid = meetings.close(meeting["id"])
    cli = Rooted(root, json.dumps(SUMMARY, ensure_ascii=False))
    notes: list[Any] = []
    MissionEngine(db, cli, lambda *a: notes.append(a), lead_model="sonnet").run_next()  # type: ignore[arg-type]
    assert cli.calls[0]["model"] == "sonnet" and notes[-1][1] == f"Compte rendu prêt (#{mid})"
    assert db.one("SELECT role FROM usage_ledger")["role"] == "réunion"
    other = meetings.create("Raté", None, "fichier")
    meetings.append(other["id"], "x", 1)
    mid = meetings.close(other["id"])
    cli.replies = [Reply("panne", "", True)]
    MissionEngine(db, cli, lambda *a: None).run_next()  # type: ignore[arg-type]
    assert meetings.get(other["id"])["status"] == "failed"
    assert db.one("SELECT status FROM missions WHERE id = ?", (mid,))["status"] == "failed"


def test_meeting_tools(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    Companies(db).create("Acme")
    gate, ctx = Gate(db), tools.make_context(db, root, [str(tmp_path)])
    run = lambda tool, **args: tools.execute(gate, ctx, tool, args)  # noqa: E731
    assert run("list_meetings") == "aucune réunion"
    assert run("meeting", action="démarrer", company="acme", title="Point").startswith(
        "réunion demandée"
    )
    assert json.loads(db.get_kv(REQUEST_KV)) == {
        "action": "start",
        "company": "1",
        "title": "Point",
    }
    assert run("meeting", action="stop").startswith("fin de réunion")
    assert run("meeting", action="danser").startswith("ÉCHEC : action")
    assert run("meeting", action="start", company="Nulle").startswith("ÉCHEC : entreprise")
    Meetings(db).create("Réunion test", None, "fichier")
    assert run("list_meetings").startswith("#1 Réunion test [transcribing] 0 min")


def test_service_meetings(
    api: Client,  # noqa: F811
    service: AssistantService,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stt = FakeSTT()
    muted = threading.Event()
    service.voice = type(
        "V", (), {"stt": stt, "stop": threading.Event(), "mic": type("M", (), {"muted": muted})()}
    )()
    assert service._meeting_stt() is stt
    service.recorder.mic = lambda: FakeMic(2)
    monkeypatch.setattr("threading.Thread.start", lambda self: self.run())
    api.json("POST", "/api/assistant/company", {"name": "Acme"})
    status, started = api.json(
        "POST", "/api/assistant/meetings/start", {"title": "Point", "company": "1"}
    )
    assert status == 200 and started["company_id"] == 1
    assert not muted.is_set()  # the meeting ended (fake microphone): the voice is back
    data = api.json("GET", "/api/assistant/meetings")[1]
    assert data["recording"] is False and data["meetings"][0]["status"] == "summarizing"
    assert (
        api.json("GET", f"/api/assistant/meetings/{started['id']}")[1]["transcript"] == "morceau 1"
    )
    status, body = api.json("POST", "/api/assistant/meetings/stop", {})
    assert status == 400 and "aucune réunion" in body["error"]
    status, uploaded = api.json(
        "POST",
        "/api/assistant/meetings/upload?title=Fichier&company=",
        raw=wav(2),
        headers={"Content-Type": "audio/wav"},
    )
    assert status == 200 and uploaded["source"] == "fichier"
    assert api.json("POST", f"/api/assistant/meetings/{uploaded['id']}/delete", {})[1] == {
        "ok": True
    }
    # the brain's tool asks the service through the database
    service.db.set_kv(REQUEST_KV, json.dumps({"action": "start", "title": "Par la voix"}))
    service.poll_changes()
    assert (
        service.db.get_kv(REQUEST_KV) == ""
        and Meetings(service.db).all()[0]["title"] == "Par la voix"
    )
    service.db.set_kv(REQUEST_KV, json.dumps({"action": "start", "company": "Nulle"}))
    service.poll_changes()
    assert (
        service.db.one("SELECT title FROM initiatives ORDER BY id DESC LIMIT 1")["title"]
        == "Réunion impossible"
    )
    service.db.set_kv(REQUEST_KV, json.dumps({"action": "stop"}))
    service.poll_changes()  # not recording: nothing to stop


def test_stt_without_voice(service: AssistantService, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    import builtins

    real_import = builtins.__import__

    def blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "spectre.assistant.voice.engines":
            raise ImportError("no voice")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(MeetingError, match="uv sync --extra voice"):
        service._meeting_stt()
