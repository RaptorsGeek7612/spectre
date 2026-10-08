"""SQLite storage for the assistant (one file, WAL mode, safe across threads and processes).

The MCP tool server runs in another process (launched by Claude Code) and shares this file.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
  text TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY, subject TEXT NOT NULL, predicate TEXT NOT NULL, value TEXT NOT NULL,
  category TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0.7, status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  observations INTEGER NOT NULL DEFAULT 1, source_event INTEGER, superseded_by INTEGER
);
CREATE INDEX IF NOT EXISTS facts_key ON facts(subject, predicate, status);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
  subject, predicate, value, content='facts', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
  INSERT INTO facts_fts(rowid, subject, predicate, value) VALUES (new.id, new.subject, new.predicate, new.value);
END;
CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
  INSERT INTO facts_fts(facts_fts, rowid, subject, predicate, value) VALUES ('delete', old.id, old.subject, old.predicate, old.value);
END;
CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE OF subject, predicate, value ON facts BEGIN
  INSERT INTO facts_fts(facts_fts, rowid, subject, predicate, value) VALUES ('delete', old.id, old.subject, old.predicate, old.value);
  INSERT INTO facts_fts(rowid, subject, predicate, value) VALUES (new.id, new.subject, new.predicate, new.value);
END;
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, tool TEXT NOT NULL, args TEXT NOT NULL,
  level INTEGER NOT NULL, category TEXT NOT NULL, reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', result TEXT NOT NULL DEFAULT '', decided_at TEXT
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, tool TEXT NOT NULL, args TEXT NOT NULL,
  level INTEGER NOT NULL, category TEXT NOT NULL, decision TEXT NOT NULL, result TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS undo (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, action TEXT NOT NULL, data TEXT NOT NULL,
  undone INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS missions (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, goal TEXT NOT NULL, status TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT '[]', steps TEXT NOT NULL DEFAULT '[]', report TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS initiatives (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '', level INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending', data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS reminders (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, due_at TEXT NOT NULL, text TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS faces (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, feature TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    """Current UTC time, ISO 8601 with seconds."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    """Thin thread-safe wrapper around one SQLite file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """A transaction (commit on success, rollback on error)."""
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Run a write statement; return lastrowid."""
        with self.tx() as conn:
            cur = conn.execute(sql, params)
            return int(cur.lastrowid or 0)

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    # ---- small helpers -------------------------------------------------------------------

    def get_kv(self, key: str, default: str = "") -> str:
        row = self.one("SELECT value FROM kv WHERE key = ?", (key,))
        return str(row["value"]) if row else default

    def set_kv(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def log_event(self, kind: str, source: str, text: str = "", **data: Any) -> int:
        """Append an immutable event (conversation turn, action, observation...)."""
        return self.execute(
            "INSERT INTO events(ts, kind, source, text, data) VALUES(?, ?, ?, ?, ?)",
            (now_iso(), kind, source, text, json.dumps(data, ensure_ascii=False)),
        )
