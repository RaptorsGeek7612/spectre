"""LangGraph node factories for Scout, Scribe and Warden."""

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
from spectre.prompts import (
    SCOUT_PROMPT,
    SCRIBE_PROMPT,
    WARDEN_PROMPT,
    scout_input,
    scribe_input,
    warden_input,
)
from spectre.state import SpectreState, UsageRecord

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
    return DEFAULT_SPECS[agent].model


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

    if stop_reason == "max_tokens":
        logger.warning("[%s] réponse tronquée (max_tokens atteint) : texte incomplet.", agent)

    return text, usage_from_message(agent, model_name, ai)


def make_scout_node(model: BaseChatModel, model_name: str | None = None) -> NodeFn:
    """Scout: request -> brief."""

    name = _resolve_model_name("scout", model, model_name)

    def scout(state: SpectreState) -> dict[str, Any]:
        messages = [SystemMessage(SCOUT_PROMPT), HumanMessage(scout_input(state["request"]))]
        brief, usage = _call_agent("scout", model, name, messages)
        return {"brief": brief, "usage": [usage]}

    return scout


def make_scribe_node(model: BaseChatModel, model_name: str | None = None) -> NodeFn:
    """Scribe: request + brief -> draft."""

    name = _resolve_model_name("scribe", model, model_name)

    def scribe(state: SpectreState) -> dict[str, Any]:
        human = scribe_input(state["request"], state["brief"])
        messages = [SystemMessage(SCRIBE_PROMPT), HumanMessage(human)]
        draft, usage = _call_agent("scribe", model, name, messages)
        return {"draft": draft, "usage": [usage]}

    return scribe


def make_warden_node(model: BaseChatModel, model_name: str | None = None) -> NodeFn:
    """Warden: request + draft -> final_text."""

    name = _resolve_model_name("warden", model, model_name)

    def warden(state: SpectreState) -> dict[str, Any]:
        human = warden_input(state["request"], state["draft"])
        messages = [SystemMessage(WARDEN_PROMPT), HumanMessage(human)]
        final_text, usage = _call_agent("warden", model, name, messages)
        return {"final_text": final_text, "usage": [usage]}

    return warden
