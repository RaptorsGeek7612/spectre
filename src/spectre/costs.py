"""Token usage extraction and USD cost computation."""

from __future__ import annotations

import warnings
from collections.abc import Iterable

from langchain_core.messages import AIMessage

from spectre.config import PRICING
from spectre.state import UsageRecord


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Return the USD cost of a call, or None (with a warning) if the model has no price."""
    price = PRICING.get(model)
    if price is None:
        warnings.warn(
            f"Prix inconnu pour le modèle {model!r} : coût non calculé.",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    cost = input_tokens * price.input_per_mtok / 1e6 + output_tokens * price.output_per_mtok / 1e6
    return round(cost, 6)


def usage_from_message(
    agent: str, model: str, message: AIMessage, *, truncated: bool = False
) -> UsageRecord:
    """Build a UsageRecord from `message.usage_metadata` (missing metadata counts as 0)."""
    metadata = message.usage_metadata
    input_tokens = int(metadata.get("input_tokens", 0)) if metadata else 0
    output_tokens = int(metadata.get("output_tokens", 0)) if metadata else 0
    return UsageRecord(
        agent=agent,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=compute_cost(model, input_tokens, output_tokens),
        truncated=truncated,
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
    header = ("Agent", "Modèle", "Entrée", "Sortie", "Coût ($)")
    rows = [
        (
            r["agent"],
            r["model"],
            str(r["input_tokens"]),
            str(r["output_tokens"]),
            _fmt_cost(r["cost_usd"]),
        )
        for r in records
    ]
    total = (
        "Total",
        "",
        str(sum(r["input_tokens"] for r in records)),
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
