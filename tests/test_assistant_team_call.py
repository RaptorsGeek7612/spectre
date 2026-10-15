"""v0.17: Octavya, Clarke and Simon, an engine per agent, the team page, the video call over
Spectre's own activity and over the Claude Code, Codex and Vibe sessions, portraits, Laya."""

from __future__ import annotations

import http.client
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import activity, call, cli_agents, engines, laya, runctx, sessions, team
from spectre.assistant import tools as tools_mod
from spectre.assistant.config import AssistantConfig, agent_name, resolve_agent
from spectre.assistant.custom_agents import CustomAgents
from spectre.assistant.db import Database, now_iso
from spectre.assistant.providers import Providers
from spectre.assistant.service import AssistantService
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def db(tmp_path: Path) -> Any:
    database = Database(tmp_path / "a.db")
    yield database
    database.close()


# ---- the new agents and their engines ------------------------------------------------------------


def test_new_agents_and_aliases() -> None:
    assert [agent_name(k) for k in ("cursor", "antigravity", "kimi")] == [
        "Octavya",
        "Clarke",
        "Simon",
    ]
    assert resolve_agent("codex") == "chatgpt" and resolve_agent("Vibe") == "mistral"
    assert resolve_agent("octavya") == "cursor" and resolve_agent("agy") == "antigravity"
    assert Providers(Path(".")).check("Codex") == "chatgpt"


def test_an_agent_moved_to_another_engine() -> None:
    config = AssistantConfig(agent_engines={"kimi": "deepseek:deepseek-chat", "cursor": "kimi"})
    assert engines.resolve(config, "kimi") == "deepseek:deepseek-chat"
    assert engines.resolve(config, "cursor") == "cursor"  # never another agent's tool
    assert engines.resolve(config, "sonnet") == "sonnet"

    class Cli:
        def __init__(self) -> None:
            self.config = config
            self.root = Path(".")

    pool = engines.Engines(Cli(), agents={"http": "HTTP"})
    assert pool.worker("kimi") == ("HTTP", "deepseek:deepseek-chat")


class Runner:
    def __init__(self, stdout: str = "Réponse.", returncode: int = 0, stderr: str = "") -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = subprocess.CompletedProcess([], returncode, stdout, stderr)

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({"cmd": cmd, **kw})
        return self.result


