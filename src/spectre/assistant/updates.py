"""Keeping the tools up to date: Spectre checks every week what can be updated on this PC
(winget packages, uv tools), tells the user, and updates only what the user approves.

Checking only reads (`winget upgrade` lists, `uv tool list --outdated`). Updating installs
software: it always waits for the user's approval, takes the stable release the source offers,
and leaves out what other programs depend on at an exact version (Python itself).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timedelta
from typing import Any

from spectre.assistant.actions import ActionContext, ActionError

CHECK_EVERY = timedelta(days=7)
CHECK_KV = "tool_updates_checked"
TIMEOUT_S = 300
UPGRADE_TIMEOUT_S = 1800
# other programs depend on these at an exact version (virtual environments, labs)
HELD = (re.compile(r"Python\.Python\.[\d.]+"),)
# not a stable release (the stable one is preferred, see spectre-amelioration)
UNSTABLE = re.compile(r"(nightly|b[eê]ta|preview|canary|insider|\brc\d*\b|alpha|\bdev\b)", re.I)
WINGET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{1,100}")
UV_TOOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")
UV_OUTDATED = re.compile(r"^(\S+) v(\S+) \[latest: (\S+)\]")


def _run(runner: Any, command: list[str], timeout: float) -> str:
    try:
        proc = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout or ""


def parse_winget(text: str) -> list[dict[str, str]]:
    """The rows of `winget upgrade` (a table whose columns follow its header)."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if index and re.fullmatch(r"-{20,}", line.strip()):
            header = lines[index - 1].split("\r")[-1]
            starts = [m.start() for m in re.finditer(r"(?:^|(?<=\s))\S", header)]
            rows = []
            for row in lines[index + 1 :]:
                row = row.rstrip()
                if len(starts) < 4 or len(row) <= starts[1]:
                    continue  # the summary lines under the table
                cells = [
                    row[a:b].strip()
                    for a, b in zip(starts, [*starts[1:], len(row) + 1], strict=False)
                ]
                if len(cells) >= 4 and WINGET_ID.fullmatch(cells[1]) and all(cells[2:4]):
                    rows.append(
                        {
                            "name": cells[0],
                            "id": cells[1],
                            "version": cells[2],
                            "available": cells[3],
                            "source": cells[4] if len(cells) > 4 else "",
                            "manager": "winget",
                        }
                    )
            return rows
    return []


def parse_uv(text: str) -> list[dict[str, str]]:
    found = []
    for line in text.splitlines():
        match = UV_OUTDATED.match(line.strip())
        if match:
            name, version, latest = match.groups()
            found.append(
                {"name": name, "id": name, "version": version, "available": latest, "manager": "uv"}
            )
    return found


def held(item: dict[str, str]) -> bool:
    return any(pattern.fullmatch(item["id"]) for pattern in HELD)


def unstable(item: dict[str, str]) -> bool:
    return bool(UNSTABLE.search(f"{item['name']} {item['id']} {item['available']}"))


def available(runner: Any = None) -> list[dict[str, str]]:
    """What can be updated on this PC (reads only)."""
    run = runner or subprocess.run
    found: list[dict[str, str]] = []
    winget = shutil.which("winget")
    if winget:
        found += parse_winget(
            _run(run, [winget, "upgrade", "--disable-interactivity", "--accept-source-agreements"],
                 TIMEOUT_S)
        )  # fmt: skip
    uv = shutil.which("uv")
    if uv:
        found += parse_uv(_run(run, [uv, "tool", "list", "--outdated"], TIMEOUT_S))
    return found


def summary(items: list[dict[str, str]]) -> str:
    if not items:
        return "tous les outils sont à jour"
    lines = [
        f"- {i['name']} ({i['manager']} : {i['id']}) {i['version']} → {i['available']}"
        + (" — tenu à sa version (d'autres programmes en dépendent)" if held(i) else "")
        + (" — version non stable, à éviter" if unstable(i) else "")
        for i in items
    ]
    return f"{len(items)} mise(s) à jour disponible(s) :\n" + "\n".join(lines)


def listing(ctx: ActionContext) -> str:
    return summary(available(ctx.runner))


def upgrade(ctx: ActionContext, which: str) -> str:
    """Update the listed tools (« tout » = everything not held), after the user's approval."""
    items = available(ctx.runner)
    wanted = {w.strip().lower() for w in re.split(r"[,;\s]+", which) if w.strip()}
    if not wanted:
        raise ActionError("précise ce qu'il faut mettre à jour (identifiants, ou « tout »)")
    if "tout" in wanted:
        chosen = [i for i in items if not held(i) and not unstable(i)]
    else:
        chosen = [i for i in items if i["id"].lower() in wanted or i["name"].lower() in wanted]
        unknown = wanted - {i["id"].lower() for i in chosen} - {i["name"].lower() for i in chosen}
        if unknown:
            raise ActionError(f"pas de mise à jour disponible pour : {', '.join(sorted(unknown))}")
        if any(held(i) for i in chosen):
            raise ActionError(
                "Python est tenu à sa version (les environnements de Spectre et des labos en "
                "dépendent) : à mettre à jour à la main, en connaissance de cause"
            )
    if not chosen:
        return "rien à mettre à jour"
    run = ctx.runner or subprocess.run
    done: list[str] = []
    failed: list[str] = []
    for item in chosen:
        if item["manager"] == "winget":
            command = [
                shutil.which("winget") or "winget", "upgrade", "--id", item["id"], "--exact",
                "--silent", "--disable-interactivity", "--accept-source-agreements",
                "--accept-package-agreements",
            ]  # fmt: skip
        else:
            if not UV_TOOL.fullmatch(item["id"]):
                failed.append(item["name"])
                continue
            command = [shutil.which("uv") or "uv", "tool", "upgrade", item["id"]]
        try:
            proc = run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=UPGRADE_TIMEOUT_S,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            ok = proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        (done if ok else failed).append(
            f"{item['name']} {item['available']}" if ok else item["name"]
        )
    text = f"mis à jour : {', '.join(done) or 'rien'}"
    if failed:
        text += f" ; échec : {', '.join(failed)} (à réessayer ou à faire à la main)"
    return text


def due(last: str, now: datetime) -> bool:
    try:
        return now - datetime.fromisoformat(last) >= CHECK_EVERY
    except ValueError:
        return True
