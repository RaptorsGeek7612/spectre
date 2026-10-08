"""Assistant settings and on-disk layout (default `~/.spectre/assistant`)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

DIR_ENV = "SPECTRE_ASSISTANT_DIR"


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
    brain_model: str = "sonnet"  # Claude Code model alias for conversation
    mission_model: str = "sonnet"
    claude_bin: str = "claude"
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
    speak_initiatives: bool = True

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
