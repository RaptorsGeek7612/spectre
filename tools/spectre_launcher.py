"""Spectre's launcher: a tiny always-on page that starts, restarts or stops Spectre from the phone.

When Spectre is closed on the PC, nothing answers on its port, so the phone cannot reach it. This
launcher (standard library only, a few MB of memory) stays on, listens on 127.0.0.1:8764, and
`tailscale serve` publishes it on the tailnet under /lanceur. Its page asks for Spectre's
password, then starts Spectre with tools/spectre-assistant.ps1 --silent (or stops it the way
tools/spectre-stop.cmd does) and sends the phone back to Spectre once it answers. It also tells
whether the PC runs on battery, when it may go to sleep and become unreachable. It can do
nothing else.

    python tools/spectre_launcher.py        (started by tools/spectre-assistant.ps1)
"""

from __future__ import annotations

import hmac
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PORT = 8764
SPECTRE = "http://127.0.0.1:8765"
MOUNT = "/lanceur"
PASSWORD_ENV = "SPECTRE_WEBUI_PASSWORD"
MAX_FAILURES = 5
LOCKOUT_S = 60.0
MAX_BODY = 4096
ACTIONS = ("start", "restart", "stop")
REPO = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("SPECTRE_ASSISTANT_DIR") or Path.home() / ".spectre" / "assistant")
# Written when Spectre is stopped on purpose (launcher, spectre-stop.cmd), removed when it is
# started: the watchdog never restarts what the user stopped.
STOPPED_FLAG = HOME / "stopped"
WATCHDOG_LOG = HOME / "watchdog.log"
WATCH_EVERY_S = 30.0
STARTUP_GRACE_S = 120.0  # Spectre takes ~20 s to answer, up to 2 min at Windows sign-in
MAX_RESTARTS = 3  # per hour: beyond that something is broken, restarting would only loop
RESTART_WINDOW_S = 3600.0
# A browser or phone that closes a page while it loads: normal, not worth a traceback in the log.
QUIET_ERRORS = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError)

PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#121315"><title>Spectre · Lanceur</title>
<style>
:root { color-scheme: dark; --ground:#121315; --plate:#1b1c1f; --hair:#4a4c52; --bone:#e9e4d8;
  --dim:#8f8a7f; --cyan:#4fc3f7; --green:#8bd450; --yellow:#ffd23f; --red:#ef5f6f; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100dvh; display: grid; place-items: center; padding: 24px 16px;
  background: var(--ground); color: var(--bone);
  font: 16px/1.5 "Barlow Semi Condensed", "Segoe UI", system-ui, sans-serif; }
main { width: min(420px, 100%); display: grid; gap: 16px; padding: 28px 22px;
  border: 1px solid var(--hair); background: var(--plate); }
h1 { margin: 0; font-weight: 500; font-size: 1.9rem; letter-spacing: .32em; text-transform: uppercase; }
p { margin: 0; color: var(--dim); }
#state { color: var(--bone); font-size: 1.1rem; }
#state[data-s="up"] { color: var(--green); } #state[data-s="err"] { color: var(--red); }
#power { padding: 10px 12px; border: 1px dashed var(--yellow); color: var(--yellow); }
label { display: grid; gap: 6px; font-size: .78rem; letter-spacing: .2em; text-transform: uppercase; color: var(--dim); }
input { min-height: 48px; padding: 0 12px; font: inherit; color: var(--bone); background: var(--ground);
  border: 1px solid var(--hair); }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
button, a.btn { min-height: 52px; display: grid; place-items: center; border: 1px solid var(--cyan);
  background: none; color: var(--bone); font: inherit; font-size: .9rem; letter-spacing: .2em;
  text-transform: uppercase; text-decoration: none; cursor: pointer; }
button.quiet { border-color: var(--hair); color: var(--dim); }
button.danger { border-color: var(--red); }
button:disabled { opacity: .5; cursor: wait; }
[hidden] { display: none !important; }
</style></head><body><main>
<h1>Spectre</h1>
<p id="state" aria-live="polite">Vérification…</p>
<p id="power" hidden></p>
<a class="btn" id="open" href="/assistant.html" hidden>Ouvrir Spectre</a>
<form id="form" hidden>
  <label>Mot de passe<input type="password" id="pw" autocomplete="current-password" required></label>
  <button type="submit" id="go" data-action="start">Lancer Spectre</button>
  <div class="row" id="manage" hidden>
    <button type="submit" class="quiet" data-action="restart">Redémarrer</button>
    <button type="submit" class="danger" data-action="stop">Arrêter</button>
  </div>
