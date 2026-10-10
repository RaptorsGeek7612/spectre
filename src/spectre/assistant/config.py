"""Assistant settings and on-disk layout (default `~/.spectre/assistant`)."""

from __future__ import annotations

import json
import os
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

DIR_ENV = "SPECTRE_ASSISTANT_DIR"

# Spectre's sub-agents, by the model that serves them (names chosen by the user)
AGENT_NAMES = {
    "sonnet": "Gétro",  # execution agent by default
    "haiku": "Kaïto",  # the verifier of every mission step
    "chatgpt": "Kyra",  # images, video and multimedia
    "mistral": "Syfer",  # cybersecurity and penetration tests
    "opus": "Spectre",  # Spectre itself, when it runs the steps too
}


# What each one does, as shown in the interface's « Agents » view
AGENT_ROLES = {
    "opus": "L'agent supérieur : il converse avec toi, planifie les missions et rédige leurs "
    "rapports.",
    "sonnet": "Agent d'exécution par défaut : il mène les étapes des missions.",
    "haiku": "Le vérificateur : il contrôle chaque étape des missions ; rapide.",
    "chatgpt": "Images, vidéo et multimédia (via Codex, sur ton compte ChatGPT).",
    "mistral": "Cybersécurité et tests d'intrusion, sur un périmètre autorisé uniquement "
    "(via Vibe, sur ton compte Le Chat).",
}
AGENT_ORDER = ("opus", "sonnet", "haiku", "chatgpt", "mistral")

AGENT_CHOICES = ("claude", *AGENT_NAMES)  # what a mission may ask for ("claude" = the setting)


def agent_name(model: str) -> str:
    return AGENT_NAMES.get(model, model)


def resolve_agent(value: str) -> str:
    """An agent key from a key or a name, whatever the case or accents ("Kaïto" -> "haiku");
    empty when unknown."""

    def plain(text: str) -> str:
        decomposed = unicodedata.normalize("NFKD", text.strip().lower())
        return "".join(c for c in decomposed if not unicodedata.combining(c))

    wanted = plain(value)
    if wanted in AGENT_CHOICES:
        return wanted
    return next((key for key, name in AGENT_NAMES.items() if plain(name) == wanted), "")


def assistant_dir() -> Path:
    """`SPECTRE_ASSISTANT_DIR` or `~/.spectre/assistant`."""
    raw = os.environ.get(DIR_ENV, "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".spectre" / "assistant"


@dataclass
class AssistantConfig:
    """User-editable settings (stored in `config.json`)."""

    name: str = "Spectre"
    user_name: str = ""
    language: str = "fr"
    brain_model: str = "opus"  # the superior agent (Opus 5.5): conversation, plans, reports
    mission_model: str = "sonnet"  # execution agents for mission steps (or chatgpt, mistral)
    claude_bin: str = "claude"
    codex_bin: str = "codex"  # Codex CLI, for the ChatGPT execution agent
    chatgpt_model: str = ""  # empty = Codex's default model for the ChatGPT account
    vibe_bin: str = "vibe"  # Mistral Vibe CLI, for the Mistral execution agent
    mistral_model: str = ""  # a Vibe model alias; empty = Vibe's default Mistral model
    brain_timeout_s: float = 300.0
    city: str = "Paris"
    briefing_hour: int = 8
    consolidation_hour: int = 3
    auto_max_level: int = 2  # actions above this level need your approval
    allowed_roots: list[str] = field(default_factory=lambda: [str(Path.home())])
    wake_word: str = "spectre"
    mic_device: str = ""  # part of the microphone's name; empty = pick a real microphone
    stt_model: str = "small"  # faster-whisper; "base" is faster but mishears French speech
    tts_voice: str = "fr_FR-upmc-medium"  # male French voice (also: fr_FR-gilles-low, tom-medium)
    tts_speaker: str = "pierre"  # speaker of a multi-speaker voice (fr_FR-upmc-medium)
    tts_effect: str = "futuriste"  # onboard-AI timbre: futuriste, vaisseau (subtler) or aucun
    tts_pace: str = "naturel"  # speaking speed: pose, naturel or vif
    speak_initiatives: bool = True
    camera: bool = False  # face recognition of enrolled people (opt-in, nothing leaves the PC)
    camera_index: int = 0

    @classmethod
    def load(cls, root: Path) -> AssistantConfig:
        path = root / "config.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        known = {f.name for f in fields(cls)}
        return (
            cls(**{k: v for k, v in data.items() if k in known})
            if isinstance(data, dict)
            else cls()
        )

    def save(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "config.json").write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def update(self, changes: dict[str, Any]) -> None:
        """Apply validated changes (unknown keys or wrong types raise ValueError)."""
        current = asdict(self)
        for key, value in changes.items():
            if key not in current:
                raise ValueError(f"réglage inconnu : {key}")
            expected = type(current[key])
            if expected is float and isinstance(value, int):
                value = float(value)
            if not isinstance(value, expected) or isinstance(value, bool) != (expected is bool):
                raise ValueError(f"{key} doit être de type {expected.__name__}")
            setattr(self, key, value)
