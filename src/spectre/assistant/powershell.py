"""PowerShell for Spectre, behind the governance gate.

A command is first parsed by PowerShell itself (in a fresh `pwsh -NoProfile`, never executed
there). When every command it contains is a known read-only cmdlet and nothing else can change
state (no method call, assignment, file redirection, env:/cert: drive, dynamic command), it runs
right away in a fresh headless `pwsh`. Anything else is CRITICAL: the user validates it, then it
runs in the visible PowerShell console shared with the user, through the open-source
PowerShell.MCP module (yotsuda/PowerShell.MCP, MIT), or headless if the module is missing.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

PWSH_TIMEOUT_S = 120.0  # headless runs (read-only commands, fallback)
CONSOLE_TIMEOUT_S = 300.0  # approved commands in the shared console
CLASSIFY_TIMEOUT_S = 30.0
MAX_OUTPUT_CHARS = 20_000

READ_VERBS = frozenset(
    {"get", "test", "measure", "select", "where", "sort", "format", "group", "compare"}
    | {"resolve", "convertto", "convertfrom", "join", "split"}
)
READ_EXTRA = frozenset({"out-string", "out-null", "write-output"})
# Read verbs that can still leak secrets, read arbitrary files, run code or call methods.
NOT_READ = frozenset(
    {
        "get-content",
        "get-credential",
        "get-clipboard",
        "get-secret",
        "get-secretinfo",
        "select-string",
        "format-hex",
        "convertto-securestring",
        "convertfrom-securestring",
        "foreach-object",
    }
)
SECRET_DRIVES = re.compile(r"(?i)\b(env|cert)\s*:")

# Parses the command (from $env:SPECTRE_PS_CMD) without running it; prints a JSON report.
CLASSIFIER = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$src = $env:SPECTRE_PS_CMD
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($src, [ref]$tokens, [ref]$errors)
$commands = [System.Collections.Generic.List[string]]::new()
$unsafe = [System.Collections.Generic.List[string]]::new()
foreach ($node in $ast.FindAll({ $true }, $true)) {
  $kind = $node.GetType().Name
  if ($kind -eq 'CommandAst') {
    $name = $node.GetCommandName()
    if (-not $name) { $unsafe.Add('commande dynamique') }
    else {
      $info = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($info -and $info.CommandType -eq 'Alias') {
        $info = Get-Command $info.Definition -ErrorAction SilentlyContinue | Select-Object -First 1
      }
      if ($info -and $info.CommandType -eq 'Cmdlet') { $commands.Add($info.Name) }
      else { $unsafe.Add("commande $name") }
    }
  }
  elseif ($kind -eq 'InvokeMemberExpressionAst') { $unsafe.Add('appel de methode') }
  elseif ($kind -eq 'AssignmentStatementAst') { $unsafe.Add('affectation') }
  elseif ($kind -eq 'FileRedirectionAst') { $unsafe.Add('redirection vers un fichier') }
  elseif ($kind -eq 'VariableExpressionAst' -and $node.VariablePath.DriveName) {
    $unsafe.Add('variable ' + $node.VariablePath.UserPath)
  }
}
[ordered]@{
  errors = @($errors | ForEach-Object { $_.Message })
  commands = @($commands)
  unsafe = @($unsafe)
} | ConvertTo-Json -Compress
"""


class PowerShellError(Exception):
    """PowerShell could not run the command; the message is shown to the user and the brain."""


def find_pwsh() -> str | None:  # pragma: no cover - depends on the machine
    """PowerShell 7 (`pwsh`), wherever winget or the MSI put it."""
    found = shutil.which("pwsh")
    if found:
        return found
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "pwsh.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "PowerShell" / "7" / "pwsh.exe",
    ]
    return next((str(p) for p in candidates if p.is_file()), None)


def _version_key(path: Path) -> tuple[int, ...]:
    # .../PowerShell.MCP/<version>/bin/win-x64/PowerShell.MCP.Proxy.exe
    parts = path.parents[2].name.split(".")
    return tuple(int(p) if p.isdigit() else 0 for p in parts)


def find_proxy() -> str | None:
    """The newest PowerShell.MCP proxy installed for this user (or $SPECTRE_PWSH_MCP_PROXY)."""
    override = os.environ.get("SPECTRE_PWSH_MCP_PROXY", "").strip()
    if override:
        return override if Path(override).is_file() else None
    documents = [Path.home() / "Documents", Path.home() / "OneDrive" / "Documents"]
    if os.environ.get("ONEDRIVE"):  # Windows env names are case-insensitive
        documents.append(Path(os.environ["ONEDRIVE"]) / "Documents")
    found: list[Path] = []
    for docs in documents:
        modules = docs / "PowerShell" / "Modules" / "PowerShell.MCP"
        found += modules.glob("*/bin/win-x64/PowerShell.MCP.Proxy.exe")
    return str(max(found, key=_version_key)) if found else None


def encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _pwsh_args(pwsh: str, script: str) -> list[str]:
    return [pwsh, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded(script)]


def assess(command: str, report: dict[str, Any]) -> str | None:
    """None when the parsed command is read-only; otherwise why it needs validation."""
    if report.get("errors"):
        return "commande mal formée : " + "; ".join(report["errors"])[:200]
    if report.get("unsafe"):
        return ", ".join(dict.fromkeys(report["unsafe"]))
    if SECRET_DRIVES.search(command):
        return "accès aux variables d'environnement ou aux certificats"
    for name in report.get("commands", []):
        low = name.lower()
        verb = low.split("-", 1)[0]
        if low in NOT_READ or (verb not in READ_VERBS and low not in READ_EXTRA):
            return f"{name} n'est pas une commande de lecture sans risque"
    return None


def read_only_reason(command: str, runner: Any = None) -> str | None:
    """Ask PowerShell's parser what the command does. None = read-only (safe to run alone)."""
    if not command.strip():
        return None
    pwsh = find_pwsh()
    if pwsh is None:
        return "PowerShell 7 introuvable : impossible d'analyser la commande"
    run = runner or subprocess.run
    try:
        proc = run(
            _pwsh_args(pwsh, CLASSIFIER),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLASSIFY_TIMEOUT_S,
            check=False,
            env={**os.environ, "SPECTRE_PS_CMD": command},
        )
        report = json.loads(proc.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return "analyse de la commande impossible"
    if not isinstance(report, dict) or not report:
        return "analyse de la commande impossible"
    return assess(command, report)


def run_headless(command: str, runner: Any = None, timeout: float = PWSH_TIMEOUT_S) -> str:
    """Run in a fresh, invisible `pwsh -NoProfile` (no state shared with earlier commands)."""
    pwsh = find_pwsh()
    if pwsh is None:
        raise PowerShellError(
            "PowerShell 7 est introuvable sur ce PC (winget install Microsoft.PowerShell)."
        )
    script = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
        f"& {{\n{command}\n}} | Out-String -Width 160"
    )
    run = runner or subprocess.run
    try:
        proc = run(
            _pwsh_args(pwsh, script),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PowerShellError(f"commande trop longue (> {int(timeout)} s)") from exc
    out, err = (proc.stdout or "").strip(), (proc.stderr or "").strip()
    body = out or "(aucune sortie)"
    if err:
        body += f"\n[erreurs] {err[:2000]}"
    if proc.returncode != 0:
        body = f"(code {proc.returncode})\n{body}"
    return body[:MAX_OUTPUT_CHARS]


def _text(result: Any) -> str:
    return "\n".join(getattr(c, "text", "") for c in getattr(result, "content", []) or [])


async def _console_session(  # pragma: no cover - needs the PowerShell.MCP proxy
    proxy: str, command: str, timeout: float
) -> str:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=proxy, args=["--no-profile"])
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    with open(os.devnull, "w", encoding="utf-8") as quiet:  # the proxy logs to stderr
        async with (
            stdio_client(params, errlog=quiet) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool("execute_command", {"pipeline": command})
            text = _text(result)
            # Past the proxy's per-call ceiling the command keeps running; collect it.
            while "wait_for_completion" in text and loop.time() < deadline:
                result = await session.call_tool("wait_for_completion", {})
                text = _text(result)
            return text


def run_in_console(command: str, proxy: str, timeout: float = CONSOLE_TIMEOUT_S) -> str:
    """Run in the visible PowerShell.MCP console (from any thread, even inside an event loop)."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["out"] = asyncio.run(_console_session(proxy, command, timeout))
        except BaseException as exc:  # noqa: BLE001 - reported to the caller below
            box["err"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout + 30)
    if worker.is_alive():
        raise PowerShellError(f"la console PowerShell ne répond pas (> {int(timeout)} s)")
    if "err" in box:
        raise PowerShellError(f"console PowerShell indisponible : {box['err']}")
    return str(box.get("out") or "(aucune sortie)")[:MAX_OUTPUT_CHARS]


def run(command: str, *, read_only: bool, runner: Any = None) -> str:
    if read_only:
        return run_headless(command, runner)
    proxy = find_proxy()
    if proxy is None or runner is not None:
        return run_headless(command, runner)
    return run_in_console(command, proxy)
