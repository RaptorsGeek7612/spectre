"""Meeting mode, all on this PC: listen, transcribe, then summarise into tasks and decisions.

Audio is transcribed in chunks of CHUNK_S seconds with the local speech-to-text and then
dropped: only the text is kept, nothing leaves the PC. When the meeting stops, a mission
summarises it; with a company, its tasks go to the board (to do) and its decisions to the
decision journal (to be reviewed in a month). A WAV file can be given instead of the microphone.
"""

from __future__ import annotations

import io
import json
import threading
import wave
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Any

from spectre.assistant.db import Database, now_iso

RATE = 16_000
CHUNK_S = 30.0
MAX_HOURS = 4
MAX_UPLOAD = 200 * 1024 * 1024
SLICE = 30_000  # characters of transcript per summary call
REQUEST_KV = "meeting_request"

SUMMARY = """\
Tu fais le compte rendu d'une réunion à partir de sa transcription automatique (elle peut \
contenir des erreurs de reconnaissance : corrige le sens, n'invente rien). Réponds UNIQUEMENT \
par un objet JSON : {{"resume": "le résumé en quelques paragraphes", "decisions": ["..."], \
"taches": [{{"titre": "...", "departement": "un parmi {departments} ou vide", "detail": \
"qui, quoi, pour quand si dit"}}], "questions_ouvertes": ["..."]}}."""

PARTIAL = """\
Résume fidèlement ce morceau de transcription de réunion : points abordés, décisions, tâches \
et qui s'en charge, chiffres cités. Pas d'invention."""


class MeetingError(ValueError):
    """A refused request (the message is for the user)."""


def wav_pcm(data: bytes) -> bytes:
    """16 kHz mono int16 PCM from a WAV file (any rate, mono or stereo, 16-bit)."""
    import numpy as np

    try:
        with wave.open(io.BytesIO(data)) as wav:
            channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError) as exc:
        raise MeetingError("fichier WAV attendu (16 bits)") from exc
    if width != 2:
        raise MeetingError("WAV 16 bits attendu")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != RATE and len(samples):
        positions = np.linspace(0, len(samples) - 1, int(len(samples) * RATE / rate))
        samples = np.interp(positions, np.arange(len(samples)), samples)
    return bytes(samples.astype(np.int16).tobytes())


def padded(pcm: bytes) -> bytes:
    """A chunk with a second of silence after it: speech-to-text drops a last sentence that
    stops dead at the end of the audio."""
    return pcm + b"\x00\x00" * RATE


def chunks(pcm: bytes, seconds: float = CHUNK_S) -> Iterator[bytes]:
    size = int(RATE * seconds) * 2
    for start in range(0, len(pcm), size):
        yield pcm[start : start + size]


