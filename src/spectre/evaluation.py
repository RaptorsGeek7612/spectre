"""Measure Spectre on a set of cases: `spectre eval CASES`.

A case is one JSON object per line (or a JSON list in a `.json` file):

    {"id": "lettre", "request": "Écris une lettre de résiliation courte",
     "checks": {"min_words": 60, "max_words": 250, "include": ["résiliation"],
                "exclude": ["Lorem"], "approved": true, "max_cost_usd": 0.10},
     "criteria": ["Le ton est poli et ferme", "La date d'effet est demandée"]}

`checks` are free and automatic. `criteria` are graded by a judge (Warden's model at low effort)
only with `--judge`. A case passes when every check and every criterion passes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from spectre.costs import total_cost, usage_from_message
from spectre.errors import ConfigurationError, SpectreError
from spectre.graph import SpectreResult, run
from spectre.state import UsageRecord

CHECK_KEYS: Final = {"min_words", "max_words", "include", "exclude", "approved", "max_cost_usd"}
_WORD = re.compile(r"\w+(?:['’-]\w+)*")

JUDGE_PROMPT: Final = """\
Tu évalues un texte produit par un assistant de rédaction, critère par critère, sans \
indulgence : un critère n'est rempli que si le texte le satisfait clairement.
Réponds UNIQUEMENT par un objet JSON : {"results": [{"ok": true|false, "note": "raison \
courte"}, ...]}, un élément par critère, dans l'ordre donné."""

Runner = Callable[..., SpectreResult]


@dataclass(frozen=True)
class Case:
    id: str
    request: str
    checks: Mapping[str, Any] = field(default_factory=dict)
    criteria: Sequence[str] = ()


@dataclass
class CaseResult:
    case: Case
    final_text: str = ""
    failures: list[str] = field(default_factory=list)
    judgments: list[dict[str, Any]] = field(default_factory=list)
    usage: list[UsageRecord] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and not self.failures

    @property
    def words(self) -> int:
        return count_words(self.final_text)

    @property
    def cost_usd(self) -> float | None:
        return total_cost(self.usage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case.id,
            "passed": self.passed,
            "failures": self.failures,
            "judgments": self.judgments,
            "words": self.words,
            "cost_usd": self.cost_usd,
            "error": self.error,
            "final_text": self.final_text,
        }


def count_words(text: str) -> int:
    return len(_WORD.findall(text))


