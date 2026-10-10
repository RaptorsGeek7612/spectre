"""Greetings: once a day, as suits the hour, never twice the same way."""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from spectre.assistant import greetings
from spectre.assistant.brain import Brain, Reply
from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database
from spectre.assistant.memory import Memory
from tests.test_assistant_brain import FakeCLI

MORNING = datetime(2026, 10, 13, 9, 30).astimezone()  # a Tuesday
EVENING = datetime(2026, 10, 13, 20, 15).astimezone()


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "spectre.db")
    yield database
    database.close()


@pytest.mark.parametrize(
    ("hour", "part"),
    [
        (2, "nuit"),
        (9, "matin"),
        (12, "midi"),
        (15, "après-midi"),
        (19, "soir"),
        (23, "fin de soirée"),
    ],
)
def test_day_part(hour: int, part: str) -> None:
    assert greetings.day_part(MORNING.replace(hour=hour)) == part


def test_moment_in_french() -> None:
    assert greetings.moment(MORNING) == "mardi 09:30, matin"


def test_greeted_once_a_day(db: Database) -> None:
    assert not greetings.greeted_today(db, MORNING)
    assert "Premier contact" in greetings.greeting_rule(db, MORNING)
    greetings.mark_greeted(db, MORNING)
    assert greetings.greeted_today(db, EVENING)  # same day, even after a restart
    assert "déjà salué" in greetings.greeting_rule(db, EVENING)
    assert not greetings.greeted_today(db, MORNING.replace(day=14))  # a new day


def test_recent_lines_kept_and_bounded(db: Database) -> None:
    assert greetings.recent_lines(db) == []
    for i in range(greetings.KEEP + 3):
        greetings.remember_line(db, f"ligne {i}")
    lines = greetings.recent_lines(db)
    assert len(lines) == greetings.KEEP and lines[-1] == f"ligne {greetings.KEEP + 2}"
    db.set_kv(greetings.LINES_KV, "pas du json")
    assert greetings.recent_lines(db) == []
    db.set_kv(greetings.LINES_KV, '{"a": 1}')
    assert greetings.recent_lines(db) == []


def test_is_greeting() -> None:
    assert greetings.is_greeting("Bonjour Olivier !")
    assert greetings.is_greeting("« Salut, ça va ? »")
    assert not greetings.is_greeting("Alors, ce minage ?")
    assert not greetings.is_greeting("")


def test_fill_without_name() -> None:
    assert greetings.fill("Bonjour {name}, bien dormi ?", "") == "Bonjour, bien dormi ?"
    assert greetings.fill("Te revoilà, {name}.", "") == "Te revoilà."
    assert greetings.fill("Bonsoir {name}.", "Olivier") == "Bonsoir Olivier."


def test_pick_avoids_recent_lines() -> None:
    pool = ("Bonjour {name}.", "Salut {name}.")
    rng = random.Random(1)
    assert {greetings.pick(pool, ["Bonjour Olivier."], "Olivier", rng) for _ in range(10)} == {
        "Salut Olivier."
    }
    every = ["Bonjour Olivier.", "Salut Olivier."]
    assert greetings.pick(pool, every, "Olivier", rng) in every  # all said: any of them


def test_fallback_first_then_again(db: Database) -> None:
    rng = random.Random(3)
    first = greetings.fallback(db, EVENING, "Olivier", rng)
    assert first in [greetings.fill(t, "Olivier") for t in greetings.FIRST["soir"]]
    greetings.mark_greeted(db, EVENING)
    again = greetings.fallback(db, EVENING, "Olivier", rng)
    assert not greetings.is_greeting(again)


def test_opening_only_once(db: Database) -> None:
    hello = greetings.opening(db, MORNING, "Olivier", random.Random(2))
    assert greetings.is_greeting(hello) or hello.startswith("Bien le bonjour")
    assert greetings.recent_lines(db) == [hello]
    assert greetings.opening(db, MORNING, "Olivier") == ""


def test_compose_uses_the_model_and_remembers(db: Database, tmp_path: Path) -> None:
    Memory(db).remember("utilisateur", "aime", "le minage")
    cli = FakeCLI(tmp_path, "« Bonsoir Olivier, la soirée commence bien ? »")
    text = greetings.compose(cli, db, EVENING, "Olivier", "il arrive")  # type: ignore[arg-type]
    assert text == "Bonsoir Olivier, la soirée commence bien ?"
    call = cli.calls[0]
    assert call["model"] == "haiku" and call["resume"] is None and not call["tools"]
    assert "mardi 20:15, soir" in call["prompt"] and "le minage" in call["prompt"]
    assert "Premier contact" in call["prompt"] and "(aucune)" in call["prompt"]
    assert greetings.greeted_today(db, EVENING) and greetings.recent_lines(db) == [text]


def test_compose_never_greets_twice(db: Database, tmp_path: Path) -> None:
    greetings.mark_greeted(db, EVENING)
    greetings.remember_line(db, "Bonsoir Olivier.")
    cli = FakeCLI(
        tmp_path, "Bonsoir encore !", Reply("panne", "", True), "x" * 300, "Alors, ce minage ?"
    )
    rng = random.Random(5)
    for _ in range(3):  # a greeting, an error, too long: the varied lists step in
        text = greetings.compose(cli, db, EVENING, "Olivier", "il revient", rng=rng)  # type: ignore[arg-type]
        assert not greetings.is_greeting(text) and len(text) < greetings.MAX_CHARS
    assert "déjà salué" in cli.calls[0]["prompt"] and "- Bonsoir Olivier." in cli.calls[0]["prompt"]
    assert greetings.compose(cli, db, EVENING, "Olivier", "il revient") == "Alors, ce minage ?"  # type: ignore[arg-type]


def test_brain_marks_the_day_greeted(db: Database, tmp_path: Path) -> None:
    cli = FakeCLI(tmp_path, Reply("panne", "", True), "Bonjour !")
    brain = Brain(db, cli, AssistantConfig())  # type: ignore[arg-type]
    now = datetime.now().astimezone()
    assert "Premier contact" in brain.system_prompt()
    brain.ask("Salut")  # an error: no greeting happened
    assert not greetings.greeted_today(db, now)
    brain.ask("Salut")
    assert greetings.greeted_today(db, now)
    system = brain.system_prompt()
    assert "déjà salué" in system and "Varie toujours" in system
