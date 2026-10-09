"""The ChatGPT (Codex CLI) and Mistral (Vibe CLI) execution agents, and how missions choose."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.assistant import codex, missions, mistral, tools
from spectre.assistant.brain import Reply
from spectre.assistant.codex import CodexCLI, find_codex
from spectre.assistant.config import AssistantConfig, agent_name, resolve_agent
from spectre.assistant.db import Database
from spectre.assistant.missions import MissionEngine
from spectre.assistant.mistral import VibeCLI, vibe_command
from tests.test_assistant_brain import FakeCLI


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "spectre.db")


def _runner(returncode: int = 0, stdout: str = "", stderr: str = "") -> Any:
    return lambda cmd, **kw: SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _missing(cmd: list[str], **kw: Any) -> Any:
    raise FileNotFoundError


def _slow(cmd: list[str], **kw: Any) -> Any:
    raise subprocess.TimeoutExpired(cmd, 1)


# ---- ChatGPT (Codex CLI) -------------------------------------------------------------------


def test_find_codex_prefers_the_native_exe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shim = tmp_path / "codex.cmd"
    shim.write_text("@echo off", encoding="utf-8")
    monkeypatch.setattr(codex.shutil, "which", lambda name: str(shim))
    assert find_codex("codex") == str(shim)  # no native binary next to it
    exe = tmp_path / codex.NATIVE / "vendor" / "x86_64-pc-windows-msvc" / "bin" / "codex.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert find_codex("codex") == str(exe)
    monkeypatch.setattr(codex.shutil, "which", lambda name: None)
    assert find_codex("/opt/codex.exe") == "/opt/codex.exe"  # not on PATH: used as given


def test_codex_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codex, "find_codex", lambda name: name)
    cli = CodexCLI(AssistantConfig(chatgpt_model="gpt-5.5"), tmp_path)
    cmd = cli.command(system='Tu es "Spectre".\nLigne 2', output=tmp_path / "o", with_tools=True)
    assert cmd[:2] == ["codex", "exec"] and cmd[-1] == "-"
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[cmd.index("-m") + 1] == "gpt-5.5"
    assert cmd[cmd.index("-C") + 1] == str(tmp_path / "workspace")
    assert 'developer_instructions="Tu es \\"Spectre\\".\\nLigne 2"' in cmd
    assert 'web_search="live"' in cmd and 'approval_policy="never"' in cmd
    assert f"mcp_servers.spectre.command={json.dumps(sys.executable)}" in cmd
    env = f"mcp_servers.spectre.env={{SPECTRE_ASSISTANT_DIR = {json.dumps(str(tmp_path))}}}"
    assert env in cmd
    plain = CodexCLI(AssistantConfig(), tmp_path).command(
        system="s", output=tmp_path / "o", with_tools=False
    )
    assert 'web_search="disabled"' in plain and "-m" not in plain
    assert not any(part.startswith("mcp_servers") for part in plain)


def test_codex_ask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen: dict[str, Any] = {}

    def ok(cmd: list[str], **kw: Any) -> Any:
        seen.update(kw)
        Path(cmd[cmd.index("-o") + 1]).write_text("  fait : rapport.md  \n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    reply = CodexCLI(AssistantConfig(), tmp_path, runner=ok).ask("étape", system="s")
    assert reply == Reply("fait : rapport.md", "", False)
    assert seen["input"] == "étape" and "OPENAI_API_KEY" not in seen["env"]
    for runner, words in (
        (_runner(1, stderr="démarrage\nERROR: not logged in\n"), "not logged in"),
        (_runner(0), "réponse vide"),
        (_missing, "Codex"),
        (_slow, "à temps"),
    ):
        reply = CodexCLI(AssistantConfig(), tmp_path, runner=runner).ask("x", system="s")
        assert reply.is_error and words in reply.text


# ---- Mistral (Vibe CLI) --------------------------------------------------------------------


def test_vibe_command_runs_the_launcher_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "vibe.exe"
    exe.write_bytes(b"MZ launcher #!C:\\Python314\\python.exe\nPK\x03\x04zip")
    monkeypatch.setattr(mistral.shutil, "which", lambda name: str(exe))
    assert vibe_command("vibe") == ["C:\\Python314\\python.exe", "-c", mistral.LAUNCH]
    exe.write_bytes(b"MZ no interpreter")
    assert vibe_command("vibe") == [str(exe)]
    monkeypatch.setattr(mistral.shutil, "which", lambda name: "/usr/bin/vibe")
    assert vibe_command("vibe") == ["/usr/bin/vibe"]
    monkeypatch.setattr(mistral.shutil, "which", lambda name: None)
    absent = str(tmp_path / "absent" / "vibe.exe")
    assert vibe_command(absent) == [absent]  # unreadable: used as given


def test_vibe_home_and_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mistral, "vibe_command", lambda name: [name])
    cli = VibeCLI(AssistantConfig(mistral_model="mistral-medium-3.5"), tmp_path)
    cli.write_home("Tu es Spectre.")
    assert (cli.home / "prompts" / "spectre.md").read_text(encoding="utf-8") == "Tu es Spectre."
    config = (cli.home / "config.toml").read_text(encoding="utf-8")
    assert 'system_prompt_id = "spectre"' in config
    assert 'active_model = "mistral-medium-3.5"' in config
    assert f"command = {json.dumps(sys.executable)}" in config and 'name = "spectre"' in config
    default = VibeCLI(AssistantConfig(), tmp_path / "b")
    default.write_home("s")
    assert "active_model" not in (default.home / "config.toml").read_text(encoding="utf-8")
    cmd = cli.command(with_tools=True)
    assert cmd[0] == "vibe" and cmd[-1] == "-p" and "--auto-approve" in cmd
    enabled = [cmd[i + 1] for i, part in enumerate(cmd) if part == "--enabled-tools"]
    assert enabled == ["spectre_*", "web_search", "web_fetch"]
    assert cmd[cmd.index("--workdir") + 1] == str(tmp_path / "workspace")
    plain = cli.command(with_tools=False)
    assert [plain[i + 1] for i, p in enumerate(plain) if p == "--enabled-tools"] == ["aucun-outil"]
    assert cli.env()["VIBE_HOME"] == str(cli.home)


def test_vibe_ask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mistral, "vibe_command", lambda name: [name])
    seen: dict[str, Any] = {}

    def ok(cmd: list[str], **kw: Any) -> Any:
        seen.update(kw)
        return SimpleNamespace(returncode=0, stdout="\nfait par Mistral\n", stderr="")

    reply = VibeCLI(AssistantConfig(), tmp_path, runner=ok).ask("étape", system="règles")
    assert reply == Reply("fait par Mistral", "", False)
    assert seen["input"] == "étape" and seen["env"]["VIBE_HOME"] == str(tmp_path / "vibe")
    for runner, words in (
        (_runner(1, stderr="Missing MISTRAL_API_KEY\n"), "MISTRAL_API_KEY"),
        (_runner(0), "réponse vide"),
        (_missing, "Vibe"),
        (_slow, "à temps"),
    ):
        reply = VibeCLI(AssistantConfig(), tmp_path, runner=runner).ask("x", system="s")
        assert reply.is_error and words in reply.text


# ---- which agent runs a mission ------------------------------------------------------------


def _queue(db: Database, plan: dict[str, Any]) -> int:
    return db.execute(
        "INSERT INTO missions(ts, goal, status, plan, updated_at) "
        "VALUES('t', 'But', 'queued', ?, 't')",
        (json.dumps(plan),),
    )


def _steps(db: Database, mid: int) -> list[dict[str, Any]]:
    row = db.one("SELECT steps FROM missions WHERE id = ?", (mid,))
    assert row is not None
    return list(json.loads(row["steps"]))


def test_mission_steps_by_chatgpt_setting(db: Database, tmp_path: Path) -> None:
    claude = FakeCLI(tmp_path, '{"ok": true}', "rapport", "fait par Claude", '{"ok": true}', "r")
    gpt = FakeCLI(tmp_path, "fait par ChatGPT")
    engine = MissionEngine(
        db,
        claude,  # type: ignore[arg-type]
        lambda *a: None,
        model="chatgpt",
        agents={"chatgpt": gpt},
    )
    mid = _queue(db, {"kind": "mission", "steps": ["unique"]})
    engine.run_next()
    assert gpt.calls[0]["tools"] is True and gpt.calls[0]["model"] == "chatgpt"
    assert claude.calls[0]["model"] == "haiku"  # the verifier stays Claude
    assert _steps(db, mid)[0]["agent"] == "chatgpt"
    assert gpt.calls[0]["system"].startswith("Tu es Kyra,")  # ChatGPT's name...
    assert "multimédia" in gpt.calls[0]["system"]  # ...and specialty
    assert _steps(db, mid)[0]["name"] == "Kyra"
    report_prompt = claude.calls[1]["prompt"]
    assert "Étape 1 (Kyra)" in report_prompt and "Vérification (Kaïto)" in report_prompt
    assert claude.calls[0]["system"].startswith("Tu es Kaïto,")  # the verifier
    # agent=claude for one mission overrides the setting (Sonnet stands in for "chatgpt")
    mid = _queue(db, {"kind": "mission", "steps": ["unique"], "agent": "claude"})
    engine.run_next()
    assert _steps(db, mid)[0]["agent"] == "sonnet" and len(gpt.calls) == 1
    assert claude.calls[2]["system"] == missions.WORKER.format(name="Gétro")  # no specialty


def test_mission_agent_override_and_lazy_creation(
    db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude = FakeCLI(tmp_path, '{"steps": ["a"]}', '{"ok": true}', "rapport")
    claude.config, claude.root = AssistantConfig(), tmp_path  # type: ignore[attr-defined]
    made: list[Any] = []

    def fake_vibe(config: AssistantConfig, root: Path) -> FakeCLI:
        made.append((config, root))
        return FakeCLI(tmp_path, "fait par Mistral")

    monkeypatch.setitem(missions.EXTERNAL, "mistral", fake_vibe)
    engine = MissionEngine(db, claude, lambda *a: None, model="sonnet")  # type: ignore[arg-type]
    mid = _queue(db, {"kind": "mission", "agent": "mistral"})
    engine.run_next()
    assert made == [(claude.config, tmp_path)]  # type: ignore[attr-defined]
    row = db.one("SELECT plan FROM missions WHERE id = ?", (mid,))
    assert row and json.loads(row["plan"]) == {
        "kind": "mission",
        "steps": ["a"],
        "agent": "mistral",
    }
    assert _steps(db, mid)[0]["agent"] == "mistral"
    system = engine.agents["mistral"].calls[0]["system"]
    assert system.startswith("Tu es Syfer,") and "autorisation écrite" in system
    # an unknown agent falls back to the setting
    claude.replies += ["fait", '{"ok": true}', "rapport"]
    mid = _queue(db, {"kind": "mission", "steps": ["b"], "agent": "gemini"})
    engine.run_next()
    assert _steps(db, mid)[0]["agent"] == "sonnet" and len(made) == 1


def test_start_mission_records_the_agent(db: Database, tmp_path: Path) -> None:
    ctx = tools.make_context(db, tmp_path, [str(tmp_path)])
    for agent, expected in (
        ("chatgpt", "chatgpt"),
        ("Kyra", "chatgpt"),
        ("SYFER", "mistral"),
        ("Getro", "sonnet"),
        ("kaïto", "haiku"),
        ("claude", "claude"),
        ("gemini", None),
    ):
        answer = tools._start_mission(ctx, "Résumer", agent=agent)
        mid = int(answer.split("#")[1].split()[0])
        row = db.one("SELECT plan FROM missions WHERE id = ?", (mid,))
        assert row and json.loads(row["plan"]).get("agent") == expected
        assert ("confiée à" in answer) == (expected not in (None, "claude"))
    assert "confiée à Syfer" in tools._start_mission(ctx, "Audit", agent="mistral")


def test_agent_names() -> None:
    assert [agent_name(m) for m in ("sonnet", "haiku", "chatgpt", "mistral", "opus")] == [
        "Gétro",
        "Kaïto",
        "Kyra",
        "Syfer",
        "Spectre",
    ]
    assert agent_name("autre") == "autre" and resolve_agent("  ") == ""


def test_mission_by_haiku_named_agent(db: Database, tmp_path: Path) -> None:
    claude = FakeCLI(tmp_path, "fait vite", '{"ok": true}', "rapport")
    engine = MissionEngine(db, claude, lambda *a: None, model="sonnet")  # type: ignore[arg-type]
    mid = _queue(db, {"kind": "mission", "steps": ["vite"], "agent": "haiku"})
    engine.run_next()
    assert claude.calls[0]["model"] == "haiku" and _steps(db, mid)[0]["name"] == "Kaïto"
