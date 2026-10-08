"""MCP server exposing Spectre's tools to the brain (Claude Code), over stdio.

Claude Code launches it as a subprocess (`python -m spectre.assistant.mcp_server`); it opens the
same SQLite database as the assistant, so every call goes through the governance gate and the
audit log, and approvals land where the UI can see them.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from spectre.assistant.config import AssistantConfig, assistant_dir
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate
from spectre.assistant.tools import TOOLS, Tool, execute, make_context

SERVER_NAME = "spectre"


def tool_wrapper(tool: Tool, call: Callable[[str, dict[str, Any]], str]) -> Callable[..., str]:
    """A function with the tool's own parameters (minus the context), for schema generation."""
    signature = inspect.signature(tool.run)
    params = list(signature.parameters.values())[1:]  # drop `ctx`

    def wrapper(**kwargs: Any) -> str:
        return call(tool.name, kwargs)

    wrapper.__name__ = tool.name
    wrapper.__doc__ = tool.description
    wrapper.__signature__ = signature.replace(parameters=params)  # type: ignore[attr-defined]
    wrapper.__annotations__ = {
        k: v for k, v in getattr(tool.run, "__annotations__", {}).items() if k != "ctx"
    }
    return wrapper


def build_server(call: Callable[[str, dict[str, Any]], str]) -> Any:
    """An `MCPServer` with one MCP tool per Spectre tool."""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        SERVER_NAME,
        instructions="Les mains de Spectre. Chaque action passe par le portail de gouvernance.",
    )
    for tool in TOOLS.values():
        server.add_tool(tool_wrapper(tool, call), name=tool.name, description=tool.description)
    return server


def main() -> None:  # pragma: no cover - launched by Claude Code over stdio
    root = assistant_dir()
    config = AssistantConfig.load(root)
    db = Database(root / "spectre.db")
    gate = Gate(db, auto_max_level=config.auto_max_level)
    ctx = make_context(db, root, config.allowed_roots)
    build_server(lambda name, args: execute(gate, ctx, name, args)).run()


if __name__ == "__main__":  # pragma: no cover
    main()
