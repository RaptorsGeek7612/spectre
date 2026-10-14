"""Companies: org chart, task board, task missions, parallel engine, steering and stopping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import tools
from spectre.assistant.brain import Reply
from spectre.assistant.company import (
    Companies,
    CompanyError,
    enqueue,
    planner_prompt,
    resolve_department,
    steer_mission,
    stop_mission,
    take_notes,
)
from spectre.assistant.custom_agents import CustomAgents
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate
from spectre.assistant.missions import MissionEngine
from spectre.assistant.service import AssistantService
from tests.test_assistant_agents import _steps, db  # noqa: F401 - fixture
from tests.test_assistant_brain import FakeCLI
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client


def _mission(db: Database, mid: int) -> dict[str, Any]:  # noqa: F811
    row = db.one("SELECT * FROM missions WHERE id = ?", (mid,))
    assert row is not None
    return row


# ---- the board ----------------------------------------------------------------------------------


def test_departments() -> None:
    assert resolve_department("Finance") == "finance"
    assert resolve_department("Support client") == "support"
    assert resolve_department("Produit") == "produit"
    assert resolve_department("RH") == "operations" and resolve_department("ceo") == "direction"
    assert resolve_department("cuisine") == ""
    assert "finance (Finance)" in planner_prompt()


def test_companies_and_posts(db: Database) -> None:  # noqa: F811
    companies = Companies(db)
    with pytest.raises(CompanyError, match="aucune pour l'instant"):
        companies.get("")
    acme = companies.create(" Acme ", "Un SaaS de minage")
    assert companies.get("") == acme  # the only one: no need to name it
    assert companies.get("ACME") == acme and companies.get(f"#{acme['id']}") == acme
    for name, error in [("A", "2 à 60"), ("acme", "existe déjà")]:
        with pytest.raises(CompanyError, match=error):
            companies.create(name)
    companies.create("Beta")
    with pytest.raises(CompanyError, match="existantes : Acme, Beta"):
        companies.get("")
    nova = CustomAgents(db).create("Nova", "sonnet", "Finance")
    assert companies.set_post("acme", "Finance", "nova") == f"agent:{nova['id']}"
    assert companies.set_post("acme", "marketing", "Kyra") == "chatgpt"
    assert companies.set_post("acme", "produit", "lmstudio:gemma") == "lmstudio:gemma"
    assert companies.set_post("acme", "produit", "défaut") == ""
    with pytest.raises(CompanyError, match="département inconnu"):
        companies.set_post("acme", "cuisine", "nova")
    with pytest.raises(CompanyError, match="agent inconnu"):
        companies.set_post("acme", "finance", "Zorg")
    posts = companies.posts("acme")
    assert posts["finance"] == f"agent:{nova['id']}" and posts["direction"] == ""
    assert companies.agent_label(posts["finance"]) == "Nova"
    assert (
        companies.agent_label("chatgpt") == "Kyra"
        and companies.agent_label("") == "selon les réglages"
    )
    assert companies.agent_label("agent:99") == "agent supprimé"
    assert companies.set_autopilot("acme", True)["autopilot"] == 1


def test_tasks_and_dependencies(db: Database) -> None:  # noqa: F811
    companies = Companies(db)
    acme, beta = companies.create("Acme", "SaaS"), companies.create("Beta")
    study = companies.add_task("acme", "Étude des prix", department="finance", priority=1)
    page = companies.add_task(
        "acme", "Page de prix", department="marketing", depends_on=[study["id"]]
    )
    other = companies.add_task("beta", "Autre chose")
    with pytest.raises(CompanyError, match="autre entreprise"):
        companies.add_task("acme", "Mauvaise dépendance", depends_on=[other["id"]])
    with pytest.raises(CompanyError, match="département inconnu"):
        companies.add_task("acme", "Tâche", department="cuisine")
    with pytest.raises(CompanyError, match="3 à 200"):
        companies.add_task("acme", "x")
    assert [t["id"] for t in companies.ready("acme")] == [study["id"]]
    with pytest.raises(CompanyError, match="attend d'abord : #"):
        companies.start(page["id"])
    mid = companies.start(study["id"])
    plan = json.loads(_mission(db, mid)["plan"])
    assert (
        plan["task"] == study["id"]
        and "Tu travailles pour l'entreprise « Acme » : SaaS" in plan["brief"]
    )
    assert "Ton poste : Finance." in plan["brief"] and "agent" not in plan
    assert companies.task(study["id"])["status"] == "doing"
    with pytest.raises(CompanyError, match="en cours : elle ne peut pas"):
        companies.start(study["id"])
    with pytest.raises(CompanyError, match="arrête d'abord sa mission"):
        companies.set_status(study["id"], "done")
    companies.mission_finished(mid, ok=True)
    assert companies.task(study["id"])["status"] == "done"
    assert [t["id"] for t in companies.ready("acme")] == [page["id"]]
    assert (
        companies.set_status(page["id"], "Bloquée", "en attente du logo")["note"]
        == "en attente du logo"
    )
    with pytest.raises(CompanyError, match="statut"):
        companies.set_status(page["id"], "doing")
    companies.set_status(page["id"], "todo")
    board = companies.board(acme["id"])
    assert (
        "Pilote automatique : désactivé" in board
        and "- Finance (finance) : selon les réglages" in board
    )
    assert f"#{page['id']} [à faire] P2 marketing : Page de prix, après #{study['id']}" in board
    assert "Autre chose" in companies.board(beta["id"])
    assert "Tâches : aucune" in companies.board(companies.create("Gamma")["id"])
    with pytest.raises(CompanyError, match="introuvable"):
        companies.task(999)


def test_task_agent_comes_from_its_post(db: Database) -> None:  # noqa: F811
    companies = Companies(db)
    companies.create("Acme")
    companies.set_post("acme", "marketing", "Kyra")
    task = companies.add_task("acme", "Visuels", department="marketing")
    own = companies.add_task("acme", "Audit", department="marketing", agent="Syfer")
    assert json.loads(_mission(db, companies.start(task["id"]))["plan"])["agent"] == "chatgpt"
    assert json.loads(_mission(db, companies.start(own["id"]))["plan"])["agent"] == "mistral"


def test_failures_and_cancellation(db: Database) -> None:  # noqa: F811
    companies = Companies(db)
    companies.create("Acme")
    task = companies.add_task("acme", "Tâche longue")
    mid = companies.start(task["id"])
    companies.mission_failed(mid, "plus de quota")
    assert companies.task(task["id"])["status"] == "blocked"
    companies.set_status(task["id"], "todo")
    mid = companies.start(task["id"])
    assert companies.set_status(task["id"], "annulée")["status"] == "cancelled"
    assert _mission(db, mid)["status"] == "cancelled"
    companies.mission_failed(mid, "trop tard")  # a cancelled task stays cancelled
    assert companies.task(task["id"])["status"] == "cancelled"
    companies.mission_finished(9999, ok=True)  # a mission without task: nothing to do


def test_plan_and_autopilot(db: Database) -> None:  # noqa: F811
    companies = Companies(db)
    companies.create("Acme")
    created = companies.add_plan(
        "acme",
        [
            {"title": "Étude de marché", "department": "direction", "priority": 1},
            {"title": "Prix", "department": "finance", "depends_on": [0, 5, "x"]},
            "pas une tâche",
            {"title": "Campagne", "department": "inconnu", "depends_on": [1]},
        ],
    )
    assert [(t["department"], t["depends_on"]) for t in created] == [
        ("direction", []),
        ("finance", [created[0]["id"]]),
        ("", [created[1]["id"]]),
    ]
    with pytest.raises(CompanyError, match="aucune tâche"):
        companies.add_plan("acme", [])
    assert companies.autopilot_tick(5) == []  # autopilot off
    companies.set_autopilot("acme", True)
    started = companies.autopilot_tick(5)
    assert len(started) == 1 and companies.task(created[0]["id"])["status"] == "doing"
    assert companies.autopilot_tick(0) == []


def test_steer_and_stop(db: Database) -> None:  # noqa: F811
    mid = enqueue(db, "Une mission", {"kind": "mission"})
    with pytest.raises(CompanyError, match="consigne vide"):
        steer_mission(db, mid, "  ")
    assert "prochaine étape" in steer_mission(db, mid, "Concentre-toi sur la France")
    assert take_notes(db, mid) == ["Concentre-toi sur la France"]
    assert take_notes(db, mid) == []  # each note is read once
    assert stop_mission(db, mid) == f"mission #{mid} arrêtée (tout de suite)"
    for call in (lambda: steer_mission(db, mid, "x"), lambda: stop_mission(db, mid)):
        with pytest.raises(CompanyError, match="n'est plus en cours"):
            call()
    for call in (lambda: steer_mission(db, 99, "x"), lambda: stop_mission(db, 99)):
        with pytest.raises(CompanyError, match="introuvable"):
            call()


# ---- the mission engine --------------------------------------------------------------------


def test_task_mission_moves_the_task(db: Database, tmp_path: Path) -> None:  # noqa: F811
    companies = Companies(db)
    companies.create("Acme", "SaaS")
    task = companies.add_task("acme", "Étude", department="finance")
    companies.start(task["id"])
    cli = FakeCLI(tmp_path, '{"steps": ["chercher"]}', "trouvé", '{"ok": true}', "rapport")
    engine = MissionEngine(db, cli, lambda *a: None)  # type: ignore[arg-type]
    steer_mission(db, 1, "Pas plus de 3 concurrents")
    engine.run_next()
    worker = cli.calls[1]
    assert "Ton poste : Finance." in worker["system"]
    assert "Consignes de l'utilisateur, données en cours de route" in worker["prompt"]
    assert "- Pas plus de 3 concurrents" in worker["prompt"]
    saved = json.loads(_mission(db, 1)["plan"])
    assert saved["task"] == task["id"] and saved["steps"] == ["chercher"]  # the plan keeps its keys
    assert companies.task(task["id"])["status"] == "done"
    # not every step verified: the task waits for the user
    task2 = companies.add_task("acme", "Prix")
    mid = companies.start(task2["id"])
    db.execute(
        "UPDATE missions SET plan = ? WHERE id = ?",
        (json.dumps({"kind": "mission", "task": task2["id"], "steps": ["a"]}), mid),
    )
    cli.replies = [
        "raté",
        '{"ok": false, "note": "rien"}',
        "encore raté",
        '{"ok": false, "note": "rien"}',
        "r",
    ]
    engine.run_next()
    assert companies.task(task2["id"])["status"] == "review"
    assert companies.task(task2["id"])["note"] == "1 étape(s) à revoir."


def test_failed_and_stopped_missions(db: Database, tmp_path: Path) -> None:  # noqa: F811
    companies = Companies(db)
    companies.create("Acme")
    task = companies.add_task("acme", "Étude")
    mid = companies.start(task["id"])
    notes: list[Any] = []
    cli = FakeCLI(tmp_path, "pas de JSON")
    engine = MissionEngine(db, cli, lambda *a: notes.append(a))  # type: ignore[arg-type]
    engine.run_next()
    assert (
        _mission(db, mid)["status"] == "failed"
        and companies.task(task["id"])["status"] == "blocked"
    )
    # stopped between two steps: no further step, no report
    companies.set_status(task["id"], "todo")
    mid = companies.start(task["id"])
    db.execute(
        "UPDATE missions SET plan = ? WHERE id = ?",
        (json.dumps({"kind": "mission", "steps": ["a", "b"]}), mid),
    )

    class Stopper(FakeCLI):
        def ask(self, prompt: str, **kwargs: Any) -> Reply:
            reply = super().ask(prompt, **kwargs)
            if "Étape à faire : a" in prompt:
                stop_mission(db, mid)
            return reply

    stopper = Stopper(tmp_path, "fait a", '{"ok": true}')
    MissionEngine(db, stopper, lambda *a: notes.append(a)).run_next()  # type: ignore[arg-type]
    assert len(stopper.calls) == 2 and _mission(db, mid)["status"] == "cancelled"
    assert companies.task(task["id"])["status"] == "cancelled"
    assert notes[-1][1] == f"Mission #{mid} arrêtée"


def test_parallel_tick(db: Database, tmp_path: Path) -> None:  # noqa: F811
    companies = Companies(db)
    companies.create("Acme")
    for title in ("Une", "Deux", "Trois"):
        companies.add_task("acme", f"Tâche {title}")
    companies.set_autopilot("acme", True)
    cli = FakeCLI(tmp_path, *(['{"steps": ["x"]}', "ok", '{"ok": true}', "rapport"] * 3))
    engine = MissionEngine(db, cli, lambda *a: None, parallel=2)  # type: ignore[arg-type]
    assert engine.tick(threaded=False) == [1, 2]  # two slots: two tasks started and run
    assert [t["status"] for t in companies.tasks("acme")] == ["done", "done", "todo"]
    assert engine.tick(threaded=False) == [3] and engine.active() == []
    assert engine.tick(threaded=False) == []


def test_company_plan_mission(db: Database, tmp_path: Path) -> None:  # noqa: F811
    companies = Companies(db)
    acme = companies.create("Acme")
    plan = {
        "tasks": [
            {"title": "Étude", "department": "direction"},
            {"title": "Prix", "department": "finance", "depends_on": [0]},
        ]
    }
    cli = FakeCLI(tmp_path, json.dumps(plan))
    notes: list[Any] = []
    mid = enqueue(db, "Lancer la bêta", {"kind": "company_plan", "company": acme["id"]})
    MissionEngine(db, cli, lambda *a: notes.append(a)).run_next()  # type: ignore[arg-type]
    assert (
        cli.calls[0]["system"] == planner_prompt()
        and "Objectif : Lancer la bêta" in cli.calls[0]["prompt"]
    )
    assert [t["title"] for t in companies.tasks("acme")] == ["Étude", "Prix"]
    row = _mission(db, mid)
    assert row["status"] == "done" and "(après #1)" in row["report"]
    assert notes[-1][2].startswith("2 tâches au tableau de Acme.")
    failing = FakeCLI(tmp_path, Reply("panne", "", True))
    mid = enqueue(db, "Encore", {"kind": "company_plan", "company": acme["id"]})
    MissionEngine(db, failing, lambda *a: None).run_next()  # type: ignore[arg-type]
    assert _mission(db, mid)["status"] == "failed"


# ---- tools, service and API ----------------------------------------------------------------------


def test_company_tools(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    database = Database(root / "spectre.db")
    gate, ctx = Gate(database), tools.make_context(database, root, [str(tmp_path)])
    run = lambda tool, **args: tools.execute(gate, ctx, tool, args)  # noqa: E731
    assert run("list_companies").startswith("aucune entreprise")
    assert run("create_company", name="Acme", pitch="SaaS").startswith("entreprise #1 créée : Acme")
    assert run("list_companies") == "#1 Acme : SaaS"
    assert (
        run("set_post", company="acme", department="finance", agent="Gétro")
        == "poste finance : Gétro"
    )
    assert run("add_task", company="acme", title="Étude", department="finance") == (
        "tâche #1 ajoutée (finance) : Étude"
    )
    assert run("add_task", company="acme", title="Prix", depends_on="#1") == (
        "tâche #2 ajoutée (sans département) : Prix"
    )
    assert run("start_tasks", company="acme") == "lancées : tâche #1 → mission #1"
    assert (
        run("start_tasks", company="acme") == "aucune tâche prête (à faire, dépendances terminées)"
    )
    assert run("steer_mission", mission_id=1, message="Va vite").startswith("consigne transmise")
    assert run("stop_mission", mission_id=1) == "mission #1 arrêtée (tout de suite)"
    assert run("update_task", task_id=2, status="blocked", note="x") == "tâche #2 : bloquée"
    assert run("update_task", task_id=2, status="doing").startswith("ÉCHEC : statut")
    assert run("set_autopilot", company="acme", on=True) == "pilote automatique activé pour Acme"
    assert "Pilote automatique : activé" in run("company_board")
    assert run("plan_company", company="acme", objective="Lancer").startswith(
        "mission #2 : la direction"
    )
    assert run("plan_company", company="acme", objective="x").startswith("ÉCHEC : décris")
    assert run("start_tasks", task_ids="2").startswith("ÉCHEC : la tâche #2 est bloquée")
    assert run("create_company", name="Acme").startswith("ÉCHEC : l'entreprise")


def test_company_api(api: Client, service: AssistantService) -> None:  # noqa: F811
    status, body = api.json("POST", "/api/assistant/company", {"name": "Acme", "pitch": "SaaS"})
    assert status == 200 and body["result"].startswith("entreprise #1 créée")
    assert api.json("GET", "/api/assistant/company")[1][0]["name"] == "Acme"
    assert (
        api.json(
            "POST", "/api/assistant/company/1/post", {"department": "marketing", "agent": "chatgpt"}
        )[0]
        == 200
    )
    status, body = api.json(
        "POST",
        "/api/assistant/company/1/tasks",
        {"title": "Visuels", "department": "marketing", "priority": 1},
    )
    assert body["result"] == "tâche #1 ajoutée (marketing) : Visuels"
    data: dict[str, Any] = api.json("GET", "/api/assistant/company/1")[1]
    assert data["company"]["name"] == "Acme" and data["ready"] == [1] and data["parallel"] == 2
    marketing = next(d for d in data["departments"] if d["key"] == "marketing")
    assert (
        marketing["agent_label"] == "Kyra" and {"key": "haiku", "name": "Kaïto"} in data["agents"]
    )
    assert (
        api.json("POST", "/api/assistant/tasks/1/start", {})[1]["result"]
        == "lancées : tâche #1 → mission #1"
    )
    assert api.json("GET", "/api/assistant/company/1")[1]["tasks"][0]["mission_status"] == "queued"
    assert api.json("POST", "/api/assistant/missions/1/steer", {"message": "Plus sobre"})[0] == 200
    assert api.json("POST", "/api/assistant/missions/1/stop", {})[1]["result"].startswith(
        "mission #1 arrêtée"
    )
    status, body = api.json("POST", "/api/assistant/missions/1/stop", {})
    assert status == 400 and "n'est plus en cours" in body["error"]
    assert (
        api.json("POST", "/api/assistant/tasks/1", {"status": "todo"})[1]["result"]
        == "tâche #1 : à faire"
    )
    assert api.json("POST", "/api/assistant/company/1/autopilot", {"on": True})[1][
        "result"
    ].startswith("pilote automatique activé")
    assert api.json("POST", "/api/assistant/company/1/start", {})[1]["result"].startswith("lancées")
    assert (
        api.json("POST", "/api/assistant/company/1/plan", {"objective": "Lancer la bêta"})[0] == 200
    )
    assert api.json("POST", "/api/assistant/company/1/nimporte", {})[0] == 404
    status, body = api.json("POST", "/api/assistant/company/1/tasks", {"title": "x"})
    assert status == 400 and "3 à 200" in body["error"]


def test_parallel_setting(service: AssistantService) -> None:  # noqa: F811
    service.update_config({"mission_parallel": 3})
    assert service.missions.parallel == 3
    for bad in (0, 5, "2"):
        with pytest.raises(ValueError, match="de 1 à 4"):
            service.update_config({"mission_parallel": bad})
