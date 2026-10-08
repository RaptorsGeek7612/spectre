"""JSON-file persistence for runs ("plates"), settings and presets.

Everything lives under one state directory (default `~/.spectre/webui`, override with
`SPECTRE_WEBUI_STATE_DIR`). Writes are atomic (temp file + replace) and serialised by a lock.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spectre.config import WEB_PRESETS

STATE_DIR_ENV = "SPECTRE_WEBUI_STATE_DIR"

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "dark",  # dark | light | system
    "font_size": "medium",  # small | medium | large
    "send_key": "ctrl-enter",  # ctrl-enter | enter
    "show_costs": True,
    "notifications": False,
    "language": "fr",  # fr | en
    "preset": "Standard",
    "demo": False,
}

_EDITABLE = {"title", "pinned", "archived", "project", "tags"}
_SETTING_TYPES: dict[str, type] = {key: type(value) for key, value in DEFAULT_SETTINGS.items()}


def default_state_dir() -> Path:
    """`SPECTRE_WEBUI_STATE_DIR` or `~/.spectre/webui`."""
    raw = os.environ.get(STATE_DIR_ENV, "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".spectre" / "webui"


def now_iso() -> str:
    """Current UTC time as ISO 8601 (seconds)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def title_from(request: str) -> str:
    """Run title: first line of the request, at most 60 characters."""
    line = request.strip().splitlines()[0] if request.strip() else "Plaque sans titre"
    return line if len(line) <= 60 else line[:59].rstrip() + "…"


