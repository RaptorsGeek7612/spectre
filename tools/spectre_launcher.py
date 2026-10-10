"""Spectre's launcher: a tiny always-on page that starts Spectre from the phone.

When Spectre is closed on the PC, nothing answers on its port, so the phone cannot reach it. This
launcher (standard library only, a few MB of memory) stays on, listens on 127.0.0.1:8764, and
`tailscale serve` publishes it on the tailnet under /lanceur. Its page asks for Spectre's
password, then starts Spectre with tools/spectre-assistant.ps1 --silent and sends the phone back
to Spectre once it answers. It can do nothing else.

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
REPO = Path(__file__).resolve().parent.parent

PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#121315"><title>Spectre · Lanceur</title>
<style>
:root { color-scheme: dark; --ground:#121315; --plate:#1b1c1f; --hair:#4a4c52; --bone:#e9e4d8;
  --dim:#8f8a7f; --cyan:#4fc3f7; --green:#8bd450; --red:#ef5f6f; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100dvh; display: grid; place-items: center; padding: 24px 16px;
  background: var(--ground); color: var(--bone);
  font: 16px/1.5 "Barlow Semi Condensed", "Segoe UI", system-ui, sans-serif; }
main { width: min(420px, 100%); display: grid; gap: 18px; padding: 28px 22px;
  border: 1px solid var(--hair); background: var(--plate); }
h1 { margin: 0; font-weight: 500; font-size: 1.9rem; letter-spacing: .32em; text-transform: uppercase; }
p { margin: 0; color: var(--dim); }
#state { color: var(--bone); font-size: 1.1rem; }
#state[data-s="up"] { color: var(--green); } #state[data-s="err"] { color: var(--red); }
label { display: grid; gap: 6px; font-size: .78rem; letter-spacing: .2em; text-transform: uppercase; color: var(--dim); }
input { min-height: 48px; padding: 0 12px; font: inherit; color: var(--bone); background: var(--ground);
  border: 1px solid var(--hair); }
button, a.btn { min-height: 52px; display: grid; place-items: center; border: 1px solid var(--cyan);
  background: none; color: var(--bone); font: inherit; font-size: .9rem; letter-spacing: .22em;
  text-transform: uppercase; text-decoration: none; cursor: pointer; }
button:disabled { opacity: .5; cursor: wait; }
[hidden] { display: none !important; }
</style></head><body><main>
<h1>Spectre</h1>
<p id="state" aria-live="polite">Vérification…</p>
<form id="form" hidden>
  <label>Mot de passe<input type="password" id="pw" autocomplete="current-password" required></label>
  <button type="submit" id="go">Lancer Spectre</button>
</form>
<a class="btn" id="open" href="/assistant.html" hidden>Ouvrir Spectre</a>
<p>Le lanceur reste allumé sur le PC et ne fait qu'une chose : démarrer Spectre.</p>
</main><script>
const $ = (s) => document.querySelector(s);
function show(text, s = "") { $("#state").textContent = text; $("#state").dataset.s = s; }
async function running() {
  try { return (await (await fetch("/lanceur/status", { cache: "no-store" })).json()).running; }
  catch { return false; }
}
async function check() {
  const up = await running();
  $("#form").hidden = up; $("#open").hidden = !up;
  show(up ? "Spectre est en marche." : "Spectre est fermé sur le PC.", up ? "up" : "");
  return up;
}
$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#go").disabled = true;
  try {
    const res = await fetch("/lanceur/start", { method: "POST", headers: { "Content-Type": "application/json", "X-Spectre": "1" },
      body: JSON.stringify({ password: $("#pw").value }) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    $("#pw").value = "";
    show("Démarrage de Spectre… (environ 20 secondes)");
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      if (await running()) { show("Spectre est prêt.", "up"); location.href = "/assistant.html"; return; }
    }
    show("Spectre ne répond pas encore. Réessaie dans un instant.", "err");
  } catch (err) { show(err.message, "err"); }
  finally { $("#go").disabled = false; }
});
check();
</script></body></html>
"""


def spectre_running(url: str = SPECTRE) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/status", timeout=2) as response:  # noqa: S310
            return bool(response.status == 200)
    except OSError:
        return False


def start_spectre() -> None:
    """Start Spectre in the background, without a window, the way the Startup shortcut does."""
    script = REPO / "tools" / "spectre-assistant.ps1"
    subprocess.Popen(  # noqa: S603 - fixed command, no user input
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script),
            "--silent",
        ],
        cwd=REPO,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class Launcher:
    """Password check with a lockout, and the start action (injectable for tests)."""

    def __init__(
        self,
        password: str | None,
        is_running: Callable[[], bool] = spectre_running,
        start: Callable[[], None] = start_spectre,
    ) -> None:
        self.password = password or None
        self.is_running = is_running
        self.start = start
        self._failures = 0
        self._locked_until = 0.0
        self._last_start = 0.0
        self._lock = threading.Lock()

    def launch(self, password: str) -> tuple[HTTPStatus, dict[str, Any]]:
        with self._lock:
            now = time.monotonic()
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
            if self.is_running():
                return HTTPStatus.OK, {"started": False, "running": True}
            if now - self._last_start > 30:  # a second tap while it boots starts nothing more
                self._last_start = now
                self.start()
            return HTTPStatus.OK, {"started": True, "running": False}


class Handler(BaseHTTPRequestHandler):
    server_version = "SpectreLanceur"
    launcher: Launcher

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
                self._json(HTTPStatus.OK, {"running": self.launcher.is_running()})
            case _:
                self._json(HTTPStatus.NOT_FOUND, {"error": "introuvable"})

    def do_POST(self) -> None:  # noqa: N802
        if self._path() != "/start":
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
        self._json(*self.launcher.launch(password))


class ExclusiveHTTPServer(ThreadingHTTPServer):
    """One launcher only: on Windows, SO_REUSEADDR would let a second one bind the same port."""

    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


def make_server(launcher: Launcher, port: int = PORT) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"launcher": launcher})
    server = ExclusiveHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def main() -> int:
    password = os.environ.get(PASSWORD_ENV, "").strip() or None
    try:
        server = make_server(Launcher(password))
    except OSError:
        return 0  # already running
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
