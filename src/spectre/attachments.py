"""Files the user attaches (paperclip, paste, drag and drop) to a request or a message.

Two uses: the writing pipeline only takes text, so `extract_text` reads a document's text (plain
text, Word, OpenDocument, PDF, or an image through Tesseract's OCR); the assistant keeps the file
itself in its workspace (`store`), where Spectre reads it whole, images included.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_BYTES = 15 * 1024 * 1024  # 15 MB: a photo, a scan, a long PDF
MAX_TEXT = 200_000  # characters added to a writing request
TEXT = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml", ".html", ".htm", ".yaml",
    ".yml", ".toml", ".ini", ".log", ".srt", ".vtt", ".fountain", ".rtf", ".py", ".js", ".ts",
    ".css", ".sql", ".sh", ".ps1", ".bat", ".tex",
}  # fmt: skip
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
DOCUMENTS = {".docx", ".odt", ".pdf"}
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ODF_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TESSERACT_DIRS = (Path("C:/Program Files/Tesseract-OCR"), Path.home() / "Apps" / "bin")
TESSDATA = Path.home() / "Apps" / "tessdata"  # the multilingual models (fra, eng…)


class AttachmentError(ValueError):
    """A refused or unreadable file (the message is for the user)."""


def safe_name(name: str) -> str:
    """A file name without folders or odd characters, kept readable."""
    base = Path(str(name).replace("\\", "/")).name.strip() or "fichier"
    base = re.sub(r"[^\w.\- ()]+", "_", base, flags=re.UNICODE).strip(" .") or "fichier"
    stem, suffix = os.path.splitext(base)
    return f"{stem[:80]}{suffix[:10].lower()}"


def kind(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in IMAGES:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    if suffix in DOCUMENTS:
        return "document"
    if suffix in TEXT or not suffix:
        return "texte"
    return "fichier"


def check(data: bytes) -> None:
    if not data:
        raise AttachmentError("fichier vide")
    if len(data) > MAX_BYTES:
        raise AttachmentError(f"fichier trop gros ({MAX_BYTES // (1024 * 1024)} Mo maximum)")


def store(folder: Path, name: str, data: bytes) -> Path:
    """Keep an attached file in `folder`, under a unique name."""
    check(data)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex[:8]}-{safe_name(name)}"
    path.write_bytes(data)
    return path


def decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _xml_paragraphs(data: bytes, member: str, paragraph: str, text: str) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ElementTree.fromstring(archive.read(member))  # noqa: S314 - a local upload
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise AttachmentError("document illisible (fichier abîmé ?)") from exc
    lines = ["".join(n.text or "" for n in p.iter(text)) for p in root.iter(paragraph)]
    return "\n".join(line for line in lines if line.strip())


def _odt(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ElementTree.fromstring(archive.read("content.xml"))  # noqa: S314
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise AttachmentError("document OpenDocument illisible") from exc
    lines = [
        "".join(node.itertext())
        for node in root.iter()
        if node.tag in (f"{ODF_TEXT}p", f"{ODF_TEXT}h")
    ]
    return "\n".join(line for line in lines if line.strip())


def _pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as exc:  # pragma: no cover - pypdf is a dependency
        raise AttachmentError("lecture des PDF indisponible (pypdf manquant)") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except (PdfReadError, ValueError, KeyError) as exc:
        raise AttachmentError("PDF illisible (protégé ou abîmé ?)") from exc
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        raise AttachmentError("ce PDF ne contient pas de texte (un scan ?) : joins-le en image")
    return text


def tesseract() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    for folder in TESSERACT_DIRS:
        candidate = folder / "tesseract.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def ocr(data: bytes, suffix: str, runner: object = None, lang: str = "fra+eng") -> str:
    """The text of an image, read by Tesseract (on this PC)."""
    exe = tesseract()
    if exe is None:
        raise AttachmentError("lecture du texte des images indisponible (Tesseract absent)")
    env = dict(os.environ)
    if TESSDATA.is_dir():
        env["TESSDATA_PREFIX"] = str(TESSDATA)
    run = runner or subprocess.run
    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / f"image{suffix}"
        image.write_bytes(data)
        try:
            proc = run(  # type: ignore[operator]
                [exe, str(image), "stdout", "-l", lang],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AttachmentError(f"lecture de l'image impossible : {exc}") from exc
    text = (proc.stdout or "").strip()
    if proc.returncode != 0 and not text:
        raise AttachmentError(f"lecture de l'image impossible : {(proc.stderr or '')[:200]}")
    if not text:
        raise AttachmentError("aucun texte lisible dans cette image")
    return text


def extract_text(name: str, data: bytes, runner: object = None) -> str:
    """A document's text, for a request that only takes text."""
    check(data)
    suffix = Path(name).suffix.lower()
    if suffix == ".docx":
        text = _xml_paragraphs(data, "word/document.xml", f"{WORD}p", f"{WORD}t")
    elif suffix == ".odt":
        text = _odt(data)
    elif suffix == ".pdf":
        text = _pdf(data)
    elif suffix in IMAGES:
        text = ocr(data, suffix, runner)
    elif suffix in TEXT or not suffix:
        if b"\x00" in data[:4096]:
            raise AttachmentError("ce fichier n'est pas du texte")
        text = decode(data)
    else:
        raise AttachmentError(
            f"format non lu ici : {suffix} (texte, Word, OpenDocument, PDF ou image)"
        )
    return text.strip()[:MAX_TEXT]
