"""Model registry, pricing and environment overrides.

This is the only module allowed to contain Claude model IDs.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Final, Literal

from dotenv import find_dotenv, load_dotenv

from spectre.errors import ConfigurationError

Effort = Literal["low", "medium", "high", "xhigh", "max"]

EFFORT_LEVELS: Final[tuple[Effort, ...]] = ("low", "medium", "high", "xhigh", "max")
AGENT_NAMES: Final[tuple[str, ...]] = ("scout", "scribe", "warden")

API_KEY_ENV: Final = "ANTHROPIC_API_KEY"
WORKSPACE_ID_ENV: Final = "ANTHROPIC_WORKSPACE_ID"
DEFAULT_MAX_RETRIES: Final = 4
DEFAULT_TIMEOUT_S: Final = 300.0


@dataclass(frozen=True)
class AgentSpec:
    """Static configuration of one agent."""

    name: str
    model: str
    max_tokens: int
    temperature: float | None  # None = not sent
    effort: Effort | None  # None = not sent


@dataclass(frozen=True)
class ModelPrice:
    """Price in USD per million tokens."""

    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True)
class ClientSettings:
    """HTTP client settings shared by every agent."""

    max_retries: int = DEFAULT_MAX_RETRIES
    timeout: float = DEFAULT_TIMEOUT_S
    workspace_id: str | None = None  # sent as `anthropic-workspace-id` (user-scoped keys)


DEFAULT_SPECS: Final[Mapping[str, AgentSpec]] = {
    "scout": AgentSpec(
        name="scout", model="claude-haiku-4-5", max_tokens=1024, temperature=0.2, effort=None
    ),
    "scribe": AgentSpec(
        name="scribe", model="claude-sonnet-5-5", max_tokens=8000, temperature=None, effort="medium"
    ),
    "warden": AgentSpec(
        name="warden", model="claude-opus-5-5", max_tokens=8000, temperature=None, effort="high"
    ),
}

PRICING: Final[Mapping[str, ModelPrice]] = {
    "claude-haiku-4-5": ModelPrice(input_per_mtok=1.0, output_per_mtok=5.0),
    "claude-sonnet-5-5": ModelPrice(input_per_mtok=2.0, output_per_mtok=10.0),
    "claude-opus-5-5": ModelPrice(input_per_mtok=4.0, output_per_mtok=20.0),
}


def load_env() -> None:
    """Load a `.env` file found from the current working directory (never overrides)."""
    load_dotenv(find_dotenv(usecwd=True), override=False)


def has_api_key(env: Mapping[str, str] | None = None) -> bool:
    """Return True if a non-empty ANTHROPIC_API_KEY is set."""
    source = os.environ if env is None else env
    return bool(source.get(API_KEY_ENV, "").strip())


def _parse_positive_int(var: str, raw: str) -> int:
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigurationError(f"{var} doit être un entier, reçu {raw!r}") from None
    if value <= 0:
        raise ConfigurationError(f"{var} doit être strictement positif, reçu {value}")
    return value


def _parse_effort(var: str, raw: str) -> Effort:
    value = raw.strip().lower()
    if value not in EFFORT_LEVELS:
        allowed = ", ".join(EFFORT_LEVELS)
        raise ConfigurationError(f"{var} doit valoir l'un de : {allowed} (reçu {raw!r})")
    return value


def get_spec(name: str, env: Mapping[str, str] | None = None) -> AgentSpec:
    """Return the spec of agent `name`, with `SPECTRE_<AGENT>_*` overrides applied."""
    if name not in DEFAULT_SPECS:
        raise ConfigurationError(f"agent inconnu : {name!r}")
    source = os.environ if env is None else env
    spec = DEFAULT_SPECS[name]
    prefix = f"SPECTRE_{name.upper()}_"

    model = source.get(prefix + "MODEL", "").strip()
    if model:
        spec = replace(spec, model=model)
    max_tokens = source.get(prefix + "MAX_TOKENS", "").strip()
    if max_tokens:
        spec = replace(spec, max_tokens=_parse_positive_int(prefix + "MAX_TOKENS", max_tokens))
    effort = source.get(prefix + "EFFORT", "").strip()
    if effort:
        spec = replace(spec, effort=_parse_effort(prefix + "EFFORT", effort))

    # Keep sampling parameters compatible with the (possibly overridden) model.
    if _is_haiku(spec.model):
        if effort:
            raise ConfigurationError(
                f"{prefix}EFFORT n'est pas supporté par {spec.model} (Haiku n'accepte pas d'effort)"
            )
        spec = replace(spec, effort=None)
    else:
        spec = replace(spec, temperature=None)
    return spec


def _is_haiku(model: str) -> bool:
    """Haiku accepts `temperature` but no effort; other models are the reverse."""
    return model.startswith("claude-haiku")


def load_specs(env: Mapping[str, str] | None = None) -> dict[str, AgentSpec]:
    """Return the specs of all agents, with environment overrides applied."""
    return {name: get_spec(name, env) for name in AGENT_NAMES}


def load_client_settings(env: Mapping[str, str] | None = None) -> ClientSettings:
    """Return client settings (retries, timeout, workspace) from the environment."""
    source = os.environ if env is None else env
    settings = ClientSettings()
    retries = source.get("SPECTRE_MAX_RETRIES", "").strip()
    if retries:
        try:
            value = int(retries)
        except ValueError:
            raise ConfigurationError(
                f"SPECTRE_MAX_RETRIES doit être un entier, reçu {retries!r}"
            ) from None
        if value < 0:
            raise ConfigurationError(f"SPECTRE_MAX_RETRIES doit être ≥ 0, reçu {value}")
        settings = replace(settings, max_retries=value)
    timeout = source.get("SPECTRE_TIMEOUT", "").strip()
    if timeout:
        try:
            seconds = float(timeout)
        except ValueError:
            raise ConfigurationError(
                f"SPECTRE_TIMEOUT doit être un nombre de secondes, reçu {timeout!r}"
            ) from None
        if seconds <= 0:
            raise ConfigurationError(f"SPECTRE_TIMEOUT doit être > 0, reçu {seconds}")
        settings = replace(settings, timeout=seconds)
    workspace_id = source.get(WORKSPACE_ID_ENV, "").strip()
    if workspace_id:
        settings = replace(settings, workspace_id=workspace_id)
    return settings
