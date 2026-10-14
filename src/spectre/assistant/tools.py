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

from spectre.assistant import actions, competences, powershell
from spectre.assistant.actions import ActionContext, ActionError
from spectre.assistant.company import (
    DEPARTMENTS,
    STATUS_LABELS,
    Companies,
    CompanyError,
    enqueue,
    steer_mission,
    stop_mission,
)
from spectre.assistant.config import agent_name, resolve_agent
from spectre.assistant.custom_agents import PREFIX, AgentError, CustomAgents
from spectre.assistant.db import now_iso
from spectre.assistant.governance import Gate, Level
from spectre.assistant.memory import Memory
from spectre.assistant.providers import ProviderError, Providers
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


def _competence(ctx: ActionContext, name: str) -> str:
    try:
        return competences.read(name)
    except ValueError as exc:
        raise ActionError(str(exc)) from exc


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
        agent = CustomAgents(ctx.db, Providers(ctx.root)).create(name, engine, role, instructions)
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


def _engine_change(ctx: ActionContext, change: Callable[[Any, Providers], str]) -> str:
    """Apply a change to the engine settings in `config.json` (the service reloads it)."""
    from spectre.assistant.config import AssistantConfig

    config = AssistantConfig.load(ctx.root)
    try:
        message = change(config, Providers(ctx.root))
    except (ProviderError, ValueError) as exc:
        raise ActionError(str(exc)) from exc
    config.save(ctx.root)
    return message


def _list_models(ctx: ActionContext) -> str:
    from spectre.assistant import engines
    from spectre.assistant.config import AssistantConfig

    return engines.summary(AssistantConfig.load(ctx.root), Providers(ctx.root))


def _set_model(ctx: ActionContext, role: str, engine: str) -> str:
    from spectre.assistant import engines

    def change(config: Any, providers: Providers) -> str:
        setting = engines.assign(config, providers, role, engine)
        return f"moteur changé : {setting} = {getattr(config, setting) or '(le cerveau)'}"

    return _engine_change(ctx, change)


def _set_fallbacks(ctx: ActionContext, engines: str) -> str:
    from spectre.assistant.engines import set_fallbacks

    def change(config: Any, providers: Providers) -> str:
        set_fallbacks(config, providers, engines.replace(";", ",").split(","))
        return "moteurs de secours : " + (", ".join(config.fallback_models) or "(aucun)")

    return _engine_change(ctx, change)


def _company_call(action: Callable[[], str]) -> str:
    try:
        return action()
    except CompanyError as exc:
        raise ActionError(str(exc)) from exc


def _ids(text: str) -> list[int]:
    """ "3, #5 7" -> [3, 5, 7]."""
    cleaned = text.replace("#", " ").replace(",", " ").replace(";", " ").split()
    return [int(t) for t in cleaned if t.isdigit()]


def _create_company(ctx: ActionContext, name: str, pitch: str = "") -> str:
    def run() -> str:
        found = Companies(ctx.db).create(name, pitch)
        return (
            f"entreprise #{found['id']} créée : {found['name']}. Organigramme vide : place un "
            f"agent sur chaque poste avec set_post ({', '.join(DEPARTMENTS)})."
        )

    return _company_call(run)


def _list_companies(ctx: ActionContext) -> str:
    rows = Companies(ctx.db).all()
    if not rows:
        return "aucune entreprise (create_company pour en créer une)"
    return "\n".join(
        f"#{c['id']} {c['name']}{' (pilote automatique)' if c['autopilot'] else ''}"
        f"{' : ' + c['pitch'][:120] if c['pitch'] else ''}"
        for c in rows
    )


def _company_board(ctx: ActionContext, company: str = "") -> str:
    return _company_call(lambda: Companies(ctx.db).board(company))


def _set_post(ctx: ActionContext, company: str, department: str, agent: str = "") -> str:
    def run() -> str:
        companies = Companies(ctx.db)
        key = companies.set_post(company, department, agent)
        return f"poste {department} : {companies.agent_label(key)}"

    return _company_call(run)


