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
from spectre.assistant.config import agent_name, resolve_agent
from spectre.assistant.custom_agents import PREFIX, AgentError, CustomAgents
from spectre.assistant.db import now_iso
from spectre.assistant.governance import Gate, Level
from spectre.assistant.memory import Memory
from spectre.assistant.vision.faces import describe_presence


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


def _start_mission(ctx: ActionContext, goal: str, kind: str = "mission", agent: str = "") -> str:
    if not goal.strip():
        raise ActionError("objectif de mission vide")
    if kind not in ("mission", "redaction"):
        kind = "mission"
    plan: dict[str, str] = {"kind": kind}
    chosen = resolve_agent(agent)
    created = CustomAgents(ctx.db).get(agent) if not chosen else None  # unknown: the setting
    if created is not None:
        chosen = f"{PREFIX}{created['id']}"
    if chosen:
        plan["agent"] = chosen
    stamp = now_iso()
    mid = ctx.db.execute(
        "INSERT INTO missions(ts, goal, status, plan, updated_at) VALUES(?, ?, 'queued', ?, ?)",
        (stamp, goal.strip(), json.dumps(plan), stamp),
    )
    name = created["name"] if created is not None else agent_name(chosen)
    who = f", confiée à {name}" if chosen and chosen != "claude" else ""
    return (
        f"mission #{mid} lancée en arrière-plan{who} : {goal.strip()} "
        "(je te préviens quand c'est fini)"
    )


def _create_agent(
    ctx: ActionContext, name: str, engine: str, role: str, instructions: str = ""
) -> str:
    try:
        agent = CustomAgents(ctx.db).create(name, engine, role, instructions)
    except AgentError as exc:
        raise ActionError(str(exc)) from exc
    return (
        f"agent créé : {agent['name']} (moteur {agent_name(agent['engine'])}, "
        f"{agent['engine']}) — {agent['role']}. Confie-lui une mission avec "
        f'start_mission(agent="{agent["name"]}").'
    )


def _list_agents(ctx: ActionContext) -> str:
    builtin = (
        "Spectre (opus, toi), Gétro (sonnet), Kaïto (haiku, vérificateur), Kyra (chatgpt, "
        "multimédia), Syfer (mistral, cybersécurité) ; rédaction : Scout, Scribe, Warden"
    )
    created = CustomAgents(ctx.db).list()
    lines = [f"- {a['name']} ({a['engine']}) : {a['role']}" for a in created]
    return f"Agents intégrés : {builtin}\nAgents créés :\n" + ("\n".join(lines) or "(aucun)")


def _delete_agent(ctx: ActionContext, name: str) -> str:
    try:
        agent = CustomAgents(ctx.db).delete(name)
    except AgentError as exc:
        raise ActionError(str(exc)) from exc
    return f"agent supprimé : {agent['name']}"


def _who_is_there(ctx: ActionContext) -> str:
    return describe_presence(ctx.db)


def _missions(ctx: ActionContext) -> str:
    rows = ctx.db.all("SELECT id, goal, status, updated_at FROM missions ORDER BY id DESC LIMIT 10")
    if not rows:
        return "aucune mission"
    return "\n".join(f"#{r['id']} [{r['status']}] {r['goal']}" for r in rows)


def _write_risk(ctx: ActionContext, args: dict[str, Any]) -> tuple[Level, str]:
    try:
        path = actions.resolve_path(ctx, str(args.get("path", "")))
    except ActionError:
        return Level.WRITE, "write_file"
    if not path.exists():
        return Level.WRITE, "write_file"
    workspace = ctx.workspace.resolve()
    if workspace in path.parents:
        # Rewriting a draft in the agents' own folder: no approval, the previous version is
        # always kept in Spectre's trash (outside the workspace) and in the undo journal.
        return Level.WRITE, "write_file"
    return Level.DESTRUCTIVE, "overwrite_file"


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
            "Liste des écrans connectés, numérotés à partir de 1 (l'écran 1 est le principal).",
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
        Tool(
            "read_file",
            "Lire un fichier texte (20 000 caractères à la fois ; offset pour lire la suite).",
            Level.READ,
            "read",
            actions.read_file,
        ),
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
            "rapport). kind=redaction pour un texte soigné rédigé par Scout, Scribe et Warden. "
            "agent : qui exécute les étapes, par son nom ou son modèle. Kyra (chatgpt) pour les "
            "images, vidéos et le multimédia ; Syfer (mistral) pour la cybersécurité et les tests "
            "d'intrusion autorisés ; Gétro (sonnet) ou Kaïto (haiku, rapide) pour le reste ; "
            "ou un agent que tu as créé (create_agent), par son nom ; vide = le réglage.",
            Level.WRITE,
            "mission",
            _start_mission,
        ),
        Tool(
            "create_agent",
            "Créer un nouvel agent spécialisé, réutilisable dans les missions. name : le nom "
            "que l'UTILISATEUR lui a donné, mot pour mot (ne l'invente jamais : demande-le "
            "d'abord s'il ne l'a pas dit ; unique) ; engine : le modèle qui le fait tourner, "
            "parmi opus, sonnet, haiku, chatgpt, mistral ; role : sa spécialité en une "
            "phrase ; instructions : ses consignes de travail (facultatif).",
            Level.WRITE,
            "agent",
            _create_agent,
        ),
        Tool(
            "list_agents",
            "Tous les agents : intégrés et créés.",
            Level.READ,
            "read",
            _list_agents,
        ),
        Tool(
            "delete_agent",
            "Supprimer un agent que tu as créé (par son nom).",
            Level.DESTRUCTIVE,
            "agent",
            _delete_agent,
        ),
        Tool("list_missions", "État des missions.", Level.READ, "read", _missions),
        Tool(
            "who_is_there",
            "Qui est devant l'écran (caméra, personnes enregistrées seulement).",
            Level.READ,
            "read",
            _who_is_there,
        ),
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
