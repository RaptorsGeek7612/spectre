"""Which engine serves a reference, and the fallback chain when one fails.

`opus`/`sonnet`/`haiku` -> Claude Code CLI, `chatgpt` -> Codex CLI, `mistral` -> Vibe CLI,
`cursor` -> Cursor CLI, `antigravity` -> Antigravity CLI, `simon` -> his hosted model
(DeepSeek by default),
`provider:model` -> an OpenAI-compatible endpoint (`llm.HttpAgent`). An agent with its own tool
can be moved to another engine (`agent_engines`: Octavya on Claude...). Like Hermes Agent, the
fallback is per call: the next call tries the chosen engine first again.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from spectre.assistant.brain import Reply, failed
from spectre.assistant.config import ROLES, AssistantConfig, resolve_role
from spectre.assistant.providers import ProviderError, Providers, split_ref

CLAUDE = ("opus", "sonnet", "haiku")


def _codex(config: AssistantConfig, root: Path) -> Any:
    from spectre.assistant.codex import CodexCLI

    return CodexCLI(config, root)


def _vibe(config: AssistantConfig, root: Path) -> Any:
    from spectre.assistant.mistral import VibeCLI

    return VibeCLI(config, root)


def _cli(name: str) -> Any:
    def make(config: AssistantConfig, root: Path) -> Any:
        from spectre.assistant import cli_agents

        return getattr(cli_agents, name)(config, root)

    return make


EXTERNAL: dict[str, Any] = {  # non-Claude CLI agents
    "chatgpt": _codex,
    "mistral": _vibe,
    "cursor": _cli("CursorCLI"),
    "antigravity": _cli("AntigravityCLI"),
}


def resolve(config: AssistantConfig, ref: str) -> str:
    """The engine that really serves a reference: an agent moved to another engine
    (`agent_engines`) runs there, Simon on his hosted model; anything else is itself."""
    from spectre.assistant.config import HOSTED_AGENTS
    from spectre.config import AGENT_DEFAULT_ENGINES

    if ref not in EXTERNAL and ref not in HOSTED_AGENTS:
        return ref
    moved = config.agent_engines.get(ref, "")
    if moved and moved not in EXTERNAL and moved not in HOSTED_AGENTS:
        return moved
    return AGENT_DEFAULT_ENGINES.get(ref, ref)


class Engines:
    """Hands out the agent behind each engine reference (CLI agents are created on first use)."""

    def __init__(
        self,
        cli: Any,
        *,
        providers: Providers | None = None,
        agents: dict[str, Any] | None = None,
    ) -> None:
        self.cli = cli
        self._providers = providers
        self.agents = dict(agents or {})  # "chatgpt", "mistral", "http" -> agent

    @property
    def providers(self) -> Providers:
        if self._providers is None:
            self._providers = Providers(self.cli.root)
        return self._providers

    def worker(self, ref: str) -> tuple[Any, str]:
        """(agent, model to pass to its `ask`) for a reference."""
        ref = resolve(self.cli.config, ref) if hasattr(self.cli, "config") else ref
        provider, model = split_ref(ref)
        if provider:
            return self._agent("http"), f"{provider}:{model}"
        if model not in EXTERNAL:
            return self.cli, model
        return self._agent(model), model

    def _agent(self, key: str) -> Any:
        if key not in self.agents:
            if key == "http":
                from spectre.assistant.llm import HttpAgent

                self.agents[key] = HttpAgent(
                    self.cli.config, self.cli.root, providers=self.providers
                )
            else:
                self.agents[key] = EXTERNAL[key](self.cli.config, self.cli.root)
        return self.agents[key]

    def ask(
        self,
        ref: str,
        prompt: str,
        system: str,
        *,
        tools: bool = False,
        history: Sequence[dict[str, str]] = (),
    ) -> Reply:
        """One stateless call on one engine; CLI engines get the history inside the prompt."""
        agent, model = self.worker(ref)
        if split_ref(ref)[0]:
            return agent.ask(  # type: ignore[no-any-return]
                prompt, system=system, model=model, with_tools=tools, history=history
            )
        if history:
            thread = "\n".join(
                f"{'Utilisateur' if m['role'] == 'user' else 'Toi'} : {m['content']}"
                for m in history
            )
            prompt = f"[Fil de la conversation :\n{thread}]\n\n{prompt}"
        return agent.ask(prompt, system=system, model=model, with_tools=tools)  # type: ignore[no-any-return]

    def ask_chain(
        self,
        refs: Sequence[str],
        prompt: str,
        system: str,
        *,
        tools: bool = False,
        history: Sequence[dict[str, str]] = (),
    ) -> tuple[Reply, str]:
        """Try each engine in order until one answers; (reply, engine that answered).
        All failing returns the first engine's error, which is the most telling."""
        first: tuple[Reply, str] | None = None
        for ref in dict.fromkeys(r for r in refs if r):  # in order, without duplicates
            reply = self.ask(ref, prompt, system, tools=tools, history=history)
            if not failed(reply):
                return reply, ref
            first = first or (reply, ref)
        return first or (Reply("aucun moteur configuré", "", True), "")


MAX_FALLBACKS = 5


def assign(config: AssistantConfig, providers: Providers, role: str, engine: str) -> str:
    """Set a role's engine (validated); returns the setting changed. Raises ProviderError."""
    setting = resolve_role(role)
    if not setting:
        raise ProviderError(
            f"rôle inconnu « {role} » ; au choix : cerveau, mission, vérificateur, planificateur"
        )
    engine = engine.strip()
    if setting in ("planner_model", "learning_model") and engine.lower() in (
        "",
        "cerveau",
        "brain",
        "verificateur",
        "vérificateur",
    ):
        value = ""
    else:
        value = providers.check(engine)
    config.update({setting: value})
    return setting


def set_fallbacks(config: AssistantConfig, providers: Providers, engines: Sequence[str]) -> None:
    """Replace the fallback chain (validated, in order, at most MAX_FALLBACKS)."""
    chain = list(dict.fromkeys(providers.check(e) for e in engines if e.strip()))
    if len(chain) > MAX_FALLBACKS:
        raise ProviderError(f"{MAX_FALLBACKS} moteurs de secours au maximum")
    config.update({"fallback_models": chain})


def roles(config: AssistantConfig) -> list[dict[str, str]]:
    """Each switchable role with its engine, for the interface and the brain."""
    return [
        {"role": key, "label": label, "engine": str(getattr(config, key))}
        for key, label in ROLES.items()
    ]


def summary(config: AssistantConfig, providers: Providers, with_models: bool = True) -> str:
    """What `list_models` tells the brain: roles, fallbacks, providers and their models."""
    lines = ["Moteurs par rôle :"]
    lines += [
        f"- {r['role']} ({r['label']}) : {r['engine'] or '(le cerveau)'}" for r in roles(config)
    ]
    chain = ", ".join(config.fallback_models) or "(aucun)"
    lines += [
        f"Secours, dans l'ordre : {chain}",
        "Moteurs CLI : opus, sonnet, haiku, chatgpt (Codex), mistral (Vibe), cursor, "
        "antigravity ; Simon (simon) sur DeepSeek",
    ]
    for item in providers.describe():
        state = "prêt" if item["ready"] else f"clé manquante ({item['key_env']})"
        line = f"- {item['id']} : {item['label']}, {state}"
        if with_models and item["ready"]:
            found = providers.models(item["id"], timeout=3.0)
            if found:
                line += " ; modèles : " + ", ".join(found[:15])
            elif item["local"]:
                line += " ; serveur local éteint"
        lines.append(line)
    return "\n".join(lines)
