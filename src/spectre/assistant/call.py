"""The team's video call: who is there, what each one is doing, what they say.

Everything comes from the activity rows, the approvals, the conversation and the cost ledger,
so the call, its stand-up round, its replay and its recap call no model and cost no tokens.
The spoken lines are short sentences built from those facts, varied so they do not repeat.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from spectre.assistant import activity
from spectre.assistant.config import (
    AGENT_DEPARTMENTS,
    AGENT_NAMES,
    AGENT_ORDER,
    AGENT_TOOLS,
)
from spectre.assistant.custom_agents import PREFIX, CustomAgents
from spectre.assistant.db import Database

LEAD = "opus"
VERIFIER = "haiku"
YOU = "you"
QUIET_S = 180  # 💤 after three silent minutes at work
STALLED_S = 600  # « bloqué ? » after ten
DONE_S = 120  # « a fini » for two minutes after a step
TOOL_RUNNING_S = 900  # a tool row still « running » after this has died with its process
GENDERS = {
    "opus": "m",
    "sonnet": "m",
    "haiku": "m",
    "chatgpt": "f",
    "mistral": "m",
    "cursor": "f",
    "antigravity": "m",
    "kimi": "m",
}
URGENCY = {"needs_you": 0, "stalled": 1, "working": 2, "waiting": 3, "done": 4, "available": 5}


# ---- the team ----------------------------------------------------------------------------------


def members(db: Database) -> list[dict[str, Any]]:
    """Everyone on the call: Spectre's agents, then the ones the user created."""
    found = [
        {
            "key": key,
            "name": AGENT_NAMES[key],
            "department": AGENT_DEPARTMENTS[key],
            "tool": AGENT_TOOLS[key],
            "gender": GENDERS[key],
            "created": False,
        }
        for key in AGENT_ORDER
    ]
    for index, agent in enumerate(CustomAgents(db).list()):
        found.append(
            {
                "key": f"{PREFIX}{agent['id']}",
                "name": agent["name"],
                "department": agent["role"][:60],
                "tool": agent["engine"],
                "gender": "f" if index % 2 else "m",
                "created": True,
            }
        )
    return found


def _names(db: Database) -> dict[str, str]:
    return {m["key"]: m["name"] for m in members(db)}


def _age(iso: str, now: datetime) -> float:
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return 1e9
    return (now - (moment if moment.tzinfo else moment.replace(tzinfo=UTC))).total_seconds()


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"


