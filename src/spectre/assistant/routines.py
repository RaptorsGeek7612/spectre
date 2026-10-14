"""Routines: what Spectre does on a schedule (Hermes-style cron jobs, in plain French).

A routine has a schedule, a kind and a text:
- `rappel`: the text comes back as a notification, with no model call;
- `question`: the brain answers it with its tools, and the answer comes back as a notification;
- `mission`: a mission is queued (with an agent and a company's brief if given).

Schedules are typed in plain words and stored in a canonical form:
`every:<seconds>`, `once:<ISO time>` or `cron:<min> <hour> <day> <month> <weekday>`.
After an outage, a routine that was due runs once (no burst of catch-up runs).
"""

from __future__ import annotations

import re
import threading
import unicodedata
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from spectre.assistant.db import Database, now_iso

KINDS = ("mission", "question", "rappel")
MAX_ROUTINES = 50
MIN_EVERY_S = 300  # at most every 5 minutes: a routine costs model calls
FAILURE_ALERT = 3
WEEKDAYS = {
    "lundi": 1,
    "mardi": 2,
    "mercredi": 3,
    "jeudi": 4,
    "vendredi": 5,
    "samedi": 6,
    "dimanche": 0,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
    "sunday": 0,
}
DAY_NAMES = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"]

QUESTION = """\
Tu es Spectre et tu exécutes une routine programmée par l'utilisateur, sans lui en direct. \
Fais ce qu'elle demande avec tes outils, puis rends un compte rendu bref et utile (quelques \
phrases), qui lui sera envoyé en notification. Aucune action externe (envoyer, publier, payer) \
sans sa validation."""

Notify = Callable[..., Any]  # add_initiative(kind, title, body)
Ask = Callable[[str, str], Any]  # (prompt, system) -> Reply


class RoutineError(ValueError):
    """A refused routine (the message is for the user)."""


def plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


# ---- schedules ---------------------------------------------------------------------------------

CRON_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def cron_field(text: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in text.split(","):
        body, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if body == "*":
            start, end = low, high
        elif "-" in body:
            a, b = body.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(body)
            if step_text:
                end = high
        if not (low <= start <= end <= high) or step < 1:
            raise RoutineError(f"valeur hors limites dans « {text} » ({low}-{high})")
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expr: str) -> tuple[set[int], ...]:
    parts = expr.split()
    if len(parts) != 5:
        raise RoutineError("une expression cron a 5 champs : minute heure jour mois jour-semaine")
    try:
        fields = tuple(
            cron_field(p, lo, hi) for p, (lo, hi) in zip(parts, CRON_RANGES, strict=True)
        )
    except ValueError as exc:
        raise RoutineError(f"expression cron invalide « {expr} » : {exc}") from exc
    weekdays = {0 if d == 7 else d for d in fields[4]}
    return (*fields[:4], weekdays)


def cron_next(expr: str, after: datetime) -> datetime:
    """The first matching minute strictly after `after` (local, aware)."""
    minutes, hours, days, months, weekdays = parse_cron(expr)
    parts = expr.split()
    day_any, weekday_any = parts[2] == "*", parts[4] == "*"
    start = after.replace(second=0, microsecond=0)
    for offset in range(0, 366 * 5):
        day = (start + timedelta(days=offset)).date()
        if day.month not in months:
            continue
        in_month, in_week = day.day in days, (day.isoweekday() % 7) in weekdays
        if day_any and weekday_any:
            ok = True
        elif day_any:
            ok = in_week
        elif weekday_any:
            ok = in_month
        else:
            ok = in_month or in_week  # cron: either one when both are restricted
        if not ok:
            continue
        for hour in sorted(hours):
            for minute in sorted(minutes):
                moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=after.tzinfo)
                if moment > after:
                    return moment
    raise RoutineError(f"aucune date ne correspond à « {expr} »")


def _time(text: str) -> tuple[int, int]:
    """ "9h", "9h30", "09:30", "18 h 05", "9" -> (hour, minute)."""
    found = re.search(r"(\d{1,2})\s*(?:h|:|heures?)?\s*(\d{2})?", text)
    if not found:
        raise RoutineError(f"heure illisible dans « {text} »")
    hour, minute = int(found[1]), int(found[2] or 0)
    if hour > 23 or minute > 59:
        raise RoutineError(f"heure invalide « {text} »")
    return hour, minute


