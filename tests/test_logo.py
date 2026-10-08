"""Tests for the logo generator and the logo assets shipped with the web UI."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "spectre" / "web" / "static"


def _make_logo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_logo", ROOT / "tools" / "make_logo.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_is_deterministic_and_matches_the_shipped_files() -> None:
    logo = _make_logo()
    assert logo.logo_svg() == logo.logo_svg()
    assert (STATIC / "logo.svg").read_text(encoding="utf-8") == logo.logo_svg()
    assert (STATIC / "favicon.svg").read_text(encoding="utf-8") == logo.favicon()
    for page in logo.PAGES:
        assert logo.symbol() in page.read_text(encoding="utf-8")


def test_small_mark_keeps_the_pipeline_classes() -> None:
    symbol = _make_logo().symbol()
    for agent, wave in (("scout", "486"), ("scribe", "546"), ("warden", "589")):
        assert f'class="mk-l mk-{wave} agent-{agent}"' in symbol
    assert symbol.count('class="mk-l ') == 7


def test_ids_are_unique_per_document() -> None:
    for page in ("index.html", "assistant.html"):
        ids = re.findall(r'\bid="([^"]+)"', (STATIC / page).read_text(encoding="utf-8"))
        assert len(ids) == len(set(ids)), page
    ids = re.findall(r'\bid="([^"]+)"', (STATIC / "logo.svg").read_text(encoding="utf-8"))
    assert ids and all(i.startswith("lg-") for i in ids)


def test_pages_use_the_full_logo() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<img class="mark mark-hero" src="logo.svg"' in index
    assert '<img class="mark mark-login" src="logo.svg"' in index
    assert 'src="logo.svg"' in (STATIC / "assistant.html").read_text(encoding="utf-8")
    assert '"logo.svg"' in (STATIC / "sw.js").read_text(encoding="utf-8")
    assert 'id="voice-fab"' in index and "hidden" in index.split('id="voice-fab"')[1][:40]
    for size in (32, 180, 192, 512):
        assert (STATIC / "icons" / f"icon-{size}.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
