"""`spectre-web`: standard-library HTTP server for the Spectre web interface.

No framework and no build step (same approach as Hermes WebUI): JSON API under `/api/`, live
runs streamed as Server-Sent Events, static files from `spectre/web/static`.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import webbrowser
from collections.abc import Iterator, Sequence
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from spectre import __version__
from spectre.config import (
    AGENT_NAMES,
    EFFORT_LEVELS,
    WEB_PRESETS,
    WORKSPACE_ID_ENV,
    has_api_key,
    load_env,
    load_specs,
)
from spectre.errors import ConfigurationError
from spectre.web.auth import COOKIE_NAME, PASSWORD_ENV, SESSION_TTL_S, Auth
from spectre.web.export import to_markdown, to_share_html
from spectre.web.pipeline import Event, clean_overrides, stream_run
from spectre.web.store import Store, title_from

# Explicit types: on Windows the registry can map .js to text/plain, which breaks ES modules.
_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".webmanifest": "application/manifest+json",
}
MAX_BODY = 2 * 1024 * 1024  # 2 MB: requests and imports, never file uploads of binaries
STATIC_ROOT = files("spectre.web") / "static"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; font-src 'self'; media-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
}


class BodyTooLarge(ValueError):
    """The request body exceeds MAX_BODY (it is left unread, so the connection must close)."""


class App:
    """Shared server state: store, auth, running jobs and demo settings."""

    def __init__(
        self,
        store: Store,
        auth: Auth,
        *,
        demo_delay: float = 0.03,
        allowed_hosts: set[str] | None = None,
    ) -> None:
        self.store = store
        self.auth = auth
        self.demo_delay = demo_delay
        self.allowed_hosts = allowed_hosts  # None = any Host header (LAN mode)
        self.cancels: dict[str, threading.Event] = {}
        self.lock = threading.Lock()
        self.assistant: Any = None  # AssistantService when launched with `spectre-assistant`


class Handler(BaseHTTPRequestHandler):
    """Routes every request; `server.app` carries the shared state."""

    server_version = f"Spectre/{__version__}"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined,no-any-return]

    # ---- plumbing --------------------------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        if os.environ.get("SPECTRE_WEBUI_LOG"):
            super().log_message(format, *args)

    def _send(
        self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if self.close_connection:
            self.send_header("Connection", "close")
        for key, value in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data: Any, extra: dict[str, str] | None = None) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise BodyTooLarge("requête trop volumineuse (2 Mo maximum)")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("le corps de la requête doit être un objet JSON")
        return data

    def _cookie(self) -> str | None:
        cookie = SimpleCookie(self.headers.get("Cookie") or "")
        morsel = cookie.get(COOKIE_NAME)
        return morsel.value if morsel else None

    def _host_ok(self) -> bool:
        allowed = self.app.allowed_hosts
        if allowed is None:
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in allowed

    def _same_origin(self) -> bool:
        """State-changing calls need our custom header (forces CORS preflight) and same origin."""
        if self.headers.get("X-Spectre") != "1":
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urlsplit(origin).netloc == (self.headers.get("Host") or "")

    def _client(self) -> str:
        return str(self.client_address[0])

    # ---- dispatch --------------------------------------------------------------------------

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib naming
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        if not self._host_ok():
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "hôte non autorisé")
            return
        url = urlsplit(self.path)
        path, query = url.path, parse_qs(url.query)
        try:
            if not path.startswith("/api/"):
                if method == "GET":
                    self._static(path)
                else:
                    self._error(HTTPStatus.METHOD_NOT_ALLOWED, "méthode non autorisée")
                return
            if method != "GET" and not self._same_origin():
                self._error(HTTPStatus.FORBIDDEN, "requête refusée (origine)")
                return
            if path in ("/api/login", "/api/logout", "/api/status"):
                getattr(self, "_" + path.removeprefix("/api/"))(method)
                return
            if not self.app.auth.valid(self._cookie()):
                self._error(HTTPStatus.UNAUTHORIZED, "connexion requise")
                return
            self._api(method, path, query)
        except BodyTooLarge as exc:
            # The body was never read: close so its bytes are not parsed as the next request.
            self.close_connection = True
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, str(exc))
        except (ValueError, ConfigurationError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except KeyError:
            self._error(HTTPStatus.NOT_FOUND, "introuvable")

    def _api(self, method: str, path: str, query: dict[str, list[str]]) -> None:
        parts = path.strip("/").split("/")[1:]  # drop "api"
        if parts and parts[0] == "assistant":
            if self.app.assistant is None:
                raise KeyError("assistant non activé")
            from spectre.web.assistant_api import handle

            handle(self, self.app.assistant, method, parts[1:], query)
            return
        store = self.app.store
        match method, parts:
            case "GET", ["runs"]:
                archived = query.get("archived", ["0"])[0] == "1"
                self._json(200, store.list_runs(query=query.get("q", [""])[0], archived=archived))
            case "GET", ["runs", run_id]:
                self._json(200, store.get_run(run_id))
            case "POST", ["runs", run_id]:
                self._json(200, store.update_run(run_id, self._body()))
            case "DELETE", ["runs", run_id]:
                store.delete_run(run_id)
                self._json(200, {"ok": True})
            case "POST", ["runs", run_id, "duplicate"]:
                self._json(200, store.duplicate_run(run_id))
            case "POST", ["runs", run_id, "cancel"]:
                with self.app.lock:
                    event = self.app.cancels.get(run_id)
                if event is None:
                    raise KeyError(run_id)
                event.set()
                self._json(200, {"ok": True})
            case "GET", ["runs", run_id, "export"]:
                self._export(store.get_run(run_id), query.get("format", ["md"])[0])
            case "GET", ["export"]:
                runs = [store.get_run(r["id"]) for r in store.list_runs()]
                runs += [store.get_run(r["id"]) for r in store.list_runs(archived=True)]
                self._send(
                    200,
                    json.dumps(
                        {"spectre": __version__, "runs": runs}, ensure_ascii=False, indent=2
                    ).encode(),
                    "application/json; charset=utf-8",
                    {"Content-Disposition": 'attachment; filename="spectre-historique.json"'},
                )
            case "POST", ["import"]:
                imported = self._body().get("runs")
                if not isinstance(imported, list):
                    raise ValueError("fichier d'import invalide : clé « runs » absente")
                self._json(200, {"imported": store.import_runs(imported)})
            case "POST", ["clear"]:
                self._json(200, {"deleted": store.clear_runs()})
            case "GET", ["settings"]:
                self._json(200, store.get_settings())
            case "POST", ["settings"]:
                self._json(200, store.update_settings(self._body()))
            case "GET", ["presets"]:
                self._json(200, store.get_presets())
            case "POST", ["presets"]:
                body = self._body()
                overrides = clean_overrides(body.get("overrides") or {})
                load_specs({**os.environ, **overrides})  # validates values
                self._json(200, store.save_preset(str(body.get("name", "")), overrides))
            case "DELETE", ["presets", name]:
                self._json(200, store.delete_preset(unquote(name)))
            case "POST", ["run"]:
                self._run(self._body())
            case _:
                raise KeyError(path)

    # ---- endpoints -------------------------------------------------------------------------

    def _status(self, method: str) -> None:
        load_env()
        authed = self.app.auth.valid(self._cookie())
        data: dict[str, Any] = {
            "version": __version__,
            "auth_required": self.app.auth.enabled,
            "authenticated": authed,
            "assistant": self.app.assistant is not None,
        }
        if authed:
            specs = load_specs()
            data.update(
                {
                    "has_api_key": has_api_key(),
                    "workspace_configured": bool(os.environ.get(WORKSPACE_ID_ENV, "").strip()),
                    "agents": [
                        {
                            "name": name,
                            "model": specs[name].model,
                            "max_tokens": specs[name].max_tokens,
                            "effort": specs[name].effort,
                        }
                        for name in AGENT_NAMES
                    ],
                    "effort_levels": list(EFFORT_LEVELS),
                    "builtin_presets": list(WEB_PRESETS),
                    "state_dir": str(self.app.store.root),
                }
            )
        self._json(200, data)

    def _login(self, method: str) -> None:
        if method != "POST":
            raise KeyError("login")
        auth = self.app.auth
        if not auth.enabled:
            self._json(200, {"ok": True})
            return
        client = self._client()
        if auth.locked_out(client):
            self._error(HTTPStatus.TOO_MANY_REQUESTS, "trop d'essais : réessayez dans une minute")
            return
        if not auth.check_password(client, str(self._body().get("password", ""))):
            self._error(HTTPStatus.UNAUTHORIZED, "mot de passe incorrect")
            return
        cookie = (
            f"{COOKIE_NAME}={auth.issue()}; HttpOnly; SameSite=Strict; Path=/; "
            f"Max-Age={SESSION_TTL_S}"
        )
        self._json(200, {"ok": True}, {"Set-Cookie": cookie})

    def _logout(self, method: str) -> None:
        if method != "POST":
            raise KeyError("logout")
        cookie = f"{COOKIE_NAME}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
        self._json(200, {"ok": True}, {"Set-Cookie": cookie})

    def _export(self, run: dict[str, Any], fmt: str) -> None:
        stem = f"spectre-{run['number']:04d}"
        if fmt == "md":
            body, ctype, ext = to_markdown(run).encode(), "text/markdown; charset=utf-8", "md"
        elif fmt == "json":
            body = json.dumps(run, ensure_ascii=False, indent=2).encode()
            ctype, ext = "application/json; charset=utf-8", "json"
        elif fmt == "html":
            body, ctype, ext = to_share_html(run).encode(), "text/html; charset=utf-8", "html"
        else:
            raise ValueError("format inconnu (md, json ou html)")
        self._send(
            200, body, ctype, {"Content-Disposition": f'attachment; filename="{stem}.{ext}"'}
        )

    def _run(self, body: dict[str, Any]) -> None:
        request = str(body.get("request", "")).strip()
        if not request:
            raise ValueError("la demande est vide")
        if len(request) > 100_000:
            raise ValueError("demande trop longue (100 000 caractères maximum)")
        demo = bool(body.get("demo"))
        preset = str(body.get("preset") or "Standard")
        overrides = clean_overrides(body.get("overrides") or {})
        store = self.app.store
        run = store.create_run(request, demo=demo, preset=preset, overrides=overrides)
        if body.get("title"):
            run["title"] = title_from(str(body["title"]))
        cancel = threading.Event()
        with self.app.lock:
            self.app.cancels[run["id"]] = cancel

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()
        self.close_connection = True

        def emit(event: Event) -> None:
            data = json.dumps(event, ensure_ascii=False)
            self.wfile.write(f"event: {event['type']}\ndata: {data}\n\n".encode())
            self.wfile.flush()

        try:
            emit({"type": "run", "run": run})
            events = stream_run(
                request,
                demo=demo,
                overrides=overrides,
                cancel=cancel,
                delay=self.app.demo_delay if demo else 0.0,
            )
            for event in events:
                if event["type"] in ("done", "error", "cancelled"):
                    _finish(run, event)
                    store.save_run(run)
                    event = {**event, "run": run}
                try:
                    emit(event)
                except OSError:
                    cancel.set()  # the browser went away: stop at the next chunk
        finally:
            with self.app.lock:
                self.app.cancels.pop(run["id"], None)
            if run["status"] == "running":
                run["status"] = "cancelled"
                store.save_run(run)

    def _static(self, path: str) -> None:
        name = "index.html" if path in ("", "/") else path.lstrip("/")
        if ".." in name.split("/") or name.startswith("api"):
            raise KeyError(name)
        resource = STATIC_ROOT.joinpath(*name.split("/"))
        if not resource.is_file():
            raise KeyError(name)
        body = resource.read_bytes()
        ctype = _TYPES.get(Path(name).suffix) or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("json"):
            ctype += "; charset=utf-8"
        extra = {"Service-Worker-Allowed": "/"} if name == "sw.js" else None
        self._send(200, body, ctype, extra)


def _finish(run: dict[str, Any], event: Event) -> None:
    for key in ("brief", "draft", "final_text", "usage", "total_cost_usd", "durations"):
        run[key] = event.get(key, run.get(key))
    run["status"] = {"done": "done", "error": "error", "cancelled": "cancelled"}[event["type"]]
    if event["type"] == "error":
        run["error"], run["error_agent"] = event["message"], event["agent"]
    elif event["type"] == "cancelled":
        run["error"], run["error_agent"] = "arrêtée par l'utilisateur", event["agent"]


def make_server(
    host: str,
    port: int,
    *,
    store: Store,
    auth: Auth,
    demo_delay: float = 0.03,
    assistant: Any = None,
) -> ThreadingHTTPServer:
    """Build (but do not start) the HTTP server."""
    local = host in LOCAL_HOSTS
    app = App(store, auth, demo_delay=demo_delay, allowed_hosts=LOCAL_HOSTS if local else None)
    app.assistant = assistant
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.app = app  # type: ignore[attr-defined]
    return server


def lan_addresses() -> list[str]:
    """Best-effort IPv4 addresses of this machine on the local network."""
    found: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1: no packet is sent
            found.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in found if not ip.startswith("127."))


def build_parser() -> argparse.ArgumentParser:
    """Argument parser of `spectre-web`."""
    parser = argparse.ArgumentParser(
        prog="spectre-web", description="Interface web de Spectre (Scout → Scribe → Warden)."
    )
    parser.add_argument("--host", default="127.0.0.1", help="adresse d'écoute (défaut 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="port (défaut 8765)")
    parser.add_argument("--state-dir", type=Path, help="dossier de l'historique et des réglages")
    parser.add_argument("--no-browser", action="store_true", help="n'ouvre pas le navigateur")
    parser.add_argument("--version", action="version", version=f"spectre-web {__version__}")
    return parser


def _serve_lines(host: str, port: int) -> Iterator[str]:
    if host in LOCAL_HOSTS:
        yield f"Spectre est prêt : http://127.0.0.1:{port}/"
        return
    yield f"Spectre écoute sur le réseau local (port {port}) :"
    for ip in lan_addresses() or ["<adresse-de-ce-pc>"]:
        yield f"  http://{ip}:{port}/   ← à ouvrir sur ton téléphone ou ta tablette"


def main(argv: Sequence[str] | None = None) -> int:
    """Start the web interface; return the process exit code."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    load_env()
    store = Store(args.state_dir)
    store.mark_interrupted()
    password = os.environ.get(PASSWORD_ENV, "").strip() or None
    if args.host not in LOCAL_HOSTS and password is None:
        print(
            f"Erreur : pour ouvrir Spectre au réseau ({args.host}), définissez d'abord "
            f"{PASSWORD_ENV} (dans .env), sinon n'importe qui sur le réseau pourrait "
            "lancer des exécutions payantes.",
            file=sys.stderr,
        )
        return 2
    auth = Auth(password, store.root / "secret.key")
    try:
        server = make_server(args.host, args.port, store=store, auth=auth)
    except OSError as exc:
        print(
            f"Erreur : impossible d'écouter sur {args.host}:{args.port} ({exc}).", file=sys.stderr
        )
        return 1
    for line in _serve_lines(args.host, args.port):
        print(line)
    print("Ctrl+C pour arrêter.")
    if not args.no_browser and args.host in LOCAL_HOSTS:
        webbrowser.open(f"http://127.0.0.1:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt de Spectre.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
