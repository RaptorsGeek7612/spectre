"""Octavya's contract tools: clause checklist and version comparison, standard library only."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import contracts
from spectre.assistant import tools as tools_mod
from spectre.assistant.actions import ActionError
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate, Level

CONTRACT = """Entre les soussignés : la société A, représentée par M. X, et la société B.
Article 1 - Objet : prestation de maintenance.
Article 2 - Prix : 12 000 € HT par an, paiement à 30 jours.
Article 3 - Durée : le contrat prend effet le 1er janvier 2026 pour 12 mois, renouvelé
automatiquement par tacite reconduction.
Article 4 - Résiliation sans préavis en cas de manquement.
Article 5 - Loi applicable : droit français. Tribunal de commerce de Paris.
"""


def docx(path: Path, paragraphs: list[str]) -> Path:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.'
        f'openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return path


@pytest.fixture
def ctx(tmp_path: Path) -> Any:
    db = Database(tmp_path / "a.db")
    home = tmp_path / "home"
    home.mkdir()
    context = tools_mod.make_context(db, tmp_path / "assistant", [str(home)])
    context.agent = "cursor"
    yield context
    db.close()


def test_analyse_finds_clauses_dates_amounts_and_alerts() -> None:
    report = contracts.analyse(CONTRACT)
    assert "pas une analyse juridique" in report
    assert "objet" in report and "loi applicable" in report and "litiges" in report
    assert "À vérifier ou absentes :" in report and "force majeure" in report.split("absentes")[1]
    assert "1er janvier 2026" in report and "12 000 €" in report and "30 jours" in report
    assert "reconduction tacite" in report and "sans préavis" in report


def test_reads_word_and_text(tmp_path: Path) -> None:
    word = docx(tmp_path / "c.docx", ["Article 1 - Objet", "Force majeure"])
    assert contracts.read_text(word) == "Article 1 - Objet\nForce majeure"
    with pytest.raises(ActionError, match="introuvable"):
        contracts.read_text(tmp_path / "c.pdf")
    (tmp_path / "c.pdf").write_bytes(b"%PDF")
    with pytest.raises(ActionError, match="formats"):
        contracts.read_text(tmp_path / "c.pdf")
    (tmp_path / "bad.docx").write_bytes(b"not a zip")
    with pytest.raises(ActionError, match="illisible"):
        contracts.read_text(tmp_path / "bad.docx")


def test_compare_writes_an_html_redline(ctx: Any) -> None:
    home = ctx.allowed_roots[0]
    docx(home / "v1.docx", ["Objet : maintenance", "Prix : 10 000 €", "Durée : 1 an"])
    (home / "v2.txt").write_text(
        "Objet : maintenance\nPrix : 12 000 €\nDurée : 1 an\nAnnexe", "utf-8"
    )
    out = contracts.contract(ctx, "comparer", "v1.docx", "v2.txt")
    assert "1 paragraphe(s) ajouté(s)" in out and "1 modifié(s)" in out
    page = (home / "v1-comparatif.html").read_text(encoding="utf-8")
    assert "Annexe" in page and "diff_chg" in page and "diff_add" in page
    with pytest.raises(ActionError, match="seconde version"):
        contracts.contract(ctx, "comparer", "v1.docx")
    with pytest.raises(ActionError, match="opération inconnue"):
        contracts.contract(ctx, "signer", "v1.docx")


def test_contract_tool_is_octavyas_and_compare_writes(ctx: Any) -> None:
    (ctx.allowed_roots[0] / "c.txt").write_text(CONTRACT, encoding="utf-8")
    gate = Gate(ctx.db)
    answer = tools_mod.execute(gate, ctx, "contrat", {"operation": "analyser", "target": "c.txt"})
    assert "Clauses repérées" in answer
    risk = tools_mod._contract_risk(ctx, {"operation": "comparer"})
    assert risk == (Level.WRITE, "convert")
    assert tools_mod._contract_risk(ctx, {"operation": "analyser"}) == (Level.READ, "read")
    ctx.agent = "lexy"
    refused = tools_mod.execute(gate, ctx, "contrat", {"operation": "analyser", "target": "c.txt"})
    assert refused.startswith("REFUSÉ")
