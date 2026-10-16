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
    assert "subtitles='" in burn and r"\:" in burn and burn.endswith("clip-soustitree.mp4")
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


# ---- Simon: trading maths and market data ---------------------------------------------------


def test_trading_operations() -> None:
    size = toolkit.trading("taille_position", [10000, 1, 100, 95])
    assert "20 unités" in size and "100.00" in size  # 1 % of 10 000 = 100 at risk, 5 per unit
    assert "+0.20 R" in toolkit.trading("esperance", [40, 200, 100])  # 0.4*200 - 0.6*100 = 20
    assert "33.3 %" in toolkit.trading("esperance", [0.5, 200, 100])  # breakeven win rate
    assert "2.00 R" in toolkit.trading("gain_risque", [100, 95, 110])
    assert "-50.0 %" in toolkit.trading("drawdown", [100, 200, 100, 150])
    with pytest.raises(ActionError, match="opération inconnue"):
        toolkit.trading("martingale", [1])
    with pytest.raises(ActionError, match="calcul impossible"):
        toolkit.trading("taille_position", [1000, 1, 100, 100])  # stop on the entry


def _candles(closes: list[float]) -> list[list[float]]:
    return [[i * 86_400_000.0, c, c * 1.01, c * 0.99, c, 1.0] for i, c in enumerate(closes)]


def test_indicators_from_candles() -> None:
    rising = toolkit.indicators(_candles([100 + i for i in range(60)]))
    assert rising["rsi14"] == 100.0 and rising["sma50"] is not None and rising["sma200"] is None
    assert rising["drawdown"] == 0.0 and (rising["performance"] or 0) > 0.5
    falling = toolkit.indicators(_candles([100, 50, 75]))
    assert falling["drawdown"] == pytest.approx(-0.5)
    with pytest.raises(ActionError, match="pas assez"):
        toolkit.indicators(_candles([1]))


def test_market_is_dated_and_sourced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        toolkit,
        "_crypto_ticker",
        lambda s: {"last": 70000, "bid": 69990, "ask": 70010, "percentage": 1.5, "timestamp": 0},
    )
    monkeypatch.setattr(
        toolkit, "_crypto_book", lambda s: {"bids": [[69990, 1]], "asks": [[70010, 2]]}
    )
    monkeypatch.setattr(toolkit, "_yahoo_daily", lambda s, p: _candles([100.0] * 30 + [110.0]))
    monkeypatch.setattr(toolkit, "_crypto_daily", lambda s, d: _candles([1.0, 2.0]))
    price = toolkit.market("prix", "btc/eur")
    assert "BTC/EUR : 70000" in price and "temps réel" in price and "UTC" in price
    stock = toolkit.market("prix", "^FCHI")
    assert "+10.00%" in stock and "retard" in stock
    assert "écart 20" in toolkit.market("carnet", "BTC/EUR")
    report = toolkit.market("analyse", "AAPL", "3mo")
    assert "RSI14" in report and "pas un signal" in report
    assert "performance +100.0%" in toolkit.market("analyse", "ETH/EUR", "")
    with pytest.raises(ActionError, match="crypto"):
        toolkit.market("carnet", "AAPL")
    with pytest.raises(ActionError, match="période"):
        toolkit.market("analyse", "AAPL", "10y")
    with pytest.raises(ActionError, match="symbole"):
        toolkit.market("prix", " ")

    def down(symbol: str) -> dict[str, Any]:
        raise OSError("réseau coupé")

    monkeypatch.setattr(toolkit, "_crypto_ticker", down)
    with pytest.raises(ActionError, match="injoignable"):
        toolkit.market("prix", "BTC/EUR")


def test_market_tools_are_simons_and_lexys(ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(toolkit, "market", lambda op, sym, opt="": f"{op} {sym}")
    gate = Gate(ctx.db)
    ctx.agent = "simon"
    assert tools_mod.execute(gate, ctx, "marche", {"operation": "prix", "symbol": "AAPL"}) == (
        "prix AAPL"
    )
    assert "R" in tools_mod.execute(
        gate, ctx, "trading", {"operation": "gain_risque", "values": [100, 95, 110]}
    )
    ctx.agent = "shelby"
    refused = tools_mod.execute(gate, ctx, "marche", {"operation": "prix", "symbol": "AAPL"})
    assert refused.startswith("REFUSÉ")


# ---- Syfer: more pentest tools (authorized scans) -------------------------------------------


def test_recon_tools_are_syfers_and_remote(ctx: Any) -> None:
    for name in ("nmap", "subfinder", "httpx"):
        assert toolkit.KITS[name].agents == ("mistral",)
        assert toolkit.KITS[name].remote and toolkit.KITS[name].level == Level.EXTERNAL
        assert tools_mod._toolkit_risk(ctx, {"name": name}) == (Level.EXTERNAL, "scan_remote")
    assert not toolkit.KITS["trufflehog"].remote  # secrets in a local folder = a read
    assert toolkit.KITS["trufflehog"].level == Level.READ


def test_recon_commands(ctx: Any) -> None:
    ctx.agent = "mistral"
    toolkit.run(ctx, "nmap", "juice-shop")
    cmd = ctx.runner.calls[-1]
    assert "-sT" in cmd and "-sV" in cmd and cmd[-1] == "juice-shop"  # connect scan, target last
    toolkit.run(ctx, "subfinder", "example.com")
    assert ctx.runner.calls[-1][1:] == ["-d", "example.com", "-silent"]
    toolkit.run(ctx, "httpx", "http://juice-shop:3000")
    assert "-tech-detect" in ctx.runner.calls[-1]


def test_trufflehog_scans_a_local_folder(ctx: Any) -> None:
    ctx.agent = "mistral"
    ctx.runner.result = subprocess.CompletedProcess([], 0, "no secrets", "")
    toolkit.run(ctx, "trufflehog", "leak.txt")
    cmd = ctx.runner.calls[-1]
    assert cmd[1] == "filesystem" and cmd[2].endswith("leak.txt")
    ctx.agent = "shelby"  # not Syfer's domain
    with pytest.raises(ActionError, match="ton domaine"):
        toolkit.run(ctx, "nmap", "juice-shop")


def test_remote_recon_waits_for_approval(ctx: Any) -> None:
    gate = Gate(ctx.db, auto_max_level=int(Level.WRITE))
    ctx.agent = "mistral"
    answer = tools_mod.execute(gate, ctx, "toolkit", {"name": "nmap", "target": "juice-shop"})
    assert answer.startswith("EN ATTENTE DE VALIDATION")
    assert ctx.runner.calls == []  # never runs a remote scan without the user's go
