"""LangGraph node factories: one generic node per `Step` (Scout, Scribe, Warden, added agents)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Protocol

import anthropic
from langchain_core.exceptions import ModelError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from spectre.config import DEFAULT_SPECS
from spectre.costs import usage_from_message
from spectre.errors import AgentRefusalError, EmptyOutputError, SpectreError
from spectre.state import SpectreState, UsageRecord
from spectre.steps import SCOUT, SCRIBE, WARDEN, Step

logger = logging.getLogger("spectre")


class NodeFn(Protocol):
    """A LangGraph node: takes the state, returns a partial state update."""

    def __call__(self, state: SpectreState) -> dict[str, Any]: ...


def _resolve_model_name(agent: str, model: BaseChatModel, model_name: str | None) -> str:
    """Model ID used for pricing: explicit name, else `model.model`, else the default one."""
    if model_name:
        return model_name
    attr = getattr(model, "model", None)
    if isinstance(attr, str) and attr:
        return attr
    default = DEFAULT_SPECS.get(agent)
    return default.model if default else "inconnu"


def _call_agent(
    agent: str, model: BaseChatModel, model_name: str, messages: Sequence[BaseMessage]
) -> tuple[str, UsageRecord]:
    """Invoke `model`, validate its answer and return (text, usage record)."""
    try:
        ai = model.invoke(list(messages))
    except SpectreError:
        raise
    except (ModelError, anthropic.APIError) as exc:
        raise SpectreError(f"échec de l'appel au modèle {model_name} : {exc}", agent=agent) from exc

    if not isinstance(ai, AIMessage):  # pragma: no cover - defensive, BaseChatModel contract
        raise SpectreError(f"réponse inattendue : {type(ai).__name__}", agent=agent)

    stop_reason = ai.response_metadata.get("stop_reason")
    if stop_reason == "refusal":
        raise AgentRefusalError(agent)

    text = str(ai.text).strip()  # `.text` keeps only text blocks (thinking blocks are skipped)
    if not text:
        raise EmptyOutputError(agent)

    truncated = stop_reason == "max_tokens"
    if truncated:
        logger.warning("[%s] réponse tronquée (max_tokens atteint) : texte incomplet.", agent)

    # After a server-side fallback, the response names the model that actually answered.
    served = ai.response_metadata.get("model_name")
    served_by = served if isinstance(served, str) and served else model_name
    if served_by != model_name:
        logger.warning("[%s] repli : %s a répondu à la place de %s.", agent, served_by, model_name)

    return text, usage_from_message(agent, served_by, ai, truncated=truncated)


def make_node(
    step: Step, model: BaseChatModel, model_name: str | None = None, *, cache: bool = False
) -> NodeFn:
    """A LangGraph node running `step` with `model` (prompt caching on Scribe/Warden if `cache`)."""

    name = _resolve_model_name(step.name, model, model_name)

    def node(state: SpectreState) -> dict[str, Any]:
        messages = [SystemMessage(step.prompt), HumanMessage(step.build(state, cache))]
        answer, usage = _call_agent(step.name, model, name, messages)
        return {**step.apply(state, answer), "usage": [usage]}

    node.__name__ = step.name
    return node


def make_scout_node(model: BaseChatModel, model_name: str | None = None) -> NodeFn:
    """Scout: request -> brief."""
    return make_node(SCOUT, model, model_name)


def make_scribe_node(
    model: BaseChatModel, model_name: str | None = None, *, cache: bool = False
) -> NodeFn:
    """Scribe: request + brief -> draft; after a rejection, rewrites with Warden's issues."""
    return make_node(SCRIBE, model, model_name, cache=cache)


def make_warden_node(
    model: BaseChatModel, model_name: str | None = None, *, cache: bool = False
) -> NodeFn:
    """Warden: request + draft -> final_text and a verdict (approved, issues)."""
    return make_node(WARDEN, model, model_name, cache=cache)
