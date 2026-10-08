"""Tests for the assistant's core: config, database, memory, governance, actions, tools, MCP."""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import actions, mcp_server, tools, winapi
from spectre.assistant.actions import ActionContext, ActionError
from spectre.assistant.config import DIR_ENV, AssistantConfig, assistant_dir
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate, Level
from spectre.assistant.memory import CATEGORIES, Memory


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "assistant" / "spectre.db")
    yield database
    database.close()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


@pytest.fixture
def launched() -> list[str]:
    return []


@pytest.fixture
def ctx(db: Database, tmp_path: Path, home: Path, launched: list[str]) -> ActionContext:
    return ActionContext(
        db=db, root=tmp_path / "assistant", allowed_roots=[home], launcher=launched.append
    )


# ---- config -------------------------------------------------------------------------------


def test_assistant_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert assistant_dir() == Path.home() / ".spectre" / "assistant"
    monkeypatch.setenv(DIR_ENV, str(tmp_path))
    assert assistant_dir() == tmp_path


def test_config_roundtrip_and_bad_files(tmp_path: Path) -> None:
    assert AssistantConfig.load(tmp_path).name == "Spectre"
    cfg = AssistantConfig(user_name="Barth", city="Lyon")
    cfg.save(tmp_path / "a")
    assert AssistantConfig.load(tmp_path / "a").city == "Lyon"
    (tmp_path / "config.json").write_text("{not json", encoding="utf-8")
    assert AssistantConfig.load(tmp_path).city == "Paris"
    (tmp_path / "config.json").write_text("[1, 2]", encoding="utf-8")
    assert AssistantConfig.load(tmp_path).city == "Paris"
    (tmp_path / "config.json").write_text('{"city": "Nice", "unknown": 1}', encoding="utf-8")
    assert AssistantConfig.load(tmp_path).city == "Nice"


def test_config_update_validates() -> None:
    cfg = AssistantConfig()
    cfg.update({"city": "Brest", "brain_timeout_s": 60, "speak_initiatives": False})
    assert (cfg.city, cfg.brain_timeout_s, cfg.speak_initiatives) == ("Brest", 60.0, False)
    for bad in (
        {"nope": 1},
        {"briefing_hour": "8"},
        {"auto_max_level": True},
        {"speak_initiatives": 1},
    ):
        with pytest.raises(ValueError):
            cfg.update(bad)


# ---- database -----------------------------------------------------------------------------


def test_database_helpers(db: Database) -> None:
    assert db.get_kv("k", "d") == "d"
    db.set_kv("k", "1")
    db.set_kv("k", "2")
    assert db.get_kv("k") == "2"
    event = db.log_event("utterance", "user", "salut", channel="voice")
    row = db.one("SELECT * FROM events WHERE id = ?", (event,))
    assert row and json.loads(row["data"]) == {"channel": "voice"}
    assert db.one("SELECT * FROM events WHERE id = -1") is None
    with pytest.raises(RuntimeError), db.tx() as conn:
        conn.execute("INSERT INTO kv(key, value) VALUES('x', 'y')")
        raise RuntimeError
    assert db.get_kv("x") == ""


# ---- memory -------------------------------------------------------------------------------


def test_memory_reinforce_supersede_multi(db: Database) -> None:
    mem = Memory(db)
    first = mem.remember("Barth", "plat préféré", "pâtes au pesto", category="preference")
    assert first["outcome"] == "created"
    again = mem.remember("barth", "Plat  préféré", "Pâtes au pesto")
    assert again["outcome"] == "reinforced" and again["observations"] == 2
    assert again["confidence"] > first["confidence"]
    new = mem.remember("Barth", "plat préféré", "risotto", category="preference")
    assert new["outcome"] == "superseded"
    assert mem.get(first["id"])["status"] == "superseded"
    mem.remember("Barth", "aime", "le vélo")
    assert mem.remember("Barth", "aime", "le jazz")["outcome"] == "created"
    assert len([f for f in mem.list() if f["predicate"] == "aime"]) == 2
    assert mem.remember("x", "y", "z", category="bizarre", confidence=5)["category"] == "autre"
    with pytest.raises(ValueError):
        mem.remember(" ", "y", "z")
    with pytest.raises(KeyError):
        mem.get(999)


def test_memory_recall_forget_correct(db: Database) -> None:
    mem = Memory(db)
    fact = mem.remember("Barth", "plat préféré", "pâtes au pesto", category="preference")
    mem.remember("Barth", "ville", "Lyon", category="lieu")
    assert [f["id"] for f in mem.recall("PATES")] == [fact["id"]]
    assert len(mem.recall("?")) == 2
    assert mem.list(category="lieu")[0]["value"] == "Lyon"
    assert mem.forget(fact["id"])["status"] == "forgotten"
    assert mem.recall("pates") == []
    lyon = mem.list(category="lieu")[0]
    fixed = mem.correct(lyon["id"], "Lille")
    assert fixed["value"] == "Lille" and fixed["confidence"] == 1.0
    assert mem.get(lyon["id"])["status"] == "superseded"
    events = db.all("SELECT * FROM events WHERE kind = 'human_correction'")
    assert len(events) == 2


