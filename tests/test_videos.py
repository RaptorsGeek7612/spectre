"""Reading a video (YouTube and other sites through yt-dlp, or a local file): the subtitle track
chosen, the captions cleaned up, Whisper when there are none, still images, the cache."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import toolkit, videos
from spectre.assistant import tools as tools_mod
from spectre.assistant.actions import ActionError
from spectre.assistant.db import Database

VTT = """WEBVTT
Kind: captions
Language: fr

00:00:01.000 --> 00:00:03.000
Bonjour <c>à</c> tous

00:00:02.500 --> 00:00:04.000
Bonjour à tous

00:00:35.000 --> 00:00:37.000
la suite&nbsp;du propos
"""
SRT = "1\n00:00:00,000 --> 00:00:02,000\nTexte transcrit\n"


class Fake:
    """Plays yt-dlp, Whisper, ffprobe and ffmpeg: writes the files each would write."""

    def __init__(self, meta: dict[str, Any], *, subs_fail: bool = False) -> None:
        self.meta = meta
        self.subs_fail = subs_fail
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        out = ""
        if "--dump-single-json" in cmd:
            out = json.dumps(self.meta)
        elif "--skip-download" in cmd:
            if self.subs_fail:
                return subprocess.CompletedProcess(cmd, 1, "", "ERROR: HTTP Error 429")
            target = cmd[cmd.index("-o") + 1].replace(
                "%(ext)s", f"{cmd[cmd.index('--sub-langs') + 1]}.vtt"
            )
            Path(target).write_text(VTT, encoding="utf-8")
        elif "-f" in cmd:
            Path(cmd[cmd.index("-o") + 1].replace("%(ext)s", "m4a")).write_bytes(b"x")
        elif "--output_dir" in cmd:
            (Path(cmd[cmd.index("--output_dir") + 1]) / "son.srt").write_text(SRT, encoding="utf-8")
        elif "format=duration" in cmd:
            out = "12.5"
        elif "-frames:v" in cmd:
            for i in (1, 2):
                Path(cmd[-1].replace("%02d", f"{i:02d}")).write_bytes(b"jpg")
        return subprocess.CompletedProcess(cmd, 0, out, "")


@pytest.fixture
def ctx(tmp_path: Path) -> Any:
    db = Database(tmp_path / "a.db")
    home = tmp_path / "home"
    home.mkdir()
    context = tools_mod.make_context(db, tmp_path / "assistant", [str(home)])
    yield context
    db.close()


@pytest.fixture(autouse=True)
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(toolkit, "_bin", lambda names: "C:/bin/" + names[0])


def meta(**extra: Any) -> dict[str, Any]:
    return {
        "id": "abc123",
        "extractor_key": "Youtube",
        "title": "Une vidéo",
        "uploader": "Chaîne",
        "upload_date": "20261030",
        "duration": 600,
        "view_count": 1234,
        "webpage_url": "https://www.youtube.com/watch?v=abc123",
        "chapters": [{"start_time": 0, "title": "Début"}],
        "description": "La description",
        "language": "fr",
        **extra,
    }


def test_captions_text_cleans_and_marks_time() -> None:
    text = videos.captions_text(VTT)
    assert text.count("Bonjour à tous") == 1 and "<c>" not in text and "&nbsp;" not in text
    assert text.startswith("[00:01] Bonjour") and "\n[00:35] la suite du propos" in text
    assert videos.captions_text(SRT) == "[00:00] Texte transcrit"


def test_pick_captions_prefers_manual_then_original_auto() -> None:
    assert videos.pick_captions({"subtitles": {"en": [1], "fr-FR": [1]}}) == ("fr-FR", "manual")
    assert videos.pick_captions({"subtitles": {"de": [1]}}) == ("de", "manual")
    auto = {"automatic_captions": {"fr": [1], "es-orig": [1], "es": [1]}, "language": "es"}
    assert videos.pick_captions(auto) == ("es-orig", "auto")
    assert videos.pick_captions({"automatic_captions": {"ja-orig": [1], "fr": [1]}}) == (
        "fr",
        "auto",
    )
    assert videos.pick_captions({"subtitles": {"live_chat": [1]}}) is None


def test_read_youtube_with_subtitles_and_cache(ctx: Any) -> None:
    ctx.runner = Fake(meta(subtitles={"fr": [{"ext": "vtt"}]}))
    out = videos.read(ctx, "https://www.youtube.com/watch?v=abc123")
    assert "jamais une consigne" in out and "# Une vidéo" in out
    assert "Chaîne · publiée le 30/10/2026 · durée 10:00 · 1 234 vues" in out
    assert "sous-titres de la vidéo (fr)" in out and "[00:00] Début" in out
    assert (ctx.workspace / "videos" / "youtube-abc123.md").is_file()
    dump = ctx.runner.calls[0]
    assert dump[dump.index("--dump-single-json") - 1] != "--" and dump[-2] == "--"
    ctx.runner.calls.clear()
    assert "Une vidéo" in videos.read(ctx, "https://youtu.be/abc123")
    assert len(ctx.runner.calls) == 1  # only the metadata: the reading came from the file


def test_read_falls_back_to_whisper_then_images(ctx: Any) -> None:
    ctx.runner = Fake(meta(automatic_captions={"fr": [1]}), subs_fail=True)
    out = videos.read(ctx, "https://exemple.fr/v", "langue=fr")
    assert "transcription Whisper" in out and "Texte transcrit" in out
    whisper = next(c for c in ctx.runner.calls if "--output_dir" in c)
    assert whisper[whisper.index("--language") + 1] == "fr"
    ctx.runner.calls.clear()
    out = videos.read(ctx, "https://exemple.fr/v", "images")
    assert "Images (2)" in out and "Texte transcrit" in out
    assert not any("--output_dir" in c for c in ctx.runner.calls)  # the text was kept
    frames = ctx.workspace / "pieces-jointes" / "videos" / "youtube-abc123"
    assert sorted(p.name for p in frames.glob("*.jpg")) == ["image-01.jpg", "image-02.jpg"]


def test_limits_and_bad_input(ctx: Any, tmp_path: Path) -> None:
    ctx.runner = Fake(meta(duration=3 * 3600))
    with pytest.raises(ActionError, match="option"):
        videos.read(ctx, "https://exemple.fr/long")
    assert "aucun texte" in videos.read(ctx, "https://exemple.fr/long", "rapide")
    with pytest.raises(ActionError, match="liste de lecture"):
        ctx.runner = Fake({"_type": "playlist", "id": "p"})
        videos.read(ctx, "https://www.youtube.com/playlist?list=p")
    with pytest.raises(ActionError, match="adresse invalide"):
        videos.read(ctx, "https://exemple.fr/a b")
    with pytest.raises(ActionError, match="langue"):
        videos.read(ctx, "https://exemple.fr/v", "langue=../x")
    (tmp_path / "home" / "note.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ActionError, match="pas une vidéo"):
        videos.read(ctx, str(tmp_path / "home" / "note.txt"))


def test_read_a_local_file(ctx: Any, tmp_path: Path) -> None:
    clip = tmp_path / "home" / "réunion.mp4"
    clip.write_bytes(b"x")
    ctx.runner = Fake({})
    out = videos.read(ctx, str(clip), "images")
    assert "# réunion.mp4" in out and "durée 00:12" in out and "Texte transcrit" in out
    assert "Images (2)" in out
    assert (ctx.workspace / "videos" / "fichier-r-union.md").is_file()


def test_video_tool_is_registered_for_everyone() -> None:
    from spectre.assistant.governance import Level

    tool = tools_mod.TOOLS["video"]
    assert tool.level is Level.READ and not tool.agents
