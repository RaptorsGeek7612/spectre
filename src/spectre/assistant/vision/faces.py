"""Face book and presence: who Spectre knows, who is in front of the screen.

Only embeddings are kept (SFace: 128 numbers per sample), never pictures, and only for people
enrolled on purpose from the UI. Faces that match nobody stay "inconnu" and leave no trace.
Pure Python (no OpenCV), so it is tested without a camera; `camera.py` feeds it.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from spectre.assistant.db import Database, now_iso

# OpenCV's published cosine threshold for SFace ("same person" above it).
MATCH_THRESHOLD: Final = 0.363
UNKNOWN: Final = "inconnu"
AWAY_AFTER_S: Final = 20 * 60  # back after this long away: Spectre greets you
GONE_AFTER_S: Final = 8.0  # not seen for this long: no longer "present" (4 looks a second)
CONFIRM_WITHIN_S: Final = 1.5  # two looks this close must agree before someone is "here"
SAVE_EVERY_S: Final = 2.0  # the presence note for the tools is rewritten at most this often


SPOOF: Final = "fraude"  # a photo or a screen held in front of the camera
UNSURE: Final = "non vérifié"  # a known face, too blurred so far to tell it from a photo
SPOOF_LOOKS: Final = 4  # sharp looks in a row that must say "photo" (the model's own advice)
TRUST_S: Final = 10.0  # seen again within this long, a verified person stays verified


def is_live(real_logit: float, spoof_logit: float, threshold: float = 0.0) -> bool:
    """MiniFASNet verdict: real when the real-vs-spoof logit gap clears `threshold` (p=0.5)."""
    return real_logit - spoof_logit >= threshold


@dataclass
class Liveness:
    """Real person or photo, decided over time instead of on one picture.

    The anti-spoofing model is right on a sharp face and wrong on a blurred one (a head that
    moves), so one look used to turn the owner into a "photo" one time in five. Now: a sharp
    look that says real verifies the person; they stay verified while the camera keeps seeing
    them, whatever blurred looks say; "photo" needs `need` sharp looks in a row. Until a first
    verdict, a face is `UNSURE`: neither present nor a fraud."""

    clock: Callable[[], float]
    trusted: dict[str, float] = field(default_factory=dict)  # name -> last seen while verified
    streak: dict[str, int] = field(default_factory=dict)  # sharp "photo" looks in a row
    caught: set[str] = field(default_factory=set)  # judged a photo, until a sharp real look

    def judge(self, name: str, live: bool, sharp: bool = True, need: int = SPOOF_LOOKS) -> str:
        """`name` as it counts for presence, or `SPOOF`, or `UNSURE`."""
        now = self.clock()
        if sharp and live:
            self.streak[name] = 0
            self.caught.discard(name)
            self.trusted[name] = now
            return name
        if sharp:
            self.streak[name] = self.streak.get(name, 0) + 1
            if self.streak[name] >= need:
                self.caught.add(name)
                self.trusted.pop(name, None)
        if name in self.caught:
            return SPOOF
        if now - self.trusted.get(name, -1e9) <= TRUST_S:
            self.trusted[name] = now
            return name
        return UNSURE


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class FaceBook:
    """Enrolled people (name -> several embeddings) stored in the assistant database."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._known: list[tuple[str, list[float]]] | None = None  # read once: 4 looks a second

    def _samples(self) -> list[tuple[str, list[float]]]:
        if self._known is None:
            self._known = [
                (row["name"], json.loads(row["feature"]))
                for row in self.db.all("SELECT name, feature FROM faces")
            ]
        return self._known

    def enroll(self, name: str, features: Sequence[Sequence[float]]) -> int:
        name = name.strip()
        if not name:
            raise ValueError("donne un prénom pour ce visage")
        if not features:
            raise ValueError("aucun visage net : regarde la caméra, bien éclairé, et réessaie")
        stamp = now_iso()
        for feature in features:
            self.db.execute(
                "INSERT INTO faces(name, feature, created_at) VALUES(?, ?, ?)",
                (name, json.dumps([round(float(v), 6) for v in feature]), stamp),
            )
        self._known = None
        return len(features)

    def people(self) -> list[dict[str, Any]]:
        return self.db.all(
            "SELECT name, COUNT(*) AS samples, MIN(created_at) AS since FROM faces "
            "GROUP BY name ORDER BY name"
        )

    def forget(self, name: str) -> int:
        """Delete every embedding of `name`; return how many were removed."""
        count = self.db.one("SELECT COUNT(*) AS n FROM faces WHERE name = ?", (name,))
        if not count or not count["n"]:
            raise KeyError(name)
        self.db.execute("DELETE FROM faces WHERE name = ?", (name,))
        self._known = None
        return int(count["n"])

    def identify(self, feature: Sequence[float]) -> tuple[str, float]:
        """Best enrolled match, or (`inconnu`, best score) below the threshold."""
        best_name, best = UNKNOWN, 0.0
        for name, sample in self._samples():
            score = cosine(feature, sample)
            if score > best:
                best_name, best = name, score
        return (best_name, best) if best >= MATCH_THRESHOLD else (UNKNOWN, best)


