"""LLM providers: any engine an agent or a role of Spectre can run on.

An engine is named by a reference:
- `opus`, `sonnet`, `haiku`: Claude through the Claude Code CLI (the subscription);
- `chatgpt`, `mistral`: the Codex and Vibe CLIs (the user's ChatGPT and Le Chat accounts);
- `cursor`, `antigravity`: the Cursor and Antigravity CLIs (same idea); `simon`: Simon's model;
- `<provider>:<model>`: any OpenAI-compatible endpoint, e.g. `lmstudio:google/gemma-4-e4b`,
  `ollama:qwen3:8b`, `openrouter:deepseek/deepseek-chat`, `groq:llama-3.3-70b-versatile`.

Built-in providers cover local servers (LM Studio, Ollama: free, nothing leaves the PC) and the
main hosted APIs; `providers.json` in the assistant folder adds custom ones. API keys are never
stored there: each provider names an environment variable, read from the process environment
or from the assistant folder's `.env` (outside the repository).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CLI_ENGINES = (
    "opus",
    "sonnet",
    "haiku",
    "chatgpt",
    "mistral",
    "cursor",
    "antigravity",
    "simon",
    "shelby",
    "ysyss",
    "lexy",
    "charlotte",
    "celya",
    "monty",
)
MAX_MODEL = 120


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    base_url: str  # OpenAI-compatible root, ending in /v1 (or the provider's equivalent)
    key_env: str = ""  # environment variable holding the API key; empty for local servers
    local: bool = False

    @property
    def needs_key(self) -> bool:
        return bool(self.key_env)


BUILTIN: tuple[Provider, ...] = (
    Provider("lmstudio", "LM Studio (local)", "http://127.0.0.1:1234/v1", local=True),
    Provider("ollama", "Ollama (local)", "http://127.0.0.1:11434/v1", local=True),
    Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    Provider("groq", "Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    Provider(
        "gemini",
        "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
    ),
    Provider("mistralapi", "Mistral (API)", "https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    Provider("openai", "OpenAI (API)", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    Provider("xai", "xAI Grok", "https://api.x.ai/v1", "XAI_API_KEY"),
    Provider("anthropic", "Anthropic (API)", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY"),
)


class ProviderError(ValueError):
    """An unknown provider or a malformed engine reference (the message is for the user)."""


def split_ref(ref: str) -> tuple[str, str]:
    """`"lmstudio:google/gemma"` -> `("lmstudio", "google/gemma")`; a CLI engine -> `("", ref)`.
    The model part may itself contain colons (`ollama:qwen3:8b`)."""
    ref = ref.strip()
    provider, sep, model = ref.partition(":")
    return (provider.strip().lower(), model.strip()) if sep else ("", ref)


def read_env_file(path: Path) -> dict[str, str]:
    """`KEY=value` lines (comments, blanks and quotes handled); missing file -> {}."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def write_env_value(root: Path, name: str, value: str) -> None:
    """Set (or, with an empty value, remove) `NAME=value` in the assistant folder's `.env`."""
    path = root / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    kept = [ln for ln in lines if not ln.strip().removeprefix("export ").startswith(f"{name}=")]
    if value:
        kept.append(f"{name}={value}")
    root.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")


class Providers:
    """The built-in providers plus the user's `providers.json`, and their API keys."""

    def __init__(self, root: Path, environ: dict[str, str] | None = None) -> None:
        self.root = root
        self.environ = os.environ if environ is None else environ

    def all(self) -> dict[str, Provider]:
        found = {p.id: p for p in BUILTIN}
        try:
            custom = json.loads((self.root / "providers.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            custom = []
        for item in custom if isinstance(custom, list) else []:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id", "")).strip().lower()
            url = str(item.get("base_url", "")).strip().rstrip("/")
            if not pid or not url.startswith(("http://", "https://")) or pid in CLI_ENGINES:
                continue
            found[pid] = Provider(
                pid,
                str(item.get("label") or pid),
                url,
                str(item.get("key_env", "")).strip(),
                url.startswith(("http://127.0.0.1", "http://localhost")),
            )
        return found

    def get(self, pid: str) -> Provider:
        provider = self.all().get(pid.strip().lower())
        if provider is None:
            known = ", ".join(self.all())
            raise ProviderError(f"fournisseur inconnu « {pid} » ; au choix : {known}")
        return provider

    def key(self, provider: Provider) -> str:
        if not provider.key_env:
            return ""
        value = self.environ.get(provider.key_env, "")
        return value or read_env_file(self.root / ".env").get(provider.key_env, "")

    def ready(self, provider: Provider) -> bool:
        """Usable without a network check: local, or its key is set."""
        return provider.local or bool(self.key(provider))

    def check(self, ref: str) -> str:
        """The normalised reference, or ProviderError if it cannot name an engine."""
        provider, model = split_ref(ref)
        if not provider:
            from spectre.assistant.config import ENGINE_ALIASES

            name = ENGINE_ALIASES.get(model.lower(), model.lower())
            if name in CLI_ENGINES:
                return name
            raise ProviderError(
                f"moteur inconnu « {ref} » ; au choix : {', '.join(CLI_ENGINES)} ou "
                "fournisseur:modèle (par exemple lmstudio:google/gemma-4-e4b)"
            )
        found = self.get(provider)
        if not model or len(model) > MAX_MODEL or any(c.isspace() for c in model):
            raise ProviderError(f"nom de modèle invalide pour {found.label} : « {model} »")
        return f"{found.id}:{model}"

    def models(self, pid: str, timeout: float = 5.0) -> list[str]:
        """The provider's model list (`GET /models`); empty when it cannot be reached."""
        return self.listing(pid, timeout)[1]

    def listing(self, pid: str, timeout: float = 5.0) -> tuple[bool, list[str]]:
        """(answered, models): a local server can run with no model installed yet."""
        provider = self.get(pid)
        if provider.needs_key and not self.key(provider):
            return False, []
        request = urllib.request.Request(
            f"{provider.base_url}/models", headers=self.headers(provider)
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, urllib.error.URLError):
            return False, []
        items = (data.get("data") or []) if isinstance(data, dict) else []  # Ollama: null
        return True, sorted(str(m.get("id")) for m in items if isinstance(m, dict) and m.get("id"))

    def headers(self, provider: Provider) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "User-Agent": "Spectre"}
        key = self.key(provider)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if provider.id == "anthropic" and key:  # its OpenAI-compatible layer also takes this
            headers["x-api-key"] = key
        if provider.id == "openrouter":
            headers["X-Title"] = "Spectre"
        return headers

    def describe(self) -> list[dict[str, Any]]:
        """For the interface: each provider, whether it is usable, never the key itself."""
        return [
            {
                "id": p.id,
                "label": p.label,
                "base_url": p.base_url,
                "local": p.local,
                "key_env": p.key_env,
                "ready": self.ready(p),
            }
            for p in self.all().values()
        ]
