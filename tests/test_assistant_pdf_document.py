"""Tests for the styled PDF tool: page building, gate levels, checks, and the undo journal."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pypdf import PdfWriter

from spectre.assistant import pdf_document, toolkit, tools
from spectre.assistant.actions import ActionContext, ActionError, undo_last
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate, Level


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "assistant" / "spectre.db")
    yield database
    database.close()


class FakeTools:
    """subprocess.run stand-in: pandoc answers HTML, Chromium prints `pages` blank pages."""

    def __init__(self, pages: int = 1, printed: bool = True) -> None:
        self.pages = pages
        self.printed = printed
        self.page = ""

    def __call__(self, args: list[str], **_: Any) -> SimpleNamespace:
        if args[0] == "pandoc":
            return SimpleNamespace(stdout="<h2>Partie</h2><p>corps</p>", stderr="", returncode=0)
        target = next(a for a in args if a.startswith("--print-to-pdf=")).split("=", 1)[1]
        self.page = Path(target).with_name("page.html").read_text(encoding="utf-8")
        if self.printed:
            writer = PdfWriter()
            for _page in range(self.pages):
                writer.add_blank_page(595, 842)
            writer.write(target)
        return SimpleNamespace(stdout="", stderr="plantage", returncode=0)


@pytest.fixture
def ctx(db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ActionContext:
    monkeypatch.setattr(toolkit, "_bin", lambda names: names[0])
    context = ActionContext(db=db, root=tmp_path / "assistant", allowed_roots=[tmp_path])
    style = context.workspace / pdf_document.STYLE_FILE
    style.parent.mkdir(parents=True)
    style.write_text("body{color:red}", encoding="utf-8")
    return context


def _document(tmp_path: Path, text: str = "# Mon *titre*\n\nUn sous-titre\n\n## Partie\n") -> Path:
    folder = tmp_path / "Dossier-test"
    folder.mkdir(exist_ok=True)
    file = folder / "note-2026-10-24.md"
    file.write_text(text, encoding="utf-8")
    return file


def test_title_subtitle_and_date(tmp_path: Path) -> None:
    title, rest = pdf_document.split_title("intro\n# Le *titre*\nsuite", "secours")
    assert title == "Le titre" and "Le" not in rest and "suite" in rest
    assert pdf_document.split_title("sans titre", "secours")[0] == "secours"
    assert pdf_document.subtitle_of("\n\nUne phrase\n") == "Une phrase"
    assert pdf_document.subtitle_of("## Titre\n") == ""
    assert pdf_document.subtitle_of("x" * 171) == ""
    assert pdf_document.subtitle_of("") == ""
    assert pdf_document.date_of(_document(tmp_path)) == "24/10/2026"
    other = tmp_path / "sans-date.md"
    other.write_text("x", encoding="utf-8")
    assert len(pdf_document.date_of(other)) == 10


def test_decorate_highlights_titles_and_one_drop_cap() -> None:
    long = "A" * 210
    out = pdf_document.decorate(f"<h2 id='a'>Un</h2><p>{long}</p><p>{long}</p><p>court</p>")
    assert "<h2 id='a'><span>Un</span></h2>" in out
    assert out.count('class="lettrine"') == 1


def test_make_builds_a_safe_page_and_journals_it(ctx: ActionContext, tmp_path: Path) -> None:
    fake = FakeTools()
    ctx.runner = fake
    file = _document(tmp_path, "# <Titre> long " + "x" * 60 + "\n\nSous-titre\n")
    args = {"source": str(file)}
    out = tools.execute(Gate(ctx.db), ctx, "pdf_document", args)
    made = file.with_name("note-2026-10-24-design.pdf")
    assert out.startswith(f"PDF créé : {made} (1 page(s)") and made.is_file()
    assert "script" not in pdf_document.POLICY and "default-src 'none'" in fake.page
    assert "&lt;Titre&gt;" in fake.page and 'class="t3"' in fake.page
    assert "Dossier test" in fake.page and "body{color:red}" in fake.page
    assert "<h2><span>Partie</span></h2>" in fake.page
    assert undo_last(ctx).startswith("fichier créé supprimé") and not made.exists()


def test_blank_pages_are_reported(ctx: ActionContext, tmp_path: Path) -> None:
    ctx.runner = FakeTools(pages=3)
    out = pdf_document.make(ctx, str(_document(tmp_path)), section="Ma rubrique")
    assert "3 page(s)" in out and "pages presque vides : 2, 3" in out


def test_replacing_outside_the_workspace_waits_for_approval(
    ctx: ActionContext, tmp_path: Path
) -> None:
    ctx.runner = FakeTools()
    file = _document(tmp_path)
    kept = tmp_path / "garde.pdf"
    args = {"source": str(file), "destination": str(kept)}
    assert tools.TOOLS["pdf_document"].risk(ctx, args) == (Level.WRITE, "write_file")
    kept.write_bytes(b"ancien")
    assert tools.TOOLS["pdf_document"].risk(ctx, args) == (Level.DESTRUCTIVE, "overwrite_file")
    out = pdf_document.make(ctx, str(file), str(kept))
    assert "ancienne version sauvegardée" in out and kept.read_bytes() != b"ancien"
    assert undo_last(ctx).startswith("ancienne version") and kept.read_bytes() == b"ancien"
    draft = ctx.workspace / "brouillon.pdf"
    draft.parent.mkdir(exist_ok=True)
    draft.write_bytes(b"x")
    args = {"source": str(file), "destination": str(draft)}
    assert tools.TOOLS["pdf_document"].risk(ctx, args) == (Level.WRITE, "write_file")
    bad = {"source": str(file), "destination": "C:/ailleurs/hors.pdf"}
    assert tools.TOOLS["pdf_document"].risk(ctx, bad) == (Level.WRITE, "write_file")


def test_make_refuses_bad_requests(
    ctx: ActionContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = _document(tmp_path)
    with pytest.raises(ActionError, match="Markdown attendu"):
        pdf_document.make(ctx, str(file.with_suffix(".txt")))
    with pytest.raises(ActionError, match="introuvable"):
        pdf_document.make(ctx, str(file.with_name("absent.md")))
    with pytest.raises(ActionError, match="finir par .pdf"):
        pdf_document.make(ctx, str(file), str(tmp_path / "sortie.docx"))
    (ctx.workspace / pdf_document.STYLE_FILE).unlink()
    with pytest.raises(ActionError, match="feuille de style"):
        pdf_document.make(ctx, str(file))


def test_failures_of_the_programs_are_reported(
    ctx: ActionContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = _document(tmp_path)
    ctx.runner = FakeTools(printed=False)
    with pytest.raises(ActionError, match="aucun PDF produit : plantage"):
        pdf_document.make(ctx, str(file))

    ctx.runner = lambda *_, **__: SimpleNamespace(stdout="", stderr="mauvais", returncode=2)
    with pytest.raises(ActionError, match="Pandoc \\(code 2\\) : mauvais"):
        pdf_document.make(ctx, str(file))

    def slow(*_: Any, **__: Any) -> Any:
        raise subprocess.TimeoutExpired("x", 1)

    ctx.runner = slow
    with pytest.raises(ActionError, match="a dépassé"):
        pdf_document.make(ctx, str(file))

    def absent(*_: Any, **__: Any) -> Any:
        raise FileNotFoundError("x")

    ctx.runner = absent
    with pytest.raises(ActionError, match="introuvable"):
        pdf_document.make(ctx, str(file))

    monkeypatch.setattr(toolkit, "_bin", lambda names: None if names == ("chrome",) else names[0])
    ctx.runner = FakeTools()
    with pytest.raises(ActionError, match="Chromium n'est pas installé"):
        pdf_document.make(ctx, str(file))
    monkeypatch.setattr(toolkit, "_bin", lambda names: None)
    with pytest.raises(ActionError, match="Pandoc n'est pas installé"):
        pdf_document.make(ctx, str(file))


def test_unreadable_or_empty_pdf_is_refused(tmp_path: Path) -> None:
    broken = tmp_path / "casse.pdf"
    broken.write_bytes(b"pas un pdf")
    with pytest.raises(ActionError, match="illisible"):
        pdf_document.inspect_pdf(broken)
    empty = tmp_path / "vide.pdf"
    PdfWriter().write(empty)
    with pytest.raises(ActionError, match="aucune page"):
        pdf_document.inspect_pdf(empty)
