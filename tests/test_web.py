"""Tests for spectre.web: demo, pipeline, store, auth, exports and the HTTP server (no network)."""

from __future__ import annotations

import http.client
import json
import os
import runpy
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from langchain_anthropic import ChatAnthropic

from spectre.errors import ConfigurationError, MissingAPIKeyError, SpectreError
from spectre.web import auth as auth_mod
from spectre.web import server as server_mod
from spectre.web.auth import Auth
from spectre.web.demo import DEMO_REQUEST, DemoChatModel, demo_text
from spectre.web.export import to_markdown, to_share_html
from spectre.web.pipeline import build_models, clean_overrides, stream_run
from spectre.web.store import DEFAULT_SETTINGS, Store, default_state_dir, title_from
from tests.conftest import FAKE_KEY, RaisingFakeModel, fake, make_ai


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    for target in ("spectre.web.pipeline.load_env", "spectre.web.server.load_env"):
        monkeypatch.setattr(target, lambda: None)


# ---- demo ------------------------------------------------------------------------------------


def test_demo_texts() -> None:
    assert "Écris un poème" in demo_text("scout", "Écris un poème")
    assert DEMO_REQUEST in demo_text("scout", "  ")
    draft, final = demo_text("scribe", "x"), demo_text("warden", "x")
    assert draft != final
    assert "1905" in final and "1915" in draft


def test_demo_model_invoke_and_stream() -> None:
    model = DemoChatModel(agent="warden", model="m-test")
    ai = model.invoke("relis")
    assert ai.text == demo_text("warden", "")
    assert ai.response_metadata["model_name"] == "m-test"
    assert ai.usage_metadata and ai.usage_metadata["output_tokens"] > 0
    chunks = list(model.stream("relis"))
    assert "".join(str(c.content) for c in chunks) == ai.text


def test_demo_model_stream_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("spectre.web.demo.time.sleep", slept.append)
    list(DemoChatModel(agent="scout", model="m", delay=0.01).stream("hello"))
    assert slept and all(value == 0.01 for value in slept)


# ---- pipeline --------------------------------------------------------------------------------


def test_clean_overrides() -> None:
    assert clean_overrides(None) == {}
    assert clean_overrides({"SPECTRE_WARDEN_EFFORT": " max ", "SPECTRE_SCOUT_MODEL": " "}) == {
        "SPECTRE_WARDEN_EFFORT": "max"
    }
    with pytest.raises(ConfigurationError, match="non autorisé"):
        clean_overrides({"ANTHROPIC_API_KEY": "x"})


def test_build_models_demo_needs_no_key() -> None:
    models = build_models(demo=True, overrides={"SPECTRE_WARDEN_MODEL": "claude-x"})
    assert all(isinstance(m, DemoChatModel) for m in models.values())
    assert models["warden"].model == "claude-x"  # type: ignore[attr-defined]


def test_build_models_real_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(MissingAPIKeyError):
        build_models(demo=False, overrides={})
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    models = build_models(demo=False, overrides={})
    assert all(isinstance(m, ChatAnthropic) for m in models.values())


def test_stream_run_demo_events() -> None:
    events = list(stream_run("Explique", demo=True))
    kinds = [e["type"] for e in events if e["type"] != "token"]
    assert kinds == [
        "agent_start",
        "agent_done",
        "agent_start",
        "agent_done",
        "agent_start",
        "agent_done",
        "done",
    ]
    tokens = {e["agent"] for e in events if e["type"] == "token"}
    assert tokens == {"scout", "scribe", "warden"}
    done = events[-1]
    assert done["final_text"] == demo_text("warden", "")
    assert [u["agent"] for u in done["usage"]] == ["scout", "scribe", "warden"]
    assert done["total_cost_usd"] > 0
    assert set(done["durations"]) == {"scout", "scribe", "warden"}


def test_stream_run_error_names_agent() -> None:
    models = {
        "scout": fake("scout", make_ai("brief")),
        "scribe": RaisingFakeModel(exc=SpectreError("boom", agent="scribe")),
        "warden": fake("warden", make_ai("final")),
    }
    events = list(stream_run("x", demo=False, models=models))
    last = events[-1]
    assert last["type"] == "error"
    assert last["agent"] == "scribe"
    assert last["brief"] == "brief"