def test_memory_context_and_mirror(db: Database, tmp_path: Path) -> None:
    mem = Memory(db)
    assert "ne sait encore rien" in mem.context_block()
    mem.remember("Barth", "ville", "Lyon", category="lieu")
    mem.remember("Spectre", "ton", "tutoiement", category="persona")
    assert mem.context_block().startswith("- [persona]")
    folder = tmp_path / "memoire"
    (folder).mkdir()
    (folder / "projet.md").write_text("old", encoding="utf-8")
    written = mem.mirror(folder)
    assert {p.name for p in written} == {"lieu.md", "persona.md"}
    assert not (folder / "projet.md").exists()
    assert "Lyon" in (folder / "lieu.md").read_text(encoding="utf-8")
    assert "persona" in CATEGORIES


# ---- governance ---------------------------------------------------------------------------


def test_gate_axes(db: Database) -> None:
    gate = Gate(db)
    assert gate.decide(Level.READ, "read").verdict == "auto"
    assert gate.decide(Level.WRITE, "write_file").verdict == "auto"
    assert gate.decide(Level.DESTRUCTIVE, "delete_file").verdict == "approval"
    assert gate.decide(Level.READ, "install").verdict == "refused"
    assert gate.decide(Level.EXTERNAL, "read").verdict == "approval"
    assert "catégorie" in gate.decide(Level.READ, "inconnue").reason
    bold = Gate(db, auto_max_level=5)
    assert "catégorie" in bold.decide(Level.DESTRUCTIVE, "delete_file").reason
    assert bold.decide(Level.CRITICAL, "read").verdict == "approval"


def test_gate_budgets(db: Database) -> None:
    gate = Gate(db, per_minute=2)
    gate.record("a", {}, Level.READ, "read", "auto", "ok")
    assert gate.decide(Level.READ, "read").verdict == "auto"
    gate.record("b", {"x": 1}, Level.READ, "read", "auto", "ok")
    assert "budget" in gate.decide(Level.READ, "read").reason
    daily = Gate(db, per_day=2)
    assert daily.decide(Level.READ, "read").verdict == "refused"
    assert len(db.all("SELECT * FROM audit")) == 2


# ---- actions ------------------------------------------------------------------------------


def test_resolve_path(ctx: ActionContext, home: Path, tmp_path: Path) -> None:
    assert actions.resolve_path(ctx, "notes.txt") == (home / "notes.txt").resolve()
    for bad in ("", str(tmp_path / "elsewhere.txt")):
        with pytest.raises(ActionError):
            actions.resolve_path(ctx, bad)
    inner = ActionContext(db=ctx.db, root=home / ".spectre", allowed_roots=[home])
    with pytest.raises(ActionError, match="internes"):
        actions.resolve_path(inner, str(home / ".spectre" / "spectre.db"))
    bare = ActionContext(db=ctx.db, root=tmp_path / "r")
    with pytest.raises(ActionError):
        actions.resolve_path(bare, "x.txt")


