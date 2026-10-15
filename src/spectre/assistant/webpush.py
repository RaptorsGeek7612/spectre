"""Native notifications on the phone and the PC (Web Push), without a third-party service.

The browser subscribes through its own push service (Google's for Chrome on Android, Mozilla's
for Firefox...); Spectre encrypts each message for that browser (RFC 8291, aes128gcm) and signs
the request with its own key (VAPID, RFC 8292). The push service only sees an encrypted blob.
The VAPID key pair is created once and kept in the assistant folder's `.env`.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from spectre.assistant.db import Database, now_iso
from spectre.assistant.providers import read_env_file, write_env_value

KEY_ENV = "SPECTRE_VAPID_PRIVATE"
CONTACT = "mailto:spectre@localhost"
RECORD = 4096
MAX_SUBSCRIPTIONS = 10
Post = Callable[[str, dict[str, str], bytes], int]  # (url, headers, body) -> HTTP status


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def raw_public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    mac = hmac.HMAC(prk, hashes.SHA256())
    mac.update(info + b"\x01")
    return mac.finalize()[:length]


def hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    mac = hmac.HMAC(salt, hashes.SHA256())
    mac.update(ikm)
    return mac.finalize()


def encrypt(
    payload: bytes,
    p256dh: str,
    auth: str,
    *,
    salt: bytes | None = None,
    server_key: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """The aes128gcm body for one subscription (RFC 8291, a single record)."""
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(p256dh))
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    server_public = raw_public(server_key.public_key())
    shared = server_key.exchange(ec.ECDH(), receiver)
    prk_key = hkdf_extract(unb64(auth), shared)
    ikm = hkdf_expand(prk_key, b"WebPush: info\x00" + raw_public(receiver) + server_public, 32)
    salt = salt or os.urandom(16)
    prk = hkdf_extract(salt, ikm)
    cek = hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)
    if len(payload) > RECORD - 17 - 103:
        raise ValueError("notification trop longue")
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return (
        salt + struct.pack("!L", RECORD) + bytes([len(server_public)]) + server_public + ciphertext
    )


def http_post(url: str, headers: dict[str, str], body: bytes) -> int:  # pragma: no cover - network
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


class WebPush:
    def __init__(self, db: Database, root: Path, post: Post = http_post) -> None:
        self.db = db
        self.root = root
        self.post = post

    # ---- the VAPID key -------------------------------------------------------------------------

    def private_key(self) -> ec.EllipticCurvePrivateKey:
        stored = os.environ.get(KEY_ENV, "") or read_env_file(self.root / ".env").get(KEY_ENV, "")
        if stored:
            value = int.from_bytes(unb64(stored), "big")
            return ec.derive_private_key(value, ec.SECP256R1())
        key = ec.generate_private_key(ec.SECP256R1())
        secret = key.private_numbers().private_value.to_bytes(32, "big")
        write_env_value(self.root, KEY_ENV, b64(secret))
        return key

    def public_key(self) -> str:
        """What the browser needs to subscribe (`applicationServerKey`)."""
        return b64(raw_public(self.private_key().public_key()))

    def vapid(self, endpoint: str, now: float | None = None) -> str:
        """The `Authorization` header for one push service."""
        parts = urllib.parse.urlsplit(endpoint)
        claims = {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int((now or time.time()) + 12 * 3600),
            "sub": CONTACT,
        }
        head = b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        body = b64(json.dumps(claims, separators=(",", ":")).encode())
        key = self.private_key()
        der = key.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        signature = b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        return f"vapid t={head}.{body}.{signature}, k={b64(raw_public(key.public_key()))}"

    # ---- subscriptions --------------------------------------------------------------------------

    def subscriptions(self) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM push_subscriptions ORDER BY id")

    def subscribe(self, data: dict[str, Any], label: str = "") -> dict[str, Any]:
        endpoint = str(data.get("endpoint", ""))
        keys = data.get("keys") or {}
        if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
            raise ValueError("abonnement de notification invalide")
        try:
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(str(keys["p256dh"])))
            if len(unb64(str(keys["auth"]))) != 16:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise ValueError("clés de notification invalides") from exc
        known = self.db.one("SELECT 1 FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        if not known and len(self.subscriptions()) >= MAX_SUBSCRIPTIONS:
            raise ValueError(f"{MAX_SUBSCRIPTIONS} appareils au maximum")
        self.db.execute(
            "INSERT INTO push_subscriptions(endpoint, p256dh, auth, label, created_at) "
            "VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth",
            (endpoint, str(keys["p256dh"]), str(keys["auth"]), label[:80], now_iso()),
        )
        row = self.db.one("SELECT * FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        assert row is not None
        return row

    def unsubscribe(self, endpoint: str) -> None:
        self.db.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))

    def send(self, title: str, body: str, url: str = "/assistant.html") -> int:
        """To every subscribed device; returns how many accepted it. Gone ones are removed."""
        payload = json.dumps(
            {"title": title[:120], "body": body[:600], "url": url}, ensure_ascii=False
        ).encode()
        sent = 0
        for sub in self.subscriptions():
            try:
                headers = {
                    "TTL": "86400",
                    "Urgency": "normal",
                    "Content-Encoding": "aes128gcm",
                    "Content-Type": "application/octet-stream",
                    "Authorization": self.vapid(sub["endpoint"]),
                }
                status = self.post(
                    sub["endpoint"], headers, encrypt(payload, sub["p256dh"], sub["auth"])
                )
            except (OSError, ValueError):
                continue
            if status in (404, 410):  # the browser dropped this subscription
                self.unsubscribe(sub["endpoint"])
            elif 200 <= status < 300:
                sent += 1
        return sent
