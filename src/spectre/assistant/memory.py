"""Memory that learns: atomic, dated, sourced facts with reinforcement and supersession.

A fact is (subject, predicate, value) in a closed category. Hearing it again reinforces it;
a new value for a single-valued predicate supersedes the old one (kept for history, never
deleted). The SQLite database is the truth; `mirror()` writes a read-only Markdown view.
"""

from __future__ import annotations

import builtins
import re
from datetime import datetime, timedelta
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


MEMORY_FACTS = 150  # facts given to the brain with each conversation (setting memory_facts)
MEMORY_CHARS = 45_000  # and at most this many characters, about 11 000 tokens
MAX_FACTS = 400  # bounds of the settings: a prompt that stays reasonable
MAX_CHARS = 120_000


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

    def compact(self, ask: Any, now: datetime) -> dict[str, Any]:
        """Merge duplicate facts and archive the ones that are over, as a review on a model
        proposes, within strict checks. Nothing is deleted: merged facts become `superseded`,
        archived ones `forgotten`, both restorable (`restore`)."""
        from spectre.assistant.brain import extract_json, failed

        facts = self.db.all("SELECT * FROM facts WHERE status = 'active' ORDER BY category, id")
        done: dict[str, Any] = {"merged": 0, "archived": 0, "refused": []}
        if len(facts) < COMPACT_FROM:
            return done
        by_id = {f["id"]: f for f in facts}
        listing = "\n".join(
            f"#{f['id']} [{f['category']}] {f['subject']} | {f['predicate']} | {f['value']} | "
            f"{str(f['last_seen_at'])[:10]}"
            for f in facts
            if not locked(f)
        )
        reply = ask(listing, COMPACTOR)
        if failed(reply):
            return done
        try:
            plan = extract_json(reply.text)
        except ValueError:
            return done
        touched: set[int] = set()
        for merge in (plan.get("merges") or [])[:MAX_MERGES]:
            try:
                keep = by_id[int(merge["keep"])]
                into = [by_id[int(i)] for i in merge.get("into") or []]
                value = " ".join(str(merge["value"]).split())
            except (KeyError, TypeError, ValueError):
                continue
            ids = {keep["id"], *(f["id"] for f in into)}
            if not into or len(ids) != len(into) + 1 or ids & touched or not value:
                continue
            why = check_merge(keep, into, value)
            if why:
                done["refused"].append(f"#{keep['id']} : {why}")
                continue
            merged = self.correct(keep["id"], value)
            for fact in into:
                self.db.execute(
                    "UPDATE facts SET status = 'superseded', superseded_by = ?, updated_at = ? "
                    "WHERE id = ?",
                    (merged["id"], now_iso(), fact["id"]),
                )
            touched |= ids
            done["merged"] += len(into)
        limit = (now - timedelta(days=ARCHIVE_AFTER_DAYS)).isoformat(timespec="seconds")
        for raw in (plan.get("archive") or [])[: MAX_ARCHIVES * 2]:
            try:
                fact = by_id[int(raw)]
            except (KeyError, TypeError, ValueError):
                continue
            if fact["id"] in touched or locked(fact) or str(fact["last_seen_at"]) >= limit:
                continue
            if done["archived"] >= MAX_ARCHIVES:
                break
            self.forget(fact["id"])
            touched.add(fact["id"])
            done["archived"] += 1
        return done

    def restore(self, fact_id: int) -> dict[str, Any]:
        """Bring back an archived or merged fact (nothing compaction does is final)."""
        fact = self.get(fact_id)
        if fact["status"] == "active":
            return fact
        self.db.execute(
            "UPDATE facts SET status = 'active', superseded_by = NULL, updated_at = ? WHERE id = ?",
            (now_iso(), fact_id),
        )
        self.db.log_event("human_correction", "user", f"restaurer le fait {fact_id}")
        return self.get(fact_id)

    def context_block(self, limit: int = 40, max_chars: int = MEMORY_CHARS) -> str:
        """Compact text of what Spectre knows, for the brain's system prompt: the most reliable
        facts first, up to `limit` facts and `max_chars` characters (the rest stays in memory,
        found with `recall`)."""
        limit = max(1, min(int(limit), MAX_FACTS))
        max_chars = max(2_000, min(int(max_chars), MAX_CHARS))
        facts = self.db.all(
            "SELECT * FROM facts WHERE status = 'active' "
            "ORDER BY (category = 'persona') DESC, confidence * observations DESC, "
            "last_seen_at DESC",
        )
        if not facts:
            return "(Spectre ne sait encore rien de l'utilisateur.)"
        lines: list[str] = []
        used = 0
        for f in facts[:limit]:
            line = f"- [{f['category']}] {f['subject']} {f['predicate']} {f['value']} (#{f['id']})"
            if lines and used + len(line) + 1 > max_chars:
                break
            lines.append(line)
            used += len(line) + 1
        if len(facts) > len(lines):
            lines.append(
                f"(+ {len(facts) - len(lines)} autre(s) souvenir(s) en mémoire : retrouve-les "
                "avec l'outil recall quand le sujet s'y prête.)"
            )
        return "\n".join(lines)

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


