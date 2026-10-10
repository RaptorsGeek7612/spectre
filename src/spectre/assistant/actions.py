"""What Spectre can do on the computer. Pure functions over an `ActionContext`.

File operations are confined to the allowed roots, journaled in the `undo` table and
reversible; "delete" moves to Spectre's own trash. Opening apps and pages is best effort.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from spectre.assistant import winapi
from spectre.assistant.db import Database, now_iso

MAX_READ_CHARS = 20_000
MAX_LIST = 200
# Files that agent programs (Claude Code, Codex, Vibe) read from their folder as instructions.
AGENT_FILES = frozenset({"claude.md", "claude.local.md", "agents.md"})


class ActionError(Exception):
    """An action could not run; the message is shown to the user and to the brain."""


@dataclass
class ActionContext:
    db: Database
    root: Path  # assistant data dir (trash lives here)
    allowed_roots: list[Path] = field(default_factory=list)
    launcher: Any = None  # injectable for tests: callable(target) -> None

    @property
    def trash(self) -> Path:
        return self.root / "trash"

    @property
    def workspace(self) -> Path:
        """Where mission agents work (their current folder): the only writable inner folder."""
        return self.root / "workspace"


# ---- paths --------------------------------------------------------------------------------


def resolve_path(ctx: ActionContext, raw: str) -> Path:
    """Expand `~`, make absolute, and require it to live under an allowed root."""
    if not raw or not raw.strip():
        raise ActionError("chemin vide")
    path = Path(os.path.expandvars(raw.strip())).expanduser()
    if not path.is_absolute():
        path = (ctx.allowed_roots[0] if ctx.allowed_roots else Path.home()) / path
    path = path.resolve()
    workspace = ctx.workspace.resolve()
    if path == workspace or workspace in path.parents:
        # The agents' working folder: open to them, except what the agent programs read as
        # their own settings or instructions (an agent could otherwise grant itself rights).
        inside = path.relative_to(workspace).parts
        if any(part.startswith(".") for part in inside) or path.name.lower() in AGENT_FILES:
            raise ActionError(f"ce fichier règle le comportement des agents : {path.name}")
        return path
    roots = [r.resolve() for r in ctx.allowed_roots]
    if not any(path == r or r in path.parents for r in roots):
        raise ActionError(f"accès refusé hors des dossiers autorisés : {path}")
    if ctx.root.resolve() in path.parents or path == ctx.root.resolve():
        raise ActionError("les fichiers internes de Spectre ne sont pas modifiables par cette voie")
    return path


def _journal(ctx: ActionContext, action: str, **data: Any) -> int:
    return ctx.db.execute(
        "INSERT INTO undo(ts, action, data) VALUES(?, ?, ?)",
        (now_iso(), action, json.dumps(data, ensure_ascii=False)),
    )


# ---- read -----------------------------------------------------------------------------------


def current_time(ctx: ActionContext) -> str:
    stamp = datetime.now().astimezone()
    return stamp.strftime("%A %d %B %Y, %H:%M (%Z)")


def list_dir(ctx: ActionContext, path: str) -> str:
    folder = resolve_path(ctx, path)
    if not folder.is_dir():
        raise ActionError(f"pas un dossier : {folder}")
    entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:MAX_LIST]
    lines = [f"{'[dossier]' if p.is_dir() else f'{p.stat().st_size} o'}  {p.name}" for p in entries]
    return f"{folder}\n" + ("\n".join(lines) if lines else "(vide)")


def read_file(ctx: ActionContext, path: str) -> str:
    file = resolve_path(ctx, path)
    if not file.is_file():
        raise ActionError(f"fichier introuvable : {file}")
    text = file.read_text(encoding="utf-8", errors="replace")
    suffix = "\n… (tronqué)" if len(text) > MAX_READ_CHARS else ""
    return text[:MAX_READ_CHARS] + suffix


def search_files(ctx: ActionContext, folder: str, pattern: str) -> str:
    base = resolve_path(ctx, folder)
    if not base.is_dir():
        raise ActionError(f"pas un dossier : {base}")
    pattern = pattern.strip() or "*"
    if not any(c in pattern for c in "*?["):
        pattern = f"*{pattern}*"
    hits: list[str] = []
    for current, dirs, files in os.walk(base):
        dirs[:] = [
            d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__")
        ]
        for name in files:
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                hits.append(str(Path(current) / name))
                if len(hits) >= MAX_LIST:
                    return "\n".join(hits) + "\n… (limite atteinte)"
    return "\n".join(hits) if hits else "aucun fichier trouvé"


def system_info(ctx: ActionContext) -> str:
    total, used, free = shutil.disk_usage(Path.home().anchor or "/")
    return (
        f"Système : {sys.platform}, {os.cpu_count()} cœurs logiques, "
        f"disque {free // 2**30} Go libres sur {total // 2**30} Go"
    )


# ---- open -----------------------------------------------------------------------------------


def _launch(ctx: ActionContext, target: str) -> None:
    if ctx.launcher is not None:
        ctx.launcher(target)
        return
    if sys.platform == "win32":  # pragma: no cover - platform specific
        os.startfile(target)
    elif sys.platform == "darwin":  # pragma: no cover
        subprocess.Popen(["open", target])
    else:  # pragma: no cover
        subprocess.Popen(["xdg-open", target])


def open_url(ctx: ActionContext, url: str, screen: int | None = None) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ActionError("adresse web invalide (http ou https attendu)")
    _open_on_screen(ctx, url.strip(), screen, use_browser=True)
    return f"page ouverte : {url.strip()}"


def _start_menu_entries() -> list[Path]:
    folders = [
        Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
        / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft/Windows/Start Menu/Programs",
    ]
    entries: list[Path] = []
    for folder in folders:
        if folder.is_dir():
            entries += [
                p for p in folder.rglob("*") if p.suffix.lower() in (".lnk", ".url", ".appref-ms")
            ]
    return entries


def find_app(name: str, entries: list[Path] | None = None) -> Path | None:
    """Best Start-menu match for an app name (exact, then prefix, then contains)."""
    wanted = name.strip().lower()
    candidates = entries if entries is not None else _start_menu_entries()
    for test in (
        lambda s: s == wanted,
        lambda s: s.startswith(wanted),
        lambda s: wanted in s,
    ):
        hits = [p for p in candidates if test(p.stem.lower()) and "uninstall" not in p.stem.lower()]
        if hits:
            return min(hits, key=lambda p: len(p.stem))
    return None


def open_app(ctx: ActionContext, name: str, screen: int | None = None) -> str:
    if not name.strip():
        raise ActionError("nom d'application vide")
    match = find_app(name)
    target = str(match) if match else name.strip()
    _open_on_screen(ctx, target, screen, use_browser=False)
    return f"application lancée : {match.stem if match else name.strip()}"


def _open_on_screen(
    ctx: ActionContext, target: str, screen: int | None, *, use_browser: bool
) -> None:
    before = winapi.visible_windows() if screen is not None and ctx.launcher is None else set()
    if use_browser and ctx.launcher is None:  # pragma: no cover - opens a real browser
        webbrowser.open(target)
    else:
        _launch(ctx, target)
    if screen is not None and ctx.launcher is None:  # pragma: no cover - real desktop only
        threading.Thread(target=winapi.move_new_window, args=(before, screen), daemon=True).start()


def list_screens(ctx: ActionContext) -> str:
    screens = winapi.monitors()
    if not screens:
        return "un seul écran détecté (ou plateforme non prise en charge)"
    return "\n".join(
        f"écran {m.index}{' (principal)' if m.primary else ''} : {m.width}×{m.height} à x={m.left}"
        for m in screens
    )


# ---- write (journaled, reversible) -----------------------------------------------------------


def write_file(ctx: ActionContext, path: str, content: str) -> str:
    file = resolve_path(ctx, path)
    file.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if file.exists():
        ctx.trash.mkdir(parents=True, exist_ok=True)
        backup = ctx.trash / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{file.name}"
        shutil.copy2(file, backup)
    file.write_text(content, encoding="utf-8")
    _journal(ctx, "write", path=str(file), backup=str(backup) if backup else None)
    return f"fichier écrit : {file} ({len(content)} caractères)"


def move_file(ctx: ActionContext, source: str, destination: str) -> str:
    src, dst = resolve_path(ctx, source), resolve_path(ctx, destination)
    if not src.exists():
        raise ActionError(f"introuvable : {src}")
    if dst.is_dir():
        dst = dst / src.name
    if dst.exists():
        raise ActionError(f"la destination existe déjà : {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    _journal(ctx, "move", src=str(src), dst=str(dst))
    return f"déplacé : {src} → {dst}"


def delete_file(ctx: ActionContext, path: str) -> str:
    target = resolve_path(ctx, path)
    if not target.exists():
        raise ActionError(f"introuvable : {target}")
    ctx.trash.mkdir(parents=True, exist_ok=True)
    kept = ctx.trash / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{target.name}"
    shutil.move(str(target), str(kept))
    _journal(ctx, "delete", path=str(target), kept=str(kept))
    return f"mis à la corbeille de Spectre : {target} (annulable)"


def undo_last(ctx: ActionContext, count: int = 1) -> str:
    """Revert the last `count` journaled file actions, newest first."""
    rows = ctx.db.all(
        "SELECT * FROM undo WHERE undone = 0 ORDER BY id DESC LIMIT ?", (max(1, count),)
    )
    if not rows:
        return "rien à annuler"
    done = []
    for row in rows:
        data = json.loads(row["data"])
        if row["action"] == "move":
            shutil.move(data["dst"], data["src"])
            done.append(f"remis en place : {data['src']}")
        elif row["action"] == "delete":
            shutil.move(data["kept"], data["path"])
            done.append(f"restauré : {data['path']}")
        elif row["action"] == "write":
            if data.get("backup"):
                shutil.copy2(data["backup"], data["path"])
                done.append(f"ancienne version rétablie : {data['path']}")
            else:
                Path(data["path"]).unlink(missing_ok=True)
                done.append(f"fichier créé supprimé : {data['path']}")
        ctx.db.execute("UPDATE undo SET undone = 1 WHERE id = ?", (row["id"],))
    return "\n".join(done)


# ---- reminders ------------------------------------------------------------------------------


def set_reminder(ctx: ActionContext, when: str, text: str) -> str:
    try:
        due = datetime.fromisoformat(when.strip())
    except ValueError:
        raise ActionError("date invalide : utilise le format ISO, ex. 2026-10-09T08:30") from None
    if due.tzinfo is None:
        due = due.astimezone()
    if not text.strip():
        raise ActionError("rappel vide")
    rid = ctx.db.execute(
        "INSERT INTO reminders(ts, due_at, text) VALUES(?, ?, ?)",
        (now_iso(), due.isoformat(timespec="minutes"), text.strip()),
    )
    return f"rappel #{rid} programmé pour {due:%d/%m %H:%M} : {text.strip()}"


def list_reminders(ctx: ActionContext) -> str:
    rows = ctx.db.all("SELECT * FROM reminders WHERE done = 0 ORDER BY due_at LIMIT 50")
    if not rows:
        return "aucun rappel en attente"
    return "\n".join(f"#{r['id']} {r['due_at']} — {r['text']}" for r in rows)
