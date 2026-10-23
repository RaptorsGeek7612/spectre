"""The assistant service: wires brain, memory, governance, missions, proactivity and voice,
and publishes live events (state, messages, approvals, initiatives) to the web UI."""

from __future__ import annotations

import base64
import contextlib
import json
import queue
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from spectre.assistant import call, engines, greetings, sessions, team, tools, winapi
from spectre.assistant.brain import Brain, ClaudeCLI
from spectre.assistant.company import DEPARTMENTS, Companies
from spectre.assistant.config import (
    AGENT_NAMES,
    AGENT_ORDER,
    AGENT_ROLES,
    HOSTED_AGENTS,
    ROLES,
    AssistantConfig,
    resolve_role,
)
from spectre.assistant.custom_agents import CustomAgents
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate, Level
from spectre.assistant.learning import Learning
from spectre.assistant.meeting import REQUEST_KV, MeetingError, Meetings, Recorder
from spectre.assistant.memory import Memory
from spectre.assistant.missions import MissionEngine
from spectre.assistant.proactive import Proactive
from spectre.assistant.providers import ProviderError, Providers, split_ref
from spectre.assistant.routines import Routines
from spectre.assistant.saas import Saas
from spectre.assistant.telegram import Telegram, save_token
from spectre.assistant.vision.faces import SPOOF, UNKNOWN, FaceBook, Presence
from spectre.assistant.voice.listen import SAMPLE_RATE, to_wav
from spectre.assistant.webhooks import Rejected, Webhooks
from spectre.assistant.webpush import WebPush
from spectre.config import DEFAULT_SPECS, model_label

