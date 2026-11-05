"""Messaging apps: talk to Spectre from Discord, WhatsApp, Signal, Reddit (Telegram: telegram.py).

Same rules as Telegram. Secrets live only in the assistant folder's `.env` and are never shown
back. Only paired contacts are served: Spectre shows a 6-digit code (valid 10 minutes) that the
contact sends from the app itself, and a QR code opens that conversation with the code already
typed. Signal is paired by linking Spectre as a device of the user's own account (QR code), and
then only « Note to self » is served. Anything else is ignored, without an answer.

Each app uses its official API (Discord bot, WhatsApp Cloud API, Reddit OAuth) or, for Signal,
the open source signal-cli (GPL-3.0). Messages received are data: they go through the same
conversation and the same governance as everything else.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spectre.assistant.db import Database
from spectre.assistant.providers import read_env_file, write_env_value

PAIR_TTL_S = 600
MAX_CONTACTS = 5
HELP = (
    "Écris-moi comme dans Spectre. Commandes : /approve N et /deny N pour une action en "
    "attente, /model pour les moteurs, /status pour l'état."
)
USER_AGENT = "Spectre/1.0 (+https://github.com/RaptorsGeek7612/spectre)"

# (method, url, headers, body, timeout) -> parsed JSON
Transport = Callable[[str, str, dict[str, str], bytes | None, float], Any]
Reply = Callable[[str, str], str]  # (text, channel) -> Spectre's answer


def http_json(
    method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> Any:  # pragma: no cover - real network
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise ConnectionError(f"HTTP {exc.code} : {detail}") from exc
    return json.loads(raw.decode("utf-8") or "{}") if raw.strip() else {}


@dataclass(frozen=True)
class Field:
    env: str
    label: str
    secret: bool = True


class Messenger:
    """What every messaging app shares: secrets, pairing, chunked sending, background loop."""

    name = ""
    label = ""
    fields: tuple[Field, ...] = ()
    chunk = 2000
    guide = ""  # how to create the bot / app, shown in the interface
    poll_s = 0.0  # pause between two runs of the loop (0: the run blocks by itself)

    def __init__(
        self,
        root: Path,
        db: Database,
        reply: Reply,
        *,
        transport: Transport = http_json,
        environ: dict[str, str] | None = None,
    ) -> None:
        self.root = root
        self.db = db
        self.reply = reply
        self.transport = transport
        self.environ = environ
        self.error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- secrets ------------------------------------------------------------------------------

    def secret(self, env: str) -> str:
        source = os.environ if self.environ is None else self.environ
        return source.get(env, "") or read_env_file(self.root / ".env").get(env, "")

    @property
    def configured(self) -> bool:
        return all(self.secret(f.env) for f in self.fields)

    def setup(self, values: dict[str, Any]) -> None:
        """Save the given settings in the `.env` (empty values leave the old ones)."""
        for f in self.fields:
            value = str(values.get(f.env, "")).strip()
            if value:
                if "\n" in value or "\r" in value:
                    raise ValueError(f"{f.label} : une seule ligne")
                write_env_value(self.root, f.env, value)
        self.connect()

    def connect(self) -> None:
        """Check the settings with the service (subclasses); raises when they are wrong."""

    # ---- lifecycle ----------------------------------------------------------------------------

    def start(self) -> bool:
        if not self.configured or (self._thread and self._thread.is_alive()):
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=f"spectre-{self.name}", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def restart(self) -> None:
        self.stop()
        if self._thread:
            self._thread.join(timeout=5)
        self.start()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:  # pragma: no cover - thread wrapper around run_once
        with contextlib.suppress(OSError, ValueError, KeyError, RuntimeError):
            self.connect()
        while not self._stop.is_set():
            try:
                self.run_once()
                self.error = ""
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                self.error = str(exc)[:200]
                self._stop.wait(15)
                continue
            if self.poll_s:
                self._stop.wait(self.poll_s)

    def run_once(self) -> None:  # pragma: no cover - overridden where there is a loop
        self._stop.wait(3600)

    # ---- contacts and pairing -----------------------------------------------------------------

    def contacts(self) -> list[dict[str, str]]:
        try:
            data = json.loads(self.db.get_kv(f"{self.name}_contacts") or "[]")
        except ValueError:
            data = []
        return [c for c in data if isinstance(c, dict) and c.get("id")]

    def _save_contacts(self, contacts: list[dict[str, str]]) -> None:
        self.db.set_kv(f"{self.name}_contacts", json.dumps(contacts, ensure_ascii=False))

    def unlink(self, contact_id: str) -> None:
        self._save_contacts([c for c in self.contacts() if c["id"] != str(contact_id)])

    def pairing_code(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        code = f"{secrets.randbelow(10**6):06d}"
        self.db.set_kv(f"{self.name}_pair", f"{code}|{now + PAIR_TTL_S}")
        return code

    def pending_code(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        code, _, until = self.db.get_kv(f"{self.name}_pair").partition("|")
        try:
            return code if code and float(until) > now else ""
        except ValueError:
            return ""

    def _pair(self, contact_id: str, name: str, text: str, now: float) -> bool:
        code = self.pending_code(now)
        words = re.findall(r"\d{6}", text)
        if not code or len(words) != 1 or not secrets.compare_digest(words[0], code):
            return False
        contacts = self.contacts()
        if len(contacts) >= MAX_CONTACTS:
            return False
        contacts.append({"id": str(contact_id), "name": name.strip() or str(contact_id)})
        self._save_contacts(contacts)
        self.db.set_kv(f"{self.name}_pair", "")
        return True

    def handle(self, contact_id: str, name: str, text: str, now: float | None = None) -> str:
        """The answer to send back; empty for an unknown contact (no answer at all)."""
        text = text.strip()
        if not text:
            return ""
        if str(contact_id) not in {c["id"] for c in self.contacts()}:
            if self._pair(str(contact_id), name, text, time.time() if now is None else now):
                return f"C'est fait : je te reconnais ici. {HELP}"
            return ""
        if text.lower() in ("/start", "/help", "/aide", "start", "aide"):
            return HELP
        return self.reply(text, self.name) or "(réponse vide)"

    # ---- sending ------------------------------------------------------------------------------

    def parts(self, text: str) -> list[str]:
        text = text.strip() or "(réponse vide)"
        return [text[i : i + self.chunk] for i in range(0, len(text), self.chunk)]

    def deliver(self, contact_id: str, text: str) -> None:
        for part in self.parts(text):
            self.send_text(contact_id, part)

    def send_text(self, contact_id: str, text: str) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def broadcast(self, text: str) -> int:
        """Send to every paired contact; returns how many got it (errors are swallowed)."""
        if not self.configured:
            return 0
        sent = 0
        for contact in self.contacts():
            try:
                self.deliver(contact["id"], text)
                sent += 1
            except (OSError, ValueError, KeyError, RuntimeError):
                continue
        return sent

    # ---- interface ----------------------------------------------------------------------------

    def pair_link(self, code: str) -> str:
        """The link (and QR code) that opens the conversation, code typed in when possible."""
        return ""

    def status(self) -> dict[str, Any]:
        code = self.pending_code()
        link = self.pair_link(code) if code else ""
        return {
            "name": self.name,
            "label": self.label,
            "configured": self.configured,
            "running": self.running,
            "error": self.error,
            "contacts": self.contacts(),
            "code": code,
            "link": link,
            "qr": _qr(link),
            "guide": self.guide,
            "fields": [
                {
                    "env": f.env,
                    "label": f.label,
                    "secret": f.secret,
                    "set": bool(self.secret(f.env)),
                }
                for f in self.fields
            ],
        }


# ---- Discord ------------------------------------------------------------------------------------


class Discord(Messenger):
    """A Discord bot, in private messages only. The Gateway (WebSocket) brings the messages;
    content of DMs comes without the privileged intent. A bot can only write to someone who
    shares a server with it: the QR code adds it to one of the user's servers."""

    name = "discord"
    label = "Discord"
    fields = (Field("DISCORD_BOT_TOKEN", "Jeton du bot"),)
    chunk = 2000
    guide = (
        "Crée une application sur discord.com/developers/applications, onglet Bot : « Reset "
        "Token », colle le jeton ici. Puis jumelle : scanne le QR pour ajouter le bot à un de tes "
        "serveurs, et envoie-lui le code en message privé."
    )
    API = "https://discord.com/api/v10"
    GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
    INTENTS = 1 << 12  # DIRECT_MESSAGES

    def __init__(
        self,
        root: Path,
        db: Database,
        reply: Reply,
        *,
        transport: Transport = http_json,
        environ: dict[str, str] | None = None,
        connector: Callable[[str], Any] | None = None,
        inline: bool = False,
    ) -> None:
        super().__init__(root, db, reply, transport=transport, environ=environ)
        self.connector = connector or _websocket
        self.inline = inline  # tests: handle messages in the receiving thread
        self.app_id = ""
        self.bot_id = ""

    def rest(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        headers = {
            "Authorization": f"Bot {self.secret('DISCORD_BOT_TOKEN')}",
            "User-Agent": "DiscordBot (https://github.com/RaptorsGeek7612/spectre, 1)",
        }
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        return self.transport(method, self.API + path, headers, body, 20.0)

    def connect(self) -> None:
        self.app_id = str(self.rest("GET", "/oauth2/applications/@me").get("id", ""))
        self.bot_id = str(self.rest("GET", "/users/@me").get("id", ""))

    def pair_link(self, code: str) -> str:
        if not self.app_id:
            return ""
        return (
            f"https://discord.com/oauth2/authorize?client_id={self.app_id}&scope=bot&permissions=0"
        )

    def send_text(self, contact_id: str, text: str) -> None:
        self.rest("POST", f"/channels/{contact_id}/messages", {"content": text})

    def on_message(self, data: dict[str, Any]) -> None:
        author = data.get("author") or {}
        if data.get("guild_id") or author.get("bot") or str(author.get("id")) == self.bot_id:
            return  # servers are never served, nor bots (Spectre included)
        channel = str(data.get("channel_id", ""))
        answer = self.handle(channel, str(author.get("username", "")), str(data.get("content", "")))
        if answer and channel:
            with contextlib.suppress(OSError, ValueError):
                self.rest("POST", f"/channels/{channel}/typing")
            self.deliver(channel, answer)

    def run_once(self) -> None:
        """One Gateway session: Hello, Identify, heartbeats, messages; returns to reconnect."""
        ws = self.connector(self.GATEWAY)
        try:
            hello = json.loads(ws.recv(30))
            interval = float(hello["d"]["heartbeat_interval"]) / 1000
            ws.send(
                json.dumps(
                    {
                        "op": 2,
                        "d": {
                            "token": self.secret("DISCORD_BOT_TOKEN"),
                            "intents": self.INTENTS,
                            "properties": {
                                "os": "windows",
                                "browser": "spectre",
                                "device": "spectre",
                            },
                        },
                    }
                )
            )
            seq: int | None = None
            beat = time.monotonic() + interval * random.random()  # noqa: S311 - jitter
            while not self._stop.is_set():
                try:
                    raw = ws.recv(max(0.05, beat - time.monotonic()))
                except TimeoutError:
                    ws.send(json.dumps({"op": 1, "d": seq}))
                    beat = time.monotonic() + interval
                    continue
                if raw is None:  # closed
                    return
                message = json.loads(raw)
                if message.get("s") is not None:
                    seq = int(message["s"])
                op = message.get("op")
                if op == 0 and message.get("t") == "MESSAGE_CREATE":
                    if self.inline:
                        self.on_message(message["d"])
                    else:  # pragma: no cover - a slow answer must not stop the heartbeats
                        threading.Thread(
                            target=self._safe_message, args=(message["d"],), daemon=True
                        ).start()
                elif op == 1:
                    ws.send(json.dumps({"op": 1, "d": seq}))
                elif op in (7, 9):  # reconnect asked, or invalid session
                    return
        finally:
            with contextlib.suppress(Exception):
                ws.close()

    def _safe_message(self, data: dict[str, Any]) -> None:  # pragma: no cover - thread
        try:
            self.on_message(data)
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            self.error = str(exc)[:200]


class _SyncSocket:  # pragma: no cover - real network
    """websockets' sync client, with `recv(timeout)` raising TimeoutError and errors as OSError."""

    def __init__(self, url: str) -> None:
        from websockets.sync.client import connect

        self._ws = connect(url, open_timeout=20, max_size=2**22, user_agent_header=USER_AGENT)

    def recv(self, timeout: float) -> str | None:
        from websockets.exceptions import ConnectionClosed

        try:
            data = self._ws.recv(timeout=timeout)
        except ConnectionClosed:
            return None
        return data if isinstance(data, str) else data.decode("utf-8")

    def send(self, text: str) -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            self._ws.send(text)
        except ConnectionClosed as exc:
            raise ConnectionError(str(exc)) from exc

    def close(self) -> None:
        self._ws.close()


def _websocket(url: str) -> Any:  # pragma: no cover - real network
    return _SyncSocket(url)


# ---- WhatsApp -----------------------------------------------------------------------------------


class WhatsApp(Messenger):
    """WhatsApp Cloud API (Meta, official). Messages arrive on Spectre's signed webhook
    (`/whatsapp/webhook`, X-Hub-Signature-256 with the app secret): it needs a public HTTPS
    address (Tailscale Funnel). Replies are free within 24 h of the user's last message;
    outside that window WhatsApp refuses free text, so a notification may not get through."""

    name = "whatsapp"
    label = "WhatsApp"
    fields = (
        Field("WHATSAPP_TOKEN", "Jeton d'accès (Meta)"),
        Field("WHATSAPP_PHONE_ID", "Identifiant du numéro (Phone number ID)", secret=False),
        Field("WHATSAPP_APP_SECRET", "Clé secrète de l'appli (App secret)"),
    )
    chunk = 4000
    guide = (
        "Sur developers.facebook.com : crée une appli « Business », ajoute WhatsApp, note le "
        "jeton d'accès permanent, l'identifiant du numéro et la clé secrète de l'appli. Webhook : "
        "l'adresse publique de Spectre (Tailscale Funnel) suivie de /whatsapp/webhook, avec le "
        "jeton de vérification affiché ici, champ « messages »."
    )
    GRAPH = "https://graph.facebook.com/v23.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.number = ""
        self._seen: deque[str] = deque(maxlen=500)

    @property
    def running(self) -> bool:  # the webhook is always listening once set up
        return self.configured

    def start(self) -> bool:  # no loop: only read the bot's number, in the background
        if not self.configured:
            return False
        threading.Thread(target=self._quiet_connect, daemon=True).start()
        return True

    def _quiet_connect(self) -> None:
        try:
            self.connect()
            self.error = ""
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            self.error = str(exc)[:200]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secret('WHATSAPP_TOKEN')}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }

    def connect(self) -> None:
        phone = urllib.parse.quote(self.secret("WHATSAPP_PHONE_ID"), safe="")
        data = self.transport(
            "GET", f"{self.GRAPH}/{phone}?fields=display_phone_number", self._headers(), None, 20.0
        )
        self.number = re.sub(r"\D", "", str(data.get("display_phone_number", "")))

    def verify_token(self) -> str:
        """The token Meta sends back to check the webhook (made once, kept in the `.env`)."""
        token = self.secret("WHATSAPP_VERIFY_TOKEN")
        if not token:
            token = secrets.token_urlsafe(24)
            write_env_value(self.root, "WHATSAPP_VERIFY_TOKEN", token)
        return token

    def verify(self, query: dict[str, str]) -> tuple[int, str]:
        """GET handshake: echo the challenge when Meta shows the right token."""
        if not self.configured:
            return 404, ""
        given = query.get("hub.verify_token", "")
        if query.get("hub.mode") == "subscribe" and secrets.compare_digest(
            given.encode(), self.verify_token().encode()
        ):
            return 200, query.get("hub.challenge", "")
        return 403, ""

    def receive(self, headers: dict[str, str], body: bytes) -> int:
        """POST from Meta: checks the signature, then handles each text message."""
        if not self.configured:
            return 404
        lowered = {k.lower(): v for k, v in headers.items()}
        given = lowered.get("x-hub-signature-256", "").removeprefix("sha256=")
        secret = self.secret("WHATSAPP_APP_SECRET").encode()
        expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
        if not given or not hmac.compare_digest(given, expected):
            return 401
        try:
            data = json.loads(body.decode("utf-8"))
        except ValueError:
            return 400
        for entry in data.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                names = {
                    str(c.get("wa_id")): str((c.get("profile") or {}).get("name", ""))
                    for c in value.get("contacts") or []
                }
                for message in value.get("messages") or []:
                    if message.get("type") != "text" or message.get("id") in self._seen:
                        continue
                    self._seen.append(str(message.get("id")))
                    sender = str(message.get("from", ""))
                    text = str((message.get("text") or {}).get("body", ""))
                    self.dispatch(sender, names.get(sender, ""), text)
        return 200

    def dispatch(self, sender: str, name: str, text: str) -> None:  # pragma: no cover - thread
        """Answer in the background: Meta wants the webhook to return at once."""
        threading.Thread(target=self.answer, args=(sender, name, text), daemon=True).start()

    def answer(self, sender: str, name: str, text: str) -> None:
        try:
            answer = self.handle(sender, name, text)
            if answer:
                self.deliver(sender, answer)
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            self.error = str(exc)[:200]

    def send_text(self, contact_id: str, text: str) -> None:
        phone = urllib.parse.quote(self.secret("WHATSAPP_PHONE_ID"), safe="")
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": contact_id,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        self.transport(
            "POST",
            f"{self.GRAPH}/{phone}/messages",
            self._headers(),
            json.dumps(payload).encode(),
            20.0,
        )

    def pair_link(self, code: str) -> str:
        if not self.number:
            return ""
        return f"https://wa.me/{self.number}?text={urllib.parse.quote(f'Spectre {code}')}"

    def status(self) -> dict[str, Any]:
        info = super().status()
        if self.configured:
            info["verify_token"] = self.verify_token()  # pasted into Meta's dashboard
            info["webhook"] = "/whatsapp/webhook"
        return info


