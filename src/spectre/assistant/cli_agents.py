"""Octavya, Clarke and Simon: mission execution agents in the Cursor, Antigravity and Kimi Code
CLIs, on the user's own accounts (like Kyra with Codex and Syfer with Vibe).

Each runs in its own folder of the assistant directory (`agents/<key>`), which Spectre rewrites
on every run: Spectre's tools over MCP (so every action still goes through the governance gate)
and the tool's own shell and file writes turned off where the CLI allows it. None of these CLIs
takes a system prompt on the command line, so Spectre's instructions open the prompt.

The model lists for the interface come from the tools themselves: `cursor-agent --list-models`,
`agy models`, Codex's `models_cache.json` and Vibe's built-in aliases.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from spectre.assistant.brain import Reply, Runner
from spectre.assistant.config import AssistantConfig
from spectre.assistant.mcp_server import SERVER_NAME

MODELS_TTL_S = 600.0
MAX_ARG = 24000  # Windows caps a command line near 32 000 characters

QUOTA = re.compile(r"usage limit|quota|RESOURCE_EXHAUSTED|rate.?limit|429", re.IGNORECASE)
LOGIN = re.compile(r"not (logged|authenticated)|login required|unauthori[sz]ed|401", re.IGNORECASE)


def mcp_servers(root: Path) -> dict[str, Any]:
    """Spectre's tool server for a CLI's `mcpServers` file (with the agent at work)."""
    from spectre.assistant import runctx

    return {
        SERVER_NAME: {
            "command": sys.executable,
            "args": ["-m", "spectre.assistant.mcp_server"],
            "env": {"SPECTRE_ASSISTANT_DIR": str(root), **runctx.env()},
        }
    }


def with_system(system: str, prompt: str) -> str:
    return f"Tes consignes (à suivre en priorité) :\n{system}\n\n---\n\nDemande :\n{prompt}"


def explain(tool: str, text: str) -> str:
    """A failure in words the user can act on."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    last = lines[-1][:300] if lines else "réponse vide"
    if QUOTA.search(text):
        return f"{tool} : la limite d'utilisation de ton compte est atteinte ({last})"
    if LOGIN.search(text):
        return f"{tool} : connecte-toi d'abord dans l'outil ({last})"
    return f"{tool} a échoué : {last}"


class _CLIAgent:
    """What the three CLIs share: a workspace, a run, the answer or the reason it failed."""

    key = ""
    tool = ""

    def __init__(
        self, config: AssistantConfig, root: Path, runner: Runner = subprocess.run
    ) -> None:
        self.config = config
        self.root = root
        self.runner = runner
        self.workspace = root / "agents" / self.key
        self.workspace.mkdir(parents=True, exist_ok=True)

    def write_files(self) -> None:
        raise NotImplementedError

    def command(self, prompt: str, *, with_tools: bool) -> tuple[list[str], str | None]:
        """The command line and what goes to stdin (None: the prompt is an argument)."""
        raise NotImplementedError

    def env(self) -> dict[str, str]:
        return {**os.environ, "PYTHONIOENCODING": "utf-8"}

    def ask(
        self, prompt: str, *, system: str, model: str | None = None, with_tools: bool = True
    ) -> Reply:
        """One stateless run; `model` is ignored (the model comes from the settings)."""
        self.write_files()
        cmd, stdin = self.command(with_system(system, prompt), with_tools=with_tools)
        try:
            proc = self.runner(
                cmd,
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.workspace,
                env=self.env(),
                timeout=self.config.brain_timeout_s,
                check=False,
            )
        except FileNotFoundError:
            return Reply(f"Je ne trouve pas {self.tool} sur ce PC.", "", True)
        except subprocess.TimeoutExpired:
            return Reply(f"{self.tool} n'a pas répondu à temps.", "", True)
        text = (proc.stdout or "").strip()
        errors = proc.stderr or ""
        if proc.returncode == 0 and text and not QUOTA.search(text[:400]):
            return Reply(text, "", False)
        return Reply(explain(self.tool, f"{errors}\n{text}"), "", True)


