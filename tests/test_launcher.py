"""The always-on launcher (tools/spectre_launcher.py) that starts Spectre from the phone."""

from __future__ import annotations

import http.client
import importlib.util
import json
import threading
from collections.abc import Iterator
from http import HTTPStatus
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "spectre_launcher", ROOT / "tools" / "spectre_launcher.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher_mod = _load()


class State:
    def __init__(self) -> None:
        self.running = False
        self.starts = 0

    def start(self) -> None:
        self.starts += 1


def _launcher(password: str | None = "secret") -> tuple[Any, State]:
    state = State()
    return launcher_mod.Launcher(password, lambda: state.running, state.start), state


def test_launch_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    launcher, state = _launcher()
    status, body = launcher.launch("faux")
    assert status == HTTPStatus.UNAUTHORIZED and state.starts == 0
    assert launcher.launch("secret") == (HTTPStatus.OK, {"started": True, "running": False})
    assert launcher.launch("secret")[0] == HTTPStatus.OK and state.starts == 1  # booting
    state.running = True
    assert launcher.launch("secret") == (HTTPStatus.OK, {"started": False, "running": True})
    clock = [launcher._last_start + 100]
    monkeypatch.setattr(launcher_mod.time, "monotonic", lambda: clock[0])
    state.running = False
    assert launcher.launch("secret")[1]["started"] is True and state.starts == 2
    for _ in range(launcher_mod.MAX_FAILURES):
        launcher.launch("faux")
    status, body = launcher.launch("secret")  # locked, even with the right password
    assert status == HTTPStatus.TOO_MANY_REQUESTS and "minute" in body["error"]
    clock[0] += launcher_mod.LOCKOUT_S + 1
    assert launcher.launch("secret")[0] == HTTPStatus.OK


def test_without_password() -> None:
    launcher, state = _launcher(None)
    status, body = launcher.launch("")
    assert status == HTTPStatus.SERVICE_UNAVAILABLE and "mot de passe" in body["error"]
    assert state.starts == 0


@pytest.fixture
def served() -> Iterator[tuple[int, State]]:
    launcher, state = _launcher()
    server = launcher_mod.make_server(launcher, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1], state
    finally:
        server.shutdown()
        server.server_close()


def _request(
    port: int, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    conn.request(method, path, body=data, headers=headers or {})
    response = conn.getresponse()
    result = response.status, response.read()
    conn.close()
    return result


def test_http(served: tuple[int, State]) -> None:
    port, state = served
    for path in ("/", "/lanceur/", "/lanceur", "/lanceur/?x=1"):
        status, page = _request(port, "GET", path)
        assert status == 200 and b"Lancer Spectre" in page
    assert json.loads(_request(port, "GET", "/lanceur/status")[1]) == {"running": False}
    assert _request(port, "GET", "/nope")[0] == 404
    same = {"X-Spectre": "1", "Content-Type": "application/json"}
    assert _request(port, "POST", "/lanceur/start", {"password": "secret"})[0] == 403
    assert _request(port, "POST", "/lanceur/start", {"password": "x"}, same)[0] == 401
    assert _request(port, "POST", "/lanceur/start", b"pas du json", same)[0] == 401
    assert _request(port, "POST", "/lanceur/start", b"[]", same)[0] == 401
    status, body = _request(port, "POST", "/lanceur/start", {"password": "secret"}, same)
    assert status == 200 and json.loads(body)["started"] is True and state.starts == 1
    assert _request(port, "POST", "/autre", {}, same)[0] == 404
    big = {**same, "Content-Length": str(launcher_mod.MAX_BODY + 1)}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest("POST", "/lanceur/start")
    for key, value in big.items():
        conn.putheader(key, value)
    conn.endheaders()
    assert conn.getresponse().status == 413
    conn.close()


def test_spectre_running_and_start(monkeypatch: pytest.MonkeyPatch) -> None:
    assert launcher_mod.spectre_running("http://127.0.0.1:9") is False
    launched: list[Any] = []
    monkeypatch.setattr(launcher_mod.subprocess, "Popen", lambda *a, **kw: launched.append(a))
    launcher_mod.start_spectre()
    command = launched[0][0]
    assert command[0] == "powershell.exe" and command[-1] == "--silent"
    assert command[-2].endswith("spectre-assistant.ps1")


def test_main(monkeypatch: pytest.MonkeyPatch) -> None:
    def busy(*a: Any, **kw: Any) -> Any:
        raise OSError("port pris")

    monkeypatch.setattr(launcher_mod, "make_server", busy)
    assert launcher_mod.main() == 0  # another launcher already listens

    class Server:
        closed = False

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            Server.closed = True

    monkeypatch.setattr(launcher_mod, "make_server", lambda launcher: Server())
    monkeypatch.setenv(launcher_mod.PASSWORD_ENV, " secret ")
    assert launcher_mod.main() == 0 and Server.closed


def test_one_launcher_per_port() -> None:
    launcher, _ = _launcher()
    first = launcher_mod.make_server(launcher, port=0)
    try:
        with pytest.raises(OSError):
            launcher_mod.make_server(launcher, port=first.server_address[1])
    finally:
        first.server_close()


def test_one_spectre_per_port(tmp_path: Path) -> None:
    from spectre.web import server as server_mod
    from spectre.web.auth import Auth
    from spectre.web.store import Store

    store = Store(tmp_path / "state")
    auth = Auth(None, store.root / "k")
    first = server_mod.make_server("127.0.0.1", 0, store=store, auth=auth)
    try:
        with pytest.raises(OSError):
            server_mod.make_server("127.0.0.1", first.server_address[1], store=store, auth=auth)
    finally:
        first.server_close()
