"""Tests for spectre.graph: full pipeline with fake models, result object, model wiring."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from langchain_anthropic import ChatAnthropic

from spectre.config import AgentSpec, ClientSettings
from spectre.errors import AgentRefusalError, MissingAPIKeyError
from spectre.graph import SpectreResult, build_graph, run
from spectre.llm import make_chat_model
from tests.conftest import RaisingFakeModel, RecordingFakeModel, fake, make_ai


def test_run_full_pipeline(fake_models: dict[str, RecordingFakeModel], call_log: list[str]) -> None:
    result = run("  Écris un haïku sur l'automne.  ", models=fake_models)

    assert isinstance(result, SpectreResult)
    assert (result.brief, result.draft, result.final_text) == ("BRIEF", "DRAFT", "FINAL")
    assert call_log == ["scout", "scribe", "warden"]
    assert [record["agent"] for record in result.usage] == ["scout", "scribe", "warden"]


def test_request_is_stripped_and_passed_along(
    fake_models: dict[str, RecordingFakeModel],
) -> None:
    run("  ma demande  ", models=fake_models)
    scout_text = " ".join(str(m.content) for m in fake_models["scout"].received[0])
    assert "ma demande" in scout_text
    assert "  ma demande  " not in scout_text
    scribe_text = " ".join(str(m.content) for m in fake_models["scribe"].received[0])
    assert "BRIEF" in scribe_text
    warden_text = " ".join(str(m.content) for m in fake_models["warden"].received[0])
    assert "DRAFT" in warden_text


def test_costs_use_injected_model_attribute(call_log: list[str]) -> None:
    models = {
        "scout": fake(
            "scout",
            make_ai("B", input_tokens=1000, output_tokens=200),
            model="claude-haiku-4-5",
        ),
        "scribe": fake(
            "scribe",
            make_ai("D", input_tokens=2000, output_tokens=3000),
            model="claude-sonnet-5-5",
        ),
        "warden": fake(
            "warden",
            make_ai("F", input_tokens=4000, output_tokens=1000),
            model="claude-opus-5-5",
        ),
    }
    result = run("demande", models=models)

    costs = [record["cost_usd"] for record in result.usage]
    assert costs == pytest.approx([0.002, 0.034, 0.036])
    assert result.total_cost_usd == pytest.approx(0.072)


def test_fakes_without_model_attribute_use_configured_ids(
    fake_models: dict[str, RecordingFakeModel],
) -> None:
    result = run("demande", models=fake_models)
    assert [r["model"] for r in result.usage] == [
        "claude-haiku-4-5",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    ]
    assert result.total_cost_usd == pytest.approx(0.072)


def test_total_cost_none_when_models_unknown() -> None:
    models = {
        name: fake(name, make_ai(name.upper()), model="claude-custom")
        for name in ("scout", "scribe", "warden")
    }
    with pytest.warns(RuntimeWarning, match="claude-custom"):
        result = run("demande", models=models)
    assert all(record["cost_usd"] is None for record in result.usage)
    assert result.total_cost_usd is None
    assert result.to_dict()["total_cost_usd"] is None


def test_to_dict_is_json_serialisable(fake_models: dict[str, RecordingFakeModel]) -> None:
    data = run("demande", models=fake_models).to_dict()
    assert set(data) == {
        "brief",
        "draft",
        "final_text",
        "approved",
        "issues",
        "revisions",
        "usage",
        "total_cost_usd",
    }
    assert (data["approved"], data["issues"], data["revisions"]) == (True, [], 0)
    assert json.loads(json.dumps(data)) == data
    assert len(data["usage"]) == 3


@pytest.mark.parametrize("request_text", ["", "   ", "\n\t"])
def test_run_rejects_empty_request(
    request_text: str, fake_models: dict[str, RecordingFakeModel]
) -> None:
    with pytest.raises(ValueError, match="vide"):
        run(request_text, models=fake_models)
    assert fake_models["scout"].received == []


def test_graph_is_reusable(make_fakes: Callable[..., dict[str, RecordingFakeModel]]) -> None:
    assert run("une", models=make_fakes()).final_text == "FINAL"
    assert run("deux", models=make_fakes()).final_text == "FINAL"


def test_agent_error_stops_pipeline(fake_models: dict[str, RecordingFakeModel]) -> None:
    models = dict(fake_models)
    models["scribe"] = fake("scribe", make_ai("non", stop_reason="refusal"))
    with pytest.raises(AgentRefusalError, match="scribe"):
        run("demande", models=models)
    assert fake_models["warden"].received == []


def test_injected_models_ignore_environment_config(
    fake_models: dict[str, RecordingFakeModel], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SPECTRE_SCOUT_MAX_TOKENS", "pas-un-nombre")
    assert run("demande", models=fake_models).final_text == "FINAL"


def test_unknown_agent_rejected(fake_models: dict[str, RecordingFakeModel]) -> None:
    models = {**fake_models, "ghost": fake("ghost", "x")}
    with pytest.raises(ValueError, match="ghost"):
        build_graph(models)


def test_missing_models_require_api_key(fake_models: dict[str, RecordingFakeModel]) -> None:
    partial = {"scout": fake_models["scout"]}
    with pytest.raises(MissingAPIKeyError):
        build_graph(partial)
    with pytest.raises(MissingAPIKeyError):
        build_graph()


def test_missing_models_are_built_from_config(
    api_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without injected models, ChatAnthropic clients are built from the config (no call)."""
    built: list[ChatAnthropic] = []

    def recording_make(*args: object, **kwargs: object) -> ChatAnthropic:
        model = make_chat_model(*args, **kwargs)  # type: ignore[arg-type]
        built.append(model)
        return model

    monkeypatch.setattr("spectre.graph.make_chat_model", recording_make)
    monkeypatch.setenv("SPECTRE_MAX_RETRIES", "1")
    graph = build_graph()

    assert [m.model for m in built] == ["claude-haiku-4-5", "claude-sonnet-5-5", "claude-opus-5-5"]
    assert all(m.max_retries == 1 for m in built)
    assert set(graph.nodes) >= {"scout", "scribe", "warden"}


def test_only_missing_models_are_built(
    api_key: str, fake_models: dict[str, RecordingFakeModel], monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[str] = []

    def recording_make(spec: AgentSpec, settings: ClientSettings) -> RaisingFakeModel:
        built.append(spec.name)
        return RaisingFakeModel(exc=RuntimeError())

    monkeypatch.setattr("spectre.graph.make_chat_model", recording_make)
    build_graph({"scout": fake_models["scout"], "scribe": fake_models["scribe"]})
    assert built == ["warden"]
