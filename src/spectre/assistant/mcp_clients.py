"""External MCP servers Spectre and its agents can use: one card (« fiche ») per server.

Spectre is already an MCP *server* for its brain and its CLI agents; this module makes it an MCP
*client* too. A card is data, `serveurs-mcp/<name>.json` in Spectre's own folder (out of reach of
the agents' file tools): how to reach the server (a local program over stdio, or an address over
streamable HTTP), for which agents, and how risky its tools are. The brain never talks to these
servers directly: it calls `mcp_call`, which goes through the governance gate and the audit log
like any other action, so the external servers stay behind the same portal.

Secrets never go in a card: a value written `${NAME}` is read at connection time from the
assistant's `.env` (then the environment). The interface stores the secrets the user types there.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from spectre.assistant.actions import MAX_READ_CHARS, ActionContext, ActionError
from spectre.assistant.db import now_iso
from spectre.assistant.governance import Level

FOLDER = "serveurs-mcp"
NAME = re.compile(r"[a-z][a-z0-9_-]{1,30}")
TOOL_NAME = re.compile(r"[A-Za-z0-9_.:/-]{1,128}")
ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,80}")
HEADER_KEY = re.compile(r"[A-Za-z0-9-]{1,80}")
REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]{0,80})\}")
SECRET_HINT = re.compile(r"TOKEN|KEY|SECRET|PASSWORD|PASS|AUTH|COOKIE|CREDENTIAL", re.I)
TRANSPORTS = ("stdio", "http")
# (level, governance category) of the tools of a server, by the level its card gives them
LEVELS = {
    "lecture": (Level.READ, "mcp_read"),  # only reads: runs on its own
    "ecriture": (Level.WRITE, "mcp_write"),  # changes local things, reversible
    "action": (Level.EXTERNAL, "mcp_action"),  # acts outside: each call waits for your go
}
# A server is one program, not a shell running a script line.
FORBIDDEN = {
    "cmd", "powershell", "pwsh", "bash", "sh", "wsl", "wscript", "cscript", "mshta",
    "rundll32", "regsvr32", "reg", "schtasks", "sc", "msiexec", "format", "diskpart", "bcdedit",
    "takeown", "icacls", "netsh", "shutdown",
}  # fmt: skip
TIMEOUT_S = 120
MAX_TIMEOUT_S = 900


def folder(root: Path) -> Path:
    return root / FOLDER


def _path(root: Path, name: str) -> Path:
    if not NAME.fullmatch(name):
        raise ActionError(f"nom de serveur invalide : {name} (minuscules, chiffres, - ou _)")
    return folder(root) / f"{name}.json"


def load(root: Path, name: str) -> dict[str, Any] | None:
    try:
        path = _path(root, name.strip().lower())
    except ActionError:
        return None
    if not path.is_file():
        return None
    try:
        card = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return card if isinstance(card, dict) else None


def cards(root: Path) -> list[dict[str, Any]]:
    found = []
    for path in sorted(folder(root).glob("*.json")) if folder(root).is_dir() else []:
        card = load(root, path.stem)
        if card is not None:
            found.append(card)
    return found


def _write(root: Path, card: dict[str, Any]) -> None:
    path = _path(root, card["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")


def allowed(card: dict[str, Any], agent: str) -> bool:
    agents = card.get("agents") or []
    return agent in ("", "opus") or not agents or agent in agents


def risk(card: dict[str, Any] | None, tool: str = "") -> tuple[Level, str]:
    if card is None:
        return Level.READ, "read"  # unknown server: the call fails before doing anything
    if tool and tool in (card.get("auto") or []):
        return LEVELS["lecture"]
    return LEVELS.get(str(card.get("level")), LEVELS["action"])


# ---- validation of what a card holds ---------------------------------------------------------


def _agents(raw: str) -> list[str]:
    from spectre.assistant.local_models import resolve_agent

    names = [n.strip() for n in re.split(r"[,;]", raw) if n.strip()]
    if not names or [n.lower() for n in names] == ["tous"]:
        return []
    return sorted({resolve_agent(n) for n in names})


def _command(raw: str) -> str:
    wanted = raw.strip().strip('"')
    if not wanted:
        raise ActionError("indique le programme qui lance le serveur (ex. npx, uvx, ou un .exe)")
    stem = Path(wanted).stem.lower() if Path(wanted).suffix else Path(wanted).name.lower()
    if stem in FORBIDDEN:
        raise ActionError(
            f"{stem} n'est pas un serveur MCP : une fiche lance un programme précis, jamais un "
            "shell ou un outil système"
        )
    if not Path(wanted).is_absolute() and not re.fullmatch(r"[A-Za-z0-9._-]+", wanted):
        raise ActionError(f"nom de programme invalide : {wanted}")
    return wanted


def _url(raw: str) -> str:
    url = raw.strip()
    if not re.fullmatch(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{3,500}", url):
        raise ActionError(f"adresse invalide : {url} (http:// ou https://)")
    host = re.sub(r"^https?://([^/:?#]+).*$", r"\1", url).lower()
    if url.startswith("http://") and host not in ("127.0.0.1", "localhost", "::1"):
        raise ActionError("un serveur distant se joint en https:// (http:// seulement en local)")
    return url


def _pairs(raw: dict[str, Any] | str | None, key: re.Pattern[str], what: str) -> dict[str, str]:
    """`{"K": "v"}` or `K=v` lines; values may be `${NAME}` references."""
    if isinstance(raw, str):
        found: dict[str, str] = {}
        for line in raw.splitlines():
            if not line.strip():
                continue
            name, sep, value = line.partition("=" if "=" in line else ":")
            if not sep:
                raise ActionError(f"{what} : « {line.strip()} » (NOM=valeur attendu)")
            found[name.strip()] = value.strip()
        raw = found
    pairs = {str(k).strip(): str(v).strip() for k, v in (raw or {}).items()}
    for name, value in pairs.items():
        if not key.fullmatch(name):
            raise ActionError(f"{what} : nom invalide « {name} »")
        if "\n" in value or len(value) > 2000:
            raise ActionError(f"{what} : valeur de {name} invalide")
    return pairs


def _no_plain_secret(pairs: dict[str, str], what: str) -> None:
    """A secret reaches a card only as a `${NAME}` reference (approvals and audit keep args)."""
    for name, value in pairs.items():
        hidden = REFERENCE.sub("", value).strip()
        bearer = hidden.lower().removeprefix("bearer").strip()
        if SECRET_HINT.search(name) and bearer:
            raise ActionError(
                f"{what} {name} ressemble à un secret : écris ${{NOM}} et demande à "
                "l'utilisateur de saisir la valeur dans Agents › Serveurs MCP (elle va dans .env)"
            )


def _tools(raw: list[str] | str | None) -> list[str]:
    items = re.split(r"[,;\s]+", raw) if isinstance(raw, str) else list(raw or [])
    names = [str(n).strip() for n in items if str(n).strip()]
    for name in names:
        if not TOOL_NAME.fullmatch(name):
            raise ActionError(f"nom d'outil MCP invalide : {name}")
    return sorted(set(names))


def build(
    root: Path,
    *,
    name: str,
    transport: str = "stdio",
    command: str = "",
    args: list[str] | str | None = None,
    url: str = "",
    env: dict[str, Any] | str | None = None,
    headers: dict[str, Any] | str | None = None,
    label: str = "",
    description: str = "",
    agents: str = "tous",
    level: str = "action",
    auto: list[str] | str | None = None,
    timeout: int = TIMEOUT_S,
    enabled: bool = True,
) -> dict[str, Any]:
    """A checked card (not written)."""
    name = name.strip().lower()
    _path(root, name)
    transport = transport.strip().lower() or "stdio"
    if transport not in TRANSPORTS:
        raise ActionError(f"transport inconnu : {transport} (stdio ou http)")
    if level not in LEVELS:
        raise ActionError(f"niveau inconnu : {level} (au choix : {', '.join(LEVELS)})")
    if isinstance(args, str):
        import shlex

        try:
            args = shlex.split(args, posix=True)
        except ValueError as exc:
            raise ActionError(f"arguments illisibles : {exc}") from exc
    card: dict[str, Any] = {
        "name": name,
        "label": (label.strip() or name)[:80],
        "description": description.strip()[:400],
        "agents": _agents(agents),
        "transport": transport,
        "level": level,
        "auto": _tools(auto),
        "timeout": max(10, min(int(timeout), MAX_TIMEOUT_S)),
        "enabled": bool(enabled),
    }
    if transport == "stdio":
        card |= {
            "command": _command(command),
            "args": [str(a) for a in args or []],
            "env": _pairs(env, ENV_KEY, "variable"),
        }
    else:
        card |= {"url": _url(url), "headers": _pairs(headers, HEADER_KEY, "en-tête")}
    previous = load(root, name)
    card["created"] = (previous or {}).get("created", now_iso())
    card["updated"] = now_iso()
    return card


def save(ctx: ActionContext, **fields: Any) -> str:
    """Write a card proposed by Spectre (after the user's approval): no plain secret."""
    card = build(ctx.root, **fields)
    _no_plain_secret(card.get("env") or {}, "la variable")
    _no_plain_secret(card.get("headers") or {}, "l'en-tête")
    previous = load(ctx.root, card["name"])
    _write(ctx.root, card)
    verb = "mis à jour" if previous else "ajouté"
    return (
        f'serveur MCP « {card["name"]} » {verb} ; ses outils : mcp_tools(server="{card["name"]}")'
    )


def save_from_user(root: Path, data: dict[str, Any]) -> dict[str, Any]:
    """A card typed by the user in the interface: plain secrets move to `.env` as references."""
    from spectre.assistant.providers import write_env_value

    card = build(
        root,
        name=str(data.get("name", "")),
        transport=str(data.get("transport", "stdio")),
        command=str(data.get("command", "")),
        args=str(data.get("args", "")),
        url=str(data.get("url", "")),
        env=str(data.get("env", "")),
        headers=str(data.get("headers", "")),
        label=str(data.get("label", "")),
        description=str(data.get("description", "")),
        agents=str(data.get("agents", "") or "tous"),
        level=str(data.get("level", "action")),
        auto=str(data.get("auto", "")),
        timeout=int(str(data.get("timeout") or TIMEOUT_S)),
    )
    token = str(data.get("token", "")).strip()
    if token and card["transport"] == "http":
        card["headers"]["Authorization"] = token if " " in token else f"Bearer {token}"
    stem = "SPECTRE_MCP_" + re.sub(r"[^A-Z0-9]", "_", card["name"].upper())
    for field in ("env", "headers"):
        for key, value in (card.get(field) or {}).items():
            if SECRET_HINT.search(key) and value and not REFERENCE.fullmatch(value):
                prefix = "Bearer " if value.lower().startswith("bearer ") else ""
                secret = value[len(prefix) :]
                var = f"{stem}_{re.sub(r'[^A-Z0-9]', '_', key.upper())}"
                write_env_value(root, var, secret)
                card[field][key] = f"{prefix}${{{var}}}"
    _write(root, card)
    return describe_card(card)


def delete(ctx_or_root: ActionContext | Path, name: str) -> str:
    root = ctx_or_root if isinstance(ctx_or_root, Path) else ctx_or_root.root
    path = _path(root, name.strip().lower())
    if not path.is_file():
        raise ActionError(f"aucun serveur MCP nommé {name}")
    path.unlink()
    return f"serveur MCP « {name} » retiré (ses secrets restent dans .env)"


def set_enabled(root: Path, name: str, enabled: bool) -> dict[str, Any]:
    card = load(root, name)
    if card is None:
        raise ActionError(f"aucun serveur MCP nommé {name}")
    card["enabled"] = bool(enabled)
    card["updated"] = now_iso()
    _write(root, card)
    return describe_card(card)


# ---- connection ------------------------------------------------------------------------------


def _expand(value: str, root: Path) -> str:
    from spectre.assistant.providers import read_env_file

    known = read_env_file(root / ".env")

    def one(match: re.Match[str]) -> str:
        key = match.group(1)
        found = known.get(key) or os.environ.get(key)
        if not found:
            raise ActionError(f"secret {key} absent : saisis-le dans Agents › Serveurs MCP")
        return found

    return REFERENCE.sub(one, value)


def _text(result: Any) -> str:
    parts = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(str(text))
        else:
            kind = getattr(item, "type", "contenu")
            parts.append(f"[{kind} {getattr(item, 'mime_type', '') or ''}]".replace(" ]", "]"))
    structured = getattr(result, "structured_content", None)
    if not parts and structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False))
    return "\n".join(parts) or "(aucune sortie)"


