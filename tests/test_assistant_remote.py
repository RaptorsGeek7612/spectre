"""Tests for the QR code encoder, the Tailscale remote access and the agents view (no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.assistant import qrcode, remote
from spectre.assistant.remote import Remote
from spectre.assistant.service import AssistantService
from spectre.web import assistant_api
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client

URL = "https://monpc.tail0000.ts.net/assistant.html"

# ---- QR code ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "size"),
    [("a", 21), (URL, 33), ("x" * 60, 33), ("y" * 150, 49), ("z" * 210, 57)],
)
def test_qr_version_and_function_patterns(text: str, size: int) -> None:
    rows = qrcode.matrix(text)
    assert len(rows) == size and all(len(r) == size for r in rows)
    finder = [[max(abs(x - 3), abs(y - 3)) not in (2, 4) for x in range(7)] for y in range(7)]
    assert [r[:7] for r in rows[:7]] == finder
    assert [r[-7:] for r in rows[:7]] == finder
    assert [r[:7] for r in rows[-7:]] == finder
    assert [rows[6][x] for x in range(8, size - 8)] == [x % 2 == 0 for x in range(8, size - 8)]
    assert rows[size - 8][8] is True  # the dark module


@pytest.mark.parametrize("text", ["a", URL, "https://exemple.fr/" + "é" * 40, "z" * 210])
def test_qr_decodes(text: str) -> None:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    modules = np.array(qrcode.matrix(text), dtype=np.uint8)
    image = (np.pad(1 - modules, 4, constant_values=1) * 255).astype(np.uint8)
    image = cv2.resize(image, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
    assert cv2.QRCodeDetector().detectAndDecode(image)[0] == text


def test_qr_svg_and_limit() -> None:
    picture = qrcode.svg("a")
    assert picture.startswith("<svg") and 'viewBox="0 0 29 29"' in picture
    assert picture.count("h1v1h-1z") == sum(map(sum, qrcode.matrix("a")))
    with pytest.raises(ValueError, match="trop long"):
        qrcode.matrix("x" * 300)


# ---- Tailscale ----------------------------------------------------------------------------

RUNNING = {"BackendState": "Running", "Self": {"DNSName": "monpc.tail0000.ts.net."}}
SERVING = {
    "Web": {"monpc.tail0000.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}}}
}


class FakeTailscale:
    def __init__(self, status: Any = RUNNING, serve: Any = None, code: int = 0) -> None:
        self.outputs = {"status": status, "serve": serve or {}}
        self.code = code
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, command: list[str], timeout: float) -> tuple[int, str]:
        self.calls.append((command, timeout))
        if "--bg" in command:
            return self.code, ""
        out = self.outputs[command[1]]
        return 0, out if isinstance(out, str) else json.dumps(out)


def test_remote_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(remote, "find_tailscale", lambda: None)
    info = Remote(8765).status(True)
    assert info["installed"] is False and info["url"] == "" and "Installe" in info["hint"]
    assert Remote(8765).enable() is False


@pytest.mark.parametrize(
    "status", [{"BackendState": "Stopped"}, "pas du json", "[]", {"BackendState": "Running"}]
)
def test_remote_stopped(status: Any) -> None:
    info = Remote(8765, "ts", FakeTailscale(status=status)).status(True)
    assert info["running"] is False or info["dns"] == ""
    assert info["url"] == "" and "arrêté" in info["hint"]


def test_remote_states() -> None:
    no_password = Remote(8765, "ts", FakeTailscale()).status(False)
    assert no_password["url"] == URL and no_password["serving"] is False
    assert "mot de passe" in no_password["hint"] and no_password["qr"].startswith("<svg")
    off = Remote(8765, "ts", FakeTailscale()).status(True)
    assert "Active" in off["hint"]
    on = Remote(8765, "ts", FakeTailscale(serve=SERVING)).status(True)
    assert on["serving"] is True and "Scanne" in on["hint"]
    assert Remote(9000, "ts", FakeTailscale(serve=SERVING)).status(True)["serving"] is False
    assert on["launcher_url"] == ""
    both = {
        "Web": {
            "x": {
                "Handlers": {
                    "/": {"Proxy": "http://127.0.0.1:8765"},
                    "/lanceur": {"Proxy": "http://127.0.0.1:8764"},
                }
            }
        }
    }
    with_launcher = Remote(8765, "ts", FakeTailscale(serve=both)).status(True)
    assert with_launcher["launcher_url"] == "https://monpc.tail0000.ts.net/lanceur/"


def test_remote_enable() -> None:
    fake = FakeTailscale()
    assert Remote(8765, "ts", fake).enable() is True
    assert fake.calls == [(["ts", "serve", "--bg", "http://127.0.0.1:8765"], 10.0)]
    assert Remote(8765, "ts", FakeTailscale(code=1)).enable() is False


def test_find_tailscale_and_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(remote.shutil, "which", lambda name: "/bin/tailscale")
    assert remote.find_tailscale() == "/bin/tailscale"
    monkeypatch.setattr(remote.shutil, "which", lambda name: None)
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    assert remote.find_tailscale() is None
    (tmp_path / "Tailscale").mkdir()
    (tmp_path / "Tailscale" / "tailscale.exe").write_bytes(b"")
    assert remote.find_tailscale() == str(tmp_path / "Tailscale" / "tailscale.exe")
    assert remote._run([str(tmp_path / "absent.exe")], 1.0) == (-1, "")
    assert remote._run([sys.executable, "-c", "print('ok')"], 30.0) == (0, "ok\n")
    failing = Remote(8765, "ts", lambda command, timeout: (1, json.dumps(RUNNING)))
    assert failing.status(True)["running"] is False


# ---- web API ------------------------------------------------------------------------------


def test_spectre_log_skips_disconnects(capsys: pytest.CaptureFixture[str]) -> None:
    from spectre.web import server as server_mod

    for error in (ConnectionAbortedError("abandon"), BrokenPipeError("tuyau"), KeyError("vraie")):
        try:
            raise error
        except Exception:  # noqa: BLE001 - handle_error reads the exception in flight
            server_mod.ExclusiveHTTPServer.handle_error(
                object.__new__(server_mod.ExclusiveHTTPServer), None, ("127.0.0.1", 1)
            )
    err = capsys.readouterr().err
    assert "vraie" in err and "abandon" not in err and "tuyau" not in err


def test_status_reports_power(service: AssistantService) -> None:  # noqa: F811
    service.power = lambda: {"on_battery": True, "percent": 42}
    assert service.status()["power"] == {"on_battery": True, "percent": 42}


def test_agents(service: AssistantService, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(
        "spectre.assistant.service.shutil.which", lambda name: None if name == "vibe" else name
    )
    service.config.update({"mission_model": "chatgpt", "chatgpt_model": "gpt-5.5"})
    data = service.agents()
    names = [a["name"] for a in data["assistant"]]
    assert names == ["Spectre", "Gétro", "Kaïto", "Kyra", "Syfer"]
    kyra, syfer = data["assistant"][3], data["assistant"][4]
    assert kyra["engine"] == "ChatGPT (gpt-5.5) · Codex" and kyra["default"] is True
    assert syfer["engine"] == "Mistral · Vibe" and syfer["available"] is False
    assert data["assistant"][0]["engine"] == "Opus 5.5 · Claude Code"
    assert [(a["name"], a["engine"]) for a in data["redaction"]] == [
        ("Scout", "Haiku 4.5"),
        ("Scribe", "Sonnet 5.5"),
        ("Warden", "Opus 5.5"),
    ]


def test_api_agents_remote_missions(api: Client, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    assert len(api.json("GET", "/api/assistant/agents")[1]["assistant"]) == 5
    seen: list[int] = []

    class Fake:
        def __init__(self, port: int) -> None:
            seen.append(port)

        def status(self, password: bool) -> dict[str, Any]:
            return {"password": password}

    monkeypatch.setattr(assistant_api, "Remote", Fake)
    assert api.json("GET", "/api/assistant/remote") == (200, {"password": False})
    assert seen == [api.port]
    status, body = api.json("POST", "/api/assistant/remote", {})
    assert status == 400 and "mot de passe" in body["error"]
    result = api.json("POST", "/api/assistant/missions", {"goal": "Audit", "agent": "Syfer"})[1]
    assert "confiée à Syfer" in result["result"]


def test_enable_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTailscale()
    monkeypatch.setattr(assistant_api, "Remote", lambda port: Remote(port, "ts", fake))
    allowed = {"127.0.0.1"}
    handler = SimpleNamespace(
        server=SimpleNamespace(server_address=("127.0.0.1", 8765)),
        app=SimpleNamespace(auth=SimpleNamespace(enabled=True), allowed_hosts=allowed),
    )
    assert assistant_api.enable_remote(handler)["url"] == URL
    assert "monpc.tail0000.ts.net" in allowed
    fake.code = 1
    with pytest.raises(ValueError, match="Tailscale"):
        assistant_api.enable_remote(handler)
