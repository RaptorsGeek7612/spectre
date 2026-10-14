"""Web Push (RFC 8291 encryption, VAPID), the per-company briefing, read-only crypto sources."""

from __future__ import annotations

import json
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from spectre.assistant.brief import company_lines
from spectre.assistant.company import Companies
from spectre.assistant.db import Database
from spectre.assistant.providers import read_env_file
from spectre.assistant.saas import Collect, Saas, SaasError
from spectre.assistant.service import AssistantService
from spectre.assistant.webpush import (
    KEY_ENV,
    WebPush,
    b64,
    encrypt,
    hkdf_expand,
    hkdf_extract,
    raw_public,
    unb64,
)
from tests.test_assistant_saas import FakeHttp
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone(timedelta(hours=2)))


def browser() -> tuple[ec.EllipticCurvePrivateKey, bytes, dict[str, Any]]:
    """A subscribing browser: its key pair, auth secret and subscription JSON."""
    key = ec.generate_private_key(ec.SECP256R1())
    auth = b"0123456789abcdef"
    subscription = {
        "endpoint": "https://push.example.com/send/abc",
        "keys": {"p256dh": b64(raw_public(key.public_key())), "auth": b64(auth)},
    }
    return key, auth, subscription


def decrypt(body: bytes, key: ec.EllipticCurvePrivateKey, auth: bytes) -> bytes:
    """What the browser does (RFC 8291), to check our encryption end to end."""
    salt, record, idlen = body[:16], struct.unpack("!L", body[16:20])[0], body[20]
    server_public = body[21 : 21 + idlen]
    assert record == 4096
    sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), server_public)
    shared = key.exchange(ec.ECDH(), sender)
    ikm = hkdf_expand(
        hkdf_extract(auth, shared),
        b"WebPush: info\x00" + raw_public(key.public_key()) + server_public,
        32,
    )
    prk = hkdf_extract(salt, ikm)
    cek = hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, body[21 + idlen :], None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_encrypt_roundtrip() -> None:
    key, auth, sub = browser()
    body = encrypt(b"bonjour", sub["keys"]["p256dh"], sub["keys"]["auth"])
    assert decrypt(body, key, auth) == b"bonjour"
    with pytest.raises(ValueError, match="trop longue"):
        encrypt(b"x" * 4000, sub["keys"]["p256dh"], sub["keys"]["auth"])
    assert unb64(b64(b"\x00\xff")) == b"\x00\xff"


def test_vapid_and_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY_ENV, raising=False)
    db = Database(tmp_path / "spectre.db")
    push = WebPush(db, tmp_path)
    public = push.public_key()  # created and kept in .env
    assert (
        KEY_ENV in read_env_file(tmp_path / ".env") and WebPush(db, tmp_path).public_key() == public
    )
    header = push.vapid("https://fcm.googleapis.com/fcm/send/x", now=1000.0)
    token, k = header.removeprefix("vapid t=").split(", k=")
    assert k == public
    head, claims, signature = token.split(".")
    assert json.loads(unb64(claims)) == {
        "aud": "https://fcm.googleapis.com",
        "exp": 1000 + 12 * 3600,
        "sub": "mailto:spectre@localhost",
    }
    raw = unb64(signature)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    verifier = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(public))
    verifier.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if wrong