def parse_schedule(spec: str, now: datetime | None = None) -> str:
    """Plain words -> canonical schedule. Raises RoutineError when it cannot be read."""
    now = now or datetime.now().astimezone()
    text = plain(spec)
    text = re.sub(r"\s+", " ", text.replace("à", "a")).strip()
    if not text:
        raise RoutineError("horaire vide")
    if re.fullmatch(r"[\d*,/\- ]+", text) and len(text.split()) == 5:
        parse_cron(text)
        return f"cron:{text}"
    found = re.fullmatch(
        r"(?:toutes les|tous les|every|chaque) ?(\d+)? ?(minutes?|min|heures?|h|hours?)", text
    )
    if found:
        count = int(found[1] or 1)
        unit = 60 if found[2].startswith("min") else 3600
        seconds = count * unit
        if seconds < MIN_EVERY_S:
            raise RoutineError("au plus toutes les 5 minutes")
        return f"every:{seconds}"
    found = re.fullmatch(r"(?:dans|in) (\d+) ?(minutes?|min|heures?|h|hours?|jours?|days?)", text)
    if found:
        count = int(found[1])
        unit = {"m": 60, "h": 3600, "j": 86400, "d": 86400}[found[2][0]]
        return f"once:{(now + timedelta(seconds=count * unit)).replace(microsecond=0).isoformat()}"
    found = re.fullmatch(r"(?:le )?(\d{4}-\d{2}-\d{2})(?:[ t]?a? ?(.+))?", text)
    if found:
        hour, minute = _time(found[2]) if found[2] else (9, 0)
        day = date.fromisoformat(found[1])
        moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=now.tzinfo)
        if moment <= now:
            raise RoutineError("cette date est déjà passée")
        return f"once:{moment.isoformat()}"
    at = re.search(r"(?: a | at |^a |^at )(.+)$", f" {text}")
    clock = text if at is None else at[1]
    head = text if at is None else f" {text}"[: at.start()].strip()
    if re.search(r"(tous les jours|chaque jour|every day|daily|quotidien)", head) or (
        at is None and re.fullmatch(r"\d{1,2} ?(h|:)? ?\d{0,2}", text)
    ):
        hour, minute = _time(clock)
        return f"cron:{minute} {hour} * * *"
    if re.search(r"(en semaine|weekdays?|jours ouvres|du lundi au vendredi)", head):
        hour, minute = _time(clock)
        return f"cron:{minute} {hour} * * 1-5"
    if re.search(r"(le week-?end|weekends?)", head):
        hour, minute = _time(clock)
        return f"cron:{minute} {hour} * * 0,6"
    days = [WEEKDAYS[w] for w in re.findall(r"[a-z]+", head) if w in WEEKDAYS]
    if days and at is not None:
        hour, minute = _time(clock)
        return f"cron:{minute} {hour} * * {','.join(str(d) for d in sorted(set(days)))}"
    found = re.search(r"le (\d{1,2})(?:er)? (?:de )?(?:chaque|du|of every) mois|monthly", head)
    if found is None:
        found = re.search(r"chaque mois le (\d{1,2})", head)
    if found and at is not None:
        day_of_month = int(found[1]) if found.groups() and found[1] else 1
        if not 1 <= day_of_month <= 28:
            raise RoutineError("jour du mois : de 1 à 28")
        hour, minute = _time(clock)
        return f"cron:{minute} {hour} {day_of_month} * *"
    raise RoutineError(
        f"horaire illisible « {spec} » ; par exemple : « tous les jours à 9h », « chaque lundi "
        "à 9h », « en semaine à 8h30 », « toutes les 2 heures », « dans 30 minutes », "
        "« 2026-11-02 à 14h » ou une expression cron « 0 9 * * 1 »"
    )


