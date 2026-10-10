"""Proactivity: reminders when due, a morning briefing, a nightly memory consolidation, and a
few times a day Spectre coming to talk to the user on its own, to get to know them better.

Everything Spectre initiates becomes an *initiative* (a row the UI shows and the voice can read
out). Nothing here acts on the outside world: initiatives inform or propose; actions still go
through the governance gate when the user follows up.
"""

from __future__ import annotations

import json
import random
import threading
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from spectre.assistant import greetings
from spectre.assistant.brain import ClaudeCLI, extract_json, one_shot
from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database, now_iso
from spectre.assistant.memory import CATEGORIES, Memory

Notify = Callable[[str, str, str], object]
Fetch = Callable[[str], Any]

WEATHER_CODES = {
    0: "ciel dégagé",
    1: "plutôt dégagé",
    2: "partiellement nuageux",
    3: "couvert",
    45: "brouillard",
    48: "brouillard givrant",
    51: "bruine légère",
    53: "bruine",
    55: "bruine forte",
    61: "pluie faible",
    63: "pluie",
    65: "forte pluie",
    71: "neige faible",
    73: "neige",
    75: "forte neige",
    80: "averses",
    81: "averses",
    82: "fortes averses",
    95: "orage",
    96: "orage et grêle",
    99: "orage violent et grêle",
}

CONSOLIDATOR = """\
Tu relis les échanges d'une journée entre un utilisateur et son assistant Spectre, et tu en \
extrais les faits DURABLES sur l'utilisateur (préférences, habitudes, projets, objectifs, \
proches, lieux, événements datés, façon dont il aime qu'on lui parle). Ignore le small talk et \
ce qui est déjà connu. Réponds UNIQUEMENT par un objet JSON :
{"facts": [{"subject": "...", "predicate": "...", "value": "...", "category": "...", \
"confidence": 0.0-1.0}]}
Catégories autorisées : """ + ", ".join(CATEGORIES)


BEFRIEND = """\
Tu es Spectre, l'IA personnelle de l'utilisateur, et tu viens de toi-même lui parler, comme un \
ami qui veut mieux le connaître. Écris UNE seule réplique, courte (une ou deux phrases), \
naturelle et chaleureuse, à dire à voix haute : soit une question sincère et précise sur un \
sujet que tu connais mal de lui (ses goûts, son histoire, ses projets, ses proches, ce qui le \
rend heureux), soit une suite à quelque chose qu'il t'a confié (« Alors, ce concert ? »). \
Tu peux partager en une phrase ce qui t'intéresse toi, pour donner envie de répondre. Jamais \
d'interrogatoire, rien d'intrusif (santé, argent, intimité) s'il ne l'a pas abordé lui-même, \
pas de flatterie, pas de culpabilisation. Tiens compte du moment de la journée. Évite de \
répéter tes dernières questions. Pas de Markdown ni d'emoji.
Réponds UNIQUEMENT par un objet JSON : \
{"text": "ta réplique", "topic": "le sujet en 2 ou 3 mots"}"""
BEFRIEND_GAP_S = 3 * 3600  # at least 3 hours between two visits
BEFRIEND_IGNORED_GAP_S = 6 * 3600  # 6 when the last one got no answer
BEFRIEND_QUIET_S = 20 * 60  # never right after a conversation (the user is busy with it)
BEFRIEND_CHANCE = 1 / 40  # per 30 s tick once allowed: about 20 minutes on average, unpredictable


def parse_hours(value: str) -> tuple[int, int]:
    """ "10-21" -> (10, 21); a broken value falls back to the default window."""
    try:
        start, end = (int(part) for part in value.split("-", 1))
    except ValueError:
        return 10, 21
    return (start, end) if 0 <= start < end <= 24 else (10, 21)


def fetch_json(url: str) -> Any:  # pragma: no cover - real network
    with urllib.request.urlopen(url, timeout=15) as response:  # noqa: S310 - fixed https hosts
        return json.loads(response.read().decode("utf-8"))


def weather_summary(city: str, fetch: Fetch = fetch_json) -> str:
    """Today's weather for `city` from Open-Meteo (no API key)."""
    geo = fetch(
        "https://geocoding-api.open-meteo.com/v1/search?count=1&language=fr&name="
        + urllib.parse.quote(city)
    )
    places = geo.get("results") or []
    if not places:
        return f"météo indisponible : ville « {city} » introuvable"
    place = places[0]
    data = fetch(
        "https://api.open-meteo.com/v1/forecast?timezone=auto&forecast_days=1"
        f"&latitude={place['latitude']}&longitude={place['longitude']}"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    )
    daily = data["daily"]
    sky = WEATHER_CODES.get(int(daily["weather_code"][0]), "temps variable")
    return (
        f"{place['name']} : {sky}, {round(daily['temperature_2m_min'][0])} à "
        f"{round(daily['temperature_2m_max'][0])} °C, risque de pluie "
        f"{daily['precipitation_probability_max'][0]} %"
    )