def test_subscriptions_and_send(tmp_path: Path) -> None:
    db = Database(tmp_path / "spectre.db")
    posted: list[tuple[str, dict[str, str], bytes]] = []
    statuses = {"https://push.example.com/send/abc": 201, "https://gone.example.com/x": 410}

    def post(url: str, headers: dict[str, str], body: bytes) -> int:
        posted.append((url, headers, body))
        if url.startswith("https://broken"):
            raise OSError("réseau")
        return statuses.get(url, 500)

    push = WebPush(db, tmp_path, post)
    key, auth, sub = browser()
    push.subscribe(sub, "téléphone")
    push.subscribe(sub)  # the same browser again: updated, not duplicated
    for endpoint in (
        "https://gone.example.com/x",
        "https://broken.example.com/y",
        "https://slow.example.com/z",
    ):
        push.subscribe({"endpoint": endpoint, "keys": sub["keys"]})
    assert len(push.subscriptions()) == 4
    assert push.send("Alerte", "Le site est tombé") == 1
    url, headers, body = posted[0]
    assert headers["Content-Encoding"] == "aes128gcm" and headers["Authorization"].startswith(
        "vapid t="
    )
    assert json.loads(decrypt(body, key, auth)) == {
        "title": "Alerte",
        "body": "Le site est tombé",
        "url": "/assistant.html",
    }
    assert [s["endpoint"] for s in push.subscriptions()] == [
        "https://push.example.com/send/abc",
        "https://broken.example.com/y",
        "https://slow.example.com/z",
    ]  # the gone one was removed
    for bad, error in [
        ({"endpoint": "http://x", "keys": sub["keys"]}, "invalide"),
        (
            {"endpoint": "https://x", "keys": {"p256dh": "AAAA", "auth": sub["keys"]["auth"]}},
            "clés",
        ),
        (
            {
                "endpoint": "https://x",
                "keys": {"p256dh": sub["keys"]["p256dh"], "auth": b64(b"short")},
            },
            "clés",
        ),
    ]:
        with pytest.raises(ValueError, match=error):
            push.subscribe(bad)
    for i in range(7):
        push.subscribe({"endpoint": f"https://more.example.com/{i}", "keys": sub["keys"]})
    with pytest.raises(ValueError, match="10 appareils"):
        push.subscribe({"endpoint": "https://one-too-many.example.com", "keys": sub["keys"]})
    push.unsubscribe("https://slow.example.com/z")
    assert len(push.subscriptions()) == 9


# ---- crypto sources ------------------------------------------------------------------------------


def test_crypto_collectors() -> None:
    fetch = FakeHttp(
        {
            "mempool.space/api/address/bc1q": (
                200,
                {},
                {
                    "chain_stats": {"funded_txo_sum": 150_000_000, "spent_txo_sum": 50_000_000},
                    "mempool_stats": {"funded_txo_sum": 1000, "spent_txo_sum": 0},
                },
            ),
            "eth.blockscout.com/api/v2/addresses/0x": (
                200,
                {},
                {"coin_balance": "2500000000000000000"},
            ),
            "api.coingecko.com": (
                200,
                {},
                {"bitcoin": {"eur": 73393}, "wrapped-bitcoin": {"eur": 73000}, "unknown": {}},
            ),
        }
    )
    collect = Collect(fetch, NOW)
    assert collect.btc_wallet({"address": "bc1qtest"}, "") == {"btc_balance": 1.00001}
    assert collect.eth_wallet({"address": "0xabc"}, "") == {"eth_balance": 2.5}
    prices = collect.crypto_price(
        {"coins": ["bitcoin", "wrapped-bitcoin", "unknown"], "currency": "eur"}, ""
    )
    assert prices == {"price_bitcoin_eur": 73393.0, "price_wrapped_bitcoin_eur": 73000.0}
    assert "ids=bitcoin%2Cwrapped-bitcoin%2Cunknown" in fetch.calls[-1][1]
    with pytest.raises(ConnectionError, match="aucun cours"):
        Collect(FakeHttp({"coingecko": (200, {}, {})}), NOW).crypto_price(
            {"coins": ["x"], "currency": "eur"}, ""
        )


def test_crypto_sources_validation(tmp_path: Path) -> None:
    db = Database(tmp_path / "spectre.db")
    cid = Companies(db).create("Acme")["id"]
    saas = Saas(db, tmp_path)
    btc = saas.add_source(
        cid, "btc_wallet", "Pool", {"address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"}
    )
    assert btc["config"] == {"address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"}
    saas.add_source(
        cid, "eth_wallet", "Trésorerie", {"address": "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe"}
    )
    price = saas.add_source(
        cid, "crypto_price", "Cours", {"coins": "Bitcoin, ethereum, bad coin!", "currency": "EUR"}
    )
    assert price["config"] == {"coins": ["bitcoin", "ethereum"], "currency": "eur"}
    seed = "abandon ability able about above absent absorb abstract absurd abuse access accident"
    for kind, config, error in [
        ("btc_wallet", {"address": seed}, "jamais de clé privée"),
        (
            "btc_wallet",
            {"address": "5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ"},
            "adresse publique",
        ),
        ("eth_wallet", {"address": "0x" + "a" * 64}, "adresse publique"),
        ("crypto_price", {"coins": "!!", "currency": "eur"}, "identifiants CoinGecko"),
        ("crypto_price", {"coins": "bitcoin", "currency": "euros!"}, "identifiants CoinGecko"),
    ]:
        with pytest.raises(SaasError, match=error):
            saas.add_source(cid, kind, "x", config)