def test_cursor_agent_runs_with_only_spectre_tools(tmp_path: Path) -> None:
    runner = Runner()
    config = AssistantConfig(cursor_model="gpt-5.3-codex")
    agent = cli_agents.CursorCLI(config, tmp_path, runner)
    with runctx.scope(agent="cursor"):
        reply = agent.ask("Rédige les CGV", system="Tu es Octavya.")
    assert reply.text == "Réponse." and not reply.is_error
    call_ = runner.calls[0]
    assert "-p" in call_["cmd"] and "--approve-mcps" in call_["cmd"]
    assert call_["cmd"][call_["cmd"].index("--model") + 1] == "gpt-5.3-codex"
    assert "Tu es Octavya." in call_["input"] and "Rédige les CGV" in call_["input"]
    folder = tmp_path / "agents" / "cursor" / ".cursor"
    servers = json.loads((folder / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert servers["spectre"]["env"]["SPECTRE_AGENT"] == "cursor"
    permissions = json.loads((folder / "cli.json").read_text(encoding="utf-8"))["permissions"]
    assert "Shell(*)" in permissions["deny"] and "Write(**)" in permissions["deny"]
    assert "--mode" in agent.command("x", with_tools=False)[0]


def test_cli_agents_explain_their_failures(tmp_path: Path) -> None:
    quota = Runner("", 1, "ActionRequiredError: You've hit your usage limit")
    reply = cli_agents.CursorCLI(AssistantConfig(), tmp_path, quota).ask("x", system="s")
    assert reply.is_error and "limite d'utilisation" in reply.text
    agy = Runner("", 1, 'AGY_ERROR: {"status":"RESOURCE_EXHAUSTED"}')
    assert (
        "limite"
        in cli_agents.AntigravityCLI(AssistantConfig(), tmp_path, agy).ask("x", system="s").text
    )
    login = Runner("", 1, "401 Unauthorized")
    assert (
        "connecte-toi"
        in cli_agents.KimiCLI(AssistantConfig(), tmp_path, login).ask("x", system="s").text
    )

    def missing(*a: Any, **k: Any) -> Any:
        raise FileNotFoundError

    assert (
        "Je ne trouve pas"
        in cli_agents.KimiCLI(AssistantConfig(), tmp_path, missing).ask("x", system="s").text
    )

    def slow(*a: Any, **k: Any) -> Any:
        raise subprocess.TimeoutExpired("x", 1)

    assert (
        "à temps"
        in cli_agents.AntigravityCLI(AssistantConfig(), tmp_path, slow).ask("x", system="s").text
    )


def test_antigravity_and_kimi_commands(tmp_path: Path) -> None:
    config = AssistantConfig(antigravity_model="gemini-3.8-flash-low", kimi_model="kimi-code/k3")
    runner = Runner()
    cli_agents.AntigravityCLI(config, tmp_path, runner).ask("Budget", system="Tu es Clarke.")
    cmd = runner.calls[0]["cmd"]
    assert (
        cmd[-2] == "-p"
        and "Budget" in cmd[-1]
        and "--sandbox" in cmd
        and "gemini-3.8-flash-low" in cmd
    )
    assert (tmp_path / "agents" / "antigravity" / ".agents" / "mcp_config.json").is_file()
    kimi = cli_agents.KimiCLI(config, tmp_path, runner)
    kimi.ask("TVA", system="Tu es Simon.")
    assert runner.calls[1]["cmd"][1:3] == ["-m", "kimi-code/k3"]
    assert runner.calls[1]["env"]["KIMI_CODE_TRUST_WORKSPACE"] == "1"
    rules = (tmp_path / "agents" / "kimi" / ".kimi-code" / "local.toml").read_text(encoding="utf-8")
    assert 'pattern = "Bash"' in rules and 'decision = "deny"' in rules


def test_find_cursor_prefers_its_bundled_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = tmp_path / "cursor-agent.cmd"
    launcher.write_text("@echo off", encoding="utf-8")
    version = tmp_path / "versions" / "2026.10.01-abc"
    version.mkdir(parents=True)
    (version / "node.exe").write_bytes(b"")
    (version / "index.js").write_text("", encoding="utf-8")
    monkeypatch.setattr(cli_agents.shutil, "which", lambda name: str(launcher))
    assert cli_agents.find_cursor("cursor-agent") == [
        str(version / "node.exe"),
        str(version / "index.js"),
    ]


def test_model_lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = "Available models\n\nauto - Auto (current, default)\ngpt-5.2 - GPT-5.2\nnoise\n"
    assert cli_agents.parse_cursor_models(text) == [
        {"id": "auto", "label": "Auto"},
        {"id": "gpt-5.2", "label": "GPT-5.2"},
    ]
    assert cli_agents.parse_agy_models(
        "Fetching…\ngemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
    ) == [{"id": "gemini-3.8-flash-high", "label": "Gemini 3.8 Flash (High)"}]
    (tmp_path / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {"slug": "gpt-6-luna", "display_name": "GPT-6-Luna"},
                    {"slug": "x", "visibility": "hide"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert cli_agents.codex_models(tmp_path) == [{"id": "gpt-6-luna", "label": "GPT-6-Luna"}]
    cli_agents._cache.clear()
    monkeypatch.setattr(cli_agents, "_run", lambda cmd, env=None: "auto - Auto\n")
    assert cli_agents.models("cursor", AssistantConfig())[0]["id"] == "auto"
    assert cli_agents.models("kimi", AssistantConfig())[0]["id"] == "kimi-code/k3"
    cli_agents._cache.clear()


# ---- activity, the gate and the call -------------------------------------------------------------


def test_gate_records_activity_and_lead_only_skills(db: Database, tmp_path: Path) -> None:
    from spectre.assistant.governance import Gate

    folder = tmp_path / "home"
    folder.mkdir()
    ctx = tools_mod.make_context(db, tmp_path / "assistant", [str(folder)])
    gate = Gate(db)
    (folder / "a.txt").write_text("bonjour", encoding="utf-8")
    ctx.agent = "cursor"
    tools_mod.execute(gate, ctx, "read_file", {"path": str(folder / "a.txt")})
    row = db.one("SELECT * FROM activity WHERE kind = 'tool'")
    assert row and row["agent"] == "cursor" and row["status"] == "ok"
    assert json.loads(row["detail"])["target"].endswith("a.txt")
    refused = tools_mod.execute(gate, ctx, "laya_decide", {"state": "x", "questions": "{}"})
    assert refused.startswith("REFUSÉ")
    ctx.agent = ""
    answer = tools_mod.execute(gate, ctx, "laya_decide", {"state": "x", "questions": "{}"})
    assert answer.startswith("ÉCHEC") and "questions" in answer


def _day(db: Database) -> int:
    mid = db.execute(
        "INSERT INTO missions(ts, goal, status, plan, updated_at) "
        "VALUES(?, 'Bêta', 'running', '{}', ?)",
        (now_iso(), now_iso()),
    )
    with runctx.scope(mission=mid):
        activity.record(db, "mission_start", agent="opus", title="Bêta")
        activity.record(db, "step_start", agent="antigravity", title="Prévisionnel")
        activity.record(
            db, "step_done", agent="antigravity", title="Prévisionnel", status="ok", seconds=12
        )
        activity.record(db, "step_start", agent="cursor", title="CGV")
        activity.tool_started(db, "cursor", mid, "web_search", {"query": "CGV SaaS"})
        failing = activity.tool_started(db, "mistral", mid, "lab_run", {"command": "nmap"})
        activity.tool_finished(
            db, failing, "lab_run", {"command": "nmap"}, "ÉCHEC : labo éteint", 0
        )
        aid = db.execute(
            "INSERT INTO approvals(ts, tool, args, level, category, reason) "
            "VALUES(?, 'write_file', '{}', 2, 'write', 'r')",
            (now_iso(),),
        )
        db.execute("INSERT INTO approval_agents(approval_id, agent) VALUES(?, 'kimi')", (aid,))
        activity.record(
            db,
            "approval",
            agent="kimi",
            title="write_file",
            detail=json.dumps({"target": "tva.xlsx"}),
            status="pending",
        )
    db.execute(
        "INSERT INTO usage_ledger(ts, agent, engine, tokens, cost_usd) "
        "VALUES(?, 'cursor', 'cursor', 4000, 0.2)",
        (now_iso(),),
    )
    return mid


def test_statuses_lines_and_snapshot(db: Database) -> None:
    mid = _day(db)
    found = {s["key"]: s for s in call.statuses(db)}
    assert found["kimi"]["status"] == "needs_you" and "write_file" in found["kimi"]["activity"]
    assert found["cursor"]["status"] == "working" and found["cursor"]["activity"].startswith(
        "web_search"
    )
    assert found["cursor"]["tokens"] == 4000
    assert found["antigravity"]["status"] == "done"
    assert found["opus"]["status"] == "waiting" and "Octavya" in found["opus"]["activity"]
    assert found["mistral"]["fails"] == 1
    assert call.statuses(db)[0]["key"] == "opus"
    first = call.snapshot(db)
    assert first["lines"] == [] and first["needs_you"] == 1 and first["screen"]["tool"] == "lab_run"
    later = call.snapshot(db, since=1, since_event=0)
    said = [(line["agent"], line["text"]) for line in later["lines"]]
    assert ("antigravity", "C'est pour moi : Prévisionnel.") in said or any(
        a == "antigravity" for a, _ in said
    )
    assert any(a == "haiku" and "rifi" in t or "Contrôl" in t or "confirme" in t for a, t in said)
    assert any(a == "kimi" and "accord" in t for a, t in said)
    assert any(a == "mistral" and "labo éteint" in t for a, t in said)
    replay = call.replay(db, mid)
    assert replay["mission"]["goal"] == "Bêta" and replay["tools"]
    assert {h["label"] for h in replay["highlights"]} >= {
        "première erreur",
        "attente de ton accord",
    }


def test_standup_recap_tree_board(db: Database) -> None:
    mid = _day(db)
    lines = call.standup(db)
    text = {line["agent"]: line["text"] for line in lines}
    assert lines[0]["agent"] == "opus" and "tour de table" in lines[0]["text"]
    assert "Prévisionnel" in text["antigravity"]
    assert "j'attends ton accord pour write_file" in text["kimi"]
    assert text["sonnet"] == "Rien pour moi depuis hier, je suis disponible."
    assert "1 étape" in text["haiku"]
    assert "attend ton accord" in lines[-1]["text"]
    markdown = call.recap(db)
    assert (
        markdown.startswith("# Point d'équipe")
        and "**Clarke**" in markdown
        and "Missions" in markdown
    )
    assert call.recap(db, mission=mid).startswith(f"# Compte rendu de la mission #{mid}")
    tree = call.tree(db)
    assert tree["missions"][0]["mission"] == mid
    assert {a["name"] for a in tree["missions"][0]["agents"]} >= {"Clarke", "Octavya"}
    board = call.board(db)
    assert board[0]["state"] == "needs_you" and "Clarke" in board[0]["agents"]


def test_created_agents_join_the_call(db: Database) -> None:
    CustomAgents(db).create("Nova", "sonnet", "Ressources humaines")
    members = call.members(db)
    assert members[-1]["name"] == "Nova" and members[-1]["created"] is True


# ---- other tools' sessions -----------------------------------------------------------------------


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_sessions_of_claude_code_codex_and_vibe(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    ts = (now - timedelta(seconds=30)).isoformat()
    old = (now - timedelta(seconds=90)).isoformat()
    roots = sessions.Roots(tmp_path / "claude", tmp_path / "codex", [tmp_path / "vibe"])
    _jsonl(
        roots.claude / "proj" / "s1.jsonl",
        [
            {
                "type": "user",
                "timestamp": old,
                "cwd": "C:/proj",
                "message": {"content": "Corrige le bug"},
            },
            {
                "type": "assistant",
                "timestamp": old,
                "message": {
                    "model": "claude",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "content": [
                        {"type": "text", "text": "Je regarde."},
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Agent",
                            "input": {"description": "Lire le code"},
                        },
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": old,
                "message": {
                    "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "Lu."}]
                },
            },
            {
                "type": "assistant",
                "timestamp": ts,
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t2",
                            "name": "Edit",
                            "input": {"file_path": "a.py"},
                        }
                    ]
                },
            },
        ],
    )
    _jsonl(
        roots.claude / "proj" / "s1" / "subagents" / "agent-x.jsonl",
        [
            {"type": "user", "timestamp": old, "message": {"content": "Lire le code"}},
            {
                "type": "assistant",
                "timestamp": old,
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "r1",
                            "name": "Read",
                            "input": {"file_path": "b.py"},
                        }
                    ]
                },
            },
        ],
    )
    (roots.claude / "proj" / "s1" / "subagents" / "agent-x.meta.json").write_text(
        json.dumps({"description": "Lecteur", "toolUseId": "t1"}), encoding="utf-8"
    )
    codex_day = roots.codex / "2026" / "10" / "15"
    _jsonl(
        codex_day / "rollout-a.jsonl",
        [
            {
                "timestamp": ts,
                "type": "session_meta",
                "payload": {"session_id": "S", "id": "S", "cwd": "C:/web"},
            },
            {
                "timestamp": ts,
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Fais le logo"}],
                },
            },
            {
                "timestamp": ts,
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "shell",
                    "arguments": '{"cmd": "ls"}',
                    "call_id": "c1",
                },
            },
            {
                "timestamp": ts,
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": {"total_tokens": 900}},
                },
            },
        ],
    )
    _jsonl(
        codex_day / "rollout-b.jsonl",
        [
            {
                "timestamp": ts,
                "type": "session_meta",
                "payload": {
                    "session_id": "S",
                    "id": "T",
                    "thread_source": "subagent",
                    "agent_nickname": "Euler",
                },
            },
            {
                "timestamp": ts,
                "type": "event_msg",
                "payload": {"type": "task_complete", "last_agent_message": "Terminé."},
            },
        ],
    )
    _jsonl(
        codex_day / "rollout-c.jsonl",
        [
            {
                "timestamp": ts,
                "type": "session_meta",
                "payload": {"session_id": "S", "id": "G", "thread_source": "guardian_review"},
            },
        ],
    )
    vibe = roots.vibe[0] / "session_1"
    vibe.mkdir(parents=True)
    (vibe / "meta.json").write_text(
        json.dumps(
            {
                "session_id": "V",
                "start_time": old,
                "end_time": ts,
                "environment": {"working_directory": "C:/v"},
            }
        ),
        encoding="utf-8",
    )
    _jsonl(
        vibe / "messages.jsonl",
        [
            {"role": "user", "content": "Audit", "injected": False},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "v1", "function": {"name": "bash", "arguments": '{"command": "nmap"}'}}
                ],
            },
            {"role": "tool", "content": "ok", "tool_call_id": "v1"},
            {"role": "assistant", "content": "Rien d'alarmant."},
        ],
    )
    found = {s["tool"]: s for s in sessions.scan(roots, now=now)}
    claude = found["claude"]
    assert claude["title"] == "Corrige le bug" and claude["project"] == "C:/proj"
    names = {a["name"]: a for a in claude["agents"]}
    assert names["Claude"]["status"] == "needs_you" and "Edit" in names["Claude"]["activity"]
    assert names["Lecteur"]["status"] == "done" and names["Claude"]["tokens"] == 15
    codex = found["codex"]
    assert [a["name"] for a in codex["agents"]] == ["Codex", "Euler"]
    assert codex["agents"][0]["tokens"] == 900 and codex["state"] == "working"
    assert found["vibe"]["title"] == "Audit" and found["vibe"]["agents"][0]["status"] == "your_turn"
    assert "events" not in claude and claude["label"] == "Claude Code"
    full = sessions.timeline(roots, "codex", "S", now=now)
    assert full and any(e["kind"] == "report" for e in full["events"])
    assert sessions.timeline(roots, "nope", "S") is None
    assert sessions.timeline(roots, "vibe", "absent") is None


