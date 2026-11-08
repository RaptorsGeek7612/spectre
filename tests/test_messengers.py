"""Discord, WhatsApp, Reddit and Signal gateways: pairing, QR links, signatures (no network)."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant.db import Database
from spectre.assistant.messengers import (
    HELP,
    Discord,
    Messenger,
    Reddit,
    Signal,
    WhatsApp,
    all_messengers,
    sweep_signal_tmp,
)
from spectre.assistant.service import AssistantService
from tests.test_assistant_agents import db  # noqa: F401 - fixture
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client


class FakeHttp:
    def __init__(self, answers: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []
        self.answers = answers or {}

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
    ) -> Any:
        self.calls.append((method, url, headers, body))
        for key, value in self.answers.items():
            if key in url:
                return value() if callable(value) else value
        return {}


def echo(text: str, channel: str) -> str:
    return f"{channel} : {text}"


def test_pairing_rules(db: Database, tmp_path: Path) -> None:  # noqa: F811
    m = Messenger(tmp_path, db, echo, environ={})
    m.name = "essai"
    assert m.configured  # no field needed
    assert m.handle("1", "A", "salut") == ""  # unknown: no answer
    code = m.pairing_code(now=100.0)
    assert m.handle("1", "A", "Spectre 000000" if code != "000000" else "1", now=100.0) == ""
    assert m.handle("1", "A", f"{code} {code}", now=100.0) == ""  # one code only
    assert m.handle("1", "Alice", f"/start {code}", now=100.0).startswith("C'est fait")
    assert m.contacts() == [{"id": "1", "name": "Alice"}] and m.pending_code(now=100.0) == ""
    assert m.handle("1", "A", "/aide") == HELP and m.handle("1", "A", "  ") == ""
    assert m.handle("1", "A", "Quelle heure ?") == "essai : Quelle heure ?"
    assert m.pairing_code(now=0.0) and m.pending_code(now=10_000.0) == ""  # expired
    db.set_kv("essai_pair", "123456|abc")
    assert m.pending_code() == ""
    for i in range(2, 7):  # five contacts at most
        code = m.pairing_code()
        m.handle(str(i), "", f"Spectre {code}")
    assert len(m.contacts()) == 5
    m.unlink("1")
    assert "1" not in {c["id"] for c in m.contacts()}
    db.set_kv("essai_contacts", "pas du json")
    assert m.contacts() == []
    assert m.parts("x" * 4500) == ["x" * 2000, "x" * 2000, "x" * 500] and m.parts("") == [
        "(réponse vide)"
    ]
    assert m.status()["qr"] == ""  # no link for the base class


def test_setup_writes_env_and_refuses_new_lines(db: Database, tmp_path: Path) -> None:  # noqa: F811
    d = Discord(tmp_path, db, echo, transport=FakeHttp({"applications": {"id": "42"}}))
    with pytest.raises(ValueError, match="une seule ligne"):
        d.setup({"DISCORD_BOT_TOKEN": "a\nb"})
    d.setup({"DISCORD_BOT_TOKEN": "jeton-secret", "AUTRE": "x"})
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "DISCORD_BOT_TOKEN=jeton-secret" in env and "AUTRE" not in env
    assert d.configured and d.app_id == "42"
    shown = json.dumps(d.status())
    assert "jeton-secret" not in shown  # never shown back
    assert d.status()["fields"][0]["set"] is True


class FakeSocket:
    def __init__(self, frames: list[Any]) -> None:
        self.frames = frames
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def recv(self, timeout: float) -> str | None:
        if not self.frames:
            return None
        frame = self.frames.pop(0)
        if frame is TimeoutError:
            raise TimeoutError
        return json.dumps(frame)

    def send(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def close(self) -> None:
        self.closed = True


def dm(seq: int, channel: str, user: str, text: str, **extra: Any) -> dict[str, Any]:
    data = {"channel_id": channel, "author": {"id": user, "username": "olivier"}, "content": text}
    return {"op": 0, "t": "MESSAGE_CREATE", "s": seq, "d": data | extra}


def test_discord_gateway_pairs_and_answers(db: Database, tmp_path: Path) -> None:  # noqa: F811
    http = FakeHttp({"applications/@me": {"id": "app1"}, "users/@me": {"id": "bot1"}})
    socket = FakeSocket([])
    d = Discord(
        tmp_path,
        db,
        echo,
        transport=http,
        environ={"DISCORD_BOT_TOKEN": "tok"},
        connector=lambda url: socket,
        inline=True,
    )
    d.connect()
    code = d.pairing_code()
    assert d.status()["link"].startswith("https://discord.com/oauth2/authorize?client_id=app1")
    assert d.status()["qr"].startswith("<svg")
    socket.frames = [
        {"op": 10, "d": {"heartbeat_interval": 41250}},
        TimeoutError,  # time to beat
        dm(1, "c9", "u1", "salut"),  # unknown: no answer
        dm(2, "g1", "u1", f"Spectre {code}", guild_id="7"),  # servers are never served
        dm(3, "c9", "bot1", f"Spectre {code}"),  # Spectre itself
        dm(4, "c9", "u2", "x", author={"id": "u3", "bot": True}),  # other bots
        dm(5, "c9", "u1", f"Spectre {code}"),
        dm(6, "c9", "u1", "Quelle heure ?"),
        {"op": 1},  # the gateway asks for a beat
        {"op": 7},  # reconnect
    ]
    d.run_once()
    assert socket.sent[0]["op"] == 2 and socket.sent[0]["d"]["intents"] == 1 << 12
    assert socket.sent[1] == {"op": 1, "d": None} and socket.sent[2] == {"op": 1, "d": 6}
    assert socket.closed and d.contacts() == [{"id": "c9", "name": "olivier"}]
    posts = [json.loads(b or b"{}") for m, u, _, b in http.calls if u.endswith("/messages")]
    assert posts[0]["content"].startswith("C'est fait") and posts[1] == {
        "content": "discord : Quelle heure ?"
    }
    assert all(h["Authorization"] == "Bot tok" for _, _, h, _ in http.calls)
    socket.frames = [{"op": 10, "d": {"heartbeat_interval": 1000}}]
    d.run_once()  # closed by Discord: returns to reconnect
    assert d.broadcast("x" * 2500) == 1


def signed(secret: str, payload: dict[str, Any]) -> tuple[dict[str, str], bytes]:
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={sig}"}, body


def wa_message(mid: str, sender: str, text: str, kind: str = "text") -> dict[str, Any]:
    value = {
        "contacts": [{"wa_id": sender, "profile": {"name": "Olivier"}}],
        "messages": [{"id": mid, "from": sender, "type": kind, "text": {"body": text}}],
    }
    return {"entry": [{"changes": [{"field": "messages", "value": value}]}]}


def test_whatsapp_webhook(db: Database, tmp_path: Path) -> None:  # noqa: F811
    http = FakeHttp({"fields=display_phone_number": {"display_phone_number": "+33 6 12 34 56 78"}})
    env = {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_ID": "99", "WHATSAPP_APP_SECRET": "s3cret"}
    wa = WhatsApp(tmp_path, db, echo, transport=http, environ=env)
    wa.dispatch = wa.answer  # type: ignore[method-assign] - answer at once in tests
    off = WhatsApp(tmp_path, db, echo, transport=http, environ={})
    assert off.verify({}) == (404, "") and off.receive({}, b"") == 404 and not off.running
    assert not off.start()
    token = wa.verify_token()
    assert token == wa.verify_token()  # made once
    assert wa.verify(
        {"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "c"}
    ) == (
        200,
        "c",
    )
    assert wa.verify({"hub.mode": "subscribe", "hub.verify_token": "faux"})[0] == 403
    wa.connect()
    code = wa.pairing_code()
    assert wa.status()["link"] == f"https://wa.me/33612345678?text=Spectre%20{code}"
    assert wa.status()["verify_token"] == token and wa.running
    headers, body = signed("s3cret", wa_message("m1", "3361", f"Spectre {code}"))
    assert wa.receive({"x-hub-signature-256": "sha256=00"}, body) == 401
    assert wa.receive({}, body) == 401
    assert wa.receive(headers, body) == 200
    assert wa.receive(headers, body) == 200  # Meta sends again: handled once
    headers2, body2 = signed("s3cret", wa_message("m2", "3361", "Bonjour"))
    assert wa.receive(headers2, body2) == 200
    headers3, body3 = signed("s3cret", wa_message("m3", "3361", "", kind="image"))
    assert wa.receive(headers3, body3) == 200
    bad = b"{pas du json"
    sig = hmac.new(b"s3cret", bad, hashlib.sha256).hexdigest()
    assert wa.receive({"X-Hub-Signature-256": f"sha256={sig}"}, bad) == 400
    sent = [json.loads(b or b"{}") for m, u, _, b in http.calls if u.endswith("/99/messages")]
    assert [s["text"]["body"][:10] for s in sent] == ["C'est fait", "whatsapp :"]
    assert sent[0]["to"] == "3361" and wa.contacts()[0]["name"] == "Olivier"

    def boom(*_: Any) -> Any:
        raise ConnectionError("hors fenêtre de 24 h")

    wa.transport = boom
    wa.answer("3361", "", "encore")
    assert "24 h" in wa.error
    wa._quiet_connect()
    assert "24 h" in wa.error
    wa.transport = http
    wa._quiet_connect()
    assert wa.error == ""


def test_reddit_inbox(db: Database, tmp_path: Path) -> None:  # noqa: F811
    inbox: list[dict[str, Any]] = []
    http = FakeHttp(
        {
            "access_token": {"access_token": "AT", "expires_in": 3600},
            "/message/unread": lambda: {"data": {"children": list(inbox)}},
        }
    )
    env = {
        "REDDIT_CLIENT_ID": "id",
        "REDDIT_CLIENT_SECRET": "sec",
        "REDDIT_USERNAME": "spectre_bot",
        "REDDIT_PASSWORD": "pw",
    }
    r = Reddit(tmp_path, db, echo, transport=http, environ=env)
    assert r.poll() == 0
    r.connect()
    code = r.pairing_code()
    link = r.status()["link"]
    assert link.startswith("https://www.reddit.com/message/compose/?to=spectre_bot")
    assert f"Spectre+{code}" in link
    inbox[:] = [
        {"kind": "t4", "data": {"name": "t4_a", "author": "Olivier", "body": f"Spectre {code}"}},
        {"kind": "t1", "data": {"name": "t1_b", "author": "x", "body": "commentaire"}},
        {"kind": "t4", "data": {"name": "t4_c", "author": "Inconnu", "body": "salut"}},
    ]
    assert r.poll() == 1
    inbox[:] = [{"kind": "t4", "data": {"name": "t4_d", "author": "olivier", "body": "Bonjour"}}]
    assert r.poll() == 1
    reads = [b for m, u, _, b in http.calls if u.endswith("/api/read_message")]
    assert reads[0] == b"id=t4_a%2Ct1_b%2Ct4_c"
    replies = [b.decode() for m, u, _, b in http.calls if u.endswith("/api/comment") and b]
    assert "thing_id=t4_a" in replies[0] and "reddit+%3A+Bonjour" in replies[1]
    auth = [h for m, u, h, _ in http.calls if u.endswith("access_token")]
    assert len(auth) == 1 and auth[0]["Authorization"].startswith("Basic ")  # token reused
    assert r.broadcast("note") == 1
    assert any(u.endswith("/api/compose") for _, u, _, _ in http.calls)
    r._token = ""
    r.transport = FakeHttp({"access_token": {"error": "invalid_grant"}})
    with pytest.raises(ConnectionError, match="invalid_grant"):
        r.connect()
    assert Reddit(tmp_path, db, echo, environ={}).pair_link("1") == ""


class FakeLink:
    def __init__(self, lines: list[str], code: int = 0) -> None:
        self.stdout = io.StringIO("".join(lines))
        self.code = code

    def poll(self) -> int | None:
        return None

    def wait(self) -> int:
        return self.code


def test_signal_link_and_note_to_self(
    db: Database,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], str]] = []
    outputs: dict[str, tuple[int, str, str]] = {}

    def runner(args: list[str], stdin: str, timeout: float) -> tuple[int, str, str]:
        calls.append((args, stdin))
        for key, out in outputs.items():
            if key in args:
                return out
        return 0, "", ""

    links: list[FakeLink] = []

    def popen(args: list[str], **_: Any) -> FakeLink:
        return links.pop(0)

    env = {"SIGNAL_CLI": "C:/outils/signal-cli.bat"}
    s = Signal(tmp_path, db, echo, runner=runner, popen=popen, environ=env)
    s.spawn = lambda *_: None  # type: ignore[method-assign] - nothing in the background
    assert not s.configured and s.contacts() == []
    links.append(FakeLink(["INFO démarrage\n"]))
    with pytest.raises(RuntimeError, match="pas donné de lien"):
        s.start_link()
    uri = "sgnl://linkdevice?uuid=abc&pub_key=XYZ"
    links.append(FakeLink([f"{uri}\n"], code=1))
    assert s.start_link() == uri
    s._finish_link(FakeLink([], code=1))
    assert s.error == "liaison annulée ou expirée" and s.link_uri == ""
    links.append(FakeLink([f"{uri}\n"]))
    s.start_link()
    assert s.status()["qr"].startswith("<svg") and s.status()["link"] == uri
    outputs["listAccounts"] = (0, json.dumps([{"number": "+33612345678"}]), "")
    s.start = lambda: True  # type: ignore[method-assign] - no thread in tests
    s._finish_link(FakeLink([]))
    assert s.account == "+33612345678" and s.configured
    assert s.contacts() == [{"id": "+33612345678", "name": "Note à soi"}]
    note = {
        "envelope": {
            "syncMessage": {
                "sentMessage": {"destinationNumber": "+33612345678", "message": "Bonjour"}
            }
        }
    }
    other = {
        "envelope": {
            "syncMessage": {"sentMessage": {"destinationNumber": "+331", "message": "pas pour toi"}}
        }
    }
    stranger = {"envelope": {"source": "+339", "dataMessage": {"message": "hello"}}}
    lines = "\n".join(json.dumps(x) for x in (note, other, stranger)) + "\nbruit\n"
    outputs["receive"] = (0, lines, "")
    s.run_once()
    sends = [(a, i) for a, i in calls if "send" in a]
    assert len(sends) == 1 and sends[0][1] == "signal : Bonjour"
    assert "--note-to-self" in sends[0][0] and "Bonjour" not in " ".join(sends[0][0])
    outputs["receive"] = (1, "", "compte non lié")
    with pytest.raises(RuntimeError, match="compte non lié"):
        s.run_once()
    outputs["send"] = (1, "", "refusé")
    with pytest.raises(RuntimeError, match="refusé"):
        s.send_text("", "x")
    outputs["listAccounts"] = (0, "pas du json", "")
    assert s.find_account() == "+33612345678"  # kept
    s.unlink("+33612345678")
    assert s.account == "" and not s.configured
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with pytest.raises(ValueError, match="introuvable"):
        Signal(tmp_path, db, echo, environ={"SIGNAL_CLI": ""}).start_link()


def test_signal_tmp_is_swept(
    db: Database,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "t"
    assert sweep_signal_tmp(folder) == 0  # not created yet
    folder.mkdir()
    old_dir = folder / "libsignal123"
    old_dir.mkdir()
    (old_dir / "signal_jni.dll").write_bytes(b"x")
    old_file = folder / "libsignal456.dll"
    old_file.write_bytes(b"x")
    fresh = folder / "libsignal789"
    fresh.mkdir()
    other = folder / "garde.txt"
    other.write_text("x", encoding="utf-8")
    past = time.time() - 3600
    for path in (old_dir, old_file, other):
        os.utime(path, (past, past))
    assert sweep_signal_tmp(folder) == 2
    assert sorted(p.name for p in folder.iterdir()) == ["garde.txt", "libsignal789"]

    def locked(_: Path) -> None:
        raise PermissionError("en cours d'usage")

    os.utime(fresh, (past, past))
    monkeypatch.setattr("shutil.rmtree", locked)
    assert sweep_signal_tmp(folder) == 0 and fresh.exists()  # skipped, not an error

    monkeypatch.setenv("SIGNAL_CLI_OPTS", "-Xmx256m")
    s = Signal(tmp_path, db, echo)
    env = s.java_env()
    assert s.tmp_dir.is_dir()
    assert env["SIGNAL_CLI_OPTS"] == f'-Xmx256m "-Djava.io.tmpdir={s.tmp_dir}"'


def test_all_messengers(db: Database, tmp_path: Path) -> None:  # noqa: F811
    found = all_messengers(tmp_path, db, echo)
    assert list(found) == ["whatsapp", "signal", "discord", "reddit"]
    for m in found.values():
        info = m.status()
        assert {"name", "label", "configured", "contacts", "qr", "guide", "fields"} <= set(info)


def test_service_and_routes(
    api: Client,  # noqa: F811
    service: AssistantService,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, listed = api.json("GET", "/api/assistant/messengers")
    assert status == 200 and [m["name"] for m in listed] == [
        "whatsapp",
        "signal",
        "discord",
        "reddit",
    ]
    status, err = api.json("POST", "/api/assistant/messengers/discord/pair", {})
    assert status == 400 and "règle d'abord Discord" in err["error"]
    assert api.json("POST", "/api/assistant/messengers/myspace/pair", {})[0] in (400, 404)
    http = FakeHttp({"applications/@me": {"id": "app1"}, "users/@me": {"id": "bot1"}})
    discord = service.messengers["discord"]
    discord.transport = http
    monkeypatch.setattr(discord, "restart", lambda: None)
    status, info = api.json(
        "POST", "/api/assistant/messengers/discord/setup", {"values": {"DISCORD_BOT_TOKEN": "tok"}}
    )
    assert status == 200 and info["configured"] and "tok" not in json.dumps(info)
    code = api.json("POST", "/api/assistant/messengers/discord/pair", {})[1]["code"]
    discord.handle("c1", "olivier", f"Spectre {code}")
    assert service._remote_reply("/status", "discord").startswith("Cerveau :")
    assert service._remote_reply("bonjour", "discord") == "Réponse."
    sent: list[str] = []
    monkeypatch.setattr(discord, "broadcast", lambda text: sent.append(text) or 1)
    monkeypatch.setattr("threading.Thread.start", lambda self: self.run())
    service._on_initiative("mission", "Mission terminée", "Rapport prêt.")
    assert sent == ["Mission terminée\nRapport prêt."]
    status, info = api.json("POST", "/api/assistant/messengers/discord/unlink", {"id": "c1"})
    assert status == 200 and info["contacts"] == []
    # WhatsApp's webhook: no session cookie, but the signature
    assert api.request("GET", "/whatsapp/webhook?hub.mode=subscribe")[0] == 404
    assert api.request("POST", "/whatsapp/webhook", raw=b"{}")[0] == 404
    assert api.request("DELETE", "/whatsapp/webhook")[0] == 405
    for key, value in {
        "WHATSAPP_TOKEN": "t",
        "WHATSAPP_PHONE_ID": "9",
        "WHATSAPP_APP_SECRET": "s",
    }.items():
        monkeypatch.setenv(key, value)
    token = service.messengers["whatsapp"].verify_token()  # type: ignore[attr-defined]
    status, _, body = api.request(
        "GET", f"/whatsapp/webhook?hub.mode=subscribe&hub.verify_token={token}&hub.challenge=42"
    )
    assert status == 200 and body == b"42"
    assert api.request("POST", "/whatsapp/webhook", raw=b"{}")[0] == 401
