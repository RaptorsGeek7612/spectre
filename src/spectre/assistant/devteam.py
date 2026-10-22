"""The technical department: code changes in an isolated branch, tests, then a PR you approve.

For a company with a code repository set up (`dev_config`: path, test command, base branch):
1. a git worktree on a new branch `spectre/<job>-<slug>` is created outside the repository;
2. a coding agent works there: Claude Code with only Read/Edit/Write/Glob/Grep and Bash limited
   to `git status|diff|log` and the test command (edits stay in the worktree), or Codex in its
   workspace-write sandbox;
3. the test command runs; on failure the agent gets one repair round with the output;
4. the work is committed on the branch; nothing is pushed.
Opening the PR (push + `gh pr create`) is an external action: it always needs approval.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spectre.assistant.db import Database, now_iso

TEST_TIMEOUT_S = 900
AGENT_TIMEOUT_S = 1800
OUTPUT_TAIL = 6000
Runner = Callable[..., Any]  # subprocess.run-compatible

CODER = """\
Tu es le département technique de l'entreprise « {company} ». Tu travailles dans une copie \
isolée de son dépôt (branche {branch}) : modifie le code pour réaliser la demande, proprement, \
dans le style du code existant, avec des tests si le projet en a. Tu peux lire et modifier les \
fichiers de ce dossier, et lancer les tests avec exactement cette commande, seule (sans cd \
ni autre commande autour) :
{tests}
Ne pousse rien, ne touche à rien en dehors de ce dossier. Termine par un compte rendu \
bref : ce que tu as changé et pourquoi."""


class DevError(ValueError):
    """A refused request (the message is for the user)."""


def slug(text: str) -> str:
    import unicodedata

    plain = "".join(
        c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:40] or "travail"


def split_command(command: str) -> list[str]:
    """Arguments of a command line; on Windows, quotes around a path are removed."""
    if os.name != "nt":
        return shlex.split(command)
    return [
        part[1:-1] if len(part) > 1 and part[0] == part[-1] == '"' else part
        for part in shlex.split(command, posix=False)
    ]


class DevTeam:
    def __init__(self, db: Database, root: Path, runner: Runner = subprocess.run) -> None:
        self.db = db
        self.root = root
        self.runner = runner

    # ---- configuration ------------------------------------------------------------------------

    def config(self, company_id: int) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM dev_config WHERE company_id = ?", (company_id,))

    def configure(
        self, company_id: int, path: str, test_command: str, base_branch: str = ""
    ) -> dict[str, Any]:
        repo = Path(path).expanduser()
        if not (repo / ".git").exists():
            raise DevError(f"« {path} » n'est pas un dépôt git")
        if not test_command.strip():
            raise DevError("donne la commande qui lance les tests (ex. uv run pytest -q)")
        try:
            split_command(test_command)
        except ValueError as exc:
            raise DevError(f"commande de tests illisible : {exc}") from exc
        base = base_branch.strip() or self.git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
        self.db.execute(
            "INSERT INTO dev_config(company_id, repo_path, test_command, base_branch) "
            "VALUES(?, ?, ?, ?) ON CONFLICT(company_id) DO UPDATE SET "
            "repo_path = excluded.repo_path, "
            "test_command = excluded.test_command, base_branch = excluded.base_branch",
            (company_id, str(repo.resolve()), test_command.strip(), base),
        )
        found = self.config(company_id)
        assert found is not None
        return found

    # ---- jobs ------------------------------------------------------------------------------------

    def jobs(self, company_id: int) -> list[dict[str, Any]]:
        return self.db.all(
            "SELECT * FROM dev_jobs WHERE company_id = ? ORDER BY id DESC LIMIT 30", (company_id,)
        )

    def job(self, job_id: int) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM dev_jobs WHERE id = ?", (int(job_id),))
        if row is None:
            raise DevError(f"travail #{job_id} introuvable")
        return row

    def request(self, company_id: int, request: str) -> tuple[dict[str, Any], int]:
        """Record the request and queue its mission; (job, mission id)."""
        from spectre.assistant.company import enqueue

        if self.config(company_id) is None:
            raise DevError(
                "configure d'abord le dépôt de l'entreprise (chemin et commande de tests)"
            )
        if len(request.strip()) < 10:
            raise DevError("décris le changement à faire en une ou deux phrases")
        jid = self.db.execute(
            "INSERT INTO dev_jobs(company_id, request, status, created_at) "
            "VALUES(?, ?, 'queued', ?)",
            (company_id, request.strip()[:4000], now_iso()),
        )
        mid = enqueue(
            self.db,
            f"Développement : {request.strip()[:200]}",
            {"kind": "code", "job": jid, "company": company_id},
        )
        self.db.execute("UPDATE dev_jobs SET mission_id = ? WHERE id = ?", (mid, jid))
        return self.job(jid), mid

    def git(self, repo: Path, *args: str, check: bool = True) -> str:
        proc = self.runner(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if check and proc.returncode != 0:
            raise DevError(
                f"git {' '.join(args[:2])} a échoué : {(proc.stderr or proc.stdout).strip()[:300]}"
            )
        return str(proc.stdout or "")

    def run_tests(self, job: dict[str, Any], command: str) -> tuple[bool, str]:
        try:
            proc = self.runner(
                split_command(command),
                cwd=job["worktree"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TEST_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, f"tests trop longs (plus de {TEST_TIMEOUT_S // 60} min)"
        except OSError as exc:
            return False, f"impossible de lancer les tests : {exc}"
        output = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
        return proc.returncode == 0, output[-OUTPUT_TAIL:]

    def coder_command(self, engine: str, system: str, tests: str, config: Any) -> list[str]:
        """The coding agent's command line: Claude Code with a narrow tool set, or Codex."""
        from spectre.assistant.brain import effort_flag
        from spectre.config import ASSISTANT_MODELS

        if engine == "chatgpt":
            from spectre.assistant.codex import find_codex, toml

            return [
                find_codex(config.codex_bin),
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "--sandbox",
                "workspace-write",
                "--color",
                "never",
                "-c",
                'approval_policy="never"',
                "-c",
                f"developer_instructions={toml(system)}",
                "-",
            ]
        model = engine if engine in ("opus", "sonnet", "haiku") else "sonnet"
        return [
            config.claude_bin,
            "-p",
            "--output-format",
            "json",
            "--model",
            ASSISTANT_MODELS[model],
            *effort_flag(config, model),
            "--system-prompt",
            system,
            "--permission-mode",
            "dontAsk",
            "--setting-sources",
            "local",
            "--tools",
            "Read,Edit,Write,Glob,Grep,Bash",
            "--allowedTools",
            "Read",
            "Edit",
            "Write",
            "Glob",
            "Grep",
            "Bash(git status:*)",
            "Bash(git diff:*)",
            "Bash(git log:*)",
            f"Bash({tests})",
            f"Bash({tests}:*)",
        ]

    def work(self, job_id: int, engine: str, config: Any, company: str) -> str:
        """The mission: worktree, coding, tests (one repair round), commit; returns the report."""
        from spectre.assistant.brain import parse_reply

        job = self.job(job_id)
        setup = self.config(job["company_id"])
        if setup is None:
            raise DevError("le dépôt de l'entreprise n'est plus configuré")
        repo = Path(setup["repo_path"])
        branch = f"spectre/{job_id}-{slug(job['request'])}"
        worktree = self.root / "worktrees" / f"{job['company_id']}-{job_id}"
        worktree.parent.mkdir(parents=True, exist_ok=True)
        self.git(repo, "worktree", "add", "-b", branch, str(worktree), setup["base_branch"])
        self.db.execute(
            "UPDATE dev_jobs SET status = 'working', branch = ?, worktree = ? WHERE id = ?",
            (branch, str(worktree), job_id),
        )
        job = self.job(job_id)
        system = CODER.format(company=company, branch=branch, tests=setup["test_command"])
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY")
        }
        notes = []
        ok, output = False, ""
        for attempt in range(2):
            prompt = (
                job["request"]
                if not attempt
                else (
                    f"{job['request']}\n\nLes tests échouent encore :\n{output[-3000:]}\n\nCorrige."
                )
            )
            try:
                proc = self.runner(
                    self.coder_command(engine, system, setup["test_command"], config),
                    input=prompt,
                    cwd=str(worktree),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=AGENT_TIMEOUT_S,
                    env=env,
                    check=False,
                )
                reply = (
                    parse_reply(proc.stdout or "", proc.stderr or "")
                    if engine != "chatgpt"
                    else None
                )
                notes.append(reply.text if reply else (proc.stdout or "").strip()[-2000:])
            except (subprocess.TimeoutExpired, OSError) as exc:
                notes.append(f"l'agent n'a pas pu travailler : {exc}")
            ok, output = self.run_tests(job, setup["test_command"])
            if ok:
                break
        self.git(worktree, "add", "-A")
        changed = self.git(worktree, "diff", "--cached", "--stat").strip()
        if changed:
            self.git(
                worktree,
                "-c",
                "user.name=Spectre",
                "-c",
                "user.email=spectre@localhost",
                "commit",
                "-m",
                f"Spectre : {job['request'][:72]}",
            )
        status = "ready" if ok and changed else "tests_failed" if changed else "no_change"
        self.db.execute(
            "UPDATE dev_jobs SET status = ?, tests_ok = ?, test_output = ?, diffstat = ?, "
            "notes = ? WHERE id = ?",
            (status, int(ok), output, changed, "\n\n".join(notes)[-8000:], job_id),
        )
        return report(self.job(job_id), setup)

    def open_pr(self, job_id: int) -> str:
        """Push the branch and open the PR (an external action: approved before this runs)."""
        job = self.job(job_id)
        if job["status"] not in ("ready", "tests_failed"):
            raise DevError(f"le travail #{job_id} n'a rien à proposer ({job['status']})")
        setup = self.config(job["company_id"])
        assert setup is not None
        repo = Path(setup["repo_path"])
        self.git(repo, "push", "-u", "origin", job["branch"])
        title = f"Spectre : {job['request'][:80]}"
        body = (
            f"{job['request']}\n\nTests : {'OK' if job['tests_ok'] else 'EN ÉCHEC'}\n\n"
            f"```\n{job['diffstat']}\n```\n\nPréparé par le département technique de Spectre."
        )
        proc = self.runner(
            [
                "gh",
                "pr",
                "create",
                "--base",
                setup["base_branch"],
                "--head",
                job["branch"],
                "--title",
                title,
                "--body",
                body,
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if proc.returncode != 0:
            raise DevError(f"gh pr create a échoué : {(proc.stderr or proc.stdout).strip()[:300]}")
        url = (proc.stdout or "").strip().splitlines()[-1]
        self.db.execute("UPDATE dev_jobs SET status = 'pr', pr_url = ? WHERE id = ?", (url, job_id))
        return f"PR ouverte : {url}"

    def discard(self, job_id: int) -> str:
        """Remove the worktree and its branch (nothing was pushed)."""
        job = self.job(job_id)
        if job["status"] == "pr":
            raise DevError("la PR est ouverte : ferme-la sur GitHub plutôt")
        setup = self.config(job["company_id"])
        if setup and job["worktree"]:
            repo = Path(setup["repo_path"])
            self.git(repo, "worktree", "remove", "--force", job["worktree"], check=False)
            self.git(repo, "branch", "-D", job["branch"], check=False)
        self.db.execute("UPDATE dev_jobs SET status = 'discarded' WHERE id = ?", (job_id,))
        return f"travail #{job_id} abandonné (branche et copie supprimées)"

    def failed(self, job_id: int, reason: str) -> None:
        self.db.execute(
            "UPDATE dev_jobs SET status = 'failed', notes = ? WHERE id = ?", (reason[:2000], job_id)
        )


def report(job: dict[str, Any], setup: dict[str, Any]) -> str:
    verdict = {
        "ready": "prêt : tests au vert",
        "tests_failed": "tests EN ÉCHEC",
        "no_change": "aucun changement",
    }
    lines = [
        f"# Développement #{job['id']} : {verdict.get(job['status'], job['status'])}",
        "",
        f"**Demande** : {job['request']}",
        f"**Branche** : `{job['branch']}` (copie isolée : {job['worktree']})",
        f"**Tests** : `{setup['test_command']}`",
        "",
        "## Changements",
        "```",
        job["diffstat"] or "(aucun)",
        "```",
    ]
    if job["notes"]:
        lines += ["", "## Compte rendu de l'agent", job["notes"][-3000:]]
    if job["test_output"] and not job["tests_ok"]:
        lines += ["", "## Sortie des tests", "```", job["test_output"][-3000:], "```"]
    if job["status"] in ("ready", "tests_failed"):
        lines += [
            "",
            "Rien n'a été poussé. Ouvre la PR depuis la vue Entreprise (avec ton accord).",
        ]
    return "\n".join(lines) + "\n"
