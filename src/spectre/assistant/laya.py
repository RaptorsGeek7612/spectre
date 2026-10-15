"""Laya: Spectre's intuition, a skill of Spectre alone (not of the agents it leads).

Laya (ConvAI Innovations, Apache 2.0) is an open-source « System 1 » decision model, compatible
with TypeSafe's Jev: given a state (a message, a ticket, a mission, JSON) and named questions,
it answers them all at once with calibrated probabilities, without generating text and without
tokens: `choice` (one option among labelled criteria), `score` (a level on an ordered rubric),
`noul` (the probability that a statement is true). Spectre uses it for fast, cheap judgements:
which agent should take a mission, how urgent a message is, whether a request is risky.

It runs on this PC through the `laya` package (`Router`, multilingual checkpoint by default,
CPU is enough), or through a `laya-serve` server (`laya_url` setting, Jev's `/v1/systemone`).
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

from spectre.assistant.config import AssistantConfig

LEAD = ("", "opus")  # who may use it: Spectre itself
KINDS = ("choice", "score", "noul")
MAX_QUESTIONS = 12
MAX_STATE = 20000
INSTALL = (
    "Laya n'est pas installé sur ce PC. Pour l'ajouter : `uv pip install laya` dans "
    "l'environnement de Spectre (PyTorch inclus, environ 1 Go avec le modèle), ou un serveur "
    "`laya-serve` dont l'adresse va dans le réglage laya_url."
)


class LayaError(ValueError):
    """Bad questions, or Laya unavailable (the message is for Spectre and the user)."""


_router: Any = None
_lock = threading.Lock()


def check(questions: Any) -> dict[str, Any]:
    """The questions in Laya's format, checked."""
    if isinstance(questions, str):
        try:
            questions = json.loads(questions)
        except ValueError as exc:
            raise LayaError(f"questions : JSON invalide ({exc})") from exc
    if not isinstance(questions, dict) or not questions:
        raise LayaError("questions : un objet {nom: {type, instructions, criteria}} attendu")
    if len(questions) > MAX_QUESTIONS:
        raise LayaError(f"{MAX_QUESTIONS} questions au maximum")
    for name, question in questions.items():
        if not isinstance(question, dict) or question.get("type") not in KINDS:
            raise LayaError(f"question « {name} » : type choice, score ou noul attendu")
        if not str(question.get("instructions", "")).strip():
            raise LayaError(f"question « {name} » : instructions manquantes")
        criteria = question.get("criteria")
        if question["type"] == "choice" and not (isinstance(criteria, dict) and len(criteria) >= 2):
            raise LayaError(f"question « {name} » : au moins deux options dans criteria")
        if question["type"] == "score" and not (isinstance(criteria, list) and len(criteria) >= 2):
            raise LayaError(f"question « {name} » : une échelle d'au moins deux niveaux")
    return questions


def _local(state: str, questions: dict[str, Any]) -> dict[str, Any]:
    global _router
    with _lock:
        if _router is None:
            try:
                from laya import Router  # type: ignore[import-not-found]
            except ImportError as exc:
                raise LayaError(INSTALL) from exc
            _router = Router()
        result = _router.predict(state, questions)
    return result if isinstance(result, dict) else {"answers": {}}


def _remote(url: str, state: str, questions: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"state": state, "questions": questions}).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/systemone",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - user's server
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LayaError(f"le serveur Laya ({url}) ne répond pas : {exc}") from exc
    return data if isinstance(data, dict) else {"answers": {}}


def decide(config: AssistantConfig, state: str, questions: Any) -> dict[str, Any]:
    """Laya's answers to `questions` about `state`."""
    checked = check(questions)
    state = str(state)[:MAX_STATE]
    if not state.strip():
        raise LayaError("état vide : donne le texte ou le JSON à juger")
    if config.laya_url:
        return _remote(config.laya_url, state, checked)
    return _local(state, checked)


def describe(result: dict[str, Any]) -> str:
    """The answers in a few lines for Spectre."""
    lines = []
    for name, answer in (result.get("answers") or {}).items():
        if not isinstance(answer, dict):
            continue
        if "choice" in answer:
            probs = answer.get("probabilities") or answer.get("probs") or {}
            best = probs.get(answer["choice"]) if isinstance(probs, dict) else None
            lines.append(f"- {name} : {answer['choice']}" + (f" ({best:.0%})" if best else ""))
        elif "noul" in answer:
            p = float(answer["noul"])
            lines.append(f"- {name} : {'oui' if p >= 0.5 else 'non'} ({p:.0%} de chances que oui)")
        elif "score" in answer:
            lines.append(f"- {name} : {answer['score']}")
        else:
            lines.append(f"- {name} : {json.dumps(answer, ensure_ascii=False)[:200]}")
        if isinstance(answer.get("confidence"), (int, float)):
            lines[-1] += f", confiance {answer['confidence']:.0%}"
    return "Laya (intuition, sans jetons) :\n" + ("\n".join(lines) or "aucune réponse")
