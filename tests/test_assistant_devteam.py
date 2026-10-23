"""The technical department: worktree, coding agent, tests, commit, PR on approval."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import tools
from spectre.assistant.company import Companies
from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database
from spectre.assistant.devteam import DevError, DevTeam, report, slug, split_command
from spectre.assistant.governance import Gate
from spectre.assistant.missions import MissionEngine
from spectre.assistant.service import AssistantService
from spectre.assistant.trust import Trust
from tests.test_assistant_engines import Rooted
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    folder = tmp_path / "saas"
    folder.mkdir()
    git(folder, "init", "-q", "-b", "main")
    (folder / "check.py").write_text(
        "import pathlib, sys\nsys.exit(0 if pathlib.Path('feature.txt').exists() else 1)\n",
        encoding="utf-8",
    )
    git(folder, "add", "-A")
    git(folder, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return folder


class Coder:
    """Real git and tests; the coding agent writes `feature.txt` on its `works`-th call."""

    def __init__(self, works: int = 1, gh: int = 0) -> None:
        self.works, self.calls, self.gh = works, 0, gh
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> Any:
        self.commands.append(cmd)
        if cmd[0] in ("claude", "codex") or cmd[0].endswith("codex.exe"):
            self.calls += 1
            if self.calls >= self.works:
                Path(kwargs["cwd"], "feature.txt").write_text("ok", encoding="utf-8")
            out = json.dumps({"result": f"essai {self.calls}", "session_id": "s"})
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd[:2] == ["git", "-C"] and "push" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "gh":
            if self.gh:
                return subprocess.CompletedProcess(cmd, 1, "", "gh: not logged in")
            return subprocess.CompletedProcess(cmd, 0, "https://github.com/me/saas/pull/7\n", "")
        return subprocess.run(cmd, **kwargs)


def setup_company(db: Database, root: Path, repo: Path, runner: Any) -> tuple[DevTeam, int]:
    cid = Companies(db).create("Acme")["id"]
    devteam = DevTeam(db, root, runner)
    devteam.configure(cid, str(repo), f"{sys.executable} check.py")
    return devteam, cid


def test_helpers() -> None:
    assert slug("Ajouter l'export CSV !") == "ajouter-l-export-csv" and slug("!!!") == "travail"
    assert split_command("uv run pytest -q") == ["uv", "run", "pytest", "-q"]
    assert split_command('"C:/Program Files/py.exe" t.py') == ["C:/Program Files/py.exe", "t.py"]


def test_configure(tmp_path: Path, repo: Path) -> None:
    db = Database(tmp_path / "a" / "spectre.db")
    cid = Companies(db).create("Acme")["id"]
    devteam = DevTeam(db, tmp_path / "a")
    setup = devteam.configure(cid, str(repo), "uv run pytest -q")
    assert setup["base_branch"] == "main" and Path(setup["repo_path"]) == repo.resolve()
    assert devteam.configure(cid, str(repo), "npm test", "develop")["base_branch"] == "develop"
    for path, command, error in [
        (str(tmp_path), "x", "pas un dépôt git"),
        (str(repo), " ", "commande qui lance"),
        (str(repo), 'pytest "oups', "illisible"),
    ]:
        if error == "illisible" and sys.platform == "win32":
            continue  # Windows splitting keeps unbalanced quotes
        with pytest.raises(DevError, match=error):
            devteam.configure(cid, path, command)
    with pytest.raises(DevError, match="décris"):
        devteam.request(cid, "court")
    other = Companies(db).create("Beta")["id"]
    with pytest.raises(DevError, match="configure d'abord"):
        devteam.request(other, "Un changement assez long")
    with pytest.raises(DevError, match="introuvable"):
        devteam.job(99)


def test_work_ready_then_pr(tmp_path: Path, repo: Path) -> None:
    root = tmp_path / "a"
    db = Database(root / "spectre.db")
    coder = Coder(works=1)
    devteam, cid = setup_company(db, root, repo, coder)
    job, mid = devteam.request(cid, "Ajouter le fichier de fonctionnalité")
    assert json.loads(db.one("SELECT plan FROM missions")["plan"]) == {
        "kind": "code",
        "job": job["id"],
        "company": cid,
    }
    text = devteam.work(job["id"], "sonnet", AssistantConfig(), "Acme")
    done = devteam.job(job["id"])
    assert done["status"] == "ready" and done["tests_ok"] == 1 and "feature.txt" in done["diffstat"]
    assert done["branch"] == f"spectre/{job['id']}-ajouter-le-fichier-de-fonctionnalite"
    assert "prêt : tests au vert" in text and "Rien n'a été poussé" in text
    claude = next(c for c in coder.commands if c[0] == "claude")
    assert claude[claude.index("--effort") + 1] == "medium"  # dev agent on Sonnet thinks harder
    assert "Bash(git diff:*)" in claude and f"Bash({sys.executable} check.py)" in claude
    assert "--tools" in claude and "Read,Edit,Write,Glob,Grep,Bash" in claude
    assert (
        git(repo, "log", "--oneline", done["branch"])
        .splitlines()[0]
        .endswith("Spectre : Ajouter le fichier de fonctionnalité")
    )
    assert "feature.txt" not in git(repo, "ls-files")  # the main branch is untouched
    assert devteam.open_pr(job["id"]) == "PR ouverte : https://github.com/me/saas/pull/7"
    assert devteam.job(job["id"])["status"] == "pr"
    with pytest.raises(DevError, match="rien à proposer"):
        devteam.open_pr(job["id"])
    with pytest.raises(DevError, match="ferme-la"):
        devteam.discard(job["id"])


def test_work_repairs_then_discards(tmp_path: Path, repo: Path) -> None:
    root = tmp_path / "a"
    db = Database(root / "spectre.db")
    coder = Coder(works=2, gh=1)
    devteam, cid = setup_company(db, root, repo, coder)
    job, _ = devteam.request(cid, "Corriger le bug de facturation")
    devteam.work(job["id"], "chatgpt", AssistantConfig(), "Acme")
    assert coder.calls == 2  # failed tests: one repair round
    second = [c for c in coder.commands if "exec" in c]
    assert second and "workspace-write" in second[0]
    assert devteam.job(job["id"])["status"] == "ready"
    with pytest.raises(DevError, match="gh pr create a échoué"):
        devteam.open_pr(job["id"])
    worktree = Path(devteam.job(job["id"])["worktree"])
    assert devteam.discard(job["id"]).startswith(f"travail #{job['id']} abandonné")
    assert not worktree.exists() and devteam.job(job["id"])["branch"] not in git(repo, "branch")
    # tests that never pass, and no change at all
    never = Coder(works=99)
    devteam.runner = never
    failing, _ = devteam.request(cid, "Un changement qui échoue")
    (repo / "extra.txt").write_text("x", encoding="utf-8")
    text = devteam.work(failing["id"], "opus", AssistantConfig(), "Acme")
    assert devteam.job(failing["id"])["status"] == "no_change" and "aucun changement" in text


def test_tests_and_agent_problems(tmp_path: Path, repo: Path) -> None:
    root = tmp_path / "a"
    db = Database(root / "spectre.db")

    def broken(cmd: list[str], **kwargs: Any) -> Any:
        if cmd[0] == "claude":
            raise subprocess.TimeoutExpired(cmd, 1)
        if cmd[0] == sys.executable:
            raise OSError("introuvable")
        return subprocess.run(cmd, **kwargs)

    devteam, cid = setup_company(db, root, repo, broken)
    job, _ = devteam.request(cid, "Un changement impossible")
    devteam.work(job["id"], "haiku", AssistantConfig(), "Acme")
    done = devteam.job(job["id"])
    assert (
        "n'a pas pu travailler" in done["notes"] and "impossible de lancer" in done["test_output"]
    )
    slow = lambda cmd, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd, 1))  # noqa: E731
    assert DevTeam(db, root, slow).run_tests(done, "x") == (
        False,
        "tests trop longs (plus de 15 min)",
    )
    with pytest.raises(DevError, match="git worktree"):
        devteam.work(job["id"], "haiku", AssistantConfig(), "Acme")  # branch exists already
    devteam.failed(job["id"], "boom")
    assert devteam.job(job["id"])["status"] == "failed"
    assert report(
        done | {"status": "x", "notes": "", "test_output": ""}, {"test_command": "t"}
    ).startswith("# Développement")


def test_code_mission(tmp_path: Path, repo: Path) -> None:
    root = tmp_path / "a"
    db = Database(root / "spectre.db")
    devteam, cid = setup_company(db, root, repo, Coder())
    Companies(db).set_post(cid, "produit", "Kyra")
    job, mid = devteam.request(cid, "Ajouter la fonctionnalité")
    notes: list[Any] = []
    engine = MissionEngine(db, Rooted(root), lambda *a: notes.append(a))  # type: ignore[arg-type]
    seen: list[str] = []

    def work(self: DevTeam, job_id: int, engine_ref: str, config: Any, company: str) -> str:
        seen.append(engine_ref)
        db.execute("UPDATE dev_jobs SET status = 'ready', tests_ok = 1 WHERE id = ?", (job_id,))
        return "# rapport"

    import spectre.assistant.devteam as module

    original = module.DevTeam.work
    module.DevTeam.work = work  # type: ignore[method-assign]
    try:
        engine.run_next()
    finally:
        module.DevTeam.work = original  # type: ignore[method-assign]
    assert seen == ["chatgpt"] and notes[-1][1] == f"Code prêt (#{mid})"
    assert Trust(db).dossier("chatgpt")["counts"] == {"step_ok": 1}
    assert db.one("SELECT role FROM usage_ledger")["role"] == "développement"
    # a failure marks the job
    second, mid2 = devteam.request(cid, "Encore un changement")
    module.DevTeam.work = lambda *a: (_ for _ in ()).throw(DevError("boom"))  # type: ignore[method-assign]
    try:
        engine.run_next()
    finally:
        module.DevTeam.work = original  # type: ignore[method-assign]
    assert devteam.job(second["id"])["status"] == "failed"


def test_dev_tools(tmp_path: Path, repo: Path) -> None:
    root = tmp_path / "a"
    db = Database(root / "spectre.db")
    Companies(db).create("Acme")
    gate, ctx = Gate(db), tools.make_context(db, root, [str(tmp_path)])
    run = lambda tool, **args: tools.execute(gate, ctx, tool, args)  # noqa: E731
    assert run("set_dev_repo", company="acme", path=str(repo), test_command="pytest").startswith(
        "EN ATTENTE"
    )
    tools.run_approved(gate, ctx, 1)
    assert run("list_dev_jobs", company="acme") == "aucun travail de développement"
    assert run("dev_task", company="acme", request="Ajouter l'export CSV").startswith(
        "travail #1 confié"
    )
    assert run("list_dev_jobs").startswith("#1 [queued] Ajouter l'export CSV")
    assert run("open_pr", job_id=1).startswith("EN ATTENTE")
    assert run("discard_dev_job", job_id=1).startswith("EN ATTENTE")
    assert run("dev_task", company="acme", request="x").startswith("ÉCHEC : décris")


def test_dev_api(
    api: Client,  # noqa: F811
    service: AssistantService,  # noqa: F811
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service.ctx.allowed_roots.append(repo.parent)
    api.json("POST", "/api/assistant/company", {"name": "Acme"})
    assert api.json("GET", "/api/assistant/company/1/dev")[1] == {"config": None, "jobs": []}
    status, setup = api.json(
        "POST", "/api/assistant/company/1/dev/config", {"path": str(repo), "test_command": "pytest"}
    )
    assert status == 200 and setup["base_branch"] == "main"
    assert api.json("POST", "/api/assistant/company/1/dev", {"request": "Ajouter l'export CSV"})[1][
        "result"
    ].startswith("travail #1")
    import spectre.assistant.devteam as module

    monkeypatch.setattr(module.DevTeam, "open_pr", lambda self, j: "PR ouverte : u")
    monkeypatch.setattr(module.DevTeam, "discard", lambda self, j: "abandonné")
    assert api.json("POST", "/api/assistant/dev/1/pr", {})[1]["result"] == "PR ouverte : u"
    assert api.json("POST", "/api/assistant/dev/1/discard", {})[1]["result"] == "abandonné"
    assert api.json("POST", "/api/assistant/dev/1/explode", {})[0] == 404
    status, body = api.json(
        "POST",
        "/api/assistant/company/1/dev/config",
        {"path": str(repo.parent / "nope"), "test_command": "x"},
    )
    assert status == 400
