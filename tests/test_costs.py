"""Tests for spectre.costs."""

from __future__ import annotations

import pytest

from spectre.costs import compute_cost, format_cost_table, total_cost, usage_from_message
from spectre.state import UsageRecord
from tests.conftest import make_ai


def _rec(agent: str, model: str, i: int, o: int, cost: float | None) -> UsageRecord:
    return UsageRecord(
        agent=agent, model=model, input_tokens=i, output_tokens=o, cost_usd=cost, truncated=False
    )


@pytest.mark.parametrize(
    ("model", "inp", "out", "expected"),
    [
        ("claude-haiku-4-5", 1_000_000, 1_000_000, 6.0),
        ("claude-sonnet-5-5", 1_000_000, 1_000_000, 12.0),
        ("claude-opus-5-5", 1_000_000, 1_000_000, 24.0),
        ("claude-haiku-4-5", 1000, 200, 0.002),
        ("claude-sonnet-5-5", 2000, 3000, 0.034),
        ("claude-opus-5-5", 4000, 1000, 0.036),
        ("claude-opus-5-5", 0, 0, 0.0),
        ("claude-sonnet-5-5", 1, 1, 0.000012),
    ],
)
def test_compute_cost_exact(model: str, inp: int, out: int, expected: float) -> None:
    assert compute_cost(model, inp, out) == pytest.approx(expected, abs=1e-12)


def test_compute_cost_unknown_model_warns() -> None:
    with pytest.warns(RuntimeWarning, match="claude-mystery"):
        assert compute_cost("claude-mystery", 10, 10) is None


def test_usage_from_message() -> None:
    record = usage_from_message(
        "scribe", "claude-sonnet-5-5", make_ai("x", input_tokens=2000, output_tokens=3000)
    )
    assert record == {
        "agent": "scribe",
        "model": "claude-sonnet-5-5",
        "input_tokens": 2000,
        "output_tokens": 3000,
        "cost_usd": pytest.approx(0.034),
        "truncated": False,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def test_usage_from_message_without_usage_metadata() -> None:
    record = usage_from_message("scout", "claude-haiku-4-5", make_ai("x", usage=False))
    assert record["input_tokens"] == 0
    assert record["output_tokens"] == 0
    assert record["cost_usd"] == 0.0


def test_usage_from_message_unknown_model() -> None:
    with pytest.warns(RuntimeWarning):
        record = usage_from_message("warden", "other-model", make_ai("x"))
    assert record["cost_usd"] is None
    assert record["input_tokens"] == 100


def test_total_cost() -> None:
    usage = [
        _rec("scout", "a", 1, 1, 0.002),
        _rec("scribe", "b", 1, 1, 0.034),
        _rec("warden", "c", 1, 1, 0.036),
    ]
    assert total_cost(usage) == pytest.approx(0.072)


def test_total_cost_ignores_unknown_and_none_when_all_unknown() -> None:
    assert total_cost([_rec("a", "m", 1, 1, None), _rec("b", "m", 1, 1, 0.5)]) == 0.5
    assert total_cost([_rec("a", "m", 1, 1, None)]) is None
    assert total_cost([]) is None


def test_format_cost_table() -> None:
    usage = [
        _rec("scout", "claude-haiku-4-5", 1000, 200, 0.002),
        _rec("warden", "unknown-model", 4000, 1000, None),
    ]
    table = format_cost_table(usage)
    lines = table.splitlines()
    assert lines[0].split() == ["Agent", "Modèle", "Entrée", "Sortie", "Coût", "($)"]
    assert set(lines[1].replace(" ", "")) == {"-"}
    assert lines[2].split() == ["scout", "claude-haiku-4-5", "1000", "200", "0.002000"]
    assert lines[3].split() == ["warden", "unknown-model", "4000", "1000", "n/d"]
    assert lines[-1].split() == ["Total", "5000", "1200", "0.002000"]
    assert all(line == line.rstrip() for line in lines)


def test_format_cost_table_empty() -> None:
    table = format_cost_table([])
    assert table.splitlines()[-1].split() == ["Total", "0", "0", "n/d"]


def test_usage_from_message_truncated() -> None:
    record = usage_from_message("warden", "claude-opus-5-5", make_ai("x"), truncated=True)
    assert record["truncated"] is True


def test_compute_cost_fallback_models_are_priced() -> None:
    assert compute_cost("claude-opus-4-8", 1_000_000, 1_000_000) == 30.0
    assert compute_cost("claude-opus-5", 1_000_000, 1_000_000) == 30.0
    assert compute_cost("claude-sonnet-5", 1_000_000, 1_000_000) == 12.0
