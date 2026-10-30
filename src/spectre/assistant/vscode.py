"""Spectre in VS Code: its MCP server added to the user's VS Code (agent mode, Copilot…).

The other way round from the `vscode` toolkit (the agents open files in the user's editor):
here VS Code's agents call Spectre's tools, through the same gate and audit. The server goes
into the user profile's `mcp.json` (VS Code format: a top-level `servers` object), merged with
what is there; the previous file is kept beside it. Only on the user's click.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

NAME = "spectre"


def user_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Code" / "User"


def entry(root: Path) -> dict[str, Any]:
    return {
        "type": "stdio",
        "command": sys.executable,
        "args": ["-m", "spectre.assistant.mcp_server"],
        "env": {"SPECTRE_ASSISTANT_DIR": str(root)},
    }


def status(folder: Path | None = None) -> dict[str, Any]:
    file = (folder or user_dir()) / "mcp.json"
    servers = _read(file).get("servers", {})
    return {
        "installed": (folder or user_dir()).is_dir(),
        "connected": isinstance(servers, dict) and NAME in servers,
        "file": str(file),
    }


def connect(root: Path, folder: Path | None = None) -> str:
    folder = folder or user_dir()
    if not folder.is_dir():
        raise ValueError("VS Code n'est pas installé pour cet utilisateur (dossier User absent)")
    file = folder / "mcp.json"
    data = _read(file)
    servers = data.get("servers")
    if not isinstance(servers, dict):
        servers = {}
    if file.is_file():
        shutil.copy2(file, folder / f"mcp.json.{datetime.now():%Y%m%d-%H%M%S}.bak")
    servers[NAME] = entry(root)
    data["servers"] = servers
    file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return (
        f"Spectre est branché dans VS Code ({file}). Dans VS Code : vue Chat, mode Agent, "
        "outils « spectre » ; les actions sensibles attendent toujours ton oui ici."
    )


def disconnect(folder: Path | None = None) -> str:
    file = (folder or user_dir()) / "mcp.json"
    data = _read(file)
    servers = data.get("servers")
    if not isinstance(servers, dict) or NAME not in servers:
        return "Spectre n'était pas branché dans VS Code."
    del servers[NAME]
    file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return "Spectre est débranché de VS Code."


def _read(file: Path) -> dict[str, Any]:
    if not file.is_file():
        return {}
    try:
        data = json.loads(file.read_text(encoding="utf-8") or "{}")
    except ValueError as exc:  # comments or a typo: never overwrite the user's file
        raise ValueError(f"{file} n'est pas un JSON lisible : corrige-le d'abord") from exc
    return data if isinstance(data, dict) else {}
