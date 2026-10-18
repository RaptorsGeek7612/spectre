"""Payments Spectre prepares and the user makes: Spectre never holds a bank login or a key.

`prepare_payment` waits for the user's approval (category `payment`), every time. Once
approved, Spectre writes the payment in its ledger (`payments` table) and hands over the means
to pay: a SEPA transfer QR code (EPC069-12 standard, scanned by the bank app) and/or the
merchant's payment page, opened in the browser. The money only leaves after the user confirms
in their own bank or on the merchant's page (strong authentication). The ledger then records
it as paid (`mark_paid`) or cancelled (`cancel_payment`).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

from spectre.assistant import qrcode
from spectre.assistant.actions import ActionContext, ActionError, open_url
from spectre.assistant.db import now_iso

FOLDER = "paiements"  # in the workspace: the QR codes to scan
MAX_AMOUNT = Decimal("10000")  # above, the user pays it themselves, without Spectre
IBAN = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}")
BIC = re.compile(r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?")
STATUSES = ("a_payer", "paye", "annule")


def clean_iban(raw: str) -> str:
    """An IBAN without spaces, checked (format and mod-97 key)."""
    iban = re.sub(r"\s+", "", raw).upper()
    if not IBAN.fullmatch(iban):
        raise ActionError(f"IBAN invalide : {raw}")
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    if int(digits) % 97 != 1:
        raise ActionError(f"IBAN invalide (clé de contrôle fausse) : {raw}")
    return iban


def clean_amount(raw: str | float) -> Decimal:
    try:
        amount = Decimal(str(raw).replace(" ", "").replace(",", ".").replace("€", ""))
    except InvalidOperation as exc:
        raise ActionError(f"montant illisible : {raw}") from exc
    if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise ActionError("montant en euros, positif, au centime près")
    if amount > MAX_AMOUNT:
        raise ActionError(
            f"au-delà de {MAX_AMOUNT} €, le paiement se fait sans Spectre, directement par toi"
        )
    return amount


def epc_payload(name: str, iban: str, amount: Decimal, reference: str, bic: str = "") -> str:
    """The text of a SEPA credit transfer QR code (EPC069-12, version 002, UTF-8)."""
    return "\n".join(
        ["BCD", "002", "1", "SCT", bic, name[:70], iban, f"EUR{amount:.2f}", "", "", reference]
    )


def prepare(
    ctx: ActionContext,
    beneficiary: str,
    amount: str,
    reference: str = "",
    iban: str = "",
    bic: str = "",
    url: str = "",
    purpose: str = "",
) -> str:
    """Runs once the user approved: the payment goes into the ledger, with its QR code and/or
    the merchant page opened. Nothing is debited here."""
    name = " ".join(beneficiary.split())[:70]
    if not name:
        raise ActionError("indique le bénéficiaire")
    value = clean_amount(amount)
    reference = " ".join(reference.split())[:140]
    account = clean_iban(iban) if iban.strip() else ""
    code = re.sub(r"\s+", "", bic).upper()
    if code and not BIC.fullmatch(code):
        raise ActionError(f"BIC invalide : {bic}")
    page = url.strip()
    if page and (urlparse(page).scheme != "https" or not urlparse(page).netloc):
        raise ActionError("la page de paiement doit être une adresse https")
    if not account and not page:
        raise ActionError("indique l'IBAN du bénéficiaire ou la page de paiement du marchand")
    payload = epc_payload(name, account, value, reference, code) if account else ""
    if payload and len(payload.encode("utf-8")) > qrcode_capacity():
        raise ActionError("référence trop longue pour le QR code : raccourcis-la")
    payment_id = ctx.db.execute(
        "INSERT INTO payments(ts, beneficiary, iban, bic, amount, reference, purpose, url, "
        "agent, mission_id, status) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'a_payer')",
        (
            now_iso(),
            name,
            account,
            code,
            f"{value:.2f}",
            reference,
            purpose.strip()[:300],
            page,
            ctx.agent or "opus",
            ctx.mission,
        ),
    )
    lines = [
        f"Paiement #{payment_id} prêt : {value:.2f} € à {name}"
        + (f" ({reference})" if reference else "")
        + "."
    ]
    if payload:
        folder = ctx.workspace / FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"paiement-{payment_id:04d}.svg"
        path.write_text(qrcode.svg(payload), encoding="utf-8")
        lines.append(
            f"QR code de virement SEPA : {path} (sur le téléphone : "
            f"/api/assistant/payments/{payment_id}/qr). Scanne-le avec ton appli bancaire, "
            "vérifie le bénéficiaire et le montant, puis confirme dans ta banque."
        )
    if page:
        opened = open_url(ctx, page)
        lines.append(f"Page de paiement du marchand : {opened}. Tu paies toi-même sur cette page.")
    lines.append(
        "Rien n'est débité tant que tu ne confirmes pas ; dis-moi quand c'est payé (mark_paid)."
    )
    return " ".join(lines)


def qrcode_capacity() -> int:
    """Bytes a level-M QR code of the largest supported version holds (byte mode)."""
    return qrcode._data_capacity(qrcode.MAX_VERSION) - 3  # mode and length header


def get(ctx: ActionContext, payment_id: int) -> dict[str, Any]:
    row = ctx.db.one("SELECT * FROM payments WHERE id = ?", (int(payment_id),))
    if row is None:
        raise ActionError(f"paiement introuvable : #{payment_id}")
    return row


def qr(ctx: ActionContext, payment_id: int) -> str:
    """The SVG QR code of a payment still to make (for the web view and the phone)."""
    row = get(ctx, payment_id)
    if not row["iban"]:
        raise ActionError("ce paiement se fait sur la page du marchand, sans QR code")
    if row["status"] != "a_payer":
        raise ActionError(f"paiement #{payment_id} déjà {row['status'].replace('_', ' ')}")
    payload = epc_payload(
        row["beneficiary"], row["iban"], Decimal(row["amount"]), row["reference"], row["bic"]
    )
    return qrcode.svg(payload)


def _set(ctx: ActionContext, payment_id: int, status: str) -> dict[str, Any]:
    row = get(ctx, payment_id)
    if row["status"] != "a_payer":
        raise ActionError(f"paiement #{payment_id} déjà {row['status'].replace('_', ' ')}")
    ctx.db.execute(
        "UPDATE payments SET status = ?, decided_at = ? WHERE id = ?",
        (status, now_iso(), row["id"]),
    )
    path = ctx.workspace / FOLDER / f"paiement-{row['id']:04d}.svg"
    path.unlink(missing_ok=True)  # a used or cancelled QR code is not left to scan again
    return get(ctx, payment_id)


def mark_paid(ctx: ActionContext, payment_id: int) -> str:
    row = _set(ctx, payment_id, "paye")
    return f"paiement #{row['id']} noté payé : {row['amount']} € à {row['beneficiary']}"


def cancel(ctx: ActionContext, payment_id: int) -> str:
    row = _set(ctx, payment_id, "annule")
    return f"paiement #{row['id']} annulé ({row['amount']} € à {row['beneficiary']})"


def listing(ctx: ActionContext, status: str = "") -> str:
    wanted = status.strip().lower().replace(" ", "_")
    if wanted and wanted not in STATUSES:
        raise ActionError(f"statut inconnu : {status} (au choix : {', '.join(STATUSES)})")
    rows = ctx.db.all(
        "SELECT * FROM payments" + (" WHERE status = ?" if wanted else "") + " ORDER BY id DESC "
        "LIMIT 50",
        (wanted,) if wanted else (),
    )
    if not rows:
        return "aucun paiement"
    return "\n".join(
        f"#{r['id']} [{r['status'].replace('_', ' ')}] {r['amount']} € à {r['beneficiary']}"
        + (f" — {r['reference']}" if r["reference"] else "")
        + (f" (IBAN {r['iban'][:4]}…{r['iban'][-4:]})" if r["iban"] else "")
        + (f" (page {urlparse(r['url']).netloc})" if r["url"] else "")
        + f" — {r['ts'][:10]}"
        for r in rows
    )
