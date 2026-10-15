"""Learning: proposed and learned skills, the curator, conversation search, restore points."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import actions, tools
from spectre.assistant.brain import Brain, Reply
from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate
from spectre.assistant.learning import (
    Learning,
    SkillError,
    mark_mission,
    mission_changes,
    parse,
    render,
    search_history,
)
from spectre.assistant.missions import MissionEngine
from spectre.assistant.service import AssistantService
from tests.test_assistant_agents import _queue
from tests.test_assistant_engines import Rooted
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone(timedelta(hours=2)))
GUIDE = "## Étapes\n1. Lister les concurrents.\n2. Relever leurs prix publics.\n3. Comparer."


@pytest.fixture
def learning(tmp_path: Path) -> Learning:
    root = tmp_path / "assistant"
    return Learning(Database(root / "spectre.db"), root)


# ---- skills --------------------------------------------------------------------------------------


def test_propose_approve_read(learning: Learning) -> None:
    row = learning.propose(
        "Étude de prix", "Comparer les prix des concurrents d'un SaaS", GUIDE, "mission #3"
    )
    assert row["name"] == "etude-de-prix" and row["status"] == "pending" and row["previous"] == ""
    assert learning.skills() == [] and learning.catalogue() == ""
    with pytest.raises(SkillError, match="attend déjà"):
        learning.propose("etude-de-prix", "Autre description assez longue", GUIDE)
    approved = learning.approve(row["id"])
    assert approved["status"] == "approved"
    text = learning.path("etude-de-prix").read_text(encoding="utf-8")
    assert (
        text.startswith("---\nname: etude-de-prix\ndescription: Comparer les prix")
        and GUIDE in text
    )
    assert learning.catalogue() == "- etude-de-prix : Comparer les prix des concurrents d'un SaaS"
    assert learning.read("Étude de prix") == text
    assert learning.skills()[0]["uses"] == 1
    with pytest.raises(SkillError, match="déjà traitée"):
        learning.approve(row["id"])
    # an update keeps the previous version
    update = learning.propose(
        "etude-de-prix", "Comparer les prix, version enrichie", GUIDE + "\n4. Conclure."
    )
    assert update["previous"] == text
    learning.approve(update["id"])
    assert len(list((learning.dir / ".history").glob("etude-de-prix-*.md"))) == 1
    rejected = learning.reject(
        learning.propose("autre-chose", "Une description assez longue", GUIDE)["id"]
    )
    assert rejected["status"] == "rejected" and not learning.path("autre-chose").exists()
    with pytest.raises(SkillError, match="déjà traitée"):
        learning.reject(rejected["id"])
    with pytest.raises(SkillError, match="introuvable"):
        learning.proposal(999)
    with pytest.raises(SkillError, match="inconnue ; apprises : etude-de-prix"):
        learning.read("nope")
    assert [p["name"] for p in learning.proposals("rejected")] == ["autre-chose"]


@pytest.mark.parametrize(
    ("name", "description", "content", "error"),
    [
        ("ab", "Une description assez longue", GUIDE, "nom de 3 à 50"),
        ("bon-nom", "court", GUIDE, "description"),
        ("bon-nom", "Une description assez longue", "trop court", "contenu"),
        ("bon-nom", "Une description assez longue", GUIDE + " sk_live_ABCDEFGH1234", "secret"),
        ("bon-nom", "Une description assez longue", GUIDE + "\n-----BEGIN PRIVATE KEY", "secret"),
    ],
)
def test_propose_refused(
    learning: Learning, name: str, description: str, content: str, error: str
) -> None:
    with pytest.raises(SkillError, match=error):
        learning.propose(name, description, content)


def test_render_and_parse() -> None:
    text = render("x-y", "Quand faire x", "---\nname: old\n---\nCorps")
    assert parse(text) == ("Quand faire x", "Corps")
    assert parse("pas de frontmatter") == ("", "pas de frontmatter")


def test_review(learning: Learning) -> None:
    mission = {"id": 4, "goal": "Comparer les prix"}
    skill = {
        "name": "etude-prix",
        "description": "Comparer les prix des concurrents",
        "content": GUIDE,
    }
    seen: list[tuple[str, str]] = []

    def ask(answer: Any) -> Any:
        def call(prompt: str, system: str) -> Reply:
            seen.append((prompt, system))
            return answer if isinstance(answer, Reply) else Reply(answer, "", False)

        return call

    proposal = learning.review(mission, "Rapport détaillé", ask(json.dumps({"skill": skill})))
    assert proposal is not None and proposal["source"] == "mission #4"
    assert (
        "Mission #4 : Comparer les prix" in seen[0][0]
        and "Compétences existantes : aucune" in seen[0][1]
    )
    assert learning.review(mission, "r", ask('{"skill": null}')) is None
    assert learning.review(mission, "r", ask("pas de JSON")) is None
    assert learning.review(mission, "r", ask(Reply("panne", "", True))) is None
    assert (
        learning.review(mission, "r", ask(json.dumps({"skill": {"name": "x"}}))) is None
    )  # invalid


def test_curator(learning: Learning) -> None:
    for name in ("ancienne", "vieillissante", "epinglee", "recente"):
        learning.approve(learning.propose(name, "Une description assez longue", GUIDE)["id"])
    stamp = {"ancienne": 130, "vieillissante": 70, "epinglee": 200, "recente": 5}
    for name, days in stamp.items():
        learning.db.execute(
            "UPDATE skill_usage SET last_used = ? WHERE name = ?",
            ((NOW - timedelta(days=days)).isoformat(), name),
        )
    learning.pin("epinglee")
    copied = learning.dir / "copiee" / "SKILL.md"  # added by hand: no usage yet
    copied.parent.mkdir(parents=True)
    copied.write_text(render("copiee", "Copiée à la main", GUIDE), encoding="utf-8")
    assert learning.curate(NOW) == {"stale": ["vieillissante"], "archived": ["ancienne"]}
    states = {s["name"]: s["state"] for s in learning.skills()}
    assert states == {
        "copiee": "active",
        "epinglee": "active",
        "recente": "active",
        "vieillissante": "obsolète",
    }
    assert [s["name"] for s in learning.skills(archived=True)] == ["ancienne"]
    assert learning.curate(NOW) == {"stale": [], "archived": []}  # nothing twice
    learning.restore("ancienne")
    assert "ancienne" in [s["name"] for s in learning.skills()]
    for call, error in [
        (lambda: learning.restore("ancienne"), "aucune compétence archivée"),
        (lambda: learning.archive("nope"), "inconnue"),
        (lambda: learning.pin("nope"), "inconnue"),
    ]:
        with pytest.raises(SkillError, match=error):
            call()
    learning.archive("recente")
    learning.approve(learning.propose("recente", "Une nouvelle description", GUIDE)["id"])
    with pytest.raises(SkillError, match="active s'appelle déjà"):
        learning.restore("recente")
    learning.archive("recente")  # replaces the older archived copy
    assert [s["name"] for s in learning.skills(archived=True)] == ["recente"]


# ---- search and restore points -------------------------------------------------------------------


def test_search_history(tmp_path: Path) -> None:
    path = tmp_path / "spectre.db"
    db = Database(path)
    db.log_event("utterance", "user", "Quel prix pour la bêta payante ?")
    db.log_event("reply", "spectre", "Je propose 19 € par mois pour la beta.")
    db.log_event("action", "spectre", "prix ignoré : une action")
    db.execute(
        "INSERT INTO missions(ts, goal, status, updated_at, report) VALUES(?, ?, 'done', ?, ?)",
        ("t", "Étude des prix", "2026-10-14", "rapport"),
    )
    found = search_history(db, "beta")
    assert [r["source"] for r in found] == ["spectre", "user"]  # accents ignored, newest first
    assert "«beta»" in found[0]["excerpt"] or "«bêta»" in found[1]["excerpt"]
    assert [r["kind"] for r in search_history(db, "prix")] == ["utterance", "mission"]
    assert search_history(db, "  !! ") == []
    db.close()
    # an older database: its conversations get indexed once, at start
    raw = Database(path)
    raw.execute("INSERT INTO events_fts(events_fts) VALUES('delete-all')")
    raw.close()
    assert len(search_history(Database(path), "prix")) == 2


def test_restore_points(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    ctx = tools.make_context(db, root, [str(tmp_path)])
    before = tmp_path / "avant.txt"
    before.write_text("avant", encoding="utf-8")
    actions.write_file(ctx, str(tmp_path / "hors-mission.txt"), "x")
    mark_mission(db, 7, "from")
    actions.write_file(ctx, str(tmp_path / "nouveau.txt"), "créé")
    actions.write_file(ctx, str(before), "après")
    mark_mission(db, 7, "from")  # a resumed mission keeps its first mark
    mark_mission(db, 7, "to")
    actions.write_file(ctx, str(tmp_path / "apres-mission.txt"), "y")
    assert len(mission_changes(db, 7)) == 2 and mission_changes(db, 8) == []
    result = actions.rollback_mission(ctx, 7)
    assert result.startswith("mission #7 ramenée à son point de départ")
    assert before.read_text(encoding="utf-8") == "avant" and not (tmp_path / "nouveau.txt").exists()
    assert (tmp_path / "hors-mission.txt").exists() and (tmp_path / "apres-mission.txt").exists()
    assert (
        actions.rollback_mission(ctx, 7)
        == "aucun changement de fichier à annuler pour la mission #7"
    )
    assert actions.undo_last(ctx, 1) == f"fichier créé supprimé : {tmp_path / 'apres-mission.txt'}"


# ---- missions, brain, tools ----------------------------------------------------------------------


def test_mission_learns(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    learning = Learning(db, root)
    learning.approve(
        learning.propose("etude-prix", "Comparer les prix des concurrents", GUIDE)["id"]
    )
    skill = {
        "name": "veille-concurrents",
        "description": "Suivre les concurrents chaque mois",
        "content": GUIDE,
    }
    cli = Rooted(root, "fait", '{"ok": true}', "rapport", json.dumps({"skill": skill}))
    notes: list[Any] = []
    engine = MissionEngine(db, cli, lambda *a: notes.append(a), verifier_model="haiku")  # type: ignore[arg-type]
    engine.learn = True
    mid = _queue(db, {"kind": "mission", "steps": ["chercher"]})
    engine.run_next()
    assert (
        "Compétences apprises" in cli.calls[0]["system"]
        and "- etude-prix :" in cli.calls[0]["system"]
    )
    assert (
        cli.calls[3]["model"] == "haiku"
        and "Compétences existantes : etude-prix" in cli.calls[3]["system"]
    )
    assert notes[-1][1] == "Compétence proposée : veille-concurrents"
    assert json.loads(db.get_kv(f"mission_undo_{mid}")).keys() == {"from", "to"}
    # a failing review never breaks the mission
    engine.learning_model = "lmstudio:x"
    engine.engines.agents["http"] = type(
        "Boom", (), {"ask": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))}
    )()
    cli.replies = ["fait", '{"ok": true}', "rapport"]
    mid = _queue(db, {"kind": "mission", "steps": ["encore"]})
    engine.run_next()
    assert db.one("SELECT status FROM missions WHERE id = ?", (mid,))["status"] == "done"


def test_brain_sees_learned_skills(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    learning = Learning(db, root)
    learning.approve(learning.propose("devis", "Préparer un devis pour un client", GUIDE)["id"])
    prompt = Brain(db, Rooted(root), AssistantConfig()).system_prompt("text")
    assert "Compétences que tu as apprises" in prompt and "- devis : Préparer un devis" in prompt


def test_learning_tools(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    database = Database(root / "spectre.db")
    gate, ctx = Gate(database), tools.make_context(database, root, [str(tmp_path)])
    run = lambda tool, **args: tools.execute(gate, ctx, tool, args)  # noqa: E731
    assert run(
        "propose_skill", name="Devis", description="Préparer un devis client", content=GUIDE
    ).startswith("compétence « devis » proposée : elle attend la validation")
    assert run("skill", name="devis").startswith("ÉCHEC : compétence « devis » inconnue")
    Learning(database, root).approve(1)
    assert "Préparer un devis client" in run("skill", name="devis")
    assert "mise à jour" in run(
        "propose_skill", name="devis", description="Version enrichie du devis", content=GUIDE
    )
    assert run("propose_skill", name="x", description="d", content="c").startswith("ÉCHEC")
    database.log_event("utterance", "user", "on parlait du devis pour Acme")
    assert "(l'utilisateur) : on parlait du «devis»" in run("search_history", query="devis")
    assert run("search_history", query="licorne") == "rien trouvé dans les conversations passées"
    assert run("rollback_mission", mission_id=1).startswith("EN ATTENTE DE VALIDATION")


def test_curator_tick(tmp_path: Path) -> None:
    from spectre.assistant.proactive import Proactive

    root = tmp_path / "assistant"
    database = Database(root / "spectre.db")
    learning = Learning(database, root)
    learning.approve(learning.propose("vieille", "Une description assez longue", GUIDE)["id"])
    database.execute(
        "UPDATE skill_usage SET last_used = ?", ((NOW - timedelta(days=200)).isoformat(),)
    )
    notes: list[Any] = []
    proactive = Proactive(
        database, Rooted(root), AssistantConfig(), lambda *a: notes.append(a), fetch=lambda u: {}
    )  # type: ignore[arg-type]
    assert proactive.curate(NOW) == {"stale": [], "archived": ["vieille"]}
    assert notes[-1][1] == "Compétences archivées" and "vieille" in notes[-1][2]
    bare = Proactive(database, object(), AssistantConfig(), print, fetch=lambda u: {})  # type: ignore[arg-type]
    assert bare.curate(NOW) == {"stale": [], "archived": []}


def test_learning_api(api: Client, service: AssistantService, home: Path) -> None:  # noqa: F811
    learning = service.learning()
    learning.propose("devis", "Préparer un devis client", GUIDE)
    state = api.json("GET", "/api/assistant/learning")[1]
    assert [p["name"] for p in state["proposals"]] == ["devis"] and state["learn"] is True
    assert service.missions.learn is True
    assert (
        api.json("POST", "/api/assistant/learning/proposals/1/approve", {})[1]["status"]
        == "approved"
    )
    assert api.json("POST", "/api/assistant/learning/proposals/1/reject", {})[0] == 400
    assert api.json("POST", "/api/assistant/learning/proposals/1/maybe", {})[0] == 404
    assert (
        api.json("POST", "/api/assistant/learning/skills/devis/pin", {})[1]["skills"][0]["pinned"]
        is True
    )
    assert (
        api.json("POST", "/api/assistant/learning/skills/devis/unpin", {})[1]["skills"][0]["pinned"]
        is False
    )
    assert (
        api.json("POST", "/api/assistant/learning/skills/devis/archive", {})[1]["archived"][0][
            "name"
        ]
        == "devis"
    )
    assert (
        api.json("POST", "/api/assistant/learning/skills/devis/restore", {})[1]["skills"][0]["name"]
        == "devis"
    )
    assert api.json("POST", "/api/assistant/learning/skills/devis/explode", {})[0] == 404
    service.db.log_event("utterance", "user", "parlons du devis")
    assert api.json("GET", "/api/assistant/search?q=devis")[1][0]["source"] == "user"
    # a mission's restore point, from the Missions view
    mid = _queue(service.db, {"kind": "mission", "steps": ["x"]})
    mark_mission(service.db, mid, "from")
    actions.write_file(service.ctx, str(home / "fait.txt"), "x")
    mark_mission(service.db, mid, "to")
    assert api.json("GET", "/api/assistant/missions")[1][0]["changes"] == 1
    result = api.json("POST", f"/api/assistant/missions/{mid}/rollback", {})[1]["result"]
    assert result.startswith(f"mission #{mid} ramenée") and not (home / "fait.txt").exists()
    assert service.chat("/model apprentissage sonnet").startswith("C'est fait : apprentissage")
    assert service.missions.learning_model == "sonnet"
    assert service.chat("/model apprentissage vérificateur").endswith("sur le cerveau.")
    assert service.config.learning_model == ""
