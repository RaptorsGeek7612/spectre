"""Shared fixtures: network-free fake chat models and an isolated environment."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from pydantic import Field

FAKE_KEY = "sk-ant-test-not-a-real-key"


class RecordingFakeModel(GenericFakeChatModel):
    """GenericFakeChatModel that records the messages it receives.

    `call_log` may be a list shared between several fakes to check the call order.
    `model` mimics `ChatAnthropic.model` (used by Spectre for pricing) when set.
    """

    received: list[list[BaseMessage]] = Field(default_factory=list)
    call_log: Any = None
    model: str | None = None

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.received.append(list(messages))
        if self.call_log is not None:
            self.call_log.append(self.name)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class RaisingFakeModel(BaseChatModel):
    """Chat model whose every call raises `exc`."""

    exc: Any

    @property
    def _llm_type(self) -> str:
        return "raising-fake"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise self.exc


def make_ai(
    text: str | list[Any] = "ok",
    *,
    input_tokens: int = 100,
    output_tokens: int = 50,
    stop_reason: str | None = "end_turn",
    usage: bool = True,
) -> AIMessage:
    """Build an AIMessage with controlled usage and response metadata."""
    kwargs: dict[str, Any] = {}
    if usage:
        kwargs["usage_metadata"] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
    metadata = {"stop_reason": stop_reason} if stop_reason is not None else {}
    return AIMessage(content=text, response_metadata=metadata, **kwargs)


def fake(name: str, *replies: AIMessage | str, **kwargs: Any) -> RecordingFakeModel:
    """Build a RecordingFakeModel answering `replies` in order."""
    return RecordingFakeModel(name=name, messages=iter(replies), **kwargs)


@pytest.fixture(autouse=True)
def isolated_env(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> Iterator[None]:
    """Remove ANTHROPIC_API_KEY / SPECTRE_* and neutralise `.env` loading.

    Live tests keep the real environment.
    """
    if request.node.get_closest_marker("live") is None:
        for var in list(os.environ):
            if var == "ANTHROPIC_API_KEY" or var.startswith("SPECTRE_"):
                monkeypatch.delenv(var, raising=False)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("spectre.graph.load_env", lambda: None)
        monkeypatch.setattr("spectre.cli.load_env", lambda: None)
    yield


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a fake API key (never used for a real call)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    return FAKE_KEY


@pytest.fixture
def call_log() -> list[str]:
    return []


@pytest.fixture
def fake_models(call_log: list[str]) -> dict[str, RecordingFakeModel]:
    """Three fakes (one reply each) sharing a call log."""
    return {
        "scout": fake(
            "scout", make_ai("BRIEF", input_tokens=1000, output_tokens=200), call_log=call_log
        ),
        "scribe": fake(
            "scribe", make_ai("DRAFT", input_tokens=2000, output_tokens=3000), call_log=call_log
        ),
        "warden": fake(
            "warden", make_ai("FINAL", input_tokens=4000, output_tokens=1000), call_log=call_log
        ),
    }


@pytest.fixture
def make_fakes() -> Callable[..., dict[str, RecordingFakeModel]]:
    """Factory building a fresh trio of fakes (for tests running the pipeline twice)."""

    def _make() -> dict[str, RecordingFakeModel]:
        return {
            "scout": fake("scout", make_ai("BRIEF")),
            "scribe": fake("scribe", make_ai("DRAFT")),
            "warden": fake("warden", make_ai("FINAL")),
        }

    return _make
