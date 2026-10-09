"""Tests for v0.5: agents added by the user, prompt caching and cache-aware costs."""

from __future__ import annotations

from pathlib import Path

import pytest

from spectre.config import load_prompt_cache
from spectre.costs import compute_cost, format_cost_table, make_record, usage_from_message
from spectre.errors import ConfigurationError, MissingAPIKeyError
from spectre.graph import build_graph, next_step, pipeline_steps, run
from spectre.nodes import make_scribe_node, make_warden_node
from spectre.plugins import ExtraAgent, agents_file, load_extra_agents
from spectre.steps import cached, content_text
from tests.conftest import fake, make_ai

TRANSLATOR = """
[[agent]]
name = "traducteur"
after = "warden"
prompt = "Traduis en anglais."
writes = "final_text"
effort = "low"

[[agent]]
name = "relecteur"
after = "scribe"
prompt = "Raccourcis le brouillon."
writes = "draft"
model = "claude-haiku-4-5"
temperature = 0.3
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "agents.toml"
    path.write_text(text, encoding="utf-8")
    return path


# ---- agents file ---------------------------------------------------------------------------


def test_load_extra_agents(tmp_path: Path) -> None:
    agents = load_extra_agents(_write(tmp_path, TRANSLATOR))
    assert [(a.name, a.after, a.reads, a.writes) for a in agents] == [
        ("traducteur", "warden", "final_text", "final_text"),
        ("relecteur", "scribe", "draft", "draft"),
    ]
    assert agents[0].spec.model == "claude-sonnet-5-5" and agents[0].spec.effort == "low"
    assert agents[1].spec.temperature == 0.3 and agents[1].spec.effort is None
    assert agents[0].step.writes == "final_text"


def test_agents_file_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert agents_file({}) is None and load_extra_agents() == []  # cwd is an empty tmp dir
    (tmp_path / "spectre-agents.toml").write_text(TRANSLATOR, encoding="utf-8")
    assert agents_file({}) == Path("spectre-agents.toml")
    other = _write(tmp_path, TRANSLATOR)
    assert agents_file({"SPECTRE_AGENTS_FILE": str(other)}) == other
    with pytest.raises(ConfigurationError, match="introuvable"):
        agents_file({"SPECTRE_AGENTS_FILE": str(tmp_path / "absent.toml")})


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("[[agent]\n", "impossible de lire"),
        ('agent = "x"', "tables"),
        ("agent = [1]", "table"),
        ('[[agent]]\nname = "x"\nfoo = 1', "inconnues"),
        ('[[agent]]\nname = "Scribe"', "nom invalide"),
        ('[[agent]]\nname = "scribe"', "nom invalide"),
        ('[[agent]]\nname = "ok"\nafter = "nulle_part"', "after"),
        ('[[agent]]\nname = "ok"\nafter = "warden"', "prompt"),
        ('[[agent]]\nname = "ok"\nafter = "warden"\nprompt = "p"\nwrites = "x"', "writes"),
        (
            '[[agent]]\nname = "ok"\nafter = "warden"\nprompt = "p"\nwrites = "draft"\nreads = "x"',
            "reads",
        ),
        (
            '[[agent]]\nname = "ok"\nafter = "warden"\nprompt = "p"\nwrites = "draft"\n'
            "temperature = 0.5",
            "temperature",
        ),
        (
            '[[agent]]\nname = "ok"\nafter = "warden"\nprompt = "p"\nwrites = "draft"\n'
            'model = "claude-haiku-4-5"\neffort = "low"',
            "effort",
        ),
        (
            '[[agent]]\nname = "ok"\nafter = "warden"\nprompt = "p"\nwrites = "draft"\n'
            'model = "claude-haiku-4-5"\ntemperature = "chaud"',
            "nombre",
        ),
        (
            '[[agent]]\nname = "ok"\nafter = "warden"\nprompt = "p"\nwrites = "draft"\n'
            'effort = "énorme"',
            "effort",
        ),
        (
            '[[agent]]\nname = "ok"\nafter = "warden"\nprompt = "p"\nwrites = "draft"\n'
            "max_tokens = 0",
            "max_tokens",
        ),
        (
            '[[agent]]\nname = "ok"\nafter = "warden"\nprompt = "p"\nwrites = "draft"\n'
            '[[agent]]\nname = "ok"\nafter = "warden"\nprompt = "p"\nwrites = "draft"\n',
            "double",
        ),
    ],
)
def test_bad_agents_file(tmp_path: Path, body: str, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load_extra_agents(_write(tmp_path, body))


# ---- the graph with added agents ------------------------------------------------------------


def _core() -> dict[str, object]:
    return {
        "scout": fake("scout", make_ai("BRIEF")),
        "scribe": fake("scribe", make_ai("DRAFT")),
        "warden": fake("warden", make_ai("FINAL")),
    }


def test_added_agents_run_in_place(tmp_path: Path) -> None:
    extras = load_extra_agents(_write(tmp_path, TRANSLATOR))
    assert [s.name for s in pipeline_steps(extras)] == [
        "scout",
        "scribe",
        "relecteur",
        "warden",
        "traducteur",
    ]
    translator = fake("traducteur", make_ai("ENGLISH"))
    shortener = fake("relecteur", make_ai("SHORT"))
    models = {**_core(), "traducteur": translator, "relecteur": shortener}
    result = run("Un poème", models=models, extra_agents=extras)  # type: ignore[arg-type]
    assert (result.draft, result.final_text) == ("SHORT", "ENGLISH")
    assert "<texte>\nFINAL\n</texte>" in translator.received[0][1].content
    assert "Un poème" in translator.received[0][1].content
    assert [r["agent"] for r in result.usage][-1] == "traducteur"


def test_added_agents_need_a_model_or_a_key(tmp_path: Path) -> None:
    extras = load_extra_agents(_write(tmp_path, TRANSLATOR))
    with pytest.raises(MissingAPIKeyError):
        build_graph(_core(), extra_agents=extras)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="agents inconnus"):
        build_graph({**_core(), "fantome": fake("x")})  # type: ignore[arg-type]


def test_added_agents_are_built_from_their_spec(tmp_path: Path, api_key: str) -> None:
    extras = load_extra_agents(_write(tmp_path, TRANSLATOR))
    graph = build_graph(_core(), extra_agents=extras)  # type: ignore[arg-type]
    assert {"traducteur", "relecteur"} <= set(graph.nodes)


def test_revision_round_then_added_agent() -> None:
    reject = 'V1\n=== VERDICT ===\n{"approved": false, "issues": ["Plus court"]}'
    extra = ExtraAgent(
        "traducteur",
        "warden",
        "Traduis.",
        "final_text",
        "final_text",
        load_extra_agents.__globals__["DEFAULT_SPECS"]["scribe"],
    )
    models = {
        "scout": fake("scout", make_ai("B")),
        "scribe": fake("scribe", make_ai("D1"), make_ai("D2")),
        "warden": fake("warden", make_ai(reject), make_ai("V2")),
        "traducteur": fake("traducteur", make_ai("EN")),
    }
    result = run("x", models=models, extra_agents=[extra])  # type: ignore[arg-type]
    agents = [r["agent"] for r in result.usage]
    assert agents == ["scout", "scribe", "warden", "scribe", "warden", "traducteur"]
    assert result.final_text == "EN" and result.revisions == 1
    order = ["scout", "scribe", "warden", "traducteur"]
    assert next_step(order, "warden", {"approved": False, "revisions": 0}, 1) == "scribe"
    assert next_step(order, "warden", {"approved": True}, 1) == "traducteur"
    assert next_step(order, "traducteur", {}, 1) is None


def test_web_stream_hides_added_agents_unless_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spectre.web.pipeline import stream_run

    monkeypatch.setenv("SPECTRE_AGENTS_FILE", str(_write(tmp_path, TRANSLATOR)))

    def models() -> dict[str, object]:
        return {
            **_core(),
            "traducteur": fake("traducteur", make_ai("EN")),
            "relecteur": fake("relecteur", make_ai("SHORT")),
        }

    hidden = list(stream_run("x", demo=False, models=models()))  # type: ignore[arg-type]
    assert {e.get("agent") for e in hidden if e["type"] == "agent_start"} == {
        "scout",
        "scribe",
        "warden",
    }
    assert hidden[-1]["final_text"] == "EN" and len(hidden[-1]["usage"]) == 5
    shown = list(stream_run("x", demo=False, models=models(), include_extras=True))  # type: ignore[arg-type]
    starts = [e["agent"] for e in shown if e["type"] == "agent_start"]
    assert starts == ["scout", "scribe", "relecteur", "warden", "traducteur"]


# ---- prompt caching -------------------------------------------------------------------------


def test_prompt_cache_setting() -> None:
    assert load_prompt_cache({}) is False
    assert load_prompt_cache({"SPECTRE_PROMPT_CACHE": "on"}) is True
    with pytest.raises(ConfigurationError, match="SPECTRE_PROMPT_CACHE"):
        load_prompt_cache({"SPECTRE_PROMPT_CACHE": "peut-être"})


def test_cached_content() -> None:
    assert cached("A", "B", False) == "AB" and cached("A", "", True) == "A"
    blocks = cached("A", "B", True)
    assert blocks == [
        {"type": "text", "text": "A", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "B"},
    ]
    assert content_text(blocks) == "AB" and content_text(["x", {"text": "y"}]) == "xy"
    assert content_text("brut") == "brut"


STATE = {"request": "Résume ce rapport", "brief": "B", "draft": "D", "usage": []}


def test_scribe_and_warden_mark_the_shared_prefix() -> None:
    warden = fake("warden", make_ai("F"))
    make_warden_node(warden, cache=True)(STATE)  # type: ignore[arg-type]
    first, second = warden.received[0][1].content
    assert first["cache_control"] == {"type": "ephemeral"} and "Résume ce rapport" in first["text"]
    assert "<brouillon>" in second["text"] and "cache_control" not in second
    scribe = fake("scribe", make_ai("D1"), make_ai("D2"))
    node = make_scribe_node(scribe, cache=True)
    node(STATE)  # type: ignore[arg-type]
    assert isinstance(scribe.received[0][1].content, str)  # nothing after the prefix yet
    revising = {**STATE, "approved": False, "issues": ["Court"], "final_text": "V1"}
    node(revising)  # type: ignore[arg-type]
    prefix, rest = scribe.received[1][1].content
    assert "cache_control" in prefix and "- Court" in rest["text"]


def test_graph_passes_the_cache_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_PROMPT_CACHE", "1")
    models = _core()
    run("x", models=models)  # type: ignore[arg-type]
    assert isinstance(models["warden"].received[0][1].content, list)  # type: ignore[attr-defined]


# ---- costs with cache and batch -------------------------------------------------------------


def test_cache_and_batch_prices() -> None:
    # 1M input of which 600k read and 200k written, 0 output, on Opus 5.5 ($4 / read $0.20)
    expected = 0.2 * 4 + 0.2 * 4 * 1.25 + 0.6 * 0.20
    assert compute_cost(
        "claude-opus-5-5", 1_000_000, 0, cache_read=600_000, cache_write=200_000
    ) == pytest.approx(expected)
    assert compute_cost("claude-sonnet-5-5", 1_000_000, 1_000_000, batch=True) == pytest.approx(6.0)
    record = make_record("warden", "claude-opus-5-5", 100, 10, 40, 20, batch=True)
    assert (record["cache_read_tokens"], record["cache_write_tokens"]) == (40, 20)


def test_usage_reads_cache_details() -> None:
    ai = make_ai("x", input_tokens=1000, output_tokens=10)
    ai.usage_metadata["input_token_details"] = {  # type: ignore[index]
        "cache_read": 700,
        "cache_creation": 0,
        "ephemeral_5m_input_tokens": 200,
        "ephemeral_1h_input_tokens": None,
    }
    record = usage_from_message("scribe", "claude-sonnet-5-5", ai)
    assert (record["cache_read_tokens"], record["cache_write_tokens"]) == (700, 200)
    assert record["cost_usd"] == pytest.approx((100 * 2 + 200 * 2.5 + 700 * 0.2 + 10 * 10) / 1e6)


def test_cost_table_shows_cache_columns_when_used() -> None:
    plain = format_cost_table([make_record("scout", "claude-haiku-4-5", 10, 5)])
    assert "Cache" not in plain
    table = format_cost_table([make_record("scribe", "claude-sonnet-5-5", 1000, 50, 600, 100)])
    header, _, row, *_rest, total = table.splitlines()
    assert header.split()[:6] == ["Agent", "Modèle", "Entrée", "Cache", "lu", "Cache"]
    assert row.split()[2:5] == ["1000", "600", "100"] and total.split()[1:4] == [
        "1000",
        "600",
        "100",
    ]