# ---- nightly compaction: merge duplicates, archive what is over, never delete ---------------

COMPACTOR = """\
Tu ranges la mémoire de Spectre sur l'utilisateur. On te donne ses souvenirs actifs, un par \
ligne : #id [catégorie] sujet | prédicat | valeur | vu le. Repère :
1. les DOUBLONS et les faits qui disent la même chose en plusieurs morceaux (même catégorie) : \
propose de les FUSIONNER en un seul fait, en gardant TOUS les détails (noms, dates, chiffres, \
nuances) — on n'enlève rien, on regroupe ;
2. les faits PÉRIMÉS : un état ponctuel dépassé (« ce soir », « objectif immédiat », une étape \
de projet remplacée par une plus récente qui la contient) : propose de les ARCHIVER.
Dans le doute, ne touche à rien. Ne fusionne jamais des faits de catégories différentes ni \
des personnes différentes.
Réponds UNIQUEMENT en JSON : {"merges": [{"keep": <id gardé>, "into": [<ids fusionnés dedans>], \
"value": "<la valeur fusionnée, complète>"}], "archive": [<ids périmés>]}"""
MAX_MERGES = 15  # per night
MAX_MERGED = 2_500  # characters of a merged fact: beyond, keep them apart
MAX_ARCHIVES = 5
ARCHIVE_AFTER_DAYS = 7  # a fact seen this week is not archived
COMPACT_FROM = 20  # below this many active facts, nothing to tidy
# never merged nor archived: the user's explicit rules and their confidences
LOCKED = re.compile(
    r"(exige|autoris|interdit|règle|veut que spectre|ne jamais|toujours|confiden|priv[ée]|secret)",
    re.IGNORECASE,
)
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def locked(fact: dict[str, Any]) -> bool:
    return bool(LOCKED.search(f"{fact['predicate']} {fact['value']}"))


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in NUMBER.findall(text)}


def check_merge(keep: dict[str, Any], into: list[dict[str, Any]], value: str) -> str | None:
    """Why a proposed merge is refused (None = it keeps everything that matters)."""
    group = [keep, *into]
    if any(locked(f) for f in group):
        return "fait protégé (règle ou confidence)"
    if len({f["category"] for f in group}) > 1:
        return "catégories différentes"
    missing = set().union(*(_numbers(f["value"]) for f in group)) - _numbers(value)
    if missing:
        return f"chiffres perdus : {', '.join(sorted(missing))}"
    if len(value) < 0.6 * max(len(f["value"]) for f in group):
        return "valeur fusionnée trop courte (détails perdus)"
    if len(value) > MAX_MERGED:
        return "valeur fusionnée trop longue (mieux vaut des souvenirs séparés)"
    return None
