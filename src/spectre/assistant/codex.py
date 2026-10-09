"""ChatGPT as a mission execution agent, through the local Codex CLI (`codex exec`).

Like the brain with `claude -p`, it runs on the user's ChatGPT subscription (Codex logged in with
"Sign in with ChatGPT"), so API-key variables are removed from the child environment. The agent
gets Spectre's own tools over MCP (so every action still goes through the governance gate) and
live web search; its shell runs in Codex's read-only sandbox, so it changes nothing on its own.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from spectre.assistant.brain import Reply, Runner
from spectre.assistant.config import AssistantConfig
from spectre.assistant.mcp_server import SERVER_NAME

STRIPPED_ENV = ("OPENAI_API_KEY", "CODEX_API_KEY")
NATIVE = Path("node_modules", "@openai", "codex", "node_modules", "@openai", "codex-win32-x64")


def find_codex(name: str) -> str:
    """The Codex executable. On Windows, npm installs a `.cmd` shim that would hand our
    arguments to cmd.exe, which mangles quotes; use the native `codex.exe` it wraps instead."""
    found = shutil.which(name) or name
    if Path(found).suffix.lower() in (".cmd", ".ps1", ""):
        for exe in sorted((Path(found).parent / NATIVE).glob("vendor/*/bin/codex.exe")):
            return str(exe)
    return found


def toml(value: str) -> str:
    """A TOML basic string (JSON string escapes are valid TOML)."""
    return json.dumps(value, ensure_ascii=False)


class CodexCLI:
    """Runs `codex exec` with Spectre's settings and returns the agent's last message."""

    def __init__(
        self, config: AssistantConfig, root: Path, runner: Runner = subprocess.run
    ) -> None:
        self.config = config
        self.root = root
        self.runner = runner
        self.workspace = root / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)

    def env(self) -> dict[str, str]:
        return {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}

    def command(self, *, system: str, output: Path, with_tools: bool) -> list[str]:
        cmd = [
            find_codex(self.config.codex_bin),
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",  # no personal plugins or hooks; the login is still used
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "-C",
            str(self.workspace),
            "-o",
            str(output),
            "-c",
            'approval_policy="never"',
            "-c",
            f"developer_instructions={toml(system)}",
            "-c",
            f'web_search="{"live" if with_tools else "disabled"}"',
        ]
        if self.config.chatgpt_model:
            cmd += ["-m", self.config.chatgpt_model]
        if with_tools:
            server = f"mcp_servers.{SERVER_NAME}"
            cmd += [
                "-c",
                f"{server}.command={toml(sys.executable)}",
                "-c",
                f'{server}.args=["-m", "spectre.assistant.mcp_server"]',
                "-c",
                f"{server}.env={{SPECTRE_ASSISTANT_DIR = {toml(str(self.root))}}}",
                "-c",
                f'{server}.default_tools_approval_mode="approve"',
            ]
        return [*cmd, "-"]  # the prompt comes on stdin

    def ask(
        self, prompt: str, *, system: str, model: str | None = None, with_tools: bool = True
    ) -> Reply:
        """One stateless run; `model` is ignored (the ChatGPT model comes from the settings)."""
        with tempfile.TemporaryDirectory(prefix="spectre-codex-") as tmp:
            output = Path(tmp) / "last.txt"
            try:
                proc = self.runner(
                    self.command(system=system, output=output, with_tools=with_tools),
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    cwd=self.workspace,
                    env=self.env(),
                    timeout=self.config.brain_timeout_s,
                    check=False,
                )
            except FileNotFoundError:
                return Reply("Je ne trouve pas Codex (commande « codex ») sur ce PC.", "", True)
            except subprocess.TimeoutExpired:
                return Reply("ChatGPT n'a pas répondu à temps.", "", True)
            text = output.read_text(encoding="utf-8").strip() if output.exists() else ""
        if proc.returncode == 0 and text:
            return Reply(text, "", False)
        detail = [ln for ln in (proc.stderr or proc.stdout or "").splitlines() if ln.strip()]
        return Reply(
            f"ChatGPT a échoué : {detail[-1][:300] if detail else 'réponse vide'}", "", True
        )
