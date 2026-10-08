"""Spectre's tools: one registry, one execution path, always through the governance gate.

Both the MCP server (called by the brain) and the web UI (approvals) use `execute` /
`run_approved`, so no action can bypass the gate or the audit log.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spectre.assistant import actions
from spectre.assistant.actions import ActionContext, ActionError
from spectre.assistant.db import now_iso
from spectre.assistant.governance import Gate, Level
from spectre.assistant.memory import Memory


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    level: Level
    category: str
    run: Callable[..., str]
    classify: Callable[[ActionContext, dict[str, Any]], tuple[Level, str]] | None = None

    def risk(self, ctx: ActionContext, args: dict[str, Any]) -> tuple[Level, str]:
        return self.classify(ctx, args) if self.classify else (self.level, self.category)


# ---- tool bodies that need more than an action -----------------------------------------------


def _remember(
    ctx: ActionContext, subject: str, predicate: str, value: str, category: str = "autre"
) -> str:
    fact = Memory(ctx.db).remember(subject, predicate, value, category=category)
    return f"mémorisé (#{fact['id']}, {fact['outcome']}) : {subject} {predicate} {value}"


def _recall(ctx: ActionContext, query: str) -> str:
    facts = Memory(ctx.db).recall(query)
    if not facts:
        return "rien en mémoire sur ce sujet"
    return "\n".join(
        f"#{f['id']} [{f['category']}] {f['subject']} {f['predicate']} {f['value']}" for f in facts
    )


def _forget(ctx: ActionContext, fact_id: int) -> str:
    fact = Memory(ctx.db).forget(int(fact_id))
    return f"oublié : #{fact['id']} {fact['subject']} {fact['predicate']} {fact['value']}"


def _start_mission(ctx: ActionContext, goal: str, kind: str = "mission") -> str:
    if not goal.strip():
        raise ActionError("objectif de mission vide")
    if kind not in ("mission", "redaction"):
        kind = "mission"
    stamp = now_iso()
    mid = ctx.db.execute(
        "INSERT INTO missions(ts, goal, status, plan, updated_at) VALUES(?, ?, 'queued', ?, ?)",
        (stamp, goal.strip(), json.dumps({"kind": kind}), stamp),
    )
    return (
        f"mission #{mid} lancée en arrière-plan : {goal.strip()} (je te préviens quand c'est fini)"
    )


def _missions(ctx: ActionContext) -> str:
    rows = ctx.db.all("SELECT id, goal, status, updated_at FROM missions ORDER BY id DESC LIMIT 10")
    if not rows:
        return "aucune mission"
    return "\n".join(f"#{r['id']} [{r['status']}] {r['goal']}" for r in rows)


def _write_risk(ctx: ActionContext, args: dict[str, Any]) -> tuple[Level, str]:
    try:
        exists = actions.resolve_path(ctx, str(args.get("path", ""))).exists()
    except ActionError:
        exists = False
    return (Level.DESTRUCTIVE, "overwrite_file") if exists else (Level.WRITE, "write_file")


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool("current_time", "Date et heure actuelles.", Level.READ, "read", actions.current_time),
        Tool(
            "system_info",
            "Infos système (OS, cœurs, disque).",
            Level.READ,
            "read",
            actions.system_info,
        ),
        Tool(
            "list_screens",
            "Liste des écrans connectés (index pour ouvrir sur un écran).",
            Level.READ,
            "read",
            actions.list_screens,
        ),
        Tool(
            "remember",
            "Retenir un fait durable sur l'utilisateur (sujet, prédicat, valeur, "
            "catégorie parmi identite, preference, habitude, projet, objectif, relation, lieu, "
            "evenement, persona, autre).",
            Level.WRITE,
            "memory",
            _remember,
        ),
        Tool("recall", "Chercher dans la mémoire de Spectre.", Level.READ, "memory", _recall),
        Tool(
            "forget", "Oublier un fait mémorisé (par son numéro).", Level.WRITE, "memory", _forget
        ),
        Tool(
            "open_url",
            "Ouvrir une page web (option : numéro d'écran).",
            Level.UI,
            "open",
            actions.open_url,
        ),
        Tool(
            "open_app",
            "Lancer une application par son nom (option : numéro d'écran).",
            Level.UI,
            "open",
            actions.open_app,
        ),
        Tool("list_dir", "Lister un dossier.", Level.READ, "read", actions.list_dir),
        Tool("read_file", "Lire un fichier texte.", Level.READ, "read", actions.read_file),
        Tool(
            "search_files",
            "Chercher des fichiers par nom dans un dossier.",
            Level.READ,
            "read",
            actions.search_files,
        ),
        Tool(
            "write_file",
            "Créer ou remplacer un fichier texte (remplacer demande validation).",
            Level.WRITE,
            "write_file",
            actions.write_file,
            _write_risk,
        ),
        Tool(
            "move_file",
            "Déplacer ou renommer un fichier.",
            Level.WRITE,
            "write_file",
            actions.move_file,
        ),
        Tool(
            "delete_file",
            "Mettre un fichier à la corbeille de Spectre (validation requise).",
            Level.DESTRUCTIVE,
            "delete_file",
            actions.delete_file,
        ),
        Tool(
            "undo",
            "Annuler les dernières actions sur les fichiers.",
            Level.WRITE,
            "write_file",
            actions.undo_last,
        ),
        Tool(
            "set_reminder",
            "Programmer un rappel (date ISO locale, texte).",
            Level.WRITE,
            "reminder",
            actions.set_reminder,
        ),
        Tool("list_reminders", "Rappels en attente.", Level.READ, "read", actions.list_reminders),
        Tool(
            "start_mission",
            "Lancer une mission longue en arrière-plan (plan, étapes vérifiées, "
            "rapport). kind=redaction pour un texte soigné rédigé par Scout, Scribe et Warden.",
            Level.WRITE,
            "mission",
            _start_mission,
        ),
        Tool("list_missions", "État des missions.", Level.READ, "read", _missions),
    ]
}


def make_context(db: Any, root: Path, allowed_roots: list[str]) -> ActionContext:
    return ActionContext(
        db=db, root=root, allowed_roots=[Path(r).expanduser() for r in allowed_roots]
    )


def execute(gate: Gate, ctx: ActionContext, name: str, args: dict[str, Any]) -> str:
    """Run a tool through the gate; return the text shown to the brain/user."""
    tool = TOOLS.get(name)
    if tool is None:
        return f"outil inconnu : {name}"
    level, category = tool.risk(ctx, args)
    decision = gate.decide(level, category)
    if decision.verdict == "refused":
        gate.record(name, args, level, category, "refused", decision.reason)
        return f"REFUSÉ : {decision.reason}"
    if decision.verdict == "approval":
        approval_id = ctx.db.execute(
            "INSERT INTO approvals(ts, tool, args, level, category, reason) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (
                now_iso(),
                name,
                json.dumps(args, ensure_ascii=False),
                int(level),
                category,
                decision.reason,
            ),
        )
        gate.record(name, args, level, category, "approval", f"demande #{approval_id}")
        return (
            f"EN ATTENTE DE VALIDATION (#{approval_id}) : {decision.reason}. "
            "Dis à l'utilisateur ce que tu veux faire et qu'il peut valider ou refuser."
        )
    return _run(gate, ctx, tool, args, level, category, "auto")


def _run(
    gate: Gate,
    ctx: ActionContext,
    tool: Tool,
    args: dict[str, Any],
    level: Level,
    category: str,
    decision: str,
) -> str:
    try:
        result = tool.run(ctx, **args)
    except ActionError as exc:
        result = f"ÉCHEC : {exc}"
    except (TypeError, KeyError) as exc:
        result = f"ÉCHEC : paramètres invalides ({exc})"
    except OSError as exc:
        result = f"ÉCHEC : {exc}"
    gate.record(tool.name, args, level, category, decision, result)
    ctx.db.log_event("action", "spectre", f"{tool.name}: {result[:300]}", tool=tool.name, args=args)
    return result


def run_approved(gate: Gate, ctx: ActionContext, approval_id: int) -> str:
    """Execute a pending action the user approved."""
    row = ctx.db.one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
    if row is None:
        raise KeyError(approval_id)
    if row["status"] != "pending":
        raise ValueError(f"demande #{approval_id} déjà traitée ({row['status']})")
    tool = TOOLS[row["tool"]]
    args = json.loads(row["args"])
    result = _run(gate, ctx, tool, args, Level(row["level"]), row["category"], "approved")
    status = "failed" if result.startswith("ÉCHEC") else "executed"
    ctx.db.execute(
        "UPDATE approvals SET status = ?, result = ?, decided_at = ? WHERE id = ?",
        (status, result, now_iso(), approval_id),
    )
    return result


def deny(ctx: ActionContext, approval_id: int, reason: str = "") -> None:
    row = ctx.db.one("SELECT status FROM approvals WHERE id = ?", (approval_id,))
    if row is None:
        raise KeyError(approval_id)
    if row["status"] != "pending":
        raise ValueError(f"demande #{approval_id} déjà traitée ({row['status']})")
    ctx.db.execute(
        "UPDATE approvals SET status = 'denied', result = ?, decided_at = ? WHERE id = ?",
        (reason or "refusé par l'utilisateur", now_iso(), approval_id),
    )
