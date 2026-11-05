"""A Markdown document as a PDF in the style the user validated, checked before it is delivered.

Pandoc turns the text into HTML, the page gets the cover and the running headers, and headless
Chromium prints it. The style sheet is the user's own file in the agents' workspace, so changing
the look needs no code. The document is data: its scripts never run (see `POLICY`).
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from spectre.assistant import toolkit
from spectre.assistant.actions import ActionContext, ActionError, _journal, resolve_path

STYLE_FILE = Path("modeles") / "pdf-olivier-final.css"
PANDOC_TIMEOUT_S = 60.0
PRINT_TIMEOUT_S = 120.0
NEARLY_BLANK_CHARS = 40  # a page past the cover with less text than this is probably empty

# Only the style's web fonts may load: no script, no other request from the document.
POLICY = (
    "default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src file: data:"
)
COVER_ART = (
    '<svg class="art" viewBox="0 0 210 297" preserveAspectRatio="none" aria-hidden="true">'
    '<polygon points="210,118 210,158 78,297 38,297" fill="#083181"/>'
    '<polygon points="210,158 210,208 126,297 78,297" fill="#0292F2"/>'
    '<polygon points="210,208 210,236 152,297 126,297" fill="#08C8DD"/>'
    '<polygon points="210,236 210,297 152,297" fill="#206097"/></svg>'
)
PAGE = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{policy}">
<base href="{base}"><title>{title}</title><style>
{css}
</style></head><body>
<div class="rail" aria-hidden="true"></div>
<section class="couverture">{art}<div class="bloc"><p class="sur-titre">{section}</p>
<h1 class="{size}">{title}</h1>{subtitle}
<p class="meta">Document du {date}<br>Préparé par Spectre</p>
</div></section>
<table class="flux"><thead><tr><td><div class="haut"><span>{title}</span><span>{section}</span>
</div></td></tr></thead>
<tfoot><tr><td><div class="bas">{name}</div></td></tr></tfoot>
<tbody><tr><td><main>
{body}
</main></td></tr></tbody></table>
</body></html>
"""


def _clean(text: str) -> str:
    return re.sub(r"[*_`]", "", text).strip()


def split_title(text: str, fallback: str) -> tuple[str, str]:
    """The document's first `# ` heading, and the text without it (it goes on the cover)."""
    found = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    if found is None:
        return fallback, text
    return _clean(found.group(1)), text[: found.start()] + text[found.end() :]


