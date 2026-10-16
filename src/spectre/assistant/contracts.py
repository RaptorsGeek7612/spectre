"""Contract tools for Octavya: a clause checklist of a contract, and a comparison of two versions.

Both read .docx (Word), .txt and .md files with the standard library only. `analyser` is a
read: it spots which usual clauses are present or missing, the dates, the amounts and a few
warning signs — a first pass to guide a lawyer's reading, never a legal opinion. `comparer`
writes an HTML comparison next to the first file.
"""

from __future__ import annotations

import difflib
import html
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from spectre.assistant.actions import MAX_READ_CHARS, ActionContext, ActionError, resolve_path

CONTRACT_AGENTS = ("cursor",)
CONTRACT_OPS = {
    "analyser": "clauses présentes et absentes, dates, montants et signaux d'alerte d'un contrat",
    "comparer": "comparatif HTML de deux versions (options = la seconde version)",
}
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# The usual clauses, each with the words (French and English) that reveal it.
CLAUSES: dict[str, tuple[str, ...]] = {
    "parties et pouvoirs": ("entre les soussignés", "représentée par", "between", "parties"),
    "objet": ("objet", "purpose", "scope"),
    "prix et paiement": ("prix", "paiement", "facturation", "price", "payment", "fees"),
    "durée": ("durée", "prend effet", "entrée en vigueur", "term", "effective date"),
    "résiliation": ("résiliation", "résolution", "termination", "terminate"),
    "responsabilité": ("responsabilité", "liability", "indemni"),
    "force majeure": ("force majeure", "force majeure event", "act of god"),
    "confidentialité": ("confidentialité", "confidentiel", "confidential"),
    "propriété intellectuelle": ("propriété intellectuelle", "droits d'auteur", "intellectual"),
    "données personnelles": ("données personnelles", "rgpd", "personal data", "gdpr"),
    "loi applicable": ("loi applicable", "droit applicable", "governing law"),
    "litiges": ("tribunal", "juridiction", "arbitrage", "médiation", "arbitration", "courts"),
    "cession et sous-traitance": ("cession", "sous-trait", "assign", "subcontract"),
    "assurance": ("assurance", "insurance"),
    "intégralité": ("intégralité", "entire agreement", "accord complet"),
}
# Wording that deserves a careful look (not illegal in itself).
ALERTS: dict[str, str] = {
    r"tacite(ment)? reconduct|renouvel\w+ automatiquement|automatically renew": (
        "reconduction tacite : vérifier le préavis et, face à un consommateur, l'information "
        "obligatoire (L215-1)"
    ),
    r"renonce\w* à (tout|toute) (recours|action)|waives? any (claim|right)": (
        "renonciation à tout recours : souvent déséquilibrée ou non écrite"
    ),
    r"sans préavis|without (prior )?notice": "résiliation ou modification sans préavis",
    r"exclu\w* toute responsabilité|en aucun cas responsable|no liability whatsoever": (
        "exclusion totale de responsabilité : risque de clause réputée non écrite (1170, 1171)"
    ),
    r"clause pénale|pénalités?|liquidated damages": (
        "pénalités : vérifier leur montant (modérables par le juge, 1231-5)"
    ),
    r"non[- ]concurrence|non[- ]compete": (
        "non-concurrence : limitée dans le temps, l'espace et l'activité ; salarié = "
        "contrepartie financière"
    ),
    r"modifi\w+ unilatéral|à sa seule discrétion|at its sole discretion": (
        "pouvoir unilatéral d'une partie (prix, conditions) : déséquilibre possible"
    ),
    r"exclusivit|exclusive": "exclusivité : durée, territoire, contrepartie",
}
DATE = re.compile(
    r"\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{1,2}(?:er)? (?:janvier|février|mars|avril|mai|juin|"
    r"juillet|août|septembre|octobre|novembre|décembre) \d{4})\b",
    re.IGNORECASE,
)
AMOUNT = re.compile(r"\b\d[\d  .]*(?:,\d+)?\s?(?:€|euros?|EUR|\$|USD|£)", re.IGNORECASE)
DELAY = re.compile(r"\b\d+\s?(?:jours?|mois|ans?|semaines?|days?|months?|years?)\b", re.I)


