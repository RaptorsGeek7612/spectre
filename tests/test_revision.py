"""Tests for v0.4: Warden's verdict, the Warden -> Scribe revision loop and its settings."""

from __future__ import annotations

import pytest

from spectre.config import (
    DEFAULT_MAX_REVISIONS,
    MAX_REVISIONS_LIMIT,
    check_max_revisions,
    load_max_revisions,
)
from spectre.errors import ConfigurationError, EmptyOutputError
from spectre.graph import run
from spectre.nodes import make_scribe_node, make_warden_node
from spectre.prompts import WARDEN_PROMPT, scribe_input
from spectre.verdict import VERDICT_MARKER, Verdict, VerdictFilter, parse_verdict
from tests.conftest import fake, make_ai

REJECT = f'TEXTE V1\n{VERDICT_MARKER}\n{{"approved": false, "issues": ["Ajoute une conclusion"]}}'
APPROVE = f'TEXTE V2\n{VERDICT_MARKER}\n{{"approved": true, "issues": []}}'


# ---- verdict ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Juste du texte", Verdict("Juste du texte")),
        (REJECT, Verdict("TEXTE V1", False, ["Ajoute une conclusion"])),
        (APPROVE, Verdict("TEXTE V2")),
        (f'T\n{VERDICT_MARKER}\n```json\n{{"approved": true}}\n```', Verdict("T")),
        (f"T\n{VERDICT_MARKER}\npas de json", Verdict("T")),
        (f"T\n{VERDICT_MARKER}\n{{cassé}}", Verdict("T")),
        (f"T\n{VERDICT_MARKER}\n[1, 2]", Verdict("T")),
        # a rejection with nothing to fix keeps the text
        (f'T\n{VERDICT_MARKER}\n{{"approved": false, "issues": []}}', Verdict("T")),
        (f'T\n{VERDICT_MARKER}\n{{"approved": false, "issues": "oui"}}', Verdict("T")),
        (
            f'T\n{VERDICT_MARKER}\n{{"approved": true, "issues": ["détail", " "]}}',
            Verdict("T", True, ["détail"]),
        ),
        (
            f"A\n{VERDICT_MARKER} cité\nB\n{VERDICT_MARKER}\n{{}}",
            Verdict(f"A\n{VERDICT_MARKER} cité\nB"),
        ),
    ],
)
def test_parse_verdict(raw: str, expected: Verdict) -> None:
    assert parse_verdict(raw) == expected


def test_verdict_filter_hides_the_verdict_while_streaming() -> None:
    filt = VerdictFilter()
    pieces = ["Bonjour ", "le monde\n=", "== VER", "DICT ===\n", '{"approved": true}']
    shown = "".join(filt.feed(p) for p in pieces) + filt.flush()
    assert shown == "Bonjour le monde\n"
    assert filt.feed("encore") == ""


def test_verdict_filter_releases_a_false_alarm() -> None:
    filt = VerdictFilter()
    assert filt.feed("a ==") == "a "
    assert filt.feed("= b") == "=== b"
    assert filt.feed("fin ===") == "fin "
    assert filt.flush() == "==="


def test_warden_prompt_asks_for_the_verdict() -> None:
    assert VERDICT_MARKER in WARDEN_PROMPT and '"approved"' in WARDEN_PROMPT


# ---- settings -----------------------------------------------------------------------------


def test_max_revisions_settings() -> None:
    assert load_max_revisions({}) == DEFAULT_MAX_REVISIONS == 1
    assert load_max_revisions({"SPECTRE_MAX_REVISIONS": " 3 "}) == 3
    assert load_max_revisions({"SPECTRE_MAX_REVISIONS": "0"}) == 0
    with pytest.raises(ConfigurationError, match="entier"):
        load_max_revisions({"SPECTRE_MAX_REVISIONS": "deux"})
    with pytest.raises(ConfigurationError, match="entre 0 et"):
        load_max_revisions({"SPECTRE_MAX_REVISIONS": str(MAX_REVISIONS_LIMIT + 1)})
    with pytest.raises(ConfigurationError, match="max_revisions"):
        check_max_revisions(-1)


# ---- nodes --------------------------------------------------------------------------------


STATE = {"request": "Écris un poème", "brief": "LE BRIEF", "draft": "BROUILLON", "usage": []}


def test_scribe_input_with_and_without_revision() -> None:
    first = scribe_input("D", "B")
    assert "<version_precedente>" not in first
    again = scribe_input("D", "B", "V1", ["Plus court", "Ajoute un titre"])
    assert "<version_precedente>\nV1\n</version_precedente>" in again
    assert "- Plus court\n- Ajoute un titre" in again
    assert "<version_precedente>" not in scribe_input("D", "B", "V1", [])


