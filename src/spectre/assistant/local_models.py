"""Which local LM Studio model suits which agent, and moving an agent there on request.

LM Studio's REST API (`/api/v1/models`) describes each installed model: size, parameters,
vision, tool use, reasoning, context. Spectre scores them against an agent's trade (a coder
for Gétro, vision for Kyra, long context for Octavya, speed for the verifier) and against this
PC's memory, then explains its pick. Agents keep their engine: `set_agent_engine` only runs when
the user asks for a change, and an empty engine sends the agent back to its original one.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import unicodedata
import urllib.request
from dataclasses import dataclass
from typing import Any

from spectre.assistant.actions import ActionError

LMSTUDIO_API = "http://127.0.0.1:1234/api/v1/models"
TIMEOUT_S = 5.0
GB = 1_000_000_000


@dataclass(frozen=True)
class Need:
    """What an agent's work asks of a model (weights 0-3)."""

    trade: str
    tools: int = 2
    vision: int = 0
    code: int = 0
    reasoning: int = 0
    context: int = 0
    fast: bool = False
    raw_ok: bool = False  # an uncensored model is acceptable (security research)


NEEDS = {
    "opus": Need("direction, conversation et plans", tools=3, reasoning=2, vision=1, context=1),
    "sonnet": Need("exécution des missions", tools=3, code=1, context=1),
    "haiku": Need("vérification rapide", tools=1, reasoning=1, fast=True),
    "chatgpt": Need("multimédia, pub et communication", tools=1, vision=2),
    "mistral": Need("cybersécurité", tools=2, code=2, reasoning=1, raw_ok=True),
    "cursor": Need("juridique et contrats", tools=1, reasoning=2, context=2),
    "antigravity": Need("finances et assurances", tools=2, reasoning=2),
    "simon": Need("comptabilité et trading", tools=2, reasoning=2),
    "shelby": Need("animaux, nature et climat", tools=2, vision=1),
    "ysyss": Need("sciences et humain", tools=1, reasoning=3),
    "lexy": Need("jeux, paris, bourse et crypto", tools=2, reasoning=1),
    "charlotte": Need("graphisme", tools=2, vision=2),
    "celya": Need("écriture romanesque", tools=1, reasoning=2, context=2),
}
DEFAULT_NEED = Need("agent personnalisé", tools=2, reasoning=1)

CODE = re.compile(r"cod(e|er|estral|ex)|devstral|cursorcore|starcoder", re.IGNORECASE)
RAW = re.compile(r"uncensored|heretic|abliterat|dolphin|venice|rpmax", re.IGNORECASE)
OLD = re.compile(
    r"mistral-7b|openhermes|neuralhermes|airoboros|openorca|dragon-mistral|gpt2|smollm",
    re.IGNORECASE,
)
MODERN = re.compile(
    r"gemma-4|qwen3\.[5-9]|ministral-3|mistral-small-3|gpt-oss|granite-4|bonsai",
    re.IGNORECASE,
)
THINKING = re.compile(r"reason|thinking|-r1", re.IGNORECASE)


