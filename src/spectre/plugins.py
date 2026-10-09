"""Agents added by the user without writing code, from `spectre-agents.toml`.

Each `[[agent]]` table describes one more agent, run after Scout, Scribe or Warden: it reads
one text of the pipeline (brief, draft or final text), sends it with its own instructions to
its model, and writes the answer back. Example, a translator after Warden:

    [[agent]]
    name = "traducteur"
    after = "warden"
    prompt = "Traduis le texte en anglais, sans rien ajouter."
    reads = "final_text"      # default: the text it writes
    writes = "final_text"
    # model = "<identifiant exact>"   # default: Scribe's model
    max_tokens = 8000
    effort = "low"

The file is `SPECTRE_AGENTS_FILE`, else `spectre-agents.toml` in the current folder.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from spectre.config import (
    AGENT_NAMES,
    DEFAULT_SPECS,
    AgentSpec,
    _is_haiku,
    _parse_effort,
    _parse_positive_int,
)
from spectre.errors import ConfigurationError
from spectre.steps import OUTPUT_KEYS, Step, extra_step

AGENTS_FILE_ENV: Final = "SPECTRE_AGENTS_FILE"
DEFAULT_AGENTS_FILE: Final = "spectre-agents.toml"
_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_KEYS = {
    "name",
    "after",
    "prompt",
    "reads",
    "writes",
    "model",
    "max_tokens",
    "effort",
    "temperature",
}


@dataclass(frozen=True)
class ExtraAgent:
    """One agent added by the user."""

    name: str
    after: str
    prompt: str
    reads: str
    writes: str
    spec: AgentSpec

    @property
    def step(self) -> Step:
        return extra_step(self.name, self.prompt, self.reads, self.writes)


def agents_file(env: Mapping[str, str] | None = None) -> Path | None:
    """The agents file to load, or None when there is none."""
    source = os.environ if env is None else env
    configured = source.get(AGENTS_FILE_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise ConfigurationError(f"{AGENTS_FILE_ENV} : fichier introuvable : {path}")
        return path
    default = Path(DEFAULT_AGENTS_FILE)
    return default if default.is_file() else None


def load_extra_agents(
    path: Path | None = None, env: Mapping[str, str] | None = None
) -> list[ExtraAgent]:
    """The agents described in `path` (default: `agents_file()`); [] without a file."""
    path = path or agents_file(env)
    if path is None:
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"impossible de lire {path} : {exc}") from exc
    tables = data.get("agent", [])
    if not isinstance(tables, list):
        raise ConfigurationError(f"{path} : utilisez des tables [[agent]]")
    agents: list[ExtraAgent] = []
    for index, table in enumerate(tables, start=1):
        agent = _parse_agent(table, f"{path.name}, agent n°{index}")
        if agent.name in {a.name for a in agents}:
            raise ConfigurationError(f"{path.name} : agent en double : {agent.name!r}")
        agents.append(agent)
    return agents


def _parse_agent(table: Any, where: str) -> ExtraAgent:
    if not isinstance(table, dict):
        raise ConfigurationError(f"{where} : table [[agent]] attendue")
    unknown = sorted(set(table) - _KEYS)
    if unknown:
        raise ConfigurationError(f"{where} : clés inconnues : {', '.join(unknown)}")
    name = str(table.get("name", "")).strip()
    if not _NAME.match(name) or name in AGENT_NAMES:
        raise ConfigurationError(
            f"{where} : nom invalide {name!r} (minuscules, chiffres et _, autre que "
            f"{', '.join(AGENT_NAMES)})"
        )
    after = str(table.get("after", "")).strip()
    if after not in AGENT_NAMES:
        raise ConfigurationError(f"{where} : after doit valoir {', '.join(AGENT_NAMES)}")
    prompt = str(table.get("prompt", "")).strip()
    if not prompt:
        raise ConfigurationError(f"{where} : prompt manquant")
    writes = str(table.get("writes", "")).strip()
    reads = str(table.get("reads", writes)).strip()
    for key, value in (("writes", writes), ("reads", reads)):
        if value not in OUTPUT_KEYS:
            raise ConfigurationError(f"{where} : {key} doit valoir {', '.join(OUTPUT_KEYS)}")
    return ExtraAgent(name, after, prompt, reads, writes, _parse_spec(table, name, where))


def _parse_spec(table: dict[str, Any], name: str, where: str) -> AgentSpec:
    model = str(table.get("model", DEFAULT_SPECS["scribe"].model)).strip()
    max_tokens = _parse_positive_int(f"{where} : max_tokens", str(table.get("max_tokens", 8000)))
    effort = table.get("effort")
    temperature = table.get("temperature")
    if _is_haiku(model):
        if effort is not None:
            raise ConfigurationError(f"{where} : {model} n'accepte pas d'effort")
        if temperature is not None and not isinstance(temperature, int | float):
            raise ConfigurationError(f"{where} : temperature doit être un nombre")
        return AgentSpec(name, model, max_tokens, temperature, None)
    if temperature is not None:
        raise ConfigurationError(f"{where} : {model} n'accepte pas de temperature (réglez effort)")
    return AgentSpec(
        name,
        model,
        max_tokens,
        None,
        _parse_effort(f"{where} : effort", str(effort)) if effort is not None else None,
    )