def load_cases(path: Path) -> list[Case]:
    """Cases from JSON Lines, or a JSON list when the file is a `.json`."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigurationError(f"impossible de lire {path} : {exc}") from exc
    try:
        if path.suffix == ".json":
            loaded = json.loads(raw)
            entries = loaded if isinstance(loaded, list) else [loaded]
        else:
            entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except ValueError as exc:
        raise ConfigurationError(f"{path.name} : JSON invalide ({exc})") from exc
    cases = [_parse_case(entry, index) for index, entry in enumerate(entries, start=1)]
    if not cases:
        raise ConfigurationError(f"{path.name} : aucun cas")
    return cases


def _parse_case(entry: Any, index: int) -> Case:
    where = f"cas n°{index}"
    if not isinstance(entry, dict) or not str(entry.get("request", "")).strip():
        raise ConfigurationError(f"{where} : objet avec « request » attendu")
    checks = entry.get("checks", {})
    if not isinstance(checks, dict) or set(checks) - CHECK_KEYS:
        raise ConfigurationError(f"{where} : checks inconnus ({', '.join(sorted(CHECK_KEYS))})")
    criteria = entry.get("criteria", [])
    if not isinstance(criteria, list) or not all(isinstance(c, str) for c in criteria):
        raise ConfigurationError(f"{where} : criteria doit être une liste de phrases")
    return Case(
        str(entry.get("id", f"cas{index}")), str(entry["request"]).strip(), checks, criteria
    )


def check(case: Case, result: SpectreResult) -> list[str]:
    """The automatic checks that `result` fails (empty when all pass)."""
    checks, text = case.checks, result.final_text
    lowered, words = text.lower(), count_words(text)
    failures: list[str] = []
    if "min_words" in checks and words < int(checks["min_words"]):
        failures.append(f"{words} mots, minimum {checks['min_words']}")
    if "max_words" in checks and words > int(checks["max_words"]):
        failures.append(f"{words} mots, maximum {checks['max_words']}")
    failures += [f"absent : « {w} »" for w in checks.get("include", []) if w.lower() not in lowered]
    failures += [f"présent : « {w} »" for w in checks.get("exclude", []) if w.lower() in lowered]
    if "approved" in checks and bool(checks["approved"]) != result.approved:
        failures.append("Warden n'a pas validé le texte" if checks["approved"] else "validé")
    cost = result.total_cost_usd
    if "max_cost_usd" in checks and cost is not None and cost > float(checks["max_cost_usd"]):
        failures.append(f"coût {cost:.4f} $ > {float(checks['max_cost_usd']):.4f} $")
    return failures


def judge(case: Case, text: str, model: BaseChatModel) -> tuple[list[dict[str, Any]], AIMessage]:
    """Grade `text` against the case's criteria: [{"criterion", "ok", "note"}]."""
    listing = "\n".join(f"{i}. {c}" for i, c in enumerate(case.criteria, start=1))
    human = (
        f"<demande>\n{case.request}\n</demande>\n\n<texte>\n{text}\n</texte>\n\n"
        f"<criteres>\n{listing}\n</criteres>"
    )
    answer = model.invoke([SystemMessage(JUDGE_PROMPT), HumanMessage(human)])
    assert isinstance(answer, AIMessage)
    raw = str(answer.text)
    start, end = raw.find("{"), raw.rfind("}")
    try:
        results = json.loads(raw[start : end + 1]).get("results", []) if 0 <= start < end else []
    except (ValueError, AttributeError):
        results = []
    judgments = []
    for index, criterion in enumerate(case.criteria):
        entry = results[index] if index < len(results) and isinstance(results[index], dict) else {}
        judgments.append(
            {
                "criterion": criterion,
                "ok": entry.get("ok") is True,
                "note": str(entry.get("note", "jugement illisible" if not entry else "")),
            }
        )
    return judgments, answer


def run_eval(
    cases: Sequence[Case],
    *,
    runner: Runner = run,
    judge_model: BaseChatModel | None = None,
    judge_name: str = "",
    notify: Callable[[str], None] = print,
    **run_kwargs: Any,
) -> list[CaseResult]:
    """Run every case through Spectre (and the judge, when given) and grade it."""
    results: list[CaseResult] = []
    for index, case in enumerate(cases, start=1):
        notify(f"[{index}/{len(cases)}] {case.id}")
        outcome = CaseResult(case)
        try:
            result = runner(case.request, **run_kwargs)
        except SpectreError as exc:
            outcome.error = str(exc)
            results.append(outcome)
            continue
        outcome.final_text, outcome.usage = result.final_text, list(result.usage)
        outcome.failures = check(case, result)
        if judge_model is not None and case.criteria:
            outcome.judgments, answer = judge(case, result.final_text, judge_model)
            outcome.usage.append(usage_from_message("juge", judge_name, answer))
            outcome.failures += [
                f"critère : {j['criterion']}" for j in outcome.judgments if not j["ok"]
            ]
        results.append(outcome)
    return results


def format_report(results: Sequence[CaseResult]) -> str:
    """A plain-text table of the cases, then the pass rate and the total cost."""
    lines = [f"{'Cas':<20} {'Résultat':<9} {'Mots':>5} {'Coût ($)':>10}  Détail"]
    for r in results:
        cost = "n/d" if r.cost_usd is None else f"{r.cost_usd:.4f}"
        status = "réussi" if r.passed else "échec"
        detail = r.error or "; ".join(r.failures)
        lines.append(f"{r.case.id[:20]:<20} {status:<9} {r.words:>5} {cost:>10}  {detail}".rstrip())
    passed = sum(r.passed for r in results)
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    total = f"{sum(costs):.4f} $" if costs else "n/d"
    lines.append(f"{passed}/{len(results)} cas réussis — coût total {total}")
    return "\n".join(lines)
