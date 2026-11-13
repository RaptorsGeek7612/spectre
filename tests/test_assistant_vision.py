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
    SPOOF_LOOKS,
    TRUST_S,
    UNKNOWN,
    UNSURE,
    FaceBook,
    Liveness,
    Presence,
    cosine,
    describe_presence,
    is_live,
    speaker_note,
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


def test_presence_confirms_newcomers_and_knows_the_moment(db: Database) -> None:
    now = [1000.0]
    arrivals: list[str] = []
    presence = Presence(db, lambda n, away: arrivals.append(n), lambda: now[0])
    assert presence.snapshot() is None  # the camera has not looked yet
    assert presence.sighting(["Barth"], confirm=True) == []  # one look: maybe a blur
    now[0] += 5
    assert presence.sighting(["Barth"], confirm=True) == []  # too long after: still one look
    now[0] += 0.25
    assert presence.sighting(["Barth", UNKNOWN], confirm=True) == ["Barth"]
    assert arrivals == ["Barth"]
    assert presence.snapshot() == {"people": ["Barth"], "unknown": 1, "spoof": 0, "unsure": 0}
    now[0] += 0.25
    presence.sighting([], confirm=True)  # a look missed (he turned his head)
    now[0] += 0.25
    assert presence.sighting(["Barth"], confirm=True) == ["Barth"]  # known: no new proof asked
    stamp = db.get_kv("presence")
    now[0] += 0.25
    presence.sighting(["Barth"], confirm=True)
    assert db.get_kv("presence") == stamp  # nothing changed: not rewritten at each look
    now[0] += GONE_AFTER_S + 1
    assert presence.snapshot() is None  # no look for a while: never an old picture
    assert presence.sighting([], confirm=True) == []


def test_speaker_note() -> None:
    assert speaker_note(None) == ""
    assert "Barth est devant toi" in speaker_note({"people": ["Barth"], "unknown": 0})
    both = speaker_note({"people": ["Ana", "Barth"], "unknown": 1, "spoof": 1})
    assert "Ana et Barth sont devant toi, avec 1 personne(s)" in both and "photo" in both
    assert "reste discret" in speaker_note({"people": [], "unknown": 2})
    assert "plus loin" in speaker_note({"people": [], "unknown": 0})
    assert speaker_note({"people": ["Barth"]}).endswith("]" + chr(10))


def test_voice_turn_knows_who_is_there(service: AssistantService) -> None:  # noqa: F811
    service.voice_reply("Bonjour")  # no camera: nothing is said of who is there
    assert "Caméra" not in service.cli.calls[-1]["prompt"]  # type: ignore[attr-defined]
    camera = FakeCamera()
    camera.woken = 0  # type: ignore[attr-defined]
    camera.wake = lambda: setattr(camera, "woken", camera.woken + 1)  # type: ignore[attr-defined]
    service.attach_camera(camera)
    service.faces.enroll("Barth", [ME])
    q = service.subscribe()
    service.on_faces([L(ME)], confirm=True)
    service.on_faces([L(ME)], confirm=True)
    service.on_faces([L(ME)], confirm=True)
    seen = [e for e in _drain(q) if e["type"] == "presence"]
    assert [e["people"] for e in seen] == [[], ["Barth"]]  # told of changes, not of each look
    service.set_voice_state("listening")
    assert camera.woken == 1  # someone speaks: the camera looks at full pace
    service.voice_reply("Tu me vois ?")
    prompt = service.cli.calls[-1]["prompt"]  # type: ignore[attr-defined]
    assert "[Caméra, à l'instant : Barth est devant toi]" in prompt
    assert service.history()[-2]["text"] == "Tu me vois ?"  # the note is not the user's words
    assert service.status()["camera_working"] is True

    def unplugged() -> list[dict[str, Any]]:
        raise RuntimeError("la caméra ne donne plus d'image")

    camera.grab = unplugged  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="plus d'image"):
        service.enroll_face("Ana")