# ---- the team page -------------------------------------------------------------------------------


def test_team_changes(db: Database, tmp_path: Path) -> None:
    config = AssistantConfig()
    providers = Providers(tmp_path)
    members = {m["key"]: m for m in team.members(db, config)}
    assert members["antigravity"]["gender"] == "f" and members["antigravity"]["voice"] == "siwis"
    assert (
        members["chatgpt"]["tool"] == "Codex" and members["opus"]["role_setting"] == "brain_model"
    )
    assert team.change(db, config, providers, "kimi", {"engine": "deepseek:deepseek-chat"}) == {
        "agent_engines": {"kimi": "deepseek:deepseek-chat"}
    }
    with pytest.raises(team.TeamError, match="emprunter"):
        team.change(db, config, providers, "kimi", {"engine": "cursor"})
    config.update({"agent_engines": {"kimi": "deepseek:deepseek-chat"}})
    assert team.change(db, config, providers, "kimi", {"engine": "kimi"}) == {"agent_engines": {}}
    assert team.change(db, config, providers, "opus", {"engine": "sonnet"}) == {
        "brain_model": "sonnet"
    }
    assert team.change(db, config, providers, "cursor", {"model": "auto"}) == {
        "cursor_model": "auto"
    }
    with pytest.raises(team.TeamError):
        team.change(db, config, providers, "opus", {"model": "x"})
    with pytest.raises(team.TeamError):
        team.change(db, config, providers, "cursor", {"voice": "inconnue"})
    assert team.change(db, config, providers, "cursor", {"voice": "tom"}) == {
        "agent_voices": {"cursor": "tom"}
    }
    nova = CustomAgents(db, providers).create("Nova", "sonnet", "RH")
    team.change(db, config, providers, f"agent:{nova['id']}", {"engine": "haiku"})
    assert CustomAgents(db).get("Nova")["engine"] == "haiku"
    with pytest.raises(team.TeamError):
        team.change(db, config, providers, "inconnu", {"engine": "haiku"})