def subtitle_of(text: str) -> str:
    """The opening line when it reads as a subtitle: short, and plain text."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"[#|>\-!\[*0-9`]", line) or len(line) > 170:
            return ""
        return _clean(line)
    return ""


def date_of(source: Path) -> str:
    found = re.search(r"(\d{4})-(\d{2})-(\d{2})", source.stem)
    if found:
        return f"{found.group(3)}/{found.group(2)}/{found.group(1)}"
    return datetime.fromtimestamp(source.stat().st_mtime).strftime("%d/%m/%Y")


def decorate(fragment: str) -> str:
    """What the style hooks on: highlighted h2 titles, a drop cap on the first long text."""
    fragment = re.sub(r"(?s)<h2([^>]*)>(.*?)</h2>", r"<h2\1><span>\2</span></h2>", fragment)
    return re.sub(r"<p>(?=[A-ZÀ-ÖØ-Þ][^<]{200,})", '<p class="lettrine">', fragment, count=1)


def page(source: Path, text: str, fragment: str, css: str, title: str, section: str) -> str:
    size = "t3" if len(title) > 60 else "t2" if len(title) > 26 else ""
    subtitle = subtitle_of(text)
    return PAGE.format(
        policy=POLICY,
        base=source.parent.as_uri() + "/",
        title=html.escape(title),
        css=css,
        art=COVER_ART,
        section=html.escape(section),
        size=size,
        subtitle=f'<p class="sous-titre">{html.escape(subtitle)}</p>' if subtitle else "",
        date=date_of(source),
        name=html.escape(source.stem),
        body=decorate(fragment),
    )


def _run(ctx: ActionContext, command: list[str], timeout: float, what: str) -> Any:
    runner = ctx.runner or subprocess.run
    try:
        return runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise ActionError(f"{what} est introuvable : {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ActionError(f"{what} a dépassé {int(timeout)} s") from exc


def _pandoc(ctx: ActionContext, text: str, folder: Path) -> str:
    pandoc = toolkit._bin(("pandoc",))
    if pandoc is None:
        raise ActionError("Pandoc n'est pas installé sur ce PC")
    file = folder / "source.md"
    file.write_text(text, encoding="utf-8")
    proc = _run(
        ctx,
        [pandoc, "-f", "gfm", "-t", "html", "--wrap=none", str(file)],
        PANDOC_TIMEOUT_S,
        "Pandoc",
    )
    if proc.returncode != 0:
        raise ActionError(f"Pandoc (code {proc.returncode}) : {(proc.stderr or '')[:400]}")
    return str(proc.stdout)


def _print(ctx: ActionContext, document: str, folder: Path) -> Path:
    chrome = toolkit._bin(("chrome",))
    if chrome is None:
        raise ActionError("Chromium n'est pas installé sur ce PC")
    file, made = folder / "page.html", folder / "page.pdf"
    file.write_text(document, encoding="utf-8")
    proc = _run(
        ctx,
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=10000",
            f"--user-data-dir={folder / 'profil'}",
            f"--print-to-pdf={made}",
            file.as_uri(),
        ],
        PRINT_TIMEOUT_S,
        "Chromium",
    )
    if not made.is_file():
        raise ActionError(f"aucun PDF produit : {(proc.stderr or '')[:400]}")
    return made


def inspect_pdf(file: Path) -> tuple[int, list[int]]:
    """The page count, and the pages past the cover with next to no text."""
    try:
        pages = PdfReader(file).pages
        texts = [p.extract_text() or "" for p in pages]
    except (PdfReadError, OSError, ValueError) as exc:
        raise ActionError(f"le PDF produit est illisible : {exc}") from exc
    if not texts:
        raise ActionError("le PDF produit n'a aucune page")
    blank = [i for i, t in enumerate(texts, 1) if i > 1 and len(t.strip()) < NEARLY_BLANK_CHARS]
    return len(texts), blank


def destination_of(ctx: ActionContext, source: str, destination: str = "") -> Path:
    """Where the PDF goes: as asked, else next to the document as `<name>-design.pdf`."""
    if destination.strip():
        target = resolve_path(ctx, destination)
        if target.suffix.lower() != ".pdf":
            raise ActionError(f"la destination doit finir par .pdf : {target.name}")
        return target
    file = resolve_path(ctx, source)
    return resolve_path(ctx, str(file.with_name(f"{file.stem}-design.pdf")))


def make(ctx: ActionContext, source: str, destination: str = "", section: str = "") -> str:
    """Build the PDF of a Markdown document in the validated style, and report what it checked."""
    file = resolve_path(ctx, source)
    if file.suffix.lower() not in (".md", ".markdown"):
        raise ActionError(f"fichier Markdown attendu : {file.name}")
    if not file.is_file():
        raise ActionError(f"introuvable : {file}")
    style = ctx.workspace / STYLE_FILE
    if not style.is_file():
        raise ActionError(f"feuille de style introuvable : {style}")
    target = destination_of(ctx, source, destination)
    title, text = split_title(file.read_text(encoding="utf-8"), file.stem)
    label = section.strip() or file.parent.name.replace("-", " ")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        folder = Path(tmp)
        fragment = _pandoc(ctx, text, folder)
        css = style.read_text(encoding="utf-8")
        made = _print(ctx, page(file, text, fragment, css, title, label), folder)
        count, blank = inspect_pdf(made)
        target.parent.mkdir(parents=True, exist_ok=True)
        backup = None
        if target.exists():
            ctx.trash.mkdir(parents=True, exist_ok=True)
            backup = ctx.trash / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{target.name}"
            shutil.copy2(target, backup)
        size = made.stat().st_size
        shutil.copyfile(made, target)
    _journal(ctx, "write", path=str(target), backup=str(backup) if backup else None)
    report = f"PDF créé : {target} ({count} page(s), {size // 1024} Ko)"
    if backup:
        report += f" ; ancienne version sauvegardée : {backup}"
    if blank:
        report += f"\nÀ VÉRIFIER : pages presque vides : {', '.join(map(str, blank))}"
    return report
