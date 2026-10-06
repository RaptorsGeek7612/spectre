"""Critical: Sonnet/Opus never get a temperature, Haiku never gets an effort.

Checked twice: on the kwargs given to ChatAnthropic, and on the request payload a real
ChatAnthropic (fake key, no network) would send.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from spectre.config import ClientSettings, get_spec, load_client_settings, load_specs
from spectre.llm import chat_model_kwargs, make_chat_model

SAMPLING = ("temperature", "top_p", "top_k")


def _payload(model: ChatAnthropic) -> dict[str, Any]:
    if not hasattr(model, "_get_request_payload"):  # pragma: no cover - library internals
        pytest.skip("ChatAnthropic._get_request_payload not available")
    payload: dict[str, Any] = model._get_request_payload(
        [SystemMessage("sys"), HumanMessage("bonjour")]
    )
    return payload


def _sent(payload: dict[str, Any], key: str) -> Any:
    """Value of `key` as sent on the wire (top level or relocated in `extra_body`)."""
    extra = payload.get("extra_body") or {}
    return payload.get(key, extra.get(key))


@pytest.mark.parametrize("agent", ["scribe", "warden"])
def test_kwargs_sonnet_opus_have_effort_no_temperature(agent: str) -> None:
    kwargs = chat_model_kwargs(get_spec(agent, env={}))
    for key in SAMPLING:
        assert key not in kwargs
    assert "budget_tokens" not in kwargs
    assert "max_output_tokens" not in kwargs
    assert kwargs["reasoning_effort"] == {"scribe": "medium", "warden": "high"}[agent]


def test_kwargs_haiku_has_temperature_no_effort() -> None:
    kwargs = chat_model_kwargs(get_spec("scout", env={}))
    assert kwargs["temperature"] == 0.2
    assert "reasoning_effort" not in kwargs
    assert "effort" not in kwargs


def test_kwargs_exact_content() -> None:
    kwargs = chat_model_kwargs(get_spec("warden", env={}), ClientSettings(2, 30.0))
    assert kwargs == {
        "model": "claude-opus-5-5",
        "max_tokens": 16000,
        "max_retries": 2,
        "timeout": 30.0,
        "reasoning_effort": "high",
        "betas": ["server-side-fallback-2026-07-01"],
        "model_kwargs": {"fallbacks": "default"},
    }


def test_kwargs_default_client_settings() -> None:
    kwargs = chat_model_kwargs(get_spec("scout", env={}))
    assert kwargs["max_retries"] == 4
    assert kwargs["timeout"] == 600.0
    assert kwargs["max_tokens"] == 1024


def test_kwargs_follow_env_overrides() -> None:
    specs = load_specs(env={"SPECTRE_WARDEN_EFFORT": "max", "SPECTRE_SCRIBE_MAX_TOKENS": "123"})
    assert chat_model_kwargs(specs["warden"])["reasoning_effort"] == "max"
    assert chat_model_kwargs(specs["scribe"])["max_tokens"] == 123


@pytest.mark.parametrize("agent", ["scout", "scribe", "warden"])
def test_make_chat_model_builds_chat_anthropic(agent: str, api_key: str) -> None:
    spec = get_spec(agent, env={})
    model = make_chat_model(spec, ClientSettings(max_retries=3, timeout=42.0))
    assert isinstance(model, ChatAnthropic)
    assert model.model == spec.model
    assert model.max_tokens == spec.max_tokens
    assert model.max_retries == 3
    assert model.default_request_timeout == 42.0


@pytest.mark.parametrize(
    ("agent", "model_id", "effort"),
    [("scribe", "claude-sonnet-5-5", "medium"), ("warden", "claude-opus-5-5", "high")],
)
def test_payload_sonnet_opus_no_sampling_params(
    agent: str, model_id: str, effort: str, api_key: str
) -> None:
    model = make_chat_model(get_spec(agent, env={}))
    assert model.temperature is None
    payload = _payload(model)
    assert payload["model"] == model_id
    assert payload["max_tokens"] == 16000
    for key in SAMPLING:
        assert _sent(payload, key) is None, f"{key} sent to {model_id}"
    assert payload["output_config"]["effort"] == effort
    assert "budget_tokens" not in str(payload)


def test_payload_haiku_has_temperature_no_effort(api_key: str) -> None:
    model = make_chat_model(get_spec("scout", env={}))
    payload = _payload(model)
    assert payload["model"] == "claude-haiku-4-5"
    assert payload["max_tokens"] == 1024
    assert _sent(payload, "temperature") == 0.2
    assert "effort" not in (payload.get("output_config") or {})
    assert _sent(payload, "reasoning_effort") is None
    assert _sent(payload, "effort") is None
    assert "thinking" not in payload


def test_payload_effort_override_reaches_opus(api_key: str) -> None:
    spec = get_spec("warden", env={"SPECTRE_WARDEN_EFFORT": "max"})
    payload = _payload(make_chat_model(spec))
    assert payload["output_config"]["effort"] == "max"
    assert _sent(payload, "temperature") is None


def test_payload_has_no_assistant_prefill(api_key: str) -> None:
    payload = _payload(make_chat_model(get_spec("warden", env={})))
    assert payload["messages"][-1]["role"] == "user"


def test_kwargs_without_workspace_send_no_header() -> None:
    assert "default_headers" not in chat_model_kwargs(get_spec("scout", env={}))


def test_workspace_id_sent_as_header(api_key: str) -> None:
    settings = load_client_settings(env={"ANTHROPIC_WORKSPACE_ID": " wrkspc_test "})
    assert settings.workspace_id == "wrkspc_test"
    model = make_chat_model(get_spec("warden", env={}), settings)
    assert model.default_headers == {"anthropic-workspace-id": "wrkspc_test"}
    assert model._client.default_headers["anthropic-workspace-id"] == "wrkspc_test"


def test_fallbacks_only_for_supported_models() -> None:
    scout = chat_model_kwargs(get_spec("scout", env={}))
    assert "betas" not in scout
    assert "model_kwargs" not in scout
    other = chat_model_kwargs(get_spec("warden", env={"SPECTRE_WARDEN_MODEL": "claude-opus-4-8"}))
    assert "betas" not in other


def test_fallbacks_can_be_disabled() -> None:
    kwargs = chat_model_kwargs(get_spec("scribe", env={}), ClientSettings(fallbacks=False))
    assert "betas" not in kwargs
    assert "model_kwargs" not in kwargs


@pytest.mark.parametrize("agent", ["scribe", "warden"])
def test_payload_requests_default_fallbacks(agent: str, api_key: str) -> None:
    payload = _payload(make_chat_model(get_spec(agent, env={})))
    assert payload["fallbacks"] == "default"
    assert payload["betas"] == ["server-side-fallback-2026-07-01"]