def test_looks_and_portraits(db: Database, tmp_path: Path) -> None:
    config = AssistantConfig()
    providers = Providers(tmp_path)
    changes = team.change(
        db,
        config,
        providers,
        "kimi",
        {"look": {"g": "f", "hair": "#AA0000", "style": "bob", "outfit_kind": "tie", "jewel": 1}},
    )
    look = changes["agent_looks"]["kimi"]
    assert (
        look["hair"] == "#aa0000"
        and look["tie"] is True
        and look["blazer"] is False
        and look["jewel"] is True
    )
    for bad in ({"style": "mohawk"}, {"hair": "red"}, {"wings": True}, "x"):
        with pytest.raises(team.TeamError):
            team.change(db, config, providers, "kimi", {"look": bad})
    config.update(changes)
    assert {m["key"]: m for m in team.members(db, config)}["kimi"]["gender"] == "f"
    assert team.change(db, config, providers, "kimi", {"look": {}}) == {"agent_looks": {}}
    team.save_portrait(tmp_path, "agent:3", PNG)
    assert team.portrait(tmp_path, "agent:3") == (PNG, "image/png")
    assert team.portraits(tmp_path) == {"agent-3"}
    with pytest.raises(team.TeamError):
        team.save_portrait(tmp_path, "kimi", b"GIF89a")
    team.delete_portrait(tmp_path, "agent:3")
    assert team.portrait(tmp_path, "agent:3") is None


