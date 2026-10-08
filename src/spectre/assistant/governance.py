"""Governance gate: every action Spectre takes is judged on three independent axes.

1. Technical risk (`Level`, 0-5): how much damage the action could do.
2. Category policy (`ALWAYS` / `ASK` / `NEVER`): what kind of action it is.
3. Budget: a cap on actions per minute and per day, against runaway loops.

The most restrictive axis wins. `refused` is final (no approval can save it); `approval`
asks the user. Every decision is written to the audit table.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Final, Literal

from spectre.assistant.db import Database, now_iso


class Level(IntEnum):
    READ = 0  # look at things: time, memory, files, the web
    UI = 1  # open an app or a page
    WRITE = 2  # create or move a file, set a reminder (reversible, journaled)
    DESTRUCTIVE = 3  # delete (to Spectre's trash), overwrite
    EXTERNAL = 4  # send, publish, contact someone, spend money
    CRITICAL = 5  # install software, power off, modify Spectre itself


Policy = Literal["ALWAYS", "ASK", "NEVER"]
Verdict = Literal["auto", "approval", "refused"]

DEFAULT_POLICIES: Final[dict[str, Policy]] = {
    "read": "ALWAYS",
    "memory": "ALWAYS",
    "open": "ALWAYS",
    "write_file": "ALWAYS",
    "reminder": "ALWAYS",
    "mission": "ALWAYS",
    "delete_file": "ASK",
    "overwrite_file": "ASK",
    "external_send": "ASK",
    "system_power": "ASK",
    "install": "NEVER",
    "modify_core": "NEVER",
    "payment": "NEVER",
}
ALWAYS_ASK_LEVELS: Final = {Level.EXTERNAL, Level.CRITICAL}


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str


class Gate:
    """Decides whether an action runs, waits for the user, or is refused."""

    def __init__(
        self,
        db: Database,
        *,
        auto_max_level: int = int(Level.WRITE),
        policies: dict[str, Policy] | None = None,
        per_minute: int = 20,
        per_day: int = 500,
    ) -> None:
        self.db = db
        self.auto_max_level = auto_max_level
        self.policies = {**DEFAULT_POLICIES, **(policies or {})}
        self.per_minute = per_minute
        self.per_day = per_day
        self._recent: deque[float] = deque()

    def decide(self, level: Level, category: str) -> Decision:
        policy = self.policies.get(category, "ASK")
        if policy == "NEVER":
            return Decision("refused", f"catégorie « {category} » interdite par conception")
        if not self._budget_ok():
            return Decision("refused", "budget d'actions dépassé (trop d'actions d'affilée)")
        if level in ALWAYS_ASK_LEVELS:
            return Decision("approval", "action vers l'extérieur ou critique : validation requise")
        if level > self.auto_max_level:
            return Decision(
                "approval", f"niveau de risque {int(level)} au-dessus du seuil automatique"
            )
        if policy == "ASK":
            return Decision("approval", f"la catégorie « {category} » demande ta validation")
        return Decision("auto", "autorisé")

    def _budget_ok(self) -> bool:
        now = time.monotonic()
        while self._recent and now - self._recent[0] > 60:
            self._recent.popleft()
        if len(self._recent) >= self.per_minute:
            return False
        day = now_iso()[:10]
        row = self.db.one("SELECT COUNT(*) AS n FROM audit WHERE substr(ts, 1, 10) = ?", (day,))
        return not (row and row["n"] >= self.per_day)

    def record(
        self,
        tool: str,
        args: dict[str, Any],
        level: Level,
        category: str,
        decision: str,
        result: str,
    ) -> None:
        """Append to the immutable audit log (and count towards the budget)."""
        self._recent.append(time.monotonic())
        self.db.execute(
            "INSERT INTO audit(ts, tool, args, level, category, decision, result) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                now_iso(),
                tool,
                json.dumps(args, ensure_ascii=False),
                int(level),
                category,
                decision,
                result[:2000],
            ),
        )
