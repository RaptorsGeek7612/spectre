"""Tools Spectre gives its agents (tool cards): data only, through the gate, never code."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import agent_tools, team, toolkit
from spectre.assistant import tools as tools_mod
from spectre.assistant.actions import ActionError
from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate, Level


class Runner:
    def __init__(self, stdout: str = "ok", returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []
        self.result = subprocess.CompletedProcess([], returncode, stdout, "")

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        self.kwargs.append(kw)
        return self.result


@pytest.fixture
def ctx(tmp_path: Path) -> Any:
    db = Database(tmp_path / "a.db")
    home = tmp_path / "home"
    home.mkdir()
    (home / "photo.jpg").write_bytes(b"x")
    context = tools_mod.make_context(db, tmp_path / "assistant", [str(home)])
    context.runner = Runner()
    yield context
    db.close()


@pytest.fixture(autouse=True)
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(toolkit, "_bin", lambda names: "C:/bin/" + names[0])


def _exiftool(ctx: Any, **kw: Any) -> str:
    args = {
        "name": "exiftool",
        "label": "ExifTool (métadonnées)",
        "agents": "Kyra, Syfer",
        "program_": "exiftool",
        "args": ["-json", "{options}", "{cible}"],
        "description": "lire les métadonnées d'une photo",
        "install": "winget:OliverBetz.ExifTool",
    } | kw
    return agent_tools.save(ctx, **args)


def test_save_list_and_run_a_card(ctx: Any, tmp_path: Path) -> None:
    assert "créée pour Kyra, Syfer" in _exiftool(ctx)
    card = agent_tools.load(ctx.root, "exiftool")
    assert card is not None and card["agents"] == ["chatgpt", "mistral"]
    assert card["install"] == {"method": "winget", "package": "OliverBetz.ExifTool"}
    assert "mise à jour" in _exiftool(ctx, label="ExifTool")
    ctx.agent = "chatgpt"
    assert "exiftool — ExifTool" in agent_tools.listing(ctx)
    out = toolkit.run(ctx, "exiftool", str(tmp_path / "home" / "photo.jpg"), "-G -n")
    assert out == "ok"
    assert ctx.runner.calls[-1] == [
        "C:/bin/exiftool",
        "-json",
        "-G",
        "-n",
        str((tmp_path / "home" / "photo.jpg").resolve()),
    ]
    assert ctx.runner.kwargs[-1]["cwd"] == str(ctx.workspace)
    ctx.agent = "antigravity"  # Clarke: not her field
    assert agent_tools.listing(ctx).startswith("aucun outil")
    with pytest.raises(ActionError, match="pas un outil de ton domaine"):
        toolkit.run(ctx, "exiftool", "photo.jpg")


def test_card_refusals(ctx: Any) -> None:
    for kw, message in [
        ({"name": "Bad Name"}, "nom d'outil invalide"),
        ({"name": "pandoc"}, "déjà un outil intégré"),
        ({"program_": "powershell"}, "pas un outil"),
        ({"program_": "C:/Windows/System32/cmd.exe"}, "pas un outil"),
        ({"program_": "a b"}, "nom de programme invalide"),
        ({"program_": ""}, "indique le programme"),
        ({"agents": ""}, "indique les agents"),
        ({"agents": "Zorglub"}, "agent inconnu"),
        ({"level": "root"}, "niveau inconnu"),
        ({"args": ["-x{options}"]}, "à lui seul"),
        ({"args": ["{cible}", "{cible}"]}, "qu'une fois"),
        ({"install": "choco:thing"}, "installation"),
    ]:
        with pytest.raises(ActionError, match=message):
            _exiftool(ctx, **kw)
    assert agent_tools.cards(ctx.root) == []


def test_run_refusals(ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _exiftool(ctx, agents="tous")
    for options in ("-o C:/Windows/x", "../secret", "a;b", "'unterminated"):
        with pytest.raises(ActionError, match="option"):
            agent_tools.run(ctx, "exiftool", "photo.jpg", options)
    with pytest.raises(ActionError, match="précise la cible"):
        agent_tools.run(ctx, "exiftool", "")
    with pytest.raises(ActionError, match="accès refusé"):
        agent_tools.run(ctx, "exiftool", "C:/Windows/win.ini")
    with pytest.raises(ActionError, match="outil inconnu"):
        toolkit.run(ctx, "absent")
    monkeypatch.setattr(toolkit, "_bin", lambda names: None)
    with pytest.raises(ActionError, match="pas installé"):
        agent_tools.run(ctx, "exiftool", "photo.jpg")
    ctx.runner.result = subprocess.CompletedProcess([], 2, "", "boom")
    monkeypatch.setattr(toolkit, "_bin", lambda names: "C:/bin/x")
    with pytest.raises(ActionError, match="boom"):
        agent_tools.run(ctx, "exiftool", "photo.jpg")


def test_remote_card_and_risk(ctx: Any) -> None:
    _exiftool(ctx, name="sonde", args=["{cible}"], level="distant", agents="Syfer")
    card = agent_tools.load(ctx.root, "sonde")
    assert agent_tools.risk(card) == (Level.EXTERNAL, "scan_remote")
    assert tools_mod._toolkit_risk(ctx, {"name": "sonde"}) == (Level.EXTERNAL, "scan_remote")
    assert tools_mod._toolkit_risk(ctx, {"name": "nmap"})[0] == toolkit.KITS["nmap"].level
    assert agent_tools.command(ctx, card, "x", "https://example.org/a?b=1", "") == [
        "x",
        "https://example.org/a?b=1",
    ]
    with pytest.raises(ActionError, match="adresse invalide"):
        agent_tools.command(ctx, card, "x", "-oG out", "")


def test_install_and_delete(ctx: Any) -> None:
    _exiftool(ctx)
    assert "installé via winget" in agent_tools.install(ctx, "exiftool")
    assert ctx.runner.calls[-1][1:4] == ["install", "--id", "OliverBetz.ExifTool"]
    agent_tools.install(ctx, "exiftool", "uv:exif-tool==1.0")
    assert ctx.runner.calls[-1][1:] == ["tool", "install", "exif-tool==1.0"]
    assert agent_tools.load(ctx.root, "exiftool")["install"]["method"] == "uv"
    ctx.runner.result = subprocess.CompletedProcess([], 1, "", "no package")
    with pytest.raises(ActionError, match="installation échouée"):
        agent_tools.install(ctx, "exiftool")
    with pytest.raises(ActionError, match="aucune fiche"):
        agent_tools.install(ctx, "absent")
    _exiftool(ctx, name="nu", install="")
    with pytest.raises(ActionError, match="précise la source"):
        agent_tools.install(ctx, "nu")
    assert "supprimée" in agent_tools.delete(ctx, "exiftool")
    with pytest.raises(ActionError, match="aucune fiche"):
        agent_tools.delete(ctx, "exiftool")


def test_installed_programs(ctx: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    apps = tmp_path / "Apps"
    (apps / "LanguageTool-6.6").mkdir(parents=True)
    (apps / "kokoro").mkdir()
    monkeypatch.setattr(agent_tools, "_folders", lambda: [("Apps", apps)])
    monkeypatch.setattr(agent_tools.shutil, "which", lambda name: "C:/winget.exe")
    ctx.runner = Runner("Nom  Id\nGIMP  GIMP.GIMP\nInkscape  Inkscape.Inkscape\n")
    out = agent_tools.installed(ctx)
    assert "LanguageTool-6.6, kokoro" in out and "GIMP.GIMP" in out
    out = agent_tools.installed(ctx, "gimp")
    assert "GIMP.GIMP" in out and "Inkscape" not in out and "kokoro" not in out
    assert agent_tools.installed(ctx, "rien") == "rien trouvé pour « rien »"


def test_tools_are_spectres_and_gated(ctx: Any, tmp_path: Path) -> None:
    registry = tools_mod.TOOLS
    for name in ("agent_tool_save", "agent_tool_install", "agent_tool_delete"):
        assert registry[name].lead_only and not registry[name].allowed("chatgpt")
    assert registry["outils_agents"].allowed("chatgpt")
    gate = Gate(ctx.db)
    assert gate.decide(Level.WRITE, "agent_tool").verdict == "approval"
    assert gate.decide(Level.CRITICAL, "install_agent_tool").verdict == "approval"
    _exiftool(ctx)
    found = team.agent_tools(AssistantConfig(), "chatgpt", ctx.root)
    assert any(t["name"] == "exiftool" and t.get("added") for t in found)
    assert not any(t["name"] == "exiftool" for t in team.agent_tools(AssistantConfig(), "simon"))
