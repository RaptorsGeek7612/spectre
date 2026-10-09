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
from spectre.graph import build_graph
from spectre.llm import make_chat_model
from spectre.state import UsageRecord
from spectre.verdict import VerdictFilter
from spectre.web.demo import DemoChatModel

# Only these per-agent overrides may come from the browser (presets).
_OVERRIDE_KEY = re.compile(r"^SPECTRE_(SCOUT|SCRIBE|WARDEN)_(MODEL|MAX_TOKENS|EFFORT)$")
_OUTPUT_KEY = {"scout": "brief", "scribe": "draft", "warden": "final_text"}

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
) -> Iterator[Event]:
    """Yield `agent_start`, `token`, `agent_done`, then `done` (or `error` / `cancelled`).

    After a rejection by Warden, Scribe and Warden run again: their `agent_start` then carry
    `revision` (1, 2...). Warden's tokens never include its verdict line.
    """
    cancel = cancel or threading.Event()
    outputs: dict[str, str] = {}
    usage: list[UsageRecord] = []
    durations: dict[str, float] = {}
    verdict: dict[str, Any] = {"approved": True, "issues": [], "revisions": 0}
    order = list(AGENT_NAMES)
    current: str | None = order[0]
    hide_verdict = VerdictFilter()
    started = time.monotonic()
    try:
        resolved = dict(models) if models is not None else None
        if resolved is None:
            resolved = build_models(demo=demo, overrides=clean_overrides(overrides), delay=delay)
        rounds = (
            load_max_revisions() if max_revisions is None else check_max_revisions(max_revisions)
        )
        graph = build_graph(resolved, max_revisions=rounds)
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
                if text and meta.get("langgraph_node") == current:
                    if current == "warden":
                        text = hide_verdict.feed(text)
                    if text:
                        yield {"type": "token", "agent": current, "text": text}
                continue
            for node, update in cast(dict[str, dict[str, Any]], chunk).items():
                if node not in _OUTPUT_KEY or not update:  # pragma: no cover - defensive
                    continue
                if node == "warden":
                    rest = hide_verdict.flush()
                    if rest:
                        yield {"type": "token", "agent": node, "text": rest}
                    hide_verdict = VerdictFilter()
                    verdict["approved"] = update.get("approved", True)
                    verdict["issues"] = list(update.get("issues", []))
                verdict["revisions"] = update.get("revisions", verdict["revisions"])
                outputs[_OUTPUT_KEY[node]] = update[_OUTPUT_KEY[node]]
                records = list(update.get("usage", []))
                usage.extend(records)
                now = time.monotonic()
                elapsed = round(now - started, 3)
                durations[node] = round(durations.get(node, 0.0) + elapsed, 3)  # all rounds
                started = now
                done: Event = {
                    "type": "agent_done",
                    "agent": node,
                    "text": outputs[_OUTPUT_KEY[node]],
                    "usage": records[0] if records else None,
                    "seconds": elapsed,
                }
                if node == "warden":
                    done["approved"], done["issues"] = verdict["approved"], verdict["issues"]
                yield done
                current = _next_agent(node, verdict, rounds)
                if current is not None:
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


def _next_agent(node: str, verdict: Mapping[str, Any], rounds: int) -> str | None:
    """The agent that runs after `node` (the graph's own routing, seen from the stream)."""
    if node == "scout":
        return "scribe"
    if node == "scribe":
        return "warden"
    if verdict["approved"] is False and verdict["revisions"] < rounds:
        return "scribe"
    return None


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
