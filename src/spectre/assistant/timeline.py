"""Spectre's sense of time: the clock, the previous visit and what happened since.

The model never guesses the date: every system prompt gets it from here, read from the
system clock in the user's IANA time zone. Storage stays in UTC (`db.now_iso`); only what is
shown is converted.

A "visit" is a run of user utterances (voice, text or image, one conversation) with no gap
longer than `VISIT_GAP`. On a new visit Spectre is told when the previous one ended, how long
ago that was, and the state of its missions: still running, interrupted by a restart, finished
or failed while the user was away, plus what is scheduled next.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from spectre.assistant.db import Database

DEFAULT_ZONE: Final = "Europe/Paris"
VISIT_GAP: Final = timedelta(minutes=30)
DAYS: Final = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS: Final = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
_LOOKBACK: Final = 2000  # utterances read back to find where the current visit started
_LIST: Final = 5  # missions shown per state


def zone(name: str) -> tzinfo:
    """The IANA zone `name`; the system's local zone when empty or unknown."""
    if name.strip():
        try:
            return ZoneInfo(name.strip())
        except (ZoneInfoNotFoundError, ValueError):
            pass
    local = datetime.now().astimezone().tzinfo
    return local if local is not None else UTC


def now(zone_name: str = DEFAULT_ZONE) -> datetime:
    """The system clock, aware, in the user's zone."""
    return datetime.now(UTC).astimezone(zone(zone_name))


def parse(stamp: str, tz: tzinfo) -> datetime | None:
    """A stored ISO stamp (UTC, or naive = UTC) shown in `tz`; None when unreadable."""
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(tz)


def spoken_date(moment: datetime) -> str:
    """« mercredi 4 novembre 2026 à 10:00 »."""
    first = "1er" if moment.day == 1 else str(moment.day)
    return (
        f"{DAYS[moment.weekday()]} {first} {MONTHS[moment.month - 1]} {moment.year} "
        f"à {moment:%H:%M}"
    )


def elapsed(delta: timedelta) -> str:
    """A duration in words, two units at most: « 2 jours et 3 heures », « 5 minutes »."""
    seconds = max(0, int(delta.total_seconds()))
    units = (("jour", 86_400), ("heure", 3_600), ("minute", 60))
    parts: list[str] = []
    for word, size in units:
        count, seconds = divmod(seconds, size)
        if count and len(parts) < 2:
            parts.append(f"{count} {word}{'s' if count > 1 else ''}")
        elif parts:
            break  # never « 2 jours et 4 minutes »: units stay adjacent
    return " et ".join(parts) if parts else "moins d'une minute"


@dataclass(frozen=True)
class Visit:
    started: datetime  # first utterance of the current visit (or now when none yet)
    previous: datetime | None  # last utterance of the visit before, if any

    @property
    def gap(self) -> timedelta | None:
        return self.started - self.previous if self.previous else None


def visit(db: Database, at: datetime) -> Visit:
    """Where the current visit started and when the previous one ended."""
    rows = db.all(
        "SELECT ts FROM events WHERE kind = 'utterance' AND source = 'user' AND ts <= ? "
        "ORDER BY ts DESC LIMIT ?",
        (at.astimezone(UTC).isoformat(timespec="seconds"), _LOOKBACK),
    )
    stamps = [m for m in (parse(r["ts"], at.tzinfo or UTC) for r in rows) if m is not None]
    if not stamps:
        return Visit(at, None)
    if at - stamps[0] > VISIT_GAP:  # nothing said in this visit yet
        return Visit(at, stamps[0])
    started = stamps[0]
    for stamp in stamps[1:]:
        if started - stamp > VISIT_GAP:
            return Visit(started, stamp)
        started = stamp
    return Visit(started, None)


