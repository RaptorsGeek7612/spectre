"""The team page: every agent with its department, the tool and model it runs on (both can be
changed), its voice on the video call, its record and what it did lately.

An agent with its own tool (Kyra on Codex, Octavya on Cursor, Simon on Kimi...) keeps its name
and its specialty when the user moves it to another engine (`agent_engines`): Simon on DeepSeek
is still the accountant. Spectre, Gétro and Kaïto are the brain, execution and verification
roles, whose engine is the role's setting.
"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from spectre.assistant import activity, call
from spectre.assistant.config import (
    AGENT_ROLES,
    EXTERNAL_AGENTS,
    AssistantConfig,
)
from spectre.assistant.custom_agents import PREFIX, CustomAgents
from spectre.assistant.db import Database
from spectre.assistant.providers import ProviderError, Providers, split_ref
from spectre.assistant.trust import Trust

# Spectre, Gétro and Kaïto: the role whose engine they are
ROLE_OF = {"opus": "brain_model", "sonnet": "mission_model", "haiku": "verifier_model"}
# The agents with their own tool: the setting that picks the model inside it
MODEL_SETTING = {
    "chatgpt": "chatgpt_model",
    "mistral": "mistral_model",
    "cursor": "cursor_model",
    "antigravity": "antigravity_model",
    "kimi": "kimi_model",
}
BINARY = {
    "chatgpt": "codex_bin",
    "mistral": "vibe_bin",
    "cursor": "cursor_bin",
    "antigravity": "antigravity_bin",
    "kimi": "kimi_bin",
}

# Spectre's local voices (Piper), clear and without effect on the call: id -> (model, speaker)
VOICES = {
    "pierre": ("fr_FR-upmc-medium", "pierre", "Pierre", "m"),
    "tom": ("fr_FR-tom-medium", "", "Tom", "m"),
    "gilles": ("fr_FR-gilles-low", "", "Gilles (grave)", "m"),
    "jessica": ("fr_FR-upmc-medium", "jessica", "Jessica", "f"),
    "siwis": ("fr_FR-siwis-medium", "", "Siwis", "f"),
}
DEFAULT_VOICES = {
    "opus": ("pierre", "naturel"),
    "sonnet": ("tom", "naturel"),
    "haiku": ("gilles", "vif"),
    "chatgpt": ("siwis", "vif"),
    "mistral": ("tom", "vif"),
    "cursor": ("jessica", "naturel"),
    "antigravity": ("siwis", "pose"),
    "kimi": ("gilles", "pose"),
}


class TeamError(ValueError):
    """A refused change (the message is for the user)."""


def voice_of(config: AssistantConfig, key: str, gender: str = "m") -> tuple[str, str]:
    """(voice id, pace) of an agent on the call."""
    chosen = config.agent_voices.get(key, "")
    default = DEFAULT_VOICES.get(key) or (("siwis" if gender == "f" else "tom"), "naturel")
    return (chosen if chosen in VOICES else default[0]), default[1]


def available(config: AssistantConfig, key: str) -> bool:
    """Is the agent's own tool installed on this PC?"""
    if key == "cursor":
        from spectre.assistant.cli_agents import find_cursor

        return shutil.which(find_cursor(config.cursor_bin)[0]) is not None
    if key == "antigravity":
        from spectre.assistant.cli_agents import find_agy

        return shutil.which(find_agy(config.antigravity_bin)) is not None
    binary = getattr(config, BINARY[key], "") if key in BINARY else config.claude_bin
    return shutil.which(binary) is not None


