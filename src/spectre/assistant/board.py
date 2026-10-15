"""The board: departments give their view on a decision, the direction arbitrates, and the
decision is written down with what should be measured. When its review date comes, the real
figures (and the experiment created for it, if any) say whether it worked; the lesson feeds the
next deliberations.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from spectre.assistant.company import DEPARTMENTS, Companies, enqueue, resolve_department
from spectre.assistant.db import Database, now_iso
from spectre.assistant.experiments import ExperimentError, Experiments, describe
from spectre.assistant.saas import Saas

MAX_SEATS = 4
DEFAULT_SEATS = ("finance", "marketing", "produit")
OUTCOMES = ("réussie", "mitigée", "ratée")

SEATS = """\
Tu présides le conseil d'administration d'une entreprise. Choisis les 2 à {max} départements \
dont l'avis compte vraiment pour cette décision, parmi : {departments}. Réponds UNIQUEMENT par \
un objet JSON : {{"departments": ["...", "..."]}}."""

OPINION = """\
Tu sièges au conseil d'administration pour le département {label}. {duty}
Donne l'avis de ton département sur la décision, avec des chiffres quand tu en as, honnêtement \
(contredis si tu n'es pas d'accord). Réponds UNIQUEMENT par un objet JSON : {{"position": \
"pour|contre|nuancé", "arguments": ["..."], "risques": ["..."], "conditions": "ce qu'il \
faudrait pour être pour"}}."""

ARBITRATE = """\
Tu es la direction générale et tu arbitres après avoir entendu les départements. Décide en chef \
d'entreprise, chiffres à l'appui, en tenant compte des leçons des décisions passées. Choisis un \
indicateur pour juger plus tard si la décision a marché, parmi ceux disponibles : {metrics} \
(ou aucun si rien ne convient). Réponds UNIQUEMENT par un objet JSON : {{"options": \
[{{"nom": "...", "pour": "...", "contre": "..."}}], "decision": "...", "raisons": "...", \
"risques": ["..."], "prochaines_etapes": ["..."], "indicateur": "nom ou vide", "sens": \
"up|down", "variation_min": 5, "reevaluer_dans_jours": 30}}."""

REVIEW = """\
Tu es la direction générale et tu réévalues une décision prise il y a quelque temps, avec les \
vrais chiffres. Sois honnête : une décision peut avoir été bonne même si le résultat est \
mauvais, et inversement. Réponds UNIQUEMENT par un objet JSON : {{"resultat": \
"réussie|mitigée|ratée", "lecon": "la leçon à retenir pour les prochaines décisions, en une \
ou deux phrases"}}."""

Ask = Any  # (prompt, system) -> Reply
AskSeat = Any  # (department, prompt, system) -> Reply


class BoardError(ValueError):
    """A refused request (the message is for the user)."""


def _json(reply: Any) -> dict[str, Any]:
    from spectre.assistant.brain import extract_json, failed

    if failed(reply):
        raise BoardError(reply.text[:300])
    data = extract_json(reply.text)
    if not isinstance(data, dict):
        raise BoardError("réponse illisible")
    return data