</form>
<p>Le lanceur reste allumé sur le PC et ne fait qu'une chose : démarrer, redémarrer ou arrêter Spectre.</p>
</main><script>
const $ = (s) => document.querySelector(s);
function show(text, s = "") { $("#state").textContent = text; $("#state").dataset.s = s; }
async function status() {
  try { return await (await fetch("/lanceur/status", { cache: "no-store" })).json(); }
  catch { return { running: false, unreachable: true }; }
}
function power(p) {
  const box = $("#power");
  box.hidden = !(p && p.on_battery);
  if (p && p.on_battery) box.textContent = `Le PC est sur batterie${p.percent != null ? ` (${p.percent} %)` : ""} : il peut se mettre en veille, et Spectre ne sera plus joignable. Branche-le pour qu'il reste disponible.`;
}
async function check() {
  const s = await status();
  power(s.power);
  $("#form").hidden = false;
  $("#open").hidden = !s.running; $("#manage").hidden = !s.running; $("#go").hidden = s.running;
  show(s.running ? "Spectre est en marche." : "Spectre est fermé sur le PC.", s.running ? "up" : "");
  return s.running;
}
async function waitFor(up) {
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    if ((await status()).running === up) return true;
  }
  return false;
}
$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const action = (e.submitter && e.submitter.dataset.action) || "start";
  if (action === "stop" && !confirm("Arrêter Spectre sur le PC ?")) return;
  const buttons = [...document.querySelectorAll("#form button")];
  buttons.forEach((b) => { b.disabled = true; });
  try {
    const res = await fetch(`/lanceur/${action}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Spectre": "1" },
      body: JSON.stringify({ password: $("#pw").value }) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    $("#pw").value = "";
    if (action === "stop") {
      show("Arrêt de Spectre…");
      await waitFor(false); await check(); show("Spectre est arrêté.");
      return;
    }
    show(action === "restart" ? "Redémarrage de Spectre… (environ 30 secondes)" : "Démarrage de Spectre… (environ 20 secondes)");
    if (action === "restart") await waitFor(false);
    if (await waitFor(true)) { show("Spectre est prêt.", "up"); location.href = "/assistant.html"; return; }
    show("Spectre ne répond pas encore. Réessaie dans un instant.", "err");
  } catch (err) { show(err.message, "err"); }
  finally { buttons.forEach((b) => { b.disabled = false; }); }
});
check();
setInterval(check, 60000);
</script></body></html>
"""


def spectre_running(url: str = SPECTRE) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/status", timeout=2) as response:  # noqa: S310
            return bool(response.status == 200)
    except OSError:
        return False


def power_status() -> dict[str, Any]:
    """On battery or mains, and the charge, from Windows (empty elsewhere or when unknown)."""
    if sys.platform != "win32":
        return {}
    import ctypes

    class SystemPowerStatus(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_ubyte),
            ("BatteryFlag", ctypes.c_ubyte),
            ("BatteryLifePercent", ctypes.c_ubyte),
            ("SystemStatusFlag", ctypes.c_ubyte),
            ("BatteryLifeTime", ctypes.c_ulong),
            ("BatteryFullLifeTime", ctypes.c_ulong),
        ]

    state = SystemPowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(state)):
        return {}
    return {
        "on_battery": state.ACLineStatus == 0,
        "percent": None if state.BatteryLifePercent == 255 else int(state.BatteryLifePercent),
    }


def _hidden() -> dict[str, Any]:
    return {
        "cwd": REPO,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }


def start_spectre() -> None:
    """Start Spectre in the background, without a window, the way the Startup shortcut does."""
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(REPO / "tools" / "spectre-assistant.ps1"),
        "--silent",
    ]
    subprocess.Popen(command, **_hidden())  # noqa: S603 - fixed command


def stop_spectre() -> None:
    """Stop Spectre like tools/spectre-stop.cmd (the launcher itself keeps running)."""
    command = ["cmd.exe", "/c", str(REPO / "tools" / "spectre-stop.cmd")]
    subprocess.run(command, timeout=30, check=False, **_hidden())  # noqa: S603


def mark_stopped(stopped: bool, flag: Path | None = None) -> None:
    """Remember that the user stopped Spectre on purpose (or forget it when it starts)."""
    flag = flag or STOPPED_FLAG
    try:
        if stopped:
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        else:
            flag.unlink(missing_ok=True)
    except OSError:
        pass  # a read-only or missing folder must not break the launcher


def free_memory_mb() -> int | None:
    """Free physical memory in MB on Windows (None elsewhere or when unknown)."""
    if sys.platform != "win32":
        return None
    import ctypes

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullAvailPhys // (1024 * 1024))


def log_tail(path: Path, lines: int = 12) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [line for line in text.splitlines() if line.strip()][-lines:]


class Watchdog:
    """Restarts Spectre when it stops on its own, and writes down the circumstances.

    Spectre has been seen to vanish without a word in its log. Every WATCH_EVERY_S the
    watchdog checks that it answers; after two silent checks in a row it notes the time, the
    free memory and the end of Spectre's log in watchdog.log, then starts it again. It leaves
    alone a Spectre the user stopped (STOPPED_FLAG), one that is still starting, and gives up
    after MAX_RESTARTS restarts in an hour: something is then broken and needs a person.
    """

    def __init__(
        self,
        launcher: Launcher,
        *,
        flag: Path | None = None,
        log: Path | None = None,
        spectre_log: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        memory: Callable[[], int | None] = free_memory_mb,
    ) -> None:
        self.launcher = launcher
        self.flag = flag or STOPPED_FLAG
        self.log = log or WATCHDOG_LOG
        self.spectre_log = spectre_log or HOME / "spectre.log"
        self.clock = clock
        self.memory = memory
        self.silent_checks = 0
        self.restarts: list[float] = []
        self.gave_up = False

    def note(self, text: str) -> None:
        try:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            with self.log.open("a", encoding="utf-8") as out:
                out.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        except OSError:
            pass

    def check(self) -> str:
        """One look; returns what it did (for the tests and the log)."""
        if self.launcher.is_running():
            self.silent_checks = 0
            self.gave_up = False
            return "ok"
        if self.flag.exists():
            self.silent_checks = 0
            return "stopped"  # stopped on purpose: not our business
        now = self.clock()
        if now - self.launcher._last_start < STARTUP_GRACE_S:
            return "starting"
        self.silent_checks += 1
        if self.silent_checks < 2:
            return "silent"  # one silent look may be a busy moment: look again first
        self.restarts = [t for t in self.restarts if now - t < RESTART_WINDOW_S]
        if len(self.restarts) >= MAX_RESTARTS:
            if not self.gave_up:
                self.gave_up = True
                self.note(
                    f"Spectre s'est arrêté {MAX_RESTARTS + 1} fois en une heure : je ne le "
                    "relance plus. Lance-le à la main (raccourci « Spectre » ou lanceur)."
                )
            return "gave-up"
        free = self.memory()
        memory = f"{free} Mo de mémoire libre" if free is not None else "mémoire libre inconnue"
        tail = "\n".join(f"    {line}" for line in log_tail(self.spectre_log))
        self.note(
            f"Spectre ne répond plus ({memory}) : je le relance.\n"
            f"  Fin de spectre.log :\n{tail or '    (vide)'}"
        )
        self.restarts.append(now)
        self.silent_checks = 0
        with self.launcher._lock:
            self.launcher._last_start = now
            self.launcher.start()
        return "restarted"

    def run(self, stop: threading.Event) -> None:  # pragma: no cover - thread loop
        while not stop.wait(WATCH_EVERY_S):
            try:
                self.check()
            except Exception as exc:  # noqa: BLE001 - the watchdog must never die
                self.note(f"erreur de la surveillance : {exc!r}")


class Launcher:
    """Password check with a lockout, and the actions (injectable for tests)."""

    def __init__(
        self,
        password: str | None,
        is_running: Callable[[], bool] = spectre_running,
        start: Callable[[], None] = start_spectre,
        stop: Callable[[], None] = stop_spectre,
        wait_stopped: Callable[[], None] | None = None,
    ) -> None:
        self.password = password or None
        self.is_running = is_running
        self.start = start
        self.stop = stop
        self.wait_stopped = wait_stopped or self._wait_stopped
        self._failures = 0
        self._locked_until = 0.0
        self._last_start = 0.0
        self._lock = threading.Lock()

    def _wait_stopped(self) -> None:
        for _ in range(30):
            if not self.is_running():
                return
            time.sleep(0.5)

    def _check(self, password: str, now: float) -> tuple[HTTPStatus, dict[str, Any]] | None:
        """An error to send back, or None when the password is right."""
        if self.password is None:
            return HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "aucun mot de passe défini sur le PC (tools\\spectre-password.cmd)"
            }
        if now < self._locked_until:
            return HTTPStatus.TOO_MANY_REQUESTS, {
                "error": "trop d'essais : réessaie dans une minute"
            }
        if not hmac.compare_digest(password.encode(), self.password.encode()):
            self._failures += 1
            if self._failures >= MAX_FAILURES:
                self._failures, self._locked_until = 0, now + LOCKOUT_S
            return HTTPStatus.UNAUTHORIZED, {"error": "mot de passe incorrect"}
        self._failures = 0
        return None

    def act(self, action: str, password: str) -> tuple[HTTPStatus, dict[str, Any]]:
        with self._lock:
            now = time.monotonic()
            refused = self._check(password, now)
            if refused:
                return refused
            running = self.is_running()
            if action == "stop":
                mark_stopped(True)
                if running:
                    self.stop()
                return HTTPStatus.OK, {"stopped": running}
            mark_stopped(False)
            if action == "restart" and running:
                self.stop()
                self.wait_stopped()
                mark_stopped(False)  # spectre-stop.cmd has just marked it stopped on purpose
                self._last_start = now
                self.start()
                return HTTPStatus.OK, {"restarted": True}
            if running:
                return HTTPStatus.OK, {"started": False, "running": True}
            if now - self._last_start > 30:  # a second tap while it boots starts nothing more
                self._last_start = now
                self.start()
            return HTTPStatus.OK, {"started": True, "running": False}

    def launch(self, password: str) -> tuple[HTTPStatus, dict[str, Any]]:
        return self.act("start", password)


class Handler(BaseHTTPRequestHandler):
    server_version = "SpectreLanceur"
    launcher: Launcher
    power: Callable[[], dict[str, Any]] = staticmethod(power_status)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    def _path(self) -> str:
        """The path without the query and without /lanceur, whether tailscale strips it or not."""
        path = self.path.split("?", 1)[0]
        if path == MOUNT or path.startswith(MOUNT + "/"):
            path = path[len(MOUNT) :]
        return path or "/"

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, data: dict[str, Any]) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        match self._path():
            case "/":
                self._send(HTTPStatus.OK, PAGE.encode(), "text/html; charset=utf-8")
            case "/status":
                self._json(
                    HTTPStatus.OK, {"running": self.launcher.is_running(), "power": self.power()}
                )
            case _:
                self._json(HTTPStatus.NOT_FOUND, {"error": "introuvable"})

    def do_POST(self) -> None:  # noqa: N802
        action = self._path().strip("/")
        if action not in ACTIONS:
            self._json(HTTPStatus.NOT_FOUND, {"error": "introuvable"})
            return
        if self.headers.get("X-Spectre") != "1":  # forces a CORS preflight: same origin only
            self._json(HTTPStatus.FORBIDDEN, {"error": "requête refusée (origine)"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self.close_connection = True
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "requête trop volumineuse"})
            return
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
            password = str(data.get("password", "")) if isinstance(data, dict) else ""
        except ValueError:
            password = ""
        self._json(*self.launcher.act(action, password))


class ExclusiveHTTPServer(ThreadingHTTPServer):
    """One launcher only: on Windows, SO_REUSEADDR would let a second one bind the same port."""

    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()

    def handle_error(self, request: Any, client_address: Any) -> None:
        if isinstance(sys.exc_info()[1], QUIET_ERRORS):
            return
        super().handle_error(request, client_address)


def make_server(launcher: Launcher, port: int = PORT) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"launcher": launcher})
    server = ExclusiveHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def main() -> int:
    password = os.environ.get(PASSWORD_ENV, "").strip() or None
    launcher = Launcher(password)
    try:
        server = make_server(launcher)
    except OSError:
        return 0  # already running
    stop = threading.Event()
    launcher._last_start = time.monotonic()  # started with Spectre: give it time to answer
    watchdog = Watchdog(launcher)
    threading.Thread(target=watchdog.run, args=(stop,), name="watchdog", daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
