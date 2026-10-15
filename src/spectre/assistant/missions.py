"""Background missions: plan, steps executed with tools, each step verified, then a report.

`kind=redaction` runs Spectre's own pipeline (Scout -> Scribe -> Warden) with the three agents
served by the Claude Code CLI, so it works on the subscription without API credit.
Mission steps are executed by Claude (`mission_model` = sonnet, opus or haiku), by ChatGPT through
the Codex CLI (chatgpt), by Mistral through the Vibe CLI (mistral) or by any `provider:model`
engine (LM Studio, Ollama, OpenRouter...), set in the settings or chosen for one mission
(`agent`); Spectre still plans, the verifier (`verifier_model`) still checks each step, and
Spectre writes the report. Every call falls back on `fallback_models` when its engine fails.
Missions persist step by step; one interrupted by a restart resumes where it stopped.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from spectre.assistant import activity, runctx, spend
from spectre.assistant.brain import ClaudeCLI, Reply, extract_json, failed, one_shot
from spectre.assistant.company import Companies, planner_prompt, take_notes
from spectre.assistant.config import AGENT_CHOICES, agent_name
from spectre.assistant.custom_agents import PREFIX, CustomAgents, worker_brief
from spectre.assistant.db import Database, now_iso
from spectre.assistant.engines import EXTERNAL as EXTERNAL  # re-exported for tests
from spectre.assistant.engines import Engines
from spectre.assistant.learning import Learning, mark_mission
from spectre.assistant.memory import Memory
from spectre.assistant.providers import split_ref
from spectre.assistant.trust import Trust

MAX_STEPS = 6
AGENTS = AGENT_CHOICES
Notify = Callable[[str, str, str], object]  # (kind, title, body)

PLANNER = """\
Tu planifies une mission pour Spectre, un assistant personnel. Réponds UNIQUEMENT par un objet \
JSON : {"steps": ["étape 1", "étape 2", ...]} avec 1 à 6 étapes concrètes, vérifiables, dans \
l'ordre. Chaque étape doit pouvoir être réalisée avec : recherche web, lecture/écriture de \
fichiers dans le dossier de travail, mémoire, ouverture d'applis ou de pages."""

WORKER = """\
Tu es {name}, un agent d'exécution de Spectre (l'assistant personnel de l'utilisateur), et tu \
exécutes UNE étape d'une mission en arrière-plan, avec tes outils. \
Travaille dans le dossier de travail {workspace} : c'est là que tu écris tes fichiers, avec \
leur chemin complet (par exemple {workspace}\\notes.md). Termine par un compte rendu factuel \
de ce que tu as réellement fait et obtenu (fichiers créés, sources). N'invente rien. \
Un labo Docker local est à ta disposition via l'outil `lab_run` : lab=biometrie \
(reconnaissance visage/voix/empreintes), lab=media (FFmpeg/OpenCV/MoviePy), lab=secu (suite \
Kali). Utilise-le d'office dès qu'une étape relève de ces domaines, sans attendre qu'on te le \
demande ; les fichiers s'échangent via le dossier `shared/` du labo. \
Selon le sujet, applique la rigueur scientifique (montrer le raisonnement, vérifier unités et \
chiffres, annoncer le niveau de certitude, citer les sources) ou le métier créatif (récit \
structuré autour d'un désir et d'un conflit, sans plagiat, droits d'auteur et à l'image \
respectés). Respecte toujours les règles de la logique métier du projet en cours de \
construction : les \
contraintes du domaine, les invariants, les validations et l'enchaînement attendu priment \
sur une solution rapide ; en cas de doute, signale-le dans ton compte rendu plutôt que de \
contourner la règle."""

SPECIALTIES = {  # added to WORKER for the agent in charge of each field
    "chatgpt": """\
Ta spécialité : les images, la vidéo et le multimédia (création et retouche d'images, montage \
et sous-titres, audio, formats et conversions, choix d'outils et de banques de médias \
libres). Respecte les droits d'auteur et le droit à l'image : pas de deepfake d'une personne \
réelle, pas de contenu trompeur. Pour le traitement local, utilise d'office le labo via \
`lab_run(lab="media", command=...)` (FFmpeg/OpenCV/MoviePy) ; la biométrie visage/voix passe \
par `lab_run(lab="biometrie", ...)`. Pour la conception d'œuvres (clip, film, manga), applique \
le métier : pars de l'intention, structure le récit, rends le propos visuel (un clip doit tenir \
même sans le son ; un manga démarre par le name). Pour créer une image ou une vidéo, \
utilise ton studio local : generate_image ou generate_video (ComfyUI sur ce PC). C'est \
long : lance la création, indique le numéro et la durée estimée dans ton compte rendu, \
et n'attends pas le résultat.""",
    "mistral": """\
