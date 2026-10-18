"""Tools Spectre gives its agents itself: one card (« fiche ») per command-line program.

Spectre never edits Python code for this: a card is data, `outils-agents/<name>.json` in its
own folder (out of reach of the agents' file tools). It says which program to run, with which
arguments, for which agents, and how risky it is. The `toolkit` tool then runs it like the
built-in kits: Spectre builds the command (no shell), the target is a path the agent may read
(or an address, for a remote tool, which waits for approval). Writing a card, deleting one or
installing its program (winget, uv tool) always waits for the user's approval.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from spectre.assistant.actions import MAX_READ_CHARS, ActionContext, ActionError, resolve_path
from spectre.assistant.db import now_iso
from spectre.assistant.governance import Level

FOLDER = "outils-agents"
NAME = re.compile(r"[a-z][a-z0-9_-]{1,30}")
TARGET, OPTIONS = "{cible}", "{options}"
OPTION_TOKEN = re.compile(r"[A-Za-z0-9_.,:=+%@-]+")
# (level, governance category) of each kind of tool
LEVELS = {
    "lecture": (Level.READ, "scan"),  # reads the target, prints a result
    "ecriture": (Level.WRITE, "convert"),  # writes a new file into the workspace
    "distant": (Level.EXTERNAL, "scan_remote"),  # the target is a URL or a host
}
# A card runs a tool, not a script: no shell, no interpreter, nothing that runs other code.
FORBIDDEN = {
    "cmd", "powershell", "pwsh", "bash", "sh", "wsl", "python", "python3", "py", "pythonw",
    "node", "deno", "bun", "wscript", "cscript", "mshta", "rundll32", "regsvr32", "reg",
    "schtasks", "sc", "msiexec", "winget", "uv", "uvx", "pip", "npm", "npx", "choco", "scoop",
    "curl", "wget", "certutil", "bitsadmin", "rm", "del", "format", "diskpart", "bcdedit",
    "takeown", "icacls", "net", "netsh", "shutdown", "git", "docker", "ssh", "scp",
}  # fmt: skip
TIMEOUT_S = 600
MAX_TIMEOUT_S = 3600
INSTALL_TIMEOUT_S = 1800
WINGET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{1,100}")
UV_PACKAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}(==[A-Za-z0-9._+-]{1,30})?")


def folder(root: Path) -> Path:
    return root / FOLDER


def _path(root: Path, name: str) -> Path:
    if not NAME.fullmatch(name):
        raise ActionError(f"nom d'outil invalide : {name} (minuscules, chiffres, - ou _)")
    return folder(root) / f"{name}.json"


def load(root: Path, name: str) -> dict[str, Any] | None:
    try:
        path = _path(root, name)
    except ActionError:
        return None
    if not path.is_file():
        return None
    try:
        card = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return card if isinstance(card, dict) else None


def cards(root: Path) -> list[dict[str, Any]]:
    found = []
    for path in sorted(folder(root).glob("*.json")) if folder(root).is_dir() else []:
        card = load(root, path.stem)
        if card is not None:
            found.append(card)
    return found


def program(card: dict[str, Any]) -> str | None:
    """The executable of a card, if it is installed."""
    from spectre.assistant.toolkit import _bin

    wanted = str(card.get("program", ""))
    if Path(wanted).is_absolute():
        return wanted if Path(wanted).is_file() else None
    return _bin((wanted,))


def allowed(card: dict[str, Any], agent: str) -> bool:
    agents = card.get("agents") or []
    return agent in ("", "opus") or not agents or agent in agents


def risk(card: dict[str, Any]) -> tuple[Level, str]:
    return LEVELS.get(str(card.get("level")), LEVELS["lecture"])


def _agents(raw: str) -> list[str]:
    from spectre.assistant.local_models import resolve_agent

    names = [n.strip() for n in re.split(r"[,;]", raw) if n.strip()]
    if not names:
        raise ActionError("indique les agents qui auront l'outil (ex. Kyra, Syfer), ou « tous »")
    if [n.lower() for n in names] == ["tous"]:
        return []
    return sorted({resolve_agent(n) for n in names})


def _program(raw: str) -> str:
    wanted = raw.strip().strip('"')
    if not wanted:
        raise ActionError("indique le programme (son nom, ex. exiftool, ou son chemin complet)")
    stem = Path(wanted).stem.lower() if Path(wanted).suffix else Path(wanted).name.lower()
    if stem in FORBIDDEN:
        raise ActionError(
            f"{stem} n'est pas un outil : une fiche lance un programme précis, jamais un "
            "interpréteur, un shell ou un installeur"
        )
    if not Path(wanted).is_absolute() and not re.fullmatch(r"[A-Za-z0-9._-]+", wanted):
        raise ActionError(f"nom de programme invalide : {wanted}")
    return wanted


def _args(raw: list[str]) -> list[str]:
    args = [str(a) for a in raw]
    if any(OPTIONS in a and a != OPTIONS for a in args):
        raise ActionError("{options} doit être un argument à lui seul")
    if sum(a.count(TARGET) for a in args) > 1 or args.count(OPTIONS) > 1:
        raise ActionError("{cible} et {options} n'apparaissent qu'une fois chacun")
    return args


def save(
    ctx: ActionContext,
    name: str,
    label: str,
    agents: str,
    program_: str,
    args: list[str],
    level: str = "lecture",
    description: str = "",
    timeout: int = TIMEOUT_S,
    install: str = "",
) -> str:
    from spectre.assistant.toolkit import KITS

    name = name.strip().lower()
    path = _path(ctx.root, name)
    if name in KITS:
        raise ActionError(f"{name} est déjà un outil intégré de la boîte à outils")
    if level not in LEVELS:
        raise ActionError(f"niveau inconnu : {level} (au choix : {', '.join(LEVELS)})")
    method, package = _install(install) if install.strip() else ("", "")
    previous = load(ctx.root, name)
    card = {
        "name": name,
        "label": (label.strip() or name)[:80],
        "description": description.strip()[:400],
        "agents": _agents(agents),
        "program": _program(program_),
        "args": _args(args),
        "level": level,
        "timeout": max(10, min(int(timeout), MAX_TIMEOUT_S)),
        "install": {"method": method, "package": package} if method else {},
        "created": (previous or {}).get("created", now_iso()),
        "updated": now_iso(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    state = "installé" if program(card) else "pas encore installé (agent_tool_install)"
    who = ", ".join(_names(card["agents"])) or "tous les agents"
    verb = "mise à jour" if previous else "créée"
    return f"fiche « {name} » {verb} pour {who} ; programme {card['program']} {state}"


def delete(ctx: ActionContext, name: str) -> str:
    path = _path(ctx.root, name.strip().lower())
    if not path.is_file():
        raise ActionError(f"aucune fiche d'outil nommée {name}")
    path.unlink()
    return f"fiche « {name} » supprimée (le programme reste installé sur le PC)"


def _install(raw: str) -> tuple[str, str]:
    method, _, package = raw.strip().partition(":")
    method, package = method.strip().lower(), package.strip()
    if method == "winget" and WINGET_ID.fullmatch(package):
        return method, package
    if method == "uv" and UV_PACKAGE.fullmatch(package):
        return method, package
    raise ActionError("installation : winget:<Id.Du.Paquet> ou uv:<paquet> (ex. uv:ruff)")


def install(ctx: ActionContext, name: str, source: str = "") -> str:
    """Install the program of a card (winget or uv tool), after the user's approval."""
    card = load(ctx.root, name.strip().lower())
    if card is None:
        raise ActionError(f"aucune fiche d'outil nommée {name} (crée-la d'abord)")
    if source.strip():
        method, package = _install(source)
    elif card.get("install"):
        method, package = card["install"]["method"], card["install"]["package"]
    else:
        raise ActionError("précise la source : winget:<Id.Du.Paquet> ou uv:<paquet>")
    exe = shutil.which(method) or method
    command = (
        [
            exe,
            "install",
            "--id",
            package,
            "--exact",
            "--silent",
            "--disable-interactivity",
            "--accept-source-agreements",
            "--accept-package-agreements",
        ]  # fmt: skip
        if method == "winget"
        else [exe, "tool", "install", package]
    )
    runner = ctx.runner or subprocess.run
    try:
        proc = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=INSTALL_TIMEOUT_S,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise ActionError(f"{method} est introuvable sur ce PC") from exc
    except subprocess.TimeoutExpired as exc:
        raise ActionError(
            f"installation trop longue (plus de {INSTALL_TIMEOUT_S // 60} min)"
        ) from exc
    tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-600:]
    if proc.returncode != 0:
        raise ActionError(f"installation échouée ({method} code {proc.returncode}) : {tail}")
    card["install"] = {"method": method, "package": package}
    card["updated"] = now_iso()
    _path(ctx.root, card["name"]).write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    found = "trouvé" if program(card) else "pas encore visible (relance peut-être Spectre)"
    return f"{package} installé via {method} ; programme {card['program']} {found}"


