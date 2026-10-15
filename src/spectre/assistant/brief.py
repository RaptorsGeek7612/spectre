"""The morning briefing's business part: a few spoken lines per company."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from spectre.assistant.db import Database
from spectre.assistant.saas import Saas, fmt


def company_lines(db: Database, root: Path | None, now: datetime) -> list[str]:
    """One short paragraph per company: figures, what waits for the user, what is due."""
    from spectre.assistant.company import Companies

    saas = Saas(db, root)
    lines = []
    for company in Companies(db).all():
        cid = company["id"]
        parts = []
        current = saas.kpis(cid, now)
        before = saas.kpis(cid, now, before=now - timedelta(days=7))
        if "mrr" in current:
            change = ""
            if "mrr" in before and before["mrr"]:
                delta = (current["mrr"] - before["mrr"]) / before["mrr"] * 100
                change = f", {'+' if delta >= 0 else ''}{delta:.0f} % sur la semaine"
            parts.append(f"MRR {fmt(current['mrr'])}{change}")
        if "churn_rate" in current:
            parts.append(f"churn {fmt(current['churn_rate'])} %")
        if current.get("up") == 0:
            parts.append("site HORS LIGNE")
        review = db.one(
            "SELECT COUNT(*) AS n FROM tasks WHERE company_id = ? AND status = 'review'", (cid,)
        )
        if review and review["n"]:
            parts.append(f"{review['n']} tâche(s) à valider")
        blocked = db.one(
            "SELECT COUNT(*) AS n FROM tasks WHERE company_id = ? AND status = 'blocked'", (cid,)
        )
        if blocked and blocked["n"]:
            parts.append(f"{blocked['n']} tâche(s) bloquée(s)")
        alerts = db.one(
            "SELECT COUNT(*) AS n FROM saas_alerts WHERE company_id = ? AND active = 1", (cid,)
        )
        if alerts and alerts["n"]:
            parts.append(f"{alerts['n']} alerte(s) active(s)")
        week = (now + timedelta(days=7)).isoformat()
        reviews = db.one(
            "SELECT COUNT(*) AS n FROM decisions WHERE company_id = ? AND status = 'decided' "
            "AND review_at <= ?",
            (cid, week),
        )
        if reviews and reviews["n"]:
            parts.append(f"{reviews['n']} décision(s) à réévaluer cette semaine")
        ending = db.one(
            "SELECT COUNT(*) AS n FROM experiments WHERE company_id = ? AND status = 'running' "
            "AND end_at <= ?",
            (cid, week),
        )
        if ending and ending["n"]:
            parts.append(f"{ending['n']} expérience(s) se terminent cette semaine")
        if parts:
            lines.append(f"{company['name']} : {', '.join(parts)}.")
    return lines
