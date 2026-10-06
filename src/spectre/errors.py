"""Exceptions raised by Spectre."""

from __future__ import annotations


class SpectreError(Exception):
    """Base class for every error raised by Spectre."""

    def __init__(self, message: str, *, agent: str | None = None) -> None:
        self.agent = agent
        prefix = f"[{agent}] " if agent else ""
        super().__init__(f"{prefix}{message}")


class ConfigurationError(SpectreError):
    """Invalid configuration (bad environment value, missing API key...)."""


class MissingAPIKeyError(ConfigurationError):
    """ANTHROPIC_API_KEY is not available while real models are required."""

    def __init__(self) -> None:
        super().__init__(
            "clé API introuvable : définissez ANTHROPIC_API_KEY ou créez un fichier .env"
        )


class AgentRefusalError(SpectreError):
    """The model refused to answer (stop_reason == "refusal")."""

    def __init__(self, agent: str) -> None:
        super().__init__("le modèle a refusé de répondre (stop_reason=refusal)", agent=agent)


class EmptyOutputError(SpectreError):
    """The model returned no text."""

    def __init__(self, agent: str) -> None:
        super().__init__("le modèle n'a renvoyé aucun texte", agent=agent)