def test_stream_run_configuration_error_reports_first_agent() -> None:
    events = list(stream_run("x", demo=False, overrides={}))  # no key -> MissingAPIKeyError
    assert events[-1]["type"] == "error"
    assert events[-1]["agent"] == "scout"


def test_stream_run_cancel() -> None:
    cancel = threading.Event()
    cancel.set()
    events = list(stream_run("x", demo=True, cancel=cancel))
    assert events[-1]["type"] == "cancelled"


# ---- store -----------------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "state")


def test_default_state_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SPECTRE_WEBUI_STATE_DIR", raising=False)
    assert default_state_dir().parts[-2:] == (".spectre", "webui")
    monkeypatch.setenv("SPECTRE_WEBUI_STATE_DIR", str(tmp_path))
    assert default_state_dir() == tmp_path


def test_title_from() -> None:
    assert title_from("  \n") == "Plaque sans titre"
    assert title_from("ligne 1\nligne 2") == "ligne 1"
    long = title_from("x" * 80)
    assert len(long) == 60 and long.endswith("…")


def test_run_lifecycle(store: Store) -> None:
    run = store.create_run("Écris un haïku", demo=True, preset="Standard", overrides={})
    assert run["number"] == 1 and run["status"] == "running"
    assert store.get_run(run["id"])["title"] == "Écris un haïku"
    updated = store.update_run(
        run["id"],
        {
            "title": "Haïku",
            "pinned": 1,
            "archived": False,
            "project": " Poèmes ",
            "tags": ["#a", "b", " "],
        },
    )
    assert updated["pinned"] is True and updated["project"] == "Poèmes"
    assert updated["tags"] == ["a", "b"]
    with pytest.raises(ValueError, match="non modifiable"):
        store.update_run(run["id"], {"status": "done"})
    with pytest.raises(ValueError, match="liste"):
        store.update_run(run["id"], {"tags": "a"})
    with pytest.raises(ValueError, match="vide"):
        store.update_run(run["id"], {"title": " "})
    copy = store.duplicate_run(run["id"])
    assert copy["number"] == 2 and copy["title"].endswith("(copie)") and not copy["pinned"]
    store.delete_run(copy["id"])
    with pytest.raises(KeyError):
        store.delete_run(copy["id"])
    with pytest.raises(KeyError):
        store.get_run("../etc")


def test_list_runs_order_search_archive(store: Store) -> None:
    a = store.create_run("alpha", demo=True, preset="Standard", overrides={})
    b = store.create_run("beta", demo=True, preset="Standard", overrides={})
    c = store.create_run("gamma", demo=True, preset="Standard", overrides={})
    store.update_run(a["id"], {"pinned": True})
    store.update_run(b["id"], {"tags": ["urgent"]})
    store.update_run(c["id"], {"archived": True})
    assert [r["id"] for r in store.list_runs()] == [a["id"], b["id"]]
    assert [r["id"] for r in store.list_runs(query="#urgent")] == [b["id"]]
    assert [r["id"] for r in store.list_runs(archived=True)] == [c["id"]]
    (store.runs_dir / "broken.json").write_text("{nope", encoding="utf-8")
    assert len(store.list_runs()) == 2


def test_import_clear_and_interrupted(store: Store) -> None:
    added = store.import_runs(
        [
            {
                "request": "importée",
                "final_text": "fin",
                "usage": [],
                "tags": ["x", 3],
                "status": "done",
            },
            {"request": " "},
            "pas un dict",
        ]
    )
    assert added == 1
    (imported,) = store.list_runs()
    assert store.get_run(imported["id"])["final_text"] == "fin"
    running = store.create_run("en cours", demo=True, preset="Standard", overrides={})
    store.mark_interrupted()
    assert store.get_run(running["id"])["status"] == "cancelled"
    assert store.clear_runs() == 2
    assert store.list_runs() == []


def test_settings_and_presets(store: Store) -> None:
    assert store.get_settings() == DEFAULT_SETTINGS
    assert store.update_settings({"theme": "light", "show_costs": False})["theme"] == "light"
    assert store.get_settings()["show_costs"] is False
    with pytest.raises(ValueError, match="inconnu"):
        store.update_settings({"nope": 1})
    with pytest.raises(ValueError, match="type"):
        store.update_settings({"demo": "yes"})
    presets = store.save_preset("Rapide", {"SPECTRE_WARDEN_EFFORT": "low"})
    assert presets["Rapide"] == {"SPECTRE_WARDEN_EFFORT": "low"}
    assert "Standard" in presets
    with pytest.raises(ValueError):
        store.save_preset(" ", {})
    assert "Rapide" not in store.delete_preset("Rapide")
    with pytest.raises(KeyError):
        store.delete_preset("Standard")