def _add_task(
    ctx: ActionContext,
    company: str,
    title: str,
    department: str = "",
    detail: str = "",
    priority: int = 2,
    depends_on: str = "",
    agent: str = "",
) -> str:
    def run() -> str:
        task = Companies(ctx.db).add_task(
            company,
            title,
            department=department,
            detail=detail,
            priority=int(priority),
            depends_on=_ids(str(depends_on)),
            agent=agent,
        )
        where = task["department"] or "sans département"
        return f"tâche #{task['id']} ajoutée ({where}) : {task['title']}"

    return _company_call(run)


def _plan_company(ctx: ActionContext, company: str, objective: str) -> str:
    def run() -> str:
        found = Companies(ctx.db).get(company)
        if len(objective.strip()) < 5:
            raise CompanyError("décris l'objectif à découper")
        mid = enqueue(
            ctx.db,
            objective.strip(),
            {"kind": "company_plan", "company": found["id"]},
        )
        return (
            f"mission #{mid} : la direction découpe l'objectif en tâches pour {found['name']} "
            "(je te préviens quand le tableau est prêt)"
        )

    return _company_call(run)


def _update_task(ctx: ActionContext, task_id: int, status: str, note: str = "") -> str:
    def run() -> str:
        task = Companies(ctx.db).set_status(task_id, status, note)
        return f"tâche #{task['id']} : {STATUS_LABELS[task['status']]}"

    return _company_call(run)


def _start_tasks(ctx: ActionContext, company: str = "", task_ids: str = "") -> str:
    def run() -> str:
        companies = Companies(ctx.db)
        ids = _ids(str(task_ids))
        if ids:
            started = [(t, companies.start(t)) for t in ids]
        else:
            ready = companies.ready(company)
            started = [(t["id"], companies.start(t["id"])) for t in ready]
        if not started:
            return "aucune tâche prête (à faire, dépendances terminées)"
        return "lancées : " + ", ".join(f"tâche #{t} → mission #{m}" for t, m in started)

    return _company_call(run)


def _set_autopilot(ctx: ActionContext, company: str, on: bool) -> str:
    def run() -> str:
        found = Companies(ctx.db).set_autopilot(company, bool(on))
        state = "activé" if found["autopilot"] else "désactivé"
        return f"pilote automatique {state} pour {found['name']}"

    return _company_call(run)


def _steer_mission(ctx: ActionContext, mission_id: int, message: str) -> str:
    return _company_call(lambda: steer_mission(ctx.db, int(mission_id), message))


def _stop_mission(ctx: ActionContext, mission_id: int) -> str:
    return _company_call(lambda: stop_mission(ctx.db, int(mission_id)))


def _routine_call(action: Callable[[], str]) -> str:
    from spectre.assistant.company import CompanyError
    from spectre.assistant.routines import RoutineError

    try:
        return action()
    except (RoutineError, CompanyError) as exc:
        raise ActionError(str(exc)) from exc


def _create_routine(
    ctx: ActionContext,
    name: str,
    schedule: str,
    prompt: str,
    kind: str = "mission",
    agent: str = "",
    company: str = "",
) -> str:
    from spectre.assistant.routines import Routines

    def run() -> str:
        company_id = Companies(ctx.db).get(company)["id"] if company.strip() else None
        if agent.strip():
            Companies(ctx.db).agent_key(agent)  # unknown agent: refused now, not at run time
        row = Routines(ctx.db).create(
            name, schedule, prompt, kind=kind, agent=agent, company_id=company_id
        )
        upcoming = row["next_run"][:16].replace("T", " à ") if row["next_run"] else "jamais"
        return f"routine #{row['id']} « {row['name']} » : {row['when']} (prochaine : {upcoming})"

    return _routine_call(run)


def _list_routines(ctx: ActionContext) -> str:
    from spectre.assistant.routines import Routines

    rows = Routines(ctx.db).all()
    if not rows:
        return "aucune routine"
    return "\n".join(
        f"#{r['id']} {r['name']} [{r['kind']}{'' if r['enabled'] else ', en pause'}] "
        f"{r['when']} — {r['prompt'][:80]}"
        + (f" (dernière : {r['last_status']})" if r["last_status"] else "")
        for r in rows
    )