@dataclass
class Presence:
    """Turns camera sightings into presence: who is here, and when someone comes back."""

    db: Database
    on_arrival: Callable[[str, float], None]  # (name, seconds away) when back after a while
    clock: Callable[[], float]
    last_seen: dict[str, float] = field(default_factory=dict)
    glimpsed: dict[str, float] = field(default_factory=dict)  # seen once, not yet confirmed
    # what each camera ("pc", "phone") saw at its last look: (when, unknown, photos, unsure)
    views: dict[str, tuple[float, int, int, int]] = field(default_factory=dict)
    _saved: dict[str, Any] = field(default_factory=dict)
    _saved_at: float = -1e9

    def sighting(
        self, names: Sequence[str], confirm: bool = False, source: str = "pc"
    ) -> list[str]:
        """Record who a camera (`source`: the PC's or the phone's) sees now; return the people
        currently present, whichever camera saw them.

        With `confirm` (the PC camera, several looks a second), a name counts once two looks
        in a row agree: one blurred picture taken for someone else greets nobody."""
        now = self.clock()
        seen = set(names) - {UNKNOWN, SPOOF, UNSURE}
        if confirm:
            fresh = {n for n in seen if now - self.glimpsed.get(n, -1e9) <= CONFIRM_WITHIN_S}
            self.glimpsed = dict.fromkeys(seen, now)
            seen = {n for n in seen if n in fresh or now - self.last_seen.get(n, -1e9) <= 60}
        for name in seen:
            previous = self.last_seen.get(name)
            if previous is None or now - previous >= AWAY_AFTER_S:
                self.on_arrival(name, now - previous if previous is not None else 0.0)
            self.last_seen[name] = now
        present = self.present(now)
        unknown, spoof = names.count(UNKNOWN), names.count(SPOOF)
        self.views[source] = (now, unknown, spoof, names.count(UNSURE))
        note = {"people": present, "unknown": unknown, "spoof": spoof}
        if note != self._saved or now - self._saved_at >= SAVE_EVERY_S:
            self._saved, self._saved_at = note, now
            stamp = datetime.now().astimezone().isoformat(timespec="seconds")
            self.db.set_kv("presence", json.dumps({"at": stamp, **note}))
        return present

    def snapshot(self, source: str = "pc", fresh_s: float = 3.0) -> dict[str, Any] | None:
        """Who is in front of that camera at this very moment, or None when it has not looked
        for `fresh_s` (off, covered, taken by another program): never an old picture."""
        now = self.clock()
        at, unknown, spoof, unsure = self.views.get(source, (-1e9, 0, 0, 0))
        if now - at > fresh_s:
            return None
        return {"people": self.present(now), "unknown": unknown, "spoof": spoof, "unsure": unsure}

    def present(self, now: float | None = None) -> list[str]:
        moment = self.clock() if now is None else now
        return sorted(n for n, seen in self.last_seen.items() if moment - seen <= GONE_AFTER_S)


def speaker_note(seen: dict[str, Any] | None, phone: bool = False) -> str:
    """What the brain is told with spoken words: who the camera of the device spoken to (the
    PC, or the phone) sees at that very moment, so Spectre knows who it is talking to. Empty
    when that camera is not looking."""
    if seen is None:
        return ""
    people, unknown = list(seen.get("people", [])), int(seen.get("unknown", 0))
    if people:
        who = " et ".join(people) + (" est" if len(people) == 1 else " sont") + " devant toi"
        if unknown:
            who += f", avec {unknown} personne(s) que tu ne connais pas"
    elif unknown:
        who = (
            f"{unknown} personne(s) que tu ne connais pas devant toi, aucun visage connu : "
            "reste discret sur ce qui est personnel"
        )
    elif seen.get("unsure"):
        who = "quelqu'un devant toi que tu n'as pas encore bien vu (il bouge ou l'image est floue)"
    else:
        who = (
            "personne devant le téléphone"
            if phone
            else "personne devant l'écran, la voix vient de plus loin dans la pièce"
        )
    if seen.get("spoof"):
        who += " ; une photo ou un écran est présenté à la caméra"
    return f"[Caméra{' du téléphone' if phone else ''}, à l'instant : {who}]\n"


def describe_presence(db: Database) -> str:
    """What the MCP tool `who_is_there` answers (it runs in another process: read the kv)."""
    raw = db.get_kv("presence")
    if not raw:
        return "la caméra n'est pas active : je ne vois personne"
    data = json.loads(raw)
    people, unknown = data.get("people", []), int(data.get("unknown", 0))
    parts = [", ".join(people)] if people else []
    if unknown:
        parts.append(f"{unknown} personne(s) que je ne connais pas")
    if data.get("spoof"):
        parts.append(f"{data['spoof']} photo(s) ou écran(s) présenté(s) à la caméra")
    seen = data.get("at", "")[11:16]
    return f"devant l'écran à {seen} : " + (" et ".join(parts) if parts else "personne")
