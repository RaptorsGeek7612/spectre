"""Tests for face recognition logic: face book, presence, service hooks, API (no camera)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import tools
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate
from spectre.assistant.service import AssistantService
from spectre.assistant.vision.faces import (
    AWAY_AFTER_S,
    GONE_AFTER_S,
    SPOOF,
    UNKNOWN,
    FaceBook,
    Presence,
    cosine,
    describe_presence,
    is_live,
)
from tests.test_assistant_service import FakeVoice, _drain, api, home, service  # noqa: F401
from tests.test_web import Client

ME = [1.0, 0.0, 0.2]
PHOTO = {"feature": [1.0, 0.0, 0.2], "live": False}
ME_AGAIN = [0.95, 0.05, 0.25]
SOMEONE = [0.0, 1.0, 0.0]


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "spectre.db")
    yield database
    database.close()


def test_is_live() -> None:
    assert is_live(2.0, -1.0) and not is_live(-0.5, 1.5) and is_live(1.0, 1.0)


def test_cosine() -> None:
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0


def test_face_book(db: Database) -> None:
    book = FaceBook(db)
    assert book.identify(ME) == (UNKNOWN, 0.0)
    for bad in (("", [ME]), ("Barth", [])):
        with pytest.raises(ValueError):
            book.enroll(*bad)
    assert book.enroll(" Barth ", [ME, ME_AGAIN]) == 2
    name, score = book.identify(ME_AGAIN)
    assert name == "Barth" and score > 0.99
    assert book.identify(SOMEONE)[0] == UNKNOWN
    assert [(p["name"], p["samples"]) for p in book.people()] == [("Barth", 2)]
    assert json.loads(db.one("SELECT feature FROM faces")["feature"]) == ME  # type: ignore[index]
    assert book.forget("Barth") == 2 and book.people() == []
    with pytest.raises(KeyError):
        book.forget("Barth")


def test_presence_arrivals(db: Database) -> None:
    now = [1000.0]
    arrivals: list[tuple[str, float]] = []
    presence = Presence(db, lambda n, away: arrivals.append((n, away)), lambda: now[0])
    assert presence.sighting(["Barth", UNKNOWN]) == ["Barth"]
    now[0] += 10
    presence.sighting(["Barth"])
    assert arrivals == [("Barth", 0.0)]  # first sighting only
    now[0] += GONE_AFTER_S + 1
    assert presence.sighting([]) == []
    now[0] += AWAY_AFTER_S
    presence.sighting(["Barth"])
    assert arrivals[-1][0] == "Barth" and arrivals[-1][1] >= AWAY_AFTER_S
    assert presence.present() == ["Barth"]


def test_describe_presence(db: Database) -> None:
    assert "pas active" in describe_presence(db)
    presence = Presence(db, lambda *a: None, lambda: 0.0)
    presence.sighting([UNKNOWN])
    assert describe_presence(db).endswith(": 1 personne(s) que je ne connais pas")
    presence.sighting(["Barth", UNKNOWN, UNKNOWN, SPOOF])
    assert describe_presence(db).endswith(
        ": Barth et 2 personne(s) que je ne connais pas"
        " et 1 photo(s) ou écran(s) présenté(s) à la caméra"
    )
    presence.last_seen.clear()
    presence.sighting([])
    assert describe_presence(db).endswith(": personne")


def L(feature: list[float]) -> dict[str, Any]:  # noqa: N802 - a live face
    return {"feature": feature, "live": True}


class FakeCamera:
    def __init__(self, *looks: list[dict[str, Any]]) -> None:
        self.looks = list(looks)
        self.stop = threading.Event()

    def grab(self) -> list[dict[str, Any]]:
        return self.looks.pop(0) if self.looks else []


def test_service_faces(service: AssistantService) -> None:  # noqa: F811
    with pytest.raises(ValueError, match="caméra"):
        service.enroll_face("Barth")
    service.attach_camera(FakeCamera([L(ME)], [], [L(ME), L(SOMEONE)], [PHOTO], [L(ME_AGAIN)]))
    with pytest.raises(ValueError, match="bien voir"):
        service.enroll_face("Barth", samples=6, attempts=3)
    service.attach_camera(FakeCamera(*[[L(ME)]] * 3))
    assert service.enroll_face("Barth", samples=3) == 3
    voice = FakeVoice()
    service.attach_voice(voice)
    service.set_voice_state("sleeping")
    q = service.subscribe()
    service.on_faces([L(ME_AGAIN), L(SOMEONE), PHOTO])
    assert service.db.one("SELECT text FROM events WHERE kind = 'spoof'")
    service.on_faces([PHOTO])  # logged at most once a minute
    assert len(service.db.all("SELECT id FROM events WHERE kind = 'spoof'")) == 1
    deadline = time.monotonic() + 2
    while not voice.triggered and time.monotonic() < deadline:
        time.sleep(0.01)
    events = _drain(q)
    # the line the model wrote (here the fake's "Réponse."), spoken, then Spectre listens
    assert {"type": "arrival", "name": "Barth", "text": "Réponse.", "speak": True} in events
    assert {"type": "presence", "people": ["Barth"], "unknown": 1, "spoof": 1} in events
    assert voice.said == ["Réponse."] and voice.triggered == 1
    assert service.status()["present"] == ["Barth"] and service.status()["camera"]
    gate = Gate(service.db)
    assert "Barth" in tools.execute(gate, service.ctx, "who_is_there", {})
    assert service.forget_face("Barth") == 3 and service.presence.present() == []
    service.stop()
    assert service.camera.stop.is_set()


def test_face_routes(api: Client, service: AssistantService) -> None:  # noqa: F811
    assert api.json("GET", "/api/assistant/faces")[1] == {"camera": False, "people": []}
    assert api.json("POST", "/api/assistant/faces/enroll", {"name": "Barth"})[0] == 400
    service.attach_camera(FakeCamera(*[[L(ME)]] * 6))
    service.config.user_name = "Barth"
    assert api.json("POST", "/api/assistant/faces/enroll", {}) == (
        200,
        {"name": "Barth", "samples": 6},
    )
    people: Any = api.json("GET", "/api/assistant/faces")[1]
    assert people["camera"] and people["people"][0]["name"] == "Barth"
    assert api.json("POST", "/api/assistant/faces/Barth/forget", {}) == (200, {"removed": 6})
    assert api.json("POST", "/api/assistant/faces/Barth/forget", {})[0] == 404


class PhoneCamera(FakeCamera):
    """A camera whose engine reads JPEG pictures sent by the phone."""

    def __init__(self, *looks: list[dict[str, Any]]) -> None:
        super().__init__(*looks)
        self.engine = self
        self.pictures: list[bytes] = []

    def embeddings_jpeg(self, data: bytes) -> list[dict[str, Any]]:
        if data == b"illisible":
            raise ValueError("image illisible")
        self.pictures.append(data)
        return self.grab()


def test_remote_frame(service: AssistantService) -> None:  # noqa: F811
    with pytest.raises(ValueError, match="reconnaissance des visages"):
        service.remote_frame(b"jpeg")
    service.attach_camera(PhoneCamera(*[[L(ME)]] * 3, [L(ME_AGAIN), L(SOMEONE)]))
    assert service.enroll_face("Barth", samples=3) == 3
    with pytest.raises(ValueError, match="vide"):
        service.remote_frame(b"")
    assert service.remote_frame(b"jpeg") == {"faces": 2, "present": ["Barth"]}
    assert service.camera.pictures == [b"jpeg"]
    with pytest.raises(ValueError, match="illisible"):
        service.remote_frame(b"illisible")


def test_frame_route(api: Client, service: AssistantService) -> None:  # noqa: F811
    headers = {"Content-Type": "image/jpeg"}
    status, _, body = api.request("POST", "/api/assistant/frame", raw=b"jpeg", headers=headers)
    assert status == 400 and "reconnaissance" in json.loads(body)["error"]
    service.attach_camera(PhoneCamera([L(SOMEONE)]))
    status, _, body = api.request("POST", "/api/assistant/frame", raw=b"jpeg", headers=headers)
    assert status == 200 and json.loads(body) == {"faces": 1, "present": []}
