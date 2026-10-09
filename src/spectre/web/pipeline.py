"""Run the Spectre graph and turn it into a stream of UI events (one dict per event)."""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Iterator, Mapping
from typing import Any, cast

from langchain_core.language_models import BaseChatModel

from spectre.config import (
    AGENT_NAMES,
    check_max_revisions,
    has_api_key,
    load_client_settings,
    load_env,
    load_max_revisions,
    load_specs,
)
from spectre.costs import total_cost
from spectre.errors import ConfigurationError, MissingAPIKeyError, SpectreError
from spectre.graph import build_graph, next_step, pipeline_steps
from spectre.llm import make_chat_model
from spectre.plugins import load_extra_agents
from spectre.state import UsageRecord
from spectre.verdict import VerdictFilter
from spectre.web.demo import DemoChatModel

# Only these per-agent overrides may come from the browser (presets).
_OVERRIDE_KEY = re.compile(r"^SPECTRE_(SCOUT|SCRIBE|WARDEN)_(MODEL|MAX_TOKENS|EFFORT)$")

Event = dict[str, Any]


class RunCancelled(Exception):
    """The user stopped the run from the UI."""


def clean_overrides(overrides: Mapping[str, Any] | None) -> dict[str, str]:
    """Keep only valid `SPECTRE_<AGENT>_*` keys with non-empty string values."""
    cleaned: dict[str, str] = {}
    for key, value in (overrides or {}).items():
        if not _OVERRIDE_KEY.match(str(key)):
            raise ConfigurationError(f"réglage non autorisé : {key!r}")
        text = str(value).strip()
        if text:
            cleaned[str(key)] = text
    return cleaned


def build_models(
    *, demo: bool, overrides: Mapping[str, str], delay: float = 0.0
) -> dict[str, BaseChatModel]:
    """Real `ChatAnthropic` clients (key required), or demo models that need nothing."""
    if not demo:
        load_env()
    specs = load_specs({**os.environ, **overrides})
    if demo:
        return {
            name: DemoChatModel(agent=name, model=specs[name].model, delay=delay)
            for name in AGENT_NAMES
        }
    if not has_api_key():
        raise MissingAPIKeyError()
    settings = load_client_settings()
    return {name: make_chat_model(specs[name], settings) for name in AGENT_NAMES}


def stream_run(
    request: str,
    *,
    demo: bool,
    overrides: Mapping[str, str] | None = None,
    cancel: threading.Event | None = None,
    delay: float = 0.0,
    models: Mapping[str, BaseChatModel] | None = None,
    max_revisions: int | None = None,
    include_extras: bool = False,
) -> Iterator[Event]:
    """Yield `agent_start`, `token`, `agent_done`, then `done` (or `error` / `cancelled`).

    After a rejection by Warden, Scribe and Warden run again: their `agent_start` then carry
    `revision` (1, 2...). Warden's tokens never include its verdict line. Agents added in
    `spectre-agents.toml` run too (not in demo mode); their events are only sent when
    `include_extras` is set, since the web UI draws the three core agents.
    """
    cancel = cancel or threading.Event()
    outputs: dict[str, str] = {}
    usage: list[UsageRecord] = []
    durations: dict[str, float] = {}
    verdict: dict[str, Any] = {"approved": True, "issues": [], "revisions": 0}
    current: str | None = AGENT_NAMES[0]
    hide_verdict = VerdictFilter()
    started = time.monotonic()
    try:
        resolved = dict(models) if models is not None else None
        if resolved is None:
            resolved = build_models(demo=demo, overrides=clean_overrides(overrides), delay=delay)
        rounds = (
            load_max_revisions() if max_revisions is None else check_max_revisions(max_revisions)
        )
        extras = [] if demo else load_extra_agents()
        writes = {step.name: step.writes for step in pipeline_steps(extras)}
        order = list(writes)

        def shown(agent: str) -> bool:
            return include_extras or agent in AGENT_NAMES

        graph = build_graph(resolved, max_revisions=rounds, extra_agents=extras)
        yield {"type": "agent_start", "agent": current}
        stream = graph.stream(
            {"request": request.strip(), "usage": [], "revisions": 0},
            stream_mode=["updates", "messages"],
        )
        for mode, chunk in stream:
            if cancel.is_set():
                raise RunCancelled
            if mode == "messages":
                message, meta = cast(tuple[Any, dict[str, Any]], chunk)
                text = str(getattr(message, "text", "") or "")
                if text and current is not None and meta.get("langgraph_node") == current:
                    if not shown(current):
                        continue
                    if current == "warden":
                        text = hide_verdict.feed(text)
                    if text:
                        yield {"type": "token", "agent": current, "text": text}
                continue
            for node, update in cast(dict[str, dict[str, Any]], chunk).items():
                if node not in writes or not update:  # pragma: no cover - defensive
                    continue
                if node == "warden":
                    rest = hide_verdict.flush()
                    if rest:
                        yield {"type": "token", "agent": node, "text": rest}
                    hide_verdict = VerdictFilter()
                    verdict["approved"] = update.get("approved", True)
                    verdict["issues"] = list(update.get("issues", []))
                verdict["revisions"] = update.get("revisions", verdict["revisions"])
                outputs[writes[node]] = update[writes[node]]
                records = list(update.get("usage", []))
                usage.extend(records)
                now = time.monotonic()
                elapsed = round(now - started, 3)
                durations[node] = round(durations.get(node, 0.0) + elapsed, 3)  # all rounds
                started = now
                done: Event = {
                    "type": "agent_done",
                    "agent": node,
                    "text": outputs[writes[node]],
                    "usage": records[0] if records else None,
                    "seconds": elapsed,
                }
                if node == "warden":
                    done["approved"], done["issues"] = verdict["approved"], verdict["issues"]
                if shown(node):
                    yield done
                current = next_step(order, node, verdict, rounds)
                if current is not None and shown(current):
                    start: Event = {"type": "agent_start", "agent": current}
                    if current != "scout" and verdict["approved"] is False:
                        start["revision"] = verdict["revisions"] + (current == "scribe")
                    yield start
    except RunCancelled:
        yield {"type": "cancelled", "agent": current, **_partial(outputs, usage, durations)}
        return
    except SpectreError as exc:
        yield {
            "type": "error",
            "agent": exc.agent or current,
            "message": str(exc),
            **_partial(outputs, usage, durations),
        }
        return
    yield {"type": "done", **_partial(outputs, usage, durations), **verdict}


def _partial(
    outputs: Mapping[str, str], usage: list[UsageRecord], durations: Mapping[str, float]
) -> Event:
    return {
        "brief": outputs.get("brief", ""),
        "draft": outputs.get("draft", ""),
        "final_text": outputs.get("final_text", ""),
        "usage": [dict(record) for record in usage],
        "total_cost_usd": total_cost(usage),
        "durations": dict(durations),
    }
