"""Bring the team's portraits to life for the video call (LivePortrait, on this PC's processor).

usage: tools/animate_portraits.cmd [key ...] [--only listen|talk] [--force]

For each picture in ~/.spectre/assistant/portraits (opus.png, chatgpt.png...), two seamless loops
in ~/.spectre/assistant/portraits-anim, played by the call while the agent is on it:
  <key>-listen.webm  listening: blinks, glances, small nods (driving video d14)
  <key>-talk.webm    talking (driving video d13)
Each loop plays forward then backward, so it never jumps. Loops already made are kept (--force
redoes them); a new picture removes its loops (team.save_portrait).

Needs, all open source: ComfyUI in ~/ComfyUI with Kijai's ComfyUI-LivePortraitKJ node (MIT; its
FaceAlignment cropper, so no InsightFace), LivePortrait's example driving videos (MIT) and the
extra packages (scikit-image, numba, onnxruntime, opencv) in ~/Apps/liveportrait. Run on the base
Python with the ComfyUI venv's packages on PYTHONPATH, as the .cmd does: Smart App Control blocks
the venv's own python.exe. About 4 s per frame here, some 10 minutes per agent.
"""

import argparse
import importlib
import os
import subprocess
import sys
import time
import zlib

HOME = os.path.expanduser("~")
COMFY = os.path.join(HOME, "ComfyUI")
LAB = os.path.join(HOME, "Apps", "liveportrait")
DATA = os.path.join(HOME, ".spectre", "assistant")

# kind: driving video, its length (s), seconds used, motion strength, lips follow the driver
# Gentle strengths: strong deltas on a single photo warp the face. Listening keeps the mouth shut.
PLAN = {
    "listen": ("d14.mp4", 17.8, 4.0, 0.40, False),
    "talk": ("d13.mp4", 11.7, 5.0, 0.65, True),
}
FPS = 15
WIDTH = 384
XFADE = 5  # frames blended tail-into-head for a seamless forward loop (no jerky reverse)

ap = argparse.ArgumentParser()
ap.add_argument("keys", nargs="*")
ap.add_argument("--portraits", default=os.path.join(DATA, "portraits"))
ap.add_argument("--out", default=os.path.join(DATA, "portraits-anim"))
ap.add_argument("--only", choices=list(PLAN))
ap.add_argument("--force", action="store_true")
args = ap.parse_args()

sys.argv = [sys.argv[0], "--cpu"]  # ComfyUI reads its options from the command line
sys.path[:0] = [COMFY, os.path.join(COMFY, "custom_nodes")]

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

torch.set_num_threads(os.cpu_count() or 8)
torch.set_grad_enabled(False)  # inference only: no graph kept frame after frame

import comfy.options  # noqa: E402

comfy.options.enable_args_parsing()
kj = importlib.import_module("ComfyUI-LivePortraitKJ.nodes")


def load_driving(path, start, seconds):
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        f"{start:.2f}",
        "-t",
        str(seconds),
        "-i",
        path,
        "-vf",
        f"fps={FPS},scale=256:256:force_original_aspect_ratio=increase,crop=256:256",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, 256, 256, 3)
    return torch.from_numpy(frames.copy()).float() / 255


def seamless(frames):
    # A forward-only loop: crossfade the last XFADE frames into the first ones, so the wrap from
    # the end back to the start is smooth. No reverse playback (blinks/nods look wrong reversed).
    o = XFADE
    if o <= 0 or len(frames) <= o * 2:
        return frames
    f = frames.astype(np.float32)
    w = np.linspace(0.0, 1.0, o, endpoint=False).reshape(-1, 1, 1, 1)
    head = f[-o:] * (1 - w) + f[:o] * w  # outgoing tail fades into the incoming head
    return np.concatenate([head, f[o:-o]]).clip(0, 255).astype(np.uint8)


def encode(frames, path):
    loop = seamless(frames)
    n, h, w, _ = loop.shape
    oh = WIDTH * h // w // 2 * 2
    enc = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{w}x{h}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-vf",
        f"scale={WIDTH}:{oh}:flags=lanczos",
        "-an",
        "-c:v",
        "libvpx-vp9",
        "-b:v",
        "0",
        "-crf",
        "32",
        "-row-mt",
        "1",
        "-pix_fmt",
        "yuv420p",
        path + ".part.webm",
    ]
    subprocess.run(enc, input=loop.tobytes(), check=True)
    os.replace(path + ".part.webm", path)


pipe = kj.DownloadAndLoadLivePortraitModels().loadmodel(precision="fp32")[0]
cropper = kj.LivePortraitLoadFaceAlignmentCropper().crop(
    "CPU", True, "blazeface_back_camera", "cpu", "fp32"
)[0]
os.makedirs(args.out, exist_ok=True)

names = sorted(
    f for f in os.listdir(args.portraits) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
)
for name in names:
    key = os.path.splitext(name)[0]
    if args.keys and key not in args.keys:
        continue
    src = Image.open(os.path.join(args.portraits, name)).convert("RGB")
    source = torch.from_numpy(np.asarray(src).copy()).float().unsqueeze(0) / 255
    crop_info = None
    for kind, (video, length, seconds, strength, lips) in PLAN.items():
        target = os.path.join(args.out, f"{key}-{kind}.webm")
        if (args.only and kind != args.only) or (os.path.exists(target) and not args.force):
            continue
        t0 = time.time()
        if crop_info is None:
            crop_info = kj.LivePortraitCropper().process(
                pipe, cropper, source, 512, 2.3, 0.0, -0.125, 0, "large-small", True
            )[1]
            if not crop_info["crop_info_list"][0]:
                print(f"{key}: no face found, skipped", flush=True)
                break
        # each agent its own stretch of the driving video, so they never move in step
        start = (
            (zlib.crc32(f"{key}{kind}".encode()) % 1000) / 1000 * max(0.0, length - seconds - 0.2)
        )
        driving = load_driving(os.path.join(LAB, "driving", video), start, seconds)
        cropped, out = kj.LivePortraitProcess().process(
            source_image=source,
            driving_images=driving,
            crop_info=crop_info,
            pipeline=pipe,
            lip_zero=not lips,  # listening: keep the mouth shut; talking: let the lips move
            lip_zero_threshold=0.03,
            stitching=True,
            relative_motion_mode="relative",
            driving_smooth_observation_variance=3e-6,
            delta_multiplier=strength,
            mismatch_method="constant",
        )
        full = kj.LivePortraitComposite().process(source, cropped, out)[0]
        encode((full.clamp(0, 1).numpy() * 255).astype(np.uint8), target)
        print(f"{key}-{kind}: {len(driving)} frames in {time.time() - t0:.0f}s", flush=True)