def _folders() -> list[tuple[str, Path]]:
    home = Path.home()
    return [
        ("Apps", home / "Apps"),
        ("Apps/bin", home / "Apps" / "bin"),
        ("uv tools", home / "AppData" / "Roaming" / "uv" / "tools"),
        ("WinGet", home / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links"),
        ("Program Files", Path("C:/Program Files")),
        ("Program Files (x86)", Path("C:/Program Files (x86)")),
        ("Programs", home / "AppData" / "Local" / "Programs"),
    ]


def installed(ctx: ActionContext, search: str = "") -> str:
    """What is installed on this PC, for Spectre to choose the programs to give its agents:
    the folders where the user installs software, and winget's list."""
    wanted = search.strip().lower()
    lines = []
    for label, base in _folders():
        if not base.is_dir():
            continue
        try:
            names = sorted(p.name for p in base.iterdir() if not p.name.startswith("."))
        except OSError:
            continue
        names = [n for n in names if wanted in n.lower()]
        if names:
            lines.append(f"{label} ({base}) : {', '.join(names)[:3000]}")
    runner = ctx.runner or subprocess.run
    winget = shutil.which("winget")
    if winget:
        try:
            proc = runner(
                [winget, "list", "--disable-interactivity", "--accept-source-agreements"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            rows = [r.rstrip() for r in (proc.stdout or "").splitlines() if r.strip()]
            rows = [r for r in rows if not wanted or wanted in r.lower()]
            if rows:
                lines.append("winget list :\n" + "\n".join(rows)[: MAX_READ_CHARS // 2])
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not lines:
        return f"rien trouvé{f' pour « {search} »' if wanted else ''}"
    return (
        "Logiciels installés (pour en faire un outil d'agent : agent_tool_save avec le nom du "
        "programme ou son chemin complet .exe) :\n" + "\n".join(lines)
    )[:MAX_READ_CHARS]


def _names(keys: list[str]) -> list[str]:
    from spectre.assistant.config import AGENT_NAMES

    return [AGENT_NAMES.get(k, k) for k in keys]


def listing(ctx: ActionContext) -> str:
    """The cards this agent may use (all of them, for Spectre)."""
    mine = [c for c in cards(ctx.root) if allowed(c, ctx.agent)]
    if not mine:
        return "aucun outil ajouté par Spectre pour l'instant"
    lines = []
    for c in mine:
        state = "installé" if program(c) else "non installé"
        who = ", ".join(_names(c.get("agents") or [])) or "tous"
        usage = " ".join(c.get("args") or [])
        lines.append(
            f"- {c['name']} — {c.get('label', '')} [{c.get('level')}, {state}, pour {who}] : "
            f"{c.get('description') or '…'} (appel : {c['program']} {usage})"
        )
    return "Outils ajoutés par Spectre (outil toolkit, name = le nom) :\n" + "\n".join(lines)


def describe(root: Path) -> list[dict[str, Any]]:
    """Like `toolkit.describe`, for the Agents view."""
    return [
        {
            "name": c["name"],
            "label": c.get("label", c["name"]),
            "agents": list(c.get("agents") or []),
            "category": risk(c)[1],
            "installed": program(c) is not None,
            "added": True,
        }
        for c in cards(root)
    ]


def _target(ctx: ActionContext, card: dict[str, Any], target: str) -> str:
    raw = target.strip()
    if card.get("level") == "distant":
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/?&=%#@+~-]{0,300}", raw):
            raise ActionError(f"adresse invalide : {raw}")
        return raw
    return str(resolve_path(ctx, raw))


def _options(options: str) -> list[str]:
    try:
        tokens = shlex.split(options, posix=True) if options.strip() else []
    except ValueError as exc:
        raise ActionError(f"options illisibles : {exc}") from exc
    for token in tokens:
        if not OPTION_TOKEN.fullmatch(token) or ".." in token or re.match(r"[A-Za-z]:", token):
            raise ActionError(
                f"option refusée : {token} (pas de chemin dans les options : passe le fichier "
                "en cible)"
            )
    return tokens


def command(
    ctx: ActionContext, card: dict[str, Any], exe: str, target: str, options: str
) -> list[str]:
    args = card.get("args") or []
    needs_target = any(TARGET in a for a in args)
    if needs_target and not target.strip():
        raise ActionError("précise la cible (un fichier, un dossier ou une adresse)")
    resolved = _target(ctx, card, target) if needs_target else ""
    extra = _options(options)
    argv = [exe]
    for arg in args:
        if arg == OPTIONS:
            argv += extra
        else:
            argv.append(arg.replace(TARGET, resolved))
    return argv


def run(ctx: ActionContext, name: str, target: str = "", options: str = "") -> str:
    card = load(ctx.root, name)
    if card is None:
        raise ActionError(f"outil inconnu : {name}")
    if not allowed(card, ctx.agent):
        raise ActionError(f"{card.get('label', name)} n'est pas un outil de ton domaine")
    exe = program(card)
    if exe is None:
        raise ActionError(f"{card.get('label', name)} n'est pas installé sur ce PC")
    argv = command(ctx, card, exe, target, options)
    timeout = float(card.get("timeout") or TIMEOUT_S)
    runner = ctx.runner or subprocess.run
    try:
        proc = runner(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            cwd=str(ctx.workspace),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise ActionError(f"{card.get('label', name)} est introuvable : {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ActionError(f"{card.get('label', name)} a dépassé {int(timeout)} s") from exc
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode not in (0, 1) and not out:
        raise ActionError(
            f"{card.get('label', name)} (code {proc.returncode}) : {(err or 'échec')[:400]}"
        )
    body = out or err or "(aucune sortie : rien à signaler)"
    if err and out:
        body += f"\n[détails] {err[:400]}"
    return body[:MAX_READ_CHARS]
