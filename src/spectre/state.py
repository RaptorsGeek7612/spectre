"""Typed LangGraph state shared by the Spectre agents."""

from __future__ import annotations

import operator
from typing import Annotated, NotRequired, TypedDict


class UsageRecord(TypedDict):
    """Token usage and cost of one agent call.

    `model` is the model that actually answered (a fallback model after a refusal);
    `truncated` is True when the answer stopped at `max_tokens`. `input_tokens` counts every
    input token; `cache_read_tokens` / `cache_write_tokens` are the part served from / written
    to the prompt cache (absent in records made before v0.5).
    """

    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    truncated: bool
    cache_read_tokens: NotRequired[int]
    cache_write_tokens: NotRequired[int]


class SpectreState(TypedDict, total=False):
    """Graph state: request in, brief/draft/final_text out, Warden's verdict, additive usage.

    `revisions` counts the Warden -> Scribe rounds already done; `approved` and `issues` are
    Warden's latest verdict.
    """

    request: str
    brief: str
    draft: str
    final_text: str
    approved: bool
    issues: list[str]
    revisions: int
    usage: Annotated[list[UsageRecord], operator.add]
