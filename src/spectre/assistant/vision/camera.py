"""Webcam + OpenCV Zoo models: YuNet (detection, MIT) and SFace (recognition, Apache 2.0).

Hardware glue, exercised by hand (excluded from coverage): the logic lives in `faces.py`.
"""

from __future__ import annotations

import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "https://huggingface.co/opencv/face_detection_yunet/resolve/main/"
        "face_detection_yunet_2023mar.onnx"
    ),
    "face_recognition_sface_2021dec.onnx": (
        "https://huggingface.co/opencv/face_recognition_sface/resolve/main/"
        "face_recognition_sface_2021dec.onnx"
    ),
}
MIN_SCORE = 0.85  # detector confidence: ignore blurry or partial faces


def ensure_models(models: Path) -> dict[str, Path]:
    folder = models / "faces"
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, url in MODELS.items():
        path = folder / name
        if not path.exists():
            tmp = path.with_suffix(".part")
            urllib.request.urlretrieve(url, tmp)  # noqa: S310 - fixed https URL
            tmp.replace(path)
        paths[name] = path
    return paths


class FaceEngine:
    """Detect faces in a BGR frame and turn each into a 128-number SFace embedding."""

    def __init__(self, models: Path) -> None:
        import cv2

        paths = ensure_models(models)
        self.cv2 = cv2
        self.detector = cv2.FaceDetectorYN.create(
            str(paths["face_detection_yunet_2023mar.onnx"]), "", (320, 240), MIN_SCORE, 0.3, 50
        )
        self.recognizer = cv2.FaceRecognizerSF.create(
            str(paths["face_recognition_sface_2021dec.onnx"]), ""
        )

    def embeddings(self, frame: Any) -> list[list[float]]:
        height, width = frame.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(frame)
        if faces is None:
            return []
        out = []
        for face in faces:
            aligned = self.recognizer.alignCrop(frame, face)
            out.append([float(v) for v in self.recognizer.feature(aligned).flatten()])
        return out


class Camera:
    """Looks every `every_s` seconds; reports embeddings to `on_faces`. Off unless started."""

    def __init__(
        self,
        engine: FaceEngine,
        on_faces: Callable[[list[list[float]]], None],
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

    def grab(self) -> list[list[float]]:
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
