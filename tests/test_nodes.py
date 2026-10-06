"""Tests for spectre.nodes: messages sent, refusals, empty output, thinking, truncation."""

from __future__ import annotations

import logging
from typing import Any

import anthropic
import httpx2 as _httpx  # the HTTP client used by the anthropic SDK
import pytest
from langchain_core.exceptions import ModelError
from langchain_core.messages import HumanMessage, SystemMessage

from spectre.errors import AgentRefusalError, EmptyOutputError, SpectreError
from spectre.nodes import make_scout_node, make_scribe_node, make_warden_node
from spectre.prompts import SCOUT_PROMPT, SCRIBE_PROMPT, WARDEN_PROMPT
from tests.conftest import RaisingFakeModel, fake, make_ai

STATE: dict[str, Any] = {
    "request": "Explique la relativité",
    "brief": "LE BRIEF",
    "draft": "LE BROUILLON",
    "usage": [],
}


def test_scout_sends_system_and_request() -> None:
    model = fake("scout", make_ai("brief!", input_tokens=1000, output_tokens=200))
    update = make_scout_node(model)(STATE)  # type: ignore[arg-type]
    (messages,) = model.received
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == SCOUT_PROMPT
    assert isinstance(messages[1], HumanMessage)
    assert "Explique la relativité" in messages[1].content
    assert update["brief"] == "brief!"
    assert update["usage"] == [
        {
            "agent": "scout",
            "model": "claude-haiku-4-5",
            "input_tokens": 1000,
            "output_tokens": 200,
            "cost_usd": pytest.approx(0.002),
        }
    ]
    assert set(update) == {"brief", "usage"}


def test_scribe_receives_request_and_brief() -> None:
    model = fake("scribe", make_ai("draft!"))
    update = make_scribe_node(model)(STATE)  # type: ignore[arg-type]
    (messages,) = model.received
    assert messages[0].content == SCRIBE_PROMPT
    human = messages[1].content
    assert isinstance(messages[1], HumanMessage)
    assert "Explique la relativité" in human
    assert "LE BRIEF" in human
    assert update["draft"] == "draft!"
    assert update["usage"][0]["agent"] == "scribe"
    assert update["usage"][0]["model"] == "claude-sonnet-5-5"
    assert set(update) == {"draft", "usage"}


def test_warden_receives_request_and_draft() -> None:
    model = fake("warden", make_ai("final!"))
    update = make_warden_node(model)(STATE)  # type: ignore[arg-type]
    (messages,) = model.received
    assert messages[0].content == WARDEN_PROMPT
    human = messages[1].content
    assert "Explique la relativité" in human
    assert "LE BROUILLON" in human
    assert "LE BRIEF" not in human
    assert update["final_text"] == "final!"
    assert update["usage"][0]["model"] == "claude-opus-5-5"
    assert set(update) == {"final_text", "usage"}


def test_no_assistant_prefill() -> None:
    for factory in (make_scout_node, make_scribe_node, make_warden_node):
        model = fake("m", make_ai("x"))
        factory(model)(STATE)  # type: ignore[arg-type]
        assert model.received[0][-1].type == "human"


def test_text_is_stripped() -> None:
    model = fake("scout", make_ai("  \n brief \n "))
    assert make_scout_node(model)(STATE)["brief"] == "brief"  # type: ignore[arg-type]


def test_explicit_model_name_used_for_pricing() -> None:
    model = fake("scribe", make_ai("x", input_tokens=1_000_000, output_tokens=0))
    update = make_scribe_node(model, "claude-opus-5-5")(STATE)  # type: ignore[arg-type]
    assert update["usage"][0]["model"] == "claude-opus-5-5"
    assert update["usage"][0]["cost_usd"] == pytest.approx(4.0)


def test_model_attribute_used_for_pricing() -> None:
    model = fake("scout", make_ai("x"), model="claude-sonnet-5-5")
    update = make_scout_node(model)(STATE)  # type: ignore[arg-type]
    assert update["usage"][0]["model"] == "claude-sonnet-5-5"


def test_configured_model_used_when_no_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_WARDEN_MODEL", "claude-custom")
    model = fake("warden", make_ai("x"))
    with pytest.warns(RuntimeWarning, match="claude-custom"):
        update = make_warden_node(model)(STATE)  # type: ignore[arg-type]
    assert update["usage"][0]["model"] == "claude-custom"
    assert update["usage"][0]["cost_usd"] is None


