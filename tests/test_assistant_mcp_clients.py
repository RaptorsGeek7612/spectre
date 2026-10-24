"""External MCP servers: cards are data, every call goes through the gate, secrets stay in .env."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import mcp_clients
from spectre.assistant import tools as tools_mod
from spectre.assistant.actions import ActionError
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate, Level
from spectre.assistant.providers import read_env_file

SERVER = '''
from mcp.server.mcpserver import MCPServer

server = MCPServer("echo")


@server.tool()
def echo(text: str) -> str:
    """Repeat the text."""
    return "echo: " + text


@server.tool()
def fail() -> str:
    """Always fails."""
    raise ValueError("boom")


server.run()
'''


@pytest.fixture
def ctx(tmp_path: Path) -> Any:
    db = Database(tmp_path / "a.db")
    context = tools_mod.make_context(db, tmp_path / "assistant", [str(tmp_path)])
    yield context
    db.close()


@pytest.fixture
def gate(ctx: Any) -> Gate:
    return Gate(ctx.db)


@pytest.fixture
def echo_server(tmp_path: Path) -> Path:
    script = tmp_path / "echo_server.py"
    script.write_text(SERVER, encoding="utf-8")
    return script


def _card(ctx: Any, script: Path, **kw: Any) -> dict[str, Any]:
    fields = {
        "name": "echo",
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(script)],
        "level": "lecture",
    } | kw
    card = mcp_clients.build(ctx.root, **fields)
    mcp_clients._write(ctx.root, card)
    return card


def test_build_checks_the_card(ctx: Any) -> None:
    with pytest.raises(ActionError, match="nom de serveur invalide"):
        mcp_clients.build(ctx.root, name="Mauvais Nom", command="npx")
    with pytest.raises(ActionError, match="pas un serveur MCP"):
        mcp_clients.build(ctx.root, name="shell", command="powershell.exe")
    with pytest.raises(ActionError, match="transport inconnu"):
        mcp_clients.build(ctx.root, name="x1", transport="ftp")
    with pytest.raises(ActionError, match="niveau inconnu"):
        mcp_clients.build(ctx.root, name="x1", command="npx", level="tout")
    with pytest.raises(ActionError, match="https"):
        mcp_clients.build(ctx.root, name="x1", transport="http", url="http://exemple.fr/mcp")
    with pytest.raises(ActionError, match="programme invalide"):
        mcp_clients.build(ctx.root, name="x1", command="npx && calc")
    local = mcp_clients.build(ctx.root, name="x1", transport="http", url="http://127.0.0.1:9/mcp")
    assert local["url"] == "http://127.0.0.1:9/mcp" and local["headers"] == {}
    card = mcp_clients.build(
        ctx.root, name="mem", command="npx", args="-y @modelcontextprotocol/server-memory"
    )
    assert card["args"] == ["-y", "@modelcontextprotocol/server-memory"]
    assert card["level"] == "action" and card["agents"] == [] and card["enabled"]


def test_spectre_never_writes_a_plain_secret(ctx: Any) -> None:
    with pytest.raises(ActionError, match="ressemble à un secret"):
        mcp_clients.save(ctx, name="gh", command="npx", env={"GITHUB_TOKEN": "ghp_abc"})
    with pytest.raises(ActionError, match="ressemble à un secret"):
        mcp_clients.save(
            ctx, name="api", transport="http", url="https://x.fr/mcp",
            headers={"Authorization": "Bearer abc"},
        )  # fmt: skip
    done = mcp_clients.save(ctx, name="gh", command="npx", env={"GITHUB_TOKEN": "${GH}"})
    assert "ajouté" in done
    assert "mis à jour" in mcp_clients.save(ctx, name="gh", command="npx")


def test_user_secrets_move_to_env(ctx: Any) -> None:
    card = mcp_clients.save_from_user(
        ctx.root,
        {
            "name": "github",
            "command": "npx",
            "args": "-y @modelcontextprotocol/server-github",
            "env": "GITHUB_PERSONAL_ACCESS_TOKEN=ghp_secret\nLOG=info",
            "agents": "",
        },
    )
    assert card["secrets"] == ["SPECTRE_MCP_GITHUB_GITHUB_PERSONAL_ACCESS_TOKEN"]
    raw = (ctx.root / "serveurs-mcp" / "github.json").read_text(encoding="utf-8")
    assert "ghp_secret" not in raw and "LOG" in raw
    env = read_env_file(ctx.root / ".env")
    assert env["SPECTRE_MCP_GITHUB_GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_secret"
    remote = mcp_clients.save_from_user(
        ctx.root,
        {"name": "notion", "transport": "http", "url": "https://mcp.notion.com/mcp",
         "token": "ntn_x", "level": "lecture"},
    )  # fmt: skip
    assert remote["secrets"] == ["SPECTRE_MCP_NOTION_AUTHORIZATION"]
    card_raw = mcp_clients.load(ctx.root, "notion")
    assert card_raw is not None
    assert card_raw["headers"]["Authorization"] == "Bearer ${SPECTRE_MCP_NOTION_AUTHORIZATION}"
    assert mcp_clients._expand(card_raw["headers"]["Authorization"], ctx.root) == "Bearer ntn_x"
    with pytest.raises(ActionError, match="secret ABSENT_X absent"):
        mcp_clients._expand("${ABSENT_X}", ctx.root)


def test_risk_follows_the_card(ctx: Any) -> None:
    card = mcp_clients.build(ctx.root, name="gh", command="npx", auto="search, get_file")
    assert mcp_clients.risk(card, "create_issue") == (Level.EXTERNAL, "mcp_action")
    assert mcp_clients.risk(card, "search") == (Level.READ, "mcp_read")
    assert mcp_clients.risk(card | {"level": "ecriture"}) == (Level.WRITE, "mcp_write")
    assert mcp_clients.risk(None) == (Level.READ, "read")


def test_listing_agents_and_toggle(ctx: Any, echo_server: Path) -> None:
    assert "aucun serveur MCP" in mcp_clients.listing(ctx)
    _card(ctx, echo_server, agents="Kyra")
    assert "echo" in mcp_clients.listing(ctx)
    ctx.agent = "mistral"
    assert "aucun serveur MCP" in mcp_clients.listing(ctx)
    with pytest.raises(ActionError, match="pas de ton domaine"):
        mcp_clients.call(ctx, "echo", "echo", {"text": "x"})
    ctx.agent = ""
    mcp_clients.set_enabled(ctx.root, "echo", False)
    assert "désactivé" in mcp_clients.listing(ctx)
    with pytest.raises(ActionError, match="désactivé"):
        mcp_clients.tools_text(ctx, "echo")
    with pytest.raises(ActionError, match="inconnu"):
        mcp_clients.call(ctx, "absent", "echo")
    assert mcp_clients.describe(ctx.root)[0]["agents"] == ["Kyra"]
    assert "retiré" in mcp_clients.delete(ctx, "echo")
    with pytest.raises(ActionError, match="aucun serveur"):
        mcp_clients.delete(ctx.root, "echo")


def test_real_stdio_server_round_trip(ctx: Any, echo_server: Path) -> None:
    _card(ctx, echo_server, auto="echo")
    tools = {t["name"] for t in mcp_clients.list_tools(ctx, "echo")}
    assert tools == {"echo", "fail"}
    assert "echo [sans validation] (text*: string)" in mcp_clients.tools_text(ctx, "echo")
    assert mcp_clients.call(ctx, "echo", "echo", '{"text": "salut"}') == "echo: salut"
    with pytest.raises(ActionError, match="echo/fail : Error"):
        mcp_clients.call(ctx, "echo", "fail", {})
    with pytest.raises(ActionError, match="JSON illisible"):
        mcp_clients.call(ctx, "echo", "echo", "{pas du json")


def test_unreachable_server_is_reported(ctx: Any) -> None:
    card = mcp_clients.build(ctx.root, name="absent", command="spectre-absent-xyz", timeout=10)
    mcp_clients._write(ctx.root, card)
    with pytest.raises(ActionError, match="absent"):
        mcp_clients.list_tools(ctx, "absent")


def test_calls_go_through_the_gate(ctx: Any, gate: Gate, echo_server: Path) -> None:
    _card(ctx, echo_server, level="action", auto="")
    pending = tools_mod.execute(
        gate, ctx, "mcp_call", {"server": "echo", "tool": "echo", "arguments": {"text": "a"}}
    )
    assert "validation" in pending.lower()
    row = ctx.db.one("SELECT * FROM approvals WHERE tool = 'mcp_call'")
    assert row["category"] == "mcp_action"
    assert tools_mod.run_approved(gate, ctx, row["id"]) == "echo: a"
    _card(ctx, echo_server, level="lecture")
    done = tools_mod.execute(
        gate, ctx, "mcp_call", {"server": "echo", "tool": "echo", "arguments": {"text": "b"}}
    )
    assert done.endswith("echo: b")
    assert "echo" in tools_mod.execute(gate, ctx, "mcp_servers", {})
    plug = tools_mod.execute(
        gate, ctx, "mcp_server_save", {"name": "mem", "command": "npx", "args": ["-y", "x"]}
    )
    assert "validation" in plug.lower() and mcp_clients.load(ctx.root, "mem") is None
    unplug = tools_mod.execute(gate, ctx, "mcp_server_delete", {"name": "echo"})
    assert "validation" in unplug.lower()


def test_spectre_equips_its_agents(ctx: Any, gate: Gate, echo_server: Path) -> None:
    from spectre.assistant import team
    from spectre.assistant.config import AssistantConfig

    _card(ctx, echo_server, agents="Kyra")
    assert "Kyra, Syfer" in mcp_clients.grant(ctx, "echo", "Syfer")
    assert mcp_clients.load(ctx.root, "echo")["agents"] == ["chatgpt", "mistral"]
    assert "Kyra" not in mcp_clients.grant(ctx, "echo", "Kyra", "retirer")
    assert "tous les agents" in mcp_clients.grant(ctx, "echo", "tous", "remplacer")
    assert mcp_clients.grant(ctx, "echo", "Kyra", "ajouter").endswith("tous les agents")
    assert "Kyra" not in mcp_clients.grant(ctx, "echo", "Kyra", "retirer")
    with pytest.raises(ActionError, match="mode inconnu"):
        mcp_clients.grant(ctx, "echo", "Kyra", "tout")
    with pytest.raises(ActionError, match="agents à qui retirer"):
        mcp_clients.grant(ctx, "echo", "tous", "retirer")
    with pytest.raises(ActionError, match="branche-le d'abord"):
        mcp_clients.grant(ctx, "absent", "Kyra")
    mcp_clients.grant(ctx, "echo", "Syfer, agent:7", "remplacer")
    assert mcp_clients.load(ctx.root, "echo")["agents"] == ["agent:7", "mistral"]
    # the agent's profile lists the servers it may use
    kit = team.agent_tools(AssistantConfig(), "mistral", ctx.root)
    assert any(t["name"] == "mcp:echo" and t["category"] == "mcp_read" for t in kit)
    assert not any(
        t["name"] == "mcp:echo" for t in team.agent_tools(AssistantConfig(), "lexy", ctx.root)
    )
    # Spectre's grant waits for the user's approval
    pending = tools_mod.execute(gate, ctx, "mcp_server_agents", {"name": "echo", "agents": "Lexy"})
    assert "validation" in pending.lower()


def test_an_agent_asks_for_a_server(ctx: Any, gate: Gate, echo_server: Path) -> None:
    _card(ctx, echo_server, agents="Kyra")
    ctx.agent = "lexy"
    with pytest.raises(ActionError, match="compte rendu"):
        mcp_clients.request(ctx, "absent", "pour les cotes")
    asked = tools_mod.execute(
        gate, ctx, "mcp_server_request", {"name": "echo", "reason": "relire les cotes"}
    )
    assert "validation" in asked.lower()
    row = ctx.db.one("SELECT * FROM approvals WHERE tool = 'mcp_server_request'")
    assert "Lexy" in tools_mod.run_approved(gate, ctx, row["id"])
    assert mcp_clients.load(ctx.root, "echo")["agents"] == ["chatgpt", "lexy"]
    assert "déjà accès" in mcp_clients.request(ctx, "echo", "x")
    assert mcp_clients.call(ctx, "echo", "echo", {"text": "ok"}) == "echo: ok"
    # the lead-only tools stay Spectre's
    refused = tools_mod.execute(gate, ctx, "mcp_server_agents", {"name": "echo", "agents": "tous"})
    assert refused.startswith("REFUSÉ")


def test_hosted_agents_get_an_object_for_arguments() -> None:
    from spectre.assistant.llm import tool_schemas

    schema = tool_schemas([tools_mod.TOOLS["mcp_call"]])[0]["function"]["parameters"]
    assert schema["properties"]["arguments"]["type"] == "object"
    assert schema["required"] == ["server", "tool"]