def _fetch() -> list[dict[str, Any]]:
    request = urllib.request.Request(LMSTUDIO_API, headers={"User-Agent": "Spectre"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        return list(json.loads(response.read().decode("utf-8")).get("models") or [])


def ram_gb() -> float:
    """This PC's memory, in GB (16 when it cannot be read)."""
    try:
        if sys.platform == "win32":

            class Status(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("load", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong),
                    ("free", ctypes.c_ulonglong),
                    ("rest", ctypes.c_ulonglong * 5),
                ]

            status = Status()
            status.length = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return float(status.total) / GB
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / GB
    except (OSError, ValueError, AttributeError):
        return 16.0


def _params(text: str) -> float:
    """« 12B » -> 12, « 8x3B » -> 24, « 855M » -> 0.855; 0 when unknown."""
    m = re.fullmatch(r"(?:(\d+)x)?([\d.]+)\s*([BM])", (text or "").strip(), re.IGNORECASE)
    if not m:
        return 0.0
    value = float(m.group(2)) * (int(m.group(1)) if m.group(1) else 1)
    return value / 1000 if m.group(3).upper() == "M" else value


def score(model: dict[str, Any], need: Need, budget_gb: float) -> tuple[float, list[str]] | None:
    """(score, reasons) of one model for one need; None when it is out of the race."""
    key = str(model.get("key", ""))
    size = float(model.get("size_bytes") or 0) / GB
    params = _params(str(model.get("params_string") or ""))
    caps = model.get("capabilities") or {}
    if model.get("type") != "llm" or size < 0.8 or params < 1:
        return None  # embeddings, broken downloads, toy models
    if size > budget_gb:
        return None
    reasons: list[str] = []
    bits = int((model.get("quantization") or {}).get("bits_per_weight") or 4)
    keep = {1: 0.35, 2: 0.6, 3: 0.85}.get(bits, 1.0)  # heavy compression loses quality
    total = min(params, 14) / 3 * keep  # more parameters, better answers (within what fits)
    if bits <= 2:
        reasons.append(f"très compressé ({bits} bit{'s' if bits > 1 else ''})")
    if caps.get("trained_for_tool_use"):
        total += 3 * need.tools
        if need.tools >= 2:
            reasons.append("sait appeler les outils")
    elif need.tools:
        total -= 2 * need.tools
        reasons.append("pas entraîné aux outils")
    if need.vision and caps.get("vision"):
        total += 2 * need.vision
        reasons.append("voit les images")
    if CODE.search(key):
        total += 3 * need.code if need.code else -1
        if need.code:
            reasons.append("spécialisé code")
    if need.reasoning and (caps.get("reasoning") or THINKING.search(key)):
        total += 2 * need.reasoning
        reasons.append("raisonne")
    if need.context and int(model.get("max_context_length") or 0) >= 128_000:
        total += need.context
        reasons.append("long contexte")
    if need.fast:  # on a CPU, speed follows size
        total += 2 * (6 - size)
        if size <= 5:
            reasons.append(f"rapide ({size:.1f} Go)")
        elif size > 6:
            reasons.append(f"lent sur ce PC ({size:.1f} Go)")
    if MODERN.search(key):
        total += 2
        reasons.append("génération récente")
    if OLD.search(key):
        total -= 3
        reasons.append("ancien")
    if RAW.search(key):
        total -= 1 if need.raw_ok else 4
        reasons.append("débridé (déconseillé pour un usage pro)" if not need.raw_ok else "débridé")
    return total, reasons


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def resolve_agent(name: str) -> str:
    """An agent's key from its name or key (« Kyra » -> chatgpt); raises ActionError."""
    from spectre.assistant.config import AGENT_NAMES

    wanted = _plain(name)
    for key, label in AGENT_NAMES.items():
        if wanted in (_plain(key), _plain(label)):
            return key
    if wanted.startswith("custom") or wanted.startswith("perso"):
        return name.strip()  # a custom agent's key, checked by team.change
    known = ", ".join(sorted(set(AGENT_NAMES.values())))
    raise ActionError(f"agent inconnu : {name} (au choix : {known})")


def current(config: Any, key: str) -> tuple[str, str]:
    """(engine now, original engine) of an agent."""
    from spectre.assistant.config import AGENT_TOOLS, AssistantConfig
    from spectre.assistant.team import ROLE_OF

    if key in ROLE_OF:
        setting = ROLE_OF[key]
        return getattr(config, setting) or key, getattr(AssistantConfig(), setting) or key
    original = f"son outil d'origine ({AGENT_TOOLS.get(key, key)})"
    return config.agent_engines.get(key, "") or original, original


def ranking(key: str, models: list[dict[str, Any]], ram: float) -> tuple[list[Any], int]:
    """The models fit for an agent, best first, and how many were too heavy for this PC."""
    need = NEEDS.get(key, DEFAULT_NEED)
    budget = ram * 0.55  # the model, its context and Spectre itself must fit in memory
    scored, heavy = [], 0
    for model in models:
        if float(model.get("size_bytes") or 0) / GB > budget and model.get("type") == "llm":
            heavy += 1
        result = score(model, need, budget)
        if result:
            scored.append((result[0], model, result[1]))
    scored.sort(key=lambda item: -item[0])
    return scored, heavy


def recommend(config: Any, agent: str, models: list[dict[str, Any]] | None = None) -> str:
    """The best local models for one agent (or the best one for every agent), explained."""
    from spectre.assistant.config import AGENT_NAMES

    try:
        models = _fetch() if models is None else models
    except (OSError, ValueError) as exc:
        raise ActionError(
            f"LM Studio ne répond pas ({exc}) : lance LM Studio et son serveur (port 1234)"
        ) from exc
    ram = ram_gb()
    if not agent.strip():
        lines = [f"Meilleur modèle LM Studio par agent (PC : {ram:.0f} Go de RAM) :"]
        for key in NEEDS:
            best, _ = ranking(key, models, ram)
            pick = best[0][1]["key"] if best else "aucun"
            lines.append(f"• {AGENT_NAMES.get(key, key)} ({NEEDS[key].trade}) : {pick}")
        lines.append("Rien n'est changé : demande-moi de l'appliquer à un agent.")
        return "\n".join(lines)
    key = resolve_agent(agent)
    now, original = current(config, key)
    best, heavy = ranking(key, models, ram)
    need = NEEDS.get(key, DEFAULT_NEED)
    lines = [
        f"{AGENT_NAMES.get(key, key)} ({need.trade}) — moteur actuel : {now} ; d'origine : "
        f"{original}.",
        f"Modèles LM Studio adaptés (PC : {ram:.0f} Go de RAM, sans carte graphique dédiée) :",
    ]
    for rank, (_, model, reasons) in enumerate(best[:5], 1):
        size = float(model.get("size_bytes") or 0) / GB
        lines.append(
            f"{rank}. lmstudio:{model['key']} — {model.get('params_string')}, {size:.1f} Go ; "
            + ", ".join(reasons)
        )
    if not best:
        lines.append("Aucun modèle installé ne convient ; télécharge-en un dans LM Studio.")
    if heavy:
        lines.append(f"({heavy} modèle(s) trop lourd(s) pour la mémoire de ce PC, écarté(s).)")
    lines.append(
        "Un modèle local est gratuit et privé, mais plus lent et moins fiable que Claude sur "
        "ce PC. Rien n'est changé sans ta demande (set_agent_engine)."
    )
    return "\n".join(lines)


def installed(models: list[dict[str, Any]] | None = None) -> set[str]:
    """The keys of the LM Studio models installed; empty when LM Studio does not answer."""
    try:
        return {str(m.get("key")) for m in (_fetch() if models is None else models)}
    except (OSError, ValueError):
        return set()