def _missions(db: Database, since: datetime | None, tz: tzinfo) -> list[str]:
    lines: list[str] = []
    active = db.all(
        "SELECT id, goal, status FROM missions WHERE status IN ('queued', 'running') "
        "ORDER BY id LIMIT ?",
        (_LIST,),
    )
    interrupted = {
        int(r["mission"])
        for r in db.all(
            "SELECT json_extract(data, '$.mission') AS mission FROM events "
            "WHERE kind = 'mission_interrupted'"
        )
        if r["mission"] is not None
    }
    for row in active:
        state = "en cours" if row["status"] == "running" else "en file"
        if row["id"] in interrupted:
            state = "interrompue par un redémarrage, reprise là où elle s'était arrêtée"
        lines.append(f"#{row['id']} {state} : {str(row['goal'])[:120]}")
    if since is None:
        return lines
    stamp = since.astimezone(UTC).isoformat(timespec="seconds")
    for status, label in (("done", "terminée"), ("failed", "échouée"), ("cancelled", "annulée")):
        for row in db.all(
            "SELECT id, goal, ts, updated_at, error FROM missions WHERE status = ? "
            "AND updated_at > ? ORDER BY updated_at DESC LIMIT ?",
            (status, stamp, _LIST),
        ):
            began, ended = parse(row["ts"], tz), parse(row["updated_at"], tz)
            took = f", durée {elapsed(ended - began)}" if began and ended else ""
            why = f", erreur : {str(row['error'])[:160]}" if status == "failed" else ""
            lines.append(f"#{row['id']} {label}{took}{why} : {str(row['goal'])[:120]}")
    return lines


def _scheduled(db: Database, tz: tzinfo) -> list[str]:
    lines = []
    for row in db.all(
        "SELECT name, next_run FROM routines WHERE enabled = 1 AND next_run IS NOT NULL "
        "ORDER BY next_run LIMIT 3"
    ):
        when = parse(row["next_run"], tz)
        if when:
            lines.append(f"routine « {row['name']} » le {spoken_date(when)}")
    return lines


def block(db: Database, zone_name: str = DEFAULT_ZONE, at: datetime | None = None) -> str:
    """The time section of the system prompt."""
    tz = zone(zone_name)
    moment = (at or now(zone_name)).astimezone(tz)
    offset = moment.strftime("%z")
    label = getattr(tz, "key", "") or moment.tzname() or "local"
    lines = [
        f"Maintenant (horloge du système, fuseau {label}, UTC{offset[:3]}:{offset[3:]}) : "
        f"{spoken_date(moment)}. Ne devine jamais la date ni l'heure : prends celles-ci, et "
        "pour une durée, calcule-la à partir des horodatages donnés ici."
    ]
    current = visit(db, moment)
    if current.previous is None:
        lines.append("Aucune conversation précédente enregistrée avec l'utilisateur.")
    elif current.gap is not None:
        lines.append(
            f"Conversation en cours depuis {spoken_date(current.started)}. La précédente "
            f"s'est terminée le {spoken_date(current.previous)}, soit {elapsed(current.gap)} "
            "plus tôt. Au premier échange de cette visite, tu peux le situer simplement "
            "(sans réciter les heures) et reprendre ce qui restait en suspens."
        )
    missions = _missions(db, current.previous, tz)
    if missions:
        lines.append("État des missions :\n" + "\n".join(f"- {m}" for m in missions))
    scheduled = _scheduled(db, tz)
    if scheduled:
        lines.append("Programmé : " + " ; ".join(scheduled) + ".")
    return "\n".join(lines)


def turn_note(db: Database, zone_name: str = DEFAULT_ZONE, at: datetime | None = None) -> str:
    """What goes in front of the user's message: the clock on every turn (a resumed brain
    session keeps the system prompt of its first turn, so the hour there grows stale), and the
    whole time section on the first message of a new visit."""
    moment = (at or now(zone_name)).astimezone(zone(zone_name))
    current = visit(db, moment)
    if current.previous is not None and moment - current.started < timedelta(minutes=1):
        return f"[{block(db, zone_name, moment)}]\n"
    return f"[Horloge : {spoken_date(moment)}]\n"