# ---- Cursor (Octavya) --------------------------------------------------------------------------


def find_cursor(name: str) -> list[str]:
    """How to start the Cursor CLI. Its Windows launcher goes through cmd.exe and PowerShell,
    which mangle quotes; run the Node it bundles on the newest version instead."""
    found = shutil.which(name) or name
    folder = Path(found).parent / "versions"
    if Path(found).suffix.lower() in (".cmd", ".ps1", "") and folder.is_dir():
        for version in sorted(folder.iterdir(), key=lambda p: p.name, reverse=True):
            node, script = version / "node.exe", version / "index.js"
            if node.is_file() and script.is_file():
                return [str(node), str(script)]
    return [found]


class CursorCLI(_CLIAgent):
    """Runs `cursor-agent -p` in its folder, with only Spectre's tools."""

    key = "cursor"
    tool = "Cursor"

    def write_files(self) -> None:
        folder = self.workspace / ".cursor"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "mcp.json").write_text(
            json.dumps({"mcpServers": mcp_servers(self.root)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        permissions = {  # deny rules win over --force: no shell, no direct writes
            "allow": [f"Mcp({SERVER_NAME}:*)", "Read(**)"],
            "deny": ["Shell(*)", "Write(**)"],
        }
        (folder / "cli.json").write_text(
            json.dumps({"permissions": permissions}, indent=2), encoding="utf-8"
        )

    def command(self, prompt: str, *, with_tools: bool) -> tuple[list[str], str | None]:
        cmd = [
            *find_cursor(self.config.cursor_bin),
            "-p",
            "--output-format",
            "text",
            "--trust",
            "--workspace",
            str(self.workspace),
        ]
        if with_tools:
            cmd += ["--approve-mcps", "--force"]
        else:
            cmd += ["--mode", "ask"]
        if self.config.cursor_model:
            cmd += ["--model", self.config.cursor_model]
        return cmd, prompt  # the prompt comes on stdin

    def env(self) -> dict[str, str]:
        return {**super().env(), "CURSOR_INVOKED_AS": "cursor-agent"}


# ---- Antigravity (Clarke) ----------------------------------------------------------------------


def find_agy(name: str) -> str:
    """The Antigravity CLI (`agy`), also where its installer puts it on Windows."""
    found = shutil.which(name)
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
    return str(local) if local.is_file() else name


class AntigravityCLI(_CLIAgent):
    """Runs `agy -p` in its folder, sandboxed, with Spectre's tools over MCP."""

    key = "antigravity"
    tool = "Antigravity"

    def write_files(self) -> None:
        folder = self.workspace / ".agents"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "mcp_config.json").write_text(
            json.dumps({"mcpServers": mcp_servers(self.root)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def command(self, prompt: str, *, with_tools: bool) -> tuple[list[str], str | None]:
        cmd = [find_agy(self.config.antigravity_bin), "--output-format", "text", "--sandbox"]
        if not with_tools:
            cmd += ["--mode", "plan"]
        if self.config.antigravity_model:
            cmd += ["--model", self.config.antigravity_model]
        return [*cmd, "-p", prompt[-MAX_ARG:]], None


# ---- Kimi Code (Simon) -------------------------------------------------------------------------


def find_kimi(name: str) -> list[str]:
    """How to start Kimi Code. npm's Windows launcher (`kimi.cmd`) goes through cmd.exe, which
    mangles quotes in the prompt; run its script with Node instead."""
    found = shutil.which(name) or name
    script = (
        Path(found).parent / "node_modules" / "@moonshot-ai" / "kimi-code" / "dist" / "main.mjs"
    )
    node = shutil.which("node")
    if Path(found).suffix.lower() in (".cmd", ".ps1", "") and script.is_file() and node:
        return [node, str(script)]
    return [found]


class KimiCLI(_CLIAgent):
    """Runs `kimi -p` in its folder: Spectre's tools over MCP, its shell and writes denied."""

    key = "kimi"
    tool = "Kimi Code"

    def write_files(self) -> None:
        folder = self.workspace / ".kimi-code"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "mcp.json").write_text(
            json.dumps({"mcpServers": mcp_servers(self.root)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rules = "".join(
            f'[[permission.rules]]\ndecision = "deny"\npattern = "{tool}"\n\n'
            for tool in ("Bash", "Write", "Edit")
        )
        (folder / "local.toml").write_text(rules, encoding="utf-8")

    def command(self, prompt: str, *, with_tools: bool) -> tuple[list[str], str | None]:
        cmd = find_kimi(self.config.kimi_bin)
        if self.config.kimi_model:
            cmd += ["-m", self.config.kimi_model]
        return [*cmd, "-p", prompt[-MAX_ARG:]], None

    def env(self) -> dict[str, str]:
        return {
            **super().env(),
            "KIMI_CODE_TRUST_WORKSPACE": "1",  # its own folder: the MCP file is Spectre's
            "KIMI_DISABLE_TELEMETRY": "1",
            "KIMI_CODE_NO_AUTO_UPDATE": "1",
        }


# ---- the models each tool offers ---------------------------------------------------------------

_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_lock = threading.Lock()


def _run(cmd: list[str], env: dict[str, str] | None = None) -> str:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed command lines
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout or ""


def parse_cursor_models(text: str) -> list[dict[str, str]]:
    found = []
    for line in text.splitlines():
        match = re.match(r"^\s*([\w.\-\[\]=,]+) - (.+?)\s*$", line)
        if match:
            label = match.group(2).replace("​", "").replace("(current, default)", "").strip()
            found.append({"id": match.group(1), "label": label})
    return found


def parse_agy_models(text: str) -> list[dict[str, str]]:
    found = []
    for line in text.splitlines():
        model, tab, label = line.partition("\t")
        if tab and model.strip():
            found.append({"id": model.strip(), "label": label.strip() or model.strip()})
    return found


def codex_models(home: Path | None = None) -> list[dict[str, str]]:
    path = (home or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")) / (
        "models_cache.json"
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    models = data.get("models", []) if isinstance(data, dict) else []
    return [
        {"id": str(m["slug"]), "label": str(m.get("display_name") or m["slug"])}
        for m in models
        if isinstance(m, dict) and m.get("slug") and m.get("visibility", "list") == "list"
    ]


VIBE_MODELS = (
    "from vibe.core.config import DEFAULT_MODELS as m; "
    "print('\\n'.join(f'{x.alias}\\t{x.name}' for x in m))"
)


def models(key: str, config: AssistantConfig) -> list[dict[str, str]]:
    """The models an agent's own tool offers (cached ten minutes); [] when it cannot say."""
    with _lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < MODELS_TTL_S:
            return cached[1]
    found: list[dict[str, str]] = []
    if key == "cursor":
        env = {**os.environ, "CURSOR_INVOKED_AS": "cursor-agent"}
        found = parse_cursor_models(_run([*find_cursor(config.cursor_bin), "--list-models"], env))
    elif key == "antigravity":
        found = parse_agy_models(_run([find_agy(config.antigravity_bin), "models"]))
    elif key == "chatgpt":
        found = codex_models()
    elif key == "kimi":  # Kimi Code has no listing command: the aliases its /login provides
        from spectre.config import KIMI_MODELS

        found = [{"id": alias, "label": label} for alias, label in KIMI_MODELS]
    elif key == "mistral":
        from spectre.assistant.mistral import vibe_command

        launcher = vibe_command(config.vibe_bin)
        if len(launcher) == 3:  # the Python interpreter behind vibe.exe
            found = parse_agy_models(_run([launcher[0], "-c", VIBE_MODELS]))
    with _lock:
        _cache[key] = (time.monotonic(), found)
    return found