def _update_routine(
    ctx: ActionContext, routine: str, enabled: str = "", schedule: str = "", prompt: str = ""
) -> str:
    from spectre.assistant.routines import Routines

    def run() -> str:
        flag = {"oui": True, "true": True, "1": True, "non": False, "false": False, "0": False}
        state = flag.get(enabled.strip().lower()) if enabled.strip() else None
        row = Routines(ctx.db).update(routine, enabled=state, schedule=schedule, prompt=prompt)
        return f"routine #{row['id']} : {row['when']}, {'active' if row['enabled'] else 'en pause'}"

    return _routine_call(run)


def _delete_routine(ctx: ActionContext, routine: str) -> str:
    from spectre.assistant.routines import Routines

    return _routine_call(lambda: f"routine supprimée : {Routines(ctx.db).delete(routine)['name']}")


def _run_routine(ctx: ActionContext, routine: str) -> str:
    from spectre.assistant.routines import Routines

    def run() -> str:
        row = Routines(ctx.db).get(routine)
        ctx.db.execute(
            "UPDATE routines SET next_run = ?, enabled = 1 WHERE id = ?", (now_iso(), row["id"])
        )
        return f"routine « {row['name']} » lancée (dans moins d'une minute)"

    return _routine_call(run)


def _list_webhooks(ctx: ActionContext) -> str:
    from spectre.assistant.webhooks import Webhooks

    rows = Webhooks(ctx.db).all()
    if not rows:
        return "aucun webhook (ils se créent dans la vue Automatisation)"
    return "\n".join(
        f"/hooks/{w['name']} ({w['source']}, {w['action']}"
        f"{', ' + ', '.join(w['events']) if w['events'] else ''}) : {w['received']} reçu(s)"
        for w in rows
    )


ASK_AGENT = (
    "Tu es {name}, un agent de Spectre. Un autre agent (ou Spectre) te pose une question "
    "dans ton domaine : réponds-lui directement, de façon précise et brève, sans outils. "
    "Si la question sort de ton domaine, dis-le."
)


def _ask_agent(ctx: ActionContext, agent: str, message: str) -> str:
    """One question to another agent, on its own engine, with its role (no tools: no loops)."""
    from spectre.assistant.brain import ClaudeCLI
    from spectre.assistant.config import AssistantConfig
    from spectre.assistant.engines import Engines

    created = CustomAgents(ctx.db).get(agent)
    key = resolve_agent(agent)
    if created is None and not key:
        raise ActionError(f"agent inconnu « {agent} »")
    if not message.strip():
        raise ActionError("message vide")
    config = AssistantConfig.load(ctx.root)
    engine = created["engine"] if created else (config.mission_model if key == "claude" else key)
    name = created["name"] if created else agent_name(key)
    system = ASK_AGENT.format(name=name)
    if created:
        system += f"\n\nTon rôle : {created['role']}"
        if created["instructions"]:
            system += f"\nTes consignes : {created['instructions']}"
    reply = Engines(ClaudeCLI(config, ctx.root)).ask_chain(
        [engine, *config.fallback_models], message.strip()[:4000], system
    )[0]
    ctx.db.log_event("agent_message", "spectre", f"→ {name} : {message[:300]}", agent=name)
    if reply.is_error:
        raise ActionError(f"{name} n'a pas pu répondre : {reply.text[:300]}")
    return f"{name} répond : {reply.text}"


def _saas(ctx: ActionContext, company: str, run: Callable[[Any, dict[str, Any], Any], str]) -> str:
    """Run `run(saas, company, now)` with errors turned into tool failures."""
    from datetime import datetime

    from spectre.assistant.saas import Saas, SaasError

    try:
        found = Companies(ctx.db).get(company)
        return run(Saas(ctx.db, ctx.root), found, datetime.now().astimezone())
    except (CompanyError, SaasError) as exc:
        raise ActionError(str(exc)) from exc