def test_scribe_revises_after_a_rejection() -> None:
    model = fake("scribe", make_ai("V2"), make_ai("V3"))
    node = make_scribe_node(model)
    first = node({**STATE})  # type: ignore[arg-type]
    assert "revisions" not in first and "<version_precedente>" not in model.received[0][1].content
    rejected = {
        **STATE,
        "final_text": "V1",
        "approved": False,
        "issues": ["Conclus"],
        "revisions": 0,
    }
    update = node(rejected)  # type: ignore[arg-type]
    assert update["revisions"] == 1 and update["draft"] == "V3"
    human = model.received[1][1].content
    assert "V1" in human and "- Conclus" in human


def test_warden_reports_its_verdict() -> None:
    update = make_warden_node(fake("warden", make_ai(REJECT)))(STATE)  # type: ignore[arg-type]
    assert update["final_text"] == "TEXTE V1"
    assert (update["approved"], update["issues"]) == (False, ["Ajoute une conclusion"])
    only_verdict = fake("warden", make_ai(f'{VERDICT_MARKER}\n{{"approved": true}}'))
    with pytest.raises(EmptyOutputError):
        make_warden_node(only_verdict)(STATE)  # type: ignore[arg-type]


# ---- the loop -----------------------------------------------------------------------------


def _models(*warden: str, scribe: int = 3) -> dict[str, object]:
    return {
        "scout": fake("scout", make_ai("BRIEF")),
        "scribe": fake("scribe", *[make_ai(f"DRAFT{i}") for i in range(1, scribe + 1)]),
        "warden": fake("warden", *[make_ai(w) for w in warden]),
    }


def test_rejected_draft_goes_back_to_scribe_once() -> None:
    models = _models(REJECT, APPROVE)
    result = run("Écris un poème", models=models)  # type: ignore[arg-type]
    assert (result.final_text, result.approved, result.revisions) == ("TEXTE V2", True, 1)
    assert result.draft == "DRAFT2"
    assert [r["agent"] for r in result.usage] == ["scout", "scribe", "warden", "scribe", "warden"]
    assert "Ajoute une conclusion" in models["scribe"].received[1][1].content  # type: ignore[attr-defined]


def test_rounds_stop_at_the_limit_and_keep_the_best_text() -> None:
    result = run("x", models=_models(REJECT, REJECT, REJECT), max_revisions=2)  # type: ignore[arg-type]
    assert (result.approved, result.revisions, result.issues) == (
        False,
        2,
        ["Ajoute une conclusion"],
    )
    assert result.final_text == "TEXTE V1" and len(result.usage) == 7


def test_zero_revisions_is_the_linear_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_MAX_REVISIONS", "0")
    result = run("x", models=_models(REJECT))  # type: ignore[arg-type]
    assert (result.approved, result.revisions, len(result.usage)) == (False, 0, 3)
    with pytest.raises(ConfigurationError):
        run("x", models=_models(APPROVE), max_revisions=9)  # type: ignore[arg-type]


# ---- the web stream -----------------------------------------------------------------------


def test_web_stream_follows_the_revision_round() -> None:
    from spectre.web.pipeline import stream_run

    events = list(stream_run("Un poème", demo=False, models=_models(REJECT, APPROVE)))  # type: ignore[arg-type]
    starts = [(e["agent"], e.get("revision")) for e in events if e["type"] == "agent_start"]
    assert starts == [
        ("scout", None),
        ("scribe", None),
        ("warden", None),
        ("scribe", 1),
        ("warden", 1),
    ]
    warden_tokens = "".join(
        e["text"] for e in events if e["type"] == "token" and e["agent"] == "warden"
    )
    assert (
        "VERDICT" not in warden_tokens
        and "TEXTE V1" in warden_tokens
        and "TEXTE V2" in warden_tokens
    )
    first_verdict = next(e for e in events if e["type"] == "agent_done" and e["agent"] == "warden")
    assert (first_verdict["approved"], first_verdict["issues"]) == (
        False,
        ["Ajoute une conclusion"],
    )
    done = events[-1]
    assert done["type"] == "done" and done["final_text"] == "TEXTE V2"
    assert (done["approved"], done["revisions"], len(done["usage"])) == (True, 1, 5)
    assert set(done["durations"]) == {"scout", "scribe", "warden"}


def test_web_stream_without_revision_and_bad_setting() -> None:
    from spectre.web.pipeline import stream_run

    events = list(stream_run("x", demo=False, models=_models(REJECT), max_revisions=0))  # type: ignore[arg-type]
    assert [e["agent"] for e in events if e["type"] == "agent_start"] == [
        "scout",
        "scribe",
        "warden",
    ]
    assert events[-1]["approved"] is False and events[-1]["revisions"] == 0
    bad = list(stream_run("x", demo=False, models=_models(APPROVE), max_revisions=7))  # type: ignore[arg-type]
    assert bad[-1]["type"] == "error" and "entre 0 et" in bad[-1]["message"]


def test_web_stream_releases_held_back_text() -> None:
    from spectre.web.pipeline import stream_run

    events = list(stream_run("x", demo=False, models=_models("La fin ==")))  # type: ignore[arg-type]
    shown = "".join(e["text"] for e in events if e["type"] == "token" and e["agent"] == "warden")
    assert shown.endswith("==") and events[-1]["final_text"] == "La fin =="
