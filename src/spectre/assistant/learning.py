"""Learning: skills Spectre proposes from its own work, a curator that ages them, a search over
past conversations, and per-mission restore points.

Skills (Hermes-style `SKILL.md`, in `~/.spectre/assistant/skills/<name>/SKILL.md`):
- after a mission succeeds, a review on a cheap engine (`learning_model`, empty = the verifier)
  reads its report and may propose a reusable procedure; the brain can propose one too when the
  user teaches it something (`propose_skill`);
- nothing is written without the user's approval; an approved update keeps the previous version
  in `skills/.history/`;
- the brain and mission agents see the catalogue (name + description) and read a skill with the
  `skill` tool, which counts its uses.

The curator never deletes: a skill unused for STALE_DAYS becomes « obsolète », for ARCHIVE_DAYS
it moves to `skills/.archive/` (restorable); pinned skills are never touched.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from spectre.assistant.db import Database, now_iso

NAME = re.compile(r"[a-z0-9][a-z0-9-]{2,49}")
MAX_DESCRIPTION = 300
MAX_CONTENT = 20_000
STALE_DAYS = 60
ARCHIVE_DAYS = 120
CATALOGUE_MAX = 40

REVIEW = """\
Tu relis une mission que Spectre vient de terminer, pour en tirer une COMPÉTENCE réutilisable : \
une méthode, des étapes, des vérifications, des pièges à éviter, utiles la prochaine fois qu'une \
mission semblable arrivera. Ne propose rien si la mission était banale, unique ou ratée, ou si \
une compétence existante la couvre déjà (tu peux alors proposer de l'enrichir sous le même \
nom). Jamais de donnée personnelle, de secret, de clé ni de résultat ponctuel : seulement la \
méthode. Réponds UNIQUEMENT par un objet JSON : {{"skill": null}} ou {{"skill": {{"name": \
"nom-en-minuscules-avec-tirets", "description": "quand l'utiliser, en une phrase", "content": \
"le guide en Markdown"}}}}.

