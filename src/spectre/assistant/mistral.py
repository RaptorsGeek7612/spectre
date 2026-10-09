"""Mistral as a mission execution agent, through the local Mistral Vibe CLI (`vibe -p`).

Vibe runs from its own home inside the assistant folder (`VIBE_HOME`), which Spectre rewrites on
each run: Spectre's identity as the system prompt and Spectre's tools over MCP. Only those tools
and web search/fetch are enabled, so every action still goes through the governance gate. Vibe
uses the Le Chat account it is logged in with, or a `MISTRAL_API_KEY` in the environment or in
`<assistant dir>/vibe/.env` (the free "Experiment" plan of console.mistral.ai is enough).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from spectre.assistant.brain import Reply, Runner
from spectre.assistant.config import AssistantConfig
from spectre.assistant.mcp_server import SERVER_NAME

LAUNCH = "from vibe.cli.launcher import main; main()"
WEB_TOOLS = ("web_search", "web_fetch")
SHEBANG = re.compile(rb"#!\"?([^\r\n\"]*python[^\r\n\"]*?\.exe)")


def vibe_command(name: str) -> list[str]:
    """How to start Vibe. pip's `vibe.exe` launcher can be blocked by Windows Smart App Control,
    so run the Python interpreter it points to instead (that one is signed)."""
    found = shutil.which(name) or name
    if found.lower().endswith(".exe"):
        try:
            match = SHEBANG.search(Path(found).read_bytes())
        except OSError:
            match = None
        if match:
            return [match.group(1).decode(), "-c", LAUNCH]
    return [found]


def toml(value: str) -> str:
    """A TOML basic string (JSON string escapes are valid TOML)."""
    return json.dumps(value, ensure_ascii=False)


class VibeCLI:
    """Runs `vibe -p` with Spectre's settings and returns the agent's last message."""

    def __init__(
        self, config: AssistantConfig, root: Path, runner: Runner = subprocess.run
    ) -> None:
        self.config = config
        self.root = root
        self.runner = runner
        self.workspace = root / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.home = root / "vibe"

    def write_home(self, system: str) -> None:
        """Vibe's settings for this run: system prompt, MCP tools, nothing personal."""
        (self.home / "prompts").mkdir(parents=True, exist_ok=True)
        (self.home / "prompts" / "spectre.md").write_text(system, encoding="utf-8")
        lines = [
            'system_prompt_id = "spectre"',
            "include_project_context = false",
            "enable_telemetry = false",
            "enable_update_checks = false",
            "enable_notifications = false",
        ]
        if self.config.mistral_model:
            lines.append(f"active_model = {toml(self.config.mistral_model)}")
        lines += [
            "",
            "[[mcp_servers]]",
            f"name = {toml(SERVER_NAME)}",
            'transport = "stdio"',
            f"command = {toml(sys.executable)}",
            'args = ["-m", "spectre.assistant.mcp_server"]',
            f"env = {{SPECTRE_ASSISTANT_DIR = {toml(str(self.root))}}}",
        ]
        (self.home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def env(self) -> dict[str, str]:
        return {**os.environ, "VIBE_HOME": str(self.home), "PYTHONIOENCODING": "utf-8"}

    def command(self, *, with_tools: bool) -> list[str]:
        tools = [f"{SERVER_NAME}_*", *WEB_TOOLS] if with_tools else ["aucun-outil"]
        cmd = [
            *vibe_command(self.config.vibe_bin),
            "--output",
            "text",
            "--auto-approve",  # Vibe's own prompt; Spectre's gate still rules every action
            "--max-turns",
            "30",
            "--workdir",
            str(self.workspace),
        ]
        for tool in tools:
            cmd += ["--enabled-tools", tool]
        return [*cmd, "-p"]  # the prompt comes on stdin

    def ask(
        self, prompt: str, *, system: str, model: str | None = None, with_tools: bool = True
    ) -> Reply:
        """One stateless run; `model` is ignored (the Mistral model comes from the settings)."""
        self.write_home(system)
        try:
            proc = self.runner(
                self.command(with_tools=with_tools),
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
            return Reply("Je ne trouve pas Mistral Vibe (commande « vibe ») sur ce PC.", "", True)
        except subprocess.TimeoutExpired:
            return Reply("Mistral n'a pas répondu à temps.", "", True)
        text = (proc.stdout or "").strip()
        if proc.returncode == 0 and text:
            return Reply(text, "", False)
        detail = [ln for ln in (proc.stderr or proc.stdout or "").splitlines() if ln.strip()]
        return Reply(
            f"Mistral a échoué : {detail[-1][:300] if detail else 'réponse vide'}", "", True
        )
