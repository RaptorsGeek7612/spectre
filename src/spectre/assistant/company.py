"""Companies Spectre helps run: an org chart of departments, a durable task board, and the link
between tasks and missions.

Each department is a post: the user puts an agent on it (a created agent, which the user always
names, or a built-in one or engine); empty = the mission setting. Tasks belong to a department,
may depend on other tasks, and run as missions with the department's brief. A finished mission
moves its task to `done` when every step was verified, else to `review` (for the user to check);
a failed or stopped one moves it to `blocked`. With autopilot on, ready tasks start on their
own; otherwise the user (or Spectre, when asked) starts them.
"""

from __future__ import annotations

import contextlib
import json
import unicodedata
from typing import Any

from spectre.assistant.config import resolve_agent
from spectre.assistant.custom_agents import PREFIX, CustomAgents
from spectre.assistant.db import Database, now_iso
from spectre.assistant.providers import split_ref

DEPARTMENTS: dict[str, tuple[str, str]] = {
    "direction": (
        "Direction générale",
        "Tu tiens la direction générale : vision, stratégie, priorités, objectifs (OKR), "
        "arbitrages entre départements et synthèses pour le dirigeant. Tu tranches avec des "
        "chiffres et tu proposes toujours la prochaine étape.",
    ),
    "finance": (
        "Finance",
        "Tu tiens la finance : budget, trésorerie, prix, prévisions, indicateurs SaaS (MRR, "
        "churn, CAC, LTV, marge). Tu montres tes calculs et tes hypothèses. Tu n'effectues "
        "jamais de paiement ni de virement.",
    ),
    "marketing": (
        "Marketing",
        "Tu tiens le marketing : positionnement, personas, contenus, SEO, réseaux sociaux, "
        "campagnes et leur mesure. Tu produis des brouillons : rien n'est publié sans le oui "
        "de l'utilisateur.",
    ),
    "ventes": (
        "Ventes",
        "Tu tiens les ventes : cibles, prospection, offres, devis, argumentaires, suivi des "
        "prospects. Tu prépares les messages : aucun contact n'est envoyé sans le oui de "
        "l'utilisateur.",
    ),
    "support": (
        "Support client",
        "Tu tiens le support client : FAQ, base de connaissances, réponses types, analyse des "
        "demandes et des irritants. Ton ton est clair, empathique et précis.",
    ),
    "produit": (
        "Produit et technique",
        "Tu tiens le produit et la technique : spécifications, feuille de route, architecture, "
        "code, tests, qualité, sécurité applicative et mise en production. Tu documentes ce que "
        "tu fais et tu ne déploies rien sans le oui de l'utilisateur.",
    ),
    "juridique": (
        "Juridique et conformité",
        "Tu tiens le juridique et la conformité (droit français par défaut) : statuts, CGV, "
        "CGU, mentions légales, RGPD, propriété intellectuelle. Tu signales toujours ce qu'un "
        "professionnel doit vérifier ; tu ne remplaces pas un avocat ni un expert-comptable.",
    ),
    "operations": (
        "Opérations et RH",
        "Tu tiens les opérations et les ressources humaines : processus, outils, fournisseurs, "
        "recrutement, organisation et planning. Tu rends les choses simples et mesurables.",
    ),
}
DEPARTMENT_ALIASES = {
    "dg": "direction",
    "ceo": "direction",
    "strategie": "direction",
    "compta": "finance",
    "comptabilite": "finance",
    "commercial": "ventes",
    "vente": "ventes",
    "sales": "ventes",
    "service client": "support",
    "sav": "support",
    "tech": "produit",
    "technique": "produit",
    "dev": "produit",
    "developpement": "produit",
    "legal": "juridique",
    "conformite": "juridique",
    "rh": "operations",
    "ops": "operations",
}
STATUSES = ("todo", "doing", "blocked", "review", "done", "cancelled")
STATUS_LABELS = {
    "todo": "à faire",
    "doing": "en cours",
    "blocked": "bloquée",
    "review": "à valider",
    "done": "faite",
    "cancelled": "annulée",
}
MANUAL = ("todo", "blocked", "done", "cancelled")  # what a person (or Spectre) may set by hand
MAX_COMPANIES = 20
MAX_TASKS = 200  # open tasks per company
MAX_PLAN = 12
MAX_COMMENT = 2000