class Meetings:
    """Meetings in the database: transcript, summary, what they produced."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT id, company_id, title, status, source, started_at, ended_at, seconds, "
            "summary, mission_id, length(transcript) AS chars FROM meetings "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return rows

    def get(self, meeting_id: int) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM meetings WHERE id = ?", (int(meeting_id),))
        if row is None:
            raise MeetingError(f"réunion #{meeting_id} introuvable")
        return row

    def active(self) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM meetings WHERE status = 'recording' ORDER BY id DESC LIMIT 1"
        )

    def create(self, title: str, company_id: int | None, source: str) -> dict[str, Any]:
        if source == "micro" and self.active():
            raise MeetingError("une réunion est déjà en cours d'enregistrement")
        title = title.strip() or f"Réunion du {datetime.now():%d/%m/%Y %H:%M}"
        mid = self.db.execute(
            "INSERT INTO meetings(company_id, title, status, source, started_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (
                company_id,
                title[:200],
                "recording" if source == "micro" else "transcribing",
                source,
                now_iso(),
            ),
        )
        return self.get(mid)

    def append(self, meeting_id: int, text: str, seconds: float) -> None:
        if not text.strip():
            self.db.execute(
                "UPDATE meetings SET seconds = seconds + ? WHERE id = ?", (seconds, meeting_id)
            )
            return
        self.db.execute(
            "UPDATE meetings SET transcript = transcript || ? || ?, seconds = seconds + ? "
            "WHERE id = ?",
            ("\n" if self.get(meeting_id)["transcript"] else "", text.strip(), seconds, meeting_id),
        )

    def close(self, meeting_id: int) -> int:
        """Stop listening and queue the summary mission; returns its id (0 if nothing heard)."""
        from spectre.assistant.company import enqueue

        meeting = self.get(meeting_id)
        if not meeting["transcript"].strip():
            self.db.execute(
                "UPDATE meetings SET status = 'done', ended_at = ?, summary = ? WHERE id = ?",
                (now_iso(), "Rien n'a été entendu.", meeting_id),
            )
            return 0
        mission = enqueue(
            self.db,
            f"Compte rendu : {meeting['title']}",
            {
                "kind": "meeting",
                "meeting": meeting_id,
                **({"company": meeting["company_id"]} if meeting["company_id"] else {}),
            },
        )
        self.db.execute(
            "UPDATE meetings SET status = 'summarizing', ended_at = ?, mission_id = ? WHERE id = ?",
            (now_iso(), mission, meeting_id),
        )
        return mission

    def delete(self, meeting_id: int) -> None:
        meeting = self.get(meeting_id)
        if meeting["status"] == "recording":
            raise MeetingError("arrête d'abord l'enregistrement")
        self.db.execute("DELETE FROM meetings WHERE id = ?", (meeting["id"],))

    # ---- the summary mission -----------------------------------------------------------------

    def summarize(self, meeting_id: int, ask: Callable[[str, str], Any], now: datetime) -> str:
        """Summarise (in slices when long), then file tasks and decisions; returns the report."""
        from spectre.assistant.brain import extract_json, failed
        from spectre.assistant.company import DEPARTMENTS, Companies, resolve_department

        meeting = self.get(meeting_id)
        transcript = meeting["transcript"]
        if len(transcript) > SLICE:  # long meeting: summarise each slice, then the whole
            parts = []
            for start in range(0, len(transcript), SLICE):
                reply = ask(transcript[start : start + SLICE], PARTIAL)
                if failed(reply):
                    raise MeetingError(reply.text[:300])
                parts.append(reply.text)
            transcript = "\n\n".join(f"Partie {i + 1} :\n{p}" for i, p in enumerate(parts))
        reply = ask(
            f"Réunion : {meeting['title']}\n\nTranscription :\n{transcript}",
            SUMMARY.format(departments=", ".join(DEPARTMENTS)),
        )
        if failed(reply):
            raise MeetingError(reply.text[:300])
        data = extract_json(reply.text)
        if not isinstance(data, dict):
            raise MeetingError("compte rendu illisible")
        tasks = [
            t
            for t in data.get("taches") or []
            if isinstance(t, dict) and str(t.get("titre", "")).strip()
        ]
        decisions = [str(d).strip() for d in data.get("decisions") or [] if str(d).strip()]
        created_tasks, created_decisions = [], []
        if meeting["company_id"]:
            companies = Companies(self.db)
            for task in tasks[:20]:
                department = str(task.get("departement") or "")
                created_tasks.append(
                    companies.add_task(
                        meeting["company_id"],
                        str(task["titre"])[:200]
                        if len(str(task["titre"])) >= 3
                        else f"Tâche : {task['titre']}",
                        department=department if resolve_department(department) else "",
                        detail=f"{task.get('detail', '')}\n\n"
                        f"(Issue de la réunion « {meeting['title']} »)",
                    )["id"]
                )
            for decision in decisions[:10]:
                verdict = {
                    "decision": decision,
                    "raisons": f"Décidé en réunion : {meeting['title']}",
                }
                created_decisions.append(
                    self.db.execute(
                        "INSERT INTO decisions(company_id, question, status, verdict, decision, "
                        "review_at, created_at, decided_at) VALUES(?, ?, 'decided', ?, ?, ?, ?, ?)",
                        (
                            meeting["company_id"],
                            f"Réunion « {meeting['title']} » : {decision}"[:1000],
                            json.dumps(verdict, ensure_ascii=False),
                            decision[:2000],
                            (now + timedelta(days=30)).isoformat(),
                            now_iso(),
                            now.isoformat(),
                        ),
                    )
                )
        report = render(meeting, data, created_tasks, created_decisions)
        self.db.execute(
            "UPDATE meetings SET status = 'done', summary = ?, result = ? WHERE id = ?",
            (
                str(data.get("resume", ""))[:20_000],
                json.dumps(
                    {"tasks": created_tasks, "decisions": created_decisions, **data},
                    ensure_ascii=False,
                ),
                meeting_id,
            ),
        )
        return report

    def failed(self, meeting_id: int, reason: str) -> None:
        self.db.execute(
            "UPDATE meetings SET status = 'failed', summary = ? WHERE id = ?",
            (reason[:500], meeting_id),
        )


def render(
    meeting: dict[str, Any], data: dict[str, Any], tasks: list[int], decisions: list[int]
) -> str:
    minutes = round((meeting["seconds"] or 0) / 60)
    lines = [
        f"# {meeting['title']}",
        "",
        f"Durée écoutée : {minutes} min",
        "",
        "## Résumé",
        str(data.get("resume", "")),
    ]
    if data.get("decisions"):
        lines += ["", "## Décisions"] + [f"- {d}" for d in data["decisions"]]
    if data.get("taches"):
        lines += ["", "## Tâches"]
        for task in data["taches"]:
            if isinstance(task, dict):
                where = f" ({task.get('departement')})" if task.get("departement") else ""
                lines.append(f"- {task.get('titre', '')}{where} — {task.get('detail', '')}")
    if data.get("questions_ouvertes"):
        lines += ["", "## Questions ouvertes"] + [f"- {q}" for q in data["questions_ouvertes"]]
    if tasks or decisions:
        lines += [
            "",
            f"Ajouté à l'entreprise : {len(tasks)} tâche(s) au tableau, "
            f"{len(decisions)} décision(s) au journal.",
        ]
    return "\n".join(lines) + "\n"


# ---- listening -----------------------------------------------------------------------------------


class Recorder:
    """Listens to a microphone in a thread and transcribes it chunk by chunk."""

    def __init__(
        self,
        meetings: Meetings,
        stt: Callable[[], Any],
        mic: Callable[[], Any],
        notify: Callable[..., Any] = lambda *a: None,
    ) -> None:
        self.meetings = meetings
        self.stt = stt  # -> an object with transcribe(pcm) (created on first use)
        self.mic = mic  # -> a context manager with blocks(stop) (the PC's microphone)
        self.notify = notify
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.meeting_id: int | None = None
        self.error = ""

    @property
    def recording(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(
        self, title: str = "", company_id: int | None = None, *, background: bool = True
    ) -> dict[str, Any]:
        if self.recording:
            raise MeetingError("une réunion est déjà en cours d'enregistrement")
        engine = self.stt()  # fail now (missing speech model) rather than in the thread
        meeting = self.meetings.create(title, company_id, "micro")
        self.meeting_id, self.error = meeting["id"], ""
        self.stop_event.clear()
        if background:  # pragma: no cover - thread wrapper around listen
            self.thread = threading.Thread(
                target=self.listen, args=(engine,), name="spectre-meeting", daemon=True
            )
            self.thread.start()
        else:
            self.listen(engine)
        return meeting

    def listen(self, engine: Any) -> None:
        meeting_id = self.meeting_id
        assert meeting_id is not None
        size = int(RATE * CHUNK_S) * 2
        buffer = bytearray()
        limit = RATE * 2 * 3600 * MAX_HOURS
        heard = 0
        try:
            with self.mic() as mic:
                for block in mic.blocks(self.stop_event):
                    buffer += block
                    heard += len(block)
                    if len(buffer) >= size:
                        self.meetings.append(
                            meeting_id,
                            engine.transcribe(padded(bytes(buffer))),
                            len(buffer) / RATE / 2,
                        )
                        buffer.clear()
                    if heard >= limit:
                        self.error = f"limite de {MAX_HOURS} h atteinte"
                        break
            if buffer:
                self.meetings.append(
                    meeting_id, engine.transcribe(padded(bytes(buffer))), len(buffer) / RATE / 2
                )
        except Exception as exc:  # noqa: BLE001 - a broken microphone must not kill Spectre
            self.error = str(exc)[:300]
        mission = self.meetings.close(meeting_id)
        title = self.meetings.get(meeting_id)["title"]
        self.notify(
            "reunion",
            f"Réunion terminée : {title}",
            ("Compte rendu en préparation." if mission else "Rien n'a été entendu.")
            + (f" ({self.error})" if self.error else ""),
        )

    def stop(self) -> int | None:
        """Stop listening; returns the meeting id."""
        if not self.recording:
            raise MeetingError("aucune réunion en cours")
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=120)
        return self.meeting_id

    def transcribe_file(self, data: bytes, title: str, company_id: int | None) -> dict[str, Any]:
        """A recorded meeting (WAV): transcribed now, then summarised like a live one."""
        if len(data) > MAX_UPLOAD:
            raise MeetingError("fichier trop volumineux (200 Mo maximum)")
        pcm = wav_pcm(data)
        engine = self.stt()
        meeting = self.meetings.create(title, company_id, "fichier")
        for part in chunks(pcm):
            self.meetings.append(
                meeting["id"], engine.transcribe(padded(part)), len(part) / RATE / 2
            )
        self.meetings.close(meeting["id"])
        return self.meetings.get(meeting["id"])
