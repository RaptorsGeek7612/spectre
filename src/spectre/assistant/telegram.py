"""Telegram gateway: talk to Spectre from Telegram, and receive its notifications there.

Long polling (`getUpdates`): no public address is needed. The bot token comes from the
environment or the assistant folder's `.env` (`TELEGRAM_BOT_TOKEN`), never from the repository.
Only paired chats are served: Spectre shows a pairing code (valid 10 minutes) that the user
sends to the bot (`/start CODE`). Any other chat is ignored, without an answer.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spectre.assistant.db import Database
from spectre.assistant.providers import read_env_file

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TOKEN = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")
API = "https://api.telegram.org/bot{token}/{method}"
PAIR_TTL_S = 600
MAX_CHATS = 5
CHUNK = 4000
CHATS_KV = "telegram_chats"
PAIR_KV = "telegram_pair"
HELP = (
    "Écris-moi comme dans Spectre. Commandes : /approve N et /deny N pour une action en "
    "attente, /model pour les moteurs, /status pour l'état."
)

Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


def call_api(
    url: str, params: dict[str, Any], timeout: float
) -> dict[str, Any]:  # pragma: no cover
    """POST to the Bot API (real network)."""
    request = urllib.request.Request(
        url, data=json.dumps(params).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        data = json.loads(exc.read().decode("utf-8", "replace") or "{}")
    return data if isinstance(data, dict) else {}


def read_token(root: Path, environ: dict[str, str] | None = None) -> str:
    import os

    source = os.environ if environ is None else environ
    return source.get(TOKEN_ENV, "") or read_env_file(root / ".env").get(TOKEN_ENV, "")


def save_token(root: Path, token: str) -> None:
    """Write the token into the assistant folder's `.env` (replacing an older one)."""
    token = token.strip()
    if not TOKEN.fullmatch(token):
        raise ValueError("jeton Telegram invalide (format 123456789:ABC..., donné par @BotFather)")
    path = root / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    kept = [
        ln for ln in lines if not ln.strip().removeprefix("export ").startswith(f"{TOKEN_ENV}=")
    ]
    root.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([*kept, f"{TOKEN_ENV}={token}"]) + "\n", encoding="utf-8")


class Telegram:
    """The bot: pairing, incoming messages, outgoing notifications."""

    def __init__(
        self,
        root: Path,
        db: Database,
        reply: Callable[[str, int], str],
        *,
        transport: Transport = call_api,
        environ: dict[str, str] | None = None,
    ) -> None:
        self.root = root
        self.db = db
        self.reply = reply  # (text, chat_id) -> Spectre's answer
        self.transport = transport
        self.environ = environ
        self.offset = 0
        self.username = ""
        self.error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def token(self) -> str:
        return read_token(self.root, self.environ)

    def api(self, method: str, wait: float = 15.0, **params: Any) -> dict[str, Any]:
        data = self.transport(API.format(token=self.token, method=method), params, wait)
        if not data.get("ok"):
            raise ConnectionError(str(data.get("description") or "Telegram ne répond pas"))
        return data

    # ---- lifecycle ------------------------------------------------------------------------------

    def start(self) -> bool:
        """Start polling in the background (when a token is set); False otherwise."""
        if not self.token or (self._thread and self._thread.is_alive()):
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="spectre-telegram", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:  # pragma: no cover - thread wrapper around poll
        while not self._stop.is_set():
            try:
                self.poll(timeout=25)
                self.error = ""
            except (OSError, ValueError) as exc:
                self.error = str(exc)[:200]
                self._stop.wait(15)

    def connect(self) -> str:
        """Check the token (`getMe`); returns the bot's @name."""
        self.username = str(self.api("getMe")["result"].get("username", ""))
        return self.username

    # ---- chats and pairing ----------------------------------------------------------------------

    def chats(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.db.get_kv(CHATS_KV) or "[]")
        except ValueError:
            data = []
        return [c for c in data if isinstance(c, dict) and "id" in c]

    def _save_chats(self, chats: list[dict[str, Any]]) -> None:
        self.db.set_kv(CHATS_KV, json.dumps(chats, ensure_ascii=False))

    def unlink(self, chat_id: int) -> None:
        self._save_chats([c for c in self.chats() if c["id"] != int(chat_id)])

    def pairing_code(self, now: float | None = None) -> str:
        """A new code to send to the bot, valid PAIR_TTL_S."""
        now = time.time() if now is None else now
        code = f"{secrets.randbelow(10**6):06d}"
        self.db.set_kv(PAIR_KV, f"{code}|{now + PAIR_TTL_S}")
        return code

    def pending_code(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        code, _, until = self.db.get_kv(PAIR_KV).partition("|")
        try:
            return code if code and float(until) > now else ""
        except ValueError:
            return ""

    def _pair(self, chat: dict[str, Any], text: str, now: float) -> bool:
        code = self.pending_code(now)
        sent = re.sub(r"^/start\s*", "", text.strip())
        if not code or not secrets.compare_digest(sent, code):
            return False
        chats = self.chats()
        if len(chats) >= MAX_CHATS:
            return False
        name = " ".join(str(chat.get(k, "")) for k in ("first_name", "last_name")).strip()
        chats.append({"id": int(chat["id"]), "name": name or str(chat.get("username", ""))})
        self._save_chats(chats)
        self.db.set_kv(PAIR_KV, "")
        return True

    # ---- messages -------------------------------------------------------------------------------

    def poll(self, timeout: int = 25, now: float | None = None) -> int:
        """Fetch and handle new messages; returns how many were handled."""
        updates = self.api(
            "getUpdates",
            timeout + 10,
            offset=self.offset,
            timeout=timeout,
            allowed_updates=["message"],
        )["result"]
        handled = 0
        for update in updates:
            self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
            message = update.get("message") or {}
            chat, text = message.get("chat") or {}, str(message.get("text") or "")
            if "id" not in chat or not text.strip():
                continue
            handled += self.handle(chat, text, time.time() if now is None else now)
        return handled

    def handle(self, chat: dict[str, Any], text: str, now: float) -> int:
        chat_id = int(chat["id"])
        if chat.get("type", "private") != "private":
            return 0  # groups are never served
        if chat_id not in {c["id"] for c in self.chats()}:
            if self._pair(chat, text, now):
                self.send(chat_id, f"C'est fait : je te reconnais ici. {HELP}")
                return 1
            return 0  # unknown chat: no answer at all
        if text.strip() in ("/start", "/help", "/aide"):
            self.send(chat_id, HELP)
            return 1
        self.api("sendChatAction", chat_id=chat_id, action="typing")
        self.send(chat_id, self.reply(text.strip(), chat_id))
        return 1

    def send(self, chat_id: int, text: str) -> None:
        text = text.strip() or "(réponse vide)"
        for start in range(0, len(text), CHUNK):
            self.api("sendMessage", chat_id=chat_id, text=text[start : start + CHUNK])

    def broadcast(self, text: str) -> int:
        """Send to every paired chat; returns how many got it (errors are swallowed)."""
        if not self.token:
            return 0
        sent = 0
        for chat in self.chats():
            try:
                self.send(chat["id"], text)
                sent += 1
            except (OSError, ValueError):
                continue
        return sent

    def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.token),
            "running": self.running,
            "username": self.username,
            "error": self.error,
            "chats": self.chats(),
            "code": self.pending_code(),
        }
