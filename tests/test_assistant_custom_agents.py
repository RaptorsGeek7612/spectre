"""Agents created by Spectre (or from the interface): storage, tools, missions and web API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import tools
from spectre.assistant.custom_agents import AgentError, CustomAgents, worker_brief
from spectre.assistant.db import Database
from spectre.assistant.missions import MissionEngine
from spectre.assistant.service import AssistantService
from tests.test_assistant_agents import _queue, _steps, db  # noqa: F401 - fixture
from tests.test_assistant_brain import FakeCLI
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client


def test_create_get_delete(db: Database) -> None:  # noqa: F811
    agents = CustomAgents(db)
    nova = agents.create("  Nova ", "Gétro", "Cuisine et menus", "Pas de porc.")
    assert (nova["name"], nova["engine"], nova["instructions"]) == (
        "Nova",
        "sonnet",
        "Pas de porc.",
    )
    assert agents.get("NOVA") == nova and agents.get(f"agent:{nova['id']}") == nova
    assert agents.get("") is None and agents.get("agent:99") is None
    assert agents.create("Éole", "mistral", "Réseau")["engine"] == "mistral"
    assert agents.get("eole")["name"] == "Éole"  # type: ignore[index]
    assert [a["name"] for a in agents.list()] == ["Nova", "Éole"]
    assert agents.delete("nova")["id"] == nova["id"]
    assert [a["name"] for a in agents.list()] == ["Éole"]
    with pytest.raises(AgentError, match="aucun agent"):
        agents.delete("Nova")


@pytest.mark.parametrize(
    ("name", "engine", "role", "error"),
    [
        ("N", "sonnet", "r", "2 à 30"),
        ("12345", "sonnet", "r", "2 à 30"),
        ("x" * 31, "sonnet", "r", "2 à 30"),
        ("Kyra", "sonnet", "r", "déjà le nom"),
        ("warden", "sonnet", "r", "déjà le nom"),
        ("Nova", "gemini", "r", "moteur inconnu"),
        ("Nova", "claude", "r", "moteur inconnu"),
        ("Nova", "sonnet", " ", "rôle"),
        ("Nova", "sonnet", "r" * 301, "limité"),
    ],
)
def test_create_refused(db: Database, name: str, engine: str, role: str, error: str) -> None:  # noqa: F811
    with pytest.raises(AgentError, match=error):
        CustomAgents(db).create(name, engine, role)


def test_duplicate_and_limit(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    agents = CustomAgents(db)
    agents.create("Nova", "haiku", "r")
    with pytest.raises(AgentError, match="déjà"):
        agents.create("nova", "haiku", "r")
    monkeypatch.setattr("spectre.assistant.custom_agents.MAX_AGENTS", 1)
    with pytest.raises(AgentError, match="au maximum"):
        agents.create("Orion", "haiku", "r")


def test_worker_brief() -> None:
    assert worker_brief({"role": "R", "instructions": ""}) == (
        "Ta spécialité, définie à ta création : R"
    )
    assert worker_brief({"role": "R", "instructions": "C"}).endswith("Tes consignes :\nC")


def test_tools(db: Database, tmp_path: Path) -> None:  # noqa: F811
    ctx = tools.make_context(db, tmp_path, [str(tmp_path)])
    answer = tools._create_agent(ctx, "Nova", "sonnet", "Cuisine")
    assert answer.startswith("agent créé : Nova (moteur Gétro, sonnet)")
    assert 'start_mission(agent="Nova")' in answer
    with pytest.raises(tools.ActionError, match="déjà"):
        tools._create_agent(ctx, "Nova", "sonnet", "Cuisine")
    listing = tools._list_agents(ctx)
    assert "Kyra (chatgpt" in listing and "- Nova (sonnet) : Cuisine" in listing
    started = tools._start_mission(ctx, "Menus", agent="nova")
    assert "confiée à Nova" in started
    row = db.one("SELECT plan FROM missions ORDER BY id DESC LIMIT 1")
    assert row and json.loads(row["plan"])["agent"] == "agent:1"
    assert tools._delete_agent(ctx, "Nova") == "agent supprimé : Nova"
    with pytest.raises(tools.ActionError, match="aucun agent"):
        tools._delete_agent(ctx, "Nova")
    assert "(aucun)" in tools._list_agents(ctx)


def test_tools_governance(service: AssistantService) -> None:  # noqa: F811
    created = tools.execute(
        service.gate, service.ctx, "create_agent", {"name": "Nova", "engine": "haiku", "role": "r"}
    )
    assert created.startswith("agent créé")  # creating runs on its own
    deleted = tools.execute(service.gate, service.ctx, "delete_agent", {"name": "Nova"})
    assert deleted.startswith("EN ATTENTE DE VALIDATION")  # deleting asks first


def test_mission_runs_on_the_created_agent(db: Database, tmp_path: Path) -> None:  # noqa: F811
    nova = CustomAgents(db).create("Nova", "haiku", "Cuisine de saison", "Budget serré.")
    claude = FakeCLI(tmp_path, "menus faits", '{"ok": true}', "rapport")
    engine = MissionEngine(db, claude, lambda *a: None, model="sonnet")  # type: ignore[arg-type]
    mid = _queue(db, {"kind": "mission", "steps": ["menus"], "agent": f"agent:{nova['id']}"})
    engine.run_next()
    worker = claude.calls[0]
    assert worker["model"] == "haiku" and worker["system"].startswith("Tu es Nova,")
    assert "Cuisine de saison" in worker["system"] and "Budget serré." in worker["system"]
    assert _steps(db, mid)[0]["name"] == "Nova"
    assert "Étape 1 (Nova)" in claude.calls[2]["prompt"]
    # deleted meanwhile: the mission falls back to the setting
    CustomAgents(db).delete("Nova")
    claude.replies += ["fait", '{"ok": true}', "rapport"]
    mid = _queue(db, {"kind": "mission", "steps": ["b"], "agent": f"agent:{nova['id']}"})
    engine.run_next()
    assert _steps(db, mid)[0]["name"] == "Gétro"


def test_api(api: Client, service: AssistantService) -> None:  # noqa: F811
    status, body = api.json(
        "POST", "/api/assistant/agents", {"name": "Nova", "engine": "sonnet", "role": "Cuisine"}
    )
    assert status == 200 and body["result"].startswith("agent créé : Nova")
    status, body = api.json("POST", "/api/assistant/agents", {"name": "Nova", "role": "x"})
    assert status == 400 and "déjà" in body["error"]
    data: dict[str, Any] = api.json("GET", "/api/assistant/agents")[1]
    assert [(a["name"], a["engine"]) for a in data["created"]] == [
        ("Nova", "Sonnet 5.5 · Claude Code")
    ]
    agent_id = data["created"][0]["id"]
    assert api.json("POST", f"/api/assistant/agents/{agent_id}/delete", {})[1]["name"] == "Nova"
    assert api.json("GET", "/api/assistant/agents")[1]["created"] == []
    assert api.json("POST", f"/api/assistant/agents/{agent_id}/delete", {})[0] == 400
    audit = service.audit()
    assert audit[0]["tool"] == "delete_agent" and audit[0]["decision"] == "user"