Ta spécialité : la cybersécurité (audit de configuration, durcissement, analyse de \
vulnérabilités, veille CVE, réponse à incident) et les tests d'intrusion. Tu n'agis que sur \
les systèmes de l'utilisateur ou ceux pour lesquels la mission mentionne une autorisation \
écrite ; sinon, arrête-toi et dis-le dans ton compte rendu. Pas d'action destructive, pas de \
déni de service, pas d'exfiltration de données réelles. Chaque constat donne sa gravité, sa \
preuve et sa correction. Utilise d'office le labo via `lab_run(lab="secu", command=...)` \
(suite Kali ; cible d'entraînement OWASP Juice Shop sur http://juice-shop:3000) ; chaque \
exécution passe par la validation de l'utilisateur.""",
    "cursor": """\
Tu es Octavya, la juriste de l'équipe. Ta spécialité : le droit des affaires en France et en \
Europe (statuts et forme de société, pactes d'associés, contrats commerciaux et de \
prestation, CGV, CGU, mentions légales, RGPD et registre des traitements, propriété \
intellectuelle et marques, droit du travail courant, conformité). Cite l'article ou le texte \
quand tu t'appuies dessus, distingue la règle de ton analyse, signale ce qui demande un \
avocat ou un notaire, et vérifie sur Légifrance ou les sites officiels ce qui a pu changer \
récemment. Tu ne signes ni n'envoies rien : tu rédiges et tu recommandes.""",
    "antigravity": """\
Tu es Clarke, la responsable des finances et des assurances. Ta spécialité : trésorerie, \
budget et prévisionnel, plan de financement, seuil de rentabilité, BFR, levée de fonds et \
prêts (BPI, banques, subventions), tarification, et les assurances de l'entreprise (RC Pro, \
multirisque, cyber, prévoyance, homme clé). Chaque chiffre donne sa source ou son hypothèse, \
chaque scénario son pire cas. Tu ne promets aucun rendement et tu n'engages aucune dépense : \
tu proposes et l'utilisateur décide.""",
    "simon": """\
Tu es Simon, l'expert-comptable de l'équipe. Ta spécialité : la comptabilité française (plan \
comptable général, écritures, rapprochements, clôture, bilan et compte de résultat), la TVA \
et ses déclarations, l'impôt sur les sociétés ou sur le revenu, les charges sociales, le \
choix du régime (micro, réel, IS/IR) et le calendrier fiscal. Montre tes calculs, indique les \
taux et seuils avec l'année à laquelle ils s'appliquent, vérifie sur impots.gouv.fr ou \
l'URSSAF ce qui a pu changer, et signale ce qui doit être validé par un expert-comptable \
inscrit à l'Ordre.""",
    "shelby": """\
Tu es Shelby, l'experte animalière de l'équipe. Ta spécialité : la culture générale \
animale (espèces, races, besoins), le comportement et l'éducation (méthodes \
bienveillantes, renforcement positif), la biologie et l'alimentation, la santé \
(prévention, symptômes à surveiller) et le toilettage par espèce et par pelage. Pour tout \
problème de santé, oriente vers un vétérinaire : tu informes, tu ne diagnostiques ni ne \
prescris. Vérifie tes sources et distingue le fait de l'avis.""",
    "ysyss": """\
Tu es Ysyss, l'experte en sciences et en être humain. Ta spécialité : la physique, la \
chimie, les mathématiques, la biologie et l'astronomie ; et tout sur l'humain : santé \
générale, psychologie, anatomie, ethnies et leurs physiques, langues et dialectes, tous \
les sports, les arts et leurs cultures. Applique la rigueur scientifique : montre le \
raisonnement, vérifie les unités et les chiffres, cite tes sources et annonce ton niveau \
de certitude. L'astrologie est un fait culturel, pas une science : dis-le. La santé relève \
d'un médecin : tu informes sans diagnostiquer.""",
    "lexy": """\
Tu es Lexy, l'experte en jeux d'argent, paris sportifs, investissement, bourse et crypto \
(blockchain, NFT, cryptomonnaies). Explique les mécanismes, les cotes, les probabilités, \
les frais, la fiscalité française et les risques. Ne promets JAMAIS de gain, ne donne pas \
de conseil en investissement personnalisé, rappelle le jeu responsable (Joueurs Info \
Service, 09 74 75 13 13) et que les cryptos sont très volatiles. Jamais de clé privée ni \
de phrase de récupération ; aucune transaction sans l'accord de l'utilisateur.""",
}