# ---- exports ---------------------------------------------------------------------------------


def _finished_run(store: Store) -> dict[str, Any]:
    run = store.create_run("Demande <b>", demo=True, preset="Standard", overrides={})
    run.update(
        status="error",
        final_text="Final & fin",
        draft="Brouillon",
        brief="Brief",
        error="boom",
        error_agent="warden",
        usage=[
            {
                "agent": "scout",
                "model": "m",
                "input_tokens": 1,
                "output_tokens": 2,
                "cost_usd": 0.1,
                "truncated": False,
            }
        ],
    )
    return run


def test_exports(store: Store) -> None:
    run = _finished_run(store)
    md = to_markdown(run)
    assert "plaque N° 0001 (démo)" in md and "[warden] boom" in md and "Coût" in md
    page = to_share_html(run)
    assert "Demande &lt;b&gt;" in page and "Final &amp; fin" in page
    assert "<script" not in page


# ---- auth ------------------------------------------------------------------------------------


def test_auth_tokens(tmp_path: Path) -> None:
    off = Auth(None, tmp_path / "s.key")
    assert not off.enabled and off.valid(None)
    on = Auth("pw", tmp_path / "s.key")
    token = on.issue(now=1000.0)
    assert on.valid(token, now=1001.0)
    assert not on.valid(token, now=1000.0 + auth_mod.SESSION_TTL_S + 1)
    assert not on.valid(None) and not on.valid("a.b") and not on.valid(token[:-1] + "0")
    # the secret is reused across restarts, and rebuilt if corrupt
    assert Auth("pw", tmp_path / "s.key").valid(token, now=1001.0)
    (tmp_path / "s.key").write_text("zz", encoding="utf-8")
    assert not Auth("pw", tmp_path / "s.key").valid(token, now=1001.0)


def test_auth_lockout(tmp_path: Path) -> None:
    auth = Auth("pw", tmp_path / "s.key")
    for _ in range(auth_mod.MAX_FAILURES):
        assert not auth.check_password("1.2.3.4", "bad", now=10.0)
    assert auth.locked_out("1.2.3.4", now=11.0)
    assert not auth.locked_out("1.2.3.4", now=10.0 + auth_mod.LOCKOUT_S + 1)
    assert auth.check_password("1.2.3.4", "pw")
    assert not auth.locked_out("1.2.3.4")


# ---- HTTP server -----------------------------------------------------------------------------


class Client:
    def __init__(self, port: int) -> None:
        self.port = port
        self.cookie = ""

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        headers: dict[str, str] | None = None,
        raw: bytes | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = {"X-Spectre": "1"} if method != "GET" else {}
        if self.cookie:
            hdrs["Cookie"] = self.cookie
        hdrs.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        payload = resp.read()
        result = resp.status, {k.lower(): v for k, v in resp.getheaders()}, payload
        conn.close()
        return result

    def json(self, method: str, path: str, body: Any = None, **kw: Any) -> tuple[int, Any]:
        status, _, payload = self.request(method, path, body, **kw)
        return status, json.loads(payload or b"null")


@contextmanager
def _serve(tmp_path: Path, password: str | None = None, delay: float = 0.0) -> Iterator[Client]:
    store = Store(tmp_path / "state")
    auth = Auth(password, store.root / "secret.key")
    server = server_mod.make_server("127.0.0.1", 0, store=store, auth=auth, demo_delay=delay)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[Client]:
    with _serve(tmp_path) as running:
        yield running


def _sse(payload: bytes) -> list[dict[str, Any]]:
    events = []
    for block in payload.decode().split("\n\n"):
        data = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


def test_static_files(client: Client) -> None:
    status, headers, body = client.request("GET", "/")
    assert status == 200 and b"<title>Spectre</title>" in body
    assert headers["content-type"].startswith("text/html")
    assert "default-src 'self'" in headers["content-security-policy"]
    for path, ctype in [
        ("/app.js", "text/javascript"),
        ("/app.css", "text/css"),
        ("/manifest.webmanifest", "application/manifest+json"),
        ("/fonts/big-shoulders-stencil-100-900-latin.woff2", "font/woff2"),
        ("/icons/icon-192.png", "image/png"),
    ]:
        status, headers, _ = client.request("GET", path)
        assert status == 200 and headers["content-type"].startswith(ctype), path
    assert client.request("GET", "/sw.js")[1]["service-worker-allowed"] == "/"
    assert client.request("HEAD", "/")[0] == 200
    assert client.request("GET", "/nope.txt")[0] == 404
    assert client.request("GET", "/fonts/../app.js")[0] == 404
    assert client.request("POST", "/")[0] == 405