def test_team_details(db: Database) -> None:
    _day(db)
    found = team.details(db, AssistantConfig(), "cursor")
    assert "Octavya" in found["prompt"] and found["tools"] == {"web_search": 1}
    assert found["recent"][0]["kind"] == "tool"


# ---- Laya ----------------------------------------------------------------------------------------


QUESTIONS = {
    "agent": {
        "type": "choice",
        "instructions": "Qui ?",
        "criteria": {"juridique": "contrats", "compta": "TVA"},
    },
    "urgence": {"type": "score", "instructions": "Urgent ?", "criteria": ["non", "oui"]},
    "risque": {"type": "noul", "instructions": "Il y a un risque"},
}


def test_laya_checks_and_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    for bad, words in (
        ("[", "JSON"),
        ({}, "objet"),
        ({"q": {"type": "x"}}, "type"),
        ({"q": {"type": "noul"}}, "instructions"),
        ({"q": {"type": "choice", "instructions": "i", "criteria": {"a": "a"}}}, "deux"),
        ({"q": {"type": "score", "instructions": "i", "criteria": ["a"]}}, "échelle"),
    ):
        with pytest.raises(laya.LayaError, match=words):
            laya.check(bad)
    with pytest.raises(laya.LayaError, match="vide"):
        laya.decide(AssistantConfig(), " ", QUESTIONS)
    answer = {
        "answers": {
            "agent": {
                "choice": "compta",
                "probabilities": {"compta": 0.8, "juridique": 0.2},
                "confidence": 0.7,
            },
            "urgence": {"score": 1.4},
            "risque": {"noul": 0.2},
        }
    }
    seen: dict[str, Any] = {}

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(answer).encode()

    def urlopen(request: Any, timeout: float) -> Response:
        seen["url"], seen["body"] = request.full_url, json.loads(request.data)
        return Response()

    monkeypatch.setattr(laya.urllib.request, "urlopen", urlopen)
    result = laya.decide(
        AssistantConfig(laya_url="http://127.0.0.1:8000/"), "Facture de TVA", json.dumps(QUESTIONS)
    )
    assert (
        seen["url"] == "http://127.0.0.1:8000/v1/systemone"
        and seen["body"]["state"] == "Facture de TVA"
    )
    text = laya.describe(result)
    assert (
        "agent : compta (80%), confiance 70%" in text
        and "urgence : 1.4" in text
        and "non (20%" in text
    )

    def down(request: Any, timeout: float) -> Any:
        raise laya.urllib.error.URLError("refusé")

    monkeypatch.setattr(laya.urllib.request, "urlopen", down)
    with pytest.raises(laya.LayaError, match="ne répond pas"):
        laya.decide(AssistantConfig(laya_url="http://127.0.0.1:8000"), "x", QUESTIONS)
    monkeypatch.setitem(__import__("sys").modules, "laya", None)  # not installed here
    monkeypatch.setattr(laya, "_router", None)
    with pytest.raises(laya.LayaError, match="pas installé"):
        laya.decide(AssistantConfig(), "x", QUESTIONS)