def _detail(row: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(row.get("detail") or "{}")
    except ValueError:
        return {"text": row.get("detail", "")}
    return data if isinstance(data, dict) else {"text": str(data)}


# ---- live state --------------------------------------------------------------------------------


def statuses(db: Database, now: datetime | None = None) -> list[dict[str, Any]]:
    """Each member's status on the call, most urgent first."""
    now = now or datetime.now(UTC)
    day = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    recent = db.all("SELECT * FROM activity WHERE ts >= ? ORDER BY id", (day,))
    pending = db.all(
        "SELECT a.id, a.ts, a.tool, a.reason, g.agent FROM approvals a "
        "LEFT JOIN approval_agents g ON g.approval_id = a.id WHERE a.status = 'pending'"
    )
    spent = {
        r["agent"]: r
        for r in db.all(
            "SELECT agent, SUM(tokens) AS tokens, SUM(cost_usd) AS cost FROM usage_ledger "
            "WHERE ts >= ? GROUP BY agent",
            (day,),
        )
    }
    names = _names(db)
    running = db.all("SELECT id FROM missions WHERE status = 'running'")
    out = []
    for member in members(db):
        key = member["key"]
        mine = [r for r in recent if r["agent"] == key]
        tools = [r for r in mine if r["kind"] == "tool"]
        status, activity_text, since = "available", "", ""
        asks = [p for p in pending if (p["agent"] or LEAD) == key]
        open_tool = next(
            (
                r
                for r in reversed(tools)
                if r["status"] == "running" and _age(r["ts"], now) < TOOL_RUNNING_S
            ),
            None,
        )
        starts = [r for r in mine if r["kind"] == "step_start"]
        dones = [r for r in mine if r["kind"] == "step_done"]
        open_step = (
            starts[-1] if starts and (not dones or dones[-1]["id"] < starts[-1]["id"]) else None
        )
        if open_step and _age(open_step["ts"], now) > 3 * 3600:
            open_step = None  # a step that never ended died with a restart
        last = mine[-1]["ts"] if mine else ""
        if asks:
            status = "needs_you"
            activity_text = f"attend ton accord : {asks[0]['tool']}"
            since = asks[0]["ts"]
        elif open_tool or open_step:
            status = "working"
            if open_tool:
                target = _detail(open_tool).get("target", "")
                activity_text = f"{open_tool['title']} {target}".strip()
            else:
                activity_text = f"étape : {_short(open_step['title'], 90)}" if open_step else ""
            since = (open_step or open_tool or {}).get("ts", "")
            if last and _age(last, now) > STALLED_S:
                status = "stalled"
        elif key == LEAD and running:
            workers = {
                r["agent"]
                for r in recent
                if r["kind"] == "step_start" and r["mission_id"] in {m["id"] for m in running}
            }
            status = "waiting"
            who = ", ".join(names.get(w, w) for w in sorted(workers)) or "l'équipe"
            activity_text = f"attend {who}"
        elif dones and _age(dones[-1]["ts"], now) < DONE_S:
            status = "done"
            activity_text = f"a fini : {_short(dones[-1]['title'], 80)}"
        last_three = [(r["title"], _detail(r).get("target")) for r in tools[-3:]]
        cost = spent.get(key) or {}
        out.append(
            {
                **member,
                "status": status,
                "activity": activity_text,
                "since": since,
                "last": last,
                "quiet": status == "working" and bool(last) and _age(last, now) > QUIET_S,
                "long_tool": bool(open_tool) and _age(open_tool["ts"], now) > 60
                if open_tool
                else False,
                "fails": sum(1 for r in mine if r["status"] == "fail"),
                "repeat": len(last_three) == 3 and len(set(last_three)) == 1,
                "tools": len(tools),
                "steps": len(dones),
                "tokens": int(cost.get("tokens") or 0),
                "cost": round(float(cost.get("cost") or 0.0), 4),
            }
        )
    out.sort(key=lambda m: (m["key"] != LEAD, URGENCY.get(m["status"], 9)))
    return out


def screen(db: Database) -> dict[str, Any] | None:
    """The last tool call, as the shared screen shows it (command and its real output)."""
    row = db.one("SELECT * FROM activity WHERE kind = 'tool' ORDER BY id DESC LIMIT 1")
    if row is None:
        return None
    data = _detail(row)
    return {
        "id": row["id"],
        "ts": row["ts"],
        "agent": row["agent"] or LEAD,
        "tool": row["title"],
        "target": data.get("target", ""),
        "args": data.get("args", {}),
        "result": data.get("result", ""),
        "status": row["status"],
        "seconds": row["seconds"],
    }


# ---- what they say -----------------------------------------------------------------------------

TEMPLATES = {
    "mission_start": (
        "Nouvelle mission : {title}.",
        "On a une mission : {title}. Je répartis le travail.",
        "Mission lancée : {title}. Je vous la confie.",
    ),
    "step_start": (
        "Je m'en occupe : {title}.",
        "C'est pour moi : {title}.",
        "Je prends cette étape : {title}.",
    ),
    "step_ok": ("C'est fait : {title}.", "Terminé : {title}.", "Voilà, c'est bouclé : {title}."),
    "verified": (
        "Vérifié, c'est bon.",
        "Je confirme, l'étape tient la route.",
        "Contrôlé : rien à redire.",
    ),
    "rejected": (
        "Ça ne passe pas : {note}",
        "Je ne valide pas : {note}",
        "Pas encore bon : {note}",
    ),
    "mission_ok": (
        "Mission terminée : {title}. Tout est vérifié.",
        "C'est fini pour {title}, tout est vérifié.",
    ),
    "mission_ko": ("Mission terminée, mais avec des étapes à revoir : {note}",),
    "approval": (
        "J'ai besoin de ton accord pour {title} : {note}.",
        "Je t'attends : il me faut ton accord pour {title}.",
    ),
    "tool_fail": ("Petit souci avec {title} : {note}", "{title} n'a pas marché : {note}"),
}


def _say(kind: str, seed: int, **values: str) -> str:
    choices = TEMPLATES[kind]
    return choices[seed % len(choices)].format(**values)


def lines_for(row: dict[str, Any]) -> list[dict[str, Any]]:
    """What the team says about one activity row (none for most tool calls)."""
    seed, kind, agent = int(row["id"]), row["kind"], row["agent"] or LEAD
    title = _short(row["title"], 110)
    data = _detail(row)
    said: list[tuple[str, str]] = []
    if kind == "mission_start":
        said.append((LEAD, _say("mission_start", seed, title=title)))
    elif kind == "step_start":
        said.append((agent, _say("step_start", seed, title=title)))
    elif kind == "step_done":
        if row["status"] == "ok":
            said.append((agent, _say("step_ok", seed, title=title)))
            said.append((VERIFIER, _say("verified", seed)))
        else:
            note = _short(str(data.get("note") or "le résultat est incomplet"), 140)
            said.append((VERIFIER, _say("rejected", seed, note=note)))
    elif kind == "mission_done":
        if row["status"] == "ok":
            said.append((LEAD, _say("mission_ok", seed, title=title)))
        else:
            said.append(
                (LEAD, _say("mission_ko", seed, note=_short(str(data.get("text", "")), 120)))
            )
    elif kind == "approval":
        reason = _short(str(data.get("target") or data.get("reason") or ""), 100)
        said.append((agent, _say("approval", seed, title=row["title"], note=reason)))
    elif kind == "tool" and row["status"] == "fail":
        first = str(data.get("result", "")).removeprefix("ÉCHEC : ").splitlines()[:1]
        said.append(
            (agent, _say("tool_fail", seed, title=row["title"], note=_short(" ".join(first), 100)))
        )
    return [
        {"id": f"a{row['id']}-{i}", "ts": row["ts"], "agent": who, "text": text, "kind": kind}
        for i, (who, text) in enumerate(said)
    ]


def conversation_lines(db: Database, since: int) -> list[dict[str, Any]]:
    """What you and Spectre said to each other, as the call hears it."""
    rows = db.all(
        "SELECT id, ts, kind, text FROM events WHERE id > ? AND kind IN ('utterance', 'reply') "
        "ORDER BY id DESC LIMIT 20",
        (since,),
    )[::-1]
    return [
        {
            "id": f"e{r['id']}",
            "ts": r["ts"],
            "agent": YOU if r["kind"] == "utterance" else LEAD,
            "text": _short(r["text"], 400),
            "kind": r["kind"],
        }
        for r in rows
        if r["text"].strip()
    ]


def snapshot(db: Database, since: int = 0, since_event: int = 0) -> dict[str, Any]:
    """The call right now: members and their status, new lines, the shared screen."""
    new_rows = activity.rows(db, since=since, limit=120)
    if not since:  # joining: nothing is replayed, the call starts now
        new_rows = []
    lines = [line for row in new_rows for line in lines_for(row)]
    events = conversation_lines(db, since_event) if since_event else []
    last_event = db.one("SELECT MAX(id) AS n FROM events")
    last_row = db.one("SELECT MAX(id) AS n FROM activity")
    agents = statuses(db)
    return {
        "agents": agents,
        "lines": sorted(lines + events, key=lambda line: line["ts"]),
        "last_id": int((last_row or {}).get("n") or 0),
        "last_event": int((last_event or {}).get("n") or 0),
        "screen": screen(db),
        "needs_you": sum(1 for a in agents if a["status"] == "needs_you"),
        "working": sum(1 for a in agents if a["status"] in ("working", "stalled")),
    }


# ---- stand-up round ---------------------------------------------------------------------------


def standup(db: Database, now: datetime | None = None) -> list[dict[str, Any]]:
    """A round of the table: each one says what it did since yesterday, does now, and what
    blocks it. Only facts from the records."""
    now = now or datetime.now(UTC)
    day = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    rows = db.all("SELECT * FROM activity WHERE ts >= ? ORDER BY id", (day,))
    states = {s["key"]: s for s in statuses(db, now)}
    missions = db.all("SELECT status FROM missions WHERE updated_at >= ?", (day,))
    said: list[tuple[str, str]] = [
        (
            LEAD,
            "Bonjour à tous. Petit tour de table : chacun dit ce qu'il a fait depuis hier, "
            "ce qu'il fait maintenant, et ce qui le bloque.",
        )
    ]
    for member in members(db):
        key = member["key"]
        if key == LEAD:
            continue
        mine = [r for r in rows if r["agent"] == key]
        done = [r for r in mine if r["kind"] == "step_done"]
        ok = [r for r in done if r["status"] == "ok"]
        state = states.get(key, {})
        if key == VERIFIER:
            checked = [r for r in rows if r["kind"] == "step_done"]
            refused = sum(1 for r in checked if r["status"] != "ok")
            text = (
                f"J'ai vérifié {len(checked)} étape{'s' if len(checked) > 1 else ''} : "
                f"{len(checked) - refused} validée{'s' if len(checked) - refused > 1 else ''}"
                f"{f', {refused} à revoir' if refused else ''}."
                if checked
                else "Aucune étape à vérifier depuis hier."
            )
        elif not mine and state.get("status") == "available":
            text = "Rien pour moi depuis hier, je suis disponible."
        else:
            parts = []
            if done:
                parts.append(
                    f"Depuis hier, j'ai bouclé {len(ok)} étape{'s' if len(ok) > 1 else ''}"
                    + (f" sur {len(done)}" if len(done) != len(ok) else "")
                    + (f", dont « {_short(ok[-1]['title'], 70)} »" if ok else "")
                    + "."
                )
            elif mine:
                tools = sum(1 for r in mine if r["kind"] == "tool")
                parts.append(f"Depuis hier, j'ai utilisé {tools} outil{'s' if tools > 1 else ''}.")
            if state.get("status") in ("working", "stalled"):
                parts.append(f"En ce moment : {state.get('activity')}.")
            else:
                parts.append("Rien en cours.")
            parts.append(
                f"Je bloque : {state.get('activity')}."
                if state.get("status") == "needs_you"
                else "Pas de blocage."
            )
            text = " ".join(parts)
        said.append((key, text))
    finished = sum(1 for m in missions if m["status"] == "done")
    active = sum(1 for m in missions if m["status"] in ("running", "queued"))
    waiting = sum(1 for s in states.values() if s["status"] == "needs_you")
    plural = "s" if finished > 1 else ""
    close = f"Merci à tous. {finished} mission{plural} terminée{plural}"
    close += f", {active} en cours." if active else "."
    if waiting:
        close += f" {waiting} d'entre nous attend{'ent' if waiting > 1 else ''} ton accord."
    said.append((LEAD, close))
    stamp = now.isoformat(timespec="seconds")
    return [
        {"id": f"s{i}", "ts": stamp, "agent": who, "text": text, "kind": "standup"}
        for i, (who, text) in enumerate(said)
    ]


# ---- recap, tree, board, replay ----------------------------------------------------------------


def recap(db: Database, *, mission: int | None = None, hours: float = 24.0) -> str:
    """A ready-to-paste stand-up report in Markdown: who did what, files, tokens, results."""
    now = datetime.now(UTC)
    if mission is not None:
        rows = activity.rows(db, mission=mission, limit=5000)
        missions = db.all("SELECT * FROM missions WHERE id = ?", (mission,))
        head = f"# Compte rendu de la mission #{mission}"
    else:
        since = (now - timedelta(hours=hours)).isoformat(timespec="seconds")
        rows = db.all("SELECT * FROM activity WHERE ts >= ? ORDER BY id", (since,))
        missions = db.all("SELECT * FROM missions WHERE updated_at >= ? ORDER BY id", (since,))
        head = f"# Point d'équipe du {now.astimezone().strftime('%d/%m/%Y %H:%M')}"
    names = _names(db)
    ledger = db.all(
        "SELECT agent, SUM(tokens) AS tokens, SUM(cost_usd) AS cost, SUM(seconds) AS seconds "
        "FROM usage_ledger WHERE ts >= ? GROUP BY agent",
        ((now - timedelta(hours=hours)).isoformat(timespec="seconds"),),
    )
    spent = {r["agent"]: r for r in ledger}
    tools = [r for r in rows if r["kind"] == "tool"]
    steps = [r for r in rows if r["kind"] == "step_done"]
    out = [
        head,
        "",
        f"- Missions : {len(missions)} ; étapes : {len(steps)} "
        f"({sum(1 for s in steps if s['status'] == 'ok')} vérifiées) ; "
        f"appels d'outils : {len(tools)} "
        f"({sum(1 for t in tools if t['status'] == 'fail')} en échec)",
        f"- Jetons : {sum(int(r['tokens'] or 0) for r in ledger)} ; coût équivalent API : "
        f"{sum(float(r['cost'] or 0) for r in ledger):.2f} $",
        "",
        "## Par agent",
        "",
    ]
    agents = sorted({r["agent"] for r in rows if r["agent"]} | set(spent) - {""})
    for key in agents:
        mine = [r for r in rows if r["agent"] == key]
        done = [r for r in mine if r["kind"] == "step_done"]
        files = sorted(
            {
                _detail(r).get("target", "")
                for r in mine
                if r["kind"] == "tool" and r["title"] in ("write_file", "append_file", "edit_file")
            }
            - {""}
        )
        cost = spent.get(key) or {}
        line = (
            f"- **{names.get(key, key)}** : {sum(1 for d in done if d['status'] == 'ok')}/"
            f"{len(done)} étapes vérifiées, {sum(1 for r in mine if r['kind'] == 'tool')} outils, "
            f"{int(cost.get('tokens') or 0)} jetons"
        )
        out.append(line)
        out += [
            f"  - {_short(d['title'], 140)} ({'✓' if d['status'] == 'ok' else '✗'})" for d in done
        ]
        if files:
            out.append(f"  - Fichiers : {', '.join(files[:12])}")
    if missions:
        out += ["", "## Missions", ""]
        for m in missions:
            report = " ".join(str(m.get("report") or m.get("error") or "").split())[:300]
            out.append(f"- #{m['id']} {_short(m['goal'], 120)} — {m['status']}")
            if report:
                out.append(f"  - {report}")
    return "\n".join(out) + "\n"


def tree(db: Database, hours: float = 24.0) -> dict[str, Any]:
    """Who asked whom: you → Spectre → missions → the agents who ran their steps."""
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
    names = _names(db)
    states = {s["key"]: s for s in statuses(db)}
    missions = db.all(
        "SELECT id, goal, status FROM missions WHERE updated_at >= ? OR status IN "
        "('running', 'queued') ORDER BY id DESC LIMIT 20",
        (since,),
    )
    children = []
    for m in missions:
        rows = activity.rows(db, mission=m["id"], limit=2000)
        agents = []
        for key in dict.fromkeys(r["agent"] for r in rows if r["agent"] and r["agent"] != LEAD):
            mine = [r for r in rows if r["agent"] == key]
            agents.append(
                {
                    "key": key,
                    "name": names.get(key, key),
                    "status": states.get(key, {}).get("status", ""),
                    "tools": sum(1 for r in mine if r["kind"] == "tool"),
                    "steps": sum(1 for r in mine if r["kind"] == "step_done"),
                    "activity": states.get(key, {}).get("activity", ""),
                }
            )
        children.append(
            {"mission": m["id"], "goal": m["goal"], "status": m["status"], "agents": agents}
        )
    lead = states.get(LEAD, {})
    return {
        "you": {"name": "Toi"},
        "lead": {
            "key": LEAD,
            "name": names[LEAD],
            "status": lead.get("status", ""),
            "activity": lead.get("activity", ""),
        },
        "missions": children,
    }


def board(db: Database, hours: float = 12.0) -> list[dict[str, Any]]:
    """Spectre's missions of the last hours by state, the ones waiting for you first."""
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
    missions = db.all(
        "SELECT id, ts, goal, status, updated_at FROM missions WHERE updated_at >= ? "
        "OR status IN ('running', 'queued') ORDER BY id DESC LIMIT 60",
        (since,),
    )
    waiting = {
        r["mission_id"]
        for r in db.all(
            "SELECT DISTINCT mission_id FROM activity WHERE kind = 'approval' AND ts >= ?", (since,)
        )
        if r["mission_id"]
    }
    pending = bool(db.one("SELECT 1 FROM approvals WHERE status = 'pending'"))
    names = _names(db)
    out = []
    for m in missions:
        state = m["status"]
        if state == "running" and m["id"] in waiting and pending:
            state = "needs_you"
        agents = [
            names.get(r["agent"], r["agent"])
            for r in db.all(
                "SELECT DISTINCT agent FROM activity WHERE mission_id = ? AND kind = 'step_start'",
                (m["id"],),
            )
        ]
        out.append({**m, "state": state, "agents": agents})
    order = {"needs_you": 0, "running": 1, "queued": 2, "failed": 3, "done": 4, "cancelled": 5}
    out.sort(key=lambda m: (order.get(m["state"], 9), -m["id"]))
    return out


def replay(db: Database, mission: int) -> dict[str, Any]:
    """A finished (or running) mission, line by line, for the call's replay."""
    rows = activity.rows(db, mission=mission, limit=5000)
    row = db.one("SELECT id, goal, status, ts FROM missions WHERE id = ?", (mission,))
    lines = [line for r in rows for line in lines_for(r)]
    tools = [
        {
            "ts": r["ts"],
            "agent": r["agent"] or LEAD,
            "tool": r["title"],
            "target": _detail(r).get("target", ""),
            "result": _detail(r).get("result", ""),
            "status": r["status"],
            "seconds": r["seconds"],
        }
        for r in rows
        if r["kind"] == "tool"
    ]
    highlights = []
    first_error = next((r for r in rows if r["status"] == "fail"), None)
    if first_error:
        highlights.append({"ts": first_error["ts"], "label": "première erreur"})
    steps = [r for r in rows if r["kind"] == "step_done"]
    if steps:
        longest = max(steps, key=lambda r: r["seconds"] or 0)
        highlights.append(
            {"ts": longest["ts"], "label": f"étape la plus longue ({round(longest['seconds'])} s)"}
        )
    asks = [r for r in rows if r["kind"] == "approval"]
    if asks:
        highlights.append({"ts": asks[0]["ts"], "label": "attente de ton accord"})
    return {"mission": row, "lines": lines, "tools": tools, "highlights": highlights}