def test_host_and_origin_checks(client: Client) -> None:
    assert client.request("GET", "/", headers={"Host": "evil.example"})[0] == 421
    status, _, _ = client.request(
        "POST", "/api/settings", {"theme": "light"}, headers={"X-Spectre": "0"}
    )
    assert status == 403
    status, _, _ = client.request(
        "POST", "/api/settings", {"theme": "light"}, headers={"Origin": "http://evil.example"}
    )
    assert status == 403


def test_status_and_settings(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    status, data = client.json("GET", "/api/status")
    assert status == 200 and data["authenticated"] and not data["has_api_key"]
    assert [a["name"] for a in data["agents"]] == ["scout", "scribe", "warden"]
    assert "Standard" in data["builtin_presets"]
    assert "ANTHROPIC_API_KEY" not in json.dumps(data)
    assert client.json("POST", "/api/settings", {"theme": "light"})[1]["theme"] == "light"
    assert client.json("GET", "/api/settings")[1]["theme"] == "light"
    assert client.json("POST", "/api/settings", {"theme": 3})[0] == 400


def test_bad_bodies(client: Client) -> None:
    assert client.request("POST", "/api/settings", raw=b"{nope")[0] == 400
    assert client.request("POST", "/api/settings", raw=b"[1]")[0] == 400
    # Announce an oversized body without sending it: the server must refuse before reading.
    with socket.create_connection(("127.0.0.1", client.port), timeout=10) as sock:
        sock.sendall(
            b"POST /api/settings HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Spectre: 1\r\n"
            b"Content-Length: " + str(server_mod.MAX_BODY + 1).encode() + b"\r\n\r\n"
        )
        reply = sock.recv(4096)
    assert reply.startswith(b"HTTP/1.1 413") and b"Connection: close" in reply
    assert client.json("GET", "/api/unknown")[0] == 404
    assert client.json("POST", "/api/run", {"request": " "})[0] == 400
    assert client.json("POST", "/api/run", {"request": "x" * 100_001})[0] == 400
    assert client.json("POST", "/api/run", {"request": "x", "overrides": {"FOO": "1"}})[0] == 400


def test_demo_run_and_history(client: Client) -> None:
    status, headers, payload = client.request(
        "POST", "/api/run", {"request": "Explique la lumière", "demo": True, "title": "Lumière"}
    )
    assert status == 200 and headers["content-type"].startswith("text/event-stream")
    events = _sse(payload)
    assert events[0]["type"] == "run"
    assert events[-1]["type"] == "done"
    run = events[-1]["run"]
    assert run["status"] == "done" and run["final_text"] and run["title"] == "Lumière"
    run_id = run["id"]

    status, runs = client.json("GET", "/api/runs?q=lumi")
    assert [r["id"] for r in runs] == [run_id]
    assert client.json("GET", f"/api/runs/{run_id}")[1]["usage"]
    assert client.json("POST", f"/api/runs/{run_id}", {"pinned": True})[1]["pinned"] is True
    copy = client.json("POST", f"/api/runs/{run_id}/duplicate", {})[1]
    assert copy["number"] == 2

    status, headers, body = client.request("GET", f"/api/runs/{run_id}/export?format=md")
    assert status == 200 and b"# Spectre" in body and "0001.md" in headers["content-disposition"]
    assert client.request("GET", f"/api/runs/{run_id}/export?format=json")[0] == 200
    assert b"<!doctype html>" in client.request("GET", f"/api/runs/{run_id}/export?format=html")[2]
    assert client.request("GET", f"/api/runs/{run_id}/export?format=pdf")[0] == 400

    status, _, dump = client.request("GET", "/api/export")
    exported = json.loads(dump)["runs"]
    assert len(exported) == 2
    assert client.json("POST", "/api/import", {"runs": exported})[1] == {"imported": 2}
    assert client.json("POST", "/api/import", {"nope": 1})[0] == 400
    assert client.json("DELETE", f"/api/runs/{copy['id']}")[1] == {"ok": True}
    assert client.json("DELETE", f"/api/runs/{copy['id']}")[0] == 404
    assert client.json("POST", "/api/clear", {})[1] == {"deleted": 3}


def test_real_run_without_key_reports_error(client: Client) -> None:
    _, _, payload = client.request("POST", "/api/run", {"request": "x", "demo": False})
    last = _sse(payload)[-1]
    assert last["type"] == "error" and "ANTHROPIC_API_KEY" in last["message"]
    assert last["run"]["status"] == "error"


def test_presets_api(client: Client) -> None:
    status, presets = client.json(
        "POST", "/api/presets", {"name": "Lent", "overrides": {"SPECTRE_WARDEN_EFFORT": "max"}}
    )
    assert status == 200 and presets["Lent"] == {"SPECTRE_WARDEN_EFFORT": "max"}
    assert client.json("GET", "/api/presets")[1]["Lent"]
    bad = {"name": "X", "overrides": {"SPECTRE_WARDEN_EFFORT": "furieux"}}
    assert client.json("POST", "/api/presets", bad)[0] == 400
    assert "Lent" not in client.json("DELETE", "/api/presets/Lent")[1]
    assert client.json("DELETE", "/api/presets/Standard")[0] == 404


def test_cancel_running_run(tmp_path: Path) -> None:
    with _serve(tmp_path, delay=0.01) as client:
        assert client.json("POST", "/api/runs/abc/cancel", {})[0] == 404
        result: dict[str, Any] = {}

        def run() -> None:
            result["payload"] = client.request("POST", "/api/run", {"request": "x", "demo": True})[
                2
            ]

        worker = threading.Thread(target=run)
        worker.start()
        run_id = None
        for _ in range(200):
            runs = client.json("GET", "/api/runs")[1]
            if runs:
                run_id = runs[0]["id"]
                break
            time.sleep(0.02)
        assert run_id
        assert client.json("POST", f"/api/runs/{run_id}/cancel", {})[1] == {"ok": True}
        worker.join(10)
        assert _sse(result["payload"])[-1]["type"] == "cancelled"
        assert client.json("GET", f"/api/runs/{run_id}")[1]["status"] == "cancelled"


def test_client_disconnect_stops_run(tmp_path: Path) -> None:
    with _serve(tmp_path, delay=0.01) as client:
        sock = socket.create_connection(("127.0.0.1", client.port))
        body = json.dumps({"request": "x", "demo": True}).encode()
        sock.sendall(
            b"POST /api/run HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Spectre: 1\r\n"
            b"Content-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n\r\n"
            + body
        )
        sock.recv(4096)
        sock.close()
        status = None
        for _ in range(300):
            runs = client.json("GET", "/api/runs")[1]
            status = runs[0]["status"] if runs else None
            if status not in (None, "running"):
                break
            time.sleep(0.02)
        assert status == "cancelled"


def test_password_flow(tmp_path: Path) -> None:
    with _serve(tmp_path, password="sesame") as client:
        status, data = client.json("GET", "/api/status")
        assert data["auth_required"] and not data["authenticated"] and "agents" not in data
        assert client.json("GET", "/api/runs")[0] == 401
        assert client.json("GET", "/api/login")[0] == 404
        assert client.json("POST", "/api/login", {"password": "non"})[0] == 401
        status, headers, _ = client.request("POST", "/api/login", {"password": "sesame"})
        assert status == 200 and "HttpOnly" in headers["set-cookie"]
        client.cookie = headers["set-cookie"].split(";")[0]
        assert client.json("GET", "/api/runs")[0] == 200
        assert client.json("GET", "/api/logout")[0] == 404
        status, headers, _ = client.request("POST", "/api/logout", {})
        assert "Max-Age=0" in headers["set-cookie"]
        for _ in range(auth_mod.MAX_FAILURES):
            client.json("POST", "/api/login", {"password": "non"})
        assert client.json("POST", "/api/login", {"password": "sesame"})[0] == 429


def test_login_without_password_is_noop(client: Client) -> None:
    assert client.json("POST", "/api/login", {"password": "x"})[1] == {"ok": True}


def test_lan_mode_accepts_any_host(tmp_path: Path) -> None:
    store = Store(tmp_path / "s")
    server = server_mod.make_server("0.0.0.0", 0, store=store, auth=Auth("pw", tmp_path / "k"))
    try:
        assert server.app.allowed_hosts is None  # type: ignore[attr-defined]
    finally:
        server.server_close()


# ---- command line ----------------------------------------------------------------------------


def test_main_refuses_lan_without_password(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert server_mod.main(["--host", "0.0.0.0", "--state-dir", str(tmp_path)]) == 2
    assert "SPECTRE_WEBUI_PASSWORD" in capsys.readouterr().err


def test_main_port_in_use(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        code = server_mod.main(["--port", str(port), "--no-browser", "--state-dir", str(tmp_path)])
    assert code == 1
    assert "impossible d'écouter" in capsys.readouterr().err


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_main_serves_until_ctrl_c(
    host: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(server_mod.webbrowser, "open", opened.append)
    monkeypatch.setenv("SPECTRE_WEBUI_PASSWORD", "pw")

    def interrupted(self: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(server_mod.ThreadingHTTPServer, "serve_forever", interrupted)
    monkeypatch.setattr(server_mod, "lan_addresses", lambda: ["192.168.1.20"])
    assert server_mod.main(["--host", host, "--port", "0", "--state-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    if host == "127.0.0.1":
        assert "http://127.0.0.1:0/" in out and opened
    else:
        assert "192.168.1.20" in out and not opened
    assert "Arrêt de Spectre" in out


def test_lan_addresses_never_loopback() -> None:
    assert all(not ip.startswith("127.") for ip in server_mod.lan_addresses())


def test_lan_addresses_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def __init__(self, *args: Any) -> None:
            raise OSError("no network")

    monkeypatch.setattr(server_mod.socket, "socket", Broken)
    assert server_mod.lan_addresses() == []
    assert any("<adresse" in line for line in server_mod._serve_lines("0.0.0.0", 1))


def test_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_mod, "main", lambda: 0)
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("spectre.web", run_name="__main__")
    assert excinfo.value.code == 0


def test_demo_json_matches_config() -> None:
    from spectre.config import DEFAULT_SPECS, PRICING, WEB_PRESETS

    data = json.loads(
        (Path(server_mod.__file__).parent / "static" / "demo.json").read_text("utf-8")
    )
    assert {a["name"]: a["model"] for a in data["agents"]} == {
        name: spec.model for name, spec in DEFAULT_SPECS.items()
    }
    assert data["prices"] == {m: [p.input_per_mtok, p.output_per_mtok] for m, p in PRICING.items()}
    assert data["presets"] == {k: dict(v) for k, v in WEB_PRESETS.items()}
    assert os.path.exists(Path(server_mod.__file__).parent / "static" / "favicon.svg")


def test_unexpected_crash_marks_run_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def exploding(*args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        raise RuntimeError("bug")
        yield {}  # pragma: no cover

    monkeypatch.setattr(server_mod, "stream_run", exploding)
    monkeypatch.setenv("SPECTRE_WEBUI_LOG", "1")  # also exercises request logging
    with _serve(tmp_path) as client:
        status, _, _ = client.request("POST", "/api/run", {"request": "x", "demo": True})
        assert status == 200
        (summary,) = client.json("GET", "/api/runs")[1]
        assert summary["status"] == "cancelled"


def test_store_ignores_non_object_run(store: Store) -> None:
    (store.runs_dir / "abc.json").write_text("[]", encoding="utf-8")
    with pytest.raises(KeyError):
        store.get_run("abc")


def test_lan_mode_serves_any_host(tmp_path: Path) -> None:
    store = Store(tmp_path / "s")
    server = server_mod.make_server("0.0.0.0", 0, store=store, auth=Auth("pw", tmp_path / "k"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = Client(server.server_address[1])
        assert client.request("GET", "/", headers={"Host": "192.168.1.20:8765"})[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_extra_hosts_behind_a_relay(tmp_path: Path) -> None:
    store = Store(tmp_path / "state")
    server = server_mod.make_server(
        "127.0.0.1",
        0,
        store=store,
        auth=Auth("pw", tmp_path / "k"),
        extra_hosts=["PC.tailnet.ts.net.", " "],
    )
    try:
        assert server.app.allowed_hosts == {  # type: ignore[attr-defined]
            "127.0.0.1",
            "localhost",
            "::1",
            "pc.tailnet.ts.net",
        }
    finally:
        server.server_close()