def test_mcp_server_hides_spectre_skills_from_agents() -> None:
    pytest.importorskip("mcp.server.mcpserver")
    from spectre.assistant.mcp_server import build_server

    def names(agent: str) -> set[str]:
        server = build_server(lambda name, args: "", agent)
        manager = getattr(server, "_tool_manager", None) or getattr(server, "tool_manager", None)
        tools = getattr(manager, "_tools", None) or getattr(manager, "tools", {})
        return set(tools)

    assert "laya_decide" in names("") and "laya_decide" not in names("cursor")


# ---- through the web API -------------------------------------------------------------------------


def test_api_team_and_call(api: Client, service: AssistantService) -> None:  # noqa: F811
    _day(service.db)
    status, data = api.json("GET", "/api/assistant/team")
    assert status == 200 and len(data["agents"]) == 8 and "siwis" in data["voices"]
    status, data = api.json(
        "POST", "/api/assistant/team/kimi", {"engine": "deepseek:deepseek-chat"}
    )
    assert status == 200 and {a["key"]: a for a in data["agents"]}["kimi"]["moved"] is True
    assert api.json("POST", "/api/assistant/team/kimi", {"engine": "cursor"})[0] == 400
    assert api.json("GET", "/api/assistant/team/cursor")[1]["key"] == "cursor"
    status, _, _ = api.request(
        "POST",
        "/api/assistant/team/cursor/portrait",
        raw=PNG,
        headers={"Content-Type": "image/png"},
    )
    assert status == 200
    status, headers, body = api.request("GET", "/api/assistant/team/cursor/portrait")
    assert status == 200 and headers["content-type"] == "image/png" and body == PNG
    assert api.json("POST", "/api/assistant/team/cursor/portrait/delete", {})[0] == 200
    assert api.request("GET", "/api/assistant/team/cursor/portrait")[0] == 404
    status, state = api.json("GET", "/api/assistant/call?since=0")
    assert status == 200 and state["needs_you"] == 1 and state["agents"][0]["look"] == {}
    assert api.json("POST", "/api/assistant/call/standup", {})[1]["lines"][0]["agent"] == "opus"
    assert "Point d'équipe" in api.json("GET", "/api/assistant/call/recap")[1]["markdown"]
    assert api.json("GET", "/api/assistant/call/tree")[0] == 200
    board = api.json("GET", "/api/assistant/call/board")[1]
    assert board["missions"] and isinstance(board["sessions"], list)
    assert api.json("GET", "/api/assistant/call/replay/1")[1]["mission"]["id"] == 1
    assert api.json("GET", "/api/assistant/call/session/codex/absent")[0] == 404
    assert api.json("POST", "/api/assistant/call/say", {"agent": "cursor", "text": "Bonjour"})[
        1
    ] == {"audio": ""}


def test_unread_request_bodies_do_not_spill(api: Client) -> None:  # noqa: F811
    """A POST whose route ignores its body must not corrupt the next request on the same
    connection (seen as « {}GET » before v0.17)."""
    conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=10)
    conn.request(
        "POST",
        "/api/assistant/call/standup",
        body=b'{"unused": true}',
        headers={"X-Spectre": "1", "Content-Type": "application/json"},
    )
    assert conn.getresponse().read() and True
    conn.request(
        "POST",
        "/api/assistant/talk",
        body=b"{}",
        headers={"X-Spectre": "1", "Content-Type": "application/json"},
    )
    conn.getresponse().read()
    conn.request("GET", "/api/assistant/status")
    response = conn.getresponse()
    assert response.status == 200 and json.loads(response.read())
    conn.close()
