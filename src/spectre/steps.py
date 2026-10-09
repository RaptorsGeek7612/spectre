"""What each agent reads and writes, shared by the LangGraph nodes and the batch mode.

A `Step` builds the human message sent to an agent from the state, and turns the agent's
answer into a state update. With prompt caching on, the part of the message that a revision
round repeats is sent as its own block carrying a `cache_control` marker.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from spectre.errors import EmptyOutputError
from spectre.prompts import (
    SCOUT_PROMPT,
    SCRIBE_PROMPT,
    WARDEN_PROMPT,
    draft_block,
    extra_input,
    request_block,
    scout_input,
    scribe_context,
    scribe_revision,
)
from spectre.state import SpectreState
from spectre.verdict import parse_verdict

Content = str | list[str | dict[str, Any]]  # what HumanMessage accepts
OUTPUT_KEYS = ("brief", "draft", "final_text")  # what an agent may write
CACHE_MARK = {"type": "ephemeral"}  # 5-minute cache: a revision round follows within minutes


@dataclass(frozen=True)
class Step:
    """One agent of the pipeline: its system prompt, its input, and its effect on the state."""

    name: str
    prompt: str
    build: Callable[[SpectreState, bool], Content]  # (state, cache) -> human message content
    apply: Callable[[SpectreState, str], dict[str, Any]]  # (state, answer) -> update
    writes: str


def cached(shared: str, rest: str, cache: bool) -> Content:
    """`shared + rest`, with a cache breakpoint after `shared` when caching is on."""
    if not cache or not rest:
        return shared + rest
    return [
        {"type": "text", "text": shared, "cache_control": dict(CACHE_MARK)},
        {"type": "text", "text": rest},
    ]


def content_text(content: Content) -> str:
    """The plain text of a message content (string or text blocks)."""
    if isinstance(content, str):
        return content
    return "".join(b if isinstance(b, str) else str(b.get("text", "")) for b in content)


def _revising(state: SpectreState) -> bool:
    return state.get("approved") is False


def _scout_build(state: SpectreState, cache: bool) -> Content:
    return scout_input(state["request"])  # one call per run: nothing to reuse


def _scribe_build(state: SpectreState, cache: bool) -> Content:
    revision = (
        scribe_revision(state.get("final_text", ""), state.get("issues", []))
        if _revising(state)
        else ""
    )
    # The prefix is written on the first round and read back on a revision round.
    return cached(scribe_context(state["request"], state["brief"]), revision or "", cache)


def _scribe_apply(state: SpectreState, answer: str) -> dict[str, Any]:
    update: dict[str, Any] = {"draft": answer}
    if _revising(state):
        update["revisions"] = state.get("revisions", 0) + 1
    return update


def _warden_build(state: SpectreState, cache: bool) -> Content:
    return cached(request_block(state["request"]), draft_block(state["draft"]), cache)


def _warden_apply(state: SpectreState, answer: str) -> dict[str, Any]:
    verdict = parse_verdict(answer)
    if not verdict.text:
        raise EmptyOutputError("warden")
    return {"final_text": verdict.text, "approved": verdict.approved, "issues": verdict.issues}


SCOUT = Step("scout", SCOUT_PROMPT, _scout_build, lambda s, a: {"brief": a}, "brief")
SCRIBE = Step("scribe", SCRIBE_PROMPT, _scribe_build, _scribe_apply, "draft")
WARDEN = Step("warden", WARDEN_PROMPT, _warden_build, _warden_apply, "final_text")
CORE_STEPS = {step.name: step for step in (SCOUT, SCRIBE, WARDEN)}


def extra_step(name: str, prompt: str, reads: str, writes: str) -> Step:
    """A step added by the user: reads one text of the state, rewrites one."""

    def build(state: SpectreState, cache: bool) -> Content:
        return extra_input(state["request"], str(state.get(reads, "")))

    return Step(name, prompt, build, lambda state, answer: {writes: answer}, writes)