class Store:
    """Runs, settings and presets in `root`."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_state_dir()
        self.runs_dir = self.root / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ---- low level -------------------------------------------------------------------------

    def _read(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _write(self, path: Path, data: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _run_path(self, run_id: str) -> Path:
        if not run_id.isalnum():
            raise KeyError(run_id)
        return self.runs_dir / f"{run_id}.json"

    # ---- runs ------------------------------------------------------------------------------

    def _next_number(self) -> int:
        counter = self.root / "counter.json"
        number = int(self._read(counter, {"next": 1}).get("next", 1))
        self._write(counter, {"next": number + 1})
        return number

    def create_run(
        self, request: str, *, demo: bool, preset: str, overrides: Mapping[str, str]
    ) -> dict[str, Any]:
        """Create and save a new run in the `running` state."""
        with self._lock:
            stamp = now_iso()
            run: dict[str, Any] = {
                "id": secrets.token_hex(8),
                "number": self._next_number(),
                "title": title_from(request),
                "request": request.strip(),
                "created_at": stamp,
                "updated_at": stamp,
                "status": "running",
                "demo": demo,
                "preset": preset,
                "overrides": dict(overrides),
                "pinned": False,
                "archived": False,
                "project": "",
                "tags": [],
                "brief": "",
                "draft": "",
                "final_text": "",
                "usage": [],
                "total_cost_usd": None,
                "durations": {},
                "error": None,
                "error_agent": None,
            }
            self._write(self._run_path(run["id"]), run)
            return run

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Return a run, or raise KeyError."""
        data = self._read(self._run_path(run_id), None)
        if not isinstance(data, dict):
            raise KeyError(run_id)
        return data

    def save_run(self, run: dict[str, Any]) -> dict[str, Any]:
        """Persist `run` (updates `updated_at`)."""
        with self._lock:
            run["updated_at"] = now_iso()
            self._write(self._run_path(run["id"]), run)
            return run

    def update_run(self, run_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        """Apply user edits (title, pinned, archived, project, tags) to a run."""
        with self._lock:
            run = self.get_run(run_id)
            for key, value in changes.items():
                if key not in _EDITABLE:
                    raise ValueError(f"champ non modifiable : {key}")
                if key in ("pinned", "archived"):
                    run[key] = bool(value)
                elif key == "tags":
                    if not isinstance(value, list):
                        raise ValueError("tags doit être une liste")
                    run[key] = sorted(
                        {str(tag).strip().lstrip("#") for tag in value if str(tag).strip()}
                    )
                else:
                    text = str(value).strip()
                    if key == "title" and not text:
                        raise ValueError("le titre ne peut pas être vide")
                    run[key] = text[:120]
            return self.save_run(run)

    def delete_run(self, run_id: str) -> None:
        """Delete a run, or raise KeyError."""
        with self._lock:
            path = self._run_path(run_id)
            if not path.exists():
                raise KeyError(run_id)
            path.unlink()

    def duplicate_run(self, run_id: str) -> dict[str, Any]:
        """Copy a finished run under a new id and number."""
        with self._lock:
            source = self.get_run(run_id)
            copy = dict(source)
            copy["id"] = secrets.token_hex(8)
            copy["number"] = self._next_number()
            copy["title"] = f"{source['title']} (copie)"[:120]
            copy["pinned"] = False
            copy["created_at"] = now_iso()
            return self.save_run(copy)

    def list_runs(self, *, query: str = "", archived: bool = False) -> list[dict[str, Any]]:
        """Run summaries, pinned first then newest first; `query` searches title and text."""
        needle = query.strip().lower()
        summaries: list[dict[str, Any]] = []
        for path in self.runs_dir.glob("*.json"):
            run = self._read(path, None)
            if not isinstance(run, dict) or bool(run.get("archived")) != archived:
                continue
            if needle:
                haystack = (
                    " ".join(
                        str(run.get(key, ""))
                        for key in ("title", "request", "final_text", "project")
                    ).lower()
                    + " "
                    + " ".join(run.get("tags", [])).lower()
                )
                if needle.lstrip("#") not in haystack:
                    continue
            summaries.append(
                {
                    key: run.get(key)
                    for key in (
                        "id",
                        "number",
                        "title",
                        "created_at",
                        "status",
                        "demo",
                        "pinned",
                        "archived",
                        "project",
                        "tags",
                        "total_cost_usd",
                    )
                }
            )
        pinned = [r for r in summaries if r["pinned"]]
        others = [r for r in summaries if not r["pinned"]]
        pinned.sort(key=lambda r: r["created_at"] or "", reverse=True)
        others.sort(key=lambda r: r["created_at"] or "", reverse=True)
        return pinned + others

    def import_runs(self, runs: list[Any]) -> int:
        """Import runs exported as JSON (new ids and numbers); return how many were added."""
        added = 0
        with self._lock:
            for item in runs:
                if not isinstance(item, dict) or not str(item.get("request", "")).strip():
                    continue
                run = self.create_run(
                    str(item["request"]),
                    demo=bool(item.get("demo")),
                    preset=str(item.get("preset", "Standard")),
                    overrides={},
                )
                for key in ("brief", "draft", "final_text", "error", "error_agent"):
                    if item.get(key) is not None:
                        run[key] = str(item[key])
                run["usage"] = item.get("usage") if isinstance(item.get("usage"), list) else []
                run["total_cost_usd"] = item.get("total_cost_usd")
                run["status"] = str(item.get("status", "done"))
                run["title"] = str(item.get("title") or run["title"])[:120]
                run["tags"] = [str(t) for t in item.get("tags", []) if isinstance(t, str)]
                run["project"] = str(item.get("project", ""))[:120]
                self.save_run(run)
                added += 1
        return added

    def clear_runs(self) -> int:
        """Delete every run; return how many were removed."""
        with self._lock:
            paths = list(self.runs_dir.glob("*.json"))
            for path in paths:
                path.unlink()
            return len(paths)

    def mark_interrupted(self) -> None:
        """Runs left `running` by a previous server process become `cancelled`."""
        for path in self.runs_dir.glob("*.json"):
            run = self._read(path, None)
            if isinstance(run, dict) and run.get("status") == "running":
                run["status"] = "cancelled"
                run["error"] = "interrompue (serveur arrêté)"
                self._write(path, run)

    # ---- settings and presets --------------------------------------------------------------

    def get_settings(self) -> dict[str, Any]:
        """Saved settings merged over the defaults."""
        saved = self._read(self.root / "settings.json", {})
        settings = dict(DEFAULT_SETTINGS)
        if isinstance(saved, dict):
            settings.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
        return settings

    def update_settings(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and save settings changes."""
        with self._lock:
            settings = self.get_settings()
            for key, value in changes.items():
                expected = _SETTING_TYPES.get(key)
                if expected is None:
                    raise ValueError(f"réglage inconnu : {key}")
                if not isinstance(value, expected):
                    raise ValueError(f"{key} doit être de type {expected.__name__}")
                settings[key] = value
            self._write(self.root / "settings.json", settings)
            return settings

    def get_presets(self) -> dict[str, dict[str, str]]:
        """Built-in presets plus the user's own (user presets override same-name ones)."""
        presets = {name: dict(values) for name, values in WEB_PRESETS.items()}
        saved = self._read(self.root / "presets.json", {})
        if isinstance(saved, dict):
            for name, values in saved.items():
                if isinstance(values, dict):
                    presets[str(name)] = {str(k): str(v) for k, v in values.items()}
        return presets

    def save_preset(self, name: str, overrides: Mapping[str, str]) -> dict[str, dict[str, str]]:
        """Create or replace a user preset."""
        name = name.strip()
        if not name or len(name) > 40:
            raise ValueError("le nom du préréglage doit faire 1 à 40 caractères")
        with self._lock:
            saved = self._read(self.root / "presets.json", {})
            saved = saved if isinstance(saved, dict) else {}
            saved[name] = dict(overrides)
            self._write(self.root / "presets.json", saved)
        return self.get_presets()

    def delete_preset(self, name: str) -> dict[str, dict[str, str]]:
        """Delete a user preset (built-in ones cannot be deleted)."""
        with self._lock:
            saved = self._read(self.root / "presets.json", {})
            saved = saved if isinstance(saved, dict) else {}
            if name not in saved:
                raise KeyError(name)
            del saved[name]
            self._write(self.root / "presets.json", saved)
        return self.get_presets()