def next_run(schedule: str, after: datetime) -> datetime | None:
    kind, _, value = schedule.partition(":")
    if kind == "every":
        return after + timedelta(seconds=int(value))
    if kind == "once":
        moment = datetime.fromisoformat(value)
        return moment if moment > after else None
    return cron_next(value, after)


def describe(schedule: str) -> str:
    """The canonical schedule in plain French."""
    kind, _, value = schedule.partition(":")
    if kind == "every":
        seconds = int(value)
        if seconds % 3600 == 0:
            hours = seconds // 3600
            return "toutes les heures" if hours == 1 else f"toutes les {hours} heures"
        return f"toutes les {seconds // 60} minutes"
    if kind == "once":
        moment = datetime.fromisoformat(value)
        return f"une fois, le {moment:%d/%m/%Y à %H:%M}"
    minute, hour, day, month, weekday = value.split()
    if not (minute.isdigit() and hour.isdigit()) or month != "*":
        return f"cron {value}"
    clock = f"{int(hour)}h{int(minute):02d}" if int(minute) else f"{int(hour)}h"
    if day == "*" and weekday == "*":
        return f"tous les jours à {clock}"
    if day == "*" and weekday == "1-5":
        return f"en semaine à {clock}"
    if day == "*" and re.fullmatch(r"[0-6](,[0-6])*", weekday):
        names = [DAY_NAMES[int(d)] for d in weekday.split(",")]
        return f"chaque {' et '.join(names)} à {clock}"
    if day.isdigit() and weekday == "*":
        return f"le {day} de chaque mois à {clock}"
    return f"cron {value}"


# ---- storage and running -------------------------------------------------------------------------


