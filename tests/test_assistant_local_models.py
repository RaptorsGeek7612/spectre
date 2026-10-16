"""The right LM Studio model for each agent, applied only when the user asks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import local_models as lm
from spectre.assistant import tools
from spectre.assistant.actions import ActionError
from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate
from spectre.assistant.providers import Providers

GB = 1_000_000_000


def model(key: str, params: str, size: float, bits: int = 4, **caps: Any) -> dict[str, Any]:
    return {
        "type": "llm",
        "key": key,
        "params_string": params,
        "size_bytes": int(size * GB),
        "quantization": {"bits_per_weight": bits},
        "max_context_length": caps.pop("context", 32_768),
        "capabilities": caps,
    }


MODELS = [
    model(
        "google/gemma-4-12b",
        "12B",
        7.6,
        vision=True,
        trained_for_tool_use=True,
        reasoning={"default": "on"},
        context=262_144,
    ),
    model("qwen3.5-9b-claude-code", "9B", 5.6, trained_for_tool_use=True, context=262_144),
    model("mistralai/ministral-3-3b", "3B", 3.0, vision=True, trained_for_tool_use=True),
    model("dolphin-2.6-mistral-7b", "7B", 4.1),
    model("heretic-uncensored-12b", "12B", 7.1, trained_for_tool_use=True),
    model("prism-ml/bonsai-27b", "27B", 4.7, bits=1, trained_for_tool_use=True),
    model("qwen3.6-40b", "40B", 16.6, trained_for_tool_use=True),  # too heavy for 16 GB
    model("broken", "20B", 0.0),
    {"type": "embedding", "key": "nomic-embed", "size_bytes": GB, "params_string": "1B"},
]


@pytest.fixture(autouse=True)
def pc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lm, "ram_gb", lambda: 16.0)
    monkeypatch.setattr(lm, "_fetch", lambda: MODELS)


def best(key: str) -> str:
    return str(lm.ranking(key, MODELS, 16.0)[0][0][1]["key"])


def test_each_trade_gets_its_model() -> None:
    assert best("sonnet") == "qwen3.5-9b-claude-code"  # Gétro runs missions: a coder
    assert best("chatgpt") == "google/gemma-4-12b"  # Kyra needs vision
    assert best("cursor") == "google/gemma-4-12b"  # Octavya: reasoning and long context
    assert best("haiku") == "mistralai/ministral-3-3b"  # the verifier must be fast


def test_heavy_broken_old_and_uncensored_models_lose() -> None:
    ranked, heavy = lm.ranking("cursor", MODELS, 16.0)
    keys = [m["key"] for _, m, _ in ranked]
    assert heavy == 1 and "qwen3.6-40b" not in keys and "broken" not in keys
    assert "nomic-embed" not in keys
    assert keys.index("heretic-uncensored-12b") > keys.index("google/gemma-4-12b")
    reasons = dict((m["key"], r) for _, m, r in ranked)
    assert "ancien" in reasons["dolphin-2.6-mistral-7b"]
    assert any("très compressé" in r for r in reasons["prism-ml/bonsai-27b"])


def test_params_parsing() -> None:
    assert lm._params("12B") == 12 and lm._params("8x3B") == 24
    assert lm._params("855M") == pytest.approx(0.855) and lm._params("") == 0


def test_recommend_explains_and_changes_nothing() -> None:
    text = lm.recommend(AssistantConfig(), "Kyra")
    assert text.startswith("Kyra (multimédia")
    assert "1. lmstudio:google/gemma-4-12b" in text and "Rien n'est changé" in text
    every = lm.recommend(AssistantConfig(), "")
    assert "• Gétro (exécution des missions) : qwen3.5-9b-claude-code" in every
    with pytest.raises(ActionError, match="agent inconnu"):
        lm.recommend(AssistantConfig(), "Zorglub")


def test_lmstudio_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def down() -> list[dict[str, Any]]:
        raise OSError("refused")

    monkeypatch.setattr(lm, "_fetch", down)
    with pytest.raises(ActionError, match="LM Studio ne répond pas"):
        lm.recommend(AssistantConfig(), "Kyra")
    assert lm.installed() == set()


def test_names_resolve() -> None:
    assert lm.resolve_agent("kyra") == "chatgpt" and lm.resolve_agent("Gétro") == "sonnet"
    assert lm.resolve_agent("KAITO") == "haiku" and lm.resolve_agent("cursor") == "cursor"


def test_set_agent_engine_only_for_spectre_and_reversible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Providers, "models", lambda self, pid, timeout=5.0: [])
    root = tmp_path / "assistant"
    database = Database(root / "spectre.db")
    gate, ctx = Gate(database), tools.make_context(database, root, [str(tmp_path)])
    run = lambda tool, **args: tools.execute(gate, ctx, tool, args)  # noqa: E731

    assert run("set_agent_engine", agent="Kyra", engine="lmstudio:google/gemma-4-12b") == (
        "Kyra travaille désormais sur lmstudio:google/gemma-4-12b (d'origine : son outil "
        "d'origine (Codex))."
    )
    assert AssistantConfig.load(root).agent_engines == {"chatgpt": "lmstudio:google/gemma-4-12b"}
    assert run("set_agent_engine", agent="Kyra", engine="lmstudio:inconnu").startswith(
        "ÉCHEC : modèle absent de LM Studio"
    )
    assert run("set_agent_engine", agent="Kyra", engine="origine").startswith(
        "Kyra revient à son moteur d'origine"
    )
    assert AssistantConfig.load(root).agent_engines == {}

    assert "Gétro travaille désormais sur lmstudio:qwen3.5-9b-claude-code" in run(
        "set_agent_engine", agent="Gétro", engine="lmstudio:qwen3.5-9b-claude-code"
    )
    assert run("set_agent_engine", agent="Gétro", engine="") == (
        "Gétro revient à son moteur d'origine : sonnet."
    )
    assert AssistantConfig.load(root).mission_model == "sonnet"

    ctx.agent = "chatgpt"  # an agent never moves itself or a colleague
    assert run("set_agent_engine", agent="Kyra", engine="lmstudio:x").startswith("REFUSÉ")
    assert "Kyra" in run("recommend_engine", agent="Kyra")
    database.close()
