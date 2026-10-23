"""Spectre's competences: the local skills its brain can list and read."""

from __future__ import annotations

from pathlib import Path

import pytest

from spectre.assistant import competences, tools
from spectre.assistant.brain import Brain
from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database
from tests.test_assistant_brain import FakeCLI


def _skill(root: Path, name: str, description: str = "Quand l'utiliser.", body: str = "") -> None:
    folder = root / name
    folder.mkdir(parents=True)
    head = f"---\nname: {name}\ndescription: {description}\n---\n" if description else ""
    (folder / "SKILL.md").write_text(f"{head}\n# {name}\n\n{body}", encoding="utf-8")


@pytest.fixture
def skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "skills"
    _skill(root, "spectre-amitie", "Amitié, loyauté, respect.", "Vouloir son bien.")
    _skill(root, "labs-media", "FFmpeg et OpenCV.")
    _skill(root, "spectre-builder", "Pour coder Spectre.")  # development only
    _skill(root, "sans-description", "")
    (root / "vide").mkdir()
    monkeypatch.setenv(competences.DIR_ENV, str(root))
    return root


def test_available_and_read(skills: Path) -> None:
    assert [c.name for c in competences.available()] == ["labs-media", "spectre-amitie"]
    text = competences.read("SPECTRE-AMITIE")
    assert text.startswith("# spectre-amitie") and "Vouloir son bien." in text
    assert "description:" not in text
    with pytest.raises(ValueError, match="disponibles : labs-media, spectre-amitie"):
        competences.read("spectre-builder")
    assert competences.catalogue() == (
        "- labs-media : FFmpeg et OpenCV.\n- spectre-amitie : Amitié, loyauté, respect."
    )


def test_missing_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(competences.DIR_ENV, str(tmp_path / "absent"))
    assert competences.available() == [] and competences.catalogue() == ""
    with pytest.raises(ValueError, match="aucune"):
        competences.read("x")


def test_default_folder_is_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(competences.DIR_ENV, raising=False)
    assert competences.skills_dir().parts[-2:] == (".claude", "skills")


def test_unreadable_file_is_skipped(skills: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = Path.read_text

    def flaky(self: Path, *a: object, **kw: object) -> str:
        if self.parent.name == "labs-media":
            raise OSError("verrouillé")
        return real(self, *a, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", flaky)
    assert [c.name for c in competences.available()] == ["spectre-amitie"]


def test_tool_and_prompt(skills: Path, tmp_path: Path) -> None:
    db = Database(tmp_path / "spectre.db")
    ctx = tools.make_context(db, tmp_path, [str(tmp_path)])
    assert "Vouloir son bien." in tools._competence(ctx, "spectre-amitie")
    with pytest.raises(tools.ActionError, match="inconnue"):
        tools._competence(ctx, "nope")
    prompt = Brain(db, FakeCLI(tmp_path), AssistantConfig()).system_prompt()  # type: ignore[arg-type]
    assert "competence(name)" in prompt and "- spectre-amitie : Amitié" in prompt
    assert "JARVIS" in prompt and "attends un oui clair" in prompt
    db.close()


def test_prompt_without_competences(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(competences.DIR_ENV, str(tmp_path / "absent"))
    db = Database(tmp_path / "spectre.db")
    prompt = Brain(db, FakeCLI(tmp_path), AssistantConfig()).system_prompt()  # type: ignore[arg-type]
    assert "competence(name)" not in prompt and "Tes compétences" not in prompt
    db.close()


def test_real_competences_are_well_formed() -> None:
    names = {c.name for c in competences.available(competences.skills_dir())}
    assert {
        "spectre-personnalite",
        "spectre-amitie",
        "spectre-developpement-humain",
        "spectre-culture",
    } <= names
    for name in names:
        assert len(competences.read(name)) > 200
