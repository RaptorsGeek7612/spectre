"""Spectre's sense of time: the clock, the previous visit and the missions' state since."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from spectre.assistant import timeline
from spectre.assistant.db import Database

PARIS = timeline.zone("Europe/Paris")
MONDAY = datetime(2026, 11, 2, 14, 0, tzinfo=PARIS)
WEDNESDAY = datetime(2026, 11, 4, 10, 0, tzinfo=PARIS)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "spectre.db")
    yield database
    database.close()


def said(db: Database, at: datetime, channel: str = "text") -> None:
    db.execute(
        "INSERT INTO events(ts, kind, source, text, data) VALUES(?, 'utterance', 'user', 'x', ?)",
        (at.astimezone(UTC).isoformat(timespec="seconds"), f'{{"channel": "{channel}"}}'),
    )


def mission(db: Database, status: str, began: datetime, ended: datetime, error: str = "") -> int:
    return db.execute(
        "INSERT INTO missions(ts, goal, status, error, updated_at) VALUES(?, ?, ?, ?, ?)",
        (
            began.astimezone(UTC).isoformat(timespec="seconds"),
            f"objectif {status}",
            status,
            error,
            ended.astimezone(UTC).isoformat(timespec="seconds"),
        ),
    )


def test_zone_falls_back_to_the_system_zone() -> None:
    assert getattr(timeline.zone("Europe/Paris"), "key", "") == "Europe/Paris"
    assert timeline.zone("Pas/UneZone") is not None
    assert timeline.zone("") is not None
    assert timeline.now("Europe/Paris").tzinfo is not None


def test_spoken_date_and_elapsed() -> None:
    assert timeline.spoken_date(WEDNESDAY) == "mercredi 4 novembre 2026 à 10:00"
    assert timeline.spoken_date(datetime(2026, 11, 1, 9, 5)).startswith("dimanche 1er novembre")
    assert timeline.elapsed(WEDNESDAY - MONDAY) == "1 jour et 20 heures"
    assert timeline.elapsed(timedelta(days=2)) == "2 jours"
    assert timeline.elapsed(timedelta(days=2, minutes=4)) == "2 jours"
    assert timeline.elapsed(timedelta(minutes=5)) == "5 minutes"
    assert timeline.elapsed(timedelta(seconds=20)) == "moins d'une minute"
    assert timeline.elapsed(timedelta(seconds=-5)) == "moins d'une minute"


def test_parse_reads_utc_and_naive_stamps() -> None:
    assert timeline.parse("2026-11-04T09:00:00+00:00", PARIS) == WEDNESDAY
    assert timeline.parse("2026-11-04T09:00:00", PARIS) == WEDNESDAY
    assert timeline.parse("demain", PARIS) is None


def test_visit_finds_the_previous_conversation(db: Database) -> None:
    assert timeline.visit(db, WEDNESDAY) == timeline.Visit(WEDNESDAY, None)
    said(db, MONDAY - timedelta(minutes=10), "voice")
    said(db, MONDAY, "text")  # voice then text: the same conversation
    # a new visit, nothing said yet
    assert timeline.visit(db, WEDNESDAY) == timeline.Visit(WEDNESDAY, MONDAY)
    said(db, WEDNESDAY)
    said(db, WEDNESDAY + timedelta(minutes=20), "image")
    current = timeline.visit(db, WEDNESDAY + timedelta(minutes=25))
    assert current.started == WEDNESDAY and current.previous == MONDAY
    assert current.gap == WEDNESDAY - MONDAY
    # within the first visit only: it has no predecessor
    first = timeline.visit(db, MONDAY + timedelta(minutes=1))
    assert first == timeline.Visit(MONDAY - timedelta(minutes=10), None)


def test_block_tells_the_date_the_gap_and_the_missions(db: Database) -> None:
    said(db, MONDAY)
    said(db, WEDNESDAY)
    mission(db, "done", MONDAY + timedelta(hours=1), MONDAY + timedelta(hours=3))
    mission(db, "failed", MONDAY + timedelta(hours=2), MONDAY + timedelta(hours=2), "quota")
    mission(db, "done", MONDAY - timedelta(days=3), MONDAY - timedelta(days=3))  # seen already
    running = mission(db, "running", MONDAY, MONDAY)
    queued = mission(db, "queued", WEDNESDAY, WEDNESDAY)
    db.log_event("mission_interrupted", "system", "", mission=running)
    db.execute(
        "INSERT INTO routines(name, schedule, prompt, next_run, created_at) VALUES(?, ?, ?, ?, ?)",
        ("point ventes", "lundi 9h", "x", "2026-11-09T08:00:00+00:00", "2026-11-01"),
    )
    text = timeline.block(db, "Europe/Paris", WEDNESDAY + timedelta(minutes=1))
    assert "fuseau Europe/Paris, UTC+01:00" in text
    assert "mercredi 4 novembre 2026 à 10:01" in text
    assert "Ne devine jamais la date" in text
    assert "lundi 2 novembre 2026 à 14:00, soit 1 jour et 20 heures" in text
    assert "terminée, durée 2 heures" in text
    assert "échouée" in text and "erreur : quota" in text
    assert (
        text.count("terminée, durée") == 1
    )  # the mission finished before the last visit is old news
    assert f"#{running} interrompue par un redémarrage" in text
    assert f"#{queued} en file" in text
    assert "routine « point ventes » le lundi 9 novembre 2026 à 09:00" in text


def test_turn_note_gives_the_clock_and_the_return_once(db: Database) -> None:
    said(db, MONDAY)
    said(db, WEDNESDAY)  # the first message of a new visit, just logged
    first = timeline.turn_note(db, "Europe/Paris", WEDNESDAY)
    assert "soit 1 jour et 20 heures" in first and first.endswith("]\n")
    said(db, WEDNESDAY + timedelta(minutes=5))
    later = timeline.turn_note(db, "Europe/Paris", WEDNESDAY + timedelta(minutes=5))
    assert later == "[Horloge : mercredi 4 novembre 2026 à 10:05]\n"


def test_block_without_history(db: Database) -> None:
    text = timeline.block(db, "Europe/Paris", WEDNESDAY)
    assert "Aucune conversation précédente" in text
    assert "État des missions" not in text


def test_restart_marks_running_missions_interrupted(db: Database, tmp_path: Path) -> None:
    from spectre.assistant.missions import MissionEngine
    from tests.test_assistant_brain import FakeCLI

    mid = mission(db, "running", MONDAY, MONDAY)
    MissionEngine(db, FakeCLI(tmp_path), lambda *_: None).recover()  # type: ignore[arg-type]
    rows = db.all("SELECT data FROM events WHERE kind = 'mission_interrupted'")
    assert len(rows) == 1 and str(mid) in rows[0]["data"]
    row = db.one("SELECT status FROM missions WHERE id = ?", (mid,))
    assert row is not None and row["status"] == "queued"
