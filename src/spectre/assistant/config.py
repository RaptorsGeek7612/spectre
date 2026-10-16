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
    "cursor": "Octavya",  # legal department
    "antigravity": "Clarke",  # finance and insurance (a woman)
    "simon": "Simon",  # chartered accountant (on DeepSeek)
    "shelby": "Shelby",  # animals (a woman)
    "ysyss": "Ysyss",  # science and humans (a woman)
    "lexy": "Lexy",  # betting, investing, crypto (a woman)
    "opus": "Spectre",  # Spectre itself, when it runs the steps too
}

# The tool each agent runs in, as the interface names it (the key stays the engine reference)
AGENT_TOOLS = {
    "opus": "Claude Code",
    "sonnet": "Claude Code",
    "haiku": "Claude Code",
    "chatgpt": "Codex",
    "mistral": "Vibe",
    "cursor": "Cursor",
    "antigravity": "Antigravity",
    "simon": "DeepSeek",
    "shelby": "Claude",
    "ysyss": "Claude",
    "lexy": "Claude",
}

# Their department in the team page and the video call
AGENT_DEPARTMENTS = {
    "opus": "Direction",
    "sonnet": "Exécution",
    "haiku": "Vérification",
    "chatgpt": "Multimédia, production, pub et communication",
    "mistral": "Cybersécurité",
    "cursor": "Juridique et contrats",
    "antigravity": "Finances et assurances",
    "simon": "Expertise comptable et trading",
    "shelby": "Animalier",
    "ysyss": "Sciences et savoirs",
    "lexy": "Jeux, paris et investissements",
}

# Another name the user may give an engine: the tool rather than the account
ENGINE_ALIASES = {
    "codex": "chatgpt",
    "vibe": "mistral",
    "agy": "antigravity",
}


# What each one does, as shown in the interface's « Agents » view
AGENT_ROLES = {
    "opus": "L'agent supérieur : il converse avec toi, planifie les missions et rédige leurs "
    "rapports.",
    "sonnet": "Agent d'exécution par défaut : il mène les étapes des missions.",
    "haiku": "Le vérificateur : il contrôle chaque étape des missions ; rapide.",
    "chatgpt": "Images, vidéo et multimédia, publicité et communication (via Codex, sur ton "
    "compte ChatGPT) ; productrice et réalisatrice de clips, séries et films ; elle crée les "
    "images et les vidéos sur ce PC avec ComfyUI et les décline pour chaque réseau.",
    "mistral": "Cybersécurité et tests d'intrusion, sur un périmètre autorisé uniquement "
    "(via Vibe, sur ton compte Le Chat).",
    "cursor": "Juridique : statuts, contrats, CGV et CGU, RGPD, propriété intellectuelle, "
    "conformité ; experte de tous les contrats en droit français, européen et international "
    "(via Cursor, sur ton compte Cursor).",
    "antigravity": "Finances et assurances : trésorerie, budget, prévisionnel, financement, "
    "levée de fonds, contrats d'assurance (via Antigravity, sur ton compte Google).",
    "simon": "Expert-comptable : comptabilité, TVA, liasses et bilans, charges sociales, "
    "fiscalité de l'entreprise ; expert et formateur en trading, données de marché en temps "
    "réel (sur DeepSeek, avec ta clé).",
    "shelby": "Animalière : culture animale, comportement et éducation, biologie, santé et "
    "soins, toilettage de toutes les espèces ; experte de la nature, de la biodiversité et des "
    "impacts du climat (air, terre, mer), données ouvertes en temps réel.",
    "ysyss": "Sciences et être humain : physique, chimie, maths, biologie, astronomie, "
    "santé, psychologie, langues et dialectes, sports, arts et cultures.",
    "lexy": "Jeux d'argent, paris sportifs, investissement et bourse, blockchain, NFT et "
    "cryptomonnaies ; jamais de promesse de gain, rappelle les risques.",
}
AGENT_ORDER = (
    "opus",
    "sonnet",
    "haiku",
    "chatgpt",
    "mistral",
    "cursor",
    "antigravity",
    "simon",
    "shelby",
    "ysyss",
    "lexy",
)
EXTERNAL_AGENTS = ("chatgpt", "mistral", "cursor", "antigravity")  # their own CLI
HOSTED_AGENTS = (
    "simon",
    "shelby",
    "ysyss",
    "lexy",
)  # on a model (`AGENT_DEFAULT_ENGINES`), changeable

AGENT_CHOICES = ("claude", *AGENT_NAMES)  # what a mission may ask for ("claude" = the setting)

