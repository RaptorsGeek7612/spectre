"""Tests for the assistant's brain (claude -p), missions and proactive initiatives (no network)."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from spectre.assistant import brain as brain_mod
from spectre.assistant.brain import (
    Brain,
    ClaudeCLI,
    Reply,
    extract_json,
    one_shot,
    parse_reply,
    tools_list,
)
from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database
from spectre.assistant.memory import Memory
from spectre.assistant.missions import ClaudeCodeChat, MissionEngine
from spectre.assistant.proactive import Proactive, weather_summary
from spectre.errors import SpectreError


class FakeCLI:
    """Stands in for ClaudeCLI: answers from a list (strings or Replies) and records calls."""

    def __init__(self, root: Path, *replies: str | Reply) -> None:
        self.workspace = root / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def ask(
        self,
        prompt: str,
        *,
        system: str,
        model: str | None = None,
        resume: str | None = None,
        with_tools: bool = True,
    ) -> Reply:
        self.calls.append(
            {
                "prompt": prompt,
                "system": system,
                "model": model,
                "resume": resume,
                "tools": with_tools,
            }
        )
        reply = self.replies.pop(0) if self.replies else "ok"
        return reply if isinstance(reply, Reply) else Reply(reply, "s1", False)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "spectre.db")
    yield database
    database.close()


def _json_line(**data: Any) -> str:
    return json.dumps({"type": "result", **data})


# ---- ClaudeCLI ----------------------------------------------------------------------------


def test_cli_command_env_and_mcp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    monkeypatch.setenv("SPECTRE_TEST_VAR", "kept")
    seen: dict[str, Any] = {}

    def runner(cmd: list[str], **kw: Any) -> Any:
        seen.update(cmd=cmd, **kw)
        return SimpleNamespace(
            stdout="log\n" + _json_line(result=" Salut ", session_id="abc"), stderr=""
        )

    cli = ClaudeCLI(AssistantConfig(brain_model="haiku"), tmp_path, runner=runner)
    reply = cli.ask("bonjour", system="SYS", resume="old")
    assert reply == Reply("Salut", "abc", False, None)
    cmd = seen["cmd"]
    assert cmd[:2] == ["claude", "-p"] and cmd[cmd.index("--model") + 1] == "claude-haiku-4-5"
    assert cmd[-2:] == ["--resume", "old"] and "--strict-mcp-config" in cmd
    assert "mcp__spectre__*" in cmd
    assert seen["input"] == "bonjour" and seen["cwd"] == tmp_path / "workspace"
    assert "ANTHROPIC_API_KEY" not in seen["env"] and seen["env"]["SPECTRE_TEST_VAR"] == "kept"
    server = json.loads((tmp_path / "mcp.json").read_text(encoding="utf-8"))["mcpServers"][
        "spectre"
    ]
    assert server["command"] == sys.executable
    assert server["env"] == {"SPECTRE_ASSISTANT_DIR": str(tmp_path)}
    bare = cli.command(system="S", model="opus", resume=None, with_tools=False)
    assert bare[-2:] == ["--tools", ""]


def test_cli_missing_binary_and_timeout(tmp_path: Path) -> None:
    def missing(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError

    def slow(*_a: Any, **_k: Any) -> Any:
        raise subprocess.TimeoutExpired("claude", 1)

    for runner, words in ((missing, "Claude Code"), (slow, "à temps")):
        reply = ClaudeCLI(AssistantConfig(), tmp_path, runner=runner).ask("x", system="s")
        assert reply.is_error and words in reply.text


def test_parse_reply() -> None:
    out = _json_line(result="ok", session_id="s", is_error=True, total_cost_usd=0.01)
    assert parse_reply("{bad\n" + out + "\n\n") == Reply("ok", "s", True, 0.01)
    assert parse_reply('{"other": 1}', "erreur 1\nerreur finale").text.endswith("erreur finale")
    assert parse_reply("", "").text == "Le cerveau a échoué : réponse vide"


def test_extract_json_and_helpers(tmp_path: Path) -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json("Voici : [1, 2] fin") == [1, 2]
    assert extract_json("{oops} puis [3]") == [3]
    assert extract_json('```{"b": 2}```') == {"b": 2}
    with pytest.raises(ValueError):
        extract_json("rien")
    assert tools_list(["a", "b"]) == "a, b"
    cli = FakeCLI(tmp_path, "r")
    assert one_shot(cli, "p", "s", model="haiku").text == "r"  # type: ignore[arg-type]
    assert cli.calls[0] == {
        "prompt": "p",
        "system": "s",
        "model": "haiku",
        "resume": None,
        "tools": False,
    }


# ---- Brain --------------------------------------------------------------------------------


def test_brain_sessions_and_prompt(db: Database, tmp_path: Path) -> None:
    cli = FakeCLI(tmp_path, "Il est midi.", Reply("vieux", "", True), "Nouveau départ.")
    brain = Brain(db, cli, AssistantConfig(user_name="Barth", city="Lyon"))  # type: ignore[arg-type]
    assert brain.ask("  ").is_error
    assert brain.ask("Quelle heure ?").text == "Il est midi."
    assert cli.calls[0]["resume"] is None
    Memory(db).remember("Barth", "aime", "le vélo")
    db.execute(
        "INSERT INTO approvals(ts, tool, args, level, category, reason) "
        "VALUES('t', 'delete_file', '{}', 3, 'c', 'r')"
    )
    db.execute("INSERT INTO reminders(ts, due_at, text) VALUES('t', '2026-10-09T08:00', 'pain')")
    assert brain.ask("Et maintenant ?", channel="text").text == "Nouveau départ."
    assert [c["resume"] for c in cli.calls[1:]] == ["s1", None]
    system = cli.calls[-1]["system"]
    assert "Barth" in system and "Lyon" in system and "le vélo" in system
    assert "#1 delete_file" in system and "pain" in system and "Canal : texte" in system
    replies = db.all("SELECT * FROM events WHERE kind = 'reply'")
    assert [r["text"] for r in replies] == ["Il est midi.", "Nouveau départ."]
    db.set_kv("brain_session", "2000-01-01|ancien")
    assert brain._session() == ""
    brain.reset()
    assert db.get_kv("brain_session") == ""


# ---- missions -----------------------------------------------------------------------------


def _engine(db: Database, cli: FakeCLI) -> tuple[MissionEngine, list[tuple[str, str, str]]]:
    notes: list[tuple[str, str, str]] = []
    engine = MissionEngine(db, cli, lambda *a: notes.append(a), model="haiku")  # type: ignore[arg-type]
    return engine, notes


def _queue(db: Database, goal: str, plan: dict[str, Any], status: str = "queued") -> int:
    return db.execute(
        "INSERT INTO missions(ts, goal, status, plan, updated_at) VALUES('t', ?, ?, ?, 't')",
        (goal, status, json.dumps(plan)),
    )


def test_claude_code_chat(tmp_path: Path) -> None:
    cli = FakeCLI(tmp_path, "réponse", Reply("panne", "", True))
    chat = ClaudeCodeChat(cli=cli, model="haiku")
    out = chat.invoke([SystemMessage("règles"), HumanMessage("question")])
    assert out.content == "réponse" and cli.calls[0]["system"] == "règles"
    with pytest.raises(SpectreError, match="panne"):
        chat.invoke([HumanMessage("q")])


def test_mission_plan_steps_verify_retry_report(db: Database, tmp_path: Path) -> None:
    cli = FakeCLI(
        tmp_path,
        '{"steps": ["chercher", "écrire"]}',
        "trouvé 3 vélos",
        '{"ok": true, "note": "bien"}',
        "rien fait",
        "illisible",
        "toujours rien",
        '{"ok": false, "note": "pas de fichier"}',
        "# Rapport",
    )
    engine, notes = _engine(db, cli)
    assert engine.run_next() is False
    mid = _queue(db, "Comparer des vélos", {"kind": "mission"})
    assert engine.run_next() is True
    row = db.one("SELECT * FROM missions WHERE id = ?", (mid,))
    assert row and row["status"] == "done" and row["report"] == "# Rapport"
    steps = json.loads(row["steps"])
    assert [s["ok"] for s in steps] == [True, False] and steps[1]["note"] == "pas de fichier"
    assert json.loads(row["plan"])["steps"] == ["chercher", "écrire"]
    assert "Tentative précédente insuffisante : vérification illisible" in cli.calls[5]["prompt"]
    assert cli.calls[1]["tools"] is True and cli.calls[2]["model"] == "haiku"
    assert cli.calls[0]["model"] == "opus" and cli.calls[-1]["model"] == "opus"  # Spectre leads
    assert cli.calls[1]["model"] == "haiku"  # execution agents (model set by _engine)
    assert (cli.workspace / "missions" / f"mission-{mid:04d}.md").read_text(
        encoding="utf-8"
    ) == "# Rapport"
    assert notes[0][1] == f"Mission terminée (#{mid})" and "1 étape(s) à revoir" in notes[0][2]


def test_mission_resumes_existing_plan(db: Database, tmp_path: Path) -> None:
    cli = FakeCLI(tmp_path, "fait", '{"ok": true}', "rapport")
    engine, notes = _engine(db, cli)
    _queue(db, "But", {"kind": "mission", "steps": ["unique"]})
    engine.run_next()
    assert len(cli.calls) == 3 and "Toutes les étapes" in notes[0][2]


def test_mission_failure_and_stop(db: Database, tmp_path: Path) -> None:
    engine, notes = _engine(db, FakeCLI(tmp_path, '{"steps": []}'))
    mid = _queue(db, "Vide", {})
    engine.run_next()
    row = db.one("SELECT * FROM missions WHERE id = ?", (mid,))
    assert row and row["status"] == "failed" and "plan" in row["error"]
    assert "échouée" in notes[0][1]
    stopped, _ = _engine(db, FakeCLI(tmp_path))
    stopped.stop()
    sid = _queue(db, "Stop", {"steps": ["a"]})
    stopped.run_next()
    assert db.one("SELECT status FROM missions WHERE id = ?", (sid,))["status"] == "running"  # type: ignore[index]


def test_mission_redaction(db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(goal: str, models: dict[str, Any]) -> Any:
        seen.update(goal=goal, models={k: m.model for k, m in models.items()})
        return SimpleNamespace(final_text="Texte final")

    monkeypatch.setattr("spectre.graph.run", fake_run)
    engine, notes = _engine(db, FakeCLI(tmp_path))
    mid = _queue(db, "Une lettre", {"kind": "redaction"})
    engine.run_next()
    assert seen["models"] == {"scout": "haiku", "scribe": "sonnet", "warden": "opus"}
    assert (
        db.one("SELECT report FROM missions WHERE id = ?", (mid,))["report"]
        == "# Une lettre\n\nTexte final\n"
    )  # type: ignore[index]
    assert notes[0][1].startswith("Texte prêt")


def test_mission_engine_start_requeues(db: Database, tmp_path: Path) -> None:
    engine, _ = _engine(db, FakeCLI(tmp_path))
    engine._loop = lambda: None  # type: ignore[method-assign]
    mid = _queue(db, "Interrompue", {}, status="running")
    engine.start()
    assert db.one("SELECT status FROM missions WHERE id = ?", (mid,))["status"] == "queued"  # type: ignore[index]


# ---- proactive ----------------------------------------------------------------------------


def _fetch(found: bool = True) -> Callable[[str], Any]:
    def fetch(url: str) -> Any:
        if "geocoding" in url:
            return (
                {"results": [{"name": "Lyon", "latitude": 45.7, "longitude": 4.8}]} if found else {}
            )
        return {
            "daily": {
                "weather_code": [61],
                "temperature_2m_min": [7.4],
                "temperature_2m_max": [15.6],
                "precipitation_probability_max": [80],
            }
        }

    return fetch


def test_weather_summary() -> None:
    assert (
        weather_summary("Lyon", _fetch()) == "Lyon : pluie faible, 7 à 16 °C, risque de pluie 80 %"
    )
    assert "introuvable" in weather_summary("Nulle-part", _fetch(found=False))


def _proactive(
    db: Database, tmp_path: Path, now: datetime, cli: FakeCLI | None = None, **kw: Any
) -> tuple[Proactive, list[tuple[str, str, str]]]:
    notes: list[tuple[str, str, str]] = []
    pro = Proactive(
        db,
        cli or FakeCLI(tmp_path),  # type: ignore[arg-type]
        AssistantConfig(user_name="Barth", city="Lyon"),
        lambda *a: notes.append(a),
        fetch=kw.get("fetch", _fetch()),
        clock=lambda: now,
        rand=kw.get("rand", lambda: 1.0),  # never befriends unless a test asks for it
    )
    return pro, notes


def test_tick_briefing_once_and_reminders(db: Database, tmp_path: Path) -> None:
    now = datetime(2026, 10, 8, 9, 0).astimezone()
    db.execute(
        "INSERT INTO reminders(ts, due_at, text) VALUES('t', ?, 'pain')",
        ((now - timedelta(minutes=5)).isoformat(),),
    )
    db.execute("INSERT INTO reminders(ts, due_at, text) VALUES('t', '2026-10-08T18:00', 'sport')")
    db.execute(
        "INSERT INTO approvals(ts, tool, args, level, category, reason) "
        "VALUES('t', 'x', '{}', 3, 'c', 'r')"
    )
    db.execute(
        "INSERT INTO missions(ts, goal, status, updated_at) VALUES('t', 'g', 'running', 't')"
    )
    pro, notes = _proactive(db, tmp_path, now)
    pro.tick()
    pro.tick()
    assert [n[0] for n in notes] == ["rappel", "briefing"]
    assert notes[0][1] == "Rappel : pain"
    text = notes[1][2]
    assert text.startswith("Bonjour Barth. Météo — Lyon : pluie faible")
    assert "18:00 sport" in text and "1 action(s)" in text and "1 mission(s)" in text
    assert len(db.all("SELECT * FROM initiatives")) == 2


def test_briefing_without_weather(db: Database, tmp_path: Path) -> None:
    def broken(url: str) -> Any:
        raise OSError("hors ligne")

    pro, _ = _proactive(db, tmp_path, datetime(2026, 10, 8, 9).astimezone(), fetch=broken)
    pro.config.user_name = ""
    assert pro.briefing(pro.clock()) == "Bonjour. Météo indisponible ce matin."


def test_consolidation(db: Database, tmp_path: Path) -> None:
    now = datetime.now().astimezone().replace(hour=3, minute=0)
    facts = {
        "facts": [
            {"subject": "Barth", "predicate": "aime", "value": "le jazz", "category": "preference"},
            {"subject": "Barth", "value": "incomplet"},
        ]
    }
    cli = FakeCLI(tmp_path, json.dumps(facts), "pas du json")
    pro, notes = _proactive(db, tmp_path, now, cli)
    assert pro.consolidate(now) == 0
    db.log_event("utterance", "user", "j'adore le jazz")
    Memory(db).remember("Barth", "ville", "Lyon")
    db.execute("UPDATE facts SET last_seen_at = '2000-01-01T00:00:00+00:00'")
    pro.tick()
    assert Memory(db).recall("jazz")[0]["value"] == "le jazz"
    assert cli.calls[0]["model"] == "haiku" and "j'adore le jazz" in cli.calls[0]["prompt"]
    assert notes[-1][1] == "Rapport de la nuit" and "1 fait(s)" in notes[-1][2]
    assert "1 souvenir(s)" in notes[-1][2]
    assert pro.consolidate(now) == 0  # unreadable answer


def test_brain_module_constants() -> None:
    assert "ANTHROPIC_API_KEY" in brain_mod.STRIPPED_ENV
    assert "ni Jarvis" in brain_mod.CORE.format(name="Spectre", user="Barth", language_name="fr")


def test_usage_limit_is_explained_in_french(db: Database, tmp_path: Path) -> None:
    from spectre.assistant.brain import explain_limit, usage_limit

    notice = "You've hit your session limit · resets 8pm (Europe/Paris)"
    assert usage_limit(notice) and not usage_limit("Il est midi.")
    assert explain_limit(notice).endswith("se réinitialise à 20 h.")
    assert explain_limit("Usage limit reached, resets at 12:30am").endswith("à 0 h 30.")
    assert explain_limit("Usage limit reached, resets 9am").endswith("à 9 h.")
    assert explain_limit("rate limit").endswith("Réessaie un peu plus tard.")
    cli = FakeCLI(tmp_path, Reply(notice, "s1", False))
    db.set_kv("brain_session", f"{datetime.now():%Y-%m-%d}|old")
    reply = Brain(db, cli, AssistantConfig()).ask("Merci")  # type: ignore[arg-type]
    assert reply.is_error and reply.text.startswith("J'ai atteint la limite")
    assert len(cli.calls) == 1  # no pointless retry


def test_superior_agent_runs_on_opus_5_5(tmp_path: Path) -> None:
    from spectre.config import ASSISTANT_MODELS, model_label

    assert AssistantConfig().brain_model == "opus" and ASSISTANT_MODELS["opus"] == "claude-opus-5-5"
    cli = ClaudeCLI(AssistantConfig(), tmp_path, runner=lambda *a, **k: None)
    cmd = cli.command(system="s", model="opus", resume=None, with_tools=False)
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-5"
    custom = cli.command(system="s", model="claude-opus-4-8", resume=None, with_tools=False)
    assert custom[custom.index("--model") + 1] == "claude-opus-4-8"  # exact IDs pass through
    assert model_label("opus") == "Opus 5.5" and model_label("haiku") == "Haiku 4.5"
    assert model_label("claude-opus-4-8") == "Opus 4.8" and model_label("bizarre") == "bizarre"
    assert "agent supérieur" in brain_mod.CORE
