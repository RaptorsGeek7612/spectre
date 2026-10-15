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
CREATE TABLE IF NOT EXISTS custom_agents (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, engine TEXT NOT NULL, role TEXT NOT NULL,
  instructions TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, pitch TEXT NOT NULL DEFAULT '',
  autopilot INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
  company_id INTEGER NOT NULL, department TEXT NOT NULL, agent TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (company_id, department)
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, title TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '', department TEXT NOT NULL DEFAULT '', agent TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'todo', priority INTEGER NOT NULL DEFAULT 2,
  depends_on TEXT NOT NULL DEFAULT '[]', note TEXT NOT NULL DEFAULT '', mission_id INTEGER,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_company ON tasks(company_id, status);
CREATE TABLE IF NOT EXISTS mission_notes (
  id INTEGER PRIMARY KEY, mission_id INTEGER NOT NULL, ts TEXT NOT NULL, text TEXT NOT NULL,
  used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS routines (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, spec TEXT NOT NULL DEFAULT '', schedule TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'mission', prompt TEXT NOT NULL, agent TEXT NOT NULL DEFAULT '',
  company_id INTEGER, enabled INTEGER NOT NULL DEFAULT 1, next_run TEXT, last_run TEXT,
  last_status TEXT NOT NULL DEFAULT '', failures INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS webhooks (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, source TEXT NOT NULL, action TEXT NOT NULL,
  instructions TEXT NOT NULL DEFAULT '', events TEXT NOT NULL DEFAULT '[]', secret TEXT NOT NULL,
  agent TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1, received INTEGER NOT NULL DEFAULT 0,
  last_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS webhook_seen (delivery TEXT PRIMARY KEY, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS saas_sources (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
  config TEXT NOT NULL DEFAULT '{}', key_env TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
  last_check TEXT, last_error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saas_metrics (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, source_id INTEGER, metric TEXT NOT NULL,
  value REAL NOT NULL, ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS saas_metrics_key ON saas_metrics(company_id, metric, ts);
CREATE TABLE IF NOT EXISTS saas_alerts (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, metric TEXT NOT NULL, op TEXT NOT NULL,
  threshold REAL NOT NULL, consecutive INTEGER NOT NULL DEFAULT 1, label TEXT NOT NULL DEFAULT '',
  cooldown_h REAL NOT NULL DEFAULT 6, last_fired TEXT, active INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS skill_usage (
  name TEXT PRIMARY KEY, uses INTEGER NOT NULL DEFAULT 0, last_used TEXT,
  pinned INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS skill_proposals (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, content TEXT NOT NULL,
  previous TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
  ts TEXT NOT NULL, decided_at TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
  text, content='events', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
  INSERT INTO events_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, question TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'deliberating', opinions TEXT NOT NULL DEFAULT '[]',
  verdict TEXT NOT NULL DEFAULT '{}', decision TEXT NOT NULL DEFAULT '', kpis_before TEXT NOT NULL DEFAULT '{}',
  experiment_id INTEGER, mission_id INTEGER, review_at TEXT, outcome TEXT NOT NULL DEFAULT '',
  lesson TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, decided_at TEXT, reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, hypothesis TEXT NOT NULL, metric TEXT NOT NULL,
  direction TEXT NOT NULL DEFAULT 'up', min_change REAL NOT NULL DEFAULT 5, baseline REAL NOT NULL,
  start_at TEXT NOT NULL, end_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'running', result REAL,
  change REAL, verdict TEXT NOT NULL DEFAULT '', decision_id INTEGER, created_at TEXT NOT NULL, done_at TEXT
);
CREATE TABLE IF NOT EXISTS trust_events (
  id INTEGER PRIMARY KEY, agent TEXT NOT NULL, kind TEXT NOT NULL, mission_id INTEGER, ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS trust_agent ON trust_events(agent);
CREATE TABLE IF NOT EXISTS approval_agents (approval_id INTEGER PRIMARY KEY, agent TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usage_ledger (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, mission_id INTEGER, company_id INTEGER,
  agent TEXT NOT NULL DEFAULT '', engine TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '',
  seconds REAL NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0, tokens INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS usage_ts ON usage_ledger(ts);
CREATE TABLE IF NOT EXISTS meetings (
  id INTEGER PRIMARY KEY, company_id INTEGER, title TEXT NOT NULL, status TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'micro', transcript TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  result TEXT NOT NULL DEFAULT '{}', seconds REAL NOT NULL DEFAULT 0, started_at TEXT NOT NULL,
  ended_at TEXT, mission_id INTEGER
);
CREATE TABLE IF NOT EXISTS dev_config (
  company_id INTEGER PRIMARY KEY, repo_path TEXT NOT NULL, test_command TEXT NOT NULL,
  base_branch TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dev_jobs (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, request TEXT NOT NULL, status TEXT NOT NULL,
  branch TEXT NOT NULL DEFAULT '', worktree TEXT NOT NULL DEFAULT '', tests_ok INTEGER NOT NULL DEFAULT 0,
  test_output TEXT NOT NULL DEFAULT '', diffstat TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
  pr_url TEXT NOT NULL DEFAULT '', mission_id INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
  id INTEGER PRIMARY KEY, endpoint TEXT NOT NULL UNIQUE, p256dh TEXT NOT NULL, auth TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS faces (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, feature TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, agent TEXT NOT NULL DEFAULT '', mission_id INTEGER,
  kind TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '', seconds REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS activity_ts ON activity(ts);
CREATE INDEX IF NOT EXISTS activity_mission ON activity(mission_id);
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
        self._index_events()
        self._conn.commit()

    def _index_events(self) -> None:
        """Index the conversations written before the search existed (once)."""
        # the index's own row table: COUNT(*) on events_fts would read the events themselves
        indexed = self._conn.execute("SELECT COUNT(*) FROM events_fts_docsize").fetchone()[0]
        if not indexed and self._conn.execute("SELECT 1 FROM events LIMIT 1").fetchone():
            self._conn.execute("INSERT INTO events_fts(events_fts) VALUES('rebuild')")

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
