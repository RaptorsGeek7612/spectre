"""Kyra's studio: images and videos made on this PC by ComfyUI (open source, local).

Kyra (the multimedia agent) asks for an image (Z-Image Turbo) or a short video (Wan 2.2 TI2V
5B); the request goes to the local ComfyUI server, which Spectre starts if it is not running.
Generation can take a long time on a PC without a dedicated graphics card (about half an hour
for an image), so a request is a job: Spectre's proactive loop follows it, copies the result to
`workspace/medias` and tells the user when it is ready. Nothing leaves the PC.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database, now_iso
from spectre.config import COMFY_MODELS

AGENT = "chatgpt"  # Kyra: the studio is hers
MAX_SIDE = 1536
MAX_SECONDS = 5
FPS = 24
START_WAIT_S = 90.0
IMAGE_STEP_S = 200.0  # one Z-Image step at 768×768 on this kind of CPU (measured)
VIDEO_STEP_S = 46.0  # one Wan 2.2 5B step at 320×192, 9 frames (measured)


class MediaError(ValueError):
    """A refused request or ComfyUI unavailable (the message is for Kyra and the user)."""


def image_workflow(
    prompt: str, width: int, height: int, seed: int, negative: str = "blurry ugly bad"
) -> dict[str, Any]:
    m = COMFY_MODELS["image"]
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": m["unet"]}},
        "2": {
            "class_type": "CLIPLoaderGGUF",
            "inputs": {"clip_name": m["clip"], "type": "lumina2"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": negative},
        },
        "7": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["7", 0],
                "seed": seed,
                "steps": 9,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {
            "class_type": "SaveImage",
            "inputs": {"images": ["9", 0], "filename_prefix": "spectre/image"},
        },
    }


def video_workflow(prompt: str, width: int, height: int, frames: int, seed: int) -> dict[str, Any]:
    m = COMFY_MODELS["video"]
    negative = "flou, déformé, texte, filigrane, image figée, mauvaise qualité"
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": m["unet"]}},
        "2": {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": m["clip"], "type": "wan"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "4": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8.0}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative}},
        "7": {
            "class_type": "Wan22ImageToVideoLatent",
            "inputs": {
                "vae": ["3", 0],
                "width": width,
                "height": height,
                "length": frames,
                "batch_size": 1,
            },
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["7", 0],
                "seed": seed,
                "steps": 20,
                "cfg": 5.0,
                "sampler_name": "uni_pc",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "CreateVideo", "inputs": {"images": ["9", 0], "fps": float(FPS)}},
        "11": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["10", 0],
                "filename_prefix": "spectre/video",
                "format": "mp4",
                "codec": "h264",
            },
        },
    }


def _round(value: int, step: int, low: int, high: int) -> int:
    return max(low, min(high, int(value) // step * step))


def estimate(kind: str, width: int, height: int, frames: int = 1) -> int:
    """Rough minutes on a CPU-only PC (what the user is told to expect)."""
    if kind == "image":
        return max(1, round(9 * IMAGE_STEP_S * width * height / (768 * 768) / 60))
    return max(1, round(20 * VIDEO_STEP_S * width * height * frames / (320 * 192 * 9) / 60))


class Studio:
    """ComfyUI jobs: submit, follow, collect."""

    def __init__(
        self, db: Database, config: AssistantConfig, root: Path, opener: Any = None
    ) -> None:
        self.db = db
        self.config = config
        self.root = root
        self.opener = opener or urllib.request.urlopen

    # ---- the ComfyUI server ------------------------------------------------------------------

    def _call(self, path: str, body: dict[str, Any] | None = None, timeout: float = 15.0) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.config.comfyui_url.rstrip("/") + path,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with self.opener(request, timeout=timeout) as response:
            raw = response.read()
        return (
            json.loads(raw or b"{}") if path != "/view" and not path.startswith("/view?") else raw
        )

    def running(self) -> bool:
        try:
            self._call("/system_stats", timeout=3)
        except (urllib.error.URLError, OSError, ValueError):
            return False
        return True

    def folder(self) -> Path:
        return (
            Path(self.config.comfyui_dir).expanduser()
            if self.config.comfyui_dir
            else Path.home() / "ComfyUI"
        )

    def ensure_running(self, sleep: Any = time.sleep) -> None:
        """Start ComfyUI (its own window-less process) when it is not answering."""
        if self.running():
            return
        launcher = self.folder() / "start_comfyui.cmd"
        if not launcher.is_file():
            raise MediaError(
                f"ComfyUI ne répond pas sur {self.config.comfyui_url} et je ne trouve pas "
                f"{launcher} pour le démarrer"
            )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        log = (self.folder() / "comfyui.log").open("ab")
        subprocess.Popen(  # noqa: S603 - the user's own launcher
            ["cmd", "/c", str(launcher)],
            cwd=self.folder(),
            stdout=log,
            stderr=log,
            creationflags=flags,
        )
        deadline = time.monotonic() + START_WAIT_S
        while time.monotonic() < deadline:
            sleep(3)
            if self.running():
                return
        raise MediaError("ComfyUI a été lancé mais ne répond pas encore : réessaie dans une minute")

    # ---- jobs --------------------------------------------------------------------------------

    def submit(
        self,
        kind: str,
        prompt: str,
        *,
        width: int,
        height: int,
        seconds: float = 2.0,
        agent: str = "",
        mission: int | None = None,
    ) -> dict[str, Any]:
        prompt = prompt.strip()
        if not prompt:
            raise MediaError("décris ce qu'il faut créer")
        seed = random.randint(0, 2**31 - 1)
        if kind == "image":
            width, height = _round(width, 16, 256, MAX_SIDE), _round(height, 16, 256, MAX_SIDE)
            workflow = image_workflow(prompt, width, height, seed)
            minutes = estimate("image", width, height)
        elif kind.startswith("portrait:"):
            width, height = PORTRAIT_SIZE
            workflow = image_workflow(prompt, width, height, seed, PORTRAIT_NEGATIVE)
            minutes = estimate("image", width, height)
        elif kind == "video":
            width, height = _round(width, 32, 160, 1280), _round(height, 32, 96, 720)
            frames = max(5, min(MAX_SECONDS * FPS, int(seconds * FPS)) // 4 * 4 + 1)
            workflow = video_workflow(prompt, width, height, frames, seed)
            minutes = estimate("video", width, height, frames)
        else:
            raise MediaError("type inconnu : image ou video")
        self.ensure_running()
        try:
            queued = self._call("/prompt", {"prompt": workflow})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise MediaError(f"ComfyUI a refusé la demande : {detail}") from exc
        job_id = self.db.execute(
            "INSERT INTO media_jobs(ts, kind, prompt, prompt_id, status, agent, mission_id) "
            "VALUES(?, ?, ?, ?, 'running', ?, ?)",
            (now_iso(), kind, prompt[:2000], str(queued.get("prompt_id", "")), agent, mission),
        )
        return {"id": job_id, "kind": kind, "width": width, "height": height, "minutes": minutes}

    def jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT * FROM media_jobs ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            row["files"] = json.loads(row["files"] or "[]")
        return rows

    def poll(self, notify: Any) -> list[int]:
        """Collect the finished jobs into the workspace and tell the user; returns their ids."""
        finished = []
        for job in self.db.all("SELECT * FROM media_jobs WHERE status = 'running'"):
            try:
                history = self._call(f"/history/{job['prompt_id']}").get(job["prompt_id"])
            except (urllib.error.URLError, OSError, ValueError):
                continue  # ComfyUI is busy or closed: try again at the next tick
            if not history:
                continue
            status = history.get("status") or {}
            if status.get("status_str") == "error":
                messages = json.dumps(status.get("messages", [])[-1:], ensure_ascii=False)[:400]
                self._close(job["id"], "failed", [], messages)
                notify("media", f"Création #{job['id']} échouée", f"ComfyUI : {messages}")
                finished.append(job["id"])
                continue
            if not status.get("completed"):
                continue
            files = self._collect(job, history.get("outputs") or {})
            self._close(job["id"], "done", files, "")
            if job["kind"].startswith("portrait:"):
                who = job["kind"].split(":", 1)[1]
                notify("media", "Portrait réaliste prêt", f"Nouveau portrait de l'agent {who}.")
            else:
                what = "Image prête" if job["kind"] == "image" else "Vidéo prête"
                notify("media", f"{what} (#{job['id']})", f"Kyra a terminé : {', '.join(files)}")
            finished.append(job["id"])
        return finished

    def _collect(self, job: dict[str, Any], outputs: dict[str, Any]) -> list[str]:
        portrait_for = job["kind"].split(":", 1)[1] if job["kind"].startswith("portrait:") else ""
        target = self.root / "workspace" / "medias"
        target.mkdir(parents=True, exist_ok=True)
        saved = []
        for node in outputs.values():
            for key in ("images", "videos", "gifs", "video"):
                for item in node.get(key) or []:
                    if not isinstance(item, dict) or "filename" not in item:
                        continue
                    query = urllib.parse.urlencode(
                        {
                            "filename": item["filename"],
                            "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output"),
                        }
                    )
                    data = self._call(f"/view?{query}")
                    if portrait_for:
                        from spectre.assistant import team

                        team.save_portrait(self.root, portrait_for, data)
                        saved.append(f"portrait:{portrait_for}")
                        continue
                    name = f"{job['kind']}-{job['id']:04d}-{Path(item['filename']).name}"
                    (target / name).write_bytes(data)
                    saved.append(str(target / name))
        return saved

    def _close(self, job_id: int, status: str, files: list[str], error: str) -> None:
        self.db.execute(
            "UPDATE media_jobs SET status = ?, files = ?, error = ?, done_at = ? WHERE id = ?",
            (status, json.dumps(files, ensure_ascii=False), error, now_iso(), job_id),
        )


PORTRAIT_SIZE = (512, 640)
PORTRAIT_NEGATIVE = (
    "cartoon, anime, drawing, illustration, 3d render, painting, deformed, extra fingers, "
    "blurry, lowres, watermark, text"
)
PORTRAIT_BASE = (
    "professional studio headshot portrait, photorealistic, {who}, soft cinematic lighting, "
    "shallow depth of field, looking at camera, upper body, "
    "against a solid vivid saturated {bg} seamless paper backdrop filling the whole frame, "
    "bold colourful {bg} studio background, evenly lit coloured backdrop, "
    "highly detailed skin, sharp focus, 85mm lens, natural colors"
)
# One realistic look per agent, faithful to its drawn avatar (gender, hair, role attire).
PORTRAIT_WHO = {
    "opus": "confident man in his 30s, short dark brown hair, calm blue-grey eyes, clean-shaven, sleek dark high-collar modern suit, composed authoritative expression",  # noqa: E501
    "sonnet": "friendly man in his late 20s, warm medium-brown skin, short black cropped hair, brown eyes, clean-shaven, dark green casual shirt, approachable smile",  # noqa: E501
    "haiku": "meticulous man in his 50s, fair skin, neat short silver-grey hair, round thin glasses, blue-grey eyes, clean-shaven, grey buttoned shirt",  # noqa: E501
    "chatgpt": "creative woman in her late 20s, tanned skin, long auburn hair, green eyes, small gold earrings, artistic violet top, bright imaginative look",  # noqa: E501
    "mistral": "focused man in his early 30s, brown skin, black undercut hair, short dark beard, dark eyes, charcoal hoodie, low-key lighting",  # noqa: E501
    "cursor": "elegant woman in her 30s, deep brown skin, black hair in a neat bun, dark eyes, small earrings, navy tailored blazer and white blouse",  # noqa: E501
    "antigravity": "poised woman in her 30s, fair skin, auburn shoulder-length bob, blue-grey eyes, tailored dark blazer, confident executive look",  # noqa: E501
    "simon": "careful man in his 50s, warm skin, short receding brown hair, square glasses, hazel eyes, clean-shaven, beige cardigan over a shirt",  # noqa: E501
    "shelby": "warm woman in her late 20s, fair skin, long wavy auburn hair, green eyes, small gold earrings, soft green top, gentle caring expression",  # noqa: E501
    "ysyss": "intelligent woman in her 30s, light-olive skin, dark hair in a bun, round glasses, blue-grey eyes, dark blue top, thoughtful look",  # noqa: E501
    "lexy": "sharp woman in her late 20s, fair skin, blonde bob hair, blue-grey eyes, small earrings, dark modern blazer, confident analytical look",  # noqa: E501
    "charlotte": "stylish creative woman in her early 30s, light skin with freckles, short asymmetric copper-red hair, hazel eyes, black turtleneck, small geometric earrings, keen artistic look",  # noqa: E501
    "celya": "dreamy literary woman in her 30s, warm beige skin, long dark curly hair, brown eyes, cream knit sweater, delicate necklace, soft thoughtful smile",  # noqa: E501
    "monty": "focused man in his 40s, olive skin, short dark hair greying at the temples, trimmed beard, dark eyes, thin round glasses, charcoal turtleneck, calm analytical look",  # noqa: E501
}


# A distinct studio-background colour per agent (echoes its drawn avatar), for the realistic
# portraits, so the eleven faces read apart at a glance.
PORTRAIT_BG = {
    "opus": "deep navy blue",
    "sonnet": "forest green",
    "haiku": "cool slate grey-blue",
    "chatgpt": "rich violet purple",
    "mistral": "warm dark amber brown",
    "cursor": "royal indigo blue",
    "antigravity": "deep burgundy maroon",
    "simon": "warm olive gold",
    "shelby": "soft teal green",
    "ysyss": "bright cobalt blue",
    "lexy": "plum magenta",
    "charlotte": "vivid coral orange",
    "celya": "deep emerald green",
    "monty": "dark steel teal",
}


def portrait_prompt(key: str, look: dict[str, Any] | None = None) -> str:
    """The realistic-portrait prompt for an agent (default look, or a custom one on request)."""
    who = PORTRAIT_WHO.get(key, "a person, neutral professional look")
    bg = PORTRAIT_BG.get(key, "dark neutral")
    return PORTRAIT_BASE.format(who=who, bg=bg)


def installed(config: AssistantConfig) -> bool:
    folder = (
        Path(config.comfyui_dir).expanduser() if config.comfyui_dir else Path.home() / "ComfyUI"
    )
    return (folder / "start_comfyui.cmd").is_file() or shutil.which("comfy") is not None
