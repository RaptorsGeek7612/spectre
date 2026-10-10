"""Remote access from the phone: Spectre published on the private tailnet by `tailscale serve`.

The launcher (tools/spectre-assistant.ps1) does this at start-up; this module lets the web
interface show where the phone should connect (link + QR code) and switch it on from there.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spectre.assistant import qrcode

SERVE_TIMEOUT_S = 10.0  # `serve` waits forever while HTTPS/Serve is off on the tailnet
STATUS_TIMEOUT_S = 5.0
PAGE = "assistant.html"

Runner = Callable[[list[str], float], tuple[int, str]]


def _run(command: list[str], timeout: float) -> tuple[int, str]:
    try:
        done = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""
    return done.returncode, done.stdout


def find_tailscale() -> str | None:
    """The Tailscale CLI, also when the PATH was not refreshed after its installation."""
    found = shutil.which("tailscale")
    if found:
        return found
    default = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Tailscale"
    exe = default / "tailscale.exe"
    return str(exe) if exe.is_file() else None


class Remote:
    """Reads and changes the Tailscale publication of the local web server on `port`."""

    def __init__(self, port: int, binary: str | None = None, run: Runner = _run) -> None:
        self.port = port
        self.binary = binary if binary is not None else find_tailscale()
        self._run = run

    def _json(self, *args: str) -> dict[str, Any]:
        assert self.binary is not None
        code, out = self._run([self.binary, *args, "--json"], STATUS_TIMEOUT_S)
        if code != 0:
            return {}
        try:
            data = json.loads(out or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def status(self, password: bool) -> dict[str, Any]:
        """Where and whether the phone can reach Spectre, with the next step when it cannot."""
        info: dict[str, Any] = {
            "installed": self.binary is not None,
            "running": False,
            "serving": False,
            "password": password,
            "dns": "",
            "url": "",
            "qr": "",
        }
        if self.binary is None:
            return info | {"hint": "Installe Tailscale sur ce PC et sur ton téléphone."}
        state = self._json("status")
        info["running"] = state.get("BackendState") == "Running"
        info["dns"] = str((state.get("Self") or {}).get("DNSName", "")).rstrip(".")
        if not info["running"] or not info["dns"]:
            return info | {"hint": "Tailscale est arrêté ou déconnecté : ouvre-le et connecte-toi."}
        served = json.dumps(self._json("serve", "status"))
        info["serving"] = f"127.0.0.1:{self.port}" in served or f"localhost:{self.port}" in served
        info["url"] = f"https://{info['dns']}/{PAGE}"
        info["qr"] = qrcode.svg(info["url"])
        if not password:
            hint = (
                "Définis d'abord un mot de passe (tools\\spectre-password.cmd), puis relance "
                "Spectre : sans lui, n'importe quel appareil de ton tailnet pourrait le piloter."
            )
        elif not info["serving"]:
            hint = "Active l'accès à distance pour publier Spectre sur ton tailnet."
        else:
            hint = "Scanne le QR code avec l'appareil photo du téléphone (Tailscale allumé)."
        return info | {"hint": hint}

    def enable(self) -> bool:
        """Publish the local server on the tailnet over HTTPS (nothing opens to the Internet)."""
        if self.binary is None:
            return False
        code, _ = self._run(
            [self.binary, "serve", "--bg", f"http://127.0.0.1:{self.port}"], SERVE_TIMEOUT_S
        )
        return code == 0