def test_read_actions(ctx: ActionContext, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert actions.current_time(ctx)
    assert "Système" in actions.system_info(ctx)
    assert actions.list_dir(ctx, str(home)).endswith("(vide)")
    (home / "docs").mkdir()
    (home / "docs" / "Rapport.md").write_text("abcdef", encoding="utf-8")
    (home / ".cache").mkdir()
    (home / ".cache" / "rapport-cache.md").write_text("x", encoding="utf-8")
    listing = actions.list_dir(ctx, str(home))
    assert "[dossier]  docs" in listing
    with pytest.raises(ActionError):
        actions.list_dir(ctx, str(home / "docs" / "Rapport.md"))
    assert actions.read_file(ctx, "docs/Rapport.md") == "abcdef"
    monkeypatch.setattr(actions, "MAX_READ_CHARS", 3)
    assert actions.read_file(ctx, "docs/Rapport.md").startswith("abc\n…")
    with pytest.raises(ActionError):
        actions.read_file(ctx, "absent.md")
    assert actions.search_files(ctx, str(home), "rapport").endswith("Rapport.md")
    assert actions.search_files(ctx, str(home), "*.pdf") == "aucun fichier trouvé"
    with pytest.raises(ActionError):
        actions.search_files(ctx, "docs/Rapport.md", "x")
    (home / "docs" / "rapport2.md").write_text("y", encoding="utf-8")
    monkeypatch.setattr(actions, "MAX_LIST", 1)
    assert "limite atteinte" in actions.search_files(ctx, str(home), "")


def test_open_actions(
    ctx: ActionContext, launched: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ActionError):
        actions.open_url(ctx, "file:///etc/passwd")
    assert "youtube" in actions.open_url(ctx, " https://youtube.com ", screen=None)
    entries = [Path("Programs/Notepad.lnk"), Path("Programs/Uninstall Notepad++.lnk")]
    monkeypatch.setattr(actions, "_start_menu_entries", lambda: entries)
    assert actions.open_app(ctx, "notepad") == "application lancée : Notepad"
    assert actions.open_app(ctx, "inconnu") == "application lancée : inconnu"
    assert launched == ["https://youtube.com", str(entries[0]), "inconnu"]
    with pytest.raises(ActionError):
        actions.open_app(ctx, "  ")


def test_find_app_and_start_menu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entries = [Path(p) for p in ("Code.lnk", "Visual Studio Code.lnk", "Codex Helper.url")]
    assert actions.find_app("code", entries) == entries[0]
    assert actions.find_app("visual", entries) == entries[1]
    assert actions.find_app("helper", entries) == entries[2]
    assert actions.find_app("zzz", entries) is None
    programs = tmp_path / "Microsoft/Windows/Start Menu/Programs"
    programs.mkdir(parents=True)
    (programs / "App.lnk").write_text("", encoding="utf-8")
    (programs / "readme.txt").write_text("", encoding="utf-8")
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "none"))
    assert actions._start_menu_entries() == [programs / "App.lnk"]


