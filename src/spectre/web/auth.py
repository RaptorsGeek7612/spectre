"""Optional password protection: signed HTTP-only session cookie and login throttling."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from pathlib import Path

PASSWORD_ENV = "SPECTRE_WEBUI_PASSWORD"
COOKIE_NAME = "spectre_session"
SESSION_TTL_S = 24 * 3600
MAX_FAILURES = 5
LOCKOUT_S = 60.0


class Auth:
    """Checks the password and issues/validates signed session tokens."""

    def __init__(self, password: str | None, secret_file: Path) -> None:
        self.password = password or None
        self._secret = self._load_secret(secret_file)
        self._failures: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

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
