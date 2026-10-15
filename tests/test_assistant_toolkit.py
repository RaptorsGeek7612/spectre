"""The open-source toolkit given to the agents: CLI tools per field, and finance maths."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import toolkit
from spectre.assistant import tools as tools_mod
from spectre.assistant.actions import ActionError
from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate, Level


class Runner:
    def __init__(self, stdout: str = "ok", returncode: int = 0, stderr: str = "") -> None:
        self.calls: list[list[str]] = []
        self.result = subprocess.CompletedProcess([], returncode, stdout, stderr)

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        return self.result


@pytest.fixture
def ctx(tmp_path: Path) -> Any:
    db = Database(tmp_path / "a.db")
    home = tmp_path / "home"
    home.mkdir()
    (home / "leak.txt").write_text("x", encoding="utf-8")
    context = tools_mod.make_context(db, tmp_path / "assistant", [str(home)])
    context.runner = Runner()
    yield context
    db.close()


@pytest.fixture(autouse=True)
def installed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    jar = tmp_path / "languagetool-commandline.jar"
    jar.write_text("", encoding="utf-8")
    monkeypatch.setattr(toolkit, "_bin", lambda names: "C:/bin/" + names[0])
    monkeypatch.setattr(toolkit, "LANGUAGETOOL", jar)


def test_finance_operations() -> None:
    assert "1109.20" in toolkit.finance("mensualite", [0.03 / 12, 240, 200000])
    assert toolkit.finance("van", [0.1, -1000, 600, 600]).startswith("VAN")
    assert "%" in toolkit.finance("tri", [-1000, 300, 400, 500])
    assert toolkit.finance("valeur_future", [0.02, 10, -100, -1000]).startswith("Valeur future")
    with pytest.raises(ActionError, match="opération inconnue"):
        toolkit.finance("magie", [1])
    with pytest.raises(ActionError, match="calcul impossible"):
        toolkit.finance("mensualite", [1])


def test_gitleaks_scans_a_local_path_as_read(ctx: Any) -> None:
    ctx.agent = "mistral"
    ctx.runner.result = subprocess.CompletedProcess([], 0, "[]", "no leaks")
    out = toolkit.run(ctx, "gitleaks", "leak.txt")
    assert out.startswith("[]")
    command = ctx.runner.calls[0]
    assert (
        command[1] == "dir" and command[2].endswith("leak.txt") and "C:/bin/gitleaks" in command[0]
    )
    assert tools_mod._toolkit_risk(ctx, {"name": "gitleaks"}) == (Level.READ, "scan")


def test_a_tool_is_only_for_its_agents(ctx: Any) -> None:
    ctx.agent = "cursor"  # Octavya cannot run a security scanner
    with pytest.raises(ActionError, match="ton domaine"):
        toolkit.run(ctx, "gitleaks", "leak.txt")
    ctx.agent = "mistral"
    assert toolkit.run(ctx, "gitleaks", "leak.txt")
    ctx.agent = "scribe"  # a writer may check prose; everyone may (vale allows writers)
    assert toolkit.run(ctx, "vale", "leak.txt")


def test_remote_scan_is_external(ctx: Any) -> None:
    assert toolkit.KITS["nuclei"].level == Level.EXTERNAL
    assert tools_mod._toolkit_risk(ctx, {"name": "nuclei"}) == (Level.EXTERNAL, "scan_remote")
    ctx.agent = "mistral"
    toolkit.run(ctx, "nuclei", "https://example.com")
    assert ctx.runner.calls[0][2] == "https://example.com"  # URL passed as-is, not a path


def test_pandoc_needs_an_output_and_errors(ctx: Any) -> None:
    ctx.agent = "chatgpt"
    with pytest.raises(ActionError, match="fichier de sortie"):
        toolkit.run(ctx, "pandoc", "leak.txt")
    toolkit.run(ctx, "pandoc", "leak.txt", "out.docx")
    assert ctx.runner.calls[0][-2:][0] == "-o"
    with pytest.raises(ActionError, match="inconnu"):
        toolkit.run(ctx, "nope", "x")
    with pytest.raises(ActionError, match="précise la cible"):
        toolkit.run(ctx, "ocr", " ")


def test_missing_binary_is_reported(ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(toolkit, "_bin", lambda names: None)
    ctx.agent = "mistral"
    with pytest.raises(ActionError, match="n'est pas installé"):
        toolkit.run(ctx, "trivy", "leak.txt")


def test_describe_lists_tools_and_installs(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {r["name"]: r for r in toolkit.describe(AssistantConfig())}
    assert rows["gitleaks"]["agents"] == ["mistral"] and rows["gitleaks"]["installed"]
    assert rows["languagetool"]["agents"] == [] and rows["nuclei"]["category"] == "scan_remote"
    monkeypatch.setattr(toolkit, "_bin", lambda names: None)
    assert not toolkit.describe(AssistantConfig())[0]["installed"]


def test_through_the_gate(ctx: Any) -> None:
    gate = Gate(ctx.db)
    ctx.agent = "mistral"
    ctx.runner.result = subprocess.CompletedProcess([], 1, "finding!", "")  # exit 1 = a result
    out = tools_mod.execute(gate, ctx, "toolkit", {"name": "gitleaks", "target": "leak.txt"})
    assert "finding!" in out
    ctx.agent = "cursor"
    refused = tools_mod.execute(gate, ctx, "toolkit", {"name": "gitleaks", "target": "leak.txt"})
    assert refused.startswith("ÉCHEC") and "domaine" in refused
    ctx.agent = "antigravity"
    money = tools_mod.execute(
        gate, ctx, "finance", {"operation": "tri", "values": [-1000, 600, 600]}
    )
    assert "TRI" in money
    ctx.agent = "mistral"  # finance is Clarke's and Simon's only
    assert tools_mod.execute(
        gate, ctx, "finance", {"operation": "tri", "values": [-1, 2]}
    ).startswith("REFUSÉ")


def test_remote_scan_waits_for_approval(ctx: Any) -> None:
    gate = Gate(ctx.db, auto_max_level=int(Level.WRITE))
    ctx.agent = "mistral"
    answer = tools_mod.execute(
        gate, ctx, "toolkit", {"name": "nuclei", "target": "https://example.com"}
    )
    assert answer.startswith("EN ATTENTE DE VALIDATION")
    assert ctx.runner.calls == []  # not run until the user approves
