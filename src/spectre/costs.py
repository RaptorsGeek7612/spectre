"""Token usage extraction and USD cost computation."""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from typing import Any

from langchain_core.messages import AIMessage

from spectre.config import BATCH_FACTOR, CACHE_WRITE_FACTOR, PRICING
from spectre.state import UsageRecord


def compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_read: int = 0,
    cache_write: int = 0,
    batch: bool = False,
) -> float | None:
    """Return the USD cost of a call, or None (with a warning) if the model has no price.

    `input_tokens` counts every input token, cached or not; `cache_read` / `cache_write` say
    how many of them were read from / written to the cache. `batch` applies the 50% discount.
    """
    price = PRICING.get(model)
    if price is None:
        warnings.warn(
            f"Prix inconnu pour le modèle {model!r} : coût non calculé.",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    uncached = max(0, input_tokens - cache_read - cache_write)
    cost = (
        uncached * price.input_per_mtok
        + cache_write * price.input_per_mtok * CACHE_WRITE_FACTOR
        + cache_read * price.cache_read_per_mtok
        + output_tokens * price.output_per_mtok
    ) / 1e6
    return round(cost * (BATCH_FACTOR if batch else 1.0), 6)


def usage_from_message(
    agent: str, model: str, message: AIMessage, *, truncated: bool = False
) -> UsageRecord:
    """Build a UsageRecord from `message.usage_metadata` (missing metadata counts as 0)."""
    metadata = message.usage_metadata
    input_tokens = int(metadata.get("input_tokens", 0)) if metadata else 0
    output_tokens = int(metadata.get("output_tokens", 0)) if metadata else 0
    details: dict[str, Any] = dict(metadata.get("input_token_details") or {}) if metadata else {}
    cache_read = int(details.get("cache_read") or 0)
    # langchain-anthropic splits writes by TTL when the API does (`ephemeral_5m/1h_...`).
    cache_write = int(details.get("cache_creation") or 0) + sum(
        int(details.get(key) or 0)
        for key in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
    )
    return make_record(
        agent, model, input_tokens, output_tokens, cache_read, cache_write, truncated
    )


def make_record(
    agent: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_write: int = 0,
    truncated: bool = False,
    *,
    batch: bool = False,
) -> UsageRecord:
    """A UsageRecord with its cost (`input_tokens` includes the cached tokens)."""
    return UsageRecord(
        agent=agent,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=compute_cost(
            model,
            input_tokens,
            output_tokens,
            cache_read=cache_read,
            cache_write=cache_write,
            batch=batch,
        ),
        truncated=truncated,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )


def total_cost(usage: Iterable[UsageRecord]) -> float | None:
    """Sum of known costs; None if no record has a known cost."""
    costs = [record["cost_usd"] for record in usage if record["cost_usd"] is not None]
    if not costs:
        return None
    return round(sum(costs), 6)


def _fmt_cost(cost: float | None) -> str:
    return "n/d" if cost is None else f"{cost:.6f}"


def format_cost_table(usage: Iterable[UsageRecord]) -> str:
    """Render a plain-text cost table (one row per agent plus a total row)."""
    records = list(usage)
    cache = any(r.get("cache_read_tokens") or r.get("cache_write_tokens") for r in records)

    def cache_cols(read: int, write: int) -> tuple[str, ...]:
        return (str(read), str(write)) if cache else ()

    header = (
        "Agent",
        "Modèle",
        "Entrée",
        *(("Cache lu", "Cache écrit") if cache else ()),
        "Sortie",
        "Coût ($)",
    )
    rows = [
        (
            r["agent"],
            r["model"],
            str(r["input_tokens"]),
            *cache_cols(r.get("cache_read_tokens", 0), r.get("cache_write_tokens", 0)),
            str(r["output_tokens"]),
            _fmt_cost(r["cost_usd"]),
        )
        for r in records
    ]
    total = (
        "Total",
        "",
        str(sum(r["input_tokens"] for r in records)),
        *cache_cols(
            sum(r.get("cache_read_tokens", 0) for r in records),
            sum(r.get("cache_write_tokens", 0) for r in records),
        ),
        str(sum(r["output_tokens"] for r in records)),
        _fmt_cost(total_cost(records)),
    )
    table = [header, *rows, total]
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]

    def fmt(row: tuple[str, ...]) -> str:
        left = [row[i].ljust(widths[i]) for i in range(2)]
        right = [row[i].rjust(widths[i]) for i in range(2, len(row))]
        return "  ".join(left + right).rstrip()

    separator = "  ".join("-" * w for w in widths)
    lines = [fmt(header), separator, *(fmt(row) for row in rows), separator, fmt(total)]
    return "\n".join(lines)