# ---- Reddit -------------------------------------------------------------------------------------


class Reddit(Messenger):
    """Reddit private messages (the official OAuth API, a « script » app on a bot account).
    Reddit has no push for them: the inbox is read every minute."""

    name = "reddit"
    label = "Reddit"
    fields = (
        Field("REDDIT_CLIENT_ID", "Identifiant de l'appli (script)", secret=False),
        Field("REDDIT_CLIENT_SECRET", "Secret de l'appli"),
        Field("REDDIT_USERNAME", "Compte Reddit du bot", secret=False),
        Field("REDDIT_PASSWORD", "Mot de passe du compte du bot"),
    )
    chunk = 9000
    poll_s = 60.0
    guide = (
        "Crée un compte Reddit pour le bot (pas ton compte), puis sur reddit.com/prefs/apps une "
        "appli de type « script » (adresse de retour : http://localhost). Colle ici son "
        "identifiant, son secret, et le compte du bot. Les messages privés sont relevés chaque "
        "minute."
    )
    AUTH = "https://www.reddit.com/api/v1/access_token"
    OAUTH = "https://oauth.reddit.com"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._token = ""
        self._until = 0.0

    def _agent(self) -> str:
        return f"windows:spectre:1.0 (by /u/{self.secret('REDDIT_USERNAME')})"

    def token(self) -> str:
        if self._token and time.time() < self._until - 60:
            return self._token
        pair = f"{self.secret('REDDIT_CLIENT_ID')}:{self.secret('REDDIT_CLIENT_SECRET')}"
        body = urllib.parse.urlencode(
            {
                "grant_type": "password",
                "username": self.secret("REDDIT_USERNAME"),
                "password": self.secret("REDDIT_PASSWORD"),
            }
        ).encode()
        data = self.transport(
            "POST",
            self.AUTH,
            {
                "Authorization": "Basic " + base64.b64encode(pair.encode()).decode(),
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self._agent(),
            },
            body,
            20.0,
        )
        if not data.get("access_token"):
            raise ConnectionError(str(data.get("error") or "Reddit refuse la connexion"))
        self._token = str(data["access_token"])
        self._until = time.time() + float(data.get("expires_in", 3600))
        return self._token

    def oauth(self, method: str, path: str, form: dict[str, str] | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.token()}", "User-Agent": self._agent()}
        body = None
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            body = urllib.parse.urlencode(form).encode()
        return self.transport(method, self.OAUTH + path, headers, body, 20.0)

    def connect(self) -> None:
        self.oauth("GET", "/api/v1/me")

    def run_once(self) -> None:
        self.poll()

    def poll(self, now: float | None = None) -> int:
        """Read unread private messages, mark them read, answer the paired ones."""
        listing = self.oauth("GET", "/message/unread?limit=25&mark=false")
        children = (listing.get("data") or {}).get("children") or []
        if not children:
            return 0
        names = [str(c["data"]["name"]) for c in children if (c.get("data") or {}).get("name")]
        self.oauth("POST", "/api/read_message", {"id": ",".join(names)})
        handled = 0
        for child in children:
            data = child.get("data") or {}
            if child.get("kind") != "t4" or not data.get("author"):
                continue  # comment replies and mentions are not conversations
            author = str(data["author"]).lower()
            answer = self.handle(author, str(data["author"]), str(data.get("body", "")), now)
            if answer:
                for part in self.parts(answer):
                    self.oauth(
                        "POST",
                        "/api/comment",
                        {"api_type": "json", "thing_id": str(data["name"]), "text": part},
                    )
                handled += 1
        return handled

    def send_text(self, contact_id: str, text: str) -> None:
        self.oauth(
            "POST",
            "/api/compose",
            {"api_type": "json", "to": contact_id, "subject": "Spectre", "text": text},
        )

    def pair_link(self, code: str) -> str:
        user = self.secret("REDDIT_USERNAME")
        if not user:
            return ""
        query = urllib.parse.urlencode(
            {"to": user, "subject": "Spectre", "message": f"Spectre {code}"}
        )
        return f"https://www.reddit.com/message/compose/?{query}"


