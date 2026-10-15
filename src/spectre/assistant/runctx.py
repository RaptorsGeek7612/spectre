"""Who is working right now: the agent, mission, company and role of the current thread.

Missions run in their own threads, so a thread-local carries this context down to the places
that need it without changing every agent's `ask` signature: the MCP config of the CLI agents
(so their tool calls reach the gate as « this agent »), the in-process HTTP agent, and the cost
ledger.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_local = threading.local()


def current() -> dict[str, Any]:
    return dict(getattr(_local, "data", {}))


@contextmanager
def scope(**data: Any) -> Iterator[dict[str, Any]]:
    """Add to the context for the duration of a block (nested scopes merge)."""
    previous = current()
    _local.data = {**previous, **{k: v for k, v in data.items() if v is not None}}
    try:
        yield current()
    finally:
        _local.data = previous


def env() -> dict[str, str]:
    """The context as environment variables, for a tool server started by a CLI agent."""
    data = current()
    found = {}
    if data.get("agent"):
        found["SPECTRE_AGENT"] = str(data["agent"])
    if data.get("mission"):
        found["SPECTRE_MISSION"] = str(data["mission"])
    return found
