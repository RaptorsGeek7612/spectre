"""Kyra's studio: images and videos through the local ComfyUI (a fake server here)."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import media
from spectre.assistant import tools as tools_mod
from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate


class FakeComfy:
    """Answers like ComfyUI: queue, history, view."""

    def __init__(self, *, up: bool = True, status: str = "success") -> None:
        self.up = up
        self.status = status
        self.done = False
        self.queued: list[dict[str, Any]] = []

    def __call__(self, request: Any, timeout: float) -> io.BytesIO:
        url = request.full_url
        if not self.up:
            raise urllib.error.URLError("refused")
        if url.endswith("/system_stats"):
            return io.BytesIO(b"{}")
        if url.endswith("/prompt"):
            self.queued.append(json.loads(request.data)["prompt"])
            return io.BytesIO(json.dumps({"prompt_id": "p1"}).encode())
        if "/history/" in url:
            if not self.done:
                return io.BytesIO(b"{}")
            entry = {
                "status": {
                    "status_str": self.status,
                    "completed": self.status == "success",
                    "messages": [["x", {"m": "OOM"}]],
                },
                "outputs": {
                    "10": {
                        "images": [
                            {
                                "filename": "image_00001_.png",
                                "subfolder": "spectre",
                                "type": "output",
                            }
                        ]
                    }
                },
            }
            return io.BytesIO(json.dumps({"p1": entry}).encode())
        if "/view?" in url:
            assert "filename=image_00001_.png" in url and "subfolder=spectre" in url
            return io.BytesIO(b"PNGDATA")
        raise AssertionError(url)


@pytest.fixture
def db(tmp_path: Path) -> Any:
    database = Database(tmp_path / "a.db")
    yield database
    database.close()


def test_image_job_is_queued_collected_and_announced(db: Database, tmp_path: Path) -> None:
    comfy = FakeComfy()
    studio = media.Studio(db, AssistantConfig(), tmp_path, comfy)
    job = studio.submit("image", "  un château enneigé ", width=1000, height=3000, agent="chatgpt")
    assert job["width"] == 992 and job["height"] == media.MAX_SIDE and job["minutes"] >= 1
    workflow = comfy.queued[0]
    assert workflow["5"]["inputs"]["text"] == "un château enneigé"
    assert workflow["1"]["inputs"]["unet_name"].startswith("z_image_turbo")
    said: list[tuple[str, str, str]] = []
    assert studio.poll(lambda *a: said.append(a)) == []  # still working
    comfy.done = True
    assert studio.poll(lambda *a: said.append(a)) == [job["id"]]
    saved = tmp_path / "workspace" / "medias" / f"image-{job['id']:04d}-image_00001_.png"
    assert saved.read_bytes() == b"PNGDATA"
    assert said[0][0] == "media" and "Image prête" in said[0][1] and str(saved) in said[0][2]
    row = studio.jobs()[0]
    assert row["status"] == "done" and row["files"] == [str(saved)] and row["agent"] == "chatgpt"


def test_video_job_and_failures(db: Database, tmp_path: Path) -> None:
    comfy = FakeComfy(status="error")
    studio = media.Studio(db, AssistantConfig(), tmp_path, comfy)
    job = studio.submit("video", "des vagues", width=641, height=353, seconds=2)
    latent = comfy.queued[0]["7"]["inputs"]
    assert (latent["width"], latent["height"], latent["length"]) == (640, 352, 49)
    assert comfy.queued[0]["11"]["inputs"]["format"] == "mp4"
    comfy.done = True
    said: list[Any] = []
    studio.poll(lambda *a: said.append(a))
    assert studio.jobs()[0]["status"] == "failed" and "échouée" in said[0][1] and job["id"] == 1
    with pytest.raises(media.MediaError, match="décris"):
        studio.submit("image", " ", width=512, height=512)
    with pytest.raises(media.MediaError, match="type"):
        studio.submit("son", "x", width=512, height=512)
    assert media.estimate("video", 640, 352, 49) > media.estimate("video", 320, 192, 9)


def test_comfyui_must_be_reachable_or_startable(db: Database, tmp_path: Path) -> None:
    config = AssistantConfig(comfyui_dir=str(tmp_path / "nowhere"))
    studio = media.Studio(db, config, tmp_path, FakeComfy(up=False))
    with pytest.raises(media.MediaError, match="start_comfyui.cmd"):
        studio.submit("image", "x", width=512, height=512)
    assert not media.installed(config)
    (tmp_path / "nowhere").mkdir()
    (tmp_path / "nowhere" / "start_comfyui.cmd").write_text("@echo off", encoding="utf-8")
    assert media.installed(config)


def test_the_studio_is_kyras(db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "assistant"
    AssistantConfig(comfyui_dir=str(tmp_path / "no-comfyui")).save(root)  # never the real one
    ctx = tools_mod.make_context(db, root, [str(tmp_path)])
    gate = Gate(db)
    ctx.agent = "cursor"
    refused = tools_mod.execute(gate, ctx, "generate_image", {"prompt": "x"})
    assert refused.startswith("REFUSÉ") and "Kyra" in refused
    comfy = FakeComfy()
    monkeypatch.setattr(media.urllib.request, "urlopen", comfy)
    ctx.agent = "chatgpt"
    answer = tools_mod.execute(
        gate, ctx, "generate_image", {"prompt": "un loup", "width": 768, "height": 768}
    )
    assert answer.startswith("Création #1 lancée") and "768×768" in answer
    answer = tools_mod.execute(gate, ctx, "generate_video", {"prompt": "la mer", "seconds": 1})
    assert "vidéo" in answer
    listing = tools_mod.execute(gate, ctx, "media_jobs", {})
    assert "#1 image [running] un loup" in listing and "#2 video" in listing
    ctx.agent = "chatgpt"
    monkeypatch.setattr(media.urllib.request, "urlopen", FakeComfy(up=False))
    failed = tools_mod.execute(gate, ctx, "generate_image", {"prompt": "x"})
    assert failed.startswith("ÉCHEC") and "ComfyUI" in failed


def test_media_tick_announces_finished_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spectre.assistant.proactive import Proactive
    from tests.test_assistant_engines import Rooted

    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    proactive = Proactive(db, Rooted(root), AssistantConfig(), lambda *a: None, fetch=lambda u: {})  # type: ignore[arg-type]
    assert proactive.media() == []
    comfy = FakeComfy()
    monkeypatch.setattr(media.urllib.request, "urlopen", comfy)
    media.Studio(db, proactive.config, root).submit("image", "x", width=512, height=512)
    comfy.done = True
    assert proactive.media() == [1]
    row = db.one("SELECT title FROM initiatives WHERE kind = 'media'")
    assert row and row["title"].startswith("Image prête")
    db.close()
