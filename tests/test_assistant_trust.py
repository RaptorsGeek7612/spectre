"""Earned autonomy (agent records, trust levels, the gate) and the AI cost ledger."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import actions, runctx, spend, tools
from spectre.assistant.brain import Brain, Reply, parse_reply
from spectre.assistant.codex import mcp_env
from spectre.assistant.company import Companies
from spectre.assistant.config import AssistantConfig
from spectre.assistant.custom_agents import CustomAgents
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate, Level
from spectre.assistant.learning import mark_mission
from spectre.assistant.missions import MissionEngine
from spectre.assistant.saas import Saas
from spectre.assistant.service import AssistantService
from spectre.assistant.trust import Trust, label
from tests.test_assistant_agents import _queue, _steps
from tests.test_assistant_engines import Rooted
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone(timedelta(hours=2)))


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "assistant" / "spectre.db")
    yield database
    database.close()


def test_runctx() -> None:
    assert runctx.current() == {} and runctx.env() == {}
    with runctx.scope(mission=3, company=None) as outer:
        assert outer == {"mission": 3}
        with runctx.scope(agent="agent:2", role="x"):
            assert runctx.env() == {"SPECTRE_AGENT": "agent:2", "SPECTRE_MISSION": "3"}
        assert runctx.current() == {"mission": 3}
    seen: list[dict[str, Any]] = []
    with runctx.scope(agent="sonnet"):
        thread = threading.Thread(target=lambda: seen.append(runctx.current()))
        thread.start()
        thread.join()
    assert seen == [{}]  # another thread: its own context


# ---- the record and the levels -------------------------------------------------------------------


def test_levels(db: Database) -> None:
    trust = Trust(db)
    trust.record("", "step_ok")  # no agent: nothing
    trust.record("sonnet", "nonsense")
    assert trust.dossier("sonnet")["level"] == "apprenti" and trust.agents() == []
    for _ in range(14):
        trust.record("sonnet", "step_ok")
    assert trust.level("sonnet") == "apprenti"  # 14 points: not enough yet
    trust.record("sonnet", "step_ok")
    assert trust.level("sonnet") == "confirmé"
    for _ in range(13):
        trust.record("sonnet", "task_validated")
    dossier = trust.dossier("sonnet")
    assert (
        dossier["level"] == "expert" and dossier["volume"] == 41 and dossier["reliability"] == 97.7
    )
    trust.record("sonnet", "rollback", 4)  # a recent rollback: no longer expert
    assert trust.level("sonnet") == "confirmé"
    later = datetime.now().astimezone() + timedelta(days=31)
    assert trust.dossier("sonnet", later)["level"] == "confirmé"  # a rollback weighs 5 points
    for _ in range(40):
        trust.record("sonnet", "step_ok")
    assert trust.dossier("sonnet", later)["level"] == "expert"  # trust earned back, window clean
    for _ in range(20):
        trust.record("sonnet", "approval_denied")
    assert trust.level("sonnet") == "apprenti"  # too many refusals: back to apprentice
    assert trust.level("") == ""
    nova = CustomAgents(db).create("Nova", "haiku", "Finance")
    assert label(f"agent:{nova['id']}", db) == "Nova" and label("agent:99", db) == "agent supprimé"
    assert label("chatgpt") == "Kyra"


def test_changes_are_announced(db: Database) -> None:
    trust = Trust(db)
    notes: list[Any] = []
    for _ in range(15):
        trust.record("haiku", "step_ok")
    assert trust.changes(lambda *a: notes.append(a)) == [("haiku", "apprenti", "confirmé")]
    assert notes[-1][1] == "Kaïto promu : confirmé" and "gagne en autonomie" in notes[-1][2]
    assert trust.changes(lambda *a: notes.append(a)) == []
    for _ in range(6):
        trust.record("haiku", "step_fail")
    trust.changes(lambda *a: notes.append(a))
    assert notes[-1][1] == "Kaïto rétrogradé : apprenti"


# ---- the gate ------------------------------------------------------------------------------------


def test_gate_trust() -> None:
    gate = Gate.__new__(Gate)
    gate.policies = {
        "delete_file": "ASK",
        "overwrite_file": "ASK",
        "external_send": "ASK",
        "install": "NEVER",
    }
    gate.auto_max_level = 2
    gate._budget_ok = lambda: True  # type: ignore[method-assign]
    assert gate.decide(Level.DESTRUCTIVE, "delete_file").verdict == "approval"
    assert gate.decide(Level.DESTRUCTIVE, "delete_file", "confirmé").verdict == "approval"
    expert = gate.decide(Level.DESTRUCTIVE, "delete_file", "expert")
    assert expert.verdict == "auto" and "autonomie méritée" in expert.reason
    assert gate.decide(Level.EXTERNAL, "external_send", "expert").verdict == "approval"
    assert gate.decide(Level.CRITICAL, "overwrite_file", "expert").verdict == "approval"
    assert gate.decide(Level.WRITE, "install", "expert").verdict == "refused"


def test_agent_actions_and_approvals(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    gate, ctx = Gate(db), tools.make_context(db, root, [str(tmp_path)])
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    ctx.agent = "sonnet"
    first = tools.execute(gate, ctx, "delete_file", {"path": str(tmp_path / "a.txt")})
    assert first.startswith("EN ATTENTE DE VALIDATION (#1)")
    assert db.one("SELECT agent FROM approval_agents WHERE approval_id = 1")["agent"] == "sonnet"
    tools.run_approved(gate, ctx, 1)
    tools.execute(gate, ctx, "delete_file", {"path": str(tmp_path / "b.txt")})
    tools.deny(ctx, 2)
    counts = Trust(db).dossier("sonnet")["counts"]
    assert counts == {"approval_granted": 1, "approval_denied": 1}
    for _ in range(40):
        Trust(db).record("sonnet", "task_validated")
    result = tools.execute(gate, ctx, "delete_file", {"path": str(tmp_path / "c.txt")})
    assert not (tmp_path / "c.txt").exists() and not result.startswith("EN ATTENTE")
    ctx.agent = ""  # Spectre itself: the usual rules
    (tmp_path / "d.txt").write_text("x", encoding="utf-8")
    assert tools.execute(gate, ctx, "delete_file", {"path": str(tmp_path / "d.txt")}).startswith(
        "EN ATTENTE"
    )
    assert db.one("SELECT COUNT(*) AS n FROM approval_agents")["n"] == 2


def test_agent_reaches_the_tool_server(tmp_path: Path) -> None:
    from spectre.assistant.brain import ClaudeCLI
    from spectre.assistant.llm import gate_caller

    root = tmp_path / "assistant"
    cli = ClaudeCLI(AssistantConfig(), root)
    assert cli.write_mcp_config() == root / "mcp.json"
    with runctx.scope(agent="agent:3", mission=9):
        path = cli.write_mcp_config()
        assert path.name.startswith("mcp-") and path != root / "mcp.json"
        env = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["spectre"]["env"]
        assert env["SPECTRE_AGENT"] == "agent:3" and env["SPECTRE_MISSION"] == "9"
        assert 'SPECTRE_AGENT = "agent:3"' in mcp_env(root)
        call = gate_caller(root, AssistantConfig(allowed_roots=[str(tmp_path)]))
        (tmp_path / "x.txt").write_text("x", encoding="utf-8")
        call("delete_file", {"path": str(tmp_path / "x.txt")})
    assert (
        Database(root / "spectre.db").one("SELECT agent FROM approval_agents")["agent"] == "agent:3"
    )


# ---- what feeds the record -----------------------------------------------------------------------


def test_missions_feed_record_and_ledger(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    companies = Companies(db)
    companies.create("Acme")
    task = companies.add_task("acme", "Étude", department="finance")
    mid = companies.start(task["id"])
    cli = Rooted(
        root,
        '{"steps": ["chercher"]}',
        Reply("trouvé", "", False, 0.02, 120),
        '{"ok": true}',
        "rapport",
    )
    engine = MissionEngine(db, cli, lambda *a: None, model="sonnet")  # type: ignore[arg-type]
    engine.run_next()
    step = _steps(db, mid)[0]
    assert step["key"] == "sonnet" and Trust(db).dossier("sonnet")["counts"] == {"step_ok": 1}
    rows = db.all(
        "SELECT role, engine, company_id, mission_id, cost_usd, tokens, agent FROM usage_ledger "
        "ORDER BY id"
    )
    assert [r["role"] for r in rows] == ["plan", "exécution", "vérification", "rapport"]
    assert {r["company_id"] for r in rows} == {1} and {r["mission_id"] for r in rows} == {mid}
    assert rows[1]["agent"] == "sonnet" and rows[1]["cost_usd"] == 0.02 and rows[1]["tokens"] == 120
    # the user sends it back, then validates it: the record follows
    companies.set_status(task["id"], "todo")
    assert Trust(db).dossier("sonnet")["counts"].get("task_redo") is None  # it was not in review
    db.execute("UPDATE tasks SET status = 'review' WHERE id = ?", (task["id"],))
    companies.set_status(task["id"], "todo")
    db.execute("UPDATE tasks SET status = 'review' WHERE id = ?", (task["id"],))
    companies.set_status(task["id"], "done")
    counts = Trust(db).dossier("sonnet")["counts"]
    assert counts["task_redo"] == 1 and counts["task_validated"] == 1
    # rolling the mission back counts too
    mark_mission(db, mid, "from")
    ctx = tools.make_context(db, root, [str(tmp_path)])
    actions.write_file(ctx, str(tmp_path / "f.txt"), "x")
    mark_mission(db, mid, "to")
    actions.rollback_mission(ctx, mid)
    assert Trust(db).dossier("sonnet")["counts"]["rollback"] == 1
    # a created agent's steps go to its own record
    nova = CustomAgents(db).create("Nova", "haiku", "Finance")
    cli.replies = ["fait", '{"ok": false, "note": "non"}', "refait", '{"ok": false}', "r"]
    other = _queue(db, {"kind": "mission", "steps": ["x"], "agent": f"agent:{nova['id']}"})
    engine.run_next()
    assert _steps(db, other)[0]["key"] == f"agent:{nova['id']}"
    assert Trust(db).dossier(f"agent:{nova['id']}")["counts"] == {"step_fail": 1}


def test_autopilot_needs_trust(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    companies = Companies(db)
    companies.create("Acme")
    companies.set_autopilot("acme", True)
    companies.add_task("acme", "Une tâche", department="finance")
    engine = MissionEngine(db, Rooted(root), lambda *a: None, model="sonnet")  # type: ignore[arg-type]
    engine.earned_autonomy = True
    engine.parallel = 0  # starting the tasks only
    engine.tick(threaded=False)
    assert companies.tasks("acme")[0]["status"] == "todo"  # apprentice: waits for the user
    for _ in range(15):
        Trust(db).record("sonnet", "step_ok")
    engine.parallel = 1
    db.execute("UPDATE missions SET status = 'done'")
    assert companies.autopilot_tick(1, engine._trusted) == [1]


# ---- the ledger ----------------------------------------------------------------------------------


def test_ledger_summary(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    companies = Companies(db)
    cid = companies.create("Acme")["id"]
    task = companies.add_task("acme", "Étude", department="finance")
    mid = companies.start(task["id"])
    with runctx.scope(mission=mid, company=cid, agent="sonnet", role="exécution"):
        spend.record(db, Reply("x", "", False, 0.5, 1000), 12.0, engine="sonnet")
        spend.record(
            db, Reply("x", "", True), 3.0, engine="lmstudio:m", role="vérification", agent="haiku"
        )
    spend.record(db, Reply("x", "", False, 0.1), 2.0, engine="opus", role="conversation")
    Saas(db, root).record(cid, "mrr", 100, datetime.now().astimezone())
    data = spend.summary(db, datetime.now().astimezone(), cid)
    assert data["calls"] == 2 and data["cost_usd"] == 0.5 and data["failed"] == 1
    assert data["mrr"] == 100 and data["cost_per_mrr"] == 0.5
    assert [r["key"] for r in data["by_agent"]] == ["sonnet", "haiku"]
    assert data["by_department"] == [{"key": "finance", "cost": 0.5, "seconds": 15.0}]
    assert data["top_missions"][0]["id"] == mid
    everything = spend.summary(db, datetime.now().astimezone())
    assert everything["calls"] == 3 and "mrr" not in everything
    text = spend.text(db, datetime.now().astimezone(), cid)
    assert (
        "2 appels, 0.50 $" in text and "0.5 % du MRR" in text and "Par agent : Gétro 0.50 $" in text
    )
    assert spend.text(db, datetime.now().astimezone() + timedelta(days=60), cid).startswith(
        "aucun appel"
    )
    assert (
        spend.mission_company(db, {"company": 4}) == 4
        and spend.mission_company(db, {"task": 99}) is None
    )
    assert (
        spend.mission_company(db, {"task": task["id"]}) == cid
        and spend.mission_company(db, {}) is None
    )
    assert spend.mission_company(db, {"decision": 7}) is None
    assert spend.tokens_of({"usage": {"input_tokens": 3, "output_tokens": 4, "x": "y"}}) == 7
    assert spend.tokens_of({"usage": "?"}) == 0 and spend.tokens_of("?") == 0


def test_tokens_from_engines(tmp_path: Path) -> None:
    from spectre.assistant.llm import HttpAgent
    from spectre.assistant.providers import Providers

    line = json.dumps(
        {
            "result": "ok",
            "session_id": "s",
            "total_cost_usd": 0.01,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    )
    assert parse_reply(line).tokens == 15
    answers = [
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"id": "1", "function": {"name": "current_time", "arguments": "{}"}}
                        ]
                    }
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
        {
            "choices": [{"message": {"content": "fini"}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 1},
        },
    ]
    agent = HttpAgent(
        AssistantConfig(),
        tmp_path,
        providers=Providers(tmp_path, environ={}),
        transport=lambda *a: answers.pop(0),
        call_tool=lambda *a: "ok",
    )
    assert agent.ask("q", system="s", model="lmstudio:m").tokens == 20


def test_brain_turns_in_ledger(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    Brain(db, Rooted(root, Reply("Bonjour", "s", False, 0.03)), AssistantConfig()).ask("salut")
    row = db.one("SELECT role, engine, cost_usd FROM usage_ledger")
    assert (row["role"], row["engine"], row["cost_usd"]) == ("conversation", "opus", 0.03)


def test_proactive_trust(tmp_path: Path) -> None:
    from spectre.assistant.proactive import Proactive

    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    for _ in range(15):
        Trust(db).record("sonnet", "step_ok")
    notes: list[Any] = []
    Proactive(
        db, Rooted(root), AssistantConfig(), lambda *a: notes.append(a), fetch=lambda u: {}
    ).trust()  # type: ignore[arg-type]
    assert notes[-1][1] == "Gétro promu : confirmé"


def test_trust_tools(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    gate, ctx = Gate(db), tools.make_context(db, root, [str(tmp_path)])
    run = lambda tool, **args: tools.execute(gate, ctx, tool, args)  # noqa: E731
    assert run("agent_record").startswith("aucun dossier encore")
    Trust(db).record("sonnet", "step_ok")
    nova = CustomAgents(db).create("Nova", "haiku", "Finance")
    Trust(db).record(f"agent:{nova['id']}", "step_fail")
    assert (
        run("agent_record", agent="Gétro")
        == "Gétro : apprenti, fiabilité 66.7 % sur 1 points (step_ok 1)"
    )
    assert run("agent_record", agent="nova").startswith("Nova : apprenti")
    assert run("agent_record", agent="Zorg").startswith("ÉCHEC : agent inconnu")
    assert len(run("agent_record").splitlines()) == 2
    assert run("cost_report").startswith("aucun appel")
    assert run("cost_report", company="Nulle").startswith("ÉCHEC : entreprise")


def test_trust_api(api: Client, service: AssistantService) -> None:  # noqa: F811
    Trust(service.db).record("sonnet", "step_ok")
    assert api.json("GET", "/api/assistant/trust")[1][0]["name"] == "Gétro"
    spend.record(service.db, Reply("x", "", False, 0.2), 1.0, engine="opus", role="conversation")
    assert api.json("GET", "/api/assistant/costs")[1]["calls"] == 1
    assert api.json("GET", "/api/assistant/costs?company=1&days=7")[1]["calls"] == 0
    assert service.missions.earned_autonomy is True
