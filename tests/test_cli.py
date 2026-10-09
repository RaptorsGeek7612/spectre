"""Tests for spectre.cli: output modes, request sources, usage errors and exit codes."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from langchain_core.language_models import BaseChatModel

from spectre import __version__, cli
from spectre.errors import AgentRefusalError
from spectre.graph import SpectreResult
from spectre.graph import run as real_run
from tests.conftest import RecordingFakeModel, fake, make_ai

FakeFactory = Callable[..., dict[str, RecordingFakeModel]]


@pytest.fixture
def requests_seen(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Route `cli.run` to the real pipeline with priced fake models; record requests."""
    seen: list[str] = []

    def fake_run(
        request: str,
        *,
        models: Mapping[str, BaseChatModel] | None = None,
        max_revisions: int | None = None,
    ) -> SpectreResult:
        seen.append(request)
        fakes = {
            "scout": fake("scout", make_ai("BRIEF"), model="claude-haiku-4-5"),
            "scribe": fake("scribe", make_ai("DRAFT"), model="claude-sonnet-5-5"),
            "warden": fake("warden", make_ai("Texte final é ✓"), model="claude-opus-5-5"),
        }
        return real_run(request, models=fakes)

    monkeypatch.setattr(cli, "run", fake_run)
    return seen


def test_text_output(
    api_key: str, requests_seen: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["Écris un haïku"]) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert out == "Texte final é ✓\n"
    assert err == ""
    assert requests_seen == ["Écris un haïku"]


def test_json_output(
    api_key: str, requests_seen: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--json", "demande"]) == cli.EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["final_text"] == "Texte final é ✓"
    assert data["brief"] == "BRIEF"
    assert [u["agent"] for u in data["usage"]] == ["scout", "scribe", "warden"]
    assert data["total_cost_usd"] is not None


def test_costs_go_to_stderr(
    api_key: str, requests_seen: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--costs", "demande"]) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert out == "Texte final é ✓\n"
    for word in ("Agent", "scout", "scribe", "warden", "Total", "claude-opus-5-5"):
        assert word in err


def test_request_from_file(
    api_key: str, requests_seen: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "demande.txt"
    path.write_text("demande depuis un fichier, accentuée\n", encoding="utf-8")
    assert cli.main(["--file", str(path)]) == cli.EXIT_OK
    assert requests_seen == ["demande depuis un fichier, accentuée\n"]


@pytest.mark.parametrize(
    "argv_factory",
    [
        lambda p: ["demande", "--file", str(p)],  # both sources
        lambda p: [],  # no source
        lambda p: ["   "],  # blank positional
        lambda p: ["--file", str(p.parent / "absent.txt")],  # unreadable file
    ],
    ids=["both", "none", "blank", "missing-file"],
)
def test_usage_errors_exit_2(
    argv_factory: Callable[[Path], list[str]],
    api_key: str,
    requests_seen: list[str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "ok.txt"
    path.write_text("ok", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        cli.main(argv_factory(path))
    assert excinfo.value.code == cli.EXIT_USAGE
    assert "spectre" in capsys.readouterr().err
    assert requests_seen == []


def test_blank_file_is_usage_error(api_key: str, requests_seen: list[str], tmp_path: Path) -> None:
    path = tmp_path / "vide.txt"
    path.write_text(" \n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--file", str(path)])
    assert excinfo.value.code == cli.EXIT_USAGE


def test_missing_api_key_exit_1(
    requests_seen: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["demande"]) == cli.EXIT_ERROR
    out, err = capsys.readouterr()
    assert out == ""
    assert "ANTHROPIC_API_KEY" in err
    assert requests_seen == []


def test_spectre_error_exit_1(
    api_key: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_run(request: str, **_: object) -> SpectreResult:
        raise AgentRefusalError("warden")

    monkeypatch.setattr(cli, "run", failing_run)
    assert cli.main(["demande"]) == cli.EXIT_ERROR
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("Erreur : [warden]")


def test_ctrl_c_exit_130(
    api_key: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupted_run(request: str, **_: object) -> SpectreResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run", interrupted_run)
    assert cli.main(["demande"]) == cli.EXIT_INTERRUPTED == 130
    out, err = capsys.readouterr()
    assert out == ""
    assert err.strip() == "Interrompu."


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"spectre {__version__}"


def test_main_loads_env_before_checking_key(
    monkeypatch: pytest.MonkeyPatch, requests_seen: list[str]
) -> None:
    monkeypatch.setattr(cli, "load_env", lambda: monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x"))
    assert cli.main(["demande"]) == cli.EXIT_OK
    assert requests_seen == ["demande"]


# ---- v0.4: streaming and revision rounds --------------------------------------------------

REJECT = 'V1\n=== VERDICT ===\n{"approved": false, "issues": ["Plus court"]}'


@pytest.fixture
def streamed(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Route `cli.stream_run` to the real stream with fake models; record its arguments."""
    from spectre.web import pipeline

    seen: dict[str, object] = {}

    def fake_stream(request: str, **kwargs: object) -> object:
        seen.update(kwargs, request=request)
        models = {
            "scout": fake("scout", make_ai("BRIEF")),
            "scribe": fake("scribe", make_ai("D1"), make_ai("D2")),
            "warden": fake("warden", make_ai(REJECT), make_ai("FINAL\n=== VERDICT ===\n{}")),
        }
        return pipeline.stream_run(request, demo=False, models=models, max_revisions=1)

    monkeypatch.setattr(cli, "stream_run", fake_stream)
    return seen


def test_stream_shows_each_agent_and_the_revision(
    api_key: str, streamed: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--stream", "--revisions", "1", "Un poème"]) == 0
    out, err = capsys.readouterr()
    assert out.strip() == "FINAL"  # not a terminal: the final text still goes to stdout
    for header in ("── Scout ──", "── Scribe ──", "── Warden ──", "── Scribe (révision 1) ──"):
        assert header in err
    assert "── Warden (révision 1) ──" in err and "VERDICT" not in err
    assert streamed["max_revisions"] == 1 and streamed["demo"] is False


def test_stream_json_and_terminal_output(
    api_key: str,
    streamed: dict[str, object],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert cli.main(["--stream", "--json", "x"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert (data["approved"], data["revisions"], data["final_text"]) == (True, 1, "FINAL")
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True)
    assert cli.main(["--stream", "x"]) == 0
    assert capsys.readouterr().out == ""  # already on screen through stderr


def test_stream_error_exit_1(
    api_key: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli, "stream_run", lambda request, **kw: iter([{"type": "error", "message": "refus"}])
    )
    assert cli.main(["--stream", "x"]) == 1
    assert "refus" in capsys.readouterr().err


def test_unapproved_text_warns(
    api_key: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    def rejected_run(request: str, **kwargs: object) -> SpectreResult:
        seen.update(kwargs)
        models = {
            "scout": fake("scout", make_ai("B")),
            "scribe": fake("scribe", make_ai("D")),
            "warden": fake("warden", make_ai(REJECT)),
        }
        return real_run(request, models=models, max_revisions=0)

    monkeypatch.setattr(cli, "run", rejected_run)
    assert cli.main(["--revisions", "0", "x"]) == 0
    out, err = capsys.readouterr()
    assert out.strip() == "V1" and "n'a pas validé" in err and "Plus court" in err
    assert seen["max_revisions"] == 0


def test_revisions_out_of_range_is_usage_error(api_key: str) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--revisions", "9", "x"])
    assert exc.value.code == 2