class Board:
    def __init__(self, db: Database, root: Path | None = None) -> None:
        self.db = db
        self.root = root
        self.companies = Companies(db)

    def all(self, company_id: int) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT * FROM decisions WHERE company_id = ? ORDER BY id DESC", (company_id,)
        )
        return [self._load(r) for r in rows]

    def get(self, decision_id: int) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM decisions WHERE id = ?", (int(decision_id),))
        if row is None:
            raise BoardError(f"décision #{decision_id} introuvable")
        return self._load(row)

    @staticmethod
    def _load(row: dict[str, Any]) -> dict[str, Any]:
        for key in ("opinions", "verdict", "kpis_before"):
            row[key] = (
                json.loads(row[key] or "{}") if key != "opinions" else json.loads(row[key] or "[]")
            )
        return row

    def convene(self, company: str | int, question: str) -> tuple[dict[str, Any], int]:
        """Record the question and queue the deliberation; (decision, mission id)."""
        found = self.companies.get(company)
        question = question.strip()
        if len(question) < 10:
            raise BoardError(
                "pose la question en une phrase claire (ex. « passer l'offre à 29 € ? »)"
            )
        did = self.db.execute(
            "INSERT INTO decisions(company_id, question, created_at) VALUES(?, ?, ?)",
            (found["id"], question[:1000], now_iso()),
        )
        mid = enqueue(self.db, question, {"kind": "board", "decision": did})
        self.db.execute("UPDATE decisions SET mission_id = ? WHERE id = ?", (mid, did))
        return self.get(did), mid

    def lessons(self, company_id: int, limit: int = 5) -> str:
        rows = self.db.all(
            "SELECT question, outcome, lesson FROM decisions WHERE company_id = ? "
            "AND status = 'reviewed' ORDER BY id DESC LIMIT ?",
            (company_id, limit),
        )
        return "\n".join(f"- « {r['question']} » : {r['outcome']} — {r['lesson']}" for r in rows)

    def deliberate(self, decision_id: int, ask_seat: AskSeat, ask_lead: Ask, now: datetime) -> str:
        """Run the board: choose seats, hear them, arbitrate, write the memo."""
        decision = self.get(decision_id)
        company = self.companies.get(decision["company_id"])
        saas = Saas(self.db, self.root)
        context = self.companies.board(company["id"]) + "\n\n" + saas.report(company["id"], now)
        lessons = self.lessons(company["id"])
        if lessons:
            context += f"\n\nLeçons des décisions passées :\n{lessons}"
        question = f"Décision à prendre : {decision['question']}\n\nContexte :\n{context}"
        names = ", ".join(
            f"{k} ({label})" for k, (label, _) in DEPARTMENTS.items() if k != "direction"
        )
        try:
            picked = _json(ask_lead(question, SEATS.format(max=MAX_SEATS, departments=names)))
            seats = [resolve_department(str(d)) for d in picked.get("departments", [])]
        except (BoardError, ValueError):
            seats = []
        seats = [s for s in dict.fromkeys(seats) if s and s != "direction"][:MAX_SEATS]
        seats = seats or list(DEFAULT_SEATS)
        opinions = []
        for seat in seats:
            label, duty = DEPARTMENTS[seat]
            reply = ask_seat(seat, question, OPINION.format(label=label, duty=duty))
            try:
                view = _json(reply)
            except (BoardError, ValueError):
                view = {"position": "absent", "arguments": [reply.text[:500]]}
            opinions.append({"department": seat, "label": label, **view})
        heard = "\n\n".join(
            f"{o['label']} ({o.get('position', '?')}) : "
            + json.dumps(
                {k: v for k, v in o.items() if k not in ("department", "label")}, ensure_ascii=False
            )
            for o in opinions
        )
        kpis = saas.kpis(company["id"], now)
        verdict = _json(
            ask_lead(
                f"{question}\n\nAvis des départements :\n{heard}",
                ARBITRATE.format(metrics=", ".join(sorted(kpis)) or "aucun"),
            )
        )
        days = max(7, min(180, int(verdict.get("reevaluer_dans_jours") or 30)))
        self.db.execute(
            "UPDATE decisions SET status = 'decided', opinions = ?, verdict = ?, decision = ?, "
            "kpis_before = ?, review_at = ?, decided_at = ? WHERE id = ?",
            (
                json.dumps(opinions, ensure_ascii=False),
                json.dumps(verdict, ensure_ascii=False),
                str(verdict.get("decision", ""))[:2000],
                json.dumps(kpis),
                (now + timedelta(days=days)).isoformat(),
                now.isoformat(),
                decision_id,
            ),
        )
        metric = str(verdict.get("indicateur") or "").strip()
        if metric in kpis:
            try:
                experiment = Experiments(self.db, self.root).start(
                    company["id"],
                    f"Décision #{decision_id} : {verdict.get('decision', decision['question'])}",
                    metric,
                    str(verdict.get("sens") or "up"),
                    float(verdict.get("variation_min") or 5),
                    days,
                    decision_id=decision_id,
                    now=now,
                )
                self.db.execute(
                    "UPDATE decisions SET experiment_id = ? WHERE id = ?",
                    (experiment["id"], decision_id),
                )
            except (ExperimentError, ValueError, TypeError):
                pass
        return memo(self.get(decision_id), company["name"])

    def due_reviews(self, now: datetime) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT * FROM decisions WHERE status = 'decided' AND review_at <= ?",
            (now.isoformat(),),
        )
        return [self._load(r) for r in rows]

    def queue_review(self, decision_id: int) -> int:
        decision = self.get(decision_id)
        if decision["status"] not in ("decided",):
            raise BoardError(f"la décision #{decision_id} n'est pas en attente de réévaluation")
        self.db.execute("UPDATE decisions SET status = 'reviewing' WHERE id = ?", (decision_id,))
        return enqueue(
            self.db,
            f"Réévaluer : {decision['question']}",
            {"kind": "board_review", "decision": decision_id},
        )

    def review(self, decision_id: int, ask_lead: Ask, now: datetime) -> str:
        """Judge a decision with the figures since; returns the review's text."""
        decision = self.get(decision_id)
        saas = Saas(self.db, self.root)
        after = saas.kpis(decision["company_id"], now)
        lines = [
            f"Décision #{decision_id} : {decision['question']}",
            f"Décidé : {decision['decision']}",
            f"Raisons : {decision['verdict'].get('raisons', '')}",
        ]
        if decision["experiment_id"]:
            experiments = Experiments(self.db, self.root)
            experiment = experiments.get(decision["experiment_id"])
            if experiment["status"] == "running":
                experiment = experiments.evaluate(experiment, now)
            lines.append(f"Expérience : {describe(experiment)}")
        before = decision["kpis_before"]
        moved = [
            f"{k} : {before[k]:g} → {after[k]:g}"
            for k in sorted(set(before) & set(after))
            if before[k] != after[k]
        ]
        lines.append("Indicateurs depuis la décision : " + ("; ".join(moved) or "inchangés"))
        result = _json(ask_lead("\n".join(lines), REVIEW))
        outcome = str(result.get("resultat", "mitigée"))
        outcome = outcome if outcome in OUTCOMES else "mitigée"
        lesson = str(result.get("lecon", ""))[:1000]
        self.db.execute(
            "UPDATE decisions SET status = 'reviewed', outcome = ?, lesson = ?, reviewed_at = ? "
            "WHERE id = ?",
            (outcome, lesson, now.isoformat(), decision_id),
        )
        return f"{outcome.capitalize()} : {lesson}"

    def failed(self, decision_id: int, reason: str) -> None:
        self.db.execute(
            "UPDATE decisions SET status = CASE WHEN status = 'reviewing' THEN 'decided' "
            "ELSE 'failed' END, lesson = CASE WHEN status = 'reviewing' THEN lesson ELSE ? END "
            "WHERE id = ?",
            (reason[:500], decision_id),
        )