def test_list_screens(ctx: ActionContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(winapi, "monitors", lambda: [])
    assert "un seul écran" in actions.list_screens(ctx)
    screens = [
        winapi.Monitor(1, 0, 0, 1920, 1080, True),
        winapi.Monitor(2, 1920, 0, 2560, 1440, False),
    ]
    monkeypatch.setattr(winapi, "monitors", lambda: screens)
    assert actions.list_screens(ctx).splitlines()[0] == "écran 1 (principal) : 1920×1080 à x=0"


def test_write_move_delete_undo(ctx: ActionContext, home: Path) -> None:
    assert actions.undo_last(ctx) == "rien à annuler"
    actions.write_file(ctx, "a/new.txt", "v1")
    actions.write_file(ctx, "a/new.txt", "v2")
    assert (home / "a/new.txt").read_text(encoding="utf-8") == "v2"
    assert "ancienne version" in actions.undo_last(ctx)
    assert (home / "a/new.txt").read_text(encoding="utf-8") == "v1"
    (home / "b").mkdir()
    actions.move_file(ctx, "a/new.txt", "b")
    assert (home / "b/new.txt").exists()
    with pytest.raises(ActionError):
        actions.move_file(ctx, "a/new.txt", "c.txt")
    (home / "c.txt").write_text("c", encoding="utf-8")
    with pytest.raises(ActionError):
        actions.move_file(ctx, "c.txt", "b/new.txt")
    actions.delete_file(ctx, "c.txt")
    assert not (home / "c.txt").exists()
    with pytest.raises(ActionError):
        actions.delete_file(ctx, "c.txt")
    out = actions.undo_last(ctx, count=3)
    assert "restauré" in out and "remis en place" in out and "fichier créé supprimé" in out
    assert (home / "c.txt").exists() and (home / "a/new.txt").exists() is False


def test_reminders(ctx: ActionContext) -> None:
    assert actions.list_reminders(ctx) == "aucun rappel en attente"
    with pytest.raises(ActionError):
        actions.set_reminder(ctx, "demain", "x")
    with pytest.raises(ActionError):
        actions.set_reminder(ctx, "2026-10-09T08:30", " ")
    assert "rappel #1" in actions.set_reminder(ctx, "2026-10-09T08:30", "pain")
    actions.set_reminder(ctx, "2026-10-09T07:00+00:00", "café")
    assert actions.list_reminders(ctx).count("#") == 2


# ---- tools --------------------------------------------------------------------------------


def test_execute_auto_and_failures(db: Database, ctx: ActionContext) -> None:
    gate = Gate(db)
    assert tools.execute(gate, ctx, "nope", {}) == "outil inconnu : nope"
    assert tools.execute(gate, ctx, "current_time", {})
    assert tools.execute(gate, ctx, "read_file", {"path": "absent"}).startswith("ÉCHEC")
    assert "paramètres invalides" in tools.execute(gate, ctx, "read_file", {"oops": 1})
    assert "rien en mémoire" in tools.execute(gate, ctx, "recall", {"query": "vélo"})
    saved = tools.execute(
        gate, ctx, "remember", {"subject": "Barth", "predicate": "aime", "value": "le vélo"}
    )
    assert "mémorisé (#1, created)" in saved
    assert "#1 [autre]" in tools.execute(gate, ctx, "recall", {"query": "vélo"})
    assert "oublié" in tools.execute(gate, ctx, "forget", {"fact_id": 1})
    assert "paramètres invalides" in tools.execute(gate, ctx, "forget", {"fact_id": 99})
    assert tools.execute(gate, ctx, "list_missions", {}) == "aucune mission"
    assert "ÉCHEC" in tools.execute(gate, ctx, "start_mission", {"goal": " "})
    assert "mission #1" in tools.execute(gate, ctx, "start_mission", {"goal": "x", "kind": "?"})
    assert "#1 [queued] x" in tools.execute(gate, ctx, "list_missions", {})
    assert json.loads(db.one("SELECT plan FROM missions")["plan"]) == {"kind": "mission"}  # type: ignore[index]

    def broken(_ctx: ActionContext) -> str:
        raise OSError("disque")

    boom = tools.Tool("boom", "", Level.READ, "read", broken)
    assert tools._run(gate, ctx, boom, {}, Level.READ, "read", "auto") == "ÉCHEC : disque"
    assert db.one("SELECT COUNT(*) AS n FROM events WHERE kind = 'action'")["n"] >= 10  # type: ignore[index]


def test_execute_refused(db: Database, ctx: ActionContext) -> None:
    gate = Gate(db, policies={"read": "NEVER"})
    assert tools.execute(gate, ctx, "current_time", {}).startswith("REFUSÉ")
    assert db.one("SELECT decision FROM audit")["decision"] == "refused"  # type: ignore[index]


def test_approval_flow(db: Database, ctx: ActionContext, home: Path) -> None:
    gate = Gate(db)
    (home / "x.txt").write_text("old", encoding="utf-8")
    out = tools.execute(gate, ctx, "write_file", {"path": "x.txt", "content": "new"})
    assert out.startswith("EN ATTENTE DE VALIDATION (#1)")
    assert (home / "x.txt").read_text(encoding="utf-8") == "old"
    assert tools.TOOLS["write_file"].risk(ctx, {"path": "/outside"}) == (Level.WRITE, "write_file")
    assert "fichier écrit" in tools.run_approved(gate, ctx, 1)
    assert (home / "x.txt").read_text(encoding="utf-8") == "new"
    assert db.one("SELECT status FROM approvals WHERE id = 1")["status"] == "executed"  # type: ignore[index]
    with pytest.raises(ValueError):
        tools.run_approved(gate, ctx, 1)
    with pytest.raises(ValueError):
        tools.deny(ctx, 1)
    for call in (lambda: tools.run_approved(gate, ctx, 9), lambda: tools.deny(ctx, 9)):
        with pytest.raises(KeyError):
            call()
    tools.execute(gate, ctx, "delete_file", {"path": "absent.txt"})
    assert tools.run_approved(gate, ctx, 2).startswith("ÉCHEC")
    assert db.one("SELECT status FROM approvals WHERE id = 2")["status"] == "failed"  # type: ignore[index]
    tools.execute(gate, ctx, "delete_file", {"path": "x.txt"})
    tools.deny(ctx, 3, "")
    row = db.one("SELECT * FROM approvals WHERE id = 3")
    assert row and row["status"] == "denied" and row["result"] == "refusé par l'utilisateur"


def test_make_context(db: Database, tmp_path: Path) -> None:
    ctx = tools.make_context(db, tmp_path, ["~"])
    assert ctx.allowed_roots == [Path.home()] and ctx.trash == tmp_path / "trash"


# ---- MCP server ---------------------------------------------------------------------------


def test_tool_wrapper_signature() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    wrapper = mcp_server.tool_wrapper(
        tools.TOOLS["write_file"], lambda n, a: calls.append((n, a)) or "ok"
    )
    assert list(inspect.signature(wrapper).parameters) == ["path", "content"]
    assert "ctx" not in wrapper.__annotations__
    assert wrapper(path="a", content="b") == "ok"
    assert calls == [("write_file", {"path": "a", "content": "b"})]


def test_build_server_lists_every_tool() -> None:
    server = mcp_server.build_server(lambda n, a: "ok")
    listed = server.list_tools()
    if inspect.isawaitable(listed):
        listed = asyncio.run(listed)
    by_name = {t.name: t for t in listed}
    assert set(by_name) == set(tools.TOOLS)
    assert by_name["set_reminder"].input_schema["required"] == ["when", "text"]
    assert sys.executable  # the brain launches this server with the same interpreter
