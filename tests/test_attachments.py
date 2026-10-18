"""Files joined to a writing request or to a message for Spectre (paperclip, paste, drop)."""

from __future__ import annotations

import io
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

from spectre import attachments
from spectre.attachments import AttachmentError
from spectre.web.store import Store
from tests.test_assistant_service import home, service  # noqa: F401 - fixtures
from tests.test_web import _serve


def _docx(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def _odt(*paragraphs: str) -> bytes:
    body = "".join(f"<text:p>{p}</text:p>" for p in paragraphs)
    xml = (
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
        ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        f"<office:body><office:text>{body}</office:text></office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("content.xml", xml)
    return buffer.getvalue()


def _pdf(text: str) -> bytes:
    """A one-page PDF with `text` in Helvetica, offsets computed (no library needed)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(out)


def test_safe_name_and_kind() -> None:
    assert attachments.safe_name("..\\..\\C:/Windows/évil<>.PNG") == "évil_.png"
    assert attachments.safe_name("") == "fichier"
    assert attachments.kind("a.jpg") == "image"
    assert attachments.kind("a.pdf") == "pdf"
    assert attachments.kind("a.docx") == "document"
    assert attachments.kind("a.md") == "texte"
    assert attachments.kind("a.zip") == "fichier"


def test_extract_text_formats() -> None:
    assert attachments.extract_text("n.txt", "Bonjour é".encode("cp1252")) == "Bonjour é"
    assert attachments.extract_text("n.md", "\ufeff# Titre\n".encode()) == "# Titre"
    assert attachments.extract_text("c.docx", _docx("Article 1", "", "Article 2")) == (
        "Article 1\nArticle 2"
    )
    assert attachments.extract_text("c.odt", _odt("Un", "Deux")) == "Un\nDeux"
    assert "Bonjour le monde" in attachments.extract_text("p.pdf", _pdf("Bonjour le monde"))


def test_extract_text_refusals() -> None:
    with pytest.raises(AttachmentError, match="vide"):
        attachments.extract_text("a.txt", b"")
    with pytest.raises(AttachmentError, match="trop gros"):
        attachments.check(b"x" * (attachments.MAX_BYTES + 1))
    with pytest.raises(AttachmentError, match="pas du texte"):
        attachments.extract_text("a.txt", b"\x00\x01binary")
    with pytest.raises(AttachmentError, match="format non lu"):
        attachments.extract_text("a.zip", b"PK")
    with pytest.raises(AttachmentError, match="illisible"):
        attachments.extract_text("a.docx", b"not a zip")
    with pytest.raises(AttachmentError, match="illisible"):
        attachments.extract_text("a.odt", b"not a zip")
    with pytest.raises(AttachmentError, match="PDF"):
        attachments.extract_text("a.pdf", b"%PDF-1.4 broken")


def test_ocr_of_an_image(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def runner(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen["cmd"], seen["env"] = cmd, kw["env"]
        assert Path(cmd[1]).read_bytes() == b"PNGDATA"
        return subprocess.CompletedProcess(cmd, 0, "Texte lu\n", "")

    monkeypatch.setattr(attachments, "tesseract", lambda: "C:/tess/tesseract.exe")
    assert attachments.extract_text("capture.png", b"PNGDATA", runner) == "Texte lu"
    assert seen["cmd"][2:] == ["stdout", "-l", "fra+eng"]

    def empty(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, "  ", "")

    with pytest.raises(AttachmentError, match="aucun texte"):
        attachments.ocr(b"x", ".png", empty)

    def failing(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, "", "bad image")

    with pytest.raises(AttachmentError, match="bad image"):
        attachments.ocr(b"x", ".png", failing)

    def crash(cmd: list[str], **kw: Any) -> Any:
        raise OSError("blocked")

    with pytest.raises(AttachmentError, match="blocked"):
        attachments.ocr(b"x", ".png", crash)
    monkeypatch.setattr(attachments, "tesseract", lambda: None)
    with pytest.raises(AttachmentError, match="Tesseract absent"):
        attachments.ocr(b"x", ".png")


def test_tesseract_lookup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(attachments.shutil, "which", lambda name: None)
    exe = tmp_path / "tesseract.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(attachments, "TESSERACT_DIRS", (tmp_path / "none", tmp_path))
    assert attachments.tesseract() == str(exe)
    monkeypatch.setattr(attachments, "TESSERACT_DIRS", ())
    assert attachments.tesseract() is None
    monkeypatch.setattr(attachments.shutil, "which", lambda name: "C:/t.exe")
    assert attachments.tesseract() == "C:/t.exe"


def test_store_keeps_unique_files(tmp_path: Path) -> None:
    first = attachments.store(tmp_path / "pj", "photo.jpg", b"a")
    second = attachments.store(tmp_path / "pj", "photo.jpg", b"b")
    assert first != second and first.name.endswith("-photo.jpg")
    assert first.read_bytes() == b"a"


def test_writing_route_returns_the_text(tmp_path: Path) -> None:
    with _serve(tmp_path) as client:
        status, data = client.json(
            "POST", "/api/attachments?name=contrat.docx", raw=_docx("Clause")
        )
        assert status == 200 and data == {"name": "contrat.docx", "text": "Clause"}
        status, data = client.json("POST", "/api/attachments?name=a.zip", raw=b"PK")
        assert status == 400 and "format non lu" in data["error"]
    assert Store(tmp_path / "state").list_runs() == []


def test_message_with_attachments(service: Any) -> None:  # noqa: F811
    note = service.attach("notes.txt", "à retenir".encode())
    photo = service.attach("photo.png", b"\x89PNGdata")
    assert note["kind"] == "texte" and photo["kind"] == "image" and photo["size"] == 8
    folder = service.cli.workspace / "pieces-jointes"
    assert (folder / photo["id"]).read_bytes() == b"\x89PNGdata"
    reply = service.chat("Regarde", "text", [note["id"], photo["id"]])
    assert reply == "Réponse."
    prompt = service.cli.calls[-1]["prompt"]
    assert "Regarde" in prompt and f"pieces-jointes/{photo['id']}" in prompt
    assert "--- notes.txt ---\nà retenir" in prompt  # short text: also in the message
    assert "photo.png (image" in prompt
    service.chat("", "text", [photo["id"]])  # a file alone is a message too
    assert "Regarde ce que je te joins." in service.cli.calls[-1]["prompt"]
    with pytest.raises(ValueError, match="introuvable"):
        service.chat("x", "text", ["../../secret.txt"])
