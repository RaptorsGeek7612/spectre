"""Spectre's competences: the local skills (`.claude/skills/<name>/SKILL.md`) its brain may read.

The brain runs in its own workspace with only Spectre's tools, so it cannot load Claude Code
skills by itself. Its system prompt lists the competences (name and when to use them) and the
`competence` tool returns one in full, on demand. The development skills of the repository
(conventions, builder, tester, devops, reviewer) are for the people who code Spectre, not for it.
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
MAX_CHARS = 30_000
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


@dataclass(frozen=True)
class Competence:
    name: str
    description: str
    path: Path


def skills_dir() -> Path:
    """`SPECTRE_SKILLS_DIR`, else the repository's `.claude/skills` (Spectre runs from it)."""
    raw = os.environ.get(DIR_ENV, "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parents[3] / ".claude" / "skills"


def _front_matter(text: str) -> dict[str, str]:
    match = _FRONT.match(text)
    fields: dict[str, str] = {}
    for line in (match.group(1) if match else "").splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def available(root: Path | None = None) -> list[Competence]:
    """The competences Spectre may use, sorted by name (empty when the folder is missing)."""
    base = root or skills_dir()
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


def read(name: str, root: Path | None = None) -> str:
    """One competence in full (without its front matter); ValueError when unknown."""
    wanted = name.strip().lower()
    for competence in available(root):
        if competence.name.lower() == wanted:
            text = competence.path.read_text(encoding="utf-8")
            return _FRONT.sub("", text, count=1).strip()[:MAX_CHARS]
    names = ", ".join(c.name for c in available(root)) or "aucune"
    raise ValueError(f"compétence inconnue : {name} (disponibles : {names})")


def catalogue(root: Path | None = None) -> str:
    """The list for the system prompt: one line per competence."""
    return "\n".join(f"- {c.name} : {c.description}" for c in available(root))
