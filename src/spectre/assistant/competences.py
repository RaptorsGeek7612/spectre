"""Spectre's competences: the local skills (`.claude/skills/<name>/SKILL.md`) its brain may read.

The brain runs in its own workspace with only Spectre's tools, so it cannot load Claude Code
skills by itself. Its system prompt lists the competences (name and when to use them) and the
`competence` tool returns one in full, on demand. The development skills of the repository
(conventions, builder, tester, devops, reviewer) are for the people who code Spectre, not for it.

The video skills installed for Claude Code itself (`~/.claude/skills`: HyperFrames, motion
graphics, explainers…) are shared too, each with the agents whose trade it is (`SHARED`); they
are read in place, never copied into the repository.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

DIR_ENV = "SPECTRE_SKILLS_DIR"
DEV_ONLY = frozenset(
    {
        "spectre-conventions",
        "spectre-builder",
        "spectre-tester",
        "spectre-devops",
        "spectre-reviewer",
    }
)
SHARED_ENV = "SPECTRE_SHARED_SKILLS_DIR"
_KYRA = ("chatgpt",)
_VIDEO = ("chatgpt", "charlotte")
# Claude Code's video skills, by the agents who use them (Spectre, the lead, sees them all)
SHARED: dict[str, tuple[str, ...]] = {
    "hyperframes": _KYRA,
    "hyperframes-core": _KYRA,
    "hyperframes-cli": _KYRA,
    "hyperframes-studio": _KYRA,
    "hyperframes-registry": _VIDEO,
    "hyperframes-keyframes": _VIDEO,
    "hyperframes-animation": _VIDEO,
    "hyperframes-creative": _VIDEO,
    "hyperframes-audio": _KYRA,
    "media-use": _KYRA,
    "general-video": ("chatgpt", "celya"),
    "faceless-explainer": ("chatgpt", "celya"),
    "product-launch-video": _KYRA,
    "music-to-video": _KYRA,
    "talking-head-recut": _KYRA,
    "embedded-captions": _VIDEO,
    "slideshow": _VIDEO,
    "motion-graphics": _VIDEO,
    "remotion-to-hyperframes": _KYRA,
    "pr-to-video": ("chatgpt", "sonnet"),
    "figma": ("charlotte",),
    "impeccable": ("chatgpt", "charlotte"),
    # ready-made title and transition blocks
    "canopy-part-title": _VIDEO,
    "code-slice-hero": _VIDEO,
    "cuboid-carousel": _VIDEO,
    "frost-sequence-camera-orbit": _VIDEO,
    "glass-shard-title": _VIDEO,
    "orbit-card": _VIDEO,
    "wireframe-portal-title": _VIDEO,
}
MAX_CHARS = 30_000
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


@dataclass(frozen=True)
class Competence:
    name: str
    description: str
    path: Path
    agents: tuple[str, ...] = ()  # a shared skill's agents (empty = Spectre's own skill)


def skills_dir() -> Path:
    """`SPECTRE_SKILLS_DIR`, else the repository's `.claude/skills` (Spectre runs from it)."""
    raw = os.environ.get(DIR_ENV, "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parents[3] / ".claude" / "skills"


def shared_dir() -> Path:
    """`SPECTRE_SHARED_SKILLS_DIR`, else Claude Code's own `~/.claude/skills`."""
    raw = os.environ.get(SHARED_ENV, "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".claude" / "skills"


def _front_matter(text: str) -> dict[str, str]:
    match = _FRONT.match(text)
    fields: dict[str, str] = {}
    folded = ""  # a `key: >` block scalar gathers the indented lines that follow
    for line in (match.group(1) if match else "").splitlines():
        if folded and line[:1].isspace():
            fields[folded] = f"{fields[folded]} {line.strip()}".strip()
            continue
        folded = ""
        key, sep, value = line.partition(":")
        if sep and not line[:1].isspace():
            value = value.strip()
            if value in (">", "|", ">-", "|-"):
                folded, value = key.strip(), ""
            fields[key.strip()] = value.strip("\"'")
    return fields


def _scan(base: Path) -> list[Competence]:
    found: list[Competence] = []
    for path in sorted(base.glob("*/SKILL.md")) if base.is_dir() else []:
        try:
            fields = _front_matter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        name = fields.get("name") or path.parent.name
        if name in DEV_ONLY or not fields.get("description"):
            continue
        found.append(Competence(name, fields["description"], path))
    return found


def available(root: Path | None = None, *, shared: bool | None = None) -> list[Competence]:
    """The competences Spectre may use, sorted by name (empty when the folder is missing).
    The shared video skills join them by default unless a folder is given explicitly."""
    found = _scan(root or skills_dir())
    if shared if shared is not None else (root is None and not os.environ.get(DIR_ENV)):
        own = {c.name for c in found}
        for c in _scan(shared_dir()):
            if c.name in SHARED and c.name not in own:
                found.append(Competence(c.name, c.description, c.path, SHARED[c.name]))
    return sorted(found, key=lambda c: c.name)


def for_agent(agent: str, root: Path | None = None) -> list[str]:
    """The shared skills of an agent's trade (every one for Spectre)."""
    return [
        c.name for c in available(root) if c.agents and (agent in ("", "opus") or agent in c.agents)
    ]


def read(name: str, root: Path | None = None) -> str:
    """One competence in full (without its front matter); ValueError when unknown."""
    wanted = name.strip().lower()
    for competence in available(root):
        if competence.name.lower() == wanted:
            text = _FRONT.sub("", competence.path.read_text(encoding="utf-8"), count=1).strip()
            if competence.agents:  # its references sit beside it
                text = f"(Dossier de la compétence : {competence.path.parent})\n\n{text}"
            return text[:MAX_CHARS]
    names = ", ".join(c.name for c in available(root)) or "aucune"
    raise ValueError(f"compétence inconnue : {name} (disponibles : {names})")


def catalogue(root: Path | None = None) -> str:
    """The list for the system prompt: one line per competence (a shared one names its
    agents and keeps a short description)."""
    from spectre.assistant.config import agent_name

    lines = []
    for c in available(root):
        if c.agents:
            who = ", ".join(agent_name(a) for a in c.agents)
            lines.append(f"- {c.name} [vidéo, pour {who}] : {c.description[:200]}")
        else:
            lines.append(f"- {c.name} : {c.description}")
    return "\n".join(lines)
