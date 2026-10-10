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


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never touch the real ~/.spectre: the stop mark and the logs go to a temporary folder."""
    home = tmp_path / "spectre-home"
    monkeypatch.setattr(launcher_mod, "HOME", home)
    monkeypatch.setattr(launcher_mod, "STOPPED_FLAG", home / "stopped")
    monkeypatch.setattr(launcher_mod, "WATCHDOG_LOG", home / "watchdog.log")
    return home


class State:
    def __init__(self) -> None:
        self.running = False
        self.starts = 0
        self.stops = 0
        self.log: list[str] = []

    def start(self) -> None:
        self.starts += 1
        self.log.append("start")

    def stop(self) -> None:
        self.stops += 1
        self.running = False
        self.log.append("stop")


def _launcher(password: str | None = "secret") -> tuple[Any, State]:
    state = State()
    launcher = launcher_mod.Launcher(
        password,
        lambda: state.running,
        state.start,
        state.stop,
        lambda: state.log.append("waited"),
    )
    return launcher, state


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


def test_stop_and_restart() -> None:
    launcher, state = _launcher()
    assert launcher.act("stop", "faux")[0] == HTTPStatus.UNAUTHORIZED and state.stops == 0
    assert launcher.act("stop", "secret") == (HTTPStatus.OK, {"stopped": False})  # not running
    state.running = True
    assert launcher.act("stop", "secret") == (HTTPStatus.OK, {"stopped": True})
    assert state.stops == 1 and state.running is False
    state.running = True
    assert launcher.act("restart", "secret") == (HTTPStatus.OK, {"restarted": True})
    assert state.log[-3:] == ["stop", "waited", "start"]
    # restart while stopped: a plain start
    assert launcher.act("restart", "secret")[1] == {"started": True, "running": False}


def test_stop_mark(_home: Path) -> None:
    """Stopping on purpose leaves a mark the watchdog respects; any start removes it."""
    launcher, state = _launcher()
    flag = _home / "stopped"
    launcher.act("stop", "secret")
    assert flag.exists()
    launcher.act("start", "secret")
    assert not flag.exists()

    def stop_like_the_cmd() -> None:  # spectre-stop.cmd marks it stopped on purpose too
        state.stop()
        launcher_mod.mark_stopped(True)

    launcher.stop = stop_like_the_cmd
    state.running = True
    assert launcher.act("restart", "secret") == (HTTPStatus.OK, {"restarted": True})
    assert not flag.exists()  # a restart is not a stop
    launcher_mod.mark_stopped(True, _home / "missing" / "dir" / "stopped")  # creates the folder
    launcher_mod.mark_stopped(False, _home / "nothing")  # removing a missing mark is fine
    blocked = _home / "blocked"
    blocked.mkdir()
    launcher_mod.mark_stopped(True, blocked)  # a folder in the way: ignored, no crash


def _watchdog(_home: Path, clock: list[float]) -> tuple[Any, State, Any]:
    launcher, state = _launcher()
    (_home / "spectre.log").parent.mkdir(parents=True, exist_ok=True)
    (_home / "spectre.log").write_text("Spectre est prêt\n\nCaméra active\n", encoding="utf-8")
    dog = launcher_mod.Watchdog(
        launcher,
        spectre_log=_home / "spectre.log",
        clock=lambda: clock[0],
        memory=lambda: 812,
    )
    return dog, state, launcher


def test_watchdog_restarts_a_silent_spectre(_home: Path) -> None:
    clock = [1000.0]
    dog, state, launcher = _watchdog(_home, clock)
    state.running = True
    assert dog.check() == "ok"
    state.running = False
    assert dog.check() == "silent" and state.starts == 0  # one silent look is not enough
    assert dog.check() == "restarted" and state.starts == 1
    log = (_home / "watchdog.log").read_text(encoding="utf-8")
    assert "ne répond plus (812 Mo de mémoire libre)" in log and "Caméra active" in log
    assert dog.check() == "starting"  # within the start-up grace: wait
    clock[0] += launcher_mod.STARTUP_GRACE_S + 1
    state.running = True
    assert dog.check() == "ok" and dog.silent_checks == 0


def test_watchdog_respects_a_stop_on_purpose(_home: Path) -> None:
    clock = [1000.0]
    dog, state, _ = _watchdog(_home, clock)
    launcher_mod.mark_stopped(True)
    for _ in range(4):
        assert dog.check() == "stopped"
    assert state.starts == 0 and not (_home / "watchdog.log").exists()


def test_watchdog_gives_up_after_too_many_restarts(_home: Path) -> None:
    clock = [1000.0]
    dog, state, _ = _watchdog(_home, clock)
    dog.memory = lambda: None
    dog.spectre_log = _home / "absent.log"
    for _ in range(launcher_mod.MAX_RESTARTS):
        dog.check()
        assert dog.check() == "restarted"
        clock[0] += launcher_mod.STARTUP_GRACE_S + 1
    dog.check()
    assert dog.check() == "gave-up" and dog.check() == "gave-up"
    assert state.starts == launcher_mod.MAX_RESTARTS
    log = (_home / "watchdog.log").read_text(encoding="utf-8")
    assert "mémoire libre inconnue" in log and "(vide)" in log
    assert log.count("je ne le relance plus") == 1  # said once, not every 30 s
    state.running = True
    assert dog.check() == "ok" and not dog.gave_up  # back up: it watches again
    clock[0] += launcher_mod.RESTART_WINDOW_S  # an hour later the count starts over
    state.running = False
    dog.check()
    assert dog.check() == "restarted"


def test_watchdog_log_and_memory_never_break(_home: Path) -> None:
    clock = [1000.0]
    dog, _, _ = _watchdog(_home, clock)
    dog.log = _home  # a folder: writing fails, quietly
    dog.note("rien")
    assert launcher_mod.log_tail(_home / "absent.log") == []
    free = launcher_mod.free_memory_mb()
    assert free is None or free > 0


def test_wait_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([True, True, False])
    launcher = launcher_mod.Launcher("s", lambda: next(answers))
    monkeypatch.setattr(launcher_mod.time, "sleep", lambda s: None)
    launcher.wait_stopped()
    with pytest.raises(StopIteration):  # it stopped asking once Spectre was down
        next(answers)
    never = launcher_mod.Launcher("s", lambda: True)
    never.wait_stopped()  # gives up after a while


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
    status_body = json.loads(_request(port, "GET", "/lanceur/status")[1])
    assert status_body["running"] is False and isinstance(status_body["power"], dict)
    assert _request(port, "GET", "/nope")[0] == 404
    same = {"X-Spectre": "1", "Content-Type": "application/json"}
    assert _request(port, "POST", "/lanceur/start", {"password": "secret"})[0] == 403
    assert _request(port, "POST", "/lanceur/start", {"password": "x"}, same)[0] == 401
    assert _request(port, "POST", "/lanceur/start", b"pas du json", same)[0] == 401
    assert _request(port, "POST", "/lanceur/start", b"[]", same)[0] == 401
    status, body = _request(port, "POST", "/lanceur/start", {"password": "secret"}, same)
    assert status == 200 and json.loads(body)["started"] is True and state.starts == 1
    assert _request(port, "POST", "/autre", {}, same)[0] == 404
    state.running = True
    status, body = _request(port, "POST", "/lanceur/stop", {"password": "secret"}, same)
    assert status == 200 and json.loads(body) == {"stopped": True} and state.stops == 1
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


def test_stop_command_and_power(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[Any] = []
    monkeypatch.setattr(launcher_mod.subprocess, "run", lambda *a, **kw: ran.append((a, kw)))
    launcher_mod.stop_spectre()
    (command,), options = ran[0]
    assert command[:2] == ["cmd.exe", "/c"] and command[2].endswith("spectre-stop.cmd")
    assert options["timeout"] == 30
    power = launcher_mod.power_status()
    assert power == {} or set(power) == {"on_battery", "percent"}
    monkeypatch.setattr(launcher_mod.sys, "platform", "linux")
    assert launcher_mod.power_status() == {}


def test_quiet_connection_errors(capsys: pytest.CaptureFixture[str]) -> None:
    launcher, _ = _launcher()
    server = launcher_mod.make_server(launcher, port=0)
    try:
        for error in (ConnectionResetError("reset"), ValueError("vraie erreur")):
            try:
                raise error
            except Exception:  # noqa: BLE001 - handle_error reads the exception in flight
                server.handle_error(None, ("127.0.0.1", 1))
    finally:
        server.server_close()
    err = capsys.readouterr().err
    assert "vraie erreur" in err and "reset" not in err


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