async def _session(card: dict[str, Any], root: Path, work: Any) -> Any:  # pragma: no cover
    """Open the server, run `work(session)`, close it (one connection per call: no state)."""
    from mcp import ClientSession

    if card["transport"] == "http":
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        headers = {k: _expand(v, root) for k, v in (card.get("headers") or {}).items()}
        async with (
            create_mcp_http_client(headers=headers) as client,
            streamable_http_client(card["url"], http_client=client) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            return await work(session)
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {k: _expand(v, root) for k, v in (card.get("env") or {}).items()}
    params = StdioServerParameters(
        command=card["command"], args=list(card.get("args") or []), env=env or None
    )
    with open(os.devnull, "w", encoding="utf-8") as quiet:  # servers log to stderr
        async with (
            stdio_client(params, errlog=quiet) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            return await work(session)


def _run(card: dict[str, Any], root: Path, work: Any) -> Any:
    """Run a session from any thread, even one already inside an event loop."""
    timeout = float(card.get("timeout") or TIMEOUT_S)
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["out"] = asyncio.run(asyncio.wait_for(_session(card, root, work), timeout))
        except BaseException as exc:  # noqa: BLE001 - reported to the caller below
            box["err"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout + 15)
    if worker.is_alive():
        raise ActionError(f"le serveur MCP {card['name']} ne répond pas (> {int(timeout)} s)")
    if "err" in box:
        exc = box["err"]
        if isinstance(exc, ActionError):
            raise exc
        if isinstance(exc, TimeoutError):
            raise ActionError(f"le serveur MCP {card['name']} a dépassé {int(timeout)} s")
        detail = _flatten(exc)
        raise ActionError(f"serveur MCP {card['name']} injoignable : {detail}"[:600])
    return box.get("out")


def _flatten(exc: BaseException) -> str:
    """The first real error inside an exception group (anyio wraps them)."""
    inner = getattr(exc, "exceptions", None)
    if inner:
        return _flatten(inner[0])
    return f"{type(exc).__name__}: {exc}"


def _usable(ctx: ActionContext, server: str) -> dict[str, Any]:
    card = load(ctx.root, server)
    if card is None:
        raise ActionError(f"serveur MCP inconnu : {server} (liste : mcp_servers)")
    if not allowed(card, ctx.agent):
        raise ActionError(f"le serveur MCP {server} n'est pas de ton domaine")
    if not card.get("enabled", True):
        raise ActionError(f"le serveur MCP {server} est désactivé par l'utilisateur")
    return card


def list_tools(ctx: ActionContext, server: str) -> list[dict[str, Any]]:
    card = _usable(ctx, server)

    async def work(session: Any) -> list[dict[str, Any]]:  # pragma: no cover - live server
        result = await session.list_tools()
        return [
            {
                "name": t.name,
                "description": (t.description or "")[:500],
                "schema": t.input_schema or {},
            }
            for t in result.tools
        ]

    found: list[dict[str, Any]] = _run(card, ctx.root, work)
    return found


def tools_text(ctx: ActionContext, server: str) -> str:
    card = _usable(ctx, server)
    found = list_tools(ctx, server)
    if not found:
        return f"le serveur {server} ne propose aucun outil"
    auto = set(card.get("auto") or [])
    lines = []
    for tool in found:
        level = "sans validation" if tool["name"] in auto else card.get("level", "action")
        props = (tool["schema"] or {}).get("properties") or {}
        required = set((tool["schema"] or {}).get("required") or [])
        params = ", ".join(
            f"{k}{'*' if k in required else ''}: {(v or {}).get('type', '?')}"
            for k, v in props.items()
        )
        lines.append(f"- {tool['name']} [{level}] ({params}) : {tool['description']}")
    return (
        f"Outils du serveur MCP {server} (mcp_call(server, tool, arguments) ; * = requis) :\n"
        + "\n".join(lines)
    )[:MAX_READ_CHARS]


def call(
    ctx: ActionContext, server: str, tool: str, arguments: dict[str, Any] | str | None = None
) -> str:
    card = _usable(ctx, server)
    if not TOOL_NAME.fullmatch(tool or ""):
        raise ActionError(f"nom d'outil MCP invalide : {tool}")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except ValueError as exc:
            raise ActionError(f"arguments : JSON illisible ({exc})") from exc
    if not isinstance(arguments, dict):
        raise ActionError('arguments : un objet JSON (ex. {"query": "…"})')

    async def work(session: Any) -> Any:  # pragma: no cover - live server
        return await session.call_tool(tool, arguments)

    result = _run(card, ctx.root, work)
    text = _text(result)
    if getattr(result, "is_error", False):
        raise ActionError(f"{server}/{tool} : {text[:600]}")
    return text[:MAX_READ_CHARS]


# ---- descriptions ----------------------------------------------------------------------------


def _names(keys: list[str]) -> list[str]:
    from spectre.assistant.config import AGENT_NAMES

    return [AGENT_NAMES.get(k, k) for k in keys]


def describe_card(card: dict[str, Any]) -> dict[str, Any]:
    """A card for the interface: references are shown, never the secrets themselves."""
    target = card.get("url") or " ".join([card.get("command", ""), *(card.get("args") or [])])
    return {
        "name": card["name"],
        "label": card.get("label", card["name"]),
        "description": card.get("description", ""),
        "transport": card.get("transport", "stdio"),
        "target": target.strip(),
        "level": card.get("level", "action"),
        "auto": list(card.get("auto") or []),
        "agents": _names(list(card.get("agents") or [])),
        "enabled": bool(card.get("enabled", True)),
        "secrets": sorted(
            {
                m
                for v in [*(card.get("env") or {}).values(), *(card.get("headers") or {}).values()]
                for m in REFERENCE.findall(v)
            }
        ),  # fmt: skip
        "updated": card.get("updated", ""),
    }


def describe(root: Path) -> list[dict[str, Any]]:
    return [describe_card(c) for c in cards(root)]


def listing(ctx: ActionContext) -> str:
    """The servers this agent may use (all of them, for Spectre)."""
    mine = [c for c in cards(ctx.root) if allowed(c, ctx.agent)]
    if not mine:
        return (
            "aucun serveur MCP branché pour l'instant (Spectre peut en proposer un avec "
            "mcp_server_save, ou l'utilisateur l'ajoute dans Agents › Serveurs MCP)"
        )
    lines = []
    for c in mine:
        d = describe_card(c)
        state = "actif" if d["enabled"] else "désactivé"
        who = ", ".join(d["agents"]) or "tous"
        lines.append(
            f"- {d['name']} — {d['label']} [{d['transport']}, {d['level']}, {state}, pour {who}] "
            f": {d['description'] or '…'}"
        )
    return "Serveurs MCP branchés (outils : mcp_tools(server), puis mcp_call) :\n" + "\n".join(
        lines
    )
