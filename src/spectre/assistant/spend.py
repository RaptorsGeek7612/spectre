"""What the AI costs, set against what the business earns.

Every model call made for a mission (plan, steps, verification, report, board...) or for the
conversation is written to a ledger: engine, agent, role, mission, company, duration, tokens and
cost. Through the Claude Code CLI the cost is the API-equivalent figure the CLI reports, while
the subscription is what is actually paid; HTTP providers report tokens; Codex and Vibe report
neither, so only their time is counted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from spectre.assistant import runctx
from spectre.assistant.db import Database, now_iso


def record(
    db: Database,
    reply: Any,
    seconds: float,
    *,
    engine: str,
    role: str = "",
    agent: str = "",
    mission_id: int | None = None,
    company_id: int | None = None,
) -> None:
    """One call in the ledger (the thread's context fills what is not given)."""
    context = runctx.current()
    db.execute(
        "INSERT INTO usage_ledger(ts, mission_id, company_id, agent, engine, role, seconds, "
        "cost_usd, tokens, failed) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            now_iso(),
            mission_id if mission_id is not None else context.get("mission"),
            company_id if company_id is not None else context.get("company"),
            agent or str(context.get("agent", "")),
            engine,
            role or str(context.get("role", "")),
            round(seconds, 2),
            float(getattr(reply, "cost_usd", None) or 0.0),
            int(getattr(reply, "tokens", 0) or 0),
            int(bool(getattr(reply, "is_error", False))),
        ),
    )


def mission_company(db: Database, plan: dict[str, Any]) -> int | None:
    """The company a mission works for (from its task, decision or explicit key)."""
    if plan.get("company"):
        return int(plan["company"])
    if plan.get("task"):
        row = db.one("SELECT company_id FROM tasks WHERE id = ?", (int(plan["task"]),))
        return int(row["company_id"]) if row else None
    if plan.get("decision"):
        row = db.one("SELECT company_id FROM decisions WHERE id = ?", (int(plan["decision"]),))
        return int(row["company_id"]) if row else None
    return None


def summary(
    db: Database, now: datetime, company_id: int | None = None, days: int = 30
) -> dict[str, Any]:
    """Totals over `days`, by role, agent, engine and department, and against the MRR."""
    since = (now - timedelta(days=days)).isoformat()
    where = "ts >= ?"
    params: list[Any] = [since]
    if company_id is not None:
        where += " AND company_id = ?"
        params.append(company_id)
    totals = db.one(
        f"SELECT COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost, "  # noqa: S608 - fixed
        f"COALESCE(SUM(seconds), 0) AS seconds, COALESCE(SUM(tokens), 0) AS tokens, "
        f"COALESCE(SUM(failed), 0) AS failed FROM usage_ledger WHERE {where}",
        tuple(params),
    )

    def group(column: str) -> list[dict[str, Any]]:
        return db.all(
            f"SELECT {column} AS key, COUNT(*) AS calls, ROUND(SUM(cost_usd), 4) AS cost, "  # noqa: S608
            f"ROUND(SUM(seconds), 1) AS seconds, SUM(tokens) AS tokens FROM usage_ledger "
            f"WHERE {where} GROUP BY {column} ORDER BY cost DESC, seconds DESC",
            tuple(params),
        )

    departments: dict[str, dict[str, float]] = {}
    for row in db.all(
        f"SELECT u.cost_usd, u.seconds, t.department FROM usage_ledger u "  # noqa: S608
        f"JOIN missions m ON m.id = u.mission_id JOIN tasks t ON t.mission_id = m.id "
        f"WHERE {where.replace('ts', 'u.ts').replace('company_id', 'u.company_id')}",
        tuple(params),
    ):
        entry = departments.setdefault(
            row["department"] or "sans département", {"cost": 0.0, "seconds": 0.0}
        )
        entry["cost"] += row["cost_usd"]
        entry["seconds"] += row["seconds"]
    missions = db.all(
        f"SELECT u.mission_id AS id, m.goal, ROUND(SUM(u.cost_usd), 4) AS cost, "  # noqa: S608
        f"ROUND(SUM(u.seconds), 1) AS seconds FROM usage_ledger u JOIN missions m ON m.id = "
        f"u.mission_id WHERE {where.replace('ts', 'u.ts').replace('company_id', 'u.company_id')} "
        f"GROUP BY u.mission_id ORDER BY cost DESC, seconds DESC LIMIT 5",
        tuple(params),
    )
    result: dict[str, Any] = {
        "days": days,
        "calls": int(totals["calls"]) if totals else 0,
        "cost_usd": round(float(totals["cost"]), 4) if totals else 0.0,
        "seconds": round(float(totals["seconds"]), 1) if totals else 0.0,
        "tokens": int(totals["tokens"]) if totals else 0,
        "failed": int(totals["failed"]) if totals else 0,
        "by_role": group("role"),
        "by_agent": group("agent"),
        "by_engine": group("engine"),
        "by_department": [
            {"key": k, "cost": round(v["cost"], 4), "seconds": round(v["seconds"], 1)}
            for k, v in sorted(departments.items(), key=lambda kv: -kv[1]["cost"])
        ],
        "top_missions": missions,
    }
    if company_id is not None:
        from spectre.assistant.saas import Saas

        mrr = Saas(db).kpis(company_id, now).get("mrr")
        result["mrr"] = mrr
        if mrr:
            result["cost_per_mrr"] = round(result["cost_usd"] / mrr * 100, 2)
    return result


def text(db: Database, now: datetime, company_id: int | None = None, days: int = 30) -> str:
    """The summary as a few lines for the brain."""
    from spectre.assistant.trust import label

    data = summary(db, now, company_id, days)
    if not data["calls"]:
        return f"aucun appel au modèle enregistré sur {days} jours"
    lines = [
        f"Sur {days} jours : {data['calls']} appels, {data['cost_usd']:.2f} $ (équivalent API ; "
        f"l'abonnement Claude est ce qui est vraiment payé), {data['seconds'] / 60:.0f} min de "
        f"calcul, {data['tokens']} jetons comptés, {data['failed']} appels en échec."
    ]
    if data.get("mrr"):
        lines.append(f"MRR : {data['mrr']:g} ; coût IA = {data['cost_per_mrr']:g} % du MRR.")

    def agent_label(key: str) -> str:
        return label(key, db) if key else "réglage"

    names: list[tuple[str, str, Callable[[str], str]]] = [
        ("Par rôle", "by_role", lambda k: k or "autre"),
        ("Par agent", "by_agent", agent_label),
        ("Par département", "by_department", lambda k: k),
    ]
    for title, key, name in names:
        rows = data[key][:6]
        if rows:
            lines.append(
                f"{title} : "
                + ", ".join(
                    f"{name(r['key'])} {r['cost'] or 0:.2f} $ ({r['seconds'] or 0:.0f} s)"
                    for r in rows
                )
            )
    for mission in data["top_missions"][:3]:
        lines.append(
            f"Mission la plus coûteuse : #{mission['id']} {mission['goal'][:80]} "
            f"({mission['cost']:.2f} $)"
        )
    return "\n".join(lines)


def tokens_of(data: Any) -> int:
    """Input + output tokens of an OpenAI-style or Claude CLI `usage` object."""
    if not isinstance(data, dict):
        return 0
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        return 0
    keys = ("prompt_tokens", "completion_tokens", "input_tokens", "output_tokens")
    return int(sum(usage.get(k) or 0 for k in keys if isinstance(usage.get(k), (int, float))))


__all__ = ["json", "mission_company", "record", "summary", "text", "tokens_of"]
