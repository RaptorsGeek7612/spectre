"""The coding agents' own sessions, as a team on the video call: Claude Code, Codex and Mistral
Vibe, with their sub-agents (the idea of Agent Standup, read from the same files).

Each tool already writes its sessions on this PC, so nothing is asked of them and no model is
called: Claude Code in `~/.claude/projects/<project>/<session>.jsonl` (sub-agents in
`<session>/subagents/agent-*.jsonl`), Codex in `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`
(one file per thread; sub-agents share the lead's `session_id`), Vibe in
`~/.vibe/logs/session/<session>/{meta.json,messages.jsonl}` (children name their parent).
Files are only read, never written; a long session is read from its end.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HEAD = 96_000  # bytes read from a session's start (its first request: the title)
TAIL = 400_000  # bytes read from its end (what is going on now)
NEEDS_YOU_S = 15  # a file edit or a question pending longer than this probably waits for you
IDLE_S = 15 * 60
ASKS_YOU = {"Edit", "Write", "MultiEdit", "NotebookEdit", "AskUserQuestion", "ExitPlanMode"}
SPAWNS = {"Task", "Agent"}
STATE_ORDER = {"needs_you": 0, "working": 1, "waiting": 2, "your_turn": 3, "idle": 4}


@dataclass
class Roots:
    """Where each tool keeps its sessions (overridable for tests and odd installs)."""

    claude: Path
    codex: Path
    vibe: list[Path] = field(default_factory=list)

    @classmethod
    def default(cls, assistant_root: Path | None = None) -> Roots:
        home = Path.home()
        claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude") / "projects"
        codex = Path(os.environ.get("CODEX_HOME") or home / ".codex") / "sessions"
        vibe = [Path(os.environ.get("VIBE_HOME") or home / ".vibe") / "logs" / "session"]
        if assistant_root is not None:  # Syfer's own Vibe home, inside Spectre's folder
            vibe.append(assistant_root / "vibe" / "logs" / "session")
        return cls(claude, codex, vibe)


# ---- small helpers -----------------------------------------------------------------------------


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _iso(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC).isoformat(timespec="seconds")
    return str(value or "")


def _age(iso: str, now: datetime) -> float:
    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 1e9
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (now - moment).total_seconds()


def _lines(path: Path, *, whole: bool = False) -> list[dict[str, Any]]:
    """JSON lines of a file: all of it, or its start and its end when it is long."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if whole or size <= HEAD + TAIL:
                raw = handle.read()
            else:
                raw = handle.read(HEAD)
                raw = raw[: raw.rfind(b"\n") + 1]
                handle.seek(size - TAIL)
                tail = handle.read()
                raw += tail[tail.find(b"\n") + 1 :]
    except OSError:
        return []
    found = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            found.append(item)
    return found


def _text(content: Any) -> str:
    """The words of a message, whatever the tool's block format."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") in (
                "text",
                "input_text",
                "output_text",
            ):
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return ""


def _target(args: Any) -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return str(args).strip().replace("\n", " ")[:140]
    if not isinstance(args, dict):
        return ""
    for key in ("file_path", "path", "command", "cmd", "pattern", "url", "query", "description"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().replace("\n", " ")[:140]
    return ""


def _human(text: str) -> bool:
    """A request typed by the user (not a context block the tool injected)."""
    stripped = text.strip()
    return bool(stripped) and not stripped.startswith(("<", "[", "{", "#", "Caveat:"))


def _event(ts: str, agent: str, kind: str, text: str = "", **extra: Any) -> dict[str, Any]:
    return {"ts": ts, "agent": agent, "kind": kind, "text": text[:2000], **extra}


def _agent(agent_id: str, name: str, *, lead: bool, model: str = "") -> dict[str, Any]:
    return {
        "id": agent_id,
        "name": name,
        "lead": lead,
        "model": model,
        "status": "idle",
        "activity": "",
        "tokens": 0,
        "tools": 0,
        "fails": 0,
        "last": "",
    }


def _settle(agent: dict[str, Any], events: list[dict[str, Any]], now: datetime) -> None:
    """An agent's status from its own last events."""
    mine = [e for e in events if e["agent"] == agent["id"]]
    if not mine:
        return
    last = mine[-1]
    agent["last"] = last["ts"]
    agent["tools"] = sum(1 for e in mine if e["kind"] == "tool")
    agent["fails"] = sum(1 for e in mine if e["kind"] == "result" and not e.get("ok", True))
    pending = [e for e in mine if e["kind"] == "tool" and not e.get("done")]
    age = _age(last["ts"], now)
    if pending:
        tool = pending[-1]
        agent["activity"] = f"{tool.get('tool', '')} {tool['text']}".strip()
        waiting = tool.get("tool") in ASKS_YOU and _age(tool["ts"], now) > NEEDS_YOU_S
        agent["status"] = "needs_you" if waiting else "working"
    elif last["kind"] in ("report", "say") and age < IDLE_S:
        agent["status"] = "your_turn" if agent["lead"] else "done"
        agent["activity"] = last["text"][:140]
    elif last["kind"] in ("user", "order", "result") and age < IDLE_S:
        agent["status"] = "working"
        agent["activity"] = "réfléchit…"
    if age >= IDLE_S:  # nothing for a quarter of an hour: whatever was pending is over
        agent["status"] = "idle" if agent["lead"] else "done"


