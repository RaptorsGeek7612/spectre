"""Real Anthropic API run (opt-in: `uv run pytest -m live`, needs ANTHROPIC_API_KEY)."""

from __future__ import annotations

import pytest

from spectre.config import has_api_key, load_env
from spectre.graph import run


@pytest.mark.live
def test_live_short_run() -> None:
    load_env()
    if not has_api_key():
        pytest.skip("ANTHROPIC_API_KEY absente")
    result = run("Écris une seule phrase qui décrit la pluie.")
    assert result.final_text.strip()
    assert [record["agent"] for record in result.usage] == ["scout", "scribe", "warden"]
    assert result.total_cost_usd is not None
