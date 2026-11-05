"""The programs the user opens, seen by Spectre (windows listed by a fake lister)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import desktop
from spectre.assistant import tools as tools_mod
from spectre.assistant.db import Database
from spectre.assistant.desktop import Desktop, Window
from spectre.assistant.governance import Gate

CODE = Window("code", "timeline.py - Spectre - Visual Studio Code")
CHROME = Window("chrome", "Hermes Agent - Google Chrome")
PRIVATE = Window("msedge", "Banque — InPrivate")
KEEPASS = Window("keepassxc", "coffre.kdbx")
SHELL = Window("explorer", "Program Manager")


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "a.db")
    yield database
    database.close()


def test_clean_drops_private_and_system_windows() -> None:
    long = Window("kdenlive", "x  " * 200)
    kept = desktop.clean([CODE, PRIVATE, KEEPASS, SHELL, Window("", "?"), long])
    assert [w.app for w in kept] == ["code", "kdenlive"]
    assert len(kept[1].title) <= desktop.TITLE_MAX and "  " not in kept[1].title
    assert desktop.private(Window("chrome", "Connexion à mon compte"))
    assert desktop.label("code") == "VS Code" and desktop.label("kdenlive") == "Kdenlive"
    assert desktop._app_of("C:\\Program Files\\Kdenlive\\bin\\kdenlive.EXE") == "kdenlive"


def test_opened_and_closed_programs_are_noted(db: Database) -> None:
    watcher = Desktop(db, lister=lambda: [])
    assert watcher.observe([CODE]) == 0  # the first look is the baseline
    assert watcher.observe([CODE, CHROME, PRIVATE], front=CHROME) == 1
    assert watcher.observe([CHROME], front=PRIVATE) == 1  # private in front: not kept
    history = watcher.history()
    assert history.index("fermé : VS Code") < history.index("ouvert : Chrome — Hermes Agent")
    assert "InPrivate" not in history and "Edge" not in history
    assert "fermé : VS Code" not in watcher.history(search="hermes")
    now = watcher.now([CHROME, CODE, Window("code", "README.md - VS Code")])
    assert "- VS Code : timeline.py" in now and "README.md" in now
    assert "au premier plan : Chrome — Hermes Agent" in now
    assert "Aucun logiciel" in watcher.now([PRIVATE])
    assert watcher.forget() == 2
    assert "Rien de noté" in watcher.history()


def test_desktop_tool_is_spectres(db: Database, tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(desktop, "open_windows", lambda: [CODE])
    ctx = tools_mod.make_context(db, tmp_path / "assistant", [str(tmp_path)])
    out = tools_mod.execute(Gate(db), ctx, "desktop_apps", {})
    assert "VS Code" in out
    out = tools_mod.execute(Gate(db), ctx, "desktop_apps", {"view": "historique"})
    assert "Rien de noté" in out
    tool = tools_mod.TOOLS["desktop_apps"]
    assert tool.allowed("opus") and not tool.allowed("chatgpt")
