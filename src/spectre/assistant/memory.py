"""Memory that learns: atomic, dated, sourced facts with reinforcement and supersession.

A fact is (subject, predicate, value) in a closed category. Hearing it again reinforces it;
a new value for a single-valued predicate supersedes the old one (kept for history, never
deleted). The SQLite database is the truth; `mirror()` writes a read-only Markdown view.
"""

from __future__ import annotations

import builtins
import re
from pathlib import Path
from typing import Any, Final

from spectre.assistant.db import Database, now_iso

CATEGORIES: Final = (
    "identite",  # name, age, job, where the user lives
    "preference",  # likes, dislikes, tastes
    "habitude",  # routines, schedules
    "projet",  # ongoing work
    "objectif",  # goals
    "relation",  # people the user knows
    "lieu",  # places
    "evenement",  # dated events
    "persona",  # how Spectre should talk to the user (adaptive layer, never the core)
    "autre",
)
# Predicates that hold one value at a time: a new value supersedes the previous one.
MULTI_VALUED: Final = {"aime", "n'aime pas", "connait", "projet", "objectif", "habitude"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


class Memory:
    """Facts about the user and their world."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def remember(
        self,
        subject: str,
        predicate: str,
        value: str,
        *,
        category: str = "autre",
        confidence: float = 0.7,
        source_event: int | None = None,
    ) -> dict[str, Any]:
        """Store a fact; return it with `outcome` = created | reinforced | superseded."""
        subject, predicate, value = subject.strip(), predicate.strip(), value.strip()
        if not subject or not predicate or not value:
            raise ValueError("un fait a besoin d'un sujet, d'un prédicat et d'une valeur")
        if category not in CATEGORIES:
            category = "autre"
        confidence = min(1.0, max(0.0, confidence))
        stamp = now_iso()
        active = self.db.all(
            "SELECT * FROM facts WHERE lower(subject) = ? AND lower(predicate) = ? "
            "AND status = 'active'",
            (_norm(subject), _norm(predicate)),
        )
        same = next((f for f in active if _norm(f["value"]) == _norm(value)), None)
        if same:
            new_conf = min(1.0, same["confidence"] + (1 - same["confidence"]) * 0.3)
            self.db.execute(
                "UPDATE facts SET observations = observations + 1, confidence = ?, "
                "last_seen_at = ?, updated_at = ? WHERE id = ?",
                (new_conf, stamp, stamp, same["id"]),
            )
            return {**self.get(same["id"]), "outcome": "reinforced"}
        fact_id = self.db.execute(
            "INSERT INTO facts(subject, predicate, value, category, confidence, created_at, "
            "updated_at, last_seen_at, source_event) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (subject, predicate, value, category, confidence, stamp, stamp, stamp, source_event),
        )
        outcome = "created"
        if active and _norm(predicate) not in MULTI_VALUED:
            for old in active:
                self.db.execute(
                    "UPDATE facts SET status = 'superseded', superseded_by = ?, updated_at = ? "
                    "WHERE id = ?",
                    (fact_id, stamp, old["id"]),
                )
            outcome = "superseded"
        return {**self.get(fact_id), "outcome": outcome}

    def get(self, fact_id: int) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM facts WHERE id = ?", (fact_id,))
        if row is None:
            raise KeyError(fact_id)
        return row

    def recall(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Active facts matching `query` (full text, accents ignored), best first."""
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
        if not words:
            return self.list(limit=limit)
        match = " OR ".join(f'"{w}"*' for w in words)
        return self.db.all(
            "SELECT f.* FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid "
            "WHERE facts_fts MATCH ? AND f.status = 'active' "
            "ORDER BY bm25(facts_fts), f.confidence DESC LIMIT ?",
            (match, limit),
        )

    def list(
        self, *, category: str | None = None, status: str = "active", limit: int = 200
    ) -> list[dict[str, Any]]:
        if category:
            return self.db.all(
                "SELECT * FROM facts WHERE status = ? AND category = ? "
                "ORDER BY last_seen_at DESC LIMIT ?",
                (status, category, limit),
            )
        return self.db.all(
            "SELECT * FROM facts WHERE status = ? ORDER BY last_seen_at DESC LIMIT ?",
            (status, limit),
        )

    def forget(self, fact_id: int) -> dict[str, Any]:
        """Archive a fact at the user's request (kept out of recall and context)."""
        self.get(fact_id)
        self.db.execute(
            "UPDATE facts SET status = 'forgotten', updated_at = ? WHERE id = ?",
            (now_iso(), fact_id),
        )
        self.db.log_event("human_correction", "user", f"oublier le fait {fact_id}")
        return self.get(fact_id)

    def correct(self, fact_id: int, value: str) -> dict[str, Any]:
        """Replace a fact's value (the old version is kept as superseded)."""
        old = self.get(fact_id)
        event = self.db.log_event("human_correction", "user", f"{old['value']} -> {value}")
        new = self.remember(
            old["subject"],
            old["predicate"],
            value,
            category=old["category"],
            confidence=1.0,
            source_event=event,
        )
        if old["status"] == "active" and new["id"] != fact_id:
            self.db.execute(
                "UPDATE facts SET status = 'superseded', superseded_by = ?, updated_at = ? "
                "WHERE id = ?",
                (new["id"], now_iso(), fact_id),
            )
        return self.get(new["id"])

    def context_block(self, limit: int = 40) -> str:
        """Compact text of what Spectre knows, for the brain's system prompt."""
        facts = self.db.all(
            "SELECT * FROM facts WHERE status = 'active' "
            "ORDER BY (category = 'persona') DESC, confidence * observations DESC, "
            "last_seen_at DESC LIMIT ?",
            (limit,),
        )
        if not facts:
            return "(Spectre ne sait encore rien de l'utilisateur.)"
        return "\n".join(
            f"- [{f['category']}] {f['subject']} {f['predicate']} {f['value']} (#{f['id']})"
            for f in facts
        )

    def mirror(self, folder: Path) -> builtins.list[Path]:
        """Write a read-only Markdown view per category; return the files written."""
        folder.mkdir(parents=True, exist_ok=True)
        written = []
        for category in CATEGORIES:
            facts = self.list(category=category)
            path = folder / f"{category}.md"
            if not facts:
                path.unlink(missing_ok=True)
                continue
            lines = [
                f"# {category}",
                "",
                "> Vue en lecture seule. Pour corriger, demande-le à Spectre ou passe par "
                "l'onglet Mémoire.",
                "",
            ]
            lines += [
                f"- {f['subject']} **{f['predicate']}** {f['value']} "
                f"_(confiance {f['confidence']:.2f}, vu {f['observations']}×, #{f['id']})_"
                for f in facts
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            written.append(path)
        return written
