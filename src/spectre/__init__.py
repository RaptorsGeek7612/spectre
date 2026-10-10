"""Spectre: a multi-agent Claude pipeline (Scout -> Scribe -> Warden) built on LangGraph."""

from spectre.errors import (
    AgentRefusalError,
    ConfigurationError,
    EmptyOutputError,
    MissingAPIKeyError,
    SpectreError,
)
from spectre.graph import SpectreResult, build_graph, run
from spectre.state import SpectreState, UsageRecord

__version__ = "0.5.2"

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