# ---- the per-company briefing -------------------------------------------------------------------


def test_company_briefing(tmp_path: Path) -> None:
    db = Database(tmp_path / "spectre.db")
    companies = Companies(db)
    acme = companies.create("Acme")
    companies.create("Vide")
    saas = Saas(db, tmp_path)
    saas.record(acme["id"], "mrr", 1000, NOW - timedelta(days=8))
    saas.record(acme["id"], "mrr", 1100, NOW)
    saas.record(acme["id"], "churn_rate", 3, NOW)
    saas.record(acme["id"], "up", 0, NOW)
    task = companies.add_task("acme", "Une tâche à valider")
    db.execute("UPDATE tasks SET status = 'review' WHERE id = ?", (task["id"],))
    blocked = companies.add_task("acme", "Une tâche bloquée")
    db.execute("UPDATE tasks SET status = 'blocked' WHERE id = ?", (blocked["id"],))
    saas.add_alert(acme["id"], "mrr", "<", 2000)
    db.execute("UPDATE saas_alerts SET active = 1")
    db.execute(
        "INSERT INTO decisions(company_id, question, status, review_at, created_at) "
        "VALUES(?, 'q', 'decided', ?, ?)",
        (acme["id"], (NOW + timedelta(days=2)).isoformat(), NOW.isoformat()),
    )
    from spectre.assistant.experiments import Experiments

    Experiments(db, tmp_path).start(acme["id"], "Une hypothèse sur le MRR", "mrr", days=3, now=NOW)
    assert company_lines(db, tmp_path, NOW) == [
        "Acme : MRR 1 100, +10 % sur la semaine, churn 3 %, site HORS LIGNE, 1 tâche(s) à valider, "
        "1 tâche(s) bloquée(s), 1 alerte(s) active(s), 1 décision(s) à réévaluer cette semaine, "
        "1 expérience(s) se terminent cette semaine."
    ]


def test_briefing_includes_companies(tmp_path: Path) -> None:
    from spectre.assistant.config import AssistantConfig
    from spectre.assistant.proactive import Proactive
    from tests.test_assistant_engines import Rooted

    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    cid = Companies(db).create("Acme")["id"]
    Saas(db, root).record(cid, "mrr", 500, NOW)
    proactive = Proactive(db, Rooted(root), AssistantConfig(), lambda *a: None, fetch=lambda u: {})  # type: ignore[arg-type]
    assert "Acme : MRR 500." in proactive.briefing(NOW)


# ---- service and API -----------------------------------------------------------------------------


def test_push_service_and_api(
    api: Client,  # noqa: F811
    service: AssistantService,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        service.push, "send", lambda title, body, url="/": sent.append((title, body)) or 1
    )
    monkeypatch.setattr("threading.Thread.start", lambda self: self.run())
    info = api.json("GET", "/api/assistant/push")[1]
    assert info["devices"] == 0 and len(unb64(info["key"])) == 65
    service._on_initiative("mission", "Mission terminée", "ok")
    assert sent == []  # nobody subscribed: nothing sent
    _, _, sub = browser()
    assert api.json(
        "POST", "/api/assistant/push/subscribe", {"subscription": sub, "label": "Pixel"}
    )[1]["ok"]
    service._on_initiative("mission", "Mission terminée", "Rapport prêt.")
    from spectre.assistant import tools

    tools.execute(service.gate, service.ctx, "delete_file", {"path": "x"})
    service.poll_changes()
    assert (
        sent[0] == ("Mission terminée", "Rapport prêt.")
        and sent[1][0] == "Spectre attend ta validation"
    )
    assert api.json("POST", "/api/assistant/push/test", {})[1] == {"sent": 1}
    assert api.json("POST", "/api/assistant/push/unsubscribe", {"endpoint": sub["endpoint"]})[
        1
    ] == {"ok": True}
    assert api.json("GET", "/api/assistant/push")[1]["devices"] == 0
    status, body = api.json("POST", "/api/assistant/push/subscribe", {"subscription": {}})
    assert status == 400