class Proactive:
    """Checks every `tick` seconds what Spectre should bring up on its own."""

    def __init__(
        self,
        db: Database,
        cli: ClaudeCLI,
        config: AssistantConfig,
        notify: Notify,
        *,
        fetch: Fetch = fetch_json,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        rand: Callable[[], float] = random.random,
        is_free: Callable[[], bool] = lambda: True,
    ) -> None:
        self.db = db
        self.cli = cli
        self.config = config
        self.notify = notify
        self.fetch = fetch
        self.clock = clock
        self.rand = rand
        self.is_free = is_free  # not talking, not thinking: a good moment to come over
        self._stop = threading.Event()

    def start(self, tick: float = 30.0) -> None:  # pragma: no cover - thread wrapper
        def loop() -> None:
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(tick)

        threading.Thread(target=loop, name="spectre-proactive", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def tick(self) -> None:
        now = self.clock()
        self.due_reminders(now)
        if now.hour >= self.config.briefing_hour and self._once_per_day("briefing", now):
            self.briefing(now)
        if now.hour == self.config.consolidation_hour and self._once_per_day("consolidation", now):
            self.consolidate(now)
        if self.befriend_due(now):
            self.befriend(now)

    def _once_per_day(self, key: str, now: datetime) -> bool:
        day = now.strftime("%Y-%m-%d")
        if self.db.get_kv(f"last_{key}") == day:
            return False
        self.db.set_kv(f"last_{key}", day)
        return True

    # ---- the three duties ------------------------------------------------------------------

    def due_reminders(self, now: datetime) -> int:
        rows = self.db.all("SELECT * FROM reminders WHERE done = 0")
        fired = 0
        for row in rows:
            due = datetime.fromisoformat(row["due_at"])
            if due.tzinfo is None:
                due = due.astimezone()
            if due <= now:
                self.db.execute("UPDATE reminders SET done = 1 WHERE id = ?", (row["id"],))
                self.add_initiative("rappel", f"Rappel : {row['text']}", "", level=0)
                fired += 1
        return fired

    def briefing(self, now: datetime) -> str:
        hello = greetings.opening(self.db, now, self.config.user_name)  # "" if already greeted
        parts = [hello] if hello else []
        try:
            parts.append("Météo — " + weather_summary(self.config.city, self.fetch) + ".")
        except (OSError, ValueError, KeyError):
            parts.append("Météo indisponible ce matin.")
        end = (now + timedelta(days=1)).isoformat()
        today = self.db.all(
            "SELECT due_at, text FROM reminders WHERE done = 0 AND due_at <= ? ORDER BY due_at",
            (end,),
        )
        if today:
            parts.append(
                "Aujourd'hui : "
                + " ; ".join(f"{r['due_at'][11:16]} {r['text']}" for r in today)
                + "."
            )
        pending = self.db.one("SELECT COUNT(*) AS n FROM approvals WHERE status = 'pending'")
        if pending and pending["n"]:
            parts.append(f"{pending['n']} action(s) attendent ta validation.")
        running = self.db.one(
            "SELECT COUNT(*) AS n FROM missions WHERE status IN ('queued', 'running')"
        )
        if running and running["n"]:
            parts.append(f"{running['n']} mission(s) en cours.")
        text = " ".join(parts)
        self.add_initiative("briefing", "Briefing du matin", text, level=0)
        return text

    def consolidate(self, now: datetime) -> int:
        """Nightly 'autodream': extract durable facts from yesterday's conversations."""
        since = (now - timedelta(days=1)).astimezone().isoformat(timespec="seconds")
        events = self.db.all(
            "SELECT source, text FROM events WHERE kind IN ('utterance', 'reply') AND ts >= ? "
            "ORDER BY id",
            (since,),
        )
        if not events:
            return 0
        transcript = "\n".join(f"{e['source']}: {e['text']}" for e in events)[-24000:]
        reply = one_shot(self.cli, transcript, CONSOLIDATOR, model="haiku")
        try:
            facts = extract_json(reply.text).get("facts", [])
        except (ValueError, AttributeError):
            return 0
        memory, added = Memory(self.db), 0
        for fact in facts:
            try:
                memory.remember(
                    str(fact["subject"]),
                    str(fact["predicate"]),
                    str(fact["value"]),
                    category=str(fact.get("category", "autre")),
                    confidence=float(fact.get("confidence", 0.6)),
                )
                added += 1
            except (KeyError, ValueError, TypeError):
                continue
        stale = self.db.one(
            "SELECT COUNT(*) AS n FROM facts WHERE status = 'active' AND last_seen_at < ?",
            ((now - timedelta(days=90)).isoformat(timespec="seconds"),),
        )
        body = f"{added} fait(s) consolidé(s) depuis les échanges d'hier."
        if stale and stale["n"]:
            body += f" {stale['n']} souvenir(s) non revus depuis 90 jours : à vérifier."
        self.add_initiative("memoire", "Rapport de la nuit", body, level=0)
        return added

    # ---- coming to talk, to get to know the user ----------------------------------------

    def befriend_due(self, now: datetime) -> bool:
        """Allowed and chosen now: within the hours, under today's count, spaced out, quiet."""
        per_day = max(0, min(4, self.config.befriend_per_day))
        start, end = parse_hours(self.config.befriend_hours)
        if not per_day or not start <= now.hour < end or not self.is_free():
            return False
        day = now.strftime("%Y-%m-%d")
        done_today = self.db.one(
            "SELECT COUNT(*) AS n FROM initiatives WHERE kind = 'lien' AND substr(ts, 1, 10) = ?",
            (now.astimezone(UTC).strftime("%Y-%m-%d") if now.tzinfo else day,),
        )
        if done_today and done_today["n"] >= per_day:
            return False
        last = self.db.one("SELECT ts FROM initiatives WHERE kind = 'lien' ORDER BY id DESC")
        if last:
            since = (now - datetime.fromisoformat(last["ts"])).total_seconds()
            gap = BEFRIEND_GAP_S if self._answered(last["ts"]) else BEFRIEND_IGNORED_GAP_S
            if since < gap:
                return False
        spoke = self.db.one(
            "SELECT ts FROM events WHERE kind IN ('utterance', 'reply') ORDER BY id DESC"
        )
        if spoke and (now - datetime.fromisoformat(spoke["ts"])).total_seconds() < BEFRIEND_QUIET_S:
            return False
        return self.rand() < BEFRIEND_CHANCE

    def _answered(self, since: str) -> bool:
        return (
            self.db.one(
                "SELECT 1 FROM events WHERE kind = 'utterance' AND source = 'user' AND ts > ?",
                (since,),
            )
            is not None
        )

    def befriend(self, now: datetime) -> str:
        """Spectre comes over with a question or a follow-up; the answer feeds its memory."""
        recent = self.db.all(
            "SELECT body FROM initiatives WHERE kind = 'lien' ORDER BY id DESC LIMIT 8"
        )
        lines = greetings.recent_lines(self.db)
        counts = {c: 0 for c in CATEGORIES if c not in ("persona", "autre")}
        for fact in Memory(self.db).list():
            if fact["category"] in counts:
                counts[fact["category"]] += 1
        thin = ", ".join(sorted(counts, key=lambda c: counts[c])[:4])
        prompt = (
            f"Moment exact : {greetings.moment(now)}. "
            f"Prénom : {self.config.user_name or 'inconnu'}.\n"
            f"{greetings.greeting_rule(self.db, now)}\n"
            f"Ce que tu sais de lui :\n{Memory(self.db).context_block(30)}\n"
            f"Sujets que tu connais le moins : {thin}.\n"
            "Tes dernières venues et répliques (ne reprends ni leurs mots ni leur tournure) :\n"
            + ("\n".join(f"- {line}" for line in [r["body"] for r in recent] + lines) or "(aucune)")
        )
        reply = one_shot(self.cli, prompt, BEFRIEND, model=self.config.brain_model)
        try:
            data = extract_json(reply.text)
            text, topic = str(data.get("text", "")).strip(), str(data.get("topic", "")).strip()
        except (ValueError, AttributeError):
            text, topic = "", ""
        if not text or reply.is_error:
            return ""
        self.db.set_kv("befriend_opener", f"{datetime.now().timestamp()}|{text}")
        greetings.remember_line(self.db, text)
        greetings.mark_greeted(self.db, now)
        self.db.log_event("reply", "spectre", text, channel="initiative", topic=topic)
        self.add_initiative("lien", "Spectre vient te parler", text, level=0, data={"topic": topic})
        return text

    def add_initiative(
        self,
        kind: str,
        title: str,
        body: str,
        *,
        level: int = 0,
        data: dict[str, Any] | None = None,
    ) -> int:
        initiative_id = self.db.execute(
            "INSERT INTO initiatives(ts, kind, title, body, level, data) VALUES(?, ?, ?, ?, ?, ?)",
            (now_iso(), kind, title, body, level, json.dumps(data or {}, ensure_ascii=False)),
        )
        self.notify(kind, title, body)
        return initiative_id
