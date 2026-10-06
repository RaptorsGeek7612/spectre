"""Tests for spectre.config: defaults, environment overrides, invalid values."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from spectre import config
from spectre.config import (
    AGENT_NAMES,
    DEFAULT_SPECS,
    PRICING,
    AgentSpec,
    ClientSettings,
    get_spec,
    has_api_key,
    load_client_settings,
    load_env,
    load_specs,
)
from spectre.errors import ConfigurationError, SpectreError


def test_agent_names_order() -> None:
    assert AGENT_NAMES == ("scout", "scribe", "warden")


def test_default_specs_match_pdr() -> None:
    assert DEFAULT_SPECS["scout"] == AgentSpec(
        name="scout", model="claude-haiku-4-5", max_tokens=1024, temperature=0.2, effort=None
    )
    assert DEFAULT_SPECS["scribe"] == AgentSpec(
        name="scribe",
        model="claude-sonnet-5-5",
        max_tokens=8000,
        temperature=None,
        effort="medium",
    )
    assert DEFAULT_SPECS["warden"] == AgentSpec(
        name="warden", model="claude-opus-5-5", max_tokens=8000, temperature=None, effort="high"
    )


def test_sonnet_and_opus_have_no_temperature_and_haiku_no_effort() -> None:
    for spec in DEFAULT_SPECS.values():
        if spec.model.startswith(("claude-sonnet", "claude-opus")):
            assert spec.temperature is None
            assert spec.effort is not None
        else:
            assert spec.effort is None


def test_pricing_table() -> None:
    assert PRICING["claude-haiku-4-5"].input_per_mtok == 1.0
    assert PRICING["claude-haiku-4-5"].output_per_mtok == 5.0
    assert PRICING["claude-sonnet-5-5"].input_per_mtok == 2.0
    assert PRICING["claude-sonnet-5-5"].output_per_mtok == 10.0
    assert PRICING["claude-opus-5-5"].input_per_mtok == 4.0
    assert PRICING["claude-opus-5-5"].output_per_mtok == 20.0
    for spec in DEFAULT_SPECS.values():
        assert spec.model in PRICING


def test_spec_is_frozen() -> None:
    with pytest.raises(AttributeError):
        DEFAULT_SPECS["scout"].model = "x"  # type: ignore[misc]


def test_get_spec_without_overrides() -> None:
    for name in AGENT_NAMES:
        assert get_spec(name, env={}) == DEFAULT_SPECS[name]


def test_get_spec_reads_os_environ_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_WARDEN_EFFORT", "max")
    assert get_spec("warden").effort == "max"


def test_get_spec_overrides() -> None:
    env = {
        "SPECTRE_SCRIBE_MODEL": " claude-custom ",
        "SPECTRE_SCRIBE_MAX_TOKENS": " 4096 ",
        "SPECTRE_SCRIBE_EFFORT": " XHigh ",
    }
    spec = get_spec("scribe", env=env)
    assert spec.model == "claude-custom"
    assert spec.max_tokens == 4096
    assert spec.effort == "xhigh"
    assert spec.temperature is None
    # other agents untouched
    assert get_spec("warden", env=env) == DEFAULT_SPECS["warden"]


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_all_effort_levels_accepted(effort: str) -> None:
    assert get_spec("warden", env={"SPECTRE_WARDEN_EFFORT": effort}).effort == effort


def test_blank_overrides_are_ignored() -> None:
    env = {
        "SPECTRE_SCOUT_MODEL": "  ",
        "SPECTRE_SCOUT_MAX_TOKENS": "",
        "SPECTRE_WARDEN_EFFORT": " ",
    }
    assert get_spec("scout", env=env) == DEFAULT_SPECS["scout"]
    assert get_spec("warden", env=env) == DEFAULT_SPECS["warden"]


@pytest.mark.parametrize("raw", ["abc", "1.5", "", "0", "-3"])
def test_invalid_max_tokens(raw: str) -> None:
    env = {"SPECTRE_SCOUT_MAX_TOKENS": raw}
    if raw == "":
        assert get_spec("scout", env=env).max_tokens == 1024
        return
    with pytest.raises(ConfigurationError, match="SPECTRE_SCOUT_MAX_TOKENS"):
        get_spec("scout", env=env)


def test_invalid_effort() -> None:
    with pytest.raises(ConfigurationError, match="SPECTRE_WARDEN_EFFORT"):
        get_spec("warden", env={"SPECTRE_WARDEN_EFFORT": "extreme"})


def test_effort_override_rejected_for_haiku_scout() -> None:
    """Rule 3: Haiku 4.5 must never receive an effort, even through the environment."""
    with pytest.raises(ConfigurationError, match="SPECTRE_SCOUT_EFFORT"):
        get_spec("scout", env={"SPECTRE_SCOUT_EFFORT": "high"})


def test_scout_moved_to_sonnet_drops_temperature() -> None:
    spec = get_spec("scout", env={"SPECTRE_SCOUT_MODEL": "claude-sonnet-5-5"})
    assert spec.model == "claude-sonnet-5-5"
    assert spec.temperature is None
    assert spec.effort is None


def test_scribe_moved_to_haiku_drops_effort() -> None:
    spec = get_spec("scribe", env={"SPECTRE_SCRIBE_MODEL": "claude-haiku-4-5"})
    assert spec.model == "claude-haiku-4-5"
    assert spec.effort is None
    assert spec.temperature is None


def test_explicit_effort_rejected_when_overridden_to_haiku() -> None:
    env = {"SPECTRE_WARDEN_MODEL": "claude-haiku-4-5", "SPECTRE_WARDEN_EFFORT": "max"}
    with pytest.raises(ConfigurationError, match="SPECTRE_WARDEN_EFFORT"):
        get_spec("warden", env=env)


def test_unknown_agent() -> None:
    with pytest.raises(ConfigurationError, match="inconnu"):
        get_spec("ghost", env={})


def test_configuration_error_is_spectre_error() -> None:
    assert issubclass(ConfigurationError, SpectreError)


def test_load_specs() -> None:
    specs = load_specs(env={"SPECTRE_WARDEN_MAX_TOKENS": "16000"})
    assert list(specs) == list(AGENT_NAMES)
    assert specs["warden"].max_tokens == 16000
    assert specs["scout"] == DEFAULT_SPECS["scout"]


def test_has_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    assert has_api_key(env={}) is False
    assert has_api_key(env={"ANTHROPIC_API_KEY": "   "}) is False
    assert has_api_key(env={"ANTHROPIC_API_KEY": "sk-x"}) is True
    assert has_api_key() is False  # isolated_env removed it
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    assert has_api_key() is True


def test_client_settings_defaults() -> None:
    settings = load_client_settings(env={})
    assert settings == ClientSettings(max_retries=4, timeout=300.0)
    assert load_client_settings() == settings


def test_client_settings_overrides() -> None:
    settings = load_client_settings(env={"SPECTRE_MAX_RETRIES": "0", "SPECTRE_TIMEOUT": " 12.5 "})
    assert settings.max_retries == 0
    assert settings.timeout == 12.5


@pytest.mark.parametrize(
    ("env", "var"),
    [
        ({"SPECTRE_MAX_RETRIES": "two"}, "SPECTRE_MAX_RETRIES"),
        ({"SPECTRE_MAX_RETRIES": "-1"}, "SPECTRE_MAX_RETRIES"),
        ({"SPECTRE_TIMEOUT": "soon"}, "SPECTRE_TIMEOUT"),
        ({"SPECTRE_TIMEOUT": "0"}, "SPECTRE_TIMEOUT"),
        ({"SPECTRE_TIMEOUT": "-5"}, "SPECTRE_TIMEOUT"),
    ],
)
def test_client_settings_invalid(env: dict[str, str], var: str) -> None:
    with pytest.raises(ConfigurationError, match=var):
        load_client_settings(env=env)


def test_load_env_reads_dotenv_from_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-from-dotenv\nSPECTRE_WARDEN_EFFORT=max\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    load_env()
    try:
        assert os.environ["ANTHROPIC_API_KEY"] == "sk-from-dotenv"
        assert get_spec("warden").effort == "max"
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("SPECTRE_WARDEN_EFFORT", None)


def test_load_env_never_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    load_env()
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-from-env"


def test_model_ids_only_in_config() -> None:
    """NF2: Claude model IDs appear nowhere in the package except config.py."""
    package = Path(config.__file__).parent
    offenders = [
        path.name
        for path in package.glob("*.py")
        if path.name != "config.py"
        and any(
            model in path.read_text(encoding="utf-8")
            for model in ("claude-haiku", "claude-sonnet", "claude-opus")
        )
    ]
    assert offenders == []


def test_product_name_is_spectre() -> None:
    """NF8: never "claude agent" in the package."""
    package = Path(config.__file__).parent
    for path in package.glob("*.py"):
        assert "claude agent" not in path.read_text(encoding="utf-8").lower()
