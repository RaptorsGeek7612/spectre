"""Spectre coming to talk to the user on its own, to get to know them better."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from spectre.assistant import proactive
from spectre.assistant.brain import Brain, Reply
from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database
from spectre.assistant.memory import Memory
from spectre.assistant.proactive import Proactive, parse_hours
from spectre.assistant.service import AssistantService
from tests.test_assistant_brain import FakeCLI
from tests.test_assistant_service import FakeVoice, _drain, home, service  # noqa: F401

NOW = datetime(2026, 10, 10, 15, 0, tzinfo=UTC)
OPENER = json.dumps({"text": "Tu joues d'un instrument ?", "topic": "musique"})


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "spectre.db")
    yield database
    database.close()


def _pro(
    db: Database,
    tmp_path: Path,
    *replies: str,
    now: datetime = NOW,
    free: bool = True,
    chance: float = 0.0,
    **config: object,
) -> tuple[Proactive, FakeCLI, list[tuple[str, str, str]]]:
    cli = FakeCLI(tmp_path, *replies)
    notes: list[tuple[str, str, str]] = []
    cfg = AssistantConfig(user_name="Olivier", briefing_hour=0, consolidation_hour=25)
    cfg.update(dict(config))
    pro = Proactive(
        db,
        cli,  # type: ignore[arg-type]
        cfg,
        lambda *a: notes.append(a),
        fetch=lambda url: {"results": []},
        clock=lambda: now,
        rand=lambda: chance,
        is_free=lambda: free,
    )
    db.set_kv("last_briefing", now.strftime("%Y-%m-%d"))
    return pro, cli, notes


def test_parse_hours() -> None:
    assert parse_hours("8-22") == (8, 22)
    assert parse_hours("bof") == parse_hours("22-8") == parse_hours("3-30") == (10, 21)


def test_comes_over_and_remembers_what_it_asked(db: Database, tmp_path: Path) -> None:
    Memory(db).remember("Olivier", "aime", "le vélo", category="preference")
    pro, cli, notes = _pro(db, tmp_path, OPENER)
    pro.tick()
    assert notes == [("lien", "Spectre vient te parler", "Tu joues d'un instrument ?")]
    call = cli.calls[0]
    assert call["model"] == "opus" and call["system"] == proactive.BEFRIEND
    assert "le vélo" in call["prompt"] and "Olivier" in call["prompt"]
    assert "preference" not in call["prompt"].split("connais le moins : ")[1].split("\n")[0]
    row = db.one("SELECT data FROM initiatives WHERE kind = 'lien'")
    assert row and json.loads(row["data"]) == {"topic": "musique"}
    said = db.one("SELECT source, text FROM events WHERE kind = 'reply'")
    assert said and said["text"] == "Tu joues d'un instrument ?"
    # the answer reaches the brain with what Spectre had said
    brain_cli = FakeCLI(tmp_path, Reply("Super !", "s1", False))
    Brain(db, brain_cli, pro.config).ask("Oui, de la guitare")  # type: ignore[arg-type]
    prompt = brain_cli.calls[0]["prompt"]
    assert prompt.startswith("[Tu étais venu vers l'utilisateur en lui disant : « Tu joues")
    assert prompt.endswith("Oui, de la guitare")
    Brain(db, brain_cli, pro.config).ask("Et toi ?")  # type: ignore[arg-type]
    assert brain_cli.calls[1]["prompt"] == "Et toi ?"  # read once


@pytest.mark.parametrize(
    ("setting", "kw"),
    [
        ({"befriend_per_day": 0}, {}),
        ({}, {"free": False}),  # in a conversation
        ({}, {"chance": 0.5}),  # not this time
        ({}, {"now": NOW.replace(hour=8)}),  # too early
        ({}, {"now": NOW.replace(hour=21)}),  # too late
        ({"befriend_hours": "16-18"}, {}),
    ],
)
def test_stays_quiet(db: Database, tmp_path: Path, setting: dict, kw: dict) -> None:  # type: ignore[type-arg]
    pro, cli, notes = _pro(db, tmp_path, OPENER, **kw, **setting)
    pro.tick()
    assert notes == [] and cli.calls == []


def test_spacing_daily_count_and_ignored(db: Database, tmp_path: Path) -> None:
    pro, _, notes = _pro(db, tmp_path, OPENER)
    assert pro.befriend_due(NOW) is True
    pro.befriend(NOW)
    stamp = (NOW - timedelta(hours=2)).isoformat()
    db.execute("UPDATE initiatives SET ts = ?", (stamp,))
    db.execute("UPDATE events SET ts = ?", (stamp,))
    assert pro.befriend_due(NOW) is False  # 2 h < 3 h
    db.execute("UPDATE initiatives SET ts = ?", ((NOW - timedelta(hours=4)).isoformat(),))
    db.execute("UPDATE events SET ts = ?", ((NOW - timedelta(hours=4)).isoformat(),))
    assert pro.befriend_due(NOW) is False  # unanswered: 6 h
    db.log_event("utterance", "user", "désolé, j'étais occupé")
    db.execute("UPDATE events SET ts = ?", ((NOW - timedelta(hours=3, minutes=30)).isoformat(),))
    assert pro.befriend_due(NOW) is True  # answered: 3 h are enough
    db.log_event("utterance", "user", "je te parle")
    db.execute(
        "UPDATE events SET ts = ? WHERE text = 'je te parle'",
        ((NOW - timedelta(minutes=5)).isoformat(),),
    )
    assert pro.befriend_due(NOW) is False  # just talked: leave them be
    db.execute("DELETE FROM events WHERE text = 'je te parle'")
    pro.config.befriend_per_day = 1
    db.execute("UPDATE initiatives SET ts = ?", ((NOW - timedelta(hours=4)).isoformat(),))
    assert pro.befriend_due(NOW) is False  # once a day is done


def test_bad_or_failed_answer(db: Database, tmp_path: Path) -> None:
    pro, _, notes = _pro(db, tmp_path, "pas du json", json.dumps({"text": " "}))
    assert pro.befriend(NOW) == ""
    assert pro.befriend(NOW) == ""
    pro, _, notes = _pro(db, tmp_path, Reply(OPENER, "", True))  # type: ignore[arg-type]
    assert pro.befriend(NOW) == "" and notes == []
    assert db.get_kv("befriend_opener") == ""


def test_old_or_broken_opener(db: Database, tmp_path: Path) -> None:
    brain = Brain(db, FakeCLI(tmp_path), AssistantConfig())  # type: ignore[arg-type]
    db.set_kv("befriend_opener", f"{time.time() - 7200}|Vieille question")
    assert brain.take_opener() == ""
    db.set_kv("befriend_opener", "pas-un-nombre|x")
    assert brain.take_opener() == ""
    assert brain.take_opener() == ""


def test_service_speaks_then_listens(service: AssistantService) -> None:  # noqa: F811
    voice = FakeVoice()
    service.attach_voice(voice)
    q = service.subscribe()
    service.set_voice_state("sleeping")
    assert service._free() is True
    service.proactive.add_initiative("lien", "Spectre vient te parler", "Ça va, Olivier ?")
    deadline = time.monotonic() + 2
    while not voice.triggered and time.monotonic() < deadline:
        time.sleep(0.01)
    assert voice.said == ["Ça va, Olivier ?"] and voice.triggered == 1
    events = _drain(q)
    assert {
        "type": "message",
        "role": "spectre",
        "text": "Ça va, Olivier ?",
        "channel": "voice",
    } in (events)
    service.set_voice_state("listening")
    assert service._free() is False
    service.stop()