Event = dict[str, Any]
LEVEL_EVERY_S = 0.05
ATTACHMENTS = "pieces-jointes"  # in the brain's workspace: files joined to messages
MAX_ATTACHMENTS = 10
INLINE_TEXT = 20_000  # bytes: a short text file also goes into the message


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
        self.gate = Gate(
            self.db,
            auto_max_level=self.config.auto_max_level,
            per_minute=self.config.actions_per_minute,
            per_day=self.config.actions_per_day,
        )
        self.ctx = tools.make_context(self.db, root, self.config.allowed_roots)
        self.cli = cli or ClaudeCLI(self.config, root)
        self.brain = Brain(self.db, self.cli, self.config)
        kwargs: dict[str, Any] = {"fetch": fetch} if fetch else {}
        self.proactive = Proactive(
            self.db, self.cli, self.config, self._on_initiative, is_free=self._free, **kwargs
        )
        self.missions = MissionEngine(
            self.db,
            self.cli,
            lambda kind, title, body: self.proactive.add_initiative(kind, title, body),
            model=self.config.mission_model,
            lead_model=self.config.planner_model or self.config.brain_model,
            verifier_model=self.config.verifier_model,
            fallbacks=self.config.fallback_models,
            parallel=self.config.mission_parallel,
        )
        self.providers = Providers(root)
        self.missions.learn = self.config.learn_from_missions
        self.missions.learning_model = self.config.learning_model
        self.missions.earned_autonomy = self.config.earned_autonomy
        self.telegram = Telegram(root, self.db, self._telegram_reply)
        self.recorder = Recorder(
            Meetings(self.db), self._meeting_stt, self._meeting_mic, self._meeting_done
        )
        self._stt: Any = None
        self.webhooks = Webhooks(self.db)
        self.push = WebPush(self.db, root)
        self._config_mtime = self._config_stamp()
        self.voice: Any = None
        self.voice_state = "off"
        self.faces = FaceBook(self.db)
        self.presence = Presence(self.db, self._on_arrival, time.monotonic)
        self.camera: Any = None
        self._spoof_logged_at = -1e9
        self._subscribers: list[queue.Queue[Event]] = []
        self._sub_lock = threading.Lock()
        self._busy = threading.Lock()
        self.power: Callable[[], Event] = winapi.power_status  # on battery: may go to sleep
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
            self.telegram.start()
            threading.Thread(target=self._watch, name="spectre-watch", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.missions.stop()
        self.proactive.stop()
        self.telegram.stop()
        if self.recorder.recording:
            self.recorder.stop_event.set()
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

    def _free(self) -> bool:
        """Nobody is talking with Spectre right now (a good moment to come over)."""
        return self.voice_state in ("sleeping", "off") and not self._busy.locked()

    def _on_initiative(self, kind: str, title: str, body: str) -> None:
        speak = self.voice is not None and self.config.speak_initiatives  # the phone says it too
        self.publish(
            {"type": "initiative", "kind": kind, "title": title, "body": body, "speak": speak}
        )
        if kind == "lien":  # Spectre comes to talk: its words join the conversation
            self.publish({"type": "message", "role": "spectre", "text": body, "channel": "voice"})
        if speak and self.voice_state == "sleeping":
            threading.Thread(target=self._announce, args=(kind, title, body), daemon=True).start()
        self._to_telegram(f"{title}\n{body}" if kind != "lien" else body)
        self._to_devices(title, body)

    def _to_devices(self, title: str, body: str) -> None:
        """A native notification on every subscribed device (in the background)."""
        if self.push.subscriptions():
            threading.Thread(target=self.push.send, args=(title, body), daemon=True).start()

    def _to_telegram(self, text: str) -> None:
        """Also send it to the paired Telegram chats (in the background: never blocks)."""
        if self.config.telegram_notify and self.telegram.chats():
            threading.Thread(target=self.telegram.broadcast, args=(text,), daemon=True).start()

    def _announce(self, kind: str, title: str, body: str) -> None:
        if kind == "lien":
            self.voice.say(body)
            self.voice.trigger()  # then listen, so the user can simply answer
        else:
            self.voice.say(f"{title}. {body}")

    def _max_id(self, table: str) -> int:
        row = self.db.one(f"SELECT COALESCE(MAX(id), 0) AS n FROM {table}")  # noqa: S608 - fixed
        return int(row["n"]) if row else 0

    def _config_stamp(self) -> float:
        try:
            return (self.root / "config.json").stat().st_mtime
        except OSError:
            return 0.0

    def reload_config(self) -> bool:
        """Pick up `config.json` changed by another process (the brain's `set_model` tool runs
        in the MCP server); the same config object is shared by the brain and proactivity."""
        stamp = self._config_stamp()
        if stamp == self._config_mtime:
            return False
        self._config_mtime = stamp
        fresh = AssistantConfig.load(self.root)
        self.config.__dict__.update(fresh.__dict__)
        self._apply_config()
        self.publish({"type": "config", "brain_model": self.config.brain_model})
        return True

    def _apply_config(self) -> None:
        cfg = self.config
        self.gate.auto_max_level = cfg.auto_max_level
        self.gate.per_minute = cfg.actions_per_minute
        self.gate.per_day = cfg.actions_per_day
        self.missions.model = cfg.mission_model
        self.missions.lead_model = cfg.planner_model or cfg.brain_model
        self.missions.verifier_model = cfg.verifier_model
        self.missions.fallbacks = list(cfg.fallback_models)
        self.missions.parallel = cfg.mission_parallel
        self.missions.learn = cfg.learn_from_missions
        self.missions.learning_model = cfg.learning_model
        self.missions.earned_autonomy = cfg.earned_autonomy

    def poll_changes(self) -> None:
        """Publish approvals/initiatives created elsewhere (e.g. by the MCP tool process)."""
        self.reload_config()
        self._meeting_request()
        for table, kind in (("approvals", "approval"), ("initiatives", "initiative_row")):
            rows = self.db.all(
                f"SELECT * FROM {table} WHERE id > ? ORDER BY id",  # noqa: S608 - fixed names
                (self._seen[table],),
            )
            for row in rows:
                self._seen[table] = row["id"]
                self.publish({"type": kind, "row": row})
                if kind == "approval":
                    self._to_devices(
                        "Spectre attend ta validation",
                        f"#{row['id']} {row['tool']} : {row['reason']}",
                    )
                    self._to_telegram(
                        f"Spectre attend ta validation (#{row['id']}, {row['tool']}) : "
                        f"{row['reason']}.\nRéponds /approve {row['id']} ou /deny {row['id']}."
                    )

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

    def attach(self, name: str, data: bytes) -> Event:
        """Keep a file the user joins to a message (paperclip, paste, drop) in the workspace,
        where Spectre reads it whole when the message is sent."""
        from spectre import attachments

        path = attachments.store(self.cli.workspace / ATTACHMENTS, name, data)
        return {
            "id": path.name,
            "name": attachments.safe_name(name),
            "kind": attachments.kind(path.name),
            "size": len(data),
        }

    def joined(self, ids: list[str]) -> str:
        """What a message says of its attached files: where Spectre reads each one, and the
        text of the short text ones (an engine without file reading still sees it)."""
        from spectre import attachments

        folder = self.cli.workspace / ATTACHMENTS
        lines = []
        for raw in ids[:MAX_ATTACHMENTS]:
            path = folder / Path(raw).name
            if not path.is_file():
                raise ValueError(f"pièce jointe introuvable : {raw}")
            name = path.name.split("-", 1)[-1]
            kind = attachments.kind(path.name)
            line = (
                f"[Pièce jointe : {name} ({kind}, {path.stat().st_size // 1024 + 1} Ko) — "
                f"lis-la avec l'outil Read : {ATTACHMENTS}/{path.name}]"
            )
            if kind == "texte" and path.stat().st_size <= INLINE_TEXT:
                line += f"\n--- {name} ---\n{attachments.decode(path.read_bytes()).strip()}"
            lines.append(line)
        return "\n".join(lines)

    def chat(self, text: str, channel: str = "text", attached: list[str] | None = None) -> str:
        """One turn with the brain (serialised: Spectre answers one thing at a time)."""
        text = text.strip()
        if attached:
            text = f"{text or 'Regarde ce que je te joins.'}\n\n{self.joined(attached)}"
        if not text:
            raise ValueError("message vide")
        self.publish({"type": "message", "role": "user", "text": text, "channel": channel})
        if text.split(maxsplit=1)[0].lower() == "/model":
            answer = self.model_command(text)
            self.publish({"type": "message", "role": "spectre", "text": answer, "channel": channel})
            return answer
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
        from spectre.assistant.learning import mission_changes

        rows = self.db.all(
            "SELECT id, ts, goal, status, steps, report, error, updated_at FROM missions "
            "ORDER BY id DESC LIMIT 30"
        )
        for row in rows:  # file changes a restore point can undo
            row["changes"] = len(mission_changes(self.db, row["id"]))
        return rows

    def rollback_mission(self, mission_id: int) -> str:
        """The user's own click: undo the mission's file changes (audited)."""
        from spectre.assistant import actions

        result = actions.rollback_mission(self.ctx, mission_id)
        self.gate.record(
            "rollback_mission",
            {"mission_id": mission_id},
            Level.DESTRUCTIVE,
            "overwrite_file",
            "user",
            result,
        )
        return result

    # ---- learning -------------------------------------------------------------------------------

    def learning(self) -> Learning:
        return Learning(self.db, self.root)

    def learning_state(self) -> Event:
        learning = self.learning()
        return {
            "proposals": learning.proposals(),
            "skills": learning.skills(),
            "archived": learning.skills(archived=True),
            "learn": self.config.learn_from_missions,
        }

    def learning_decide(self, proposal_id: int, approve: bool) -> Event:
        learning = self.learning()
        row = learning.approve(proposal_id) if approve else learning.reject(proposal_id)
        self.gate.record(
            "skill_proposal",
            {"id": proposal_id, "name": row["name"]},
            Level.WRITE,
            "skill",
            "user",
            row["status"],
        )
        return row

    def learning_skill(self, name: str, action: str) -> Event:
        learning = self.learning()
        if action == "pin":
            learning.pin(name, True)
        elif action == "unpin":
            learning.pin(name, False)
        elif action == "archive":
            learning.archive(name)
        elif action == "restore":
            learning.restore(name)
        else:
            raise KeyError(action)
        return self.learning_state()

    def search(self, query: str) -> list[Event]:
        from spectre.assistant.learning import search_history

        return search_history(self.db, query, 20)

    def start_mission(self, goal: str, kind: str = "mission", agent: str = "") -> str:
        args = {"goal": goal, "kind": kind} | ({"agent": agent} if agent else {})
        return tools.execute(self.gate, self.ctx, "start_mission", args)

    # ---- technical department ---------------------------------------------------------------

    def dev(self, company_id: int) -> Event:
        from spectre.assistant.devteam import DevTeam

        company = Companies(self.db).get(company_id)
        devteam = DevTeam(self.db, self.root)
        return {"config": devteam.config(company["id"]), "jobs": devteam.jobs(company["id"])}

    def dev_configure(self, company_id: int, data: dict[str, Any]) -> Event:
        """The user's own form: configure the repository (audited)."""
        from spectre.assistant import actions
        from spectre.assistant.devteam import DevTeam

        company = Companies(self.db).get(company_id)
        repo = actions.resolve_path(self.ctx, str(data.get("path", "")))
        setup = DevTeam(self.db, self.root).configure(
            company["id"],
            str(repo),
            str(data.get("test_command", "")),
            str(data.get("base_branch", "")),
        )
        self.gate.record("set_dev_repo", setup, Level.CRITICAL, "dev_config", "user", "")
        return setup

    def dev_action(self, job_id: int, action: str) -> str:
        """The user's own click: open the PR or discard the work (audited)."""
        from spectre.assistant.devteam import DevTeam

        devteam = DevTeam(self.db, self.root)
        if action == "pr":
            result = devteam.open_pr(job_id)
            self.gate.record(
                "open_pr", {"job": job_id}, Level.EXTERNAL, "external_send", "user", result
            )
        elif action == "discard":
            result = devteam.discard(job_id)
            self.gate.record(
                "discard_dev_job", {"job": job_id}, Level.DESTRUCTIVE, "delete_file", "user", result
            )
        else:
            raise KeyError(action)
        self.publish({"type": "company"})
        return result

    # ---- meetings ------------------------------------------------------------------------------

    def _meeting_stt(self) -> Any:
        """The speech engine: the voice loop's, or a local one loaded on first use."""
        if self.voice is not None and getattr(self.voice, "stt", None) is not None:
            return self.voice.stt
        if self._stt is None:
            try:
                from spectre.assistant.voice.engines import WhisperSTT
            except ImportError as exc:
                raise MeetingError(
                    "la reconnaissance vocale n'est pas installée (uv sync --extra voice)"
                ) from exc
            self._stt = WhisperSTT(self.config.stt_model, self.config.language)
        return self._stt

    def _meeting_mic(self) -> Any:  # pragma: no cover - real microphone
        from spectre.assistant.voice.engines import Microphone, pick_microphone

        return Microphone(device=pick_microphone(self.config.mic_device)[0])

    def _voice_muted(self, muted: bool) -> None:
        """Spectre must not answer « Spectre » said during a meeting."""
        mic = getattr(self.voice, "mic", None)
        muted_event = getattr(mic, "muted", None)
        if muted_event is not None:
            (muted_event.set if muted else muted_event.clear)()

    def _meeting_done(self, kind: str, title: str, body: str) -> None:
        self._voice_muted(False)
        self.proactive.add_initiative(kind, title, body)
        self.publish({"type": "meeting"})

    def meetings(self) -> list[Event]:
        return Meetings(self.db).all()

    def meeting(self, meeting_id: int) -> Event:
        return Meetings(self.db).get(meeting_id) | {"recording": self.recorder.recording}

    def meeting_start(self, title: str = "", company: str = "") -> Event:
        company_id = Companies(self.db).get(company)["id"] if company.strip() else None
        self._voice_muted(True)  # before listening: a short meeting may end at once
        try:
            meeting = self.recorder.start(title, company_id)
        except Exception:
            self._voice_muted(False)
            raise
        self.gate.record("meeting", {"id": meeting["id"]}, Level.WRITE, "meeting", "user", "start")
        self.publish({"type": "meeting"})
        return meeting

    def meeting_stop(self) -> Event:
        meeting_id = self.recorder.stop()
        self._voice_muted(False)
        self.publish({"type": "meeting"})
        return Meetings(self.db).get(int(meeting_id or 0))

    def meeting_upload(self, data: bytes, title: str = "", company: str = "") -> Event:
        company_id = Companies(self.db).get(company)["id"] if company.strip() else None
        meeting = self.recorder.transcribe_file(data, title, company_id)
        self.publish({"type": "meeting"})
        return meeting

    def _meeting_request(self) -> None:
        """A start or stop asked by the brain's `meeting` tool (another process)."""
        raw = self.db.get_kv(REQUEST_KV)
        if not raw:
            return
        self.db.set_kv(REQUEST_KV, "")
        try:
            request = json.loads(raw)
            if request.get("action") == "start":
                company = str(request.get("company") or "")
                self.meeting_start(str(request.get("title") or ""), company)
            elif request.get("action") == "stop" and self.recorder.recording:
                self.meeting_stop()
        except (MeetingError, ValueError) as exc:
            self.proactive.add_initiative("reunion", "Réunion impossible", str(exc))

    # ---- Telegram ----------------------------------------------------------------------------

    def _telegram_reply(self, text: str, chat_id: int) -> str:
        """A message from a paired Telegram chat: a command, or a turn with the brain."""
        command, _, rest = text.partition(" ")
        command = command.lower().split("@")[0]
        try:
            if command in ("/approve", "/valider") and rest.strip().lstrip("#").isdigit():
                return f"Validé : {self.approve(int(rest.strip().lstrip('#')))}"
            if command in ("/deny", "/refuser") and rest.strip().lstrip("#").isdigit():
                self.deny(int(rest.strip().lstrip("#")), "refusé depuis Telegram")
                return "Refusé."
        except (KeyError, ValueError) as exc:
            return f"Impossible : {exc}"
        if command == "/status":
            s = self.status()
            return (
                f"Cerveau : {s['brain_label']}. Validations en attente : {s['pending_approvals']}. "
                f"Missions en cours : {s['missions_running']}."
            )
        return self.chat(text, "telegram")

    def telegram_status(self) -> Event:
        return self.telegram.status() | {"notify": self.config.telegram_notify}

    def telegram_token(self, token: str) -> Event:
        """Save the bot token (in the assistant's .env, never shown back) and start the bot."""
        save_token(self.root, token)
        self.telegram.stop()
        self.telegram.connect()
        self.telegram.start()
        self.gate.record("telegram_token", {}, Level.CRITICAL, "external_send", "user", "jeton")
        return self.telegram_status()

    def telegram_pair(self) -> Event:
        if not self.telegram.token:
            raise ValueError("ajoute d'abord le jeton du bot (donné par @BotFather)")
        code = self.telegram.pairing_code()
        return self.telegram_status() | {"code": code}

    def telegram_unlink(self, chat_id: int) -> Event:
        self.telegram.unlink(chat_id)
        return self.telegram_status()

    # ---- routines and webhooks -------------------------------------------------------------

    def routines(self) -> list[Event]:
        return Routines(self.db).all()

    def webhooks_list(self, base: str = "") -> list[Event]:
        """The webhooks, with their URL; secrets are shown only in part."""
        return [
            w | {"secret": f"{w['secret'][:6]}…", "url": f"{base}/hooks/{w['name']}"}
            for w in self.webhooks.all()
        ]

    def create_webhook(self, data: dict[str, Any], base: str = "") -> Event:
        """Create a webhook from the interface; its full secret is returned this once."""
        events = data.get("events") or []
        if isinstance(events, str):
            events = [e for e in events.replace(";", ",").split(",") if e.strip()]
        row = self.webhooks.create(
            str(data.get("name", "")),
            str(data.get("source", "generic")),
            action=str(data.get("action", "notify")),
            instructions=str(data.get("instructions", "")),
            events=[str(e) for e in events],
            secret=str(data.get("secret", "")),
            agent=str(data.get("agent", "")),
        )
        self.gate.record(
            "create_webhook", {"name": row["name"]}, Level.WRITE, "webhook", "user", ""
        )
        return row | {"url": f"{base}/hooks/{row['name']}"}

    def delete_webhook(self, name: str) -> Event:
        row = self.webhooks.delete(name)
        self.gate.record("delete_webhook", {"name": name}, Level.DESTRUCTIVE, "webhook", "user", "")
        return {"name": row["name"]}

    def hook(self, name: str, headers: dict[str, str], body: bytes) -> tuple[int, str]:
        """A call on /hooks/<name>: (HTTP status, message)."""
        try:
            done = self.webhooks.receive(name, headers, body, self.proactive.add_initiative)
        except Rejected as exc:
            self.db.log_event("webhook_refused", "web", f"{name}: {exc.reason}")
            return exc.status, exc.reason
        return 200, done

    # ---- earned autonomy and costs -----------------------------------------------------------

    def trust_board(self) -> list[Event]:
        from spectre.assistant.trust import Trust

        return Trust(self.db).agents()

    def costs(self, company_id: int | None = None, days: int = 30) -> Event:
        from spectre.assistant import spend

        return spend.summary(self.db, datetime.now().astimezone(), company_id, days)

    # ---- board and experiments ----------------------------------------------------------------

    def decisions(self, company_id: int) -> Event:
        from spectre.assistant.board import Board, memo
        from spectre.assistant.experiments import Experiments, describe

        company = Companies(self.db).get(company_id)
        rows = Board(self.db, self.root).all(company["id"])
        experiments = Experiments(self.db, self.root).all(company["id"])
        return {
            "decisions": [
                d | {"memo": memo(d, company["name"]) if d["status"] != "deliberating" else ""}
                for d in rows
            ],
            "experiments": [e | {"text": describe(e)} for e in experiments],
            "metrics": sorted(self.saas().kpis(company["id"], datetime.now().astimezone())),
        }

    # ---- SaaS monitoring -------------------------------------------------------------------------

    def saas(self) -> Saas:
        return Saas(self.db, self.root)

    def saas_dashboard(self, company_id: int) -> Event:
        Companies(self.db).get(company_id)
        return self.saas().dashboard(company_id, datetime.now().astimezone())

    def saas_add_source(self, company_id: int, data: dict[str, Any]) -> Event:
        """Add a source; its key goes to the assistant's .env and is never sent back."""
        Companies(self.db).get(company_id)
        keys = ("url", "table", "date_column", "repo", "fields", "address", "coins", "currency")
        config: dict[str, Any] = {k: data[k] for k in keys if k in data}
        source = self.saas().add_source(
            company_id,
            str(data.get("kind", "")),
            str(data.get("name", "")),
            config,
            str(data.get("key", "")),
        )
        self.gate.record(
            "saas_source",
            {"kind": source["kind"], "name": source["name"]},
            Level.WRITE,
            "company",
            "user",
            "",
        )
        threading.Thread(target=self.saas_check, args=(source["id"],), daemon=True).start()
        return {k: v for k, v in source.items() if k != "key_env"}

    def saas_check(self, source_id: int) -> Event:
        """Collect one source now (and check its company's alerts)."""
        saas = self.saas()
        source = saas.source(source_id)
        now = datetime.now().astimezone()
        found = saas.check(source, now)
        saas.alerts_check(source["company_id"], now, self.proactive.add_initiative)
        self.publish({"type": "company"})
        return {"metrics": found, "error": saas.source(source_id)["last_error"]}

    def saas_report_routine(self, company_id: int) -> str:
        """The weekly report, as a Monday 9 o'clock routine."""
        found = Companies(self.db).get(company_id)
        return self.act(
            "create_routine",
            {
                "name": f"Rapport hebdo {found['name']}"[:60],
                "schedule": "chaque lundi à 9h",
                "kind": "question",
                "prompt": (
                    f"Fais le rapport hebdomadaire de l'entreprise « {found['name']} » : lis "
                    "saas_report et company_board, commente les tendances en chef d'entreprise "
                    "(chiffres à l'appui), signale les risques et propose trois actions concrètes."
                ),
            },
        )

    # ---- companies: org chart and task board --------------------------------------------------

    def act(self, tool: str, args: dict[str, Any]) -> str:
        """A click in the interface, through the gate and the audit like Spectre's own calls."""
        result = tools.execute(self.gate, self.ctx, tool, args)
        if result.startswith(("ÉCHEC", "REFUSÉ")):
            raise ValueError(result.split(" : ", 1)[-1])
        self.publish({"type": "company"})
        return result

    def companies(self) -> list[Event]:
        return Companies(self.db).all()

    def company(self, company_id: int) -> Event:
        """A company with its posts, its tasks and who can hold a post."""
        companies = Companies(self.db)
        found = companies.get(company_id)
        posts = companies.posts(found["id"])
        agents = [{"key": key, "name": AGENT_NAMES[key]} for key in AGENT_ORDER]
        agents += [
            {"key": f"agent:{a['id']}", "name": a["name"]} for a in CustomAgents(self.db).list()
        ]
        missions = {
            m["id"]: m["status"]
            for m in self.db.all("SELECT id, status FROM missions ORDER BY id DESC LIMIT 200")
        }
        return {
            "company": found,
            "departments": [
                {
                    "key": key,
                    "label": label,
                    "agent": posts[key],
                    "agent_label": companies.agent_label(posts[key]),
                }
                for key, (label, _) in DEPARTMENTS.items()
            ],
            "tasks": [
                t | {"mission_status": missions.get(t["mission_id"] or 0, "")}
                for t in companies.tasks(found["id"])
            ],
            "ready": [t["id"] for t in companies.ready(found["id"])],
            "agents": agents,
            "parallel": self.missions.parallel,
            "active": self.missions.active(),
        }

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
            "power": self.power(),
        }

    def agents(self) -> Event:
        """Every agent by name: Spectre and its sub-agents, then the writing pipeline."""
        cfg = self.config
        labels = {"chatgpt": "Codex", "mistral": "Vibe", "cursor": "Cursor"}
        labels |= {"antigravity": "Antigravity"}

        def engine_of(key: str) -> str:
            if key in HOSTED_AGENTS:
                return engines.resolve(cfg, key)
            if key not in labels:
                return f"{model_label(key)} · Claude Code"
            moved = cfg.agent_engines.get(key, "")
            if moved:
                return f"{moved} (au lieu de {labels[key]})"
            model = str(getattr(cfg, team.MODEL_SETTING[key]))
            return f"{labels[key]}{f' ({model})' if model else ''}"

        assistant = [
            {
                "key": key,
                "name": AGENT_NAMES[key],
                "engine": engine_of(key),
                "role": AGENT_ROLES[key],
                "available": team.available(cfg, key),
                "default": key == cfg.mission_model,
            }
            for key in AGENT_ORDER
        ]
        redaction = [
            {"key": spec.name, "name": spec.name.capitalize(), "engine": model_label(spec.model)}
            for spec in DEFAULT_SPECS.values()
        ]
        created = [
            {
                "key": f"agent:{a['id']}",
                "id": a["id"],
                "name": a["name"],
                "engine": self._engine_label(a["engine"], assistant),
                "role": a["role"],
                "instructions": a["instructions"],
            }
            for a in CustomAgents(self.db).list()
        ]
        return {"assistant": assistant, "created": created, "redaction": redaction}

    def _engine_label(self, engine: str, assistant: list[Event]) -> str:
        provider, model = split_ref(engine)
        if not provider:
            return next((x["engine"] for x in assistant if x["key"] == engine), engine)
        found = self.providers.all().get(provider)
        return f"{model} · {found.label if found else provider}"

    def create_agent(self, data: dict[str, Any]) -> str:
        """Create an agent from the interface, through the gate like Spectre would."""
        args = {k: str(data.get(k, "")) for k in ("name", "engine", "role", "instructions")}
        result = tools.execute(self.gate, self.ctx, "create_agent", args)
        if result.startswith("ÉCHEC"):
            raise ValueError(result.removeprefix("ÉCHEC : "))
        return result

    def delete_agent(self, agent_id: int) -> Event:
        """The user removes a created agent (their own click: no approval needed)."""
        agent = CustomAgents(self.db).delete(f"agent:{agent_id}")
        self.gate.record(
            "delete_agent", {"id": agent_id}, Level.DESTRUCTIVE, "agent", "user", agent["name"]
        )
        return agent

    def update_config(self, changes: dict[str, Any]) -> Event:
        changes = dict(changes)
        probe = AssistantConfig()
        parallel = changes.get("mission_parallel")
        if parallel is not None and (not isinstance(parallel, int) or not 1 <= parallel <= 4):
            raise ValueError("missions en parallèle : de 1 à 4")
        for key, value in changes.items():  # engines are checked like `set_model` would
            if key in ROLES and isinstance(value, str):
                engines.assign(probe, self.providers, key, value)
                changes[key] = getattr(probe, key)
            elif key == "fallback_models" and isinstance(value, list):
                engines.set_fallbacks(probe, self.providers, [str(v) for v in value])
                changes[key] = probe.fallback_models
        self.config.update(changes)
        self.config.save(self.root)
        self._config_mtime = self._config_stamp()
        self._apply_config()
        return self.config.__dict__.copy()

    # ---- engines (LLM providers) -------------------------------------------------------------

    def models(self) -> Event:
        """Each role's engine, the fallback chain and the providers (never their keys)."""
        return {
            "roles": engines.roles(self.config),
            "fallbacks": list(self.config.fallback_models),
            "cli": ["opus", "sonnet", "haiku", "chatgpt", "mistral"],
            "providers": self.providers.describe(),
        }

    def provider_models(self, provider: str) -> Event:
        online, models = self.providers.listing(provider)
        return {"provider": provider, "models": models, "online": online}

    def set_engine(self, data: dict[str, Any]) -> Event:
        """Switch a role's engine, or replace the fallback chain, from the interface."""
        if "fallbacks" in data:
            raw = data["fallbacks"]
            items = raw if isinstance(raw, list) else str(raw).replace(";", ",").split(",")
            self.update_config({"fallback_models": [str(i) for i in items]})
        else:
            role = resolve_role(str(data.get("role", "")))
            if not role:
                raise ValueError("rôle inconnu")
            self.update_config({role: str(data.get("engine", "")).strip()})
        return self.models()

    def model_command(self, text: str) -> str:
        """Hermes-style `/model`: show the engines, or switch one, without asking the brain.
        `/model` · `/model <engine>` (the brain) · `/model <role> <engine>` ·
        `/model secours <engine>, <engine>` (empty = none)."""
        args = text.split()[1:]
        try:
            if not args:
                return engines.summary(self.config, self.providers)
            if args[0].lower() in ("secours", "fallback", "fallbacks"):
                self.set_engine({"fallbacks": " ".join(args[1:])})
                return "Moteurs de secours : " + (", ".join(self.config.fallback_models) or "aucun")
            if len(args) == 1:
                role, engine = "brain_model", args[0]
            else:
                role, engine = resolve_role(args[0]), " ".join(args[1:])
                if not role:
                    raise ProviderError(
                        f"rôle inconnu « {args[0]} » : cerveau, mission, verificateur ou "
                        "planificateur"
                    )
            self.set_engine({"role": role, "engine": engine})
        except (ProviderError, ValueError) as exc:
            return f"Impossible : {exc}"
        value = getattr(self.config, role) or "le cerveau"
        return f"C'est fait : {ROLES[role].split(' :')[0]} sur {value}."

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
        return {"heard": text, "reply": reply, "audio": self.render_speech(reply)}

    # ---- the team and its video call -------------------------------------------------------

    def team(self) -> Event:
        mine, alive = team.portraits(self.root), team.clips(self.root)
        agents = team.members(self.db, self.config)
        for agent in agents:
            agent["portrait"] = agent["key"].replace(":", "-") in mine
            agent["clips"] = (
                alive.get(agent["key"].replace(":", "-"), []) if agent["portrait"] else []
            )
        return {"agents": agents, "voices": team.VOICES}

    def generate_portrait(self, key: str) -> Event:
        """Launch a realistic portrait of an agent (ComfyUI); saved when it is ready."""
        from spectre.assistant import media

        studio = media.Studio(self.db, self.config, self.root)
        job = studio.submit(
            f"portrait:{key}", media.portrait_prompt(key), width=512, height=640, agent="chatgpt"
        )
        return {"minutes": job["minutes"]}

    def team_portrait(self, key: str, data: bytes | None) -> Event:
        """Set (bytes) or remove (None) the user's own picture of an agent."""
        if data is None:
            team.delete_portrait(self.root, key)
        else:
            team.save_portrait(self.root, key, data)
        return {"ok": True}

    def team_change(self, key: str, data: dict[str, Any]) -> Event:
        """Change an agent's engine, its model in its own tool, or its voice on the call."""
        changes = team.change(self.db, self.config, self.providers, key, data)
        if changes:
            self.update_config(changes)
        return {"agents": team.members(self.db, self.config)}

    def team_models(self, key: str) -> Event:
        from spectre.assistant import cli_agents

        return {"key": key, "models": cli_agents.models(key, self.config)}

    def team_details(self, key: str) -> Event:
        return team.details(self.db, self.config, key, self.root)

    def call_state(self, since: int, since_event: int) -> Event:
        state = call.snapshot(self.db, since, since_event)
        mine, alive = team.portraits(self.root), team.clips(self.root)
        for agent in state["agents"]:  # the portrait the user chose: drawn look or picture
            look = self.config.agent_looks.get(agent["key"], {})
            agent["look"] = look
            agent["gender"] = look.get("g", agent["gender"])
            agent["portrait"] = agent["key"].replace(":", "-") in mine
            agent["clips"] = (
                alive.get(agent["key"].replace(":", "-"), []) if agent["portrait"] else []
            )
        return state

    def call_standup(self) -> Event:
        return {"lines": call.standup(self.db)}

    def call_recap(self, mission: int | None, hours: float) -> Event:
        return {"markdown": call.recap(self.db, mission=mission, hours=hours)}

    def call_tree(self) -> Event:
        return call.tree(self.db)

    def call_board(self) -> Event:
        roots = sessions.Roots.default(self.root)
        return {"missions": call.board(self.db), "sessions": sessions.scan(roots)}

    def call_replay(self, mission: int) -> Event:
        return call.replay(self.db, mission)

    def call_session(self, tool: str, sid: str) -> Event:
        found = sessions.timeline(sessions.Roots.default(self.root), tool, sid)
        if found is None:
            raise KeyError(sid)
        return found

    def speak_as(self, key: str, text: str) -> str:
        """An agent's own voice saying `text` (base64 WAV), clear and without effect; "" when
        the local voices are not installed (the page then uses the browser's voices)."""
        text = text.strip()[:600]
        if not text:
            return ""
        gender = next((m["gender"] for m in call.members(self.db) if m["key"] == key), "m")
        gender = str(self.config.agent_looks.get(key, {}).get("g", gender))
        voice, pace = team.voice_of(self.config, key, gender)
        model, speaker, _label, _gender = team.VOICES[voice]
        if not (self.root / "models" / "piper" / f"{model}.onnx").is_file():
            return ""  # never a download during a call: the browser speaks instead
        cache = self.__dict__.setdefault("_call_voices", {})
        try:
            if (voice, pace) not in cache:
                from spectre.assistant.voice.engines import PiperTTS

                cache[(voice, pace)] = PiperTTS(self.root / "models", model, speaker, "aucun", pace)
            rendered = cache[(voice, pace)].render(text)
        except Exception:  # noqa: BLE001 - no Piper here: the browser speaks instead
            return ""
        return base64.b64encode(to_wav(*rendered)).decode("ascii") if rendered else ""

    def render_speech(self, text: str) -> str:
        """Spectre's voice saying `text`, as a base64 WAV for another device (the phone) to
        play: typed replies and initiatives; "" when nothing can be rendered."""
        if self.voice is None:
            raise ValueError("la voix n'est pas active (lance Spectre avec la voix)")
        render = getattr(self.voice.tts, "render", None)  # the Windows fallback voice cannot
        rendered = render(text) if text.strip() and render else None
        return base64.b64encode(to_wav(*rendered)).decode("ascii") if rendered else ""

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
        self.db.log_event("presence", "camera", f"{name} est là")
        # writing the line takes a few seconds: not on the camera's thread
        threading.Thread(target=self.welcome, args=(name, away_s), daemon=True).start()

    def welcome(self, name: str, away_s: float) -> str:
        """Greet once a day as suits the hour; afterwards (a return, a restart) start the
        conversation instead, never with the same words. Then listen, so they can answer."""
        situation = (
            f"{name} revient devant toi après {int(away_s // 60)} minutes d'absence"
            if away_s
            else f"tu viens de voir {name} arriver devant toi (ou tu viens d'être rallumé)"
        )
        now = datetime.now().astimezone()
        text = greetings.compose(self.cli, self.db, now, name, situation)
        self.db.set_kv("befriend_opener", f"{time.time()}|{text}")  # the brain will know it
        speak = self.voice is not None and self.voice_state == "sleeping"
        self.publish({"type": "arrival", "name": name, "text": text, "speak": speak})
        if speak:
            self.voice.say(text)
            self.voice.trigger()
        return text

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