def members(db: Database, config: AssistantConfig) -> list[dict[str, Any]]:
    """Every agent for the team page, with its engine, model, voice, record and costs."""
    since = (datetime.now(UTC) - timedelta(days=30)).isoformat(timespec="seconds")
    spent = {
        r["agent"]: r
        for r in db.all(
            "SELECT agent, COUNT(*) AS calls, SUM(tokens) AS tokens, SUM(cost_usd) AS cost, "
            "SUM(seconds) AS seconds FROM usage_ledger WHERE ts >= ? GROUP BY agent",
            (since,),
        )
    }
    trust = Trust(db)
    created = {f"{PREFIX}{a['id']}": a for a in CustomAgents(db).list()}
    out = []
    for member in call.members(db):
        key = member["key"]
        own = key in EXTERNAL_AGENTS
        if key in ROLE_OF:
            engine = str(getattr(config, ROLE_OF[key])) or key
        elif own:
            engine = config.agent_engines.get(key, "") or key
        else:
            engine = created[key]["engine"] if key in created else ""
        dossier = trust.dossier(key)
        cost = spent.get(key) or {}
        look = config.agent_looks.get(key, {})
        member = {**member, "gender": look.get("g", member["gender"]), "look": look}
        voice, pace = voice_of(config, key, member["gender"])
        steps = (
            db.one(
                "SELECT COUNT(*) AS n, SUM(status = 'ok') AS ok FROM activity "
                "WHERE agent = ? AND kind = 'step_done' AND ts >= ?",
                (key, since),
            )
            or {}
        )
        out.append(
            {
                **member,
                "role": AGENT_ROLES.get(key) or (created[key]["role"] if key in created else ""),
                "instructions": created[key]["instructions"] if key in created else "",
                "own_tool": own,
                "engine": engine,
                "moved": own and engine != key,
                "role_setting": ROLE_OF.get(key, ""),
                "model": str(getattr(config, MODEL_SETTING[key])) if own else "",
                "available": available(config, key) if key in BINARY or key in ROLE_OF else True,
                "voice": voice,
                "pace": pace,
                "level": dossier["level"],
                "reliability": dossier["reliability"],
                "counts": dossier["counts"],
                "calls": int(cost.get("calls") or 0),
                "tokens": int(cost.get("tokens") or 0),
                "cost": round(float(cost.get("cost") or 0.0), 4),
                "seconds": round(float(cost.get("seconds") or 0.0)),
                "steps": int(steps.get("n") or 0),
                "steps_ok": int(steps.get("ok") or 0),
            }
        )
    return out


