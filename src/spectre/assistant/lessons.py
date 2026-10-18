"""Lessons: what Spectre and its agents learn from their own mistakes.

A lesson is one short rule of conduct tied to an agent: « quand <situation>, <ce qu'il faut
faire> ». It comes from:
- a mission step that failed its check (Kaïto): after the mission, a review on a cheap engine
  reads the failed or retried steps and writes at most three lessons;
- a refusal: when the user denies an action and gives a reason, the agent that asked learns it;
- Spectre itself, when the user corrects it in conversation (`learn_lesson`).

Each agent's lessons go into its instructions (the most confirmed first). A lesson never relaxes
a rule, a validation or the gate: it only says how to avoid repeating an error. The same lesson
learned again is confirmed (`hits`), not duplicated; the user can archive one (`forget_lesson`).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Callable
from typing import Any

from spectre.assistant.db import Database, now_iso

MAX_TEXT = 300
MAX_PER_AGENT = 8  # lessons given to an agent with its instructions
MAX_FROM_REVIEW = 3
SIMILAR = 0.8  # this close to an existing lesson of the agent: the same lesson, confirmed

REVIEW = """\
Tu relis les étapes d'une mission qui ont ÉCHOUÉ à la vérification ou qu'il a fallu refaire, \
pour en tirer des LEÇONS : ce que l'agent doit faire autrement la prochaine fois pour ne pas \
refaire la même erreur. Une leçon est une règle de conduite courte et générale (pas un \
résultat ponctuel), au format « quand <situation>, <ce qu'il faut faire> ». Exemples : « quand \
un fichier est absent, le chercher avec list_dir avant de conclure » ; « quand un outil n'est \
pas trouvé, utiliser son chemin complet donné dans le brief ». Jamais de donnée personnelle, \
de secret ou d'adresse ; jamais une leçon qui assouplit une règle, contourne une validation \
ou élargit des droits. Si l'échec ne vient pas de l'agent (panne, quota, réseau) ou n'apprend \
rien, ne propose rien. Si Spectre a dû aider l'agent, la solution qui a marché est une bonne \
leçon.
Propose aussi, s'il y en a, des AMÉLIORATIONS qui rendraient l'agent plus performant : un \
outil à lui donner (logiciel libre, stable, de source officielle), une compétence à écrire, un \
chemin ou une information à mettre dans ses briefs, une étape à découper. Ce ne sont que des \
propositions : Spectre les soumettra à l'utilisateur.
Réponds UNIQUEMENT en JSON : {"lessons": [{"step": <numéro de l'étape>, "situation": "...", \
"lesson": "..."}], "improvements": [{"step": <numéro>, "idea": "..."}]} (au plus 3 de chaque, \
listes vides si rien)."""
# a lesson must not be a way to grant rights: these words are refused outright
FORBIDDEN = re.compile(
    r"(sans (demander|validation|autorisation|accord)|contourn|ignor\w* (la|les) (règle|validation)"
    r"|désactiv|bypass|mot de passe|clé api|token|phrase de récupération)",
    re.IGNORECASE,
)


class LessonError(ValueError):
    """A refused lesson (the message is for the user)."""


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def _clean(text: str) -> str:
    text = re.sub(r"https?://\S+", "", str(text))
    return " ".join(text.split())[:MAX_TEXT].strip()


class Lessons:
    def __init__(self, db: Database) -> None:
        self.db = db

    def learn(
        self,
        agent: str,
        situation: str,
        lesson: str,
        *,
        source: str = "",
        mission_id: int | None = None,
    ) -> dict[str, Any]:
        """Record a lesson, or confirm the same one already learned by this agent."""
        situation, lesson = _clean(situation), _clean(lesson)
        if not lesson:
            raise LessonError("une leçon a besoin d'un texte")
        if FORBIDDEN.search(f"{situation} {lesson}"):
            raise LessonError("une leçon ne peut ni assouplir une règle ni toucher aux secrets")
        agent = agent.strip() or "opus"
        wanted = _plain(f"{situation} {lesson}")
        for row in self.active(agent):
            known = _plain(f"{row['situation']} {row['lesson']}")
            if difflib.SequenceMatcher(None, wanted, known).ratio() >= SIMILAR:
                self.db.execute(
                    "UPDATE lessons SET hits = hits + 1, updated_at = ? WHERE id = ?",
                    (now_iso(), row["id"]),
                )
                return {**self.get(row["id"]), "outcome": "confirmed"}
        stamp = now_iso()
        lesson_id = self.db.execute(
            "INSERT INTO lessons(agent, situation, lesson, source, mission_id, created_at, "
            "updated_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (agent, situation, lesson, source, mission_id, stamp, stamp),
        )
        return {**self.get(lesson_id), "outcome": "created"}

    def get(self, lesson_id: int) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM lessons WHERE id = ?", (lesson_id,))
        if row is None:
            raise LessonError(f"leçon introuvable : #{lesson_id}")
        return row

    def active(self, agent: str | None = None) -> list[dict[str, Any]]:
        if agent is None:
            return self.db.all(
                "SELECT * FROM lessons WHERE status = 'active' ORDER BY hits DESC, updated_at DESC"
            )
        return self.db.all(
            "SELECT * FROM lessons WHERE status = 'active' AND agent = ? "
            "ORDER BY hits DESC, updated_at DESC",
            (agent,),
        )

    def forget(self, lesson_id: int) -> dict[str, Any]:
        self.get(lesson_id)
        self.db.execute(
            "UPDATE lessons SET status = 'forgotten', updated_at = ? WHERE id = ?",
            (now_iso(), lesson_id),
        )
        return self.get(lesson_id)

    def block(self, agent: str) -> str:
        """The lessons given to an agent with its instructions (empty when it has none)."""
        rows = self.active(agent)[:MAX_PER_AGENT]
        if not rows:
            return ""
        lines = "\n".join(
            f"- {r['situation']} : {r['lesson']}" if r["situation"] else f"- {r['lesson']}"
            for r in rows
        )
        return (
            "Leçons tirées de tes erreurs passées (applique-les ; elles ne changent jamais les "
            f"règles, les validations ni tes droits) :\n{lines}"
        )

    def listing(self, agent: str | None = None) -> str:
        from spectre.assistant.config import agent_name

        rows = self.active(agent)
        if not rows:
            return "aucune leçon apprise pour l'instant"
        return "\n".join(
            f"#{r['id']} [{agent_name(r['agent'])}, confirmée {r['hits']} fois] "
            f"{r['situation'] + ' : ' if r['situation'] else ''}{r['lesson']}"
            for r in rows[:60]
        )

    def review(
        self, mission: dict[str, Any], steps: list[dict[str, Any]], ask: Callable[[str, str], Any]
    ) -> dict[str, list[dict[str, Any]]]:
        """Lessons (recorded) and improvement ideas (only proposed) from the failed, retried
        or helped steps of a finished mission."""
        from spectre.assistant.brain import extract_json, failed

        missed = [(i, s) for i, s in enumerate(steps, 1) if not s.get("ok") or s.get("retried")]
        nothing: dict[str, list[dict[str, Any]]] = {"lessons": [], "improvements": []}
        if not missed:
            return nothing
        text = "\n\n".join(
            f"Étape {i} ({s.get('name') or s.get('key', '')}) : {s.get('step', '')}\n"
            f"Compte rendu : {str(s.get('result', ''))[:1200]}\n"
            f"Vérification : {'OK après une seconde tentative' if s.get('ok') else 'NON'} — "
            f"{s.get('first_note') or s.get('note', '')}"
            + (f"\nAide de Spectre : {str(s['advice'])[:800]}" if s.get("advice") else "")
            for i, s in missed
        )
        reply = ask(f"Mission : {mission.get('goal', '')}\n\n{text}", REVIEW)
        if failed(reply):
            return nothing
        try:
            data = extract_json(reply.text)
        except ValueError:
            return nothing
        found = data.get("lessons") or []
        learned = []
        by_number = dict(missed)
        ideas = []
        for item in (data.get("improvements") or [])[:MAX_FROM_REVIEW]:
            if not isinstance(item, dict):
                continue
            try:
                step = by_number.get(int(item.get("step", 0)))
            except (TypeError, ValueError):
                step = None
            idea = _clean(str(item.get("idea", "")))
            if step is not None and idea and not FORBIDDEN.search(idea):
                ideas.append({"agent": str(step.get("key") or "opus"), "idea": idea})
        for item in found[:MAX_FROM_REVIEW]:
            if not isinstance(item, dict):
                continue
            try:
                step = by_number.get(int(item.get("step", 0)))
            except (TypeError, ValueError):
                step = None
            if step is None:
                continue
            try:
                learned.append(
                    self.learn(
                        str(step.get("key") or "opus"),
                        str(item.get("situation", "")),
                        str(item.get("lesson", "")),
                        source="mission",
                        mission_id=mission.get("id"),
                    )
                )
            except LessonError:
                continue
        return {"lessons": learned, "improvements": ideas}

    def from_refusal(self, approval: dict[str, Any], agent: str, reason: str) -> dict[str, Any]:
        """The user denied an action and said why: the agent that asked remembers it."""
        what = f"{approval.get('tool', 'action')} ({str(approval.get('reason', ''))[:120]})"
        return self.learn(
            agent or "opus",
            f"quand je veux faire {what}",
            f"l'utilisateur a refusé en disant : « {reason.strip()} » ; en tenir compte",
            source="refus",
        )
