"""Earned autonomy: each agent's record, and the trust level it earns from it.

The record counts what went well (verified steps, tasks the user validated, actions the user
approved) and what went wrong (failed checks, tasks sent back, missions rolled back, actions the
user refused). Levels:
- apprenti: every action under the usual rules; under autopilot its tasks wait for the user;
- confirmé: its tasks may start on their own under autopilot;
- expert: on top of that, replacing or deleting a file inside the allowed folders no longer
  needs approval (still journaled and undoable). Sending, paying, installing or anything
  critical always asks, whatever the level.
A level is recomputed from the record each time: an agent that starts failing loses it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from spectre.assistant.db import Database, now_iso

WEIGHTS = {
    "step_ok": (1.0, 0.0),
    "task_validated": (2.0, 0.0),
    "approval_granted": (0.5, 0.0),
    "step_fail": (0.0, 1.0),
    "task_redo": (0.0, 2.0),
    "approval_denied": (0.0, 2.0),
    "rollback": (0.0, 5.0),
}
LEVELS = ("apprenti", "confirmé", "expert")
CONFIRMED = (15.0, 0.85)  # (volume, reliability)
EXPERT = (40.0, 0.93)
CLEAN_DAYS = 30  # an expert has no rollback in this window
RELAXED = ("delete_file", "overwrite_file")  # what an expert may do without asking


def label(agent: str, db: Database | None = None) -> str:
    from spectre.assistant.config import agent_name
    from spectre.assistant.custom_agents import PREFIX, CustomAgents

    if agent.startswith(PREFIX) and db is not None:
        found = CustomAgents(db).get(agent)
        return found["name"] if found else "agent supprimé"
    return agent_name(agent)


class Trust:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, agent: str, kind: str, mission_id: int | None = None) -> None:
        if not agent or kind not in WEIGHTS:
            return
        self.db.execute(
            "INSERT INTO trust_events(agent, kind, mission_id, ts) VALUES(?, ?, ?, ?)",
            (agent, kind, mission_id, now_iso()),
        )

    def dossier(self, agent: str, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now().astimezone()
        rows = self.db.all(
            "SELECT kind, COUNT(*) AS n FROM trust_events WHERE agent = ? GROUP BY kind", (agent,)
        )
        counts = {r["kind"]: int(r["n"]) for r in rows}
        good = sum(WEIGHTS[k][0] * n for k, n in counts.items() if k in WEIGHTS)
        bad = sum(WEIGHTS[k][1] * n for k, n in counts.items() if k in WEIGHTS)
        reliability = (good + 1) / (good + bad + 2)
        volume = good + bad
        recent = self.db.one(
            "SELECT 1 FROM trust_events WHERE agent = ? AND kind = 'rollback' AND ts >= ?",
            (agent, (now - timedelta(days=CLEAN_DAYS)).isoformat()),
        )
        level = "apprenti"
        if volume >= CONFIRMED[0] and reliability >= CONFIRMED[1]:
            level = "confirmé"
            if volume >= EXPERT[0] and reliability >= EXPERT[1] and recent is None:
                level = "expert"
        return {
            "agent": agent,
            "name": label(agent, self.db),
            "level": level,
            "reliability": round(reliability * 100, 1),
            "volume": volume,
            "counts": counts,
        }

    def level(self, agent: str) -> str:
        return self.dossier(agent)["level"] if agent else ""

    def agents(self) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT DISTINCT agent FROM trust_events ORDER BY agent")
        return [self.dossier(r["agent"]) for r in rows]

    def changes(self, notify: Any) -> list[tuple[str, str, str]]:
        """Announce promotions and demotions since the last check."""
        import json

        known = json.loads(self.db.get_kv("trust_levels") or "{}")
        moved = []
        for dossier in self.agents():
            before = known.get(dossier["agent"], "apprenti")
            if dossier["level"] != before:
                moved.append((dossier["agent"], before, dossier["level"]))
                up = LEVELS.index(dossier["level"]) > LEVELS.index(before)
                notify(
                    "confiance",
                    f"{dossier['name']} {'promu' if up else 'rétrogradé'} : {dossier['level']}",
                    f"Fiabilité {dossier['reliability']:g} % sur {dossier['volume']:g} points. "
                    + (
                        "Il gagne en autonomie."
                        if up
                        else "Il redemande ta validation là où il pouvait s'en passer."
                    ),
                )
            known[dossier["agent"]] = dossier["level"]
        self.db.set_kv("trust_levels", json.dumps(known, ensure_ascii=False))
        return moved

    def mission_agent(self, mission_id: int) -> str:
        """The agent who carried out a mission's steps (the first step's)."""
        import json

        row = self.db.one("SELECT steps FROM missions WHERE id = ?", (mission_id,))
        steps = json.loads(row["steps"] or "[]") if row else []
        return str(steps[0].get("key") or steps[0].get("agent") or "") if steps else ""
