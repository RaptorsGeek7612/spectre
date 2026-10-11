"""Tests for the PowerShell tool: read-only detection, gate levels, headless and console runs."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.assistant import powershell, tools
from spectre.assistant.actions import ActionContext
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate, Level


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "assistant" / "spectre.db")
    yield database
    database.close()


class FakePwsh:
    """subprocess.run stand-in: the classifier gets `reports[command]`, a run gets `output`."""

    def __init__(self, reports: dict[str, dict[str, Any]], output: str = "ok") -> None:
        self.reports = reports
        self.output = output
        self.ran: list[list[str]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> SimpleNamespace:
        env = kwargs.get("env")
        if env and "SPECTRE_PS_CMD" in env:
            report = self.reports.get(env["SPECTRE_PS_CMD"], {"unsafe": ["commande inconnue"]})
            return SimpleNamespace(stdout=json.dumps(report), stderr="", returncode=0)
        self.ran.append(args)
        return SimpleNamespace(stdout=self.output, stderr="", returncode=0)


@pytest.fixture(autouse=True)
def pwsh_here(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(powershell, "find_pwsh", lambda: "pwsh")


READ = {"errors": [], "commands": ["Get-Process", "Sort-Object"], "unsafe": []}


def test_assess_read_only_and_not() -> None:
    assert powershell.assess("Get-Process | Sort-Object", READ) is None
    assert "Remove-Item" in str(powershell.assess("x", {"commands": ["Remove-Item"]}))
    assert "Get-Content" in str(powershell.assess("x", {"commands": ["Get-Content"]}))
    assert powershell.assess("x", {"commands": ["Out-String"]}) is None
    assert "affectation" in str(powershell.assess("x", {"unsafe": ["affectation"] * 2}))
    assert "mal formée" in str(powershell.assess("x", {"errors": ["vide"]}))
    assert "environnement" in str(powershell.assess("Get-ChildItem Env:", READ))


def test_read_only_reason_handles_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    assert powershell.read_only_reason("  ") is None

    def broken(*_: Any, **__: Any) -> Any:
        raise subprocess.TimeoutExpired("pwsh", 1)

    assert "impossible" in str(powershell.read_only_reason("Get-Date", broken))
    empty = SimpleNamespace(stdout="", stderr="", returncode=1)
    assert "impossible" in str(powershell.read_only_reason("Get-Date", lambda *a, **k: empty))
    monkeypatch.setattr(powershell, "find_pwsh", lambda: None)
    assert "introuvable" in str(powershell.read_only_reason("Get-Date"))
    with pytest.raises(powershell.PowerShellError, match="introuvable"):
        powershell.run_headless("Get-Date")


def test_run_headless_output_errors_and_timeout() -> None:
    def runner(args: list[str], **_: Any) -> SimpleNamespace:
        return SimpleNamespace(stdout="", stderr="boom", returncode=1)

    out = powershell.run_headless("Get-Date", runner)
    assert out.startswith("(code 1)") and "(aucune sortie)" in out and "boom" in out

    def slow(*_: Any, **__: Any) -> Any:
        raise subprocess.TimeoutExpired("pwsh", 1)

    with pytest.raises(powershell.PowerShellError, match="trop longue"):
        powershell.run_headless("Start-Sleep 999", slow)


def test_encoded_command_round_trip() -> None:
    import base64

    args = powershell._pwsh_args("pwsh", "Get-Date # é")
    assert args[:3] == ["pwsh", "-NoProfile", "-NonInteractive"]
    assert base64.b64decode(args[-1]).decode("utf-16-le") == "Get-Date # é"


def test_tool_read_only_runs_at_once(db: Database, tmp_path: Path) -> None:
    fake = FakePwsh({"Get-Process | Sort-Object": READ}, output="pwsh 7")
    ctx = ActionContext(db=db, root=tmp_path, pwsh_runner=fake)
    args = {"command": "Get-Process | Sort-Object"}
    assert tools.TOOLS["powershell"].risk(ctx, args) == (Level.READ, "read")
    assert tools.execute(Gate(db), ctx, "powershell", args) == "pwsh 7"
    assert fake.ran and fake.ran[0][:2] == ["pwsh", "-NoProfile"]


def test_tool_change_waits_for_approval(db: Database, tmp_path: Path) -> None:
    fake = FakePwsh({}, output="supprimé")
    ctx = ActionContext(db=db, root=tmp_path, pwsh_runner=fake)
    args = {"command": "Remove-Item C:/x.txt"}
    assert tools.TOOLS["powershell"].risk(ctx, args) == (Level.CRITICAL, "powershell")
    pending = tools.execute(Gate(db), ctx, "powershell", args)
    assert pending.startswith("EN ATTENTE DE VALIDATION") and not fake.ran
    approval = db.one("SELECT id FROM approvals")
    assert approval is not None
    assert tools.run_approved(Gate(db), ctx, approval["id"]) == "supprimé"
    assert tools.execute(Gate(db), ctx, "powershell", {"command": " "}).startswith("ÉCHEC")


def test_find_proxy_prefers_newest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("SPECTRE_PWSH_MCP_PROXY", raising=False)
    monkeypatch.delenv("ONEDRIVE", raising=False)
    assert powershell.find_proxy() is None
    base = tmp_path / "OneDrive" / "Documents" / "PowerShell" / "Modules" / "PowerShell.MCP"
    for version in ("1.9.0", "1.15.0"):
        exe = base / version / "bin" / "win-x64" / "PowerShell.MCP.Proxy.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"")
    assert "1.15.0" in str(powershell.find_proxy())
    monkeypatch.setenv("SPECTRE_PWSH_MCP_PROXY", str(tmp_path / "absent.exe"))
    assert powershell.find_proxy() is None


def test_run_in_console(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fine(proxy: str, command: str, timeout: float) -> str:
        return f"{proxy}:{command}"

    monkeypatch.setattr(powershell, "_console_session", fine)
    monkeypatch.setattr(powershell, "find_proxy", lambda: "proxy.exe")
    assert powershell.run("hostname", read_only=False) == "proxy.exe:hostname"

    async def broken(proxy: str, command: str, timeout: float) -> str:
        raise OSError("pas de proxy")

    monkeypatch.setattr(powershell, "_console_session", broken)
    with pytest.raises(powershell.PowerShellError, match="indisponible"):
        powershell.run_in_console("hostname", "proxy.exe")


def test_console_result_text() -> None:
    result = SimpleNamespace(content=[SimpleNamespace(text="a"), SimpleNamespace(text="b")])
    assert powershell._text(result) == "a\nb"
    assert powershell._text(None) == ""


def test_tool_reports_powershell_errors(db: Database, tmp_path: Path) -> None:
    def slow(args: list[str], **kwargs: Any) -> SimpleNamespace:
        if "SPECTRE_PS_CMD" in (kwargs.get("env") or {}):
            return SimpleNamespace(stdout=json.dumps(READ), stderr="", returncode=0)
        raise subprocess.TimeoutExpired("pwsh", 1)

    ctx = ActionContext(db=db, root=tmp_path, pwsh_runner=slow)
    out = tools.execute(Gate(db), ctx, "powershell", {"command": "Get-Process"})
    assert out.startswith("ÉCHEC") and "trop longue" in out