# ---- Signal -------------------------------------------------------------------------------------

Runner = Callable[[list[str], str, float], tuple[int, str, str]]  # (args, stdin, timeout)


def run_cli(
    args: list[str], stdin: str, timeout: float
) -> tuple[int, str, str]:  # pragma: no cover
    done = subprocess.run(  # noqa: S603 - fixed program, no shell, text through stdin
        args,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    return done.returncode, done.stdout, done.stderr


class Signal(Messenger):
    """Signal through signal-cli (GPL-3.0), linked as a device of the user's own account: the
    QR code is the one Signal shows in « Linked devices ». Only « Note to self » is served, so
    nobody else can talk to Spectre. Texts go through stdin, never on the command line."""

    name = "signal"
    label = "Signal"
    fields = ()
    chunk = 6000
    poll_s = 1.0
    guide = (
        "Il faut signal-cli (libre, GPL) et Java 21+. Clique « Lier Signal », puis dans Signal "
        "sur ton téléphone : Réglages → Appareils liés → « + », et scanne le QR. Ensuite, écris à "
        "Spectre dans « Note à soi » : il répond au même endroit."
    )

    def __init__(
        self,
        root: Path,
        db: Database,
        reply: Reply,
        *,
        runner: Runner = run_cli,
        popen: Callable[..., Any] = subprocess.Popen,
        environ: dict[str, str] | None = None,
    ) -> None:
        super().__init__(root, db, reply, environ=environ)
        self.runner = runner
        self.popen = popen
        self.link_uri = ""
        self._linking: Any = None
        self.spawn: Callable[..., None] = _thread  # tests: run nothing in the background

    @property
    def data_dir(self) -> Path:
        return self.root / "signal"

    def cli(self) -> str:
        found = self.secret("SIGNAL_CLI") or shutil.which("signal-cli") or ""
        if not found:
            local = Path.home() / ".spectre" / "tools" / "signal-cli" / "bin" / "signal-cli.bat"
            found = str(local) if local.exists() else ""
        return found

    @property
    def account(self) -> str:
        return self.db.get_kv("signal_account")

    @property
    def configured(self) -> bool:
        return bool(self.account and self.cli())

    def contacts(self) -> list[dict[str, str]]:
        return [{"id": self.account, "name": "Note à soi"}] if self.account else []

    def unlink(self, contact_id: str) -> None:
        """Forget the account (remove « Spectre » from Signal's linked devices on the phone)."""
        self.stop()
        self.db.set_kv("signal_account", "")

    def _base(self) -> list[str]:
        return [self.cli(), "--config", str(self.data_dir)]

    def start_link(self) -> str:
        """Start `signal-cli link`: returns the sgnl:// address to show as a QR code. The
        command waits for the scan; when it ends well, the account is kept and served."""
        if not self.cli():
            raise ValueError("signal-cli introuvable : installe-le (voir le guide)")
        if self._linking is not None and self._linking.poll() is None and self.link_uri:
            return self.link_uri
        self.data_dir.mkdir(parents=True, exist_ok=True)
        process = self.popen(
            [*self._base(), "link", "-n", "Spectre"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        self._linking = process
        self.link_uri = ""
        for line in process.stdout:
            if line.strip().startswith("sgnl://"):
                self.link_uri = line.strip()
                break
        if not self.link_uri:
            raise RuntimeError("signal-cli n'a pas donné de lien")
        uri = self.link_uri
        self.spawn(self._finish_link, process)
        return uri

    def _finish_link(self, process: Any) -> None:
        code = process.wait()
        self.link_uri = ""
        if code != 0:
            self.error = "liaison annulée ou expirée"
            return
        self.find_account()
        self.start()

    def find_account(self) -> str:
        code, out, _ = self.runner([*self._base(), "-o", "json", "listAccounts"], "", 60)
        try:
            accounts = json.loads(out) if code == 0 and out.strip() else []
        except ValueError:
            accounts = []
        numbers = [str(a.get("number", "")) for a in accounts if isinstance(a, dict)]
        if numbers and numbers[0]:
            self.db.set_kv("signal_account", numbers[0])
            self.error = ""
        return self.account

    def run_once(self) -> None:
        code, out, err = self.runner(
            [
                *self._base(),
                "-a",
                self.account,
                "-o",
                "json",
                "receive",
                "-t",
                "20",
                "--ignore-attachments",
                "--ignore-stories",
            ],
            "",
            90,
        )
        if code != 0:
            raise RuntimeError((err or out or "signal-cli a échoué").strip()[:200])
        for line in out.splitlines():
            self.on_line(line)

    def on_line(self, line: str) -> None:
        try:
            envelope = (json.loads(line) or {}).get("envelope") or {}
        except ValueError:
            return
        sent = (envelope.get("syncMessage") or {}).get("sentMessage") or {}
        target = str(sent.get("destinationNumber") or sent.get("destination") or "")
        text = str(sent.get("message") or "")
        if not text or target != self.account:
            return  # only « Note to self » from the user's own phone
        answer = self.handle(self.account, "", text)
        if answer:
            self.deliver(self.account, answer)

    def send_text(self, contact_id: str, text: str) -> None:
        code, out, err = self.runner(
            [*self._base(), "-a", self.account, "send", "--note-to-self", "--message-from-stdin"],
            text,
            90,
        )
        if code != 0:
            raise RuntimeError((err or out or "envoi Signal refusé").strip()[:200])

    def status(self) -> dict[str, Any]:
        info = super().status()
        info |= {"cli": bool(self.cli()), "link": self.link_uri, "qr": _qr(self.link_uri)}
        return info


def _thread(target: Callable[..., Any], *args: Any) -> None:
    threading.Thread(target=target, args=args, daemon=True).start()


def _qr(text: str) -> str:
    from spectre.assistant import qrcode

    try:
        return qrcode.svg(text) if text else ""
    except ValueError:  # too long for the encoder: the link stays clickable
        return ""


def all_messengers(root: Path, db: Database, reply: Reply) -> dict[str, Messenger]:
    items: list[Messenger] = [
        WhatsApp(root, db, reply),
        Signal(root, db, reply),
        Discord(root, db, reply),
        Reddit(root, db, reply),
    ]
    return {m.name: m for m in items}
