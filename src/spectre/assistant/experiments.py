"""Measured experiments: a hypothesis on one KPI, a duration, and a verdict from the real figures.

The baseline is the KPI's value when the experiment starts (from the SaaS monitoring); at the
end, the value is compared with it. With no control group this is a before/after reading, not
proof of cause: the verdict says so. No model call is needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from spectre.assistant.db import Database, now_iso
from spectre.assistant.saas import LABELS, Saas, fmt

DIRECTIONS = ("up", "down")
MAX_DAYS = 180
CAVEAT = "lecture avant/après, sans groupe témoin : d'autres causes ont pu jouer"


class ExperimentError(ValueError):
    """A refused experiment (the message is for the user)."""


class Experiments:
    def __init__(self, db: Database, root: Path | None = None) -> None:
        self.db = db
        self.saas = Saas(db, root)

    def all(self, company_id: int) -> list[dict[str, Any]]:
        return self.db.all(
            "SELECT * FROM experiments WHERE company_id = ? ORDER BY id DESC", (company_id,)
        )

    def get(self, experiment_id: int) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM experiments WHERE id = ?", (int(experiment_id),))
        if row is None:
            raise ExperimentError(f"expérience #{experiment_id} introuvable")
        return row

    def start(
        self,
        company_id: int,
        hypothesis: str,
        metric: str,
        direction: str = "up",
        min_change: float = 5.0,
        days: int = 14,
        *,
        decision_id: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or datetime.now().astimezone()
        hypothesis, metric = hypothesis.strip(), metric.strip()
        direction = {"hausse": "up", "baisse": "down"}.get(direction.strip().lower(), direction)
        if len(hypothesis) < 10:
            raise ExperimentError("décris l'hypothèse (ce que tu changes et ce que tu attends)")
        if direction not in DIRECTIONS:
            raise ExperimentError("sens attendu : up (hausse) ou down (baisse)")
        if not 1 <= int(days) <= MAX_DAYS:
            raise ExperimentError(f"durée de 1 à {MAX_DAYS} jours")
        if not 0 < float(min_change) <= 1000:
            raise ExperimentError("variation minimale en % : plus de 0")
        kpis = self.saas.kpis(company_id, now)
        if metric not in kpis:
            known = ", ".join(sorted(kpis)) or "aucun : branche d'abord une source"
            raise ExperimentError(
                f"pas encore de chiffre pour « {metric} » ; disponibles : {known}"
            )
        eid = self.db.execute(
            "INSERT INTO experiments(company_id, hypothesis, metric, direction, min_change, "
            "baseline, start_at, end_at, decision_id, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                hypothesis[:1000],
                metric,
                direction,
                float(min_change),
                kpis[metric],
                now.isoformat(),
                (now + timedelta(days=int(days))).isoformat(),
                decision_id,
                now_iso(),
            ),
        )
        return self.get(eid)

    def stop(self, experiment_id: int) -> dict[str, Any]:
        row = self.get(experiment_id)
        if row["status"] != "running":
            raise ExperimentError(f"l'expérience #{experiment_id} est déjà terminée")
        self.db.execute("UPDATE experiments SET status = 'cancelled' WHERE id = ?", (row["id"],))
        return self.get(row["id"])

    @staticmethod
    def judge(row: dict[str, Any], value: float) -> tuple[str, float]:
        """(verdict, change in %) for a result."""
        base = float(row["baseline"])
        change = (value - base) / abs(base) * 100 if base else (100.0 if value > 0 else 0.0)
        wanted = change if row["direction"] == "up" else -change
        if wanted >= row["min_change"]:
            return "confirmée", round(change, 2)
        if wanted <= -row["min_change"]:
            return "infirmée", round(change, 2)
        return "non concluante", round(change, 2)

    def evaluate(self, row: dict[str, Any], now: datetime) -> dict[str, Any]:
        value = self.saas.kpis(row["company_id"], now).get(row["metric"])
        if value is None:
            verdict, change = "non concluante", 0.0
        else:
            verdict, change = self.judge(row, value)
        self.db.execute(
            "UPDATE experiments SET status = 'done', result = ?, change = ?, verdict = ?, "
            "done_at = ? WHERE id = ?",
            (value, change, verdict, now.isoformat(), row["id"]),
        )
        return self.get(row["id"])

    def tick(self, now: datetime, notify: Any) -> list[int]:
        """Conclude the experiments whose time is up."""
        done = []
        for row in self.db.all(
            "SELECT * FROM experiments WHERE status = 'running' AND end_at <= ?",
            (now.isoformat(),),
        ):
            result = self.evaluate(row, now)
            done.append(row["id"])
            notify("experience", f"Expérience #{row['id']} : {result['verdict']}", describe(result))
        return done


def describe(row: dict[str, Any]) -> str:
    """One readable line about an experiment."""
    label = LABELS.get(row["metric"], row["metric"])
    sense = "hausse" if row["direction"] == "up" else "baisse"
    head = f"« {row['hypothesis']} » — {label}, {sense} d'au moins {row['min_change']:g} % attendue"
    if row["status"] == "running":
        return f"{head} ; départ {fmt(row['baseline'])}, fin le {row['end_at'][:10]}."
    if row["status"] == "cancelled":
        return f"{head} ; arrêtée."
    result = "pas de chiffre" if row["result"] is None else fmt(row["result"])
    return (
        f"{head} ; {fmt(row['baseline'])} → {result} ({row['change']:+g} %) : "
        f"{row['verdict']} ({CAVEAT})."
    )