def _saas_report(ctx: ActionContext, company: str = "") -> str:
    return _saas(ctx, company, lambda saas, found, now: saas.report(found["id"], now))


def _set_metric(ctx: ActionContext, company: str, metric: str, value: float) -> str:
    def run(saas: Any, found: dict[str, Any], now: Any) -> str:
        saas.record(found["id"], metric.strip(), float(value), now)
        return f"{metric.strip()} = {value} enregistré pour {found['name']}"

    return _saas(ctx, company, run)


def _add_monitor(ctx: ActionContext, company: str, url: str, name: str = "") -> str:
    def run(saas: Any, found: dict[str, Any], now: Any) -> str:
        source = saas.add_source(found["id"], "uptime", name or url, {"url": url})
        return (
            f"surveillance #{source['id']} de {source['config']['url']} ajoutée pour "
            f"{found['name']} (toutes les 5 minutes ; alerte après deux échecs d'affilée)"
        )

    return _saas(ctx, company, run)


def _add_alert(
    ctx: ActionContext, company: str, metric: str, op: str, threshold: float, label: str = ""
) -> str:
    def run(saas: Any, found: dict[str, Any], now: Any) -> str:
        rule = saas.add_alert(found["id"], metric, op, float(threshold), label=label)
        return f"alerte #{rule['id']} : {rule['metric']} {rule['op']} {rule['threshold']:g}"

    return _saas(ctx, company, run)


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


def _lab_risk(ctx: ActionContext, args: dict[str, Any]) -> tuple[Level, str]:
    # le labo sécu contacte un réseau/une cible -> toujours la validation de l'utilisateur
    if str(args.get("lab", "")).strip().lower() == "secu":
        return (Level.EXTERNAL, "lab_secu")
    return (Level.WRITE, "lab")


def _powershell_risk(ctx: ActionContext, args: dict[str, Any]) -> tuple[Level, str]:
    # lecture seule (cmdlets Get-/Test-... sans effet de bord) -> tout de suite ; le reste
    # peut tout faire sur le PC -> niveau critique, toujours la validation de l'utilisateur
    if powershell.read_only_reason(str(args.get("command", "")), ctx.pwsh_runner) is None:
        return (Level.READ, "read")
    return (Level.CRITICAL, "powershell")