# The roles whose engine the user can switch (Hermes-style `/model`): setting -> description.
# Each takes an engine reference: opus, sonnet, haiku, chatgpt, mistral or provider:model.
ROLES = {
    "brain_model": "cerveau : la conversation avec toi",
    "mission_model": "exécution des étapes de mission",
    "verifier_model": "vérification de chaque étape",
    "planner_model": "plans et rapports de mission",
    "learning_model": "apprentissage : relecture des missions réussies",
}
ROLE_ALIASES = {
    "cerveau": "brain_model",
    "brain": "brain_model",
    "mission": "mission_model",
    "missions": "mission_model",
    "execution": "mission_model",
    "verificateur": "verifier_model",
    "verifier": "verifier_model",
    "verification": "verifier_model",
    "planificateur": "planner_model",
    "planner": "planner_model",
    "plans": "planner_model",
    "rapports": "planner_model",
    "apprentissage": "learning_model",
    "learning": "learning_model",
}


def agent_name(model: str) -> str:
    return AGENT_NAMES.get(model, model)


def resolve_agent(value: str) -> str:
    """An agent key from a key or a name, whatever the case or accents ("Kaïto" -> "haiku");
    empty when unknown."""

    def plain(text: str) -> str:
        decomposed = unicodedata.normalize("NFKD", text.strip().lower())
        return "".join(c for c in decomposed if not unicodedata.combining(c))

    wanted = plain(value)
    wanted = ENGINE_ALIASES.get(wanted, wanted)
    if wanted in AGENT_CHOICES:
        return wanted
    return next((key for key, name in AGENT_NAMES.items() if plain(name) == wanted), "")


def resolve_role(value: str) -> str:
    """A role's setting from its name in French or English ("cerveau" -> "brain_model")."""
    decomposed = unicodedata.normalize("NFKD", value.strip().lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    if plain in ROLES:
        return plain
    return ROLE_ALIASES.get(plain, ROLE_ALIASES.get(plain.removesuffix("_model"), ""))


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
    verifier_model: str = "haiku"  # Kaïto's engine: checks each mission step
    planner_model: str = ""  # plans and reports missions; empty = the brain's engine
    fallback_models: list[str] = field(default_factory=list)  # tried in order when one fails
    mission_parallel: int = 2  # missions running at the same time (1 to 4)
    learning_model: str = ""  # reviews finished missions for skills; empty = the verifier
    learn_from_missions: bool = True  # propose skills after successful missions
    earned_autonomy: bool = True  # autopilot and relaxed approvals for trusted agents only
    telegram_notify: bool = True  # notifications and approvals also go to paired chats
    claude_bin: str = "claude"
    codex_bin: str = "codex"  # Codex CLI, for the ChatGPT execution agent
    chatgpt_model: str = ""  # empty = Codex's default model for the ChatGPT account
    vibe_bin: str = "vibe"  # Mistral Vibe CLI, for the Mistral execution agent
    mistral_model: str = ""  # a Vibe model alias; empty = Vibe's default Mistral model
    cursor_bin: str = "cursor-agent"  # Cursor CLI, for Octavya (legal)
    cursor_model: str = ""  # empty = Cursor's « auto »
    antigravity_bin: str = "agy"  # Antigravity CLI, for Clarke (finance and insurance)
    antigravity_model: str = ""  # empty = the model chosen in Antigravity
    # Another engine for an agent than its own tool: agent key -> engine reference
    # (for example {"cursor": "sonnet"}: Octavya then works on Claude Sonnet)
    agent_engines: dict[str, str] = field(default_factory=dict)
    agent_voices: dict[str, str] = field(default_factory=dict)  # agent key -> voice id
    agent_looks: dict[str, dict[str, Any]] = field(default_factory=dict)  # portraits
    comfyui_url: str = "http://127.0.0.1:8188"  # Kyra's studio (images and videos)
    comfyui_dir: str = ""  # ComfyUI folder (start_comfyui.cmd); empty = ~/ComfyUI
    laya_url: str = ""  # a laya-serve address; empty = the local `laya` package
    brain_timeout_s: float = 300.0
    city: str = "Paris"
    briefing_hour: int = 8
    consolidation_hour: int = 3
    auto_max_level: int = 2  # actions above this level need your approval
    allowed_roots: list[str] = field(default_factory=lambda: [str(Path.home())])
    wake_word: str = "spectre"
    mic_device: str = ""  # part of the microphone's name; empty = pick a real microphone
    stt_model: str = "small"  # faster-whisper: small (fast), medium or large-v3-turbo (finer)
    tts_voice: str = "fr_FR-upmc-medium"  # male French voice (also: fr_FR-gilles-low, tom-medium)
    tts_speaker: str = "pierre"  # speaker of a multi-speaker voice (fr_FR-upmc-medium)
    tts_effect: str = "futuriste"  # onboard-AI timbre: futuriste, vaisseau (subtler) or aucun
    tts_pace: str = "naturel"  # speaking speed: pose, naturel or vif
    speak_initiatives: bool = True
    befriend_per_day: int = 2  # times a day Spectre comes to talk to you on its own (0 = never)
    befriend_hours: str = "10-21"  # when it may: from hour to hour
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