@pytest.mark.parametrize(
    ("factory", "agent"),
    [(make_scout_node, "scout"), (make_scribe_node, "scribe"), (make_warden_node, "warden")],
)
def test_refusal_raises(factory: Any, agent: str) -> None:
    model = fake(agent, make_ai("I can't help", stop_reason="refusal"))
    with pytest.raises(AgentRefusalError, match=agent) as info:
        factory(model)(STATE)
    assert info.value.agent == agent
    assert isinstance(info.value, SpectreError)


def test_refusal_with_empty_content_is_refusal() -> None:
    model = fake("scribe", make_ai("", stop_reason="refusal"))
    with pytest.raises(AgentRefusalError):
        make_scribe_node(model)(STATE)  # type: ignore[arg-type]


@pytest.mark.parametrize("content", ["", "   \n", []])
def test_empty_output_raises(content: Any) -> None:
    model = fake("warden", make_ai(content))
    with pytest.raises(EmptyOutputError, match="warden") as info:
        make_warden_node(model)(STATE)  # type: ignore[arg-type]
    assert info.value.agent == "warden"


def test_thinking_only_is_empty() -> None:
    content = [{"type": "thinking", "thinking": "réflexion", "signature": "sig"}]
    model = fake("scribe", make_ai(content))
    with pytest.raises(EmptyOutputError):
        make_scribe_node(model)(STATE)  # type: ignore[arg-type]


def test_thinking_blocks_ignored() -> None:
    content = [
        {"type": "thinking", "thinking": "SECRET REASONING", "signature": "sig"},
        {"type": "text", "text": "Partie 1. "},
        {"type": "redacted_thinking", "data": "xxx"},
        {"type": "text", "text": "Partie 2."},
    ]
    model = fake("warden", make_ai(content))
    final = make_warden_node(model)(STATE)["final_text"]  # type: ignore[arg-type]
    assert final == "Partie 1. Partie 2."
    assert "SECRET" not in final


def test_max_tokens_warns_but_continues(caplog: pytest.LogCaptureFixture) -> None:
    model = fake("scribe", make_ai("texte tronqué", stop_reason="max_tokens"))
    with caplog.at_level(logging.WARNING, logger="spectre"):
        update = make_scribe_node(model)(STATE)  # type: ignore[arg-type]
    assert update["draft"] == "texte tronqué"
    assert any(
        "max_tokens" in r.getMessage() and "scribe" in r.getMessage() for r in caplog.records
    )


def test_normal_stop_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    model = fake("scribe", make_ai("ok"))
    with caplog.at_level(logging.WARNING, logger="spectre"):
        make_scribe_node(model)(STATE)  # type: ignore[arg-type]
    assert caplog.records == []


def test_missing_stop_reason_is_fine() -> None:
    model = fake("scout", make_ai("ok", stop_reason=None))
    assert make_scout_node(model)(STATE)["brief"] == "ok"  # type: ignore[arg-type]


def _api_errors() -> list[Exception]:
    request = _httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return [
        anthropic.APIConnectionError(request=request),
        anthropic.APITimeoutError(request=request),
        ModelError("boom"),
    ]


@pytest.mark.parametrize("exc", _api_errors(), ids=lambda e: type(e).__name__)
def test_api_errors_wrapped_in_spectre_error(exc: Exception) -> None:
    model = RaisingFakeModel(exc=exc)
    with pytest.raises(SpectreError, match=r"^\[scribe\] ") as info:
        make_scribe_node(model, "claude-sonnet-5-5")(STATE)  # type: ignore[arg-type]
    assert info.value.agent == "scribe"
    assert "claude-sonnet-5-5" in str(info.value)
    assert info.value.__cause__ is exc


def test_spectre_error_passes_through() -> None:
    original = SpectreError("déjà une erreur Spectre", agent="x")
    model = RaisingFakeModel(exc=original)
    with pytest.raises(SpectreError) as info:
        make_warden_node(model, "m")(STATE)  # type: ignore[arg-type]
    assert info.value is original


def test_other_exceptions_propagate() -> None:
    model = RaisingFakeModel(exc=KeyError("bug"))
    with pytest.raises(KeyError):
        make_scout_node(model, "m")(STATE)  # type: ignore[arg-type]
