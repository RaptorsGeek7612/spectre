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
GONE_AFTER_S: Final = 30.0  # not seen for this long: no longer "present"


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class FaceBook:
    """Enrolled people (name -> several embeddings) stored in the assistant database."""

    def __init__(self, db: Database) -> None:
        self.db = db

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
        return int(count["n"])

    def identify(self, feature: Sequence[float]) -> tuple[str, float]:
        """Best enrolled match, or (`inconnu`, best score) below the threshold."""
        best_name, best = UNKNOWN, 0.0
        for row in self.db.all("SELECT name, feature FROM faces"):
            score = cosine(feature, json.loads(row["feature"]))
            if score > best:
                best_name, best = row["name"], score
        return (best_name, best) if best >= MATCH_THRESHOLD else (UNKNOWN, best)


@dataclass
class Presence:
    """Turns camera sightings into presence: who is here, and when someone comes back."""

    db: Database
    on_arrival: Callable[[str, float], None]  # (name, seconds away) when back after a while
    clock: Callable[[], float]
    last_seen: dict[str, float] = field(default_factory=dict)

    def sighting(self, names: Sequence[str]) -> list[str]:
        """Record who the camera sees now; return the people currently present."""
        now = self.clock()
        for name in set(names) - {UNKNOWN}:
            previous = self.last_seen.get(name)
            if previous is None or now - previous >= AWAY_AFTER_S:
                self.on_arrival(name, now - previous if previous is not None else 0.0)
            self.last_seen[name] = now
        present = self.present(now)
        self.db.set_kv(
            "presence",
            json.dumps(
                {
                    "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "people": present,
                    "unknown": names.count(UNKNOWN),
                }
            ),
        )
        return present

    def present(self, now: float | None = None) -> list[str]:
        moment = self.clock() if now is None else now
        return sorted(n for n, seen in self.last_seen.items() if moment - seen <= GONE_AFTER_S)


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
    seen = data.get("at", "")[11:16]
    return f"devant l'écran à {seen} : " + (" et ".join(parts) if parts else "personne")
