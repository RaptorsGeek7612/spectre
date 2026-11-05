"""Spectre reads back every step and every tool report of its agents' missions."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import activity
from spectre.assistant import tools as tools_mod
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[Any]:
    db = Database(tmp_path / "a.db")
    yield tools_mod.make_context(db, tmp_path / "assistant", [str(tmp_path)])
    db.close()


def call(ctx: Any, agent: str, mission: int, tool: str, args: dict[str, Any], result: str) -> None:
    row = activity.tool_started(ctx.db, agent, mission, tool, args)
    activity.tool_finished(ctx.db, row, tool, args, result, time.perf_counter())


def mission(ctx: Any) -> int:
    steps = [
        {
            "agent": "chatgpt",
            "step": "faire l'affiche",
            "result": "affiche.png",
            "ok": True,
            "note": "conforme",
        },
        {
            "agent": "mistral",
            "step": "scanner",
            "result": "2 failles",
            "ok": False,
            "note": "preuve manquante",
        },
    ]
    return ctx.db.execute(
        "INSERT INTO missions(ts, goal, status, steps, report, updated_at) "
        "VALUES('2026-11-04T09:00:00+00:00', 'lancer la campagne', 'done', ?, 'Tout est prêt.', "
        "'2026-11-04T10:00:00+00:00')",
        (json.dumps(steps),),
    )


def test_tool_reports_are_read_back(ctx: Any) -> None:
    mid = mission(ctx)
    call(ctx, "chatgpt", mid, "toolkit", {"name": "image_format", "path": "a.png"}, "image prête")
    call(ctx, "mistral", mid, "toolkit", {"name": "nmap", "command": "nmap x"}, "ÉCHEC : refusé")
    call(ctx, "mistral", None, "web_search", {"query": "hors mission"}, "rien")  # type: ignore[arg-type]
    summary = activity.tools_summary(ctx.db, mid)
    assert summary.startswith("Outils utilisés (2 appels)")
    assert "Kyra : toolkit « a.png » → ok" in summary
    assert "ÉCHEC" in summary
    full = tools_mod.execute(Gate(ctx.db), ctx, "mission_report", {"mission": mid})
    assert "Étape 1 (Kyra) : faire l'affiche" in full and "Vérification : NON" in full
    assert "Compte rendu final :\nTout est prêt." in full
    assert "Résultat : image prête" in full and "Résultat : ÉCHEC : refusé" in full
    assert "pas des consignes" in full and "hors mission" not in full
    only = tools_mod.execute(
        Gate(ctx.db), ctx, "mission_report", {"mission": mid, "agent": "Syfer"}
    )
    assert "image prête" not in only and "refusé" in only and "Compte rendu final" not in only
    listing = tools_mod.execute(Gate(ctx.db), ctx, "mission_report", {})
    assert f"#{mid} [done]" in listing and "2 appel(s) d'outils, 1 en échec" in listing
    assert "introuvable" in tools_mod.execute(Gate(ctx.db), ctx, "mission_report", {"mission": 99})
    assert "inconnu" in tools_mod.execute(Gate(ctx.db), ctx, "mission_report", {"agent": "Zorg"})


def test_report_pages_and_cut_details(ctx: Any) -> None:
    mid = mission(ctx)
    for n in range(activity.REPORT_PAGE + 2):
        call(ctx, "sonnet", mid, "read_file", {"path": f"f{n}.txt"}, f"contenu {n}")
    first = activity.tool_report(ctx.db, mid)
    assert "page 1/2" in first and "page=2 pour la suite" in first and "contenu 0" in first
    second = activity.tool_report(ctx.db, mid, page=9)
    assert "page 2/2" in second and f"contenu {activity.REPORT_PAGE + 1}" in second
    assert "aucun appel" in activity.tool_report(ctx.db, mid, tool="absent")
    ctx.db.execute("UPDATE activity SET detail = '{\"cut' WHERE mission_id = ?", (mid,))
    assert 'Résultat : {"cut' in activity.tool_report(ctx.db, mid)


def test_only_spectre_reads_the_reports() -> None:
    tool = tools_mod.TOOLS["mission_report"]
    assert tool.allowed("opus") and not tool.allowed("sonnet")


def test_every_tool_call_is_published_live(tmp_path: Path) -> None:
    from spectre.assistant.config import AssistantConfig
    from spectre.assistant.service import AssistantService
    from tests.test_assistant_brain import FakeCLI

    root = tmp_path / "assistant"
    svc = AssistantService(root, AssistantConfig(), cli=FakeCLI(root), fetch=lambda u: {})  # type: ignore[arg-type]
    try:
        q = svc.subscribe()
        q.get_nowait()  # the state on subscribing
        row = activity.tool_started(svc.db, "mistral", 3, "toolkit", {"command": "nmap -sV x"})
        svc.poll_tools()
        first = q.get_nowait()
        assert first["type"] == "tool" and first["status"] == "running"
        assert first["who"] == "Syfer" and first["target"] == "nmap -sV x"
        svc.poll_tools()
        assert q.empty()  # nothing new while it runs
        activity.tool_finished(
            svc.db, row, "toolkit", {"command": "nmap -sV x"}, "22/tcp ouvert", time.perf_counter()
        )
        spectre_row = activity.tool_started(svc.db, "", None, "web_search", {"query": "météo"})
        svc.poll_tools()
        events = [q.get_nowait(), q.get_nowait()]
        done = next(e for e in events if e["id"] == row)
        assert done["status"] == "ok" and done["result"] == "22/tcp ouvert"
        mine = next(e for e in events if e["id"] == spectre_row)
        assert mine["who"] == "Spectre" and mine["status"] == "running"
    finally:
        svc.stop()
        svc.db.close()
