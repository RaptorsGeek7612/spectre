"""Background missions: plan, steps executed with tools, each step verified, then a report.

`kind=redaction` runs Spectre's own pipeline (Scout -> Scribe -> Warden) with the three agents
served by the Claude Code CLI, so it works on the subscription without API credit.
Mission steps are executed by Claude (`mission_model` = sonnet, opus or haiku), by ChatGPT through
the Codex CLI (chatgpt) or by Mistral through the Vibe CLI (mistral), set in the settings or chosen
for one mission (`agent`); Spectre still plans, the Haiku verifier still checks each step, and
Spectre writes the report.
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

from spectre.assistant.brain import ClaudeCLI, extract_json, one_shot
from spectre.assistant.codex import CodexCLI
from spectre.assistant.config import AGENT_CHOICES, agent_name
from spectre.assistant.custom_agents import PREFIX, CustomAgents, worker_brief
from spectre.assistant.db import Database, now_iso
from spectre.assistant.memory import Memory
from spectre.assistant.mistral import VibeCLI

MAX_STEPS = 6
EXTERNAL: dict[str, Any] = {"chatgpt": CodexCLI, "mistral": VibeCLI}  # non-Claude agents
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
de ce que tu as réellement fait et obtenu (fichiers créés, sources). N'invente rien."""

