"""The code an agent writes, live: the « View » button of the team cards and the task board.

Every file an agent writes goes through the gate (`write_file`), so the activity rows already
say who wrote what, when, for which mission: the viewer lists those files, newest first, and
reads each one from disk as it is now (an agent rewriting a file is seen at the next poll).
The technical department codes in a git worktree with its own tools: its changed files and
diff are read from git. Nothing is written and no model is called.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from spectre.assistant.db import Database

WRITES = ("write_file", "move_file")
MAX_FILES = 40
MAX_BYTES = 200_000  # a file larger than this is shown cut
MAX_DIFF = 120_000
LANGS = {
    ".py": "python",
    ".rs": "rust",
    ".js": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".sql": "sql",
    ".sh": "bash",
    ".ps1": "powershell",
    ".sol": "solidity",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".svg": "xml",
    ".xml": "xml",
    ".typ": "typst",
    ".txt": "text",
}


def language(path: str) -> str:
    return LANGS.get(Path(path).suffix.lower(), "text")


def _detail(raw: str) -> dict[str, Any]:
    try:
        found = json.loads(raw or "{}")
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def files(
    db: Database,
    *,
    agent: str | None = None,
    mission: int | None = None,
    since_id: int = 0,
) -> list[dict[str, Any]]:
    """The files written by an agent or for a mission, newest first (one entry per path)."""
    where = ["kind = 'tool'", f"title IN ({','.join('?' * len(WRITES))})", "id > ?"]
    params: list[Any] = [*WRITES, since_id]
    if agent is not None:
        where.append("agent = ?")
        params.append(agent)
    if mission is not None:
        where.append("mission_id = ?")
        params.append(mission)
    rows = db.all(
        f"SELECT id, ts, agent, mission_id, title, detail, status FROM activity "  # noqa: S608
        f"WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT 400",
        tuple(params),
    )
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        detail = _detail(row["detail"])
        raw = detail.get("args")
        args: dict[str, Any] = raw if isinstance(raw, dict) else {}
        path = str(args.get("destination") or args.get("path") or detail.get("target") or "")
        if not path or path in seen or row["status"] == "fail":
            continue
        seen[path] = {
            "path": path,
            "name": Path(path).name,
            "lang": language(path),
            "ts": row["ts"],
            "row": row["id"],
            "agent": row["agent"],
            "mission": row["mission_id"],
            "writing": row["status"] == "running",
            "edits": 1,
        }
        if len(seen) >= MAX_FILES:
            break
    for row in rows:  # how many times each file was written (a file rewritten often is hot)
        args = _detail(row["detail"]).get("args") or {}
        path = str(args.get("path") or "") if isinstance(args, dict) else ""
        if path in seen and row["id"] != seen[path]["row"]:
            seen[path]["edits"] += 1
    return list(seen.values())


def read(path: str, known: list[dict[str, Any]]) -> dict[str, Any]:
    """One file as it is now; only a file the viewer listed (written by an agent)."""
    if path not in {f["path"] for f in known}:
        raise KeyError(path)
    file = Path(path)
    if not file.is_file():
        return {"path": path, "lang": language(path), "text": "", "missing": True, "size": 0}
    size = file.stat().st_size
    with file.open("rb") as handle:
        data = handle.read(MAX_BYTES)
    return {
        "path": path,
        "lang": language(path),
        "text": data.decode("utf-8", errors="replace"),
        "size": size,
        "cut": size > MAX_BYTES,
        "missing": False,
        "mtime": file.stat().st_mtime,
    }


def _git(worktree: str, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", worktree, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def dev_jobs(db: Database, limit: int = 3) -> list[dict[str, Any]]:
    """The technical department's current worktrees: changed files and the live diff."""
    found = []
    for job in db.all(
        "SELECT id, company_id, request, status, branch, worktree FROM dev_jobs "
        "WHERE worktree != '' AND status NOT IN ('discarded', 'failed') ORDER BY id DESC LIMIT ?",
        (limit,),
    ):
        if not Path(job["worktree"]).is_dir():
            continue
        status = _git(job["worktree"], "status", "--porcelain")
        diff = _git(job["worktree"], "diff", "HEAD")
        if not diff and job["status"] != "working":  # committed: the branch's own change
            diff = _git(job["worktree"], "show", "--format=", "HEAD")
        found.append(
            {
                "id": job["id"],
                "request": job["request"],
                "status": job["status"],
                "branch": job["branch"],
                "worktree": job["worktree"],
                "changed": [line[3:] for line in status.splitlines() if len(line) > 3],
                "diff": diff[:MAX_DIFF],
            }
        )
    return found


def live(db: Database, agent: str, since: int = 0) -> dict[str, Any]:
    """What the viewer polls: the agent's files, what it does right now, its dev worktrees."""
    now = db.one(
        "SELECT id, ts, kind, title, detail, status, mission_id FROM activity WHERE agent = ? "
        "ORDER BY id DESC LIMIT 1",
        (agent,),
    )
    doing = ""
    if now is not None:
        target = _detail(now["detail"]).get("target", "")
        doing = f"{now['title']} {target}".strip() if now["kind"] == "tool" else now["title"]
    last = db.one("SELECT MAX(id) AS id FROM activity")
    return {
        "agent": agent,
        "files": files(db, agent=agent),
        "doing": doing,
        "doing_status": now["status"] if now else "",
        "doing_ts": now["ts"] if now else "",
        "mission": now["mission_id"] if now else None,
        "dev": dev_jobs(db) if agent in _dev_agents(db) else [],
        "last": (last or {}).get("id") or 0,
        "changed": bool(last and (last.get("id") or 0) > since),
    }


def _dev_agents(db: Database) -> set[str]:
    """Who may be coding in a worktree: the agents on a « produit » post, or any by default."""
    posts = {r["agent"] for r in db.all("SELECT agent FROM posts WHERE department = 'produit'")}
    return (posts - {""}) | {"opus", "sonnet", "chatgpt"}
