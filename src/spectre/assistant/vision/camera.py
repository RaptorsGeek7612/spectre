"""Webcam + YuNet (detection, MIT), SFace (recognition, Apache 2.0), MiniFASNet (anti-spoofing,
Apache 2.0): every model is downloaded from its official repository and checked by SHA-256.

Hardware glue, exercised by hand (excluded from coverage): the logic lives in `faces.py`.
"""

from __future__ import annotations

import hashlib
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

DETECTOR = "face_detection_yunet_2023mar.onnx"
RECOGNIZER = "face_recognition_sface_2021dec.onnx"
LIVENESS = "antispoof_minifasnet_quantized.onnx"
MODELS = {  # name: (url, sha256)
    DETECTOR: (
        "https://huggingface.co/opencv/face_detection_yunet/resolve/main/" + DETECTOR,
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    RECOGNIZER: (
        "https://huggingface.co/opencv/face_recognition_sface/resolve/main/" + RECOGNIZER,
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
    LIVENESS: (
        "https://raw.githubusercontent.com/facenox/face-antispoof-onnx/"
        "2b0a221fda633ac0aa0b0797b578580ecbbb4f81/models/best_model_quantized.onnx",
        "fde20585635cae62ed1d41796f76b6f8bc4b92cd91ec1cf0f1bc6485d2d587a9",
    ),
}
LIVENESS_SIZE = 128
LIVENESS_EXPANSION = 1.5  # crop 1.5x the face box, as the model was trained
MIN_SCORE = 0.85  # detector confidence: ignore blurry or partial faces


def ensure_models(models: Path) -> dict[str, Path]:
    folder = models / "faces"
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, (url, digest) in MODELS.items():
        path = folder / name
        if not path.exists():
            tmp = path.with_suffix(".part")
            urllib.request.urlretrieve(url, tmp)  # noqa: S310 - fixed https URL
            if hashlib.sha256(tmp.read_bytes()).hexdigest() != digest:
                tmp.unlink()
                raise RuntimeError(f"modèle {name} corrompu ou modifié (empreinte SHA-256)")
            tmp.replace(path)
        paths[name] = path
    return paths


class FaceEngine:
    """Detect faces in a BGR frame; for each, an SFace embedding and a liveness verdict."""

    def __init__(self, models: Path) -> None:
        import cv2
        import numpy as np
        import onnxruntime

        paths = ensure_models(models)
        self.cv2, self.np = cv2, np
        self.detector = cv2.FaceDetectorYN.create(
            str(paths[DETECTOR]), "", (320, 240), MIN_SCORE, 0.3, 50
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(paths[RECOGNIZER]), "")
        self.liveness = onnxruntime.InferenceSession(
            str(paths[LIVENESS]), providers=["CPUExecutionProvider"]
        )
        self.liveness_input = self.liveness.get_inputs()[0].name

    def _liveness_crop(self, rgb: Any, box: Any) -> Any:
        """Square crop of the face, 1.5x larger, edges mirrored, letterboxed to 128x128 CHW."""
        cv2, np = self.cv2, self.np
        x, y, w, h = (float(v) for v in box[:4])
        side = max(w, h) * LIVENESS_EXPANSION
        x0, y0 = int(x + w / 2 - side / 2), int(y + h / 2 - side / 2)
        size = int(side)
        height, width = rgb.shape[:2]
        pad = cv2.copyMakeBorder(
            rgb[max(0, y0) : min(height, y0 + size), max(0, x0) : min(width, x0 + size)],
            max(0, -y0),
            max(0, y0 + size - height),
            max(0, -x0),
            max(0, x0 + size - width),
            cv2.BORDER_REFLECT_101,
        )
        face = cv2.resize(pad, (LIVENESS_SIZE, LIVENESS_SIZE), interpolation=cv2.INTER_AREA)
        return face.transpose(2, 0, 1).astype(np.float32) / 255.0

    def embeddings(self, frame: Any) -> list[dict[str, Any]]:
        """[{"feature": [128 floats], "live": bool}] for each face found."""
        from spectre.assistant.vision.faces import is_live

        height, width = frame.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(frame)
        if faces is None:
            return []
        rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
        crops = self.np.stack([self._liveness_crop(rgb, face) for face in faces])
        logits = self.liveness.run(None, {self.liveness_input: crops})[0]
        out = []
        for face, (real, spoof) in zip(faces, logits, strict=True):
            aligned = self.recognizer.alignCrop(frame, face)
            out.append(
                {
                    "feature": [float(v) for v in self.recognizer.feature(aligned).flatten()],
                    "live": is_live(float(real), float(spoof)),
                }
            )
        return out


class Camera:
    """Looks every `every_s` seconds; reports embeddings to `on_faces`. Off unless started."""

    def __init__(
        self,
        engine: FaceEngine,
        on_faces: Callable[[list[dict[str, Any]]], None],
        index: int = 0,
        every_s: float = 1.5,
    ) -> None:
        self.engine = engine
        self.on_faces = on_faces
        self.index = index
        self.every_s = every_s
        self.stop = threading.Event()
        self._lock = threading.Lock()
        self._capture: Any = None

    def _open(self) -> Any:
        cv2 = self.engine.cv2
        capture = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture = cv2.VideoCapture(self.index)
        if not capture.isOpened():
            raise RuntimeError(f"caméra {self.index} introuvable ou occupée")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return capture

    def grab(self) -> list[dict[str, Any]]:
        """One look through the camera (also used to enroll a face)."""
        with self._lock:
            if self._capture is None:
                self._capture = self._open()
            ok, frame = self._capture.read()
            if not ok:
                self._capture.release()
                self._capture = None
                return []
            return self.engine.embeddings(frame)

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                self.on_faces(self.grab())
            except Exception:  # noqa: BLE001 - a camera hiccup must not kill the watcher
                time.sleep(2)
            self.stop.wait(self.every_s)
        with self._lock:
            if self._capture is not None:
                self._capture.release()
                self._capture = None

    def start(self) -> None:
        threading.Thread(target=self.run, name="spectre-camera", daemon=True).start()
