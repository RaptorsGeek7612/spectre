"""An agent on any OpenAI-compatible endpoint (LM Studio, Ollama, OpenRouter, Groq, Gemini...).

It has the same `ask` interface as the CLI agents (Claude Code, Codex, Vibe), so the brain, the
missions and created agents can run on it. Tools are Spectre's own, called through
`tools.execute` in this process: every action still goes through the governance gate and the
audit log, exactly as over MCP.
"""

from __future__ import annotations

import inspect
import json
import types
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Union, get_args, get_origin

from spectre.assistant.brain import Reply
from spectre.assistant.config import AssistantConfig
from spectre.assistant.providers import ProviderError, Providers, split_ref

MAX_TOOL_ROUNDS = 12
MAX_TOOL_RESULT = 12_000
Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]
ToolCall = Callable[[str, dict[str, Any]], str]  # (name, args) -> text, through the gate

JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def post_json(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
) -> dict[str, Any]:
    """POST a JSON body and return the JSON answer (HTTP errors carry the provider's message)."""
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise ConnectionError(f"HTTP {exc.code} : {detail}") from exc
    return data if isinstance(data, dict) else {}


def json_type(annotation: Any) -> str:
    """The JSON Schema type of a parameter annotation (`int | None` -> integer)."""
    if get_origin(annotation) in (Union, types.UnionType):
        inner = [a for a in get_args(annotation) if a is not type(None)]
        annotation = inner[0] if inner else str
    return JSON_TYPES.get(annotation, "string")


def tool_schemas(tools: Sequence[Any]) -> list[dict[str, Any]]:
    """OpenAI `tools` definitions from Spectre's tools (their parameters minus the context)."""
    schemas = []
    for tool in tools:
        params = list(inspect.signature(tool.run, eval_str=True).parameters.values())[1:]
        properties = {p.name: {"type": json_type(p.annotation)} for p in params}
        required = [p.name for p in params if p.default is inspect.Parameter.empty]
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
        )
    return schemas


def gate_caller(root: Path, config: AssistantConfig) -> ToolCall:
    """Spectre's tools through the gate, as the MCP server would run them."""
    from spectre.assistant.db import Database
    from spectre.assistant.governance import Gate
    from spectre.assistant.tools import execute, make_context

    db = Database(root / "spectre.db")
    gate = Gate(db, auto_max_level=config.auto_max_level)
    ctx = make_context(db, root, config.allowed_roots)
    return lambda name, args: execute(gate, ctx, name, args)


class HttpAgent:
    """`ask` on a `provider:model` engine, with a tool loop over Spectre's tools."""

    def __init__(
        self,
        config: AssistantConfig,
        root: Path,
        *,
        providers: Providers | None = None,
        transport: Transport = post_json,
        call_tool: ToolCall | None = None,
    ) -> None:
        self.config = config
        self.root = root
        self.providers = providers or Providers(root)
        self.transport = transport
        self._call_tool = call_tool
        self.workspace = root / "workspace"

    def call_tool(self, name: str, args: dict[str, Any]) -> str:
        if self._call_tool is None:
            self._call_tool = gate_caller(self.root, self.config)
        return self._call_tool(name, args)

    def ask(
        self,
        prompt: str,
        *,
        system: str,
        model: str | None = None,
        resume: str | None = None,
        with_tools: bool = True,
        history: Sequence[dict[str, str]] = (),
    ) -> Reply:
        """One turn. `history` = earlier `{"role", "content"}` messages (the brain's thread);
        `resume` is ignored: an HTTP model has no server-side session."""
        from spectre.assistant.tools import TOOLS

        try:
            pid, name = split_ref(model or "")
            provider = self.providers.get(pid)
        except ProviderError as exc:
            return Reply(str(exc), "", True)
        if provider.needs_key and not self.providers.key(provider):
            return Reply(
                f"Il manque la clé de {provider.label} ({provider.key_env}) : ajoute-la dans le "
                f"fichier .env du dossier de Spectre.",
                "",
                True,
            )
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        messages += [dict(m) for m in history]
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {"model": name, "messages": messages}
        if with_tools:
            body["tools"] = tool_schemas(list(TOOLS.values()))
        url = f"{provider.base_url}/chat/completions"
        headers = self.providers.headers(provider)
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                data = self.transport(url, headers, body, self.config.brain_timeout_s)
            except (OSError, ValueError) as exc:
                return Reply(f"{provider.label} a échoué : {str(exc)[:300]}", "", True)
            choices = data.get("choices") or []
            message = choices[0].get("message", {}) if choices else {}
            calls = message.get("tool_calls") or []
            if not calls:
                text = str(message.get("content") or "").strip()
                if not text:
                    error = data.get("error")
                    detail = error.get("message") if isinstance(error, dict) else error
                    return Reply(
                        f"{provider.label} a échoué : {detail or 'réponse vide'}", "", True
                    )
                return Reply(text, "", False)
            messages.append(
                {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
            )
            for call in calls:
                function = call.get("function", {})
                try:
                    args = json.loads(function.get("arguments") or "{}")
                except ValueError:
                    args = None
                if not isinstance(args, dict):
                    result = "ÉCHEC : arguments illisibles (JSON attendu)"
                else:
                    result = self.call_tool(str(function.get("name", "")), args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": result[:MAX_TOOL_RESULT],
                    }
                )
        return Reply(f"{provider.label} a enchaîné trop d'appels d'outils sans conclure.", "", True)