SPECIALTIES = {  # added to WORKER for the agent in charge of each field
    "chatgpt": """\
Ta spécialité : les images, la vidéo et le multimédia (création et retouche d'images, montage \
et sous-titres, audio, formats et conversions, choix d'outils et de banques de médias \
libres). Respecte les droits d'auteur et le droit à l'image : pas de deepfake d'une personne \
réelle, pas de contenu trompeur.""",
    "mistral": """\
Ta spécialité : la cybersécurité (audit de configuration, durcissement, analyse de \
vulnérabilités, veille CVE, réponse à incident) et les tests d'intrusion. Tu n'agis que sur \
les systèmes de l'utilisateur ou ceux pour lesquels la mission mentionne une autorisation \
écrite ; sinon, arrête-toi et dis-le dans ton compte rendu. Pas d'action destructive, pas de \
déni de service, pas d'exfiltration de données réelles. Chaque constat donne sa gravité, sa \
preuve et sa correction.""",
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
    ) -> None:
        self.db = db
        self.cli = cli
        self.notify = notify
        self.model = model  # execution agents: a Claude alias, "chatgpt" or "mistral"
        self.lead_model = lead_model  # Spectre itself plans and reports
        self.agents = dict(agents or {})  # ChatGPT and Mistral agents, created on first use
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- lifecycle -----------------------------------------------------------------------

    def start(self) -> None:
        self.db.execute("UPDATE missions SET status = 'queued' WHERE status = 'running'")
        self._thread = threading.Thread(target=self._loop, name="spectre-missions", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:  # pragma: no cover - thread wrapper around run_next
        while not self._stop.is_set():
            if not self.run_next():
                self._stop.wait(2.0)

    def run_next(self) -> bool:
        """Run the oldest queued mission; return False when there was none."""
        row = self.db.one("SELECT * FROM missions WHERE status = 'queued' ORDER BY id LIMIT 1")
        if row is None:
            return False
        self._set(row["id"], status="running")
        try:
            plan = json.loads(row["plan"] or "{}")
            if isinstance(plan, dict) and plan.get("kind") == "redaction":
                self._run_redaction(row)
            else:
                self._run_mission(row)
        except Exception as exc:  # noqa: BLE001 - a mission must never kill the engine
            self._set(row["id"], status="failed", error=str(exc)[:1000])
            self.notify("mission", f"Mission #{row['id']} échouée", str(exc)[:300])
        return True

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
        self._finish(row, report, "Texte prêt", "Scout, Scribe et Warden ont terminé.")

    def _run_mission(self, row: dict[str, Any]) -> None:
        plan = json.loads(row["plan"] or "{}")
        steps_plan: list[str] = (plan.get("steps") if isinstance(plan, dict) else None) or []
        if not steps_plan:
            context = Memory(self.db).context_block(20)
            reply = one_shot(
                self.cli,
                f"Mission : {row['goal']}\n\nContexte :\n{context}",
                PLANNER,
                model=self.lead_model,
            )
            steps_plan = [str(s) for s in extract_json(reply.text).get("steps", [])][:MAX_STEPS]
            if not steps_plan:
                raise ValueError("le plan de mission est vide")
            saved: dict[str, Any] = {"kind": "mission", "steps": steps_plan}
            if isinstance(plan, dict) and plan.get("agent"):
                saved["agent"] = plan["agent"]
            self._set(row["id"], plan=json.dumps(saved, ensure_ascii=False))
        agent = str(plan.get("agent", "")) if isinstance(plan, dict) else ""
        done: list[dict[str, Any]] = json.loads(row["steps"] or "[]")
        for index in range(len(done), len(steps_plan)):
            if self._stop.is_set():
                return
            step = steps_plan[index]
            outcome = self._run_step(row["goal"], step, done, agent)
            done.append(outcome)
            self._set(row["id"], steps=json.dumps(done, ensure_ascii=False))
        summary = "\n\n".join(
            f"Étape {i + 1} ({d.get('name') or agent_name(d.get('agent', ''))}) : {d['step']}\n"
            f"Résultat : {d['result']}\nVérification ({agent_name('haiku')}) : "
            f"{'OK' if d['ok'] else 'NON'} — {d['note']}"
            for i, d in enumerate(done)
        )
        report = one_shot(
            self.cli, f"Objectif : {row['goal']}\n\n{summary}", REPORTER, model=self.lead_model
        ).text
        failed = sum(1 for d in done if not d["ok"])
        body = "Toutes les étapes sont vérifiées." if not failed else f"{failed} étape(s) à revoir."
        self._finish(row, report, "Mission terminée", body)

    def _worker(self, agent: str) -> tuple[Any, str]:
        """Who executes a step: the mission's own choice, else the `mission_model` setting."""
        name = agent if agent in AGENTS else self.model
        if name == "claude":  # Claude asked for one mission while the setting names another
            name = "sonnet" if self.model in EXTERNAL else self.model
        if name not in EXTERNAL:
            return self.cli, name
        if name not in self.agents:
            self.agents[name] = EXTERNAL[name](self.cli.config, self.cli.root)
        return self.agents[name], name

    def _run_step(
        self, goal: str, step: str, done: list[dict[str, Any]], agent: str = ""
    ) -> dict[str, Any]:
        previous = "\n".join(f"- {d['step']} → {d['result'][:400]}" for d in done) or "(aucune)"
        prompt = f"Mission : {goal}\nÉtapes déjà faites :\n{previous}\n\nÉtape à faire : {step}"
        created = CustomAgents(self.db).get(agent) if agent.startswith(PREFIX) else None
        worker, model = self._worker(created["engine"] if created else agent)
        name = created["name"] if created else agent_name(model)
        system = WORKER.format(name=name, workspace=self.cli.workspace)
        if created:
            system += f"\n\n{worker_brief(created)}"
        elif model in SPECIALTIES:
            system += f"\n\n{SPECIALTIES[model]}"
        note, ok, result = "", False, ""
        for attempt in range(2):
            extra = f"\n\nTentative précédente insuffisante : {note}" if attempt else ""
            result = worker.ask(prompt + extra, system=system, model=model, with_tools=True).text
            check = one_shot(
                self.cli, f"Étape : {step}\n\nCompte rendu :\n{result}", VERIFIER, model="haiku"
            )
            try:
                verdict = extract_json(check.text)
                ok, note = bool(verdict.get("ok")), str(verdict.get("note", ""))
            except ValueError:
                ok, note = False, "vérification illisible"
            if ok:
                break
        return {
            "step": step,
            "result": result,
            "ok": ok,
            "note": note,
            "agent": model,
            "name": name,
        }

    # ---- persistence -----------------------------------------------------------------------

    def _finish(self, row: dict[str, Any], report: str, title: str, body: str) -> None:
        folder = self.cli.workspace / "missions"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"mission-{row['id']:04d}.md"
        path.write_text(report, encoding="utf-8")
        self._set(row["id"], status="done", report=report)
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
