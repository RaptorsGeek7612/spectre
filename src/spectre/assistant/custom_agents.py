"""Agents Spectre creates on request: a name, an engine (one of the built-in agents' models) and
a role. A mission given to one runs its steps on that engine, with the role added to the
worker's instructions; the plan, the verifier (Kaïto) and the report do not change.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from spectre.assistant.config import AGENT_ORDER, agent_name, resolve_agent
from spectre.assistant.db import Database, now_iso

ENGINES = AGENT_ORDER  # opus, sonnet, haiku, chatgpt, mistral
PREFIX = "agent:"  # a mission's `agent` for a created agent: "agent:<id>"
MAX_AGENTS = 30
MAX_NAME = 30
MAX_ROLE = 300
MAX_INSTRUCTIONS = 4000


class AgentError(ValueError):
    """A refused creation or an unknown agent (the message is for the user)."""


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


class CustomAgents:
    """The created agents, in the assistant's database (shared with the MCP tool process)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM custom_agents ORDER BY id")

    def get(self, value: str) -> dict[str, Any] | None:
        """An agent by its name (any case or accents) or its `agent:<id>` key."""
        if value.startswith(PREFIX) and value[len(PREFIX) :].isdigit():
            return self.db.one(
                "SELECT * FROM custom_agents WHERE id = ?", (int(value[len(PREFIX) :]),)
            )
        wanted = _plain(value)
        return (
            next((a for a in self.list() if _plain(a["name"]) == wanted), None) if wanted else None
        )

    def create(self, name: str, engine: str, role: str, instructions: str = "") -> dict[str, Any]:
        name, role, instructions = name.strip(), role.strip(), instructions.strip()
        if not 2 <= len(name) <= MAX_NAME or not any(c.isalpha() for c in name):
            raise AgentError(f"le nom doit faire de 2 à {MAX_NAME} caractères, avec des lettres")
        if resolve_agent(name) or _plain(name) in ("scout", "scribe", "warden"):
            raise AgentError(f"« {name} » est déjà le nom d'un agent de Spectre")
        if self.get(name):
            raise AgentError(f"un agent s'appelle déjà « {name} »")
        key = resolve_agent(engine)
        if key not in ENGINES:
            names = ", ".join(f"{agent_name(e)} ({e})" for e in ENGINES)
            raise AgentError(f"moteur inconnu « {engine} » ; au choix : {names}")
        if not role:
            raise AgentError("décris le rôle de l'agent (sa spécialité)")
        if len(role) > MAX_ROLE or len(instructions) > MAX_INSTRUCTIONS:
            raise AgentError(f"rôle limité à {MAX_ROLE} caractères, consignes à {MAX_INSTRUCTIONS}")
        if len(self.list()) >= MAX_AGENTS:
            raise AgentError(f"{MAX_AGENTS} agents au maximum : supprimes-en un d'abord")
        agent_id = self.db.execute(
            "INSERT INTO custom_agents(name, engine, role, instructions, created_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (name, key, role, instructions, now_iso()),
        )
        agent = self.db.one("SELECT * FROM custom_agents WHERE id = ?", (agent_id,))
        assert agent is not None
        return agent

    def delete(self, value: str) -> dict[str, Any]:
        agent = self.get(value)
        if agent is None:
            raise AgentError(f"aucun agent créé ne s'appelle « {value} »")
        self.db.execute("DELETE FROM custom_agents WHERE id = ?", (agent["id"],))
        return agent


def worker_brief(agent: dict[str, Any]) -> str:
    """What a created agent adds to the worker's instructions."""
    brief = f"Ta spécialité, définie à ta création : {agent['role']}"
    return (
        f"{brief}\n\nTes consignes :\n{agent['instructions']}" if agent["instructions"] else brief
    )