Compétences existantes : {existing}"""


class SkillError(ValueError):
    """A refused skill (the message is for the user)."""


def slug(name: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", name.strip().lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:50]


def render(name: str, description: str, content: str) -> str:
    body = content.strip()
    if body.startswith("---"):  # a full SKILL.md already: keep its body only
        body = body.split("---", 2)[-1].strip()
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"


def parse(text: str) -> tuple[str, str]:
    """(description, body) of a SKILL.md."""
    found = re.match(r"---\s*\n(.*?)\n---\s*\n?(.*)", text, re.S)
    if not found:
        return "", text
    meta = dict(line.split(":", 1) for line in found[1].splitlines() if ":" in line)
    return meta.get("description", "").strip(), found[2].strip()


class Learning:
    """Learned skills on disk, their proposals and usage in the database."""

    def __init__(self, db: Database, root: Path) -> None:
        self.db = db
        self.root = root
        self.dir = root / "skills"

    # ---- skills on disk -------------------------------------------------------------------------

    def path(self, name: str, archived: bool = False) -> Path:
        return (self.dir / ".archive" if archived else self.dir) / name / "SKILL.md"

    def skills(self, *, archived: bool = False) -> list[dict[str, Any]]:
        base = self.dir / ".archive" if archived else self.dir
        usage = {r["name"]: r for r in self.db.all("SELECT * FROM skill_usage")}
        found = []
        for file in sorted(base.glob("*/SKILL.md")) if base.exists() else []:
            name = file.parent.name
            if name.startswith("."):
                continue
            description, _ = parse(file.read_text(encoding="utf-8"))
            row = usage.get(name, {})
            found.append(
                {
                    "name": name,
                    "description": description,
                    "uses": row.get("uses", 0),
                    "last_used": row.get("last_used"),
                    "pinned": bool(row.get("pinned", 0)),
                    "state": "archivée" if archived else row.get("state") or "active",
                }
            )
        return found

    def catalogue(self) -> str:
        """For the brain's and agents' prompts: one line per active skill."""
        rows = self.skills()[:CATALOGUE_MAX]
        return "\n".join(f"- {s['name']} : {s['description']}" for s in rows)

    def read(self, name: str) -> str:
        key = slug(name)
        file = self.path(key)
        if not file.exists():
            known = ", ".join(s["name"] for s in self.skills()) or "aucune"
            raise SkillError(f"compétence « {name} » inconnue ; apprises : {known}")
        self.db.execute(
            "INSERT INTO skill_usage(name, uses, last_used, state) VALUES(?, 1, ?, 'active') "
            "ON CONFLICT(name) DO UPDATE SET uses = uses + 1, last_used = excluded.last_used, "
            "state = 'active'",
            (key, now_iso()),
        )
        return file.read_text(encoding="utf-8")

    # ---- proposals ------------------------------------------------------------------------------

    def propose(
        self, name: str, description: str, content: str, source: str = ""
    ) -> dict[str, Any]:
        key = slug(name)
        description, content = description.strip(), content.strip()
        if not NAME.fullmatch(key):
            raise SkillError("nom de 3 à 50 lettres minuscules, chiffres ou tirets")
        if not 10 <= len(description) <= MAX_DESCRIPTION:
            raise SkillError(f"description de 10 à {MAX_DESCRIPTION} caractères (quand l'utiliser)")
        if not 50 <= len(content) <= MAX_CONTENT:
            raise SkillError(f"contenu de 50 à {MAX_CONTENT} caractères")
        if re.search(r"(sk|rk|pk)_(live|test)_\w{8,}|whsec_\w{8,}|-----BEGIN", content):
            raise SkillError("une compétence ne doit contenir aucune clé ni aucun secret")
        if self.db.one(
            "SELECT 1 FROM skill_proposals WHERE name = ? AND status = 'pending'", (key,)
        ):
            raise SkillError(f"une proposition pour « {key} » attend déjà ta validation")
        previous = self.path(key).read_text(encoding="utf-8") if self.path(key).exists() else ""
        pid = self.db.execute(
            "INSERT INTO skill_proposals(name, description, content, previous, source, ts) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (key, description, content[:MAX_CONTENT], previous, source[:100], now_iso()),
        )
        return self.proposal(pid)

    def proposal(self, proposal_id: int) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM skill_proposals WHERE id = ?", (int(proposal_id),))
        if row is None:
            raise SkillError(f"proposition #{proposal_id} introuvable")
        return row

    def proposals(self, status: str = "pending") -> list[dict[str, Any]]:
        return self.db.all(
            "SELECT * FROM skill_proposals WHERE status = ? ORDER BY id DESC LIMIT 50", (status,)
        )

    def approve(self, proposal_id: int) -> dict[str, Any]:
        row = self.proposal(proposal_id)
        if row["status"] != "pending":
            raise SkillError(f"proposition #{proposal_id} déjà traitée ({row['status']})")
        file = self.path(row["name"])
        if file.exists():  # an update: keep the previous version
            history = self.dir / ".history"
            history.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(file, history / f"{row['name']}-{stamp}.md")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(render(row["name"], row["description"], row["content"]), encoding="utf-8")
        self.db.execute(
            "INSERT INTO skill_usage(name, uses, last_used, state) VALUES(?, 0, ?, 'active') "
            "ON CONFLICT(name) DO UPDATE SET last_used = excluded.last_used, state = 'active'",
            (row["name"], now_iso()),
        )
        self.db.execute(
            "UPDATE skill_proposals SET status = 'approved', decided_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
        return self.proposal(row["id"])

    def reject(self, proposal_id: int) -> dict[str, Any]:
        row = self.proposal(proposal_id)
        if row["status"] != "pending":
            raise SkillError(f"proposition #{proposal_id} déjà traitée ({row['status']})")
        self.db.execute(
            "UPDATE skill_proposals SET status = 'rejected', decided_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
        return self.proposal(row["id"])

    # ---- review of a finished mission -----------------------------------------------------------

    def review_prompt(self) -> str:
        names = ", ".join(s["name"] for s in self.skills()) or "aucune"
        return REVIEW.format(existing=names)

    def review(self, mission: dict[str, Any], report: str, ask: Any) -> dict[str, Any] | None:
        """Ask the review engine whether the mission taught something; propose it if so."""
        from spectre.assistant.brain import extract_json, failed

        reply = ask(
            f"Mission #{mission['id']} : {mission['goal'][:2000]}\n\nRapport :\n{report[:12000]}",
            self.review_prompt(),
        )
        if failed(reply):
            return None
        try:
            skill = extract_json(reply.text).get("skill")
        except (ValueError, AttributeError):
            return None
        if not isinstance(skill, dict):
            return None
        try:
            return self.propose(
                str(skill.get("name", "")),
                str(skill.get("description", "")),
                str(skill.get("content", "")),
                source=f"mission #{mission['id']}",
            )
        except SkillError:
            return None

    # ---- curator --------------------------------------------------------------------------------

    def pin(self, name: str, pinned: bool = True) -> None:
        key = slug(name)
        if not self.path(key).exists():
            raise SkillError(f"compétence « {name} » inconnue")
        self.db.execute(
            "INSERT INTO skill_usage(name, uses, last_used, pinned, state) "
            "VALUES(?, 0, ?, ?, 'active') "
            "ON CONFLICT(name) DO UPDATE SET pinned = excluded.pinned",
            (key, now_iso(), int(pinned)),
        )

    def archive(self, name: str) -> None:
        key = slug(name)
        source, target = self.path(key).parent, self.path(key, archived=True).parent
        if not source.exists():
            raise SkillError(f"compétence « {name} » inconnue")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(source), str(target))
        self.db.execute("UPDATE skill_usage SET state = 'archivée' WHERE name = ?", (key,))

    def restore(self, name: str) -> None:
        key = slug(name)
        source, target = self.path(key, archived=True).parent, self.path(key).parent
        if not source.exists():
            raise SkillError(f"aucune compétence archivée ne s'appelle « {name} »")
        if target.exists():
            raise SkillError(f"une compétence active s'appelle déjà « {key} »")
        shutil.move(str(source), str(target))
        self.db.execute(
            "INSERT INTO skill_usage(name, uses, last_used, state) VALUES(?, 0, ?, 'active') "
            "ON CONFLICT(name) DO UPDATE SET last_used = excluded.last_used, state = 'active'",
            (key, now_iso()),
        )

    def curate(self, now: datetime) -> dict[str, list[str]]:
        """Mark unused skills « obsolète », archive long-unused ones (never pinned ones)."""
        done: dict[str, list[str]] = {"stale": [], "archived": []}
        for skill in self.skills():
            if skill["pinned"]:
                continue
            last = skill["last_used"]
            if last is None:  # never tracked (copied by hand): start counting today
                self.db.execute(
                    "INSERT OR IGNORE INTO skill_usage(name, uses, last_used, state) "
                    "VALUES(?, 0, ?, 'active')",
                    (skill["name"], now.isoformat()),
                )
                continue
            idle = now - datetime.fromisoformat(last)
            if idle >= timedelta(days=ARCHIVE_DAYS):
                self.archive(skill["name"])
                done["archived"].append(skill["name"])
            elif idle >= timedelta(days=STALE_DAYS) and skill["state"] != "obsolète":
                self.db.execute(
                    "UPDATE skill_usage SET state = 'obsolète' WHERE name = ?", (skill["name"],)
                )
                done["stale"].append(skill["name"])
        return done


# ---- search over past conversations -------------------------------------------------------------


SEARCHED = ("utterance", "reply", "webhook", "agent_message")


def search_history(db: Database, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Full-text search (accents ignored) over past exchanges, newest first."""
    words = re.findall(r"\w+", query.lower())
    if not words:
        return []
    match = " ".join(f'"{w}"*' for w in words[:8])
    marks = ",".join("?" for _ in SEARCHED)
    rows = db.all(
        "SELECT e.id, e.ts, e.kind, e.source, snippet(events_fts, 0, '«', '»', '…', 16) AS excerpt "
        "FROM events_fts JOIN events e ON e.id = events_fts.rowid "
        f"WHERE events_fts MATCH ? AND e.kind IN ({marks}) ORDER BY e.id DESC LIMIT ?",  # noqa: S608
        (match, *SEARCHED, max(1, min(limit, 30))),
    )
    missions = db.all(
        "SELECT id, updated_at AS ts, goal FROM missions WHERE goal LIKE ? OR report LIKE ? "
        "ORDER BY id DESC LIMIT 5",
        (f"%{query.strip()}%", f"%{query.strip()}%"),
    )
    rows += [
        {
            "id": m["id"],
            "ts": m["ts"],
            "kind": "mission",
            "source": "mission",
            "excerpt": m["goal"][:200],
        }
        for m in missions
    ]
    return rows


# ---- restore points for missions ----------------------------------------------------------------


def mark_mission(db: Database, mission_id: int, edge: str) -> None:
    """Note the undo journal's position when a mission starts (`from`) or ends (`to`)."""
    row = db.one("SELECT COALESCE(MAX(id), 0) AS n FROM undo")
    key = f"mission_undo_{mission_id}"
    data = json.loads(db.get_kv(key) or "{}")
    if edge == "from" and "from" in data:  # a resumed mission keeps its first mark
        return
    data[edge] = int(row["n"]) if row else 0
    db.set_kv(key, json.dumps(data))


def mission_changes(db: Database, mission_id: int) -> list[dict[str, Any]]:
    """File actions journaled while the mission ran (not undone yet), newest first."""
    data = json.loads(db.get_kv(f"mission_undo_{mission_id}") or "{}")
    if "from" not in data:
        return []
    end = data.get("to", 1 << 62)
    return db.all(
        "SELECT * FROM undo WHERE id > ? AND id <= ? AND undone = 0 ORDER BY id DESC",
        (data["from"], end),
    )