def _powershell(ctx: ActionContext, command: str) -> str:
    if not command.strip():
        raise ActionError("commande vide")
    read_only = powershell.read_only_reason(command, ctx.pwsh_runner) is None
    try:
        return powershell.run(command, read_only=read_only, runner=ctx.pwsh_runner)
    except powershell.PowerShellError as exc:
        raise ActionError(str(exc)) from exc


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
            "competence",
            "Lire une de tes compétences en entier (guide détaillé sur ce PC : personnalité, "
            "amitié, développement humain, mémoire, savoirs, création, labos...), par son nom.",
            Level.READ,
            "read",
            _competence,
        ),
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
            "lab_run",
            "Exécuter une commande dans un labo Docker local (apprentissage/labo), via docker "
            "exec. lab=biometrie : reconnaissance visage/voix/empreintes (scripts "
            "/work/shared/face_demo*.py, voice_demo*.py, fp_match.py) ; lab=media : "
            "FFmpeg/OpenCV/MoviePy ; lab=secu : suite Kali (cibles possédées ou autorisées "
            "uniquement — chaque exécution demande ta validation). Échange de fichiers via le "
            "dossier shared/ du labo.",
            Level.WRITE,
            "lab",
            actions.lab_run,
            _lab_risk,
        ),
        Tool(
            "create_agent",
            "Créer un nouvel agent spécialisé, réutilisable dans les missions. name : le nom "
            "que l'UTILISATEUR lui a donné, mot pour mot (ne l'invente jamais : demande-le "
            "d'abord s'il ne l'a pas dit ; unique) ; engine : le modèle qui le fait tourner, "
            "parmi opus, sonnet, haiku, chatgpt, mistral ; role : sa spécialité en une "
            "phrase ; instructions : ses consignes de travail (facultatif). Le moteur peut "
            "aussi être fournisseur:modèle (list_models montre lesquels sont prêts).",
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
        Tool(
            "powershell",
            "Exécuter une commande PowerShell 7 sur ce PC. Lecture seule (Get-, Test-, "
            "Measure-, Select-, Sort-, Format-... sans écriture) : tout de suite, dans un pwsh "
            "neuf et invisible. Tout le reste (modifier, installer, arrêter, réseau, programmes "
            "externes) demande la validation de l'utilisateur, puis s'exécute dans la console "
            "PowerShell visible sur le PC. Utilise des chemins absolus ; pour lire un fichier, "
            "préfère read_file.",
            Level.CRITICAL,
            "powershell",
            _powershell,
            _powershell_risk,
        ),
        Tool(
            "list_models",
            "Les moteurs (LLM) : celui de chaque rôle, les moteurs de secours, les fournisseurs "
            "prêts (LM Studio, Ollama, OpenRouter, Groq, Gemini...) et leurs modèles.",
            Level.READ,
            "read",
            _list_models,
        ),
        Tool(
            "set_model",
            "Changer le moteur (LLM) d'un rôle, à la demande de l'utilisateur. role : cerveau, "
            "mission, verificateur ou planificateur ; engine : opus, sonnet, haiku, chatgpt, "
            "mistral ou fournisseur:modèle (ex. lmstudio:google/gemma-4-e4b). Le changement "
            "vaut dès le prochain message.",
            Level.WRITE,
            "model",
            _set_model,
        ),
        Tool(
            "set_fallbacks",
            "Définir les moteurs de secours, essayés dans l'ordre quand un moteur échoue ou "
            "atteint sa limite (ex. « lmstudio:google/gemma-4-e4b, haiku ») ; vide = aucun.",
            Level.WRITE,
            "model",
            _set_fallbacks,
        ),
        Tool("list_missions", "État des missions.", Level.READ, "read", _missions),
        Tool(
            "saas_report",
            "Le tableau de bord SaaS d'une entreprise : MRR, ARR, abonnés, churn, ARPA, LTV, "
            "CAC, paiements échoués, encaissé, utilisateurs, inscriptions, disponibilité, CI, "
            "avec leur évolution sur 7 jours, les sources en erreur et les alertes de la semaine.",
            Level.READ,
            "read",
            _saas_report,
        ),
        Tool(
            "set_metric",
            "Enregistrer un chiffre donné par l'utilisateur pour une entreprise (ex. "
            "marketing_spend_30d pour calculer le CAC). metric en minuscules avec _ .",
            Level.WRITE,
            "company",
            _set_metric,
        ),
        Tool(
            "add_monitor",
            "Surveiller la disponibilité d'un site (url) pour une entreprise : vérifié toutes les "
            "5 minutes, alerte après deux échecs d'affilée.",
            Level.WRITE,
            "company",
            _add_monitor,
        ),
        Tool(
            "add_alert",
            "Ajouter une alerte sur un indicateur d'une entreprise : metric (ex. churn_rate, "
            "mrr, latency_ms), op parmi < <= > >= =, threshold, label facultatif.",
            Level.WRITE,
            "company",
            _add_alert,
        ),
        Tool(
            "create_routine",
            "Programmer une routine, à la demande de l'utilisateur. schedule en mots : « tous "
            "les jours à 9h », « chaque lundi à 9h », « en semaine à 8h30 », « toutes les 2 "
            "heures », « dans 30 minutes », « 2026-11-02 à 14h » ou cron « 0 9 * * 1 ». kind : "
            "mission (une mission complète), question (tu réponds avec tes outils et "
            "l'utilisateur reçoit ta réponse) ou rappel (le texte lui revient tel quel). "
            "agent et company facultatifs.",
            Level.WRITE,
            "routine",
            _create_routine,
        ),
        Tool("list_routines", "Les routines programmées.", Level.READ, "read", _list_routines),
        Tool(
            "update_routine",
            "Modifier une routine (numéro ou nom) : enabled oui/non (pause), schedule, prompt.",
            Level.WRITE,
            "routine",
            _update_routine,
        ),
        Tool(
            "delete_routine",
            "Supprimer une routine (numéro ou nom).",
            Level.DESTRUCTIVE,
            "routine",
            _delete_routine,
        ),
        Tool(
            "run_routine",
            "Lancer une routine maintenant, sans attendre son horaire.",
            Level.WRITE,
            "routine",
            _run_routine,
        ),
        Tool(
            "list_webhooks",
            "Les webhooks qui préviennent Spectre (GitHub, Stripe...) et ce qu'ils ont reçu.",
            Level.READ,
            "read",
            _list_webhooks,
        ),
        Tool(
            "ask_agent",
            "Poser une question à un autre agent (créé ou intégré : Gétro, Kyra, Syfer...) sur "
            "son moteur et avec son rôle, et obtenir sa réponse. Il répond sans outils.",
            Level.READ,
            "agent",
            _ask_agent,
        ),
        Tool(
            "steer_mission",
            "Donner une consigne à une mission en cours : elle la lit avant sa prochaine étape "
            "(ex. « concentre-toi sur la France »).",
            Level.WRITE,
            "mission",
            _steer_mission,
        ),
        Tool(
            "stop_mission",
            "Arrêter une mission (en attente : tout de suite ; en cours : après son étape).",
            Level.WRITE,
            "mission",
            _stop_mission,
        ),
        Tool(
            "create_company",
            "Créer une entreprise que Spectre aide à diriger (nom, pitch en une ou deux "
            "phrases). Elle a un organigramme de départements et un tableau de tâches.",
            Level.WRITE,
            "company",
            _create_company,
        ),
        Tool("list_companies", "Les entreprises.", Level.READ, "read", _list_companies),
        Tool(
            "company_board",
            "Organigramme et tableau des tâches d'une entreprise (par nom ou numéro ; vide "
            "s'il n'y en a qu'une).",
            Level.READ,
            "read",
            _company_board,
        ),
        Tool(
            "set_post",
            "Placer un agent sur un poste : department parmi direction, finance, marketing, "
            "ventes, support, produit, juridique, operations ; agent = le nom d'un agent créé "
            "ou intégré (Gétro, Kyra...), un moteur, ou vide pour le réglage par défaut.",
            Level.WRITE,
            "company",
            _set_post,
        ),
        Tool(
            "add_task",
            "Ajouter une tâche au tableau d'une entreprise : titre, département, détail, "
            "priorité (1 urgent, 2 normal, 3 plus tard), depends_on (numéros de tâches à "
            "finir avant, ex. « 3, 5 »), agent (facultatif, sinon celui du poste).",
            Level.WRITE,
            "company",
            _add_task,
        ),
        Tool(
            "plan_company",
            "Faire découper un objectif d'entreprise en tâches par la direction (en arrière-"
            "plan) : elles arrivent au tableau, avec départements et dépendances.",
            Level.WRITE,
            "company",
            _plan_company,
        ),
        Tool(
            "update_task",
            "Changer le statut d'une tâche : todo (à refaire), blocked (bloquée, avec une "
            "note), done (validée), cancelled (annulée, arrête sa mission).",
            Level.WRITE,
            "company",
            _update_task,
        ),
        Tool(
            "start_tasks",
            "Lancer des tâches (une mission chacune, avec le brief de leur poste) : task_ids "
            "(ex. « 3, 4 ») ou, vide, toutes les tâches prêtes de l'entreprise.",
            Level.WRITE,
            "mission",
            _start_tasks,
        ),
        Tool(
            "set_autopilot",
            "Activer ou couper le pilote automatique d'une entreprise : activé, Spectre lance "
            "seul les tâches prêtes, dans la limite des missions en parallèle. Seulement si "
            "l'utilisateur le demande.",
            Level.WRITE,
            "company",
            _set_autopilot,
        ),
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
