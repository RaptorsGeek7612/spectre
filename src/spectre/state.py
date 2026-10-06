"""Typed LangGraph state shared by the Spectre agents."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class UsageRecord(TypedDict):
    """Token usage and cost of one agent call."""

    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class SpectreState(TypedDict, total=False):
    """Graph state: request in, brief/draft/final_text out, additive usage log."""

    request: str
    brief: str
    draft: str
    final_text: str
    usage: Annotated[list[UsageRecord], operator.add]