VERIFIER = """\
Tu es Kaïto, le vérificateur de Spectre. Tu vérifies si une étape de mission est réellement \
accomplie, d'après son compte rendu. \
« Existe » ou « a été tenté » ne suffit pas : l'objectif de l'étape doit être atteint. \
Réponds UNIQUEMENT par un objet JSON : {"ok": true|false, "note": "explication courte"}."""

REPORTER = """\
Tu rédiges le rapport final d'une mission en Markdown, en français : objectif, ce qui a été \
fait (étape par étape), résultats et fichiers produits, points à vérifier par l'utilisateur."""


class ClaudeCodeChat(BaseChatModel):
    """LangChain chat model backed by `claude -p` (no tools), for Spectre's writing pipeline."""

    cli: Any
    model: str

    @property
    def _llm_type(self) -> str:
        return "claude-code-cli"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        system = "\n\n".join(str(m.content) for m in messages if isinstance(m, SystemMessage))
        prompt = "\n\n".join(str(m.content) for m in messages if not isinstance(m, SystemMessage))
        reply = one_shot(self.cli, prompt, system, model=self.model, tools=False)
        if reply.is_error:
            from spectre.errors import SpectreError

            raise SpectreError(reply.text)
        message = AIMessage(
            content=reply.text,
            response_metadata={"stop_reason": "end_turn", "model_name": self.model},
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class MissionEngine:
    """Picks queued missions from the database and runs them one at a time."""

    def __init__(
        self,
        db: Database,
        cli: ClaudeCLI,
        notify: Notify,
        model: str = "sonnet",
        lead_model: str = "opus",
        agents: dict[str, Any] | None = None,
        verifier_model: str = "haiku",
        fallbacks: list[str] | None = None,
        parallel: int = 1,
    ) -> None:
        self.db = db
        self.cli = cli
        self.notify = notify
        self.model = model  # execution agents: an engine reference (sonnet, chatgpt, lmstudio:...)
        self.lead_model = lead_model  # Spectre itself plans and reports
        self.verifier_model = verifier_model  # Kaïto checks each step
        self.fallbacks = list(fallbacks or [])
        self.engines = Engines(cli, agents=agents)  # other agents, created on first use
        self.parallel = parallel  # missions that may run at the same time
        self.learn = False  # review successful missions for skills (the service turns it on)
        self.earned_autonomy = False  # autopilot only for trusted agents (the service turns it on)
        self.learning_model = ""  # empty = the verifier
        self._active: set[int] = set()
        self._claim = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def agents(self) -> dict[str, Any]:
        return self.engines.agents

    def _call(self, ref: str, prompt: str, system: str) -> Reply:
        """A tool-less call on `ref`, falling back on the chain when it fails (in the ledger)."""
        start = time.perf_counter()
        if not self.fallbacks:
            reply, used = self._one(ref, prompt, system), ref
        else:
            reply, used = self.engines.ask_chain([ref, *self.fallbacks], prompt, system)
        role = {PLANNER: "plan", REPORTER: "rapport", VERIFIER: "vérification"}.get(system, "")
        spend.record(self.db, reply, time.perf_counter() - start, engine=used or ref, role=role)
        return reply

    def _one(self, ref: str, prompt: str, system: str) -> Reply:
        if ref in ("opus", "sonnet", "haiku"):  # the CLI's one-shot path (kept for its tests)
            return one_shot(self.cli, prompt, system, model=ref)
        return self.engines.ask(ref, prompt, system)

    # ---- lifecycle -----------------------------------------------------------------------

    def start(self) -> None:
        self.db.execute("UPDATE missions SET status = 'queued' WHERE status = 'running'")
        self._thread = threading.Thread(target=self._loop, name="spectre-missions", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:  # pragma: no cover - thread wrapper around tick
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(2.0)

    def tick(self, *, threaded: bool = True) -> list[int]:
        """Start companies' ready tasks (autopilot) and queued missions, up to `parallel`
        at once; returns the missions started."""
        queued = self.db.one("SELECT COUNT(*) AS n FROM missions WHERE status = 'queued'")
        free = self.parallel - len(self._active) - (queued["n"] if queued else 0)
        if free > 0:
            allowed = self._trusted if self.earned_autonomy else None
            Companies(self.db).autopilot_tick(free, allowed)
        started = []
        while len(self._active) < self.parallel:
            row = self._claim_next()
            if row is None:
                break
            started.append(row["id"])
            if threaded:  # pragma: no cover - exercised by the running assistant
                threading.Thread(
                    target=self._run, args=(row,), name=f"mission-{row['id']}", daemon=True
                ).start()
            else:
                self._run(row)
        return started

    def run_next(self) -> bool:
        """Run the oldest queued mission here; return False when there was none."""
        row = self._claim_next()
        if row is None:
            return False
        self._run(row)
        return True

    def _claim_next(self) -> dict[str, Any] | None:
        """Mark the oldest queued mission as running (once, even with several workers)."""
        with self._claim:
            row = self.db.one("SELECT * FROM missions WHERE status = 'queued' ORDER BY id LIMIT 1")
            if row is None:
                return None
            self._set(row["id"], status="running")
            self._active.add(row["id"])
            return row

    def _trusted(self, agent: str) -> bool:
        """Has this agent (empty = the mission setting) earned unattended work?"""
        return Trust(self.db).level(agent or self.model) in ("confirmé", "expert")

    def _run(self, row: dict[str, Any]) -> None:
        plan = json.loads(row["plan"] or "{}")
        company = spend.mission_company(self.db, plan) if isinstance(plan, dict) else None
        with runctx.scope(mission=row["id"], company=company):
            self._run_scoped(row)

    def _run_scoped(self, row: dict[str, Any]) -> None:
        try:
            plan = json.loads(row["plan"] or "{}")
            if isinstance(plan, dict) and plan.get("kind") == "redaction":
                self._run_redaction(row)
            elif isinstance(plan, dict) and plan.get("kind") == "company_plan":
                self._run_company_plan(row, plan)
            elif isinstance(plan, dict) and plan.get("kind") in ("board", "board_review"):
                self._run_board(row, plan)
            elif isinstance(plan, dict) and plan.get("kind") == "meeting":
                self._run_meeting(row, plan)
            elif isinstance(plan, dict) and plan.get("kind") == "code":
                self._run_code(row, plan)
            else:
                self._run_mission(row)
        except Exception as exc:  # noqa: BLE001 - a mission must never kill the engine
            if not self._cancelled(row["id"]):
                self._set(row["id"], status="failed", error=str(exc)[:1000])
                Companies(self.db).mission_failed(row["id"], str(exc))
                self.notify("mission", f"Mission #{row['id']} échouée", str(exc)[:300])
        finally:
            self._active.discard(row["id"])

    def _cancelled(self, mission_id: int) -> bool:
        row = self.db.one("SELECT status FROM missions WHERE id = ?", (mission_id,))
        return row is not None and row["status"] == "cancelled"

    def active(self) -> list[int]:
        return sorted(self._active)

    # ---- the two kinds ---------------------------------------------------------------------

    def _run_redaction(self, row: dict[str, Any]) -> None:
        from spectre.graph import run as run_pipeline

        models = {
            "scout": ClaudeCodeChat(cli=self.cli, model="haiku"),
            "scribe": ClaudeCodeChat(cli=self.cli, model="sonnet"),
            "warden": ClaudeCodeChat(cli=self.cli, model="opus"),
        }
        result = run_pipeline(row["goal"], models=models)
        report = f"# {row['goal']}\n\n{result.final_text}\n"
        self._finish(row, report, "Texte prêt", "Scout, Scribe et Warden ont terminé.", ok=True)

    def _seat(self, company_id: int, department: str) -> tuple[str, str]:
        """(engine, role text) of the agent holding a company's post."""
        key = Companies(self.db).posts(company_id).get(department, "")
        if key.startswith(PREFIX):
            created = CustomAgents(self.db).get(key)
            if created is not None:
                return created["engine"], f"\n\n{worker_brief(created)}"
            key = ""
        if not key or key == "claude":
            return self.model, ""
        return key, ""

    def _run_board(self, row: dict[str, Any], plan: dict[str, Any]) -> None:
        """The board deliberates on a decision, or reviews one with the figures since."""
        from datetime import datetime

        from spectre.assistant.board import Board

        board = Board(self.db, getattr(self.cli, "root", None))
        decision = board.get(int(plan["decision"]))
        now = datetime.now().astimezone()

        def lead(prompt: str, system: str) -> Reply:
            return self._call(self.lead_model, prompt, system)

        def seat(department: str, prompt: str, system: str) -> Reply:
            engine, role = self._seat(decision["company_id"], department)
            return self._call(engine, prompt, system + role)

        try:
            with runctx.scope(role="conseil"):
                if plan["kind"] == "board":
                    report = board.deliberate(decision["id"], seat, lead, now)
                    title = "Le conseil a décidé"
                    body = board.get(decision["id"])["decision"][:300]
                else:
                    body = board.review(decision["id"], lead, now)
                    report, title = (
                        f"# Réévaluation de la décision #{decision['id']}\n\n{body}\n",
                        "Décision réévaluée",
                    )
        except Exception as exc:
            board.failed(decision["id"], str(exc))
            raise
        self._finish(row, report, title, body, ok=True)

    def _run_code(self, row: dict[str, Any], plan: dict[str, Any]) -> None:
        """The technical department: branch, coding agent, tests, commit (no push)."""
        from spectre.assistant.devteam import DevTeam

        devteam = DevTeam(self.db, self.cli.root)
        job = devteam.job(int(plan["job"]))
        company = Companies(self.db).get(job["company_id"])
        key = Companies(self.db).posts(company["id"]).get("produit", "")
        engine, _ = self._seat(company["id"], "produit")
        engine = engine if engine in ("opus", "sonnet", "haiku", "chatgpt") else "sonnet"
        start = time.perf_counter()
        try:
            with runctx.scope(agent=key or engine, role="développement"):
                report = devteam.work(job["id"], engine, self.cli.config, company["name"])
        except Exception as exc:
            devteam.failed(job["id"], str(exc))
            raise
        finally:
            spend.record(
                self.db,
                Reply("", "", False),
                time.perf_counter() - start,
                engine=engine,
                role="développement",
                agent=key or engine,
            )
        done = devteam.job(job["id"])
        Trust(self.db).record(
            key or engine, "step_ok" if done["tests_ok"] else "step_fail", row["id"]
        )
        title = "Code prêt" if done["status"] == "ready" else "Code à revoir"
        self._finish(row, report, title, done["request"][:200], ok=done["status"] == "ready")

    def _run_meeting(self, row: dict[str, Any], plan: dict[str, Any]) -> None:
        """A meeting's report: summary, then its tasks and decisions filed."""
        from datetime import datetime

        from spectre.assistant.meeting import Meetings

        meetings = Meetings(self.db)
        meeting_id = int(plan["meeting"])
        try:
            with runctx.scope(role="réunion"):
                report = meetings.summarize(
                    meeting_id,
                    lambda p, s: self._call(self.lead_model, p, s),
                    datetime.now().astimezone(),
                )
        except Exception as exc:
            meetings.failed(meeting_id, str(exc))
            raise
        self._finish(row, report, "Compte rendu prêt", meetings.get(meeting_id)["title"], ok=True)

    def _run_company_plan(self, row: dict[str, Any], plan: dict[str, Any]) -> None:
        """The direction breaks an objective into tasks on the company's board."""
        companies = Companies(self.db)
        company = companies.get(int(plan["company"]))
        context = companies.board(company["id"])
        reply = self._call(
            self.lead_model,
            f"Objectif : {row['goal']}\n\nÉtat actuel de l'entreprise :\n{context}",
            planner_prompt(),
        )
        if failed(reply):
            raise ValueError(reply.text)
        items = extract_json(reply.text).get("tasks", [])
        created = companies.add_plan(company["id"], items if isinstance(items, list) else [])
        lines = [
            f"- #{t['id']} {t['department'] or 'sans département'} : {t['title']}"
            + (f" (après {', '.join(f'#{d}' for d in t['depends_on'])})" if t["depends_on"] else "")
            for t in created
        ]
        report = f"# Plan : {row['goal']}\n\nEntreprise : {company['name']}\n\n" + "\n".join(lines)
        self._finish(
            row,
            report,
            "Plan prêt",
            f"{len(created)} tâches au tableau de {company['name']}.",
            ok=True,
        )

    def _run_mission(self, row: dict[str, Any]) -> None:
        mark_mission(self.db, row["id"], "from")  # restore point: file changes start here
        activity.record(self.db, "mission_start", agent="opus", title=row["goal"])
        plan = json.loads(row["plan"] or "{}")
        steps_plan: list[str] = (plan.get("steps") if isinstance(plan, dict) else None) or []
        if not steps_plan:
            context = Memory(self.db).context_block(20)
            reply = self._call(
                self.lead_model, f"Mission : {row['goal']}\n\nContexte :\n{context}", PLANNER
            )
            steps_plan = [str(s) for s in extract_json(reply.text).get("steps", [])][:MAX_STEPS]
            if not steps_plan:
                raise ValueError("le plan de mission est vide")
            saved = {**(plan if isinstance(plan, dict) else {}), "kind": "mission"}
            saved["steps"] = steps_plan
            self._set(row["id"], plan=json.dumps(saved, ensure_ascii=False))
        agent = str(plan.get("agent", "")) if isinstance(plan, dict) else ""
        brief = str(plan.get("brief", "")) if isinstance(plan, dict) else ""
        done: list[dict[str, Any]] = json.loads(row["steps"] or "[]")
        for index in range(len(done), len(steps_plan)):
            if self._stop.is_set():
                return
            if self._cancelled(row["id"]):
                self.notify("mission", f"Mission #{row['id']} arrêtée", "Arrêtée à ta demande.")
                return
            step = steps_plan[index]
            notes = take_notes(self.db, row["id"])
            outcome = self._run_step(row["goal"], step, done, agent, brief=brief, notes=notes)
            done.append(outcome)
            self._set(row["id"], steps=json.dumps(done, ensure_ascii=False))
        summary = "\n\n".join(
            f"Étape {i + 1} ({d.get('name') or agent_name(d.get('agent', ''))}) : {d['step']}\n"
            f"Résultat : {d['result']}\nVérification ({agent_name('haiku')}) : "
            f"{'OK' if d['ok'] else 'NON'} — {d['note']}"
            for i, d in enumerate(done)
        )
        report = self._call(
            self.lead_model, f"Objectif : {row['goal']}\n\n{summary}", REPORTER
        ).text
        missed = sum(1 for d in done if not d["ok"])
        body = "Toutes les étapes sont vérifiées." if not missed else f"{missed} étape(s) à revoir."
        if self._cancelled(row["id"]):
            return
        mark_mission(self.db, row["id"], "to")
        activity.record(
            self.db,
            "mission_done",
            agent="opus",
            title=row["goal"],
            detail=body,
            status="fail" if missed else "ok",
        )
        self._finish(row, report, "Mission terminée", body, ok=not missed)
        if not missed and self.learn:
            self._learn(row, report)

    def _learn(self, row: dict[str, Any], report: str) -> None:
        """Ask the review engine whether this mission taught a reusable method."""
        learning = Learning(self.db, self.cli.root)
        ref = self.learning_model or self.verifier_model
        try:
            with runctx.scope(role="apprentissage"):
                proposal = learning.review(row, report, lambda p, s: self._call(ref, p, s))
        except Exception:  # noqa: BLE001 - learning must never break a finished mission
            return
        if proposal:
            self.notify(
                "apprentissage",
                f"Compétence proposée : {proposal['name']}",
                f"{proposal['description']} (tirée de la mission #{row['id']} ; à valider "
                "dans la vue Apprentissage)",
            )

    def _chosen(self, agent: str) -> str:
        """Who executes a step: the mission's own choice, else the `mission_model` setting."""
        remote = split_ref(agent)[0] and not agent.startswith(PREFIX)  # provider:model
        name = agent if agent in AGENTS or remote else self.model
        if name == "claude":  # Claude asked for one mission while the setting names another
            name = self.model if self.model in ("opus", "sonnet", "haiku") else "sonnet"
        return name

    def _worker(self, agent: str) -> tuple[Any, str]:
        return self.engines.worker(self._chosen(agent))

    def _run_step(
        self,
        goal: str,
        step: str,
        done: list[dict[str, Any]],
        agent: str = "",
        *,
        brief: str = "",
        notes: list[str] | None = None,
    ) -> dict[str, Any]:
        previous = "\n".join(f"- {d['step']} → {d['result'][:400]}" for d in done) or "(aucune)"
        prompt = f"Mission : {goal}\nÉtapes déjà faites :\n{previous}\n\nÉtape à faire : {step}"
        if notes:
            prompt += "\n\nConsignes de l'utilisateur, données en cours de route (prioritaires) :\n"
            prompt += "\n".join(f"- {n}" for n in notes)
        created = CustomAgents(self.db).get(agent) if agent.startswith(PREFIX) else None
        # `model` is the agent (Simon...), `engine` what really runs it (cursor, or Claude if
        # the user moved him there), `wanted` what that engine's `ask` takes
        model = self._chosen(created["engine"] if created else agent)
        worker, wanted = self.engines.worker(model)
        engine = wanted if split_ref(wanted)[0] else model
        name = created["name"] if created else agent_name(model)
        system = WORKER.format(name=name, workspace=self.cli.workspace)
        learned = Learning(self.db, self.cli.root).catalogue() if hasattr(self.cli, "root") else ""
        if learned:
            system += (
                "\n\nCompétences apprises (lis celle qui s'applique avec l'outil skill(name) "
                f"avant d'agir) :\n{learned}"
            )
        if created:
            system += f"\n\n{worker_brief(created)}"
        elif model in SPECIALTIES:
            system += f"\n\n{SPECIALTIES[model]}"
        if brief:
            system += f"\n\n{brief}"
        note, ok, result = "", False, ""
        key = f"{PREFIX}{created['id']}" if created else model  # whose record this step feeds
        activity.record(self.db, "step_start", agent=key, title=step, detail=name)
        step_started = time.perf_counter()
        for attempt in range(2):
            extra = f"\n\nTentative précédente insuffisante : {note}" if attempt else ""
            start = time.perf_counter()
            with runctx.scope(agent=key, role="exécution"):
                answer = worker.ask(prompt + extra, system=system, model=wanted, with_tools=True)
                spend.record(self.db, answer, time.perf_counter() - start, engine=engine)
                if failed(answer) and self.fallbacks:
                    start = time.perf_counter()
                    answer, model = self.engines.ask_chain(
                        self.fallbacks, prompt + extra, system, tools=True
                    )
                    spend.record(self.db, answer, time.perf_counter() - start, engine=model)
            result = answer.text
            check = self._call(
                self.verifier_model, f"Étape : {step}\n\nCompte rendu :\n{result}", VERIFIER
            )
            try:
                verdict = extract_json(check.text)
                ok, note = bool(verdict.get("ok")), str(verdict.get("note", ""))
            except ValueError:
                ok, note = False, "vérification illisible"
            if ok:
                break
        Trust(self.db).record(key, "step_ok" if ok else "step_fail")
        activity.record(
            self.db,
            "step_done",
            agent=key,
            title=step,
            status="ok" if ok else "fail",
            detail=json.dumps({"result": result[:1500], "note": note}, ensure_ascii=False),
            seconds=time.perf_counter() - step_started,
        )
        return {
            "step": step,
            "result": result,
            "ok": ok,
            "note": note,
            "agent": model,
            "name": name,
            "key": key,
        }

    # ---- persistence -----------------------------------------------------------------------

    def _finish(
        self, row: dict[str, Any], report: str, title: str, body: str, *, ok: bool = True
    ) -> None:
        folder = self.cli.workspace / "missions"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"mission-{row['id']:04d}.md"
        path.write_text(report, encoding="utf-8")
        self._set(row["id"], status="done", report=report)
        Companies(self.db).mission_finished(row["id"], ok, "" if ok else body)
        self.notify("mission", f"{title} (#{row['id']})", f"{body} Rapport : {path}")

    def _set(self, mission_id: int, **fields: Any) -> None:
        sets = ", ".join(f"{key} = ?" for key in fields)
        self.db.execute(
            f"UPDATE missions SET {sets}, updated_at = ? WHERE id = ?",  # noqa: S608 - fixed keys
            (*fields.values(), now_iso(), mission_id),
        )

    def wait_idle(self, timeout: float = 5.0) -> None:  # pragma: no cover - test helper
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self.db.one(
            "SELECT 1 FROM missions WHERE status IN ('queued', 'running')"
        ):
            time.sleep(0.05)