PLANNER = """\
Tu es la direction générale d'une entreprise et tu découpes un objectif en tâches confiées aux \
départements. Départements possibles : {departments}. Réponds UNIQUEMENT par un objet JSON : \
{{"tasks": [{{"title": "...", "department": "...", "detail": "...", "priority": 1, \
"depends_on": [0]}}]}} avec 1 à {max} tâches concrètes, vérifiables, chacune faisable par un \
agent avec recherche web et fichiers. priority : 1 urgent, 2 normal, 3 plus tard. depends_on : \
les indices (à partir de 0) des tâches qui doivent être finies avant. Pas d'action externe \
(envoyer, publier, payer) : prépare des brouillons."""


class CompanyError(ValueError):
    """A refused change (the message is for the user)."""


def plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def resolve_department(value: str) -> str:
    """A department key from its key, label or a common alias; empty when unknown."""
    wanted = plain(value)
    if wanted in DEPARTMENTS:
        return wanted
    for key, (label, _) in DEPARTMENTS.items():
        if plain(label) == wanted or plain(label.split()[0]) == wanted:
            return key
    return DEPARTMENT_ALIASES.get(wanted, "")


class Companies:
    """Companies, their posts and their task board, in the assistant's database."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- companies -------------------------------------------------------------------------

    def all(self) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM companies ORDER BY id")

    def get(self, value: str | int) -> dict[str, Any]:
        """A company by id or name (any case or accents); CompanyError when unknown."""
        text = str(value).strip().removeprefix("#")
        if text.isdigit():
            found = self.db.one("SELECT * FROM companies WHERE id = ?", (int(text),))
        else:
            found = next((c for c in self.all() if plain(c["name"]) == plain(text)), None)
        if found is None:
            if not text and len(self.all()) == 1:  # only one: no need to name it
                return self.all()[0]
            names = ", ".join(c["name"] for c in self.all()) or "aucune pour l'instant"
            raise CompanyError(f"entreprise inconnue « {value} » ; existantes : {names}")
        return found

    def create(self, name: str, pitch: str = "") -> dict[str, Any]:
        name, pitch = name.strip(), pitch.strip()
        if not 2 <= len(name) <= 60:
            raise CompanyError("le nom de l'entreprise doit faire de 2 à 60 caractères")
        if any(plain(c["name"]) == plain(name) for c in self.all()):
            raise CompanyError(f"l'entreprise « {name} » existe déjà")
        if len(self.all()) >= MAX_COMPANIES:
            raise CompanyError(f"{MAX_COMPANIES} entreprises au maximum")
        cid = self.db.execute(
            "INSERT INTO companies(name, pitch, created_at) VALUES(?, ?, ?)",
            (name, pitch[:1000], now_iso()),
        )
        return self.get(cid)

    def set_autopilot(self, company: str | int, on: bool) -> dict[str, Any]:
        found = self.get(company)
        self.db.execute("UPDATE companies SET autopilot = ? WHERE id = ?", (int(on), found["id"]))
        return self.get(found["id"])

    # ---- org chart ---------------------------------------------------------------------------

    def posts(self, company: str | int) -> dict[str, str]:
        found = self.get(company)
        rows = self.db.all(
            "SELECT department, agent FROM posts WHERE company_id = ?", (found["id"],)
        )
        held = {r["department"]: r["agent"] for r in rows}
        return {key: held.get(key, "") for key in DEPARTMENTS}

    def set_post(self, company: str | int, department: str, agent: str) -> str:
        """Put an agent on a post (name, built-in key, engine or "" for the setting);
        returns the stored agent key."""
        found = self.get(company)
        key = resolve_department(department)
        if not key:
            raise CompanyError(
                f"département inconnu « {department} » ; au choix : {', '.join(DEPARTMENTS)}"
            )
        stored = self.agent_key(agent)
        self.db.execute(
            "INSERT INTO posts(company_id, department, agent) VALUES(?, ?, ?) "
            "ON CONFLICT(company_id, department) DO UPDATE SET agent = excluded.agent",
            (found["id"], key, stored),
        )
        return stored

    def agent_key(self, agent: str) -> str:
        """`agent:<id>` for a created agent, a built-in key, a provider:model engine, or ""."""
        agent = agent.strip()
        if not agent or plain(agent) in ("defaut", "aucun", "reglage"):
            return ""
        created = CustomAgents(self.db).get(agent)
        if created is not None:
            return f"{PREFIX}{created['id']}"
        builtin = resolve_agent(agent)
        if builtin:
            return builtin
        if split_ref(agent)[0]:
            return agent
        raise CompanyError(f"agent inconnu « {agent} » (crée-le d'abord, avec le nom que tu veux)")

    def agent_label(self, key: str) -> str:
        from spectre.assistant.config import agent_name

        if not key:
            return "selon les réglages"
        if key.startswith(PREFIX):
            created = CustomAgents(self.db).get(key)
            return created["name"] if created else "agent supprimé"
        return agent_name(key)

    # ---- tasks ---------------------------------------------------------------------------------

    def tasks(self, company: str | int, *, open_only: bool = False) -> list[dict[str, Any]]:
        found = self.get(company)
        sql = "SELECT * FROM tasks WHERE company_id = ?"
        if open_only:
            sql += " AND status NOT IN ('done', 'cancelled')"
        rows = self.db.all(sql + " ORDER BY priority, id", (found["id"],))
        for row in rows:
            row["depends_on"] = json.loads(row["depends_on"] or "[]")
        return rows

    def task(self, task_id: int | str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM tasks WHERE id = ?", (int(str(task_id).lstrip("#")),))
        if row is None:
            raise CompanyError(f"tâche #{task_id} introuvable")
        row["depends_on"] = json.loads(row["depends_on"] or "[]")
        return row

    def add_task(
        self,
        company: str | int,
        title: str,
        *,
        department: str = "",
        detail: str = "",
        priority: int = 2,
        depends_on: list[int] | None = None,
        agent: str = "",
    ) -> dict[str, Any]:
        found = self.get(company)
        title = title.strip()
        if not 3 <= len(title) <= 200:
            raise CompanyError("le titre d'une tâche doit faire de 3 à 200 caractères")
        key = resolve_department(department) if department.strip() else ""
        if department.strip() and not key:
            raise CompanyError(f"département inconnu « {department} »")
        if len(self.tasks(found["id"], open_only=True)) >= MAX_TASKS:
            raise CompanyError(f"{MAX_TASKS} tâches ouvertes au maximum : termine-en d'abord")
        deps = sorted(set(depends_on or []))
        for dep in deps:
            if self.task(dep)["company_id"] != found["id"]:
                raise CompanyError(f"la tâche #{dep} appartient à une autre entreprise")
        stamp = now_iso()
        tid = self.db.execute(
            "INSERT INTO tasks(company_id, title, detail, department, agent, priority, depends_on, "
            "created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                found["id"],
                title,
                detail.strip()[:4000],
                key,
                self.agent_key(agent),
                min(3, max(1, int(priority))),
                json.dumps(deps),
                stamp,
                stamp,
            ),
        )
        self.log(tid, "created", title)
        return self.task(tid)

    def set_status(self, task_id: int | str, status: str, note: str = "") -> dict[str, Any]:
        """A status set by hand (todo, blocked, done, cancelled)."""
        task = self.task(task_id)
        wanted = next((s for s in STATUSES if plain(STATUS_LABELS[s]) == plain(status)), status)
        wanted = {"bloquee": "blocked", "faite": "done", "annulee": "cancelled"}.get(
            plain(wanted), wanted
        )
        if wanted not in MANUAL:
            raise CompanyError(f"statut « {status} » : au choix {', '.join(MANUAL)}")
        if task["status"] == "doing" and wanted != "cancelled":
            raise CompanyError(f"la tâche #{task['id']} est en cours : arrête d'abord sa mission")
        self._update(task["id"], status=wanted, note=note.strip()[:1000] or task["note"])
        if task["status"] == "review" and task["mission_id"] and wanted in ("done", "todo"):
            from spectre.assistant.trust import Trust

            trust = Trust(self.db)
            agent = trust.mission_agent(task["mission_id"])
            trust.record(
                agent, "task_validated" if wanted == "done" else "task_redo", task["mission_id"]
            )
        if wanted == "cancelled" and task["mission_id"]:
            stop_mission(self.db, task["mission_id"])
        return self.task(task["id"])

    def ready(self, company: str | int) -> list[dict[str, Any]]:
        """Tasks to do whose dependencies are all done, most urgent first."""
        tasks = self.tasks(company)
        done = {t["id"] for t in tasks if t["status"] == "done"}
        return [t for t in tasks if t["status"] == "todo" and set(t["depends_on"]) <= done]

    def start(self, task_id: int | str) -> int:
        """Queue the task's mission; returns the mission id."""
        task = self.task(task_id)
        if task["status"] != "todo":
            raise CompanyError(
                f"la tâche #{task['id']} est {STATUS_LABELS[task['status']]} : elle ne peut pas "
                "être lancée"
            )
        company = self.get(task["company_id"])
        done = {t["id"] for t in self.tasks(company["id"]) if t["status"] == "done"}
        missing = [d for d in task["depends_on"] if d not in done]
        if missing:
            raise CompanyError(
                f"la tâche #{task['id']} attend d'abord : " + ", ".join(f"#{d}" for d in missing)
            )
        agent = task["agent"] or (self.posts(company["id"]).get(task["department"], ""))
        plan: dict[str, Any] = {
            "kind": "mission",
            "task": task["id"],
            "company": company["id"],
            "brief": self.brief(company, task["department"]),
        }
        if agent:
            plan["agent"] = agent
        goal = f"{task['title']}" + (f"\n\n{task['detail']}" if task["detail"] else "")
        mid = enqueue(self.db, goal, plan)
        self._update(task["id"], status="doing", mission_id=mid)
        return mid

    def start_ready(self, company: str | int, limit: int = 10) -> list[int]:
        return [self.start(t["id"]) for t in self.ready(company)[:limit]]

    def brief(self, company: dict[str, Any], department: str) -> str:
        """What the agent on a task learns about the company and its post."""
        head = f"Tu travailles pour l'entreprise « {company['name']} »"
        head += f" : {company['pitch']}" if company["pitch"] else "."
        if department in DEPARTMENTS:
            label, duty = DEPARTMENTS[department]
            head += f"\nTon poste : {label}. {duty}"
        return head

    def mission_finished(self, mission_id: int, ok: bool, note: str = "") -> None:
        """Called by the mission engine: move the linked task on."""
        row = self.db.one("SELECT id FROM tasks WHERE mission_id = ?", (mission_id,))
        if row is None:
            return
        self._update(row["id"], status="done" if ok else "review", note=note[:1000])

    def mission_failed(self, mission_id: int, reason: str) -> None:
        row = self.db.one("SELECT id, status FROM tasks WHERE mission_id = ?", (mission_id,))
        if row is None or row["status"] == "cancelled":
            return
        self._update(row["id"], status="blocked", note=reason[:1000])

    def autopilot_tick(self, capacity: int, allowed: Any = None) -> list[int]:
        """Start ready tasks of companies on autopilot, within `capacity` free mission slots.
        `allowed(agent_key)` says whether a task's agent has earned it (None = every agent)."""
        started: list[int] = []
        for company in self.all():
            if not company["autopilot"]:
                continue
            posts = self.posts(company["id"])
            for task in self.ready(company["id"]):
                if len(started) >= capacity:
                    return started
                agent = task["agent"] or posts.get(task["department"], "")
                if allowed is not None and not allowed(agent):
                    continue
                started.append(self.start(task["id"]))
        return started

    def board(self, company: str | int) -> str:
        """The org chart and open tasks, as text for the brain."""
        found = self.get(company)
        lines = [
            f"Entreprise #{found['id']} « {found['name']} »"
            + (f" : {found['pitch']}" if found["pitch"] else ""),
            f"Pilote automatique : {'activé' if found['autopilot'] else 'désactivé'}",
            "Organigramme :",
        ]
        for key, agent in self.posts(found["id"]).items():
            lines.append(f"- {DEPARTMENTS[key][0]} ({key}) : {self.agent_label(agent)}")
        tasks = self.tasks(found["id"])
        lines.append("Tâches :" if tasks else "Tâches : aucune")
        for t in tasks:
            deps = (
                f", après {', '.join(f'#{d}' for d in t['depends_on'])}" if t["depends_on"] else ""
            )
            mission = f", mission #{t['mission_id']}" if t["mission_id"] else ""
            note = f" — {t['note'][:120]}" if t["note"] else ""
            lines.append(
                f"- #{t['id']} [{STATUS_LABELS[t['status']]}] P{t['priority']} "
                f"{t['department'] or 'sans département'} : {t['title']}{deps}{mission}{note}"
            )
        return "\n".join(lines)

    def add_plan(self, company: str | int, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create the tasks of a decomposed objective (dependencies given by index)."""
        found = self.get(company)
        created: list[dict[str, Any]] = []
        for index, item in enumerate(items[:MAX_PLAN]):
            if not isinstance(item, dict):
                continue
            deps = []
            for ref in item.get("depends_on") or []:
                if isinstance(ref, int) and 0 <= ref < index and ref < len(created):
                    deps.append(created[ref]["id"])
            department = str(item.get("department", ""))
            created.append(
                self.add_task(
                    found["id"],
                    str(item.get("title", ""))[:200],
                    department=department if resolve_department(department) else "",
                    detail=str(item.get("detail", "")),
                    priority=int(item.get("priority", 2) or 2),
                    depends_on=deps,
                )
            )
        if not created:
            raise CompanyError("le plan ne contient aucune tâche exploitable")
        return created

    # ---- the card: history, comments, review with requested changes, reassignment ----------

    def log(self, task_id: int, kind: str, text: str = "", actor: str = "") -> None:
        """One line of a task's history (created, status, comment, changes, agent)."""
        self.db.execute(
            "INSERT INTO task_events(task_id, ts, kind, actor, text) VALUES(?, ?, ?, ?, ?)",
            (task_id, now_iso(), kind, actor[:60], text.strip()[:MAX_COMMENT]),
        )

    def events(self, task_id: int | str) -> list[dict[str, Any]]:
        task = self.task(task_id)
        return self.db.all(
            "SELECT ts, kind, actor, text FROM task_events WHERE task_id = ? ORDER BY id",
            (task["id"],),
        )

    def comment(self, task_id: int | str, text: str, actor: str = "toi") -> dict[str, Any]:
        """A comment on the card; a running mission reads it before its next step."""
        task = self.task(task_id)
        if not text.strip():
            raise CompanyError("commentaire vide")
        self.log(task["id"], "comment", text, actor)
        if task["status"] == "doing" and task["mission_id"]:
            # the mission may have just ended: the comment stays on the card
            with contextlib.suppress(CompanyError):
                steer_mission(self.db, task["mission_id"], f"Commentaire sur la tâche : {text}")
        return self.task(task["id"])

    def request_changes(self, task_id: int | str, text: str) -> dict[str, Any]:
        """Send a task to be checked back to its agent, with what to change (it is ready
        again: « Lancer » or the autopilot restarts it with the request in its detail)."""
        task = self.task(task_id)
        if task["status"] not in ("review", "done"):
            raise CompanyError(
                f"la tâche #{task['id']} est {STATUS_LABELS[task['status']]} : seule une tâche "
                "à valider ou faite peut repartir avec des changements"
            )
        if not text.strip():
            raise CompanyError("dis ce qu'il faut changer")
        agent = task["agent"]
        if task["mission_id"]:
            from spectre.assistant.trust import Trust

            trust = Trust(self.db)
            done_by = trust.mission_agent(task["mission_id"])
            trust.record(done_by, "task_redo", task["mission_id"])
            agent = agent or self._stored_agent(done_by)  # back to whoever did it
        detail = f"{task['detail']}\n\nChangements demandés ({now_iso()[:10]}) : {text.strip()}"
        self._update(task["id"], status="todo", agent=agent, detail=detail.strip()[:8000])
        self.log(task["id"], "changes", text, "toi")
        return self.task(task["id"])

    def assign(self, task_id: int | str, agent: str) -> dict[str, Any]:
        """Give a task to another agent (or back to its post: empty)."""
        task = self.task(task_id)
        if task["status"] == "doing":
            raise CompanyError(f"la tâche #{task['id']} est en cours : arrête d'abord sa mission")
        key = self.agent_key(agent)
        self._update(task["id"], agent=key)
        self.log(task["id"], "agent", self.agent_label(key) if key else "celui du poste")
        return self.task(task["id"])

    def _waiting(self, mission_id: int) -> int:
        """How many of a mission's requests still wait for the user's yes."""
        asked = []
        for row in self.db.all(
            "SELECT detail FROM activity WHERE mission_id = ? AND kind = 'approval'",
            (mission_id,),
        ):
            try:
                asked.append(int(json.loads(row["detail"] or "{}").get("id", 0)))
            except (ValueError, TypeError, AttributeError):
                continue
        if not asked:
            return 0
        marks = ",".join("?" * len(asked))
        return len(
            self.db.all(
                f"SELECT id FROM approvals WHERE status = 'pending' AND id IN ({marks})",  # noqa: S608
                tuple(asked),
            )
        )

    def waiting_tasks(self, company: str | int) -> list[int]:
        """The company's running tasks whose agent waits for the user (badge on the card)."""
        return [
            t["id"]
            for t in self.tasks(company, open_only=True)
            if t["status"] == "doing" and t["mission_id"] and self._waiting(t["mission_id"])
        ]

    def _stored_agent(self, key: str) -> str:
        try:
            return self.agent_key(key)
        except CompanyError:
            return ""

    def card(self, task_id: int | str) -> dict[str, Any]:
        """Everything the card shows: the task, its history, its mission's steps and the files
        its agent wrote (for « Voir le code »)."""
        task = self.task(task_id)
        mission: dict[str, Any] = {}
        files: list[dict[str, Any]] = []
        waiting = 0
        if task["mission_id"]:
            row = self.db.one(
                "SELECT id, status, steps, report, error, updated_at FROM missions WHERE id = ?",
                (task["mission_id"],),
            )
            if row is not None:
                steps = json.loads(row["steps"] or "[]")
                mission = {
                    "id": row["id"],
                    "status": row["status"],
                    "updated_at": row["updated_at"],
                    "error": row["error"],
                    "report": row["report"][:6000],
                    "steps": [
                        {
                            "title": str(s.get("step") or ""),
                            "agent": str(s.get("name") or s.get("key") or ""),
                            "ok": bool(s.get("ok")),
                            "note": str(s.get("note") or "")[:400],
                        }
                        for s in steps
                        if isinstance(s, dict)
                    ],
                }
            from spectre.assistant import codeview

            files = codeview.files(self.db, mission=task["mission_id"])
            waiting = self._waiting(task["mission_id"])
        blockers = [d for d in task["depends_on"] if self.task(d)["status"] != "done"]
        return {
            "task": task,
            "agent_label": self.agent_label(task["agent"]) if task["agent"] else "",
            "events": self.events(task["id"]),
            "mission": mission,
            "files": files,
            "waiting": waiting,
            "blocked_by": blockers,
        }

    def _update(self, task_id: int, **fields: Any) -> None:
        if "status" in fields:
            old = self.db.one("SELECT status FROM tasks WHERE id = ?", (task_id,))
            if old is not None and old["status"] != fields["status"]:
                self.log(
                    task_id,
                    "status",
                    f"{STATUS_LABELS.get(old['status'], old['status'])} → "
                    f"{STATUS_LABELS.get(fields['status'], fields['status'])}"
                    + (f" — {fields['note']}" if fields.get("note") else ""),
                )
        sets = ", ".join(f"{key} = ?" for key in fields)
        self.db.execute(
            f"UPDATE tasks SET {sets}, updated_at = ? WHERE id = ?",  # noqa: S608 - fixed keys
            (*fields.values(), now_iso(), task_id),
        )


def planner_prompt() -> str:
    names = ", ".join(f"{key} ({label})" for key, (label, _) in DEPARTMENTS.items())
    return PLANNER.format(departments=names, max=MAX_PLAN)


# ---- missions: queueing, steering and stopping (shared by tools, the service and the engine) ----


def enqueue(db: Database, goal: str, plan: dict[str, Any]) -> int:
    stamp = now_iso()
    return db.execute(
        "INSERT INTO missions(ts, goal, status, plan, updated_at) VALUES(?, ?, 'queued', ?, ?)",
        (stamp, goal.strip(), json.dumps(plan, ensure_ascii=False), stamp),
    )


def steer_mission(db: Database, mission_id: int, text: str) -> str:
    """Leave a note the mission reads before its next step."""
    row = db.one("SELECT status FROM missions WHERE id = ?", (int(mission_id),))
    if row is None:
        raise CompanyError(f"mission #{mission_id} introuvable")
    if row["status"] not in ("queued", "running"):
        raise CompanyError(f"la mission #{mission_id} n'est plus en cours ({row['status']})")
    if not text.strip():
        raise CompanyError("consigne vide")
    db.execute(
        "INSERT INTO mission_notes(mission_id, ts, text) VALUES(?, ?, ?)",
        (int(mission_id), now_iso(), text.strip()[:2000]),
    )
    return "consigne transmise : la mission la lira avant sa prochaine étape"


def take_notes(db: Database, mission_id: int) -> list[str]:
    """The user's new notes for a mission (each is read once)."""
    rows = db.all(
        "SELECT id, text FROM mission_notes WHERE mission_id = ? AND used = 0 ORDER BY id",
        (mission_id,),
    )
    for row in rows:
        db.execute("UPDATE mission_notes SET used = 1 WHERE id = ?", (row["id"],))
    return [r["text"] for r in rows]


def stop_mission(db: Database, mission_id: int) -> str:
    """Cancel a queued mission, or stop a running one after its current step."""
    row = db.one("SELECT status FROM missions WHERE id = ?", (int(mission_id),))
    if row is None:
        raise CompanyError(f"mission #{mission_id} introuvable")
    if row["status"] not in ("queued", "running"):
        raise CompanyError(f"la mission #{mission_id} n'est plus en cours ({row['status']})")
    db.execute(
        "UPDATE missions SET status = 'cancelled', updated_at = ? WHERE id = ?",
        (now_iso(), int(mission_id)),
    )
    task = db.one("SELECT id FROM tasks WHERE mission_id = ?", (int(mission_id),))
    if task is not None:
        db.execute(
            "UPDATE tasks SET status = 'cancelled', updated_at = ? WHERE id = ? "
            "AND status = 'doing'",
            (now_iso(), task["id"]),
        )
    running = "après son étape en cours" if row["status"] == "running" else "tout de suite"
    return f"mission #{mission_id} arrêtée ({running})"