class Routines:
    """The routines table, and running the ones that are due."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT * FROM routines ORDER BY id")
        for row in rows:
            row["when"] = describe(row["schedule"])
        return rows

    def get(self, value: int | str) -> dict[str, Any]:
        text = str(value).strip().removeprefix("#")
        row = (
            self.db.one("SELECT * FROM routines WHERE id = ?", (int(text),))
            if text.isdigit()
            else next((r for r in self.all() if plain(r["name"]) == plain(text)), None)
        )
        if row is None:
            raise RoutineError(f"routine « {value} » introuvable")
        row["when"] = describe(row["schedule"])
        return row

    def create(
        self,
        name: str,
        schedule: str,
        prompt: str,
        *,
        kind: str = "mission",
        agent: str = "",
        company_id: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or datetime.now().astimezone()
        name, prompt, kind = name.strip(), prompt.strip(), plain(kind) or "mission"
        if not 2 <= len(name) <= 60:
            raise RoutineError("le nom d'une routine doit faire de 2 à 60 caractères")
        if kind not in KINDS:
            raise RoutineError(f"type « {kind} » : au choix {', '.join(KINDS)}")
        if not 3 <= len(prompt) <= 4000:
            raise RoutineError("décris ce que la routine doit faire (3 à 4000 caractères)")
        if any(plain(r["name"]) == plain(name) for r in self.all()):
            raise RoutineError(f"une routine s'appelle déjà « {name} »")
        if len(self.all()) >= MAX_ROUTINES:
            raise RoutineError(f"{MAX_ROUTINES} routines au maximum")
        canonical = parse_schedule(schedule, now)
        upcoming = next_run(canonical, now)
        rid = self.db.execute(
            "INSERT INTO routines(name, spec, schedule, kind, prompt, agent, company_id, "
            "next_run, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                schedule.strip()[:200],
                canonical,
                kind,
                prompt,
                agent.strip(),
                company_id,
                upcoming.isoformat() if upcoming else None,
                now_iso(),
            ),
        )
        return self.get(rid)

    def update(
        self,
        value: int | str,
        *,
        enabled: bool | None = None,
        schedule: str = "",
        prompt: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or datetime.now().astimezone()
        row = self.get(value)
        fields: dict[str, Any] = {}
        if schedule.strip():
            fields["schedule"] = parse_schedule(schedule, now)
            fields["spec"] = schedule.strip()[:200]
        if prompt.strip():
            fields["prompt"] = prompt.strip()[:4000]
        if enabled is not None:
            fields["enabled"] = int(enabled)
            if enabled:
                fields["failures"] = 0
        if "schedule" in fields or enabled:
            upcoming = next_run(fields.get("schedule", row["schedule"]), now)
            if upcoming is None:
                raise RoutineError("cette routine unique est déjà passée : donne un autre horaire")
            fields["next_run"] = upcoming.isoformat()
        if fields:
            sets = ", ".join(f"{key} = ?" for key in fields)
            self.db.execute(
                f"UPDATE routines SET {sets} WHERE id = ?",  # noqa: S608 - fixed keys
                (*fields.values(), row["id"]),
            )
        return self.get(row["id"])

    def delete(self, value: int | str) -> dict[str, Any]:
        row = self.get(value)
        self.db.execute("DELETE FROM routines WHERE id = ?", (row["id"],))
        return row

    def due(self, now: datetime) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT * FROM routines WHERE enabled = 1 AND next_run IS NOT NULL ORDER BY id"
        )
        return [r for r in rows if datetime.fromisoformat(r["next_run"]) <= now]

    def tick(
        self, now: datetime, notify: Notify, ask: Ask, *, background: bool = True
    ) -> list[int]:
        """Run every due routine once, then plan its next run; returns the routines run."""
        ran = []
        for row in self.due(now):
            upcoming = next_run(row["schedule"], now)
            self.db.execute(
                "UPDATE routines SET last_run = ?, next_run = ?, enabled = ? WHERE id = ?",
                (
                    now.isoformat(),
                    upcoming.isoformat() if upcoming else None,
                    int(upcoming is not None),
                    row["id"],
                ),
            )
            ran.append(row["id"])
            self.run(row, notify, ask, background=background)
        return ran

    def run(
        self, row: dict[str, Any], notify: Notify, ask: Ask, *, background: bool = True
    ) -> None:
        if row["kind"] == "rappel":
            notify("routine", row["name"], row["prompt"])
            self._done(row["id"], "rappel envoyé")
        elif row["kind"] == "mission":
            mid = self.queue_mission(row)
            self._done(row["id"], f"mission #{mid}")
        elif background:  # pragma: no cover - thread wrapper around answer
            threading.Thread(
                target=self.answer, args=(row, notify, ask), name="spectre-routine", daemon=True
            ).start()
        else:
            self.answer(row, notify, ask)

    def queue_mission(self, row: dict[str, Any]) -> int:
        from spectre.assistant.company import Companies, enqueue

        plan: dict[str, Any] = {"kind": "mission", "routine": row["id"]}
        if row["agent"]:
            plan["agent"] = Companies(self.db).agent_key(row["agent"])
        if row["company_id"]:
            companies = Companies(self.db)
            plan["brief"] = companies.brief(companies.get(row["company_id"]), "")
        return enqueue(self.db, row["prompt"], plan)

    def answer(self, row: dict[str, Any], notify: Notify, ask: Ask) -> None:
        from spectre.assistant.brain import failed

        try:
            reply = ask(row["prompt"], QUESTION)
            bad = failed(reply)
            text = reply.text
        except Exception as exc:  # noqa: BLE001 - a routine must never kill the loop
            bad, text = True, str(exc)
        if not bad:
            notify("routine", row["name"], text)
            self._done(row["id"], "réponse envoyée")
            return
        failures = self._fail(row["id"], text)
        body = f"Échec : {text[:300]}"
        if failures >= FAILURE_ALERT:
            body += f" ({failures} échecs d'affilée : vérifie-la, ou mets-la en pause.)"
        notify("routine", f"Routine « {row['name']} » en échec", body)

    def _done(self, routine_id: int, status: str) -> None:
        self.db.execute(
            "UPDATE routines SET last_status = ?, failures = 0 WHERE id = ?", (status, routine_id)
        )

    def _fail(self, routine_id: int, reason: str) -> int:
        self.db.execute(
            "UPDATE routines SET last_status = ?, failures = failures + 1 WHERE id = ?",
            (f"échec : {reason[:200]}", routine_id),
        )
        row = self.db.one("SELECT failures FROM routines WHERE id = ?", (routine_id,))
        return int(row["failures"]) if row else 0
