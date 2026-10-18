"""Learning from mistakes (lessons, help for a stuck agent) and keeping the tools up to date."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import tools as tools_mod
from spectre.assistant import updates
from spectre.assistant.actions import ActionError
from spectre.assistant.brain import Reply
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate, Level
from spectre.assistant.lessons import LessonError, Lessons
from tests.test_assistant_brain import FakeCLI, _engine, _queue

WINGET = (
    "\r   - \rNom              ID                        Version  Disponible  Source\n"
    "---------------------------------------------------------------------------\n"
    "Docker Desktop   Docker.DockerDesktop      4.93.0   4.95.0      winget\n"
    "Python 3.14.6    Python.Python.3.14        3.14.6   3.14.7      winget\n"
    "OpenToonz 1.8.0  DWANGO.OpenToonz.Nightly  1.8.0    2024.05.04  winget\n"
    "3 mises à niveau disponibles.\n"
)
UV = "openfisca-core v44.7.1 [latest: 45.0.5]\n- openfisca\nruff v0.6.0 [latest: 0.7.1]\n"


@pytest.fixture
def db(tmp_path: Path) -> Any:
    database = Database(tmp_path / "a.db")
    yield database
    database.close()


# ---- lessons ----------------------------------------------------------------------------------


def test_learn_confirms_the_same_lesson(db: Database) -> None:
    lessons = Lessons(db)
    first = lessons.learn("mistral", "quand un outil manque", "utiliser son chemin complet")
    again = lessons.learn("mistral", "quand un outil manque", "utiliser son chemin complet.")
    assert first["outcome"] == "created" and again["outcome"] == "confirmed"
    assert lessons.get(first["id"])["hits"] == 2
    other = lessons.learn("chatgpt", "quand un outil manque", "utiliser son chemin complet")
    assert other["outcome"] == "created"  # another agent learns it for itself
    assert "Leçons tirées de tes erreurs" in lessons.block("mistral")
    assert lessons.block("simon") == ""
    assert "confirmée 2 fois" in lessons.listing("mistral")
    lessons.forget(first["id"])
    assert lessons.block("mistral") == "" and lessons.listing("mistral").startswith("aucune")
    with pytest.raises(LessonError, match="introuvable"):
        lessons.get(999)


def test_lessons_refuse_rules_and_secrets(db: Database) -> None:
    lessons = Lessons(db)
    for text in ("agir sans demander la validation", "contourner le portail", "noter le token"):
        with pytest.raises(LessonError, match="assouplir"):
            lessons.learn("opus", "quand c'est urgent", text)
    with pytest.raises(LessonError, match="texte"):
        lessons.learn("opus", "x", "  ")
    row = lessons.learn("", "voir https://exemple.org/x", "lire la doc " + "a" * 400)
    assert "https" not in row["situation"] and len(row["lesson"]) <= 300 and row["agent"] == "opus"


def test_review_turns_failed_steps_into_lessons_and_ideas(db: Database) -> None:
    lessons = Lessons(db)
    steps = [
        {"step": "lire", "ok": True, "result": "ok", "key": "sonnet"},
        {
            "step": "scanner",
            "ok": True,
            "retried": True,
            "first_note": "outil introuvable",
            "advice": "chemin complet de gitleaks",
            "result": "fait",
            "key": "mistral",
        },
    ]
    seen: list[str] = []

    def ask(prompt: str, system: str) -> Reply:
        seen.append(prompt)
        return Reply(
            json.dumps(
                {
                    "lessons": [
                        {
                            "step": 2,
                            "situation": "quand gitleaks manque",
                            "lesson": "chemin complet",
                        },
                        {"step": 9, "situation": "x", "lesson": "étape inconnue"},
                        {"step": 2, "situation": "y", "lesson": "sans demander la validation"},
                        "pas un objet",
                    ],
                    "improvements": [
                        {"step": 2, "idea": "donner à Syfer une fiche d'outil gitleaks"},
                        {"step": "?", "idea": "rien"},
                    ],
                }
            ),
            "s",
            False,
        )

    found = lessons.review({"id": 7, "goal": "audit"}, steps, ask)
    assert [x["lesson"] for x in found["lessons"]] == ["chemin complet"]
    assert found["lessons"][0]["agent"] == "mistral" and found["lessons"][0]["mission_id"] == 7
    assert found["improvements"] == [
        {"agent": "mistral", "idea": "donner à Syfer une fiche d'outil gitleaks"}
    ]
    assert "Aide de Spectre : chemin complet de gitleaks" in seen[0]
    assert "Étape 1" not in seen[0]  # only the steps that went wrong
    nothing = {"lessons": [], "improvements": []}
    assert lessons.review({}, [{"ok": True}], ask) == nothing
    assert lessons.review({}, steps, lambda p, s: Reply("pas de JSON", "s", False)) == nothing
    assert lessons.review({}, steps, lambda p, s: Reply("panne", "", True)) == nothing


def test_refusal_with_a_reason_becomes_a_lesson(db: Database, tmp_path: Path) -> None:
    ctx = tools_mod.make_context(db, tmp_path / "assistant", [str(tmp_path)])
    approval = db.execute(
        "INSERT INTO approvals(ts, tool, args, level, category, reason) "
        "VALUES('t', 'send_email', '{}', 4, 'external_send', 'envoyer le devis')"
    )
    db.execute("INSERT INTO approval_agents VALUES(?, 'cursor')", (approval,))
    tools_mod.deny(ctx, approval, "pas avant que je relise le devis")
    rows = Lessons(db).active("cursor")
    assert rows and "relise le devis" in rows[0]["lesson"] and rows[0]["source"] == "refus"
    second = db.execute(
        "INSERT INTO approvals(ts, tool, args, level, category, reason) "
        "VALUES('t', 'x', '{}', 4, 'external_send', 'r')"
    )
    tools_mod.deny(ctx, second, "")  # no reason: nothing to learn
    tools_mod.deny(
        ctx,
        db.execute(
            "INSERT INTO approvals(ts, tool, args, level, category, reason) "
            "VALUES('t', 'x', '{}', 4, 'external_send', 'r')"
        ),
        "donne-moi le mot de passe",
    )  # a refused lesson never breaks the refusal
    assert len(Lessons(db).active()) == 1


def test_lesson_tools(db: Database, tmp_path: Path) -> None:
    ctx = tools_mod.make_context(db, tmp_path / "assistant", [str(tmp_path)])
    assert "retenue" in tools_mod._learn_lesson(ctx, "quand on me corrige", "noter la correction")
    assert "confirmée" in tools_mod._learn_lesson(ctx, "quand on me corrige", "noter la correction")
    with pytest.raises(ActionError):
        tools_mod._learn_lesson(ctx, "x", "contourner la validation")
    ctx.agent = "mistral"
    tools_mod._learn_lesson(ctx, "quand nmap échoue", "vérifier la cible autorisée")
    assert "nmap" in tools_mod._lessons(ctx) and "corrige" not in tools_mod._lessons(ctx)
    ctx.agent = ""
    assert "corrige" in tools_mod._lessons(ctx) and "nmap" in tools_mod._lessons(ctx)
    assert "nmap" in tools_mod._lessons(ctx, "Syfer") and "corrige" not in tools_mod._lessons(
        ctx, "Syfer"
    )
    assert "archivée" in tools_mod._forget_lesson(ctx, 1)
    with pytest.raises(ActionError):
        tools_mod._forget_lesson(ctx, 99)
    registry = tools_mod.TOOLS
    assert registry["forget_lesson"].lead_only and registry["learn_lesson"].allowed("mistral")
    assert registry["update_tools"].lead_only and registry["tool_updates"].lead_only


def test_agent_lessons_reach_its_instructions(db: Database, tmp_path: Path) -> None:
    Lessons(db).learn("haiku", "quand un fichier manque", "le chercher avant de conclure")
    cli = FakeCLI(tmp_path, "fait", '{"ok": true}', "rapport")
    engine, _ = _engine(db, cli)
    _queue(db, "But", {"kind": "mission", "steps": ["unique"]})
    engine.run_next()
    assert "le chercher avant de conclure" in cli.calls[0]["system"]


def test_mission_lessons_are_announced(db: Database, tmp_path: Path) -> None:
    review = json.dumps(
        {
            "lessons": [{"step": 1, "situation": "quand x", "lesson": "faire y"}],
            "improvements": [{"step": 1, "idea": "une fiche d'outil"}],
        }
    )
    cli = FakeCLI(
        tmp_path,
        "rien",
        '{"ok": false, "note": "vide"}',
        "toujours rien",
        '{"ok": false, "note": "vide"}',
        "Fais y.",
        "fait",
        '{"ok": true}',
        "rapport",
        review,
    )
    engine, notes = _engine(db, cli)
    engine.learn = True
    _queue(db, "But", {"kind": "mission", "steps": ["unique"]})
    engine.run_next()
    kinds = [n[0] for n in notes]
    assert "apprentissage" in kinds and "amelioration" in kinds
    assert Lessons(db).active("haiku")[0]["lesson"] == "faire y"
    assert "avant toute mise en place" in next(n[2] for n in notes if n[0] == "amelioration")


# ---- tool updates -----------------------------------------------------------------------------


class Runner:
    def __init__(self, outputs: dict[str, str], code: int = 0) -> None:
        self.outputs, self.code, self.calls = outputs, code, []

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        key = "winget" if "upgrade" in cmd and "--id" not in cmd else cmd[1]
        return subprocess.CompletedProcess(cmd, self.code, self.outputs.get(key, ""), "")


@pytest.fixture
def managers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updates.shutil, "which", lambda name: name)


def test_parse_and_summary(managers: None) -> None:
    rows = updates.parse_winget(WINGET)
    assert [r["id"] for r in rows] == [
        "Docker.DockerDesktop",
        "Python.Python.3.14",
        "DWANGO.OpenToonz.Nightly",
    ]
    assert rows[0]["available"] == "4.95.0" and rows[0]["source"] == "winget"
    assert updates.parse_winget("rien") == []
    assert [r["id"] for r in updates.parse_uv(UV)] == ["openfisca-core", "ruff"]
    items = updates.available(Runner({"winget": WINGET, "tool": UV}))
    text = updates.summary(items)
    assert text.startswith("5 mise(s) à jour")
    assert "Python.Python.3.14) 3.14.6 → 3.14.7 — tenu à sa version" in text
    assert "Nightly) 1.8.0 → 2024.05.04 — version non stable" in text
    assert updates.summary([]) == "tous les outils sont à jour"


def test_upgrade(managers: None, db: Database, tmp_path: Path) -> None:
    ctx = tools_mod.make_context(db, tmp_path / "assistant", [str(tmp_path)])
    ctx.runner = Runner({"winget": WINGET, "tool": UV})
    out = updates.upgrade(ctx, "tout")
    assert "Docker Desktop 4.95.0" in out and "ruff 0.7.1" in out
    upgraded = [c for c in ctx.runner.calls if "--id" in c or c[1:3] == ["tool", "upgrade"]]
    assert upgraded[0][:4] == ["winget", "upgrade", "--id", "Docker.DockerDesktop"]
    assert not any("Python.Python.3.14" in c or "DWANGO.OpenToonz.Nightly" in c for c in upgraded)
    assert ["uv", "tool", "upgrade", "openfisca-core"] in upgraded
    ctx.runner = Runner({"winget": WINGET, "tool": UV})
    assert updates.upgrade(ctx, "ruff") == "mis à jour : ruff 0.7.1"
    with pytest.raises(ActionError, match="tenu à sa version"):
        updates.upgrade(ctx, "Python.Python.3.14")
    with pytest.raises(ActionError, match="pas de mise à jour"):
        updates.upgrade(ctx, "inconnu")
    with pytest.raises(ActionError, match="précise"):
        updates.upgrade(ctx, " ")
    ctx.runner = Runner({"winget": WINGET, "tool": UV}, code=1)
    assert "échec : Docker Desktop" in updates.upgrade(ctx, "Docker.DockerDesktop")
    ctx.runner = Runner({})
    assert updates.upgrade(ctx, "tout") == "rien à mettre à jour"
    assert updates.listing(ctx) == "tous les outils sont à jour"


def test_update_tools_is_gated(db: Database) -> None:
    gate = Gate(db)
    assert tools_mod.TOOLS["update_tools"].level == Level.CRITICAL
    assert gate.decide(Level.CRITICAL, "install_agent_tool").verdict == "approval"


def test_weekly_check_tells_the_user(managers: None, db: Database, monkeypatch: Any) -> None:
    from spectre.assistant.config import AssistantConfig
    from spectre.assistant.proactive import Proactive

    notes: list[tuple[str, str, str]] = []
    proactive = Proactive(db, None, AssistantConfig(), lambda *a: notes.append(a))  # type: ignore[arg-type]
    monkeypatch.setattr(updates, "available", lambda runner=None: updates.parse_winget(WINGET))
    now = datetime(2026, 10, 18, 9).astimezone()
    proactive.tool_updates(now, background=False)
    assert notes and notes[0][0] == "mises_a_jour" and "3 mise(s)" in notes[0][1]
    proactive.tool_updates(now + timedelta(days=3), background=False)
    assert len(notes) == 1  # once a week
    monkeypatch.setattr(updates, "available", lambda runner=None: [])
    proactive.tool_updates(now + timedelta(days=8), background=False)
    assert len(notes) == 1  # nothing to update: nothing to say
    assert updates.due("pas une date", now)