def test_liveness_is_judged_over_time() -> None:
    now = [0.0]
    live = Liveness(lambda: now[0])
    assert live.judge("Barth", live=False, sharp=False) == UNSURE  # blurred: no verdict yet
    assert live.judge("Barth", live=True, sharp=False) == UNSURE
    assert live.judge("Barth", live=True) == "Barth"  # one sharp look verifies
    for _ in range(20):  # he moves: blurred looks say "photo", he stays himself
        now[0] += 0.25
        assert live.judge("Barth", live=False, sharp=False) == "Barth"
    for _ in range(SPOOF_LOOKS - 1):  # a few sharp wrong verdicts are not a fraud
        assert live.judge("Barth", live=False) == "Barth"
    assert live.judge("Barth", live=True) == "Barth"
    for _ in range(SPOOF_LOOKS - 1):
        assert live.judge("Barth", live=False) == "Barth"
    assert live.judge("Barth", live=False) == SPOOF  # four sharp looks agree: a photo
    assert live.judge("Barth", live=True, sharp=False) == SPOOF  # until a sharp real look
    assert live.judge("Barth", live=True) == "Barth"
    now[0] += TRUST_S + 1  # he left: on his return he is verified again
    assert live.judge("Barth", live=False, sharp=False) == UNSURE
    assert live.judge(UNKNOWN, live=False, need=1) == SPOOF  # one picture from the phone
    assert "pas encore bien vu" in speaker_note({"people": [], "unknown": 0, "unsure": 1})


def test_service_judges_the_pc_camera_over_several_looks(
    service: AssistantService,  # noqa: F811
) -> None:
    service.faces.enroll("Barth", [ME])
    blurred = {"feature": ME, "live": False, "sharp": False}
    service.on_faces([blurred], confirm=True)
    service.on_faces([blurred], confirm=True)
    assert service.presence.present() == [] and service.presence.snapshot()["unsure"] == 1  # type: ignore[index]
    service.on_faces([L(ME)], confirm=True)
    service.on_faces([L(ME)], confirm=True)
    assert service.presence.present() == ["Barth"]
    service.on_faces([blurred], confirm=True)
    service.on_faces([PHOTO], confirm=True)  # one wrong verdict: still him, nothing logged
    assert service.presence.snapshot()["spoof"] == 0  # type: ignore[index]
    assert not service.db.one("SELECT text FROM events WHERE kind = 'spoof'")
    for _ in range(SPOOF_LOOKS):
        service.on_faces([PHOTO], confirm=True)
    assert service.db.one("SELECT text FROM events WHERE kind = 'spoof'")
    assert service.forget_face("Barth") == 1 and not service.liveness.trusted


def test_phone_and_pc_cameras_keep_their_own_view(service: AssistantService) -> None:  # noqa: F811
    from tests.test_assistant_service import PhoneVoice

    service.faces.enroll("Barth", [ME])
    service.attach_camera(PhoneCamera([L(ME)], [{"feature": ME, "live": False, "sharp": False}]))
    service.attach_voice(PhoneVoice("Bonjour Spectre."))
    pcm = bytes([0, 16]) * 16000
    service.remote_voice(pcm)  # the phone's camera is off: nothing is said of who is there
    assert "Caméra" not in service.cli.calls[-1]["prompt"]  # type: ignore[attr-defined]
    service.on_faces([], confirm=True)  # the PC camera sees nobody
    assert service.remote_frame(b"jpeg")["present"] == ["Barth"]
    assert service.presence.snapshot("pc") == {
        "people": ["Barth"],
        "unknown": 0,
        "spoof": 0,
        "unsure": 0,
    }
    service.remote_voice(pcm)
    prompt = service.cli.calls[-1]["prompt"]  # type: ignore[attr-defined]
    assert "[Caméra du téléphone, à l'instant : Barth est devant toi]" in prompt
    service.remote_frame(b"jpeg")  # a blurred picture (the phone moves): still him, no fraud
    assert service.presence.snapshot("phone")["spoof"] == 0  # type: ignore[index]
    assert "personne devant le téléphone" in speaker_note({"people": []}, phone=True)

    def broken(text: str) -> tuple[bytes, int]:
        raise ImportError("DLL bloquée")

    service.voice.tts.render = broken
    assert service.render_speech("Bonjour") == ""  # shown, not spoken: never an error page
