"""Spectre's tools: one registry, one execution path, always through the governance gate.

Both the MCP server (called by the brain) and the web UI (approvals) use `execute` /
`run_approved`, so no action can bypass the gate or the audit log.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spectre.assistant import actions, activity, competences, powershell, runctx
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
    lead_only: bool = False  # a skill of Spectre alone, not of the agents it leads
    agents: tuple[str, ...] = ()  # only these agents may use it (empty = anyone)

    def allowed(self, agent: str) -> bool:
        if self.lead_only and agent not in ("", "opus"):
            return False
        return not self.agents or agent in self.agents

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
        "Codex, multimédia, pub et communication), Syfer (mistral, Vibe, cybersécurité), "
        "Octavya (cursor, juridique), "
        "Clarke (antigravity, finances et assurances), Simon (DeepSeek, expert-comptable), "
        "Shelby (animalier), Ysyss (sciences et humain), Lexy (jeux, paris, bourse, crypto) ; "
        "rédaction : Scout, Scribe, Warden"
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


def _recommend_engine(ctx: ActionContext, agent: str = "") -> str:
    from spectre.assistant import local_models
    from spectre.assistant.config import AssistantConfig

    return local_models.recommend(AssistantConfig.load(ctx.root), agent)


def _set_agent_engine(ctx: ActionContext, agent: str, engine: str = "") -> str:
    from spectre.assistant import local_models, team
    from spectre.assistant.config import AGENT_NAMES, AssistantConfig

    key = local_models.resolve_agent(agent)
    wanted = engine.strip()
    if wanted.lower() in ("origine", "d'origine", "defaut", "défaut", "reset"):
        wanted = ""
    providers = Providers(ctx.root)
    if wanted.startswith("lmstudio:"):
        found = local_models.installed()
        if found and wanted.split(":", 1)[1] not in found:
            raise ActionError(
                f"modèle absent de LM Studio : {wanted} (recommend_engine liste ceux installés)"
            )
    config = AssistantConfig.load(ctx.root)
    if not wanted and key in team.ROLE_OF:  # Spectre, Gétro, Kaïto: their Claude model
        wanted = local_models.current(config, key)[1]
    try:
        changes = team.change(ctx.db, config, providers, key, {"engine": wanted})
    except team.TeamError as exc:
        raise ActionError(str(exc)) from exc
    config.update(changes)
    config.save(ctx.root)
    now, original = local_models.current(config, key)
    name = AGENT_NAMES.get(key, key)
    if now == original:
        return f"{name} revient à son moteur d'origine : {original}."
    return f"{name} travaille désormais sur {now} (d'origine : {original})."


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


def _skill(ctx: ActionContext, name: str) -> str:
    from spectre.assistant.learning import Learning, SkillError

    try:
        return Learning(ctx.db, ctx.root).read(name)
    except SkillError as exc:
        raise ActionError(str(exc)) from exc


def _propose_skill(ctx: ActionContext, name: str, description: str, content: str) -> str:
    from spectre.assistant.learning import Learning, SkillError

    try:
        row = Learning(ctx.db, ctx.root).propose(name, description, content, source="conversation")
    except SkillError as exc:
        raise ActionError(str(exc)) from exc
    update = " (mise à jour d'une compétence existante)" if row["previous"] else ""
    return (
        f"compétence « {row['name']} » proposée{update} : elle attend la validation de "
        "l'utilisateur dans la vue Apprentissage"
    )


def _toolkit(ctx: ActionContext, name: str, target: str = "", options: str = "") -> str:
    from spectre.assistant import toolkit

    try:
        return toolkit.run(ctx, name, target, options)
    except ActionError:
        raise
    except (OSError, ValueError) as exc:
        raise ActionError(str(exc)) from exc


def _toolkit_risk(ctx: ActionContext, args: dict[str, Any]) -> tuple[Level, str]:
    from spectre.assistant import agent_tools, toolkit

    name = str(args.get("name", ""))
    kit = toolkit.KITS.get(name)
    if kit:
        return kit.level, kit.category
    card = agent_tools.load(ctx.root, name)
    return agent_tools.risk(card) if card else (Level.READ, "read")


def _agent_tools(ctx: ActionContext) -> str:
    from spectre.assistant import agent_tools

    return agent_tools.listing(ctx)


def _installed_programs(ctx: ActionContext, search: str = "") -> str:
    from spectre.assistant import agent_tools

    return agent_tools.installed(ctx, search)


def _agent_tool_save(
    ctx: ActionContext,
    name: str,
    label: str,
    agents: str,
    program: str,
    args: list[str],
    level: str = "lecture",
    description: str = "",
    timeout: int = 600,
    install: str = "",
) -> str:
    from spectre.assistant import agent_tools

    return agent_tools.save(
        ctx, name, label, agents, program, args, level, description, timeout, install
    )


def _agent_tool_install(ctx: ActionContext, name: str, source: str = "") -> str:
    from spectre.assistant import agent_tools

    return agent_tools.install(ctx, name, source)


def _agent_tool_delete(ctx: ActionContext, name: str) -> str:
    from spectre.assistant import agent_tools

    return agent_tools.delete(ctx, name)


def _trading(ctx: ActionContext, operation: str, values: list[float]) -> str:
    from spectre.assistant import toolkit

    return toolkit.trading(operation, list(values))


def _market(ctx: ActionContext, operation: str, symbol: str, options: str = "") -> str:
    from spectre.assistant import toolkit

    return toolkit.market(operation, symbol, options)


def _nature(ctx: ActionContext, operation: str, subject: str, options: str = "") -> str:
    from spectre.assistant import nature

    return nature.nature(operation, subject, options)


def _administration(ctx: ActionContext, operation: str, subject: str, options: str = "") -> str:
    from spectre.assistant import administration

    return administration.administration(operation, subject, options)


def _contract(ctx: ActionContext, operation: str, target: str, options: str = "") -> str:
    from spectre.assistant import contracts

    try:
        return contracts.contract(ctx, operation, target, options)
    except ActionError:
        raise
    except (OSError, ValueError) as exc:
        raise ActionError(str(exc)) from exc


def _contract_risk(ctx: ActionContext, args: dict[str, Any]) -> tuple[Level, str]:
    if str(args.get("operation", "")).strip().lower() == "comparer":
        return Level.WRITE, "convert"  # writes the HTML comparison next to the contract
    return Level.READ, "read"


def _finance(ctx: ActionContext, operation: str, values: list[float]) -> str:
    from spectre.assistant import toolkit

    return toolkit.finance(operation, list(values))


def _science(ctx: ActionContext, operation: str, expression: str) -> str:
    from spectre.assistant import toolkit

    return toolkit.science(operation, expression)


def _betting(ctx: ActionContext, operation: str, values: list[float]) -> str:
    from spectre.assistant import toolkit

    return toolkit.betting(operation, list(values))


def _studio(ctx: ActionContext) -> Any:
    from spectre.assistant.config import AssistantConfig
    from spectre.assistant.media import Studio

    return Studio(ctx.db, AssistantConfig.load(ctx.root), ctx.root)


def _media(
    ctx: ActionContext, kind: str, prompt: str, width: int, height: int, seconds: float
) -> str:
    from spectre.assistant.media import MediaError

    try:
        job = _studio(ctx).submit(
            kind,
            prompt,
            width=int(width),
            height=int(height),
            seconds=float(seconds),
            agent=ctx.agent,
            mission=ctx.mission,
        )
    except MediaError as exc:
        raise ActionError(str(exc)) from exc
    what = "image" if kind == "image" else "vidéo"
    return (
        f"Création #{job['id']} lancée dans ComfyUI ({what} {job['width']}×{job['height']}). "
        f"Environ {job['minutes']} min sur ce PC sans carte graphique dédiée : le fichier "
        "arrivera dans workspace\\medias et l'utilisateur sera prévenu. Ne l'attends pas."
    )


def _generate_image(ctx: ActionContext, prompt: str, width: int = 1024, height: int = 1024) -> str:
    return _media(ctx, "image", prompt, width, height, 0)


def _generate_video(
    ctx: ActionContext, prompt: str, width: int = 640, height: int = 352, seconds: float = 2.0
) -> str:
    return _media(ctx, "video", prompt, width, height, seconds)


def _media_jobs(ctx: ActionContext) -> str:
    jobs = _studio(ctx).jobs(10)
    if not jobs:
        return "Aucune création pour l'instant."
    return "\n".join(
        f"#{j['id']} {j['kind']} [{j['status']}] {j['prompt'][:80]}"
        + (f" → {', '.join(j['files'])}" if j["files"] else "")
        + (f" ({j['error'][:120]})" if j["error"] else "")
        for j in jobs
    )


def _laya_decide(ctx: ActionContext, state: str, questions: str) -> str:
    from spectre.assistant.config import AssistantConfig
    from spectre.assistant.laya import LayaError, decide, describe

    try:
        return describe(decide(AssistantConfig.load(ctx.root), state, questions))
    except LayaError as exc:
        raise ActionError(str(exc)) from exc


def _search_history(ctx: ActionContext, query: str, limit: int = 10) -> str:
    from spectre.assistant.learning import search_history

    rows = search_history(ctx.db, query, int(limit))
    if not rows:
        return "rien trouvé dans les conversations passées"
    who = {"user": "l'utilisateur", "spectre": "toi", "mission": "mission"}
    return "\n".join(
        f"{r['ts'][:16].replace('T', ' ')} ({who.get(r['source'], r['source'])}) : {r['excerpt']}"
        for r in rows
    )


def _board_call(action: Callable[[], str]) -> str:
    from spectre.assistant.board import BoardError
    from spectre.assistant.experiments import ExperimentError

    try:
        return action()
    except (BoardError, ExperimentError, CompanyError) as exc:
        raise ActionError(str(exc)) from exc


def _convene_board(ctx: ActionContext, company: str, question: str) -> str:
    from spectre.assistant.board import Board

    def run() -> str:
        decision, mid = Board(ctx.db, ctx.root).convene(company, question)
        return (
            f"conseil réuni (décision #{decision['id']}, mission #{mid}) : les départements "
            "donnent leur avis, puis la direction tranche ; je te préviens avec la note"
        )

    return _board_call(run)


def _list_decisions(ctx: ActionContext, company: str = "") -> str:
    from spectre.assistant.board import Board

    def run() -> str:
        rows = Board(ctx.db, ctx.root).all(Companies(ctx.db).get(company)["id"])
        if not rows:
            return "aucune décision"
        return "\n".join(
            f"#{d['id']} [{d['status']}{' : ' + d['outcome'] if d['outcome'] else ''}] "
            f"{d['question']} → {d['decision'][:150] or '(en délibération)'}"
            + (f" — leçon : {d['lesson']}" if d["lesson"] else "")
            for d in rows[:20]
        )

    return _board_call(run)


def _review_decision(ctx: ActionContext, decision_id: int) -> str:
    from spectre.assistant.board import Board

    def run() -> str:
        mission = Board(ctx.db, ctx.root).queue_review(int(decision_id))
        return f"réévaluation lancée (mission #{mission})"

    return _board_call(run)


def _start_experiment(
    ctx: ActionContext,
    company: str,
    hypothesis: str,
    metric: str,
    direction: str = "up",
    min_change: float = 5.0,
    days: int = 14,
) -> str:
    from spectre.assistant.experiments import Experiments, describe

    def run() -> str:
        found = Companies(ctx.db).get(company)
        row = Experiments(ctx.db, ctx.root).start(
            found["id"], hypothesis, metric, direction, float(min_change), int(days)
        )
        return f"expérience #{row['id']} lancée : {describe(row)}"

    return _board_call(run)


def _list_experiments(ctx: ActionContext, company: str = "") -> str:
    from spectre.assistant.experiments import Experiments, describe

    def run() -> str:
        rows = Experiments(ctx.db, ctx.root).all(Companies(ctx.db).get(company)["id"])
        return (
            "\n".join(f"#{r['id']} [{r['status']}] {describe(r)}" for r in rows)
            or "aucune expérience"
        )

    return _board_call(run)


def _stop_experiment(ctx: ActionContext, experiment_id: int) -> str:
    from spectre.assistant.experiments import Experiments

    return _board_call(
        lambda: (
            f"expérience #{Experiments(ctx.db, ctx.root).stop(int(experiment_id))['id']} arrêtée"
        )
    )


def _agent_record(ctx: ActionContext, agent: str = "") -> str:
    from spectre.assistant.trust import Trust

    trust = Trust(ctx.db)
    if agent.strip():
        created = CustomAgents(ctx.db).get(agent)
        key = f"{PREFIX}{created['id']}" if created else resolve_agent(agent)
        if not key:
            raise ActionError(f"agent inconnu « {agent} »")
        rows = [trust.dossier(key)]
    else:
        rows = trust.agents()
    if not rows:
        return "aucun dossier encore : les agents en gagnent un en menant des missions"
    return "\n".join(
        f"{d['name']} : {d['level']}, fiabilité {d['reliability']:g} % sur {d['volume']:g} "
        f"points ({', '.join(f'{k} {n}' for k, n in sorted(d['counts'].items())) or 'rien encore'})"
        for d in rows
    )


def _cost_report(ctx: ActionContext, company: str = "", days: int = 30) -> str:
    from datetime import datetime

    from spectre.assistant import spend

    company_id = None
    if company.strip():
        try:
            company_id = Companies(ctx.db).get(company)["id"]
        except CompanyError as exc:
            raise ActionError(str(exc)) from exc
    return spend.text(ctx.db, datetime.now().astimezone(), company_id, max(1, min(int(days), 365)))


def _meeting(ctx: ActionContext, action: str, company: str = "", title: str = "") -> str:
    from spectre.assistant.meeting import REQUEST_KV

    wanted = action.strip().lower()
    if wanted in ("start", "demarrer", "démarrer", "lancer", "commencer"):
        company_id = ""
        if company.strip():
            try:
                company_id = str(Companies(ctx.db).get(company)["id"])
            except CompanyError as exc:
                raise ActionError(str(exc)) from exc
        ctx.db.set_kv(
            REQUEST_KV, json.dumps({"action": "start", "company": company_id, "title": title})
        )
        return (
            "réunion demandée : j'écoute dans quelques secondes (rappelle aux participants que "
            "tu enregistres ; seul le texte est gardé, rien ne quitte le PC)"
        )
    if wanted in ("stop", "arreter", "arrêter", "terminer", "fin"):
        ctx.db.set_kv(REQUEST_KV, json.dumps({"action": "stop"}))
        return "fin de réunion demandée : le compte rendu suit"
    raise ActionError("action : start ou stop")


def _list_meetings(ctx: ActionContext) -> str:
    from spectre.assistant.meeting import Meetings

    rows = Meetings(ctx.db).all(10)
    if not rows:
        return "aucune réunion"
    return "\n".join(
        f"#{m['id']} {m['title']} [{m['status']}] {round((m['seconds'] or 0) / 60)} min"
        + (f" — {m['summary'][:200]}" if m["summary"] else "")
        for m in rows
    )


def _dev_call(action: Callable[[Any], str]) -> str:
    from spectre.assistant.devteam import DevError

    try:
        return action(None)
    except (DevError, CompanyError) as exc:
        raise ActionError(str(exc)) from exc


def _set_dev_repo(
    ctx: ActionContext, company: str, path: str, test_command: str, base_branch: str = ""
) -> str:
    from spectre.assistant.devteam import DevTeam

    def run(_: Any) -> str:
        found = Companies(ctx.db).get(company)
        repo = actions.resolve_path(ctx, path)
        setup = DevTeam(ctx.db, ctx.root).configure(
            found["id"], str(repo), test_command, base_branch
        )
        return (
            f"dépôt de {found['name']} : {setup['repo_path']} (branche {setup['base_branch']}, "
            f"tests : {setup['test_command']})"
        )

    return _dev_call(run)


def _dev_task(ctx: ActionContext, company: str, request: str) -> str:
    from spectre.assistant.devteam import DevTeam

    def run(_: Any) -> str:
        found = Companies(ctx.db).get(company)
        job, mid = DevTeam(ctx.db, ctx.root).request(found["id"], request)
        return (
            f"travail #{job['id']} confié au département technique (mission #{mid}) : branche "
            "isolée, tests, puis je te propose la PR"
        )

    return _dev_call(run)


def _list_dev_jobs(ctx: ActionContext, company: str = "") -> str:
    from spectre.assistant.devteam import DevTeam

    def run(_: Any) -> str:
        rows = DevTeam(ctx.db, ctx.root).jobs(Companies(ctx.db).get(company)["id"])
        return (
            "\n".join(
                f"#{j['id']} [{j['status']}] {j['request'][:120]}"
                + (f" — {j['branch']}" if j["branch"] else "")
                + (f" — {j['pr_url']}" if j["pr_url"] else "")
                for j in rows
            )
            or "aucun travail de développement"
        )

    return _dev_call(run)


def _open_pr(ctx: ActionContext, job_id: int) -> str:
    from spectre.assistant.devteam import DevTeam

    return _dev_call(lambda _: DevTeam(ctx.db, ctx.root).open_pr(int(job_id)))


def _discard_dev_job(ctx: ActionContext, job_id: int) -> str:
    from spectre.assistant.devteam import DevTeam

    return _dev_call(lambda _: DevTeam(ctx.db, ctx.root).discard(int(job_id)))


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
            "images, vidéos, le multimédia, la publicité et la communication ; Syfer "
            "(mistral) pour la cybersécurité et les tests "
            "d'intrusion autorisés ; Octavya (cursor) pour le juridique ; Clarke (antigravity) "
            "pour les finances et les assurances ; Simon (simon, sur DeepSeek) pour la "
            "comptabilité, la TVA et la fiscalité ; Gétro (sonnet) ou Kaïto (haiku, rapide) "
            "pour le reste ; "
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
            "recommend_engine",
            "Conseiller le meilleur modèle local LM Studio pour un agent selon son métier "
            "(outils, vision, code, raisonnement, contexte) et la mémoire de ce PC. agent : "
            "son nom (Kyra, Octavya, Gétro…) ; vide = le meilleur pour chaque agent. Ne change "
            "rien.",
            Level.READ,
            "read",
            _recommend_engine,
        ),
        Tool(
            "set_agent_engine",
            "Changer le moteur (LLM) d'un agent, UNIQUEMENT quand l'utilisateur le demande. "
            "agent : son nom (Kyra, Octavya, Gétro…) ; engine : lmstudio:<modèle> (ou un "
            "autre fournisseur:modèle, ou opus/sonnet/haiku pour Spectre, Gétro et Kaïto) ; "
            "vide ou « origine » = son moteur d'origine.",
            Level.WRITE,
            "model",
            _set_agent_engine,
            lead_only=True,  # an agent never moves itself or a colleague
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
            "set_dev_repo",
            "Configurer le dépôt de code d'une entreprise pour le département technique : path "
            "(un dépôt git sur ce PC), test_command (ce qui lance les tests), base_branch "
            "(facultatif). Demande la validation de l'utilisateur.",
            Level.CRITICAL,
            "dev_config",
            _set_dev_repo,
        ),
        Tool(
            "dev_task",
            "Confier un changement de code au département technique d'une entreprise : il "
            "travaille dans une branche isolée, lance les tests, et la PR n'est ouverte "
            "qu'avec l'accord de l'utilisateur.",
            Level.WRITE,
            "mission",
            _dev_task,
        ),
        Tool(
            "list_dev_jobs",
            "Les travaux du département technique d'une entreprise.",
            Level.READ,
            "read",
            _list_dev_jobs,
        ),
        Tool(
            "open_pr",
            "Pousser la branche d'un travail et ouvrir sa PR sur GitHub (validation requise).",
            Level.EXTERNAL,
            "external_send",
            _open_pr,
        ),
        Tool(
            "discard_dev_job",
            "Abandonner un travail : supprime sa branche et sa copie isolée.",
            Level.DESTRUCTIVE,
            "delete_file",
            _discard_dev_job,
        ),
        Tool(
            "meeting",
            "Mode réunion, quand l'utilisateur le demande : action=start (écouter avec le micro "
            "du PC et transcrire en local ; company et title facultatifs) ou stop (arrêter : le "
            "compte rendu suit, ses tâches vont au tableau et ses décisions au journal).",
            Level.WRITE,
            "meeting",
            _meeting,
        ),
        Tool(
            "list_meetings",
            "Les dernières réunions et leurs résumés.",
            Level.READ,
            "read",
            _list_meetings,
        ),
        Tool(
            "agent_record",
            "Le dossier de fiabilité d'un agent (ou de tous) : niveau (apprenti, confirmé, "
            "expert), fiabilité, étapes vérifiées ou ratées, tâches validées ou à refaire, "
            "actions refusées, missions annulées.",
            Level.READ,
            "read",
            _agent_record,
        ),
        Tool(
            "cost_report",
            "Ce que coûte l'IA sur une période (30 jours par défaut), au total ou pour une "
            "entreprise : appels, coût équivalent API, temps, jetons, par rôle, agent et "
            "département, et rapporté au MRR.",
            Level.READ,
            "read",
            _cost_report,
        ),
        Tool(
            "convene_board",
            "Réunir le conseil d'administration d'une entreprise sur une décision importante "
            "(prix, lancement, recrutement, pivot...) : les départements concernés donnent leur "
            "avis, la direction tranche, une note de décision est écrite et la décision sera "
            "réévaluée avec les vrais chiffres.",
            Level.WRITE,
            "company",
            _convene_board,
        ),
        Tool(
            "list_decisions",
            "Le journal des décisions d'une entreprise : décidé, résultat, leçon.",
            Level.READ,
            "read",
            _list_decisions,
        ),
        Tool(
            "review_decision",
            "Réévaluer une décision maintenant, avec les chiffres depuis qu'elle a été prise.",
            Level.WRITE,
            "company",
            _review_decision,
        ),
        Tool(
            "start_experiment",
            "Lancer une expérience mesurée : hypothesis (ce qu'on change et ce qu'on attend), "
            "metric (un indicateur suivi, ex. mrr, churn_rate, signups_7d), direction up ou "
            "down, min_change (variation minimale en %), days (durée). Verdict automatique.",
            Level.WRITE,
            "company",
            _start_experiment,
        ),
        Tool(
            "list_experiments",
            "Les expériences d'une entreprise et leurs verdicts.",
            Level.READ,
            "read",
            _list_experiments,
        ),
        Tool(
            "stop_experiment",
            "Arrêter une expérience en cours.",
            Level.WRITE,
            "company",
            _stop_experiment,
        ),
        Tool(
            "skill",
            "Lire une compétence apprise en entier (son guide), par son nom.",
            Level.READ,
            "read",
            _skill,
        ),
        Tool(
            "propose_skill",
            "Proposer une compétence apprise : name (minuscules et tirets), description (quand "
            "l'utiliser, une phrase), content (le guide en Markdown : étapes, vérifications, "
            "pièges). Elle n'est enregistrée qu'après la validation de l'utilisateur ; même nom "
            "= mise à jour. Jamais de donnée personnelle ni de secret dedans.",
            Level.WRITE,
            "skill",
            _propose_skill,
        ),
        Tool(
            "toolkit",
            "Outils libres installés sur ce PC, chacun pour son métier. name : gitleaks (fuite "
            "de secrets), trivy (vulnérabilités), semgrep (analyse de code), trufflehog "
            "(secrets dans un dossier) ; sécu réseau/web sur cible AUTORISÉE, demande ta "
            "validation : nuclei (scan de vulnérabilités d'une adresse), nmap (ports et "
            "services), subfinder (sous-domaines d'un domaine), httpx (sonde HTTP). vale et "
            "languagetool (style et "
            "grammaire d'un texte ; options = langue, fr par défaut), pandoc (conversion : "
            "options = fichier de sortie), ocr (texte d'une image ; options = langue). Pub et "
            "multimédia (Kyra) : video_info (infos d'une vidéo), video_format et image_format "
            "(recadrage pour un réseau ; options = story, fil, carre ou paysage), sous_titres "
            "(fichier .srt ; options = langue), incruster (sous-titres gravés ; options = le "
            ".srt, sinon celui de même nom), detourage (fond transparent), voix_off (voix "
            "française d'un fichier .txt ; options = vitesse), agrandir (image ×4). Production "
            "(Kyra) : scenario_pdf (scénario .fountain en PDF), plans (liste des plans d'une "
            "vidéo), derushage (retire les silences d'un rush), loudness (son de diffusion ; "
            "options = web ou tv). Ils créent "
            "un nouveau fichier à côté de la source. target : le fichier, le dossier ou "
            "l'adresse. Chaque agent ne voit que les outils de son domaine. Aussi les outils "
            "ajoutés par Spectre (liste : outils_agents).",
            Level.READ,
            "scan",
            _toolkit,
            _toolkit_risk,
        ),
        Tool(
            "outils_agents",
            "Lister les outils que Spectre a ajoutés à ses agents (fiches d'outils) : ceux de "
            "ton domaine, à lancer avec toolkit (name = le nom de l'outil).",
            Level.READ,
            "read",
            _agent_tools,
        ),
        Tool(
            "installed_programs",
            "Recenser les logiciels installés sur ce PC (dossiers Apps, uv tools, Program "
            "Files, winget list), pour choisir ceux à donner aux agents. search : un mot pour "
            "filtrer (vide = tout). Ne change rien.",
            Level.READ,
            "read",
            _installed_programs,
            lead_only=True,
        ),
        Tool(
            "agent_tool_save",
            "Donner un outil à des agents (ou mettre à jour sa fiche) : un programme en ligne "
            "de commande, installé ou à installer. name : nom court (minuscules) ; label : "
            "son titre ; agents : leurs noms séparés par des virgules (Kyra, Syfer…) ou "
            "« tous » ; program : le nom du programme (ex. exiftool) ou le chemin complet de "
            "son .exe — jamais un shell, un interpréteur ou un installeur ; args : la liste "
            "des arguments, avec {cible} (le fichier ou l'adresse, remplacé à l'appel) et "
            "{options} (les options libres de l'agent, sans chemin) ; level : lecture (lit et "
            "répond), ecriture (crée un fichier dans l'espace de travail) ou distant (la cible "
            "est une adresse : chaque appel demande validation) ; description : quand s'en "
            "servir ; install : winget:<Id> ou uv:<paquet> s'il faut l'installer. Tu ne "
            "modifies jamais le code de Spectre : seulement ces fiches. Demande validation.",
            Level.WRITE,
            "agent_tool",
            _agent_tool_save,
            lead_only=True,
        ),
        Tool(
            "agent_tool_install",
            "Installer le programme d'une fiche d'outil (winget ou uv tool) sur ce PC. name : "
            "la fiche ; source : winget:<Id> ou uv:<paquet> (vide = celle de la fiche). "
            "Toujours avec la validation de l'utilisateur.",
            Level.CRITICAL,
            "install_agent_tool",
            _agent_tool_install,
            lead_only=True,
        ),
        Tool(
            "agent_tool_delete",
            "Retirer un outil ajouté aux agents (supprime sa fiche ; le programme reste "
            "installé). name : la fiche.",
            Level.DESTRUCTIVE,
            "agent_tool",
            _agent_tool_delete,
            lead_only=True,
        ),
        Tool(
            "finance",
            "Calcul financier (Clarke, Simon). operation : mensualite (taux, périodes, "
            "capital), van (taux puis flux), tri (flux, le premier négatif), valeur_future "
            "(taux, périodes, versement, valeur présente). values : la liste des nombres. Les "
            "taux sont par période (mensuel ou annuel selon les périodes).",
            Level.READ,
            "read",
            _finance,
            agents=("antigravity", "simon"),
        ),
        Tool(
            "science",
            "Calcul scientifique symbolique (Ysyss). operation : calculer (évaluer), simplifier, "
            "resoudre (équation en x), deriver, integrer. expression : la formule, x comme "
            "variable (ex. x**2 - 4, sin(x), sqrt(2)*pi).",
            Level.READ,
            "read",
            _science,
            agents=("ysyss",),
        ),
        Tool(
            "paris",
            "Maths des paris et probabilités (Lexy). operation : probabilite (cote décimale → "
            "probabilité implicite), kelly (cote puis ta probabilité estimée → mise optimale), "
            "arbitrage (les cotes des issues → garantie de gain ?). values : les nombres. "
            "Jamais un pronostic ni une promesse de gain.",
            Level.READ,
            "read",
            _betting,
            agents=("lexy",),
        ),
        Tool(
            "trading",
            "Calculs de trading (Simon, Lexy). operation : taille_position (capital, risque en % "
            "du capital, entrée, stop), esperance (taux de réussite, gain moyen, perte moyenne), "
            "gain_risque (entrée, stop, objectif), drawdown (la suite des valeurs du capital). "
            "values : les nombres. Un calcul, jamais un conseil ni un signal.",
            Level.READ,
            "read",
            _trading,
            agents=("simon", "lexy"),
        ),
        Tool(
            "marche",
            "Données de marché en lecture seule (Simon, Lexy). operation : prix (dernier prix ; "
            "crypto en temps réel « BTC/EUR », action, indice ou forex « AAPL », « ^FCHI », "
            "« EURUSD=X » parfois avec 15 min de retard), analyse (performance, volatilité, "
            "drawdown, moyennes mobiles, RSI, ATR ; options = 1mo, 3mo, 6mo, 1y, 2y, 5y), carnet "
            "(carnet d'ordres d'une crypto). symbol : le symbole. Cite toujours l'heure et la "
            "source ; jamais un signal d'achat ou de vente.",
            Level.READ,
            "read",
            _market,
            agents=("simon", "lexy"),
        ),
        Tool(
            "nature",
            "Données ouvertes sur la nature et le climat (Shelby, Ysyss). operation : espece "
            "(classification, noms français, statut UICN, observations), observations (par "
            "année sur 10 ans ; options = code pays, FR par défaut), marin (vie marine, OBIS), "
            "meteo (météo actuelle et mer d'un point), climat (écart des 30 derniers jours à "
            "la normale 1991-2020). subject : l'espèce (nom latin de préférence) ou le point "
            "« lat,lon ». Cite toujours la source et la date.",
            Level.READ,
            "read",
            _nature,
            agents=("shelby", "ysyss"),
        ),
        Tool(
            "contrat",
            "Outils de contrat (Octavya). operation : analyser (repère les clauses présentes "
            "et absentes, dates, montants, délais et signaux d'alerte d'un contrat .docx, .txt "
            "ou .md — une première lecture, pas un avis juridique), comparer (compare deux "
            "versions et écrit un comparatif HTML à côté ; options = la seconde version). "
            "target : le fichier du contrat.",
            Level.READ,
            "read",
            _contract,
            _contract_risk,
            agents=("cursor",),
        ),
        Tool(
            "administration",
            "Boîte à outils administrative (Spectre seul). operation : annuaire (guichets "
            "publics compétents pour une commune — mairie, caf, cpam, prefecture, impots, "
            "france_travail, tribunal, urssaf… ; options = type, vide = liste des types), "
            "entreprise (fiche Sirene par SIREN, SIRET ou nom), commune (INSEE, département, "
            "intercommunalité), adresse (normaliser une adresse française), tva (numéro de TVA "
            "UE dans VIES), identifiant (IBAN, SIREN, SIRET, numéros étrangers ; options = type "
            "stdnum, ex. fr.siret, de.vat), delai (subject = date de départ, options « 2 mois », "
            "« 15 jours ouvrés », « 10 jours francs », + pays FR-57…), feries (subject = pays "
            "ou région, options = année). Cite la source et la date.",
            Level.READ,
            "read",
            _administration,
            lead_only=True,
        ),
        Tool(
            "generate_image",
            "Créer une image sur ce PC avec ComfyUI (Z-Image Turbo, rendu réaliste). Décris la "
            "scène précisément, en anglais de préférence : sujet, cadrage, lumière, style. "
            "width/height de 256 à 1536 (1024 par défaut). Long sur ce PC (environ 30 min) : la "
            "demande part en file et l'utilisateur est prévenu quand l'image est prête.",
            Level.WRITE,
            "media",
            _generate_image,
            agents=("chatgpt",),
        ),
        Tool(
            "generate_video",
            "Créer une courte vidéo sur ce PC avec ComfyUI (Wan 2.2). Décris le mouvement, le "
            "cadrage et l'ambiance. seconds de 1 à 5 ; 640×352 par défaut. Très long sur ce PC "
            "(plusieurs heures) : préviens l'utilisateur ; il est averti à la fin.",
            Level.WRITE,
            "media",
            _generate_video,
            agents=("chatgpt",),
        ),
        Tool(
            "media_jobs",
            "Les dernières créations d'images et de vidéos (en cours, prêtes, échouées) et leurs "
            "fichiers.",
            Level.READ,
            "read",
            _media_jobs,
        ),
        Tool(
            "laya_decide",
            "Ton intuition (Laya, modèle de décision local, sans jetons ni texte généré) : juge "
            "vite un état (message, mission, ticket, JSON) en répondant à des questions typées. "
            'questions = JSON {"nom": {"type": "choice", "instructions": "...", "criteria": '
            '{"option": "description", ...}}, "nom2": {"type": "score", "instructions": "...", '
            '"criteria": ["bas", "moyen", "haut"]}, "nom3": {"type": "noul", "instructions": '
            '"affirmation à vérifier"}}. '
            "Pour choisir l'agent d'une mission, trier un message, "
            "noter une urgence ou repérer un risque avant d'y réfléchir en détail. Réservé à toi.",
            Level.READ,
            "read",
            _laya_decide,
            lead_only=True,
        ),
        Tool(
            "search_history",
            "Chercher dans les conversations passées (et les missions) par mots-clés ; rend "
            "des extraits datés.",
            Level.READ,
            "read",
            _search_history,
        ),
        Tool(
            "rollback_mission",
            "Ramener les fichiers d'une mission à leur état d'avant (annule ses écritures, "
            "déplacements et suppressions) ; demande la validation de l'utilisateur.",
            Level.DESTRUCTIVE,
            "overwrite_file",
            actions.rollback_mission,
        ),
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
    if not tool.allowed(ctx.agent or str(runctx.current().get("agent", ""))):
        owner = (
            "de Spectre seul"
            if tool.lead_only
            else "réservée à " + ", ".join(agent_name(a) for a in tool.agents)
        )
        return f"REFUSÉ : {name} est une compétence {owner}"
    level, category = tool.risk(ctx, args)
    from spectre.assistant.trust import Trust

    trust = Trust(ctx.db).level(ctx.agent) if ctx.agent else ""
    decision = gate.decide(level, category, trust)
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
        if ctx.agent:  # whose request it was: the answer goes to its record
            ctx.db.execute(
                "INSERT OR REPLACE INTO approval_agents(approval_id, agent) VALUES(?, ?)",
                (approval_id, ctx.agent),
            )
        gate.record(name, args, level, category, "approval", f"demande #{approval_id}")
        context = runctx.current()
        activity.record(  # the agent now waits for the user, on the video call too
            ctx.db,
            "approval",
            agent=ctx.agent or str(context.get("agent", "")),
            mission=ctx.mission if ctx.mission is not None else context.get("mission"),
            title=name,
            detail=json.dumps(
                {"id": approval_id, "reason": decision.reason, "target": activity.target(args)},
                ensure_ascii=False,
            ),
            status="pending",
        )
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
    context = runctx.current()
    agent = ctx.agent or str(context.get("agent", ""))
    mission = ctx.mission if ctx.mission is not None else context.get("mission")
    started = time.perf_counter()
    row = activity.tool_started(ctx.db, agent, mission, tool.name, args)
    try:
        result = tool.run(ctx, **args)
    except ActionError as exc:
        result = f"ÉCHEC : {exc}"
    except (TypeError, KeyError) as exc:
        result = f"ÉCHEC : paramètres invalides ({exc})"
    except OSError as exc:
        result = f"ÉCHEC : {exc}"
    except Exception as exc:
        activity.tool_finished(ctx.db, row, tool.name, args, f"ÉCHEC : {exc}", started)
        raise
    activity.tool_finished(ctx.db, row, tool.name, args, result, started)
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
    _answered(ctx, approval_id, "approval_granted")
    return result


def _answered(ctx: ActionContext, approval_id: int, kind: str) -> None:
    from spectre.assistant.trust import Trust

    row = ctx.db.one("SELECT agent FROM approval_agents WHERE approval_id = ?", (approval_id,))
    if row is not None:
        Trust(ctx.db).record(row["agent"], kind)


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
    _answered(ctx, approval_id, "approval_denied")
