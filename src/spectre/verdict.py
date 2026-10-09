"""Warden's verdict: the final text first, then a marker line and a small JSON object.

Warden writes the corrected text, then `=== VERDICT ===` and `{"approved": ..., "issues": [...]}`.
A plain-text verdict (instead of a tool call) works with every chat model Spectre drives,
including the Claude Code CLI and the demo models, and lets the text stream before the verdict.
A missing or unreadable verdict counts as approved: the text is never lost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Final

VERDICT_MARKER: Final = "=== VERDICT ==="


@dataclass(frozen=True)
class Verdict:
    """What Warden decided about the draft."""

    text: str
    approved: bool = True
    issues: list[str] = field(default_factory=list)


def parse_verdict(raw: str) -> Verdict:
    """Split Warden's answer into the final text and its verdict."""
    head, marker, tail = raw.rpartition(VERDICT_MARKER)
    if not marker:
        return Verdict(raw.strip())
    text = head.strip()
    start, end = tail.find("{"), tail.rfind("}")
    try:
        data = json.loads(tail[start : end + 1]) if 0 <= start < end else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return Verdict(text)
    raw_issues = data.get("issues")
    issues = (
        [str(item).strip() for item in raw_issues if str(item).strip()]
        if isinstance(raw_issues, list)
        else []
    )
    # A rejection without any issue gives the writer nothing to act on: keep the text.
    approved = data.get("approved") is not False or not issues
    return Verdict(text, approved, issues)


class VerdictFilter:
    """Streams Warden's text while hiding the verdict marker and everything after it."""

    def __init__(self) -> None:
        self._pending = ""
        self._done = False

    def feed(self, chunk: str) -> str:
        """Return the part of `chunk` that is safe to show now."""
        if self._done:
            return ""
        self._pending += chunk
        index = self._pending.find(VERDICT_MARKER)
        if index >= 0:
            visible, self._pending, self._done = self._pending[:index], "", True
            return visible
        hold = _marker_prefix_length(self._pending)
        cut = len(self._pending) - hold
        visible, self._pending = self._pending[:cut], self._pending[cut:]
        return visible

    def flush(self) -> str:
        """Text held back at the end of the stream (it was not the marker after all)."""
        rest, self._pending = ("" if self._done else self._pending), ""
        return rest


def _marker_prefix_length(text: str) -> int:
    """Length of the longest end of `text` that could be the start of the marker."""
    for size in range(min(len(text), len(VERDICT_MARKER) - 1), 0, -1):
        if VERDICT_MARKER.startswith(text[-size:]):
            return size
    return 0