def memo(decision: dict[str, Any], company: str) -> str:
    """The decision memo in Markdown."""
    verdict = decision["verdict"]
    lines = [
        f"# Conseil de {company} — décision #{decision['id']}",
        "",
        f"**Question** : {decision['question']}",
        "",
    ]
    lines.append("## Avis des départements")
    for opinion in decision["opinions"]:
        lines.append(
            f"- **{opinion['label']}** ({opinion.get('position', '?')}) : "
            + "; ".join(map(str, opinion.get("arguments", [])))
        )
        if opinion.get("risques"):
            lines.append(f"  - risques : {'; '.join(map(str, opinion['risques']))}")
    if verdict.get("options"):
        lines += ["", "## Options"]
        for option in verdict["options"]:
            if isinstance(option, dict):
                lines.append(
                    f"- **{option.get('nom', '')}** — pour : {option.get('pour', '')} ; "
                    f"contre : {option.get('contre', '')}"
                )
    lines += [
        "",
        "## Décision",
        str(verdict.get("decision", "")),
        "",
        f"**Raisons** : {verdict.get('raisons', '')}",
    ]
    if verdict.get("risques"):
        lines.append(f"**Risques** : {'; '.join(map(str, verdict['risques']))}")
    if verdict.get("prochaines_etapes"):
        lines += ["", "## Prochaines étapes"] + [f"- {s}" for s in verdict["prochaines_etapes"]]
    lines += ["", f"Réévaluation prévue le {str(decision['review_at'])[:10]}"]
    if decision["experiment_id"]:
        lines[-1] += (
            f", mesurée par l'expérience #{decision['experiment_id']} ({verdict.get('indicateur')})"
        )
    return "\n".join(lines) + "\n"
