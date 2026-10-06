"""LangGraph pipeline (Scout -> Scribe -> Warden) and the `run` entry point."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from spectre.config import AGENT_NAMES, has_api_key, load_client_settings, load_env, load_specs
from spectre.costs import total_cost
from spectre.errors import MissingAPIKeyError
from spectre.llm import make_chat_model
from spectre.nodes import make_scout_node, make_scribe_node, make_warden_node
from spectre.state import SpectreState, UsageRecord

SpectreGraph = CompiledStateGraph[SpectreState, None, SpectreState, SpectreState]


@dataclass
class SpectreResult:
    """Outcome of a Spectre run."""

    brief: str
    draft: str
    final_text: str
    usage: list[UsageRecord] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> float | None:
        """Sum of known per-agent costs (None if no cost is known)."""
        return total_cost(self.usage)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable view of the result, including `total_cost_usd`."""
        return {
            "brief": self.brief,
            "draft": self.draft,
            "final_text": self.final_text,
            "usage": [dict(record) for record in self.usage],
            "total_cost_usd": self.total_cost_usd,
        }


def build_graph(models: Mapping[str, BaseChatModel] | None = None) -> SpectreGraph:
    """Compile the Spectre graph.

    `models` maps agent names ("scout", "scribe", "warden") to chat models (e.g. fakes
    for tests). Missing agents get a `ChatAnthropic` built from `spectre.config`; in that
    case `.env` is loaded and ANTHROPIC_API_KEY must be set.
    """
    provided = dict(models or {})
    unknown = sorted(set(provided) - set(AGENT_NAMES))
    if unknown:
        raise ValueError(f"agents inconnus : {', '.join(unknown)} (attendus : {AGENT_NAMES})")

    missing = [name for name in AGENT_NAMES if name not in provided]
    if missing:
        load_env()  # before load_specs() so SPECTRE_* overrides in .env are honoured
    specs = load_specs()
    resolved: dict[str, BaseChatModel] = dict(provided)
    if missing:
        if not has_api_key():
            raise MissingAPIKeyError()
        settings = load_client_settings()
        for name in missing:
            resolved[name] = make_chat_model(specs[name], settings)

    # Injected models: pricing uses their `.model` attribute, else the configured ID.
    names = {name: (None if name in provided else specs[name].model) for name in AGENT_NAMES}

    builder = StateGraph(SpectreState)
    builder.add_node("scout", make_scout_node(resolved["scout"], names["scout"]))
    builder.add_node("scribe", make_scribe_node(resolved["scribe"], names["scribe"]))
    builder.add_node("warden", make_warden_node(resolved["warden"], names["warden"]))
    builder.add_edge(START, "scout")
    builder.add_edge("scout", "scribe")
    builder.add_edge("scribe", "warden")
    builder.add_edge("warden", END)
    return builder.compile(name="spectre")


def run(request: str, *, models: Mapping[str, BaseChatModel] | None = None) -> SpectreResult:
    """Run the full pipeline on `request` and return a SpectreResult."""
    if not request or not request.strip():
        raise ValueError("la demande est vide")
    graph = build_graph(models)
    state = graph.invoke({"request": request.strip(), "usage": []})
    return SpectreResult(
        brief=state["brief"],
        draft=state["draft"],
        final_text=state["final_text"],
        usage=list(state["usage"]),
    )
