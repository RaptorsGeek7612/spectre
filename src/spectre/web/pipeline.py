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
    has_api_key,
    load_client_settings,
    load_env,
    load_specs,
)
from spectre.costs import total_cost
from spectre.errors import ConfigurationError, MissingAPIKeyError, SpectreError
from spectre.graph import build_graph
from spectre.llm import make_chat_model
from spectre.state import UsageRecord
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
) -> Iterator[Event]:
    """Yield `agent_start`, `token`, `agent_done`, then `done` (or `error` / `cancelled`)."""
    cancel = cancel or threading.Event()
    outputs: dict[str, str] = {}
    usage: list[UsageRecord] = []
    durations: dict[str, float] = {}
    order = list(AGENT_NAMES)
    current = order[0]
    started = time.monotonic()
    try:
        resolved = dict(models) if models is not None else None
        if resolved is None:
            resolved = build_models(demo=demo, overrides=clean_overrides(overrides), delay=delay)
        graph = build_graph(resolved)
        yield {"type": "agent_start", "agent": current}
        stream = graph.stream(
            {"request": request.strip(), "usage": []}, stream_mode=["updates", "messages"]
        )
        for mode, chunk in stream:
            if cancel.is_set():
                raise RunCancelled
            if mode == "messages":
                message, meta = cast(tuple[Any, dict[str, Any]], chunk)
                text = getattr(message, "text", "")
                if text and meta.get("langgraph_node") == current:
                    yield {"type": "token", "agent": current, "text": str(text)}
                continue
            for node, update in cast(dict[str, dict[str, Any]], chunk).items():
                if node not in _OUTPUT_KEY or not update:  # pragma: no cover - defensive
                    continue
                outputs[_OUTPUT_KEY[node]] = update[_OUTPUT_KEY[node]]
                records = list(update.get("usage", []))
                usage.extend(records)
                now = time.monotonic()
                durations[node] = round(now - started, 3)
                started = now
                yield {
                    "type": "agent_done",
                    "agent": node,
                    "text": outputs[_OUTPUT_KEY[node]],
                    "usage": records[0] if records else None,
                    "seconds": durations[node],
                }
                position = order.index(node)
                if position + 1 < len(order):
                    current = order[position + 1]
                    yield {"type": "agent_start", "agent": current}
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
    yield {"type": "done", **_partial(outputs, usage, durations)}


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
