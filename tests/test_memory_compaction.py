"""Nightly tidying of Spectre's memory: merge duplicates, archive what is over, delete nothing."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import memory as memory_mod
from spectre.assistant import tools as tools_mod
from spectre.assistant.brain import Reply
from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database
from spectre.assistant.memory import Memory, check_merge, locked
from spectre.assistant.proactive import Proactive

NOW = datetime(2026, 10, 19, 3).astimezone()


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "spectre.db")
    yield database
    database.close()


def _filled(db: Database) -> dict[str, int]:
    mem = Memory(db)
    ids = {
        "lever": mem.remember("Olivier", "se lève à", "4 h", category="habitude")["id"],
        "lever2": mem.remember("Olivier", "réveil", "4 h en semaine", category="habitude")["id"],
        "dormir": mem.remember("Olivier", "ce soir", "dormir tôt", category="objectif")["id"],
        "regle": mem.remember(
            "Olivier", "exige son autorisation pour", "tout paiement", category="preference"
        )["id"],
        "ville": mem.remember("Olivier", "habite", "Favières", category="lieu")["id"],
    }
    for i in range(memory_mod.COMPACT_FROM):
        mem.remember("Olivier", f"détail {i}", f"valeur {i}", category="autre")
    old = (NOW - timedelta(days=10)).isoformat(timespec="seconds")
    db.execute("UPDATE facts SET last_seen_at = ?", (old,))
    return ids


def _ask(plan: dict[str, Any], seen: list[str] | None = None) -> Any:
    def ask(prompt: str, system: str) -> Reply:
        if seen is not None:
            seen.append(prompt)
        return Reply(json.dumps(plan), "s", False)

    return ask


def test_merges_and_archives_without_deleting(db: Database) -> None:
    ids = _filled(db)
    seen: list[str] = []
    plan = {
        "merges": [
            {"keep": ids["lever"], "into": [ids["lever2"]], "value": "4 h, en semaine"},
            {"keep": ids["ville"], "into": [ids["dormir"]], "value": "Favières, dormir tôt"},
        ],
        "archive": [ids["dormir"], ids["regle"]],
    }
    done = Memory(db).compact(_ask(plan, seen), NOW)
    assert done["merged"] == 1 and done["archived"] == 1
    assert "catégories différentes" in done["refused"][0]
    assert "tout paiement" not in seen[0]  # a rule is not even shown to the tidier
    statuses = {r["id"]: r["status"] for r in db.all("SELECT id, status FROM facts")}
    assert statuses[ids["lever"]] == statuses[ids["lever2"]] == "superseded"
    assert statuses[ids["dormir"]] == "forgotten" and statuses[ids["regle"]] == "active"
    merged = db.one("SELECT * FROM facts WHERE value = '4 h, en semaine'")
    assert merged and merged["status"] == "active"
    assert db.one("SELECT COUNT(*) AS n FROM facts")["n"] == 5 + memory_mod.COMPACT_FROM + 1
    restored = Memory(db).restore(ids["dormir"])  # nothing is final
    assert restored["status"] == "active" and Memory(db).restore(ids["dormir"]) == restored
    assert "restauré" in tools_mod._restore_fact(
        tools_mod.make_context(db, db.path.parent, []), ids["lever2"]
    )


def test_checks_keep_every_detail() -> None:
    fact = {
        "category": "projet",
        "predicate": "étape",
        "value": "rapport complet du 10/10/2026, 31 958 octets, fin non lue",
    }
    other = {"category": "projet", "predicate": "suite", "value": "relu le 11/10"}
    assert (
        check_merge(
            fact,
            [other],
            "rapport complet du 10/10/2026 (31 958 octets, fin non lue), relu le 11/10",
        )
        is None
    )
    assert "chiffres perdus : 11" in str(check_merge(fact, [other], "rapport 10/10/2026 31 958"))
    assert "trop courte" in str(check_merge(fact, [other], "10 10 2026 31 958 11"))
    assert "trop longue" in str(
        check_merge(fact, [other], "10 10 2026 31 958 11 " + "x" * memory_mod.MAX_MERGED)
    )
    secret = {"category": "persona", "predicate": "confidence (privée)", "value": "x"}
    assert locked(secret) and "protégé" in str(check_merge(secret, [other], "x"))


def test_recent_facts_and_limits(db: Database) -> None:
    ids = _filled(db)
    db.execute(
        "UPDATE facts SET last_seen_at = ? WHERE id = ?",
        (NOW.isoformat(timespec="seconds"), ids["dormir"]),
    )
    rows = db.all("SELECT id FROM facts WHERE category = 'autre'")
    plan = {"archive": [ids["dormir"], *[r["id"] for r in rows]], "merges": "pas une liste"}
    done = Memory(db).compact(_ask(plan), NOW)
    assert done["archived"] == memory_mod.MAX_ARCHIVES  # at most five a night
    assert db.one("SELECT status FROM facts WHERE id = ?", (ids["dormir"],))["status"] == "active"
    broken = Memory(db).compact(lambda p, s: Reply("pas de JSON", "s", False), NOW)
    assert broken == {"merged": 0, "archived": 0, "refused": []}
    assert Memory(db).compact(lambda p, s: Reply("panne", "", True), NOW)["merged"] == 0
    odd = {"merges": [{"keep": 9999, "into": [1]}, {"keep": 1, "into": []}, "x"], "archive": ["?"]}
    assert Memory(db).compact(_ask(odd), NOW)["merged"] == 0


def test_too_few_facts_nothing_to_tidy(db: Database) -> None:
    Memory(db).remember("Olivier", "habite", "Favières", category="lieu")
    asked: list[str] = []
    assert Memory(db).compact(_ask({}, asked), NOW)["merged"] == 0 and not asked


class RootCLI:
    def __init__(self, root: Path, reply: str) -> None:
        self.root = root
        self.workspace = root / "workspace"
        self.reply = reply
        self.models: list[str | None] = []

    def ask(self, prompt: str, *, system: str, model: str | None = None, **_: Any) -> Reply:
        self.models.append(model)
        return Reply(self.reply, "s", False)


def test_nightly_backup_then_tidy(db: Database, tmp_path: Path) -> None:
    ids = _filled(db)
    plan = {"merges": [{"keep": ids["lever"], "into": [ids["lever2"]], "value": "4 h, en semaine"}]}
    cli = RootCLI(tmp_path, json.dumps(plan))
    notes: list[tuple[str, str, str]] = []
    proactive = Proactive(db, cli, AssistantConfig(), lambda *a: notes.append(a))  # type: ignore[arg-type]
    folder = tmp_path / "sauvegardes"
    folder.mkdir()
    for day in range(1, 10):  # old copies: only the last seven are kept
        (folder / f"memoire-2026-09-{day:02d}.db").write_bytes(b"")
    done = proactive.compact_memory(NOW)
    assert done["merged"] == 1 and cli.models == ["sonnet"]
    backups = sorted(p.name for p in folder.glob("memoire-*.db"))
    assert len(backups) == 7 and backups[-1] == "memoire-2026-10-19.db"
    copy = Database(folder / "memoire-2026-10-19.db")  # the copy holds the memory before tidying
    assert copy.one("SELECT status FROM facts WHERE id = ?", (ids["lever2"],))["status"] == "active"
    copy.close()
    assert notes[-1][1] == "Mémoire rangée cette nuit" and "Rien n'est effacé" in notes[-1][2]
    assert Proactive(db, None, AssistantConfig(), print).compact_memory(NOW)["merged"] == 0  # type: ignore[arg-type]

    def boom(*_: Any, **__: Any) -> Reply:
        raise RuntimeError("panne")

    cli.ask = boom  # type: ignore[method-assign]
    assert proactive.compact_memory(NOW)["merged"] == 0  # never breaks the night
