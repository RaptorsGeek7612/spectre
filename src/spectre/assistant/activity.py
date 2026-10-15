"""What each agent does, moment by moment, for the video call, the team page and the replays.

Rows are written where the work happens: a mission starts or ends, a step goes to an agent or
comes back verified, a tool runs through the gate (from the service or from a CLI agent's MCP
server, which shares the database). Nothing here calls a model: the call's spoken lines are
made from these rows, so watching the team costs no tokens.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from spectre.assistant import runctx
from spectre.assistant.db import Database, now_iso

KEEP_DAYS = 30
MAX_DETAIL = 4000
TARGET_KEYS = ("path", "url", "query", "command", "name", "app", "title", "text", "goal")


def target(args: dict[str, Any]) -> str:
    """What a tool call is about, in a few words (its file, page, search or command)."""
    for key in TARGET_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().replace("\n", " ")[:140]
    for value in args.values():
        if isinstance(value, str) and value.strip():
            return value.strip().replace("\n", " ")[:140]
    return ""


def record(
    db: Database,
    kind: str,
    *,
    agent: str | None = None,
    mission: int | None = None,
    title: str = "",
    detail: str = "",
    status: str = "",
    seconds: float = 0.0,
) -> int:
    """Append one row; the agent and mission default to the thread's context."""
    context = runctx.current()
    row_id = db.execute(
        "INSERT INTO activity(ts, agent, mission_id, kind, title, detail, status, seconds) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        (
            now_iso(),
            agent if agent is not None else str(context.get("agent", "")),
            mission if mission is not None else context.get("mission"),
            kind,
            title[:300],
            detail[:MAX_DETAIL],
            status,
            round(seconds, 2),
        ),
    )
    if row_id % 500 == 0:  # now and then, forget what is older than a month
        cutoff = (datetime.now(UTC) - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
        db.execute("DELETE FROM activity WHERE ts < ?", (cutoff,))
    return row_id


def finish(db: Database, row_id: int, status: str, detail: str, started: float) -> None:
    """Close a row opened as `running` (a tool call that has returned)."""
    db.execute(
        "UPDATE activity SET status = ?, detail = ?, seconds = ? WHERE id = ?",
        (status, detail[:MAX_DETAIL], round(time.perf_counter() - started, 2), row_id),
    )


def tool_started(db: Database, agent: str, mission: int | None, name: str, args: Any) -> int:
    args = args if isinstance(args, dict) else {}
    return record(
        db,
        "tool",
        agent=agent or None,
        mission=mission,
        title=name,
        detail=json.dumps({"target": target(args)}, ensure_ascii=False),
        status="running",
    )


def tool_finished(db: Database, row_id: int, name: str, args: Any, result: str, t0: float) -> None:
    args = args if isinstance(args, dict) else {}
    failed = result.startswith(("ÉCHEC", "REFUSÉ"))
    payload = {"target": target(args), "args": _short_args(args), "result": result[:1500]}
    finish(db, row_id, "fail" if failed else "ok", json.dumps(payload, ensure_ascii=False), t0)


def _short_args(args: dict[str, Any]) -> dict[str, Any]:
    return {k: (v[:600] if isinstance(v, str) else v) for k, v in list(args.items())[:8]}


def rows(
    db: Database,
    *,
    since: int = 0,
    mission: int | None = None,
    agent: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Rows in order, newest last; filtered by mission or agent."""
    where: list[str] = ["id > ?"]
    params: list[Any] = [since]
    if mission is not None:
        where.append("mission_id = ?")
        params.append(mission)
    if agent is not None:
        where.append("agent = ?")
        params.append(agent)
    found = db.all(
        f"SELECT * FROM activity WHERE {' AND '.join(where)} "  # noqa: S608 - fixed clauses
        "ORDER BY id DESC LIMIT ?",
        (*params, limit),
    )
    return found[::-1]
