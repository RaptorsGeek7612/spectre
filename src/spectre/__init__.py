"""Spectre: a multi-agent Claude pipeline (Scout -> Scribe -> Warden) built on LangGraph."""

from typing import TYPE_CHECKING, Any

from spectre.errors import (
    AgentRefusalError,
    ConfigurationError,
    EmptyOutputError,
    MissingAPIKeyError,
    SpectreError,
)
from spectre.state import SpectreState, UsageRecord

if TYPE_CHECKING:
    from spectre.graph import SpectreResult, build_graph, run

_GRAPH_NAMES = frozenset({"SpectreResult", "build_graph", "run"})


def __getattr__(name: str) -> Any:
    """Load the pipeline (LangGraph, LangChain, Anthropic SDK) on first use only: the assistant
    and the web UI then start faster (PEP 562)."""
    if name in _GRAPH_NAMES:
        from spectre import graph

        return getattr(graph, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__version__ = "0.29.2"

__all__ = [
    "AgentRefusalError",
    "ConfigurationError",
    "EmptyOutputError",
    "MissingAPIKeyError",
    "SpectreError",
    "SpectreResult",
    "SpectreState",
    "UsageRecord",
    "__version__",
    "build_graph",
    "run",
]
