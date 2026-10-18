"""Payments Spectre prepares and the user makes (approval every time, no bank login, ever)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import payments, qrcode
from spectre.assistant import tools as tools_mod
from spectre.assistant.actions import ActionError
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate

IBAN = "FR76 3000 6000 0112 3456 7890 189"


@pytest.fixture
def ctx(tmp_path: Path) -> Any:
    db = Database(tmp_path / "a.db")
    context = tools_mod.make_context(db, tmp_path / "assistant", [str(tmp_path)])
    context.opened = []
    context.launcher = context.opened.append
    yield context
    db.close()


def test_checks() -> None:
    assert payments.clean_iban(IBAN) == "FR7630006000011234567890189"
    with pytest.raises(ActionError, match="clé de contrôle"):
        payments.clean_iban("FR76 3000 6000 0112 3456 7890 188")
    with pytest.raises(ActionError, match="IBAN invalide"):
        payments.clean_iban("pas un iban")
    assert payments.clean_amount("49,90 €") == Decimal("49.90")
    for bad in ("0", "-5", "12.345", "abc"):
        with pytest.raises(ActionError):
            payments.clean_amount(bad)
    with pytest.raises(ActionError, match="sans Spectre"):
        payments.clean_amount("10000.01")


def test_a_payment_always_waits_for_the_user(ctx: Any) -> None:
    gate = Gate(ctx.db)
    args = {"beneficiary": "EDF", "amount": "49,90", "reference": "Facture 42", "iban": IBAN}
    pending = tools_mod.execute(gate, ctx, "prepare_payment", args)
    assert "VALIDATION" in pending.upper()
    assert ctx.db.one("SELECT COUNT(*) AS n FROM payments")["n"] == 0  # nothing before the yes
    ctx.agent = "antigravity"  # an agent asks too: still the user's go
    assert "VALIDATION" in tools_mod.execute(gate, ctx, "prepare_payment", args).upper()
    ctx.agent = ""
    approval = ctx.db.one("SELECT * FROM approvals ORDER BY id LIMIT 1")
    assert approval["category"] == "payment" and json.loads(approval["args"])["amount"] == "49,90"
    result = tools_mod.run_approved(gate, ctx, approval["id"])
    assert "Paiement #1 prêt : 49.90 € à EDF (Facture 42)" in result
    assert "rien n'est débité" in result.lower()
    row = payments.get(ctx, 1)
    assert row["status"] == "a_payer" and row["iban"] == "FR7630006000011234567890189"
    svg = ctx.workspace / "paiements" / "paiement-0001.svg"
    assert svg.read_text(encoding="utf-8") == payments.qr(ctx, 1)


def test_qr_holds_the_sepa_transfer(ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = payments.epc_payload("EDF", "FR7630006000011234567890189", Decimal("49.9"), "F42")
    assert payload.split("\n") == [
        "BCD", "002", "1", "SCT", "", "EDF", "FR7630006000011234567890189", "EUR49.90", "", "",
        "F42",
    ]  # fmt: skip
    assert qrcode.matrix(payload)  # fits a supported QR code
    assert payments.qrcode_capacity() == 213  # level M, version 10, byte mode
    usual = payments.epc_payload("E" * 70, "FR7630006000011234567890189", Decimal(1), "x" * 70)
    assert len(usual.encode()) < payments.qrcode_capacity()  # a long name and reference fit
    with pytest.raises(ActionError, match="trop longue"):  # beyond the QR code: shorten it
        payments.prepare(ctx, "E" * 70, "10", "x" * 140, IBAN, "AGRIFRPPXXX")
    monkeypatch.setattr(payments, "qrcode_capacity", lambda: 40)
    with pytest.raises(ActionError, match="trop longue"):
        payments.prepare(ctx, "EDF", "10", "Facture", IBAN)


def test_merchant_page_and_refusals(ctx: Any) -> None:
    out = payments.prepare(ctx, "Boutique", "19.99", "Commande 7", url="https://pay.exemple.fr/c/7")
    assert ctx.opened == ["https://pay.exemple.fr/c/7"] and "Tu paies toi-même" in out
    assert not (ctx.workspace / "paiements").exists()  # no transfer: no QR code
    with pytest.raises(ActionError, match="sans QR code"):
        payments.qr(ctx, 1)
    for kwargs, message in [
        ({"beneficiary": " "}, "bénéficiaire"),
        ({"url": "http://pay.exemple.fr"}, "https"),
        ({"url": "", "iban": ""}, "IBAN du bénéficiaire ou la page"),
        ({"bic": "12"}, "BIC invalide"),
    ]:
        args = {"beneficiary": "B", "amount": "5", "iban": IBAN} | kwargs
        with pytest.raises(ActionError, match=message):
            payments.prepare(ctx, **args)


def test_ledger(ctx: Any) -> None:
    payments.prepare(ctx, "EDF", "49.90", "F42", IBAN)
    payments.prepare(ctx, "Free", "29.99", "", IBAN)
    assert payments.listing(ctx).count("[a payer]") == 2 and "IBAN FR76…0189" in payments.listing(
        ctx
    )
    assert "noté payé" in tools_mod._mark_paid(ctx, 1)
    assert not (ctx.workspace / "paiements" / "paiement-0001.svg").exists()
    assert "annulé" in tools_mod._cancel_payment(ctx, 2)
    with pytest.raises(ActionError, match="déjà paye"):
        payments.mark_paid(ctx, 1)
    with pytest.raises(ActionError, match="déjà annule"):
        payments.qr(ctx, 2)
    assert "[paye]" in tools_mod._payments(ctx, "paye") and "Free" not in payments.listing(
        ctx, "paye"
    )
    assert payments.listing(ctx, "a payer") == "aucun paiement"
    with pytest.raises(ActionError, match="statut inconnu"):
        payments.listing(ctx, "rembourse")
    with pytest.raises(ActionError, match="introuvable"):
        payments.get(ctx, 9)
    registry = tools_mod.TOOLS
    assert registry["mark_paid"].lead_only and registry["cancel_payment"].lead_only
    assert registry["prepare_payment"].category == "payment"