def _close_tools(events: list[dict[str, Any]]) -> None:
    """Mark each tool call whose result came back (matched by its call id)."""
    results = {e.get("call") for e in events if e["kind"] == "result"}
    for event in events:
        if event["kind"] == "tool" and event.get("call") in results:
            event["done"] = True


def _session(
    tool: str,
    sid: str,
    title: str,
    project: str,
    agents: list[dict[str, Any]],
    events: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    events.sort(key=lambda e: e["ts"])
    _close_tools(events)
    answered = {e.get("call") for e in events if e["kind"] == "result"}
    for agent in agents:
        _settle(agent, events, now)
        if agent.pop("spawned_by", None) in answered:  # its lead got the report: it left
            agent["status"] = "done"
    lead_last = max((e["ts"] for e in events if e["agent"] == "lead"), default="")
    for agent in agents:  # a helper silent for 2 min while its lead went on has left the call
        if (
            not agent["lead"]
            and agent["last"]
            and _age(agent["last"], now) - _age(lead_last or agent["last"], now) > 120
        ):
            agent["status"] = "done"
    lead = next((a for a in agents if a["lead"]), agents[0] if agents else None)
    states = [a["status"] for a in agents]
    if "needs_you" in states:
        state = "needs_you"
    elif lead and lead["status"] == "working":
        state = "working"
    elif any(a["status"] == "working" for a in agents if not a["lead"]):
        state = "waiting"  # the lead waits on its sub-agents
    else:
        state = lead["status"] if lead else "idle"
    if state == "done":
        state = "your_turn"
    updated = max((e["ts"] for e in events), default="")
    return {
        "id": sid,
        "tool": tool,
        "title": title or "(sans titre)",
        "project": project,
        "updated": updated,
        "state": state,
        "agents": agents,
        "events": events,
    }


# ---- Claude Code -------------------------------------------------------------------------------


def _claude_events(lines: list[dict[str, Any]], agent_id: str, agent: dict[str, Any]) -> list[Any]:
    events: list[dict[str, Any]] = []
    tokens = 0
    for item in lines:
        ts = str(item.get("timestamp", ""))
        message = _dict(item.get("message"))
        content = message.get("content")
        if item.get("type") == "user":
            if isinstance(content, str):
                if _human(content):
                    events.append(
                        _event(ts, agent_id, "user" if agent["lead"] else "order", content)
                    )
                continue
            for block in content or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    out = block.get("content")
                    text = out if isinstance(out, str) else _text(out)
                    events.append(
                        _event(
                            ts,
                            agent_id,
                            "result",
                            text,
                            call=block.get("tool_use_id"),
                            ok=not block.get("is_error"),
                        )
                    )
                elif (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and _human(str(block.get("text", "")))
                ):
                    kind = "user" if agent["lead"] else "order"
                    events.append(_event(ts, agent_id, kind, str(block["text"])))
        elif item.get("type") == "assistant":
            agent["model"] = str(message.get("model") or agent["model"])
            usage = message.get("usage") or {}
            tokens += sum(
                int(usage.get(k) or 0)
                for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens")
            )
            for block in content or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and str(block.get("text", "")).strip():
                    events.append(_event(ts, agent_id, "say", str(block["text"])))
                elif block.get("type") == "tool_use":
                    name = str(block.get("name", ""))
                    events.append(
                        _event(
                            ts,
                            agent_id,
                            "tool",
                            _target(block.get("input")),
                            tool=name,
                            call=block.get("id"),
                            spawn=name in SPAWNS,
                            args=json.dumps(block.get("input"), ensure_ascii=False)[:1500],
                        )
                    )
    agent["tokens"] = tokens
    return events


def _claude(roots: Roots, since: datetime, now: datetime, only: str = "") -> list[Any]:
    found: list[dict[str, Any]] = []
    if not roots.claude.is_dir():
        return found
    for path in roots.claude.glob("*/*.jsonl"):
        if only and path.stem != only:
            continue
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, UTC) < since:
                continue
        except OSError:
            continue
        lines = _lines(path, whole=bool(only))
        cwd = next((str(i.get("cwd")) for i in lines if i.get("cwd")), path.parent.name)
        title = next(
            (
                str(i["message"]["content"]).strip()[:90]
                for i in lines
                if i.get("type") == "user"
                and isinstance(i.get("message"), dict)
                and isinstance(i["message"].get("content"), str)
                and _human(i["message"]["content"])
            ),
            "",
        )
        lead = _agent("lead", "Claude", lead=True)
        events = _claude_events(lines, "lead", lead)
        agents = [lead]
        sub = path.parent / path.stem / "subagents"
        for file in sorted(sub.glob("agent-*.jsonl")) if sub.is_dir() else []:
            try:
                meta = json.loads(file.with_suffix(".meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
            name = str(meta.get("description") or meta.get("agentType") or file.stem)[:40]
            helper = _agent(file.stem, name, lead=False)
            helper["spawned_by"] = meta.get("toolUseId")
            events += _claude_events(_lines(file, whole=bool(only)), file.stem, helper)
            agents.append(helper)
        found.append(_session("claude", path.stem, title, cwd, agents, events, now))
    return found


# ---- Codex -------------------------------------------------------------------------------------


def _codex_thread(lines: list[dict[str, Any]], agent_id: str, agent: dict[str, Any]) -> list[Any]:
    events: list[dict[str, Any]] = []
    for item in lines:
        ts = str(item.get("timestamp", ""))
        payload = _dict(item.get("payload"))
        kind = payload.get("type")
        if item.get("type") == "response_item":
            if kind == "message":
                text = _text(payload.get("content"))
                if payload.get("role") == "assistant" and text.strip():
                    events.append(_event(ts, agent_id, "say", text))
                elif payload.get("role") == "user" and _human(text):
                    events.append(_event(ts, agent_id, "user" if agent["lead"] else "order", text))
            elif kind in ("function_call", "custom_tool_call"):
                args = payload.get("arguments") if kind == "function_call" else payload.get("input")
                events.append(
                    _event(
                        ts,
                        agent_id,
                        "tool",
                        _target(args),
                        tool=str(payload.get("name", "")),
                        call=payload.get("call_id"),
                        args=str(args or "")[:1500],
                    )
                )
            elif kind in ("function_call_output", "custom_tool_call_output"):
                out = payload.get("output")
                text = out if isinstance(out, str) else _text(out)
                events.append(_event(ts, agent_id, "result", text, call=payload.get("call_id")))
            elif kind == "agent_message" and payload.get("recipient"):
                target = str(payload["recipient"]).rsplit("/", 1)[-1]
                events.append(_event(ts, agent_id, "order", f"Nouvelle tâche pour {target}"))
        elif item.get("type") == "event_msg":
            if kind == "token_count":
                info = payload.get("info") or {}
                total = (info.get("total_token_usage") or {}).get("total_tokens")
                if isinstance(total, int):
                    agent["tokens"] = total
            elif kind == "task_complete" and payload.get("last_agent_message"):
                events.append(_event(ts, agent_id, "report", str(payload["last_agent_message"])))
        elif item.get("type") == "turn_context":
            agent["model"] = str(payload.get("model") or agent["model"])
    return events


def _codex(roots: Roots, since: datetime, now: datetime, only: str = "") -> list[Any]:
    if not roots.codex.is_dir():
        return []
    groups: dict[str, list[tuple[dict[str, Any], list[dict[str, Any]]]]] = {}
    for path in roots.codex.glob("*/*/*/*.jsonl"):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, UTC) < since:
                continue
        except OSError:
            continue
        lines = _lines(path, whole=bool(only))
        meta: dict[str, Any] = next(
            (
                i["payload"]
                for i in lines
                if i.get("type") == "session_meta" and isinstance(i.get("payload"), dict)
            ),
            {},
        )
        if meta.get("thread_source") == "guardian_review":  # Codex's own reviewer, not a teammate
            continue
        session = str(meta.get("session_id") or meta.get("id") or path.stem)
        if only and session != only:
            continue
        groups.setdefault(session, []).append((meta, lines))
    found = []
    for session, threads in groups.items():
        agents, events, title, project = [], [], "", ""
        for meta, lines in threads:
            lead = meta.get("thread_source") != "subagent"
            agent_id = "lead" if lead else str(meta.get("id", ""))
            name = (
                "Codex"
                if lead
                else str(
                    meta.get("agent_nickname") or str(meta.get("agent_path", "")).rsplit("/", 1)[-1]
                )
            )
            agent = _agent(agent_id, name, lead=lead)
            thread = _codex_thread(lines, agent_id, agent)
            events += thread
            agents.append(agent)
            project = project or str(meta.get("cwd", ""))
            if lead and not title:
                title = next((e["text"][:90] for e in thread if e["kind"] == "user"), "")
        if not any(a["lead"] for a in agents):
            agents.insert(0, _agent("lead", "Codex", lead=True))
        agents.sort(key=lambda a: not a["lead"])
        found.append(_session("codex", session, title, project, agents, events, now))
    return found


# ---- Mistral Vibe ------------------------------------------------------------------------------


def _vibe_events(
    folder: Path, agent_id: str, agent: dict[str, Any], meta: dict[str, Any]
) -> list[Any]:
    lines = _lines(folder / "messages.jsonl")
    start, end = str(meta.get("start_time", "")), str(meta.get("end_time") or "")
    try:
        t0 = datetime.fromisoformat(start)
        t1 = datetime.fromisoformat(end) if end else datetime.now(UTC)
    except ValueError:
        t0 = t1 = datetime.now(UTC)
    span = max((t1 - t0).total_seconds(), 1.0)
    events: list[dict[str, Any]] = []
    for index, item in enumerate(lines):  # Vibe keeps no time per message: spread them out
        ts = (t0 + timedelta(seconds=span * index / max(len(lines), 1))).isoformat(
            timespec="seconds"
        )
        role = item.get("role")
        text = _text(item.get("content"))
        if role == "user" and _human(text) and not item.get("injected"):
            events.append(_event(ts, agent_id, "user" if agent["lead"] else "order", text))
        elif role == "assistant":
            if text.strip():
                events.append(_event(ts, agent_id, "say", text))
            for call in item.get("tool_calls") or []:
                function = call.get("function") or {}
                events.append(
                    _event(
                        ts,
                        agent_id,
                        "tool",
                        _target(function.get("arguments")),
                        tool=str(function.get("name", "")),
                        call=call.get("id"),
                        args=str(function.get("arguments") or "")[:1500],
                    )
                )
        elif role == "tool":
            events.append(_event(ts, agent_id, "result", text, call=item.get("tool_call_id")))
    if end and events and events[-1]["kind"] == "say":
        events[-1]["kind"] = "report"
    return events


def _vibe(roots: Roots, since: datetime, now: datetime, only: str = "") -> list[Any]:
    metas: dict[str, tuple[Path, dict[str, Any]]] = {}
    for base in roots.vibe:
        if not base.is_dir():
            continue
        for folder in base.iterdir():
            meta_path = folder / "meta.json"
            try:
                if datetime.fromtimestamp(meta_path.stat().st_mtime, UTC) < since and not only:
                    continue
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(meta, dict):
                metas[str(meta.get("session_id") or folder.name)] = (folder, meta)
    found = []
    for sid, (folder, meta) in metas.items():
        if meta.get("parent_session_id") in metas or (only and sid != only):
            continue  # a child is shown inside its parent's call
        lead = _agent("lead", "Vibe", lead=True)
        events = _vibe_events(folder, "lead", lead, meta)
        agents = [lead]
        for cid, (child_folder, child) in metas.items():
            if child.get("parent_session_id") == sid:
                name = str(child.get("title") or child.get("agent_name") or f"Agent {cid[:6]}")
                helper = _agent(cid, name[:40], lead=False)
                events += _vibe_events(child_folder, cid, helper, child)
                agents.append(helper)
        title = next((e["text"][:90] for e in events if e["kind"] == "user"), "")
        project = str((meta.get("environment") or {}).get("working_directory", ""))
        if meta.get("end_time"):
            lead["status"] = "your_turn"
        found.append(_session("vibe", sid, title, project, agents, events, now))
    return found


# ---- public ------------------------------------------------------------------------------------

READERS = {"claude": _claude, "codex": _codex, "vibe": _vibe}
TOOL_LABELS = {"claude": "Claude Code", "codex": "Codex", "vibe": "Mistral Vibe"}


def scan(roots: Roots, hours: float = 12.0, now: datetime | None = None) -> list[dict[str, Any]]:
    """The sessions active in the last hours, most urgent first, without their events."""
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=hours)
    found: list[dict[str, Any]] = []
    for reader in READERS.values():
        try:
            found += reader(roots, since, now)
        except OSError:
            continue
    found.sort(key=lambda s: (STATE_ORDER.get(s["state"], 9), _age(s["updated"], now)))
    return [
        {**{k: v for k, v in s.items() if k != "events"}, "label": TOOL_LABELS[s["tool"]]}
        for s in found
    ]


def timeline(
    roots: Roots, tool: str, sid: str, now: datetime | None = None
) -> dict[str, Any] | None:
    """One session in full, with its events in order, for the call and its replay."""
    reader = READERS.get(tool)
    if reader is None:
        return None
    now = now or datetime.now(UTC)
    found = reader(roots, datetime(1970, 1, 1, tzinfo=UTC), now, sid)
    if not found:
        return None
    session: dict[str, Any] = found[0]
    session["label"] = TOOL_LABELS[tool]
    session["events"] = session["events"][-2000:]
    return session
