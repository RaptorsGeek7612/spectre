"""The assistant service: wires brain, memory, governance, missions, proactivity and voice,
and publishes live events (state, messages, approvals, initiatives) to the web UI."""

from __future__ import annotations

import base64
import contextlib
import queue
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spectre.assistant import tools
from spectre.assistant.brain import Brain, ClaudeCLI
from spectre.assistant.config import AGENT_NAMES, AGENT_ORDER, AGENT_ROLES, AssistantConfig
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate
from spectre.assistant.memory import Memory
from spectre.assistant.missions import MissionEngine
from spectre.assistant.proactive import Proactive
from spectre.assistant.vision.faces import SPOOF, UNKNOWN, FaceBook, Presence
from spectre.assistant.voice.listen import SAMPLE_RATE, to_wav
from spectre.config import DEFAULT_SPECS, model_label

Event = dict[str, Any]
LEVEL_EVERY_S = 0.05


class AssistantService:
    """One instance per running assistant (web server + optional voice)."""

    def __init__(
        self,
        root: Path,
        config: AssistantConfig | None = None,
        *,
        cli: ClaudeCLI | None = None,
        fetch: Callable[[str], Any] | None = None,
    ) -> None:
        self.root = root
        self.config = config or AssistantConfig.load(root)
        self.db = Database(root / "spectre.db")
        self.memory = Memory(self.db)
        self.gate = Gate(self.db, auto_max_level=self.config.auto_max_level)
        self.ctx = tools.make_context(self.db, root, self.config.allowed_roots)
        self.cli = cli or ClaudeCLI(self.config, root)
        self.brain = Brain(self.db, self.cli, self.config)
        kwargs: dict[str, Any] = {"fetch": fetch} if fetch else {}
        self.proactive = Proactive(self.db, self.cli, self.config, self._on_initiative, **kwargs)
        self.missions = MissionEngine(
            self.db,
            self.cli,
            lambda kind, title, body: self.proactive.add_initiative(kind, title, body),
            model=self.config.mission_model,
            lead_model=self.config.brain_model,
        )
        self.voice: Any = None
        self.voice_state = "off"
        self.faces = FaceBook(self.db)
        self.presence = Presence(self.db, self._on_arrival, time.monotonic)
        self.camera: Any = None
        self._spoof_logged_at = -1e9
        self._subscribers: list[queue.Queue[Event]] = []
        self._sub_lock = threading.Lock()
        self._busy = threading.Lock()
        self._stop = threading.Event()
        self._level_at = 0.0
        self._seen = {
            "approvals": self._max_id("approvals"),
            "initiatives": self._max_id("initiatives"),
        }

    # ---- lifecycle -----------------------------------------------------------------------

    def start(self, *, background: bool = True) -> None:
        self.memory.mirror(self.root / "memoire")
        if background:  # pragma: no cover - threads exercised manually
            self.missions.start()
            self.proactive.start()
            threading.Thread(target=self._watch, name="spectre-watch", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.missions.stop()
        self.proactive.stop()
        if self.voice is not None:
            self.voice.stop.set()
        if self.camera is not None:
            self.camera.stop.set()

    # ---- events ----------------------------------------------------------------------------

    def subscribe(self) -> queue.Queue[Event]:
        q: queue.Queue[Event] = queue.Queue(maxsize=500)
        with self._sub_lock:
            self._subscribers.append(q)
        q.put({"type": "state", "state": self.voice_state, "detail": ""})
        return q

    def unsubscribe(self, q: queue.Queue[Event]) -> None:
        with self._sub_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event: Event) -> None:
        with self._sub_lock:
            targets = list(self._subscribers)
        for q in targets:
            with contextlib.suppress(queue.Full):
                q.put_nowait(event)

    def _on_initiative(self, kind: str, title: str, body: str) -> None:
        self.publish({"type": "initiative", "kind": kind, "title": title, "body": body})
        if (
            self.voice is not None
            and self.config.speak_initiatives
            and self.voice_state == "sleeping"
        ):
            threading.Thread(target=self.voice.say, args=(f"{title}. {body}",), daemon=True).start()

    def _max_id(self, table: str) -> int:
        row = self.db.one(f"SELECT COALESCE(MAX(id), 0) AS n FROM {table}")  # noqa: S608 - fixed
        return int(row["n"]) if row else 0

    def poll_changes(self) -> None:
        """Publish approvals/initiatives created elsewhere (e.g. by the MCP tool process)."""
        for table, kind in (("approvals", "approval"), ("initiatives", "initiative_row")):
            rows = self.db.all(
                f"SELECT * FROM {table} WHERE id > ? ORDER BY id",  # noqa: S608 - fixed names
                (self._seen[table],),
            )
            for row in rows:
                self._seen[table] = row["id"]
                self.publish({"type": kind, "row": row})

    def _watch(self) -> None:  # pragma: no cover - thread wrapper
        while not self._stop.wait(1.5):
            self.poll_changes()

    # ---- conversation ----------------------------------------------------------------------

    def set_level(self, rms: float) -> None:
        """Loudness heard or spoken (int16 RMS), throttled to ~20 events/s for the voice orb."""
        now = time.monotonic()
        if rms > 0 and now - self._level_at < LEVEL_EVERY_S:
            return
        self._level_at = now
        level = min(1.0, (max(rms, 0.0) / 6000) ** 0.6)
        self.publish({"type": "level", "v": round(level, 3)})

    def set_voice_state(self, state: str, detail: str = "") -> None:
        if state != "heard":
            self.voice_state = state
        self.publish({"type": "state", "state": state, "detail": detail})

    def chat(self, text: str, channel: str = "text") -> str:
        """One turn with the brain (serialised: Spectre answers one thing at a time)."""
        text = text.strip()
        if not text:
            raise ValueError("message vide")
        self.publish({"type": "message", "role": "user", "text": text, "channel": channel})
        with self._busy:
            if channel == "text":
                self.publish({"type": "state", "state": "thinking", "detail": ""})
            reply = self.brain.ask(text, channel=channel)
            if channel == "text":
                self.publish({"type": "state", "state": self.voice_state, "detail": ""})
        self.publish(
            {
                "type": "message",
                "role": "spectre",
                "text": reply.text,
                "channel": channel,
                "error": reply.is_error,
            }
        )
        self.poll_changes()
        return reply.text

    def history(self, limit: int = 60) -> list[Event]:
        rows = self.db.all(
            "SELECT ts, kind, source, text FROM events WHERE kind IN ('utterance', 'reply') "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "ts": r["ts"],
                "role": "user" if r["source"] == "user" else "spectre",
                "text": r["text"],
            }
            for r in reversed(rows)
        ]

    # ---- approvals, missions, initiatives, memory -----------------------------------------

    def approvals(self, status: str = "pending") -> list[Event]:
        return self.db.all(
            "SELECT * FROM approvals WHERE status = ? ORDER BY id DESC LIMIT 50", (status,)
        )

    def approve(self, approval_id: int) -> str:
        result = tools.run_approved(self.gate, self.ctx, approval_id)
        self.publish({"type": "approval_done", "id": approval_id, "result": result})
        self.db.log_event("approval", "user", f"validé #{approval_id}: {result[:200]}")
        return result

    def deny(self, approval_id: int, reason: str = "") -> None:
        tools.deny(self.ctx, approval_id, reason)
        self.publish({"type": "approval_done", "id": approval_id, "result": "refusé"})
        self.db.log_event("approval", "user", f"refusé #{approval_id}")

    def missions_list(self) -> list[Event]:
        return self.db.all(
            "SELECT id, ts, goal, status, steps, report, error, updated_at FROM missions "
            "ORDER BY id DESC LIMIT 30"
        )

    def start_mission(self, goal: str, kind: str = "mission", agent: str = "") -> str:
        args = {"goal": goal, "kind": kind} | ({"agent": agent} if agent else {})
        return tools.execute(self.gate, self.ctx, "start_mission", args)

    def initiatives(self, status: str = "pending") -> list[Event]:
        return self.db.all(
            "SELECT * FROM initiatives WHERE status = ? ORDER BY id DESC LIMIT 50", (status,)
        )

    def resolve_initiative(self, initiative_id: int, status: str) -> None:
        if status not in ("done", "dismissed"):
            raise ValueError("statut attendu : done ou dismissed")
        if not self.db.one("SELECT 1 FROM initiatives WHERE id = ?", (initiative_id,)):
            raise KeyError(initiative_id)
        self.db.execute("UPDATE initiatives SET status = ? WHERE id = ?", (status, initiative_id))

    def facts(self, query: str = "", category: str | None = None) -> list[Event]:
        if query.strip():
            return self.memory.recall(query, limit=100)
        return self.memory.list(category=category or None)

    def forget(self, fact_id: int) -> Event:
        fact = self.memory.forget(fact_id)
        self.memory.mirror(self.root / "memoire")
        return fact

    def correct(self, fact_id: int, value: str) -> Event:
        fact = self.memory.correct(fact_id, value)
        self.memory.mirror(self.root / "memoire")
        return fact

    def audit(self, limit: int = 100) -> list[Event]:
        return self.db.all("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))

    def status(self) -> Event:
        return {
            "name": self.config.name,
            "voice": self.voice_state,
            "voice_available": self.voice is not None,
            "brain_model": self.config.brain_model,
            "brain_label": model_label(self.config.brain_model),
            "pending_approvals": len(self.approvals()),
            "pending_initiatives": len(self.initiatives()),
            "facts": len(self.memory.list()),
            "missions_running": len(
                self.db.all("SELECT id FROM missions WHERE status IN ('queued', 'running')")
            ),
            "camera": self.camera is not None,
            "present": self.presence.present(),
        }

    def agents(self) -> Event:
        """Every agent by name: Spectre and its sub-agents, then the writing pipeline."""
        cfg = self.config
        binaries = {"chatgpt": cfg.codex_bin, "mistral": cfg.vibe_bin}
        engines = {
            "chatgpt": f"ChatGPT{f' ({cfg.chatgpt_model})' if cfg.chatgpt_model else ''} · Codex",
            "mistral": f"Mistral{f' ({cfg.mistral_model})' if cfg.mistral_model else ''} · Vibe",
        }
        assistant = [
            {
                "key": key,
                "name": AGENT_NAMES[key],
                "engine": engines.get(key) or f"{model_label(key)} · Claude Code",
                "role": AGENT_ROLES[key],
                "available": shutil.which(binaries.get(key, cfg.claude_bin)) is not None,
                "default": key == cfg.mission_model,
            }
            for key in AGENT_ORDER
        ]
        redaction = [
            {"key": spec.name, "name": spec.name.capitalize(), "engine": model_label(spec.model)}
            for spec in DEFAULT_SPECS.values()
        ]
        return {"assistant": assistant, "redaction": redaction}

    def update_config(self, changes: dict[str, Any]) -> Event:
        self.config.update(changes)
        self.config.save(self.root)
        self.gate.auto_max_level = self.config.auto_max_level
        self.missions.model = self.config.mission_model
        return self.config.__dict__.copy()

    # ---- voice -----------------------------------------------------------------------------

    def attach_voice(self, voice: Any) -> None:
        self.voice = voice

    def push_to_talk(self) -> None:
        if self.voice is None:
            raise ValueError("la voix n'est pas active (lance avec --voice)")
        self.voice.trigger()

    def voice_reply(self, text: str) -> str:
        return self.chat(text, channel="voice")

    def remote_voice(self, pcm: bytes) -> Event:
        """A turn spoken into another device (the phone, 16 kHz mono int16): Spectre transcribes
        it with its own speech recognition, answers, and returns its voice as a WAV to play
        there; nothing is played on the PC."""
        if self.voice is None:
            raise ValueError("la voix n'est pas active (lance Spectre avec la voix)")
        if len(pcm) < SAMPLE_RATE:  # under half a second: nothing was said
            return {"heard": "", "reply": "", "audio": ""}
        text = str(self.voice.stt.transcribe(pcm)).strip()
        if not text:
            return {"heard": "", "reply": "", "audio": ""}
        reply = self.chat(text, channel="voice")
        audio = ""
        render = getattr(self.voice.tts, "render", None)  # the Windows fallback voice cannot
        rendered = render(reply) if reply and render else None
        if rendered:
            audio = base64.b64encode(to_wav(*rendered)).decode("ascii")
        return {"heard": text, "reply": reply, "audio": audio}

    # ---- vision (opt-in) -------------------------------------------------------------------

    def attach_camera(self, camera: Any) -> None:
        self.camera = camera

    def on_faces(self, faces: list[dict[str, Any]]) -> None:
        """One camera look: identify live, enrolled people; flag photos and screens."""
        names = [
            self.faces.identify(face["feature"])[0] if face.get("live", True) else SPOOF
            for face in faces
        ]
        present = self.presence.sighting(names)
        spoofs = names.count(SPOOF)
        if spoofs and time.monotonic() - self._spoof_logged_at > 60:
            self._spoof_logged_at = time.monotonic()
            self.db.log_event("spoof", "camera", "photo ou écran présenté à la caméra")
        self.publish(
            {
                "type": "presence",
                "people": present,
                "unknown": names.count(UNKNOWN),
                "spoof": spoofs,
            }
        )

    def remote_frame(self, jpeg: bytes) -> Event:
        """A picture from another device's camera (the phone), analysed like the PC camera's:
        enrolled, live people become present; nothing is stored."""
        if self.camera is None:
            raise ValueError(
                "la reconnaissance des visages n'est pas active (active-la dans les réglages "
                "puis relance Spectre)"
            )
        if not jpeg:
            raise ValueError("image vide")
        faces = self.camera.engine.embeddings_jpeg(jpeg)
        self.on_faces(faces)
        return {"faces": len(faces), "present": self.presence.present()}

    def _on_arrival(self, name: str, away_s: float) -> None:
        greeting = f"Bon retour, {name}." if away_s else f"Bonjour {name}."
        self.db.log_event("presence", "camera", f"{name} est là")
        self.publish({"type": "arrival", "name": name, "text": greeting})
        if self.voice is not None and self.voice_state == "sleeping":
            threading.Thread(target=self.voice.say, args=(greeting,), daemon=True).start()

    def enroll_face(self, name: str, samples: int = 6, attempts: int = 30) -> int:
        """Look through the camera until `samples` single-face shots are taken, then store them."""
        if self.camera is None:
            raise ValueError("la caméra n'est pas active (lance avec --camera)")
        shots: list[list[float]] = []
        for _ in range(attempts):
            faces = self.camera.grab()
            if len(faces) == 1 and faces[0].get("live", True):  # never enroll a photo
                shots.append(faces[0]["feature"])
                if len(shots) >= samples:
                    break
        if len(shots) < max(2, samples // 2):
            raise ValueError(
                "je n'ai pas réussi à bien voir ton visage (seul, de face, bien éclairé, "
                "et pas une photo)"
            )
        count = self.faces.enroll(name, shots)
        self.db.log_event("face_enrolled", "user", f"visage de {name} enregistré ({count} prises)")
        return count

    def forget_face(self, name: str) -> int:
        count = self.faces.forget(name)
        self.presence.last_seen.pop(name, None)
        self.db.log_event("human_correction", "user", f"visage de {name} oublié")
        return count
