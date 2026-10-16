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


def test_science_operations() -> None:
    assert "[-2, 2]" in toolkit.science("resoudre", "x**2 - 4")
    assert "cos(x)" in toolkit.science("deriver", "sin(x)")
    assert toolkit.science("integrer", "2*x").startswith("∫")
    assert "3.14159" in toolkit.science("calculer", "pi")
    assert toolkit.science("simplifier", "x + x").endswith("2*x")
    with pytest.raises(ActionError, match="opération inconnue"):
        toolkit.science("magie", "x")
    with pytest.raises(ActionError, match="invalide"):
        toolkit.science("calculer", "2 +")


def test_betting_operations() -> None:
    assert "40.0 %" in toolkit.betting("probabilite", [2.5])
    kelly = toolkit.betting("kelly", [2.5, 0.5])
    assert "16.7 %" in kelly and "risque de perte" in kelly
    assert "0.0 %" in toolkit.betting("kelly", [2.0, 0.4])  # no edge -> never bet
    assert "arbitrage possible" in toolkit.betting("arbitrage", [2.1, 2.1])
    assert "pas d'arbitrage" in toolkit.betting("arbitrage", [1.8, 1.8])
    with pytest.raises(ActionError, match="opération inconnue"):
        toolkit.betting("pronostic", [1])
    with pytest.raises(ActionError, match="calcul impossible"):
        toolkit.betting("kelly", [2.0])


def test_science_and_betting_are_restricted(ctx: Any) -> None:
    gate = Gate(ctx.db)
    ctx.agent = "ysyss"
    assert "[-2, 2]" in tools_mod.execute(
        gate, ctx, "science", {"operation": "resoudre", "expression": "x**2 - 4"}
    )
    ctx.agent = "lexy"
    assert tools_mod.execute(
        gate, ctx, "science", {"operation": "calculer", "expression": "1"}
    ).startswith("REFUSÉ")
    assert "40.0 %" in tools_mod.execute(
        gate, ctx, "paris", {"operation": "probabilite", "values": [2.5]}
    )
    ctx.agent = "shelby"
    assert tools_mod.execute(
        gate, ctx, "paris", {"operation": "probabilite", "values": [2.0]}
    ).startswith("REFUSÉ")


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


# ---- Kyra: advertising and communication media ----------------------------------------------


def test_media_tools_are_kyras(ctx: Any) -> None:
    for name in ("video_format", "image_format", "sous_titres", "detourage", "voix_off"):
        assert toolkit.KITS[name].agents == ("chatgpt",)
        assert toolkit.KITS[name].level == Level.WRITE
    ctx.agent = "lexy"
    with pytest.raises(ActionError, match="ton domaine"):
        toolkit.run(ctx, "video_format", "leak.txt", "story")


def test_video_format_crops_to_the_network_frame(ctx: Any) -> None:
    ctx.agent = "chatgpt"
    (ctx.allowed_roots[0] / "spot.mp4").write_bytes(b"v")
    calls: list[list[str]] = []
    made = toolkit.KITS["video_format"].output(ctx, "spot.mp4", "story")  # type: ignore[misc]

    def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        made.write_bytes(b"x")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    ctx.runner = run
    out = toolkit.run(ctx, "video_format", "spot.mp4", "story")
    assert out.startswith("Fichier créé") and made.name == "spot-story.mp4"
    assert "crop=1080:1920" in " ".join(calls[0]) and "-n" in calls[0]  # never overwrites
    with pytest.raises(ActionError, match="format inconnu"):
        toolkit.run(ctx, "video_format", "spot.mp4", "panorama")


def test_media_tool_fails_without_its_file(ctx: Any) -> None:
    ctx.agent = "chatgpt"
    (ctx.allowed_roots[0] / "pic.jpg").write_bytes(b"i")
    ctx.runner.result = subprocess.CompletedProcess([], 0, "", "")  # ran, but wrote nothing
    with pytest.raises(ActionError, match="aucun fichier produit"):
        toolkit.run(ctx, "detourage", "pic.jpg")
    assert ctx.runner.calls[0][-1].endswith("pic-detoure.png")


def test_subtitles_voice_and_burn_in_commands(ctx: Any) -> None:
    ctx.agent = "chatgpt"
    home = ctx.allowed_roots[0]
    for name in ("clip.mp4", "texte.txt"):
        (home / name).write_bytes(b"x")
    ctx.runner.result = subprocess.CompletedProcess([], 0, "", "")
    with pytest.raises(ActionError):  # the fake runner writes nothing
        toolkit.run(ctx, "sous_titres", "clip.mp4", "en")
    assert ctx.runner.calls[-1][ctx.runner.calls[-1].index("--language") + 1] == "en"
    with pytest.raises(ActionError, match="deux lettres"):
        toolkit.run(ctx, "sous_titres", "clip.mp4", "français")
    (home / "clip.srt").write_bytes(b"1")
    with pytest.raises(ActionError):
        toolkit.run(ctx, "incruster", "clip.mp4")
    burn = " ".join(ctx.runner.calls[-1])
    assert "subtitles='" in burn and "\:" in burn and burn.endswith("clip-soustitree.mp4")
    with pytest.raises(ActionError):
        toolkit.run(ctx, "voix_off", "texte.txt", "3")
    voice = ctx.runner.calls[-1]
    assert voice[voice.index("--speed") + 1] == "2.0" and "fr-fr" in voice  # speed is bounded
    with pytest.raises(ActionError, match="vitesse"):
        toolkit.run(ctx, "voix_off", "texte.txt", "vite")


def test_production_tools_commands(ctx: Any) -> None:
    ctx.agent = "chatgpt"
    home = ctx.allowed_roots[0]
    for name in ("film.fountain", "rush.mp4"):
        (home / name).write_bytes(b"x")
    ctx.runner.result = subprocess.CompletedProcess([], 0, "", "")
    for name, target, options, ends in (
        ("scenario_pdf", "film.fountain", "", "film-scenario.pdf"),
        ("derushage", "rush.mp4", "", "--no-open"),
        ("loudness", "rush.mp4", "tv", "rush-23lufs.mp4"),
        ("plans", "rush.mp4", "", "rush-plans.csv"),
    ):
        with pytest.raises(ActionError, match="aucun fichier produit"):
            toolkit.run(ctx, name, target, options)
        assert ctx.runner.calls[-1][-1].endswith(ends), name
    assert "loudnorm=I=-23" in " ".join(ctx.runner.calls[2])
    with pytest.raises(ActionError, match="web"):
        toolkit.run(ctx, "loudness", "rush.mp4", "cinema")
    ctx.agent = "scribe"  # writers may lay out a screenplay, not edit rushes
    with pytest.raises(ActionError, match="aucun fichier produit"):
        toolkit.run(ctx, "scenario_pdf", "film.fountain")
    with pytest.raises(ActionError, match="ton domaine"):
        toolkit.run(ctx, "derushage", "rush.mp4")
