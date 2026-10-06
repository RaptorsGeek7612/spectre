"""Factory building `ChatAnthropic` clients from an `AgentSpec`."""

from __future__ import annotations

from typing import Any

from langchain_anthropic import ChatAnthropic

from spectre.config import AgentSpec, ClientSettings


def chat_model_kwargs(spec: AgentSpec, settings: ClientSettings | None = None) -> dict[str, Any]:
    """Return the constructor kwargs for `ChatAnthropic`.

    `temperature` and `reasoning_effort` are only included when not None, so that
    Sonnet/Opus 5.5 never receive a temperature and Haiku 4.5 never receives an effort.
    """
    settings = settings or ClientSettings()
    kwargs: dict[str, Any] = {
        "model": spec.model,
        "max_tokens": spec.max_tokens,
        "max_retries": settings.max_retries,
        "timeout": settings.timeout,
    }
    if spec.temperature is not None:
        kwargs["temperature"] = spec.temperature
    if spec.effort is not None:
        kwargs["reasoning_effort"] = spec.effort
    return kwargs


def make_chat_model(spec: AgentSpec, settings: ClientSettings | None = None) -> ChatAnthropic:
    """Build a `ChatAnthropic` client for `spec` (no network call is made here)."""
    return ChatAnthropic(**chat_model_kwargs(spec, settings))
