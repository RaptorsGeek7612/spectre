"""The board (decisions, memo, review with the figures) and measured experiments."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import tools
from spectre.assistant.board import Board, BoardError, memo
from spectre.assistant.brain import Reply
from spectre.assistant.company import Companies
from spectre.assistant.custom_agents import CustomAgents
from spectre.assistant.db import Database
from spectre.assistant.experiments import ExperimentError, Experiments, describe
from spectre.assistant.governance import Gate
from spectre.assistant.missions import MissionEngine
from spectre.assistant.saas import Saas
from spectre.assistant.service import AssistantService
from tests.test_assistant_engines import Rooted
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone(timedelta(hours=2)))


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Database, Path, int]:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    company = Companies(db).create("Acme", "SaaS de minage")
    Saas(db, root).record(company["id"], "mrr", 1000, NOW)
    Saas(db, root).record(company["id"], "churn_rate", 4, NOW)
    return db, root, company["id"]


def reply(data: Any) -> Reply:
    return Reply(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), "", False)


VERDICT = {
    "options": [{"nom": "29 €", "pour": "marge", "contre": "churn"}, "pas un objet"],
    "decision": "Passer l'offre Pro à 29 € pour les nouveaux clients",
    "raisons": "Les concurrents sont à 35 €",
    "risques": ["churn"],
    "prochaines_etapes": ["Prévenir les clients"],
    "indicateur": "mrr",
    "sens": "up",
    "variation_min": 10,
    "reevaluer_dans_jours": 30,
}


# ---- experiments ---------------------------------------------------------------------------------


def test_experiments(setup: tuple[Database, Path, int]) -> None:
    db, root, cid = setup
    experiments = Experiments(db, root)
    row = experiments.start(
        cid, "L'essai de 14 jours augmente le MRR", "mrr", "hausse", 10, 7, now=NOW
    )
    assert row["baseline"] == 1000 and row["end_at"].startswith("2026-10-21")
    assert "départ 1 000, fin le 2026-10-21" in describe(row)
    for args, error in [
        (("court", "mrr"), "hypothèse"),
        (("Une hypothèse longue", "mrr", "sideways"), "sens"),
        (("Une hypothèse longue", "mrr", "up", 5, 0), "durée"),
        (("Une hypothèse longue", "mrr", "up", 0), "plus de 0"),
        (("Une hypothèse longue", "signups_7d"), "pas encore de chiffre"),
    ]:
        with pytest.raises(ExperimentError, match=error):
            experiments.start(cid, *args, now=NOW)
    notes: list[Any] = []
    assert experiments.tick(NOW + timedelta(days=3), notes.append) == []
    Saas(db, root).record(cid, "mrr", 1150, NOW + timedelta(days=7))
    assert experiments.tick(NOW + timedelta(days=7), lambda *a: notes.append(a)) == [row["id"]]
    done = experiments.get(row["id"])
    assert (done["verdict"], done["change"], done["status"]) == ("confirmée", 15.0, "done")
    assert (
        notes[-1][1] == f"Expérience #{row['id']} : confirmée"
        and "sans groupe témoin" in notes[-1][2]
    )
    assert experiments.judge({"baseline": 1000, "direction": "down", "min_change": 5}, 1100) == (
        "infirmée",
        10.0,
    )
    assert (
        experiments.judge({"baseline": 1000, "direction": "up", "min_change": 5}, 1020)[0]
        == "non concluante"
    )
    assert experiments.judge({"baseline": 0, "direction": "up", "min_change": 5}, 3) == (
        "confirmée",
        100.0,
    )
    other = experiments.start(
        cid, "Le churn baisse avec l'onboarding", "churn_rate", "down", now=NOW
    )
    assert experiments.stop(other["id"])["status"] == "cancelled" and "arrêtée" in describe(
        experiments.get(other["id"])
    )
    with pytest.raises(ExperimentError, match="déjà terminée"):
        experiments.stop(other["id"])
    with pytest.raises(ExperimentError, match="introuvable"):
        experiments.get(99)
    db.execute("DELETE FROM saas_metrics WHERE metric = 'churn_rate'")
    third = experiments.start(cid, "Une hypothèse sur le MRR", "mrr", now=NOW)
    db.execute("DELETE FROM saas_metrics")
    assert experiments.evaluate(third, NOW)["verdict"] == "non concluante"
    assert "pas de chiffre" in describe(experiments.get(third["id"]))


# ---- the board -----------------------------------------------------------------------------------


def test_board_deliberates_and_reviews(setup: tuple[Database, Path, int]) -> None:
    db, root, cid = setup
    board = Board(db, root)
    with pytest.raises(BoardError, match="question"):
        board.convene("acme", "29 ?")
    decision, mid = board.convene("acme", "Passer l'offre Pro de 19 € à 29 € ?")
    assert decision["status"] == "deliberating" and decision["mission_id"] == mid
    seats: list[str] = []

    def seat(department: str, prompt: str, system: str) -> Reply:
        seats.append(department)
        assert "Décision à prendre : Passer l'offre Pro" in prompt and "MRR : 1 000" in prompt
        if department == "marketing":
            return reply("pas du JSON")
        return reply({"position": "pour", "arguments": [f"{department} ok"], "risques": ["prix"]})

    lead_calls: list[tuple[str, str]] = []

    def lead(prompt: str, system: str) -> Reply:
        lead_calls.append((prompt, system))
        if "Choisis les 2 à 4" in system:
            return reply(
                {"departments": ["Finance", "marketing", "direction", "cuisine", "finance"]}
            )
        return reply(VERDICT)

    text = board.deliberate(decision["id"], seat, lead, NOW)
    assert seats == ["finance", "marketing"]
    assert "Finance (pour)" in lead_calls[1][0] and "chiffres disponibles" not in lead_calls[1][1]
    assert "churn_rate, mrr" in lead_calls[1][1]
    done = board.get(decision["id"])
    assert done["status"] == "decided" and done["decision"].startswith("Passer l'offre Pro à 29 €")
    assert done["opinions"][1]["position"] == "absent" and done["kpis_before"]["mrr"] == 1000
    assert done["review_at"].startswith("2026-11-13") and done["experiment_id"]
    assert (
        "# Conseil de Acme — décision #1" in text
        and "**29 €** — pour : marge ; contre : churn" in text
    )
    assert "mesurée par l'expérience #1 (mrr)" in text
    experiment = Experiments(db, root).get(done["experiment_id"])
    assert experiment["decision_id"] == decision["id"] and experiment["min_change"] == 10
    # thirty days later: the review uses the experiment and the figures since
    later = NOW + timedelta(days=31)
    Saas(db, root).record(cid, "mrr", 900, later)
    assert [d["id"] for d in board.due_reviews(later)] == [decision["id"]]
    review_mid = board.queue_review(decision["id"])
    assert board.get(decision["id"])["status"] == "reviewing" and review_mid > mid
    with pytest.raises(BoardError, match="pas en attente"):
        board.queue_review(decision["id"])
    seen: list[str] = []

    def reviewer(prompt: str, system: str) -> Reply:
        seen.append(prompt)
        return reply({"resultat": "ratée", "lecon": "Hausse trop brutale : prévenir et étaler."})

    assert (
        board.review(decision["id"], reviewer, later)
        == "Ratée : Hausse trop brutale : prévenir et étaler."
    )
    assert (
        "Expérience : « Décision #1" in seen[0]
        and "infirmée" in seen[0]
        and "mrr : 1000 → 900" in seen[0]
    )
    assert board.get(decision["id"])["outcome"] == "ratée"
    assert "Hausse trop brutale" in board.lessons(cid)
    # the next board hears the lesson
    second, _ = board.convene("acme", "Lancer une offre Entreprise à 99 € ?")
    prompts: list[str] = []
    board.deliberate(
        second["id"],
        lambda d, p, s: reply({"position": "nuancé"}),
        lambda p, s: (
            prompts.append(p),
            reply(
                {"departments": []} if "Choisis" in s else {"decision": "Oui", "indicateur": "rien"}
            ),
        )[1],
        later,
    )
    assert (
        "Leçons des décisions passées" in prompts[0]
        and board.get(second["id"])["experiment_id"] is None
    )


def test_board_failures(setup: tuple[Database, Path, int]) -> None:
    db, root, cid = setup
    board = Board(db, root)
    decision, _ = board.convene("acme", "Recruter un commercial ce trimestre ?")
    with pytest.raises(BoardError, match="panne"):
        board.deliberate(
            decision["id"],
            lambda d, p, s: reply({"position": "pour"}),
            lambda p, s: Reply("panne", "", True),
            NOW,
        )
    board.failed(decision["id"], "panne")
    assert board.get(decision["id"])["status"] == "failed"
    db.execute("UPDATE decisions SET status = 'reviewing' WHERE id = ?", (decision["id"],))
    board.failed(decision["id"], "x")  # a failed review goes back to « décidée »
    assert board.get(decision["id"])["status"] == "decided"
    with pytest.raises(BoardError, match="introuvable"):
        board.get(99)
    with pytest.raises(BoardError, match="illisible"):
        board.review(decision["id"], lambda p, s: reply("[1, 2]"), NOW)
    weird = board.review(decision["id"], lambda p, s: reply({"resultat": "géniale"}), NOW)
    assert weird.startswith("Mitigée") and memo(board.get(decision["id"]), "Acme").startswith(
        "# Conseil"
    )


def test_board_missions(setup: tuple[Database, Path, int]) -> None:
    db, root, cid = setup
    CustomAgents(db).create("Nova", "haiku", "Finance prudente")
    Companies(db).set_post("acme", "finance", "Nova")
    Companies(db).set_post("acme", "marketing", "Kyra")
    decision, mid = Board(db, root).convene("acme", "Passer l'offre Pro à 29 € ?")
    cli = Rooted(
        root,
        json.dumps({"departments": ["finance", "produit"]}),
        json.dumps({"position": "contre"}),
        json.dumps({"position": "pour"}),
        json.dumps(VERDICT),
    )
    notes: list[Any] = []
    engine = MissionEngine(db, cli, lambda *a: notes.append(a), model="sonnet", lead_model="opus")  # type: ignore[arg-type]
    engine.engines.agents["chatgpt"] = Rooted(root, *[json.dumps({"position": "pour"})] * 3)
    engine.run_next()
    models = [c["model"] for c in cli.calls]
    assert models == [
        "opus",
        "haiku",
        "sonnet",
        "opus",
    ]  # finance = Nova on Haiku, produit = setting
    assert "Finance prudente" in cli.calls[1]["system"]
    assert notes[-1][1] == f"Le conseil a décidé (#{mid})"
    assert db.one("SELECT status FROM missions WHERE id = ?", (mid,))["status"] == "done"
    assert engine._seat(cid, "marketing") == ("chatgpt", "")
    CustomAgents(db).delete("Nova")
    assert engine._seat(cid, "finance") == ("sonnet", "")
    # a review mission, and a failing deliberation
    review_mid = Board(db, root).queue_review(decision["id"])
    cli.replies = [json.dumps({"resultat": "réussie", "lecon": "Bien."})]
    engine.run_next()
    assert db.one("SELECT report FROM missions WHERE id = ?", (review_mid,))["report"].startswith(
        "# Réévaluation"
    )
    second, mid2 = Board(db, root).convene("acme", "Ouvrir un bureau à Lyon ?")
    cli.replies = [
        json.dumps({"departments": []}),
        *[json.dumps({"position": "pour"})] * 2,
        Reply("panne", "", True),
    ]
    engine.run_next()
    assert Board(db, root).get(second["id"])["status"] == "failed"
    assert db.one("SELECT status FROM missions WHERE id = ?", (mid2,))["status"] == "failed"


def test_proactive_decisions(setup: tuple[Database, Path, int]) -> None:
    from spectre.assistant.config import AssistantConfig
    from spectre.assistant.proactive import Proactive

    db, root, cid = setup
    Experiments(db, root).start(cid, "Une hypothèse sur le MRR", "mrr", days=1, now=NOW)
    board = Board(db, root)
    decision, _ = board.convene("acme", "Une décision importante ?")
    db.execute(
        "UPDATE decisions SET status = 'decided', review_at = ? WHERE id = ?",
        (NOW.isoformat(), decision["id"]),
    )
    notes: list[Any] = []
    proactive = Proactive(
        db, Rooted(root), AssistantConfig(), lambda *a: notes.append(a), fetch=lambda u: {}
    )  # type: ignore[arg-type]
    proactive.decisions(NOW + timedelta(days=2))
    assert notes[-1][0] == "experience" and board.get(decision["id"])["status"] == "reviewing"


def test_board_tools(setup: tuple[Database, Path, int]) -> None:
    db, root, cid = setup
    gate, ctx = Gate(db), tools.make_context(db, root, [str(root)])
    run = lambda tool, **args: tools.execute(gate, ctx, tool, args)  # noqa: E731
    assert run("list_decisions", company="acme") == "aucune décision"
    assert run("convene_board", company="acme", question="Passer à 29 € ?").startswith(
        "conseil réuni (décision #1, mission #1)"
    )
    assert "#1 [deliberating] Passer à 29 € ? → (en délibération)" in run("list_decisions")
    assert run("review_decision", decision_id=1).startswith("ÉCHEC : la décision #1 n'est pas")
    db.execute("UPDATE decisions SET status = 'decided', lesson = 'x' WHERE id = 1")
    assert run("review_decision", decision_id=1) == "réévaluation lancée (mission #2)"
    assert run("list_experiments", company="acme") == "aucune expérience"
    assert run(
        "start_experiment",
        company="acme",
        hypothesis="L'essai gratuit fait monter le MRR",
        metric="mrr",
    ).startswith("expérience #1 lancée")
    assert "#1 [running]" in run("list_experiments")
    assert run("stop_experiment", experiment_id=1) == "expérience #1 arrêtée"
    assert run("start_experiment", company="acme", hypothesis="x", metric="mrr").startswith("ÉCHEC")
    assert run("convene_board", company="nulle", question="Une question longue ?").startswith(
        "ÉCHEC"
    )


def test_board_api(api: Client, service: AssistantService) -> None:  # noqa: F811
    api.json("POST", "/api/assistant/company", {"name": "Acme"})
    service.saas().record(1, "mrr", 500, datetime.now().astimezone())
    status, body = api.json(
        "POST", "/api/assistant/company/1/decisions", {"question": "Passer à 29 € ?"}
    )
    assert status == 200 and body["result"].startswith("conseil réuni")
    data = api.json("GET", "/api/assistant/company/1/decisions")[1]
    assert data["decisions"][0]["memo"] == "" and data["metrics"] == ["arr", "mrr"]
    service.db.execute("UPDATE decisions SET status = 'decided' WHERE id = 1")
    assert api.json("GET", "/api/assistant/company/1/decisions")[1]["decisions"][0][
        "memo"
    ].startswith("# Conseil")
    assert api.json("POST", "/api/assistant/decisions/1/review", {})[1]["result"].startswith(
        "réévaluation"
    )
    status, body = api.json(
        "POST",
        "/api/assistant/company/1/experiments",
        {
            "hypothesis": "Le nouvel onboarding fait monter le MRR",
            "metric": "mrr",
            "direction": "up",
            "min_change": 5,
            "days": 7,
        },
    )
    assert body["result"].startswith("expérience #1 lancée")
    assert api.json("GET", "/api/assistant/company/1/decisions")[1]["experiments"][0][
        "text"
    ].startswith("« Le nouvel")
    assert (
        api.json("POST", "/api/assistant/experiments/1/stop", {})[1]["result"]
        == "expérience #1 arrêtée"
    )
    status, body = api.json(
        "POST", "/api/assistant/company/1/experiments", {"hypothesis": "x", "metric": "mrr"}
    )
    assert status == 400