def change(
    db: Database,
    config: AssistantConfig,
    providers: Providers,
    key: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """The settings to save for one agent: engine, model in its tool, voice. Raises TeamError."""
    changes: dict[str, Any] = {}
    if "engine" in data:
        wanted = str(data["engine"]).strip()
        if key in ROLE_OF:
            try:
                changes[ROLE_OF[key]] = providers.check(wanted or key)
            except ProviderError as exc:
                raise TeamError(str(exc)) from exc
        elif key in EXTERNAL_AGENTS:
            moved = dict(config.agent_engines)
            if not wanted or wanted == key:
                moved.pop(key, None)  # back to its own tool
            else:
                try:
                    ref = providers.check(wanted)
                except ProviderError as exc:
                    raise TeamError(str(exc)) from exc
                if ref in EXTERNAL_AGENTS:
                    raise TeamError(
                        "un agent ne peut pas emprunter l'outil d'un autre agent : choisis Claude "
                        "ou un modèle fournisseur:modèle"
                    )
                moved[key] = ref
            changes["agent_engines"] = moved
        elif key.startswith(PREFIX):
            agent = CustomAgents(db, providers).get(key)
            if agent is None:
                raise TeamError("agent introuvable")
            try:
                ref = providers.check(wanted)
            except ProviderError as exc:
                raise TeamError(str(exc)) from exc
            db.execute("UPDATE custom_agents SET engine = ? WHERE id = ?", (ref, agent["id"]))
        else:
            raise TeamError(f"agent inconnu : {key}")
    if "model" in data:
        if key not in MODEL_SETTING:
            raise TeamError("le modèle se choisit dans l'outil des agents qui en ont un")
        model = str(data["model"]).strip()
        if len(model) > 120 or any(c.isspace() for c in model):
            raise TeamError(f"nom de modèle invalide : « {model} »")
        changes[MODEL_SETTING[key]] = model
    if "look" in data:
        looks = dict(config.agent_looks)
        look = clean_look(data["look"] or {})
        if look:
            looks[key] = look
        else:
            looks.pop(key, None)  # back to its usual portrait
        changes["agent_looks"] = looks
    if "voice" in data:
        voice = str(data["voice"]).strip()
        if voice and voice not in VOICES:
            raise TeamError(f"voix inconnue : {voice}")
        voices = dict(config.agent_voices)
        if voice:
            voices[key] = voice
        else:
            voices.pop(key, None)
        changes["agent_voices"] = voices
    return changes


def details(db: Database, config: AssistantConfig, key: str) -> dict[str, Any]:
    """One agent in depth: its instructions, its recent activity (last 30 actions with their
    status, duration, command and result), its tool counts and its record."""
    from spectre.assistant.missions import SPECIALTIES

    rows = activity.rows(db, agent=key, limit=30)
    counts: dict[str, int] = {}
    for row in db.all(
        "SELECT title, COUNT(*) AS n FROM activity WHERE agent = ? AND kind = 'tool' "
        "GROUP BY title ORDER BY n DESC",
        (key,),
    ):
        counts[row["title"]] = int(row["n"])
    created = CustomAgents(db).get(key) if key.startswith(PREFIX) else None
    prompt = SPECIALTIES.get(key, "")
    if created:
        prompt = f"{created['role']}\n\n{created['instructions']}".strip()
    return {
        "key": key,
        "prompt": prompt or AGENT_ROLES.get(key, ""),
        "recent": rows[::-1],
        "tools": counts,
        "dossier": Trust(db).dossier(key),
        "remote": bool(split_ref(config.agent_engines.get(key, ""))[0]),
    }


# ---- portraits ----------------------------------------------------------------------------------

PORTRAIT_MAX = 2 * 1024 * 1024
PORTRAIT_TYPES = {b"\x89PNG": ("png", "image/png"), b"\xff\xd8\xff": ("jpg", "image/jpeg")}


def _portrait_kind(data: bytes) -> tuple[str, str] | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return next((kind for magic, kind in PORTRAIT_TYPES.items() if data.startswith(magic)), None)


def _portrait_name(key: str) -> str:
    return key.replace(":", "-")


def save_portrait(root: Path, key: str, data: bytes) -> None:
    """The user's own picture for an agent (PNG, JPEG or WebP, 2 MB at most)."""
    kind = _portrait_kind(data)
    if kind is None:
        raise TeamError("image PNG, JPEG ou WebP uniquement")
    if len(data) > PORTRAIT_MAX:
        raise TeamError("image de 2 Mo au maximum")
    folder = root / "portraits"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob(f"{_portrait_name(key)}.*"):
        old.unlink()
    (folder / f"{_portrait_name(key)}.{kind[0]}").write_bytes(data)


def portrait(root: Path, key: str) -> tuple[bytes, str] | None:
    for path in (root / "portraits").glob(f"{_portrait_name(key)}.*"):
        data = path.read_bytes()
        kind = _portrait_kind(data)
        if kind:
            return data, kind[1]
    return None


def delete_portrait(root: Path, key: str) -> None:
    for path in (root / "portraits").glob(f"{_portrait_name(key)}.*"):
        path.unlink()


def portraits(root: Path) -> set[str]:
    folder = root / "portraits"
    return {p.stem for p in folder.iterdir()} if folder.is_dir() else set()


# ---- appearance (the « create a Sim » editor) ---------------------------------------------------

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
LOOK_CHOICES = {
    "g": ("m", "f"),
    "style": ("short", "side", "crew", "neat", "long", "bob", "bun", "undercut", "receding"),
    "beard": ("", "stubble", "short", "trim"),
    "glasses": ("", "round", "square"),
    "outfit_kind": ("shirt", "tie", "blazer", "hoodie", "cardigan"),
}
LOOK_COLORS = ("skin", "shade", "hair", "eyes", "lips", "outfit", "shirt", "accent", "bg")
LOOK_FLAGS = ("jewel", "age")


def clean_look(look: Any) -> dict[str, Any]:
    """A portrait's settings from the editor, checked; raises TeamError on anything odd."""
    if not isinstance(look, dict):
        raise TeamError("apparence invalide")
    out: dict[str, Any] = {}
    for key, value in look.items():
        if key in LOOK_CHOICES:
            if value not in LOOK_CHOICES[key]:
                raise TeamError(f"apparence : valeur inconnue pour {key}")
            out[key] = value
        elif key in LOOK_COLORS:
            if not isinstance(value, str) or not HEX.match(value):
                raise TeamError(f"apparence : couleur invalide pour {key}")
            out[key] = value.lower()
        elif key in LOOK_FLAGS:
            out[key] = bool(value)
        else:
            raise TeamError(f"apparence : réglage inconnu {key}")
    kind = out.pop("outfit_kind", None)
    if kind is not None:  # the clothes the drawing understands
        for flag in ("tie", "blazer", "hoodie", "cardigan"):
            out[flag] = kind == flag
    return out