def read_text(path: Path) -> str:
    """The plain text of a .docx, .txt or .md contract, one paragraph per line."""
    if not path.is_file():
        raise ActionError(f"fichier introuvable : {path}")
    suffix = path.suffix.lower()
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(path) as archive:
                root = ElementTree.fromstring(archive.read("word/document.xml"))  # noqa: S314
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise ActionError(f"document Word illisible : {path.name}") from exc
        paragraphs = [
            "".join(node.text or "" for node in p.iter(f"{WORD}t")) for p in root.iter(f"{WORD}p")
        ]
        return "\n".join(p for p in paragraphs if p.strip())
    if suffix in (".txt", ".md", ".markdown", ".fountain"):
        return path.read_text(encoding="utf-8", errors="replace")
    raise ActionError("formats lus : .docx, .txt, .md (convertir un PDF avec pandoc ou l'OCR)")


def analyse(text: str) -> str:
    low = text.lower()
    present = [name for name, words in CLAUSES.items() if any(w in low for w in words)]
    missing = [name for name in CLAUSES if name not in present]
    alerts = [why for pattern, why in ALERTS.items() if re.search(pattern, low)]
    dates = list(dict.fromkeys(m.group(0) for m in DATE.finditer(text)))[:10]
    amounts = list(dict.fromkeys(m.group(0).strip() for m in AMOUNT.finditer(text)))[:10]
    delays = list(dict.fromkeys(m.group(0) for m in DELAY.finditer(text)))[:10]
    lines = [
        f"Repérage ({len(text.split())} mots) — une première lecture, pas une analyse juridique.",
        f"Clauses repérées ({len(present)}/{len(CLAUSES)}) : {', '.join(present) or 'aucune'}.",
        f"À vérifier ou absentes : {', '.join(missing) or 'aucune'}.",
        f"Dates : {', '.join(dates) or 'aucune'}.",
        f"Montants : {', '.join(amounts) or 'aucun'}.",
        f"Délais et durées : {', '.join(delays) or 'aucun'}.",
    ]
    lines += ["Signaux d'alerte :"] + ([f"- {a}" for a in alerts] or ["- aucun mot-clé repéré"])
    return "\n".join(lines)


def compare(ctx: ActionContext, first: Path, second: Path) -> str:
    old = read_text(first).splitlines()
    new = read_text(second).splitlines()
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    added = removed = changed = 0
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "insert":
            added += b2 - b1
        elif tag == "delete":
            removed += a2 - a1
        elif tag == "replace":
            changed += max(a2 - a1, b2 - b1)
    table = difflib.HtmlDiff(wrapcolumn=90).make_table(
        old, new, html.escape(first.name), html.escape(second.name), context=True, numlines=2
    )
    out = resolve_path(ctx, str(first.with_name(f"{first.stem}-comparatif.html")))
    page = (
        '<!doctype html><meta charset="utf-8"><title>Comparatif</title><style>'
        "body{font:14px system-ui;margin:16px}table.diff{border-collapse:collapse;width:100%}"
        "td{vertical-align:top;padding:2px 6px}.diff_add{background:#d9f7d9}"
        ".diff_chg{background:#fff1b8}.diff_sub{background:#ffd6d6}</style>"
        f"<h1>{html.escape(first.name)} → {html.escape(second.name)}</h1>"
        f"<p>{added} paragraphe(s) ajouté(s), {removed} supprimé(s), {changed} modifié(s).</p>"
        f"{table}"
    )
    out.write_text(page, encoding="utf-8")
    return (
        f"{added} paragraphe(s) ajouté(s), {removed} supprimé(s), {changed} modifié(s). "
        f"Comparatif : {out}"
    )


def contract(ctx: ActionContext, operation: str, target: str, options: str = "") -> str:
    op = operation.strip().lower()
    if not target.strip():
        raise ActionError("précise le fichier du contrat")
    path = resolve_path(ctx, target)
    if op == "analyser":
        return analyse(read_text(path))[:MAX_READ_CHARS]
    if op == "comparer":
        if not options.strip():
            raise ActionError("options = le fichier de la seconde version")
        return compare(ctx, path, resolve_path(ctx, options))
    raise ActionError(f"opération inconnue : {operation} (au choix : {', '.join(CONTRACT_OPS)})")
