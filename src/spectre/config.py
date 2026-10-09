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
DEFAULT_TIMEOUT_S: Final = 600.0
FALLBACK_BETA: Final = "server-side-fallback-2026-07-01"
# Models accepting `fallbacks: "default"` (server-side retry on another model after a refusal).
FALLBACK_MODELS: Final = frozenset({"claude-sonnet-5-5", "claude-opus-5-5"})
# The voice assistant runs on Claude Code (`claude -p`): its short names map to exact models,
# so "opus" always means Opus 5.5 whatever the CLI's own alias points to.
ASSISTANT_MODELS: Final[dict[str, str]] = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "haiku": "claude-haiku-4-5",
}


def model_label(model: str) -> str:
    """Human name of a model: "claude-opus-5-5" or "opus" -> "Opus 5.5"."""
    exact = ASSISTANT_MODELS.get(model, model)
    parts = exact.removeprefix("claude-").split("-")
    if len(parts) < 2 or not parts[1].isdigit():
        return model
    return f"{parts[0].capitalize()} {'.'.join(parts[1:])}"


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
    """Price in USD per million tokens (cache writes: CACHE_WRITE_FACTOR x input)."""

    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float


CACHE_WRITE_FACTOR: Final = 1.25  # 5-minute cache entries
BATCH_FACTOR: Final = 0.5  # the Message Batches API halves every token price


@dataclass(frozen=True)
class ClientSettings:
    """HTTP client settings shared by every agent."""

    max_retries: int = DEFAULT_MAX_RETRIES
    timeout: float = DEFAULT_TIMEOUT_S
    workspace_id: str | None = None  # sent as `anthropic-workspace-id` (user-scoped keys)
    fallbacks: bool = True  # server-side fallback after a refusal, on FALLBACK_MODELS only


DEFAULT_SPECS: Final[Mapping[str, AgentSpec]] = {
    "scout": AgentSpec(
        name="scout", model="claude-haiku-4-5", max_tokens=1024, temperature=0.2, effort=None
    ),
    "scribe": AgentSpec(
        name="scribe",
        model="claude-sonnet-5-5",
        max_tokens=16000,
        temperature=None,
        effort="medium",
    ),
    "warden": AgentSpec(
        name="warden", model="claude-opus-5-5", max_tokens=16000, temperature=None, effort="high"
    ),
}

PRICING: Final[Mapping[str, ModelPrice]] = {
    "claude-haiku-4-5": ModelPrice(1.0, 5.0, cache_read_per_mtok=0.10),
    "claude-sonnet-5-5": ModelPrice(2.0, 10.0, cache_read_per_mtok=0.20),
    "claude-opus-5-5": ModelPrice(4.0, 20.0, cache_read_per_mtok=0.20),
    # Possible server-side fallback targets.
    "claude-sonnet-5": ModelPrice(2.0, 10.0, cache_read_per_mtok=0.20),
    "claude-opus-5": ModelPrice(5.0, 25.0, cache_read_per_mtok=0.50),
    "claude-opus-4-8": ModelPrice(5.0, 25.0, cache_read_per_mtok=0.50),
}


# Built-in presets for the web UI: named sets of `SPECTRE_<AGENT>_*` overrides.
WEB_PRESETS: Final[Mapping[str, Mapping[str, str]]] = {
    "Standard": {},
    "Économie": {"SPECTRE_WARDEN_MODEL": "claude-sonnet-5-5", "SPECTRE_WARDEN_EFFORT": "medium"},
    "Qualité max": {"SPECTRE_SCRIBE_EFFORT": "high", "SPECTRE_WARDEN_EFFORT": "max"},
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
    """Return client settings (retries, timeout, workspace, fallbacks) from the environment."""
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
    fallbacks = source.get("SPECTRE_FALLBACKS", "").strip().lower()
    if fallbacks:
        if fallbacks not in _BOOL_VALUES:
            raise ConfigurationError(
                f"SPECTRE_FALLBACKS doit valoir 1/0, true/false ou on/off, reçu {fallbacks!r}"
            )
        settings = replace(settings, fallbacks=_BOOL_VALUES[fallbacks])
    return settings


DEFAULT_MAX_REVISIONS: Final = 1  # Warden -> Scribe rounds; 0 = the v0.1 linear chain
MAX_REVISIONS_LIMIT: Final = 5  # each round costs a Scribe and a Warden call


def load_max_revisions(env: Mapping[str, str] | None = None) -> int:
    """Revision rounds allowed when Warden rejects the draft (`SPECTRE_MAX_REVISIONS`)."""
    source = os.environ if env is None else env
    raw = source.get("SPECTRE_MAX_REVISIONS", "").strip()
    if not raw:
        return DEFAULT_MAX_REVISIONS
    try:
        value = int(raw)
    except ValueError:
        raise ConfigurationError(
            f"SPECTRE_MAX_REVISIONS doit être un entier, reçu {raw!r}"
        ) from None
    return check_max_revisions(value, "SPECTRE_MAX_REVISIONS")


def check_max_revisions(value: int, source: str = "max_revisions") -> int:
    """`value` if it is within 0..MAX_REVISIONS_LIMIT, else ConfigurationError."""
    if not 0 <= value <= MAX_REVISIONS_LIMIT:
        raise ConfigurationError(
            f"{source} doit être compris entre 0 et {MAX_REVISIONS_LIMIT}, reçu {value}"
        )
    return value


def load_prompt_cache(env: Mapping[str, str] | None = None) -> bool:
    """Prompt caching on Scribe/Warden (`SPECTRE_PROMPT_CACHE`, off by default).

    A cache entry is written on the first round and only pays off when a revision round reads
    it back: worth it for long requests that Warden often sends back, a 25% surcharge on the
    request otherwise.
    """
    source = os.environ if env is None else env
    raw = source.get("SPECTRE_PROMPT_CACHE", "").strip().lower()
    if not raw:
        return False
    if raw not in _BOOL_VALUES:
        raise ConfigurationError(
            f"SPECTRE_PROMPT_CACHE doit valoir 1/0, true/false ou on/off, reçu {raw!r}"
        )
    return _BOOL_VALUES[raw]


_BOOL_VALUES: Final[Mapping[str, bool]] = {
    "1": True,
    "true": True,
    "on": True,
    "0": False,
    "false": False,
    "off": False,
}
