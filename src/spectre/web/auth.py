"""Optional password protection: signed HTTP-only session cookie and login throttling."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sys
import threading
import time
from pathlib import Path

PASSWORD_ENV = "SPECTRE_WEBUI_PASSWORD"
COOKIE_NAME = "spectre_session"
SESSION_TTL_S = 24 * 3600
MAX_FAILURES = 5
LOCKOUT_S = 60.0
RESET_CODE_TTL_S = 10 * 60
RESET_MAX_TRIES = 5
RESET_COOLDOWN_S = 60.0
MIN_PASSWORD_LEN = 8


class Auth:
    """Checks the password and issues/validates signed session tokens."""

    def __init__(self, password: str | None, secret_file: Path) -> None:
        self.password = password or None
        self._secret_file = secret_file
        self._secret = self._load_secret(secret_file)
        self._failures: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()
        # Forgotten password: one code at a time, kept as a hash, with its expiry and tries left.
        self._reset: tuple[str, float, int] | None = None
        self._last_reset_request = -RESET_COOLDOWN_S

    @property
    def enabled(self) -> bool:
        """True when a password is configured."""
        return self.password is not None

    @staticmethod
    def _load_secret(path: Path) -> bytes:
        try:
            secret = bytes.fromhex(path.read_text(encoding="utf-8").strip())
            if len(secret) >= 32:
                return secret
        except (OSError, ValueError):
            pass
        secret = secrets.token_bytes(32)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secret.hex(), encoding="utf-8")
        return secret

    def _sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()

    def issue(self, now: float | None = None) -> str:
        """New session token valid for `SESSION_TTL_S` seconds."""
        expires = int((now or time.time()) + SESSION_TTL_S)
        payload = f"{expires}.{secrets.token_hex(8)}"
        return f"{payload}.{self._sign(payload)}"

    def valid(self, token: str | None, now: float | None = None) -> bool:
        """True if auth is off, or `token` is correctly signed and not expired."""
        if not self.enabled:
            return True
        if not token or token.count(".") != 2:
            return False
        expires, nonce, signature = token.split(".")
        if not hmac.compare_digest(self._sign(f"{expires}.{nonce}"), signature):
            return False
        return expires.isdigit() and int(expires) > (now or time.time())

    def locked_out(self, client: str, now: float | None = None) -> bool:
        """True while `client` is throttled after too many wrong passwords."""
        with self._lock:
            count, since = self._failures.get(client, (0, 0.0))
            return count >= MAX_FAILURES and (now or time.monotonic()) - since < LOCKOUT_S

    def check_password(self, client: str, attempt: str, now: float | None = None) -> bool:
        """Compare in constant time and track failures per client."""
        ok = self.password is not None and hmac.compare_digest(
            attempt.encode("utf-8"), self.password.encode("utf-8")
        )
        with self._lock:
            if ok:
                self._failures.pop(client, None)
            else:
                count, _ = self._failures.get(client, (0, 0.0))
                self._failures[client] = (count + 1, now or time.monotonic())
        return ok

    # ---- forgotten password ------------------------------------------------------------------

    def request_reset(self, now: float | None = None) -> str | None:
        """New 8-digit one-time code, or None while the last one was asked less than a minute ago.

        The code is never returned to the web page: the caller delivers it where only the owner
        can read it (a file on the PC, the paired Telegram chats).
        """
        moment = now if now is not None else time.monotonic()
        with self._lock:
            if moment - self._last_reset_request < RESET_COOLDOWN_S:
                return None
            self._last_reset_request = moment
            code = f"{secrets.randbelow(10**8):08d}"
            self._reset = (self._sign("reset." + code), moment + RESET_CODE_TTL_S, RESET_MAX_TRIES)
            return code

    def reset_password(
        self, code: str, new_password: str, now: float | None = None
    ) -> tuple[bool, str]:
        """Check the one-time code and set `new_password`; every open session is closed.

        Returns (ok, message in French). A wrong code uses one try; the code dies after
        `RESET_MAX_TRIES` wrong tries or `RESET_CODE_TTL_S` seconds.
        """
        if len(new_password) < MIN_PASSWORD_LEN:
            return (
                False,
                f"le nouveau mot de passe doit faire au moins {MIN_PASSWORD_LEN} caractères",
            )
        moment = now if now is not None else time.monotonic()
        with self._lock:
            if self._reset is None:
                return False, "demandez d'abord un code"
            digest, expires, tries = self._reset
            if moment > expires:
                self._reset = None
                return False, "code expiré : demandez-en un nouveau"
            if not hmac.compare_digest(digest, self._sign("reset." + code.strip())):
                tries -= 1
                self._reset = (digest, expires, tries) if tries > 0 else None
                return (
                    False,
                    "code incorrect" if tries > 0 else "code incorrect : demandez-en un nouveau",
                )
            self._reset = None
            self.password = new_password
            self._failures.clear()
            # A new signing key: every cookie issued with the old password stops working.
            self._secret = secrets.token_bytes(32)
            self._secret_file.write_text(self._secret.hex(), encoding="utf-8")
        return True, "mot de passe changé"


def save_password(password: str) -> bool:
    """Keep the new password for the next start: this process and, on Windows, the user's
    environment (where `tools/spectre-assistant.ps1` reads it). True when it was saved for good."""
    os.environ[PASSWORD_ENV] = password
    if sys.platform != "win32":
        return False
    import winreg  # pragma: no cover - Windows only

    with winreg.OpenKey(  # pragma: no cover
        winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, PASSWORD_ENV, 0, winreg.REG_SZ, password)
    return True  # pragma: no cover
