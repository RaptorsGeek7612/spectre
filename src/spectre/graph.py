"""LangGraph pipeline (Scout -> Scribe -> Warden, with Warden -> Scribe revision rounds)
and the `run` entry point."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from spectre.config import (
    AGENT_NAMES,
    AgentSpec,
    check_max_revisions,
    has_api_key,
    load_client_settings,
    load_env,
    load_max_revisions,
    load_prompt_cache,
    load_specs,
)
from spectre.costs import total_cost
from spectre.errors import MissingAPIKeyError
from spectre.llm import make_chat_model
from spectre.nodes import make_node
from spectre.plugins import ExtraAgent, load_extra_agents
from spectre.state import SpectreState, UsageRecord
from spectre.steps import CORE_STEPS, Step

SpectreGraph = CompiledStateGraph[SpectreState, None, SpectreState, SpectreState]


@dataclass
class SpectreResult:
    """Outcome of a Spectre run."""

    brief: str
    draft: str
    final_text: str
    usage: list[UsageRecord] = field(default_factory=list)
    approved: bool = True
    issues: list[str] = field(default_factory=list)
    revisions: int = 0

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
            "approved": self.approved,
            "issues": list(self.issues),
            "revisions": self.revisions,
            "usage": [dict(record) for record in self.usage],
            "total_cost_usd": self.total_cost_usd,
        }


def pipeline_steps(extras: Sequence[ExtraAgent] = ()) -> list[Step]:
    """The agents in running order: each core agent, then the extras placed after it."""
    order: list[Step] = []
    for name in AGENT_NAMES:
        order.append(CORE_STEPS[name])
        order.extend(extra.step for extra in extras if extra.after == name)
    return order


def next_step(
    order: Sequence[str], node: str, state: Mapping[str, Any], max_revisions: int
) -> str | None:
    """The agent after `node` (None at the end): back to Scribe while Warden rejects the text
    and rounds remain, else the next one in `order`."""
    if (
        node == "warden"
        and state.get("approved") is False
        and state.get("revisions", 0) < max_revisions
    ):
        return "scribe"
    position = order.index(node)
    return order[position + 1] if position + 1 < len(order) else None


def revision_router(
    max_revisions: int, order: Sequence[str] = AGENT_NAMES
) -> Callable[[SpectreState], str]:
    """After Warden: back to Scribe while the draft is rejected and rounds remain, else on."""

    def route(state: SpectreState) -> str:
        return next_step(order, "warden", state, max_revisions) or END

    return route


def build_graph(
    models: Mapping[str, BaseChatModel] | None = None,
    *,
    max_revisions: int | None = None,
    extra_agents: Sequence[ExtraAgent] | None = None,
    prompt_cache: bool | None = None,
) -> SpectreGraph:
    """Compile the Spectre graph.

    `models` maps agent names ("scout", "scribe", "warden", and added agents) to chat models
    (e.g. fakes for tests). Missing agents get a `ChatAnthropic` built from `spectre.config`;
    in that case `.env` is loaded and ANTHROPIC_API_KEY must be set. `max_revisions` caps the
    Warden -> Scribe rounds (default: `SPECTRE_MAX_REVISIONS`, else 1; 0 = linear chain).
    `extra_agents` defaults to `spectre-agents.toml`; `prompt_cache` to `SPECTRE_PROMPT_CACHE`.
    """
    rounds = load_max_revisions() if max_revisions is None else check_max_revisions(max_revisions)
    extras = list(load_extra_agents() if extra_agents is None else extra_agents)
    cache = load_prompt_cache() if prompt_cache is None else prompt_cache
    steps = pipeline_steps(extras)
    order = [step.name for step in steps]
    provided = dict(models or {})
    unknown = sorted(set(provided) - set(order))
    if unknown:
        raise ValueError(f"agents inconnus : {', '.join(unknown)} (attendus : {', '.join(order)})")

    missing = [name for name in order if name not in provided]
    resolved: dict[str, BaseChatModel] = dict(provided)
    specs: dict[str, AgentSpec] = {extra.name: extra.spec for extra in extras}
    if missing:
        load_env()  # before load_specs() so SPECTRE_* overrides in .env are honoured
        specs.update(load_specs())
        if not has_api_key():
            raise MissingAPIKeyError()
        settings = load_client_settings()
        for name in missing:
            resolved[name] = make_chat_model(specs[name], settings)

    builder = StateGraph(SpectreState)
    for step in steps:
        # Injected models: pricing uses their `.model` attribute, else the configured ID.
        priced = None if step.name in provided else specs[step.name].model
        builder.add_node(step.name, make_node(step, resolved[step.name], priced, cache=cache))
    builder.add_edge(START, order[0])
    for current, following in zip(order, order[1:], strict=False):
        if current != "warden":
            builder.add_edge(current, following)
    after_warden = order[order.index("warden") + 1 :]
    builder.add_conditional_edges(
        "warden", revision_router(rounds, order), ["scribe", *after_warden[:1], END]
    )
    return builder.compile(name="spectre")


def run(
    request: str,
    *,
    models: Mapping[str, BaseChatModel] | None = None,
    max_revisions: int | None = None,
    extra_agents: Sequence[ExtraAgent] | None = None,
    prompt_cache: bool | None = None,
) -> SpectreResult:
    """Run the full pipeline on `request` and return a SpectreResult (see `build_graph`)."""
    if not request or not request.strip():
        raise ValueError("la demande est vide")
    graph = build_graph(
        models, max_revisions=max_revisions, extra_agents=extra_agents, prompt_cache=prompt_cache
    )
    state = graph.invoke({"request": request.strip(), "usage": [], "revisions": 0})
    return SpectreResult(
        brief=state["brief"],
        draft=state["draft"],
        final_text=state["final_text"],
        usage=list(state["usage"]),
        approved=state.get("approved", True),
        issues=list(state.get("issues", [])),
        revisions=state.get("revisions", 0),
    )
