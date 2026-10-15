"""SaaS monitoring: read-only sources per company, a metric history, KPIs, alerts and a report.

Sources (all read-only, keys kept in the assistant folder's `.env`, never in the database):
- `uptime`: a URL checked every 5 minutes (`up`, `latency_ms`);
- `stripe`: subscriptions and charges (`mrr`, `active_subscriptions`, `new_subscriptions_30d`,
  `canceled_30d`, `churn_rate`, `failed_payments_30d`, `revenue_30d`); a restricted read-only
  key (`rk_...`) is enough;
- `supabase`: an exact row count of a table, and the rows created in the last 7 days
  (`users_total`, `signups_7d`), with a HEAD request and `Prefer: count=exact`;
- `github`: the last CI run of the default branch and the open issues (`ci_ok`, `open_issues`);
- `http_json`: any JSON API, with numbers picked by dotted paths (`{"errors": "data.count"}`);
- `manual`: figures typed by the user or Spectre (e.g. `marketing_spend_30d`, for the CAC).

Derived KPIs: ARR, ARPA, LTV (ARPA / monthly churn), CAC (marketing spend / new subscriptions)
and LTV/CAC. Alert rules compare a metric with a threshold, with a cooldown; an uptime source
gets a « site down » rule (two failed checks in a row) when it is added.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from spectre.assistant.db import Database, now_iso
from spectre.assistant.providers import read_env_file, write_env_value

KINDS = ("uptime", "stripe", "supabase", "github", "http_json", "manual")
INTERVALS = {"uptime": 300, "stripe": 3600, "supabase": 3600, "github": 900, "http_json": 900}
OPS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "=": lambda a, b: a == b,
}
MAX_SOURCES = 20
KEEP_DAYS = 120
STRIPE_PAGES = 10
PER_MONTH = {"day": 365 / 12, "week": 52 / 12, "month": 1.0, "year": 1 / 12}
METRIC = re.compile(r"[a-z][a-z0-9_]{1,39}")
LABELS = {
    "mrr": "MRR",
    "arr": "ARR",
    "active_subscriptions": "Abonnements actifs",
    "new_subscriptions_30d": "Nouveaux abonnements (30 j)",
    "canceled_30d": "Résiliations (30 j)",
    "churn_rate": "Churn (30 j, %)",
    "failed_payments_30d": "Paiements échoués (30 j)",
    "revenue_30d": "Encaissé (30 j)",
    "arpa": "ARPA (par abonné)",
    "ltv": "LTV",
    "cac": "CAC",
    "ltv_cac": "LTV / CAC",
    "users_total": "Utilisateurs",
    "signups_7d": "Inscriptions (7 j)",
    "up": "Site en ligne",
    "latency_ms": "Temps de réponse (ms)",
    "uptime_7d": "Disponibilité (7 j, %)",
    "ci_ok": "CI au vert",
    "open_issues": "Tickets et PR ouverts",
    "marketing_spend_30d": "Dépenses marketing (30 j)",
}
HIGHER_IS_BETTER = {
    "mrr": True,
    "arr": True,
    "active_subscriptions": True,
    "new_subscriptions_30d": True,
    "revenue_30d": True,
    "arpa": True,
    "ltv": True,
    "ltv_cac": True,
    "users_total": True,
    "signups_7d": True,
    "uptime_7d": True,
    "canceled_30d": False,
    "churn_rate": False,
    "failed_payments_30d": False,
    "latency_ms": False,
    "cac": False,
    "open_issues": False,
}
TILES = (
    "mrr",
    "arr",
    "active_subscriptions",
    "churn_rate",
    "arpa",
    "ltv",
    "cac",
    "ltv_cac",
    "failed_payments_30d",
    "revenue_30d",
    "users_total",
    "signups_7d",
    "uptime_7d",
    "latency_ms",
)

Response = tuple[int, dict[str, str], bytes]
Fetch = Callable[[str, str, dict[str, str], float], Response]


class SaasError(ValueError):
    """A refused configuration (the message is for the user)."""


def http_fetch(method: str, url: str, headers: dict[str, str], timeout: float) -> Response:
    """One HTTP call (real network); HTTP errors come back as their status."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "Spectre", **headers}, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def get_path(data: Any, path: str) -> Any:
    """`"data.items.0.count"` inside nested dicts and lists."""
    for part in path.split("."):
        if isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        elif isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return None
    return data


# ---- collectors: one per source kind, each returns {metric: value} ---------------------------


class Collect:
    def __init__(self, fetch: Fetch, now: datetime) -> None:
        self.fetch = fetch
        self.now = now

    def json(self, url: str, headers: dict[str, str]) -> Any:
        status, _, body = self.fetch("GET", url, headers, 20.0)
        if status >= 400:
            detail = body.decode("utf-8", "replace")[:200]
            raise ConnectionError(f"HTTP {status} : {detail}")
        return json.loads(body.decode("utf-8") or "null")

    def uptime(self, config: dict[str, Any], key: str) -> dict[str, float]:
        start = time.perf_counter()
        try:
            status, _, _ = self.fetch("GET", config["url"], {}, 15.0)
        except OSError:
            return {"up": 0.0}
        latency = round((time.perf_counter() - start) * 1000, 1)
        return {"up": 1.0 if status < 400 else 0.0, "latency_ms": latency}

    def stripe_list(self, path: str, params: dict[str, str], key: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        after = ""
        for _ in range(STRIPE_PAGES):
            query = {"limit": "100", **params} | ({"starting_after": after} if after else {})
            page = self.json(
                f"https://api.stripe.com/v1/{path}?{urllib.parse.urlencode(query)}",
                {"Authorization": f"Bearer {key}"},
            )
            data = page.get("data") or []
            items += data
            if not page.get("has_more") or not data:
                break
            after = data[-1]["id"]
        return items

    def stripe(self, config: dict[str, Any], key: str) -> dict[str, float]:
        since = int((self.now - timedelta(days=30)).timestamp())
        active = self.stripe_list("subscriptions", {"status": "active"}, key)
        canceled = [
            s
            for s in self.stripe_list("subscriptions", {"status": "canceled"}, key)
            if (s.get("canceled_at") or 0) >= since
        ]
        charges = self.stripe_list("charges", {"created[gte]": str(since)}, key)
        mrr = 0.0
        for sub in active:
            for item in (sub.get("items") or {}).get("data") or []:
                price = item.get("price") or {}
                recurring = price.get("recurring") or {}
                unit = price.get("unit_amount") or 0
                per_month = PER_MONTH.get(recurring.get("interval", "month"), 1.0)
                per_month /= recurring.get("interval_count") or 1
                mrr += unit * (item.get("quantity") or 1) * per_month / 100
        new = sum(1 for s in active if (s.get("created") or 0) >= since)
        churn = 100 * len(canceled) / (len(active) + len(canceled)) if active or canceled else 0.0
        paid = [c for c in charges if c.get("status") == "succeeded"]
        return {
            "mrr": round(mrr, 2),
            "active_subscriptions": float(len(active)),
            "new_subscriptions_30d": float(new),
            "canceled_30d": float(len(canceled)),
            "churn_rate": round(churn, 2),
            "failed_payments_30d": float(sum(1 for c in charges if c.get("status") == "failed")),
            "revenue_30d": round(
                sum((c.get("amount") or 0) - (c.get("amount_refunded") or 0) for c in paid) / 100, 2
            ),
        }

    def count(self, url: str, key: str) -> float:
        headers = {"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact"}
        status, response_headers, body = self.fetch("HEAD", url, headers, 20.0)
        if status >= 400:
            raise ConnectionError(f"HTTP {status} : {body.decode('utf-8', 'replace')[:200]}")
        content_range = {k.lower(): v for k, v in response_headers.items()}.get("content-range", "")
        total = content_range.rsplit("/", 1)[-1]
        if not total.isdigit():
            raise ConnectionError("Supabase n'a pas renvoyé de total (Content-Range)")
        return float(total)

    def supabase(self, config: dict[str, Any], key: str) -> dict[str, float]:
        base = f"{config['url'].rstrip('/')}/rest/v1/{urllib.parse.quote(config['table'])}"
        found = {"users_total": self.count(f"{base}?select=*", key)}
        if config.get("date_column"):
            since = (self.now - timedelta(days=7)).astimezone(UTC).isoformat()
            column = urllib.parse.quote(config["date_column"])
            found["signups_7d"] = self.count(
                f"{base}?select=*&{column}=gte.{urllib.parse.quote(since)}", key
            )
        return found

    def github(self, config: dict[str, Any], key: str) -> dict[str, float]:
        headers = {"Accept": "application/vnd.github+json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        repo = self.json(f"https://api.github.com/repos/{config['repo']}", headers)
        found = {"open_issues": float(repo.get("open_issues_count") or 0)}
        branch = urllib.parse.quote(str(repo.get("default_branch") or "main"))
        runs = self.json(
            f"https://api.github.com/repos/{config['repo']}/actions/runs?branch={branch}&per_page=5",
            headers,
        ).get("workflow_runs", [])
        done = [r for r in runs if r.get("status") == "completed"]
        if done:
            found["ci_ok"] = 1.0 if done[0].get("conclusion") == "success" else 0.0
        return found

    def http_json(self, config: dict[str, Any], key: str) -> dict[str, float]:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        data = self.json(config["url"], headers)
        found = {}
        for metric, path in (config.get("fields") or {}).items():
            value = get_path(data, str(path))
            if isinstance(value, bool):
                value = float(value)
            if isinstance(value, (int, float)):
                found[metric] = float(value)
        if not found:
            raise ConnectionError("aucun des champs demandés n'est un nombre dans la réponse")
        return found


# ---- storage, KPIs, alerts and report --------------------------------------------------------


class Saas:
    """A company's sources, metric history, KPIs and alert rules."""

    def __init__(self, db: Database, root: Path | None = None) -> None:
        self.db = db
        self.root = root
        self._lock = threading.Lock()

    # ---- sources -----------------------------------------------------------------------------

    def sources(self, company_id: int) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT * FROM saas_sources WHERE company_id = ? ORDER BY id", (company_id,)
        )
        for row in rows:
            row["config"] = json.loads(row["config"] or "{}")
            row["has_key"] = bool(self.key(row))
        return rows

    def source(self, source_id: int) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM saas_sources WHERE id = ?", (int(source_id),))
        if row is None:
            raise SaasError(f"source #{source_id} introuvable")
        row["config"] = json.loads(row["config"] or "{}")
        return row

    def key(self, row: dict[str, Any]) -> str:
        if not row.get("key_env") or self.root is None:
            return ""
        import os

        return os.environ.get(row["key_env"], "") or read_env_file(self.root / ".env").get(
            row["key_env"], ""
        )

    def add_source(
        self, company_id: int, kind: str, name: str, config: dict[str, Any], key: str = ""
    ) -> dict[str, Any]:
        kind = kind.strip().lower()
        if kind not in KINDS:
            raise SaasError(f"type de source « {kind} » : au choix {', '.join(KINDS)}")
        if len(self.sources(company_id)) >= MAX_SOURCES:
            raise SaasError(f"{MAX_SOURCES} sources au maximum par entreprise")
        clean = self._check(kind, config, key)
        name = name.strip() or kind
        sid = self.db.execute(
            "INSERT INTO saas_sources(company_id, kind, name, config, created_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (company_id, kind, name[:60], json.dumps(clean), now_iso()),
        )
        if key.strip():
            if self.root is None:
                raise SaasError("dossier de Spectre inconnu : impossible d'enregistrer la clé")
            env = f"SPECTRE_SAAS_{sid}_KEY"
            write_env_value(self.root, env, key.strip())
            self.db.execute("UPDATE saas_sources SET key_env = ? WHERE id = ?", (env, sid))
        if kind == "uptime":
            self.add_alert(company_id, "up", "<", 1, consecutive=2, label="Site indisponible")
        if kind == "github":
            self.add_alert(company_id, "ci_ok", "<", 1, label="CI en échec")
        if kind == "stripe":
            self.add_alert(company_id, "failed_payments_30d", ">", 0, label="Paiements échoués")
        return self.source(sid)

    def _check(self, kind: str, config: dict[str, Any], key: str) -> dict[str, Any]:
        def url(value: Any) -> str:
            text = str(value or "").strip()
            if not text.startswith(("https://", "http://")):
                raise SaasError("adresse http(s) attendue")
            return text

        if kind == "uptime":
            return {"url": url(config.get("url"))}
        if kind == "stripe":
            if not key.strip().startswith(("rk_", "sk_")):
                raise SaasError(
                    "clé Stripe attendue (de préférence restreinte en lecture : rk_...)"
                )
            return {}
        if kind == "supabase":
            table = str(config.get("table") or "").strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                raise SaasError("nom de table Supabase attendu (ex. profiles)")
            if not key.strip():
                raise SaasError("clé Supabase attendue (clé de service, en lecture)")
            column = str(config.get("date_column") or "").strip()
            if column and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column):
                raise SaasError("nom de colonne de date invalide")
            return {"url": url(config.get("url")), "table": table, "date_column": column}
        if kind == "github":
            repo = str(config.get("repo") or "").strip()
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
                raise SaasError("dépôt GitHub attendu sous la forme propriétaire/nom")
            return {"repo": repo}
        if kind == "http_json":
            fields = config.get("fields") or {}
            if isinstance(fields, str):
                fields = dict(
                    (part.split("=", 1)[0].strip(), part.split("=", 1)[1].strip())
                    for part in fields.split(",")
                    if "=" in part
                )
            if not fields or not all(METRIC.fullmatch(m) for m in fields):
                raise SaasError("champs attendus : métrique=chemin, ex. errors=data.count")
            return {"url": url(config.get("url")), "fields": fields}
        return {}

    def delete_source(self, source_id: int) -> dict[str, Any]:
        row = self.source(source_id)
        self.db.execute("DELETE FROM saas_sources WHERE id = ?", (row["id"],))
        if row["key_env"] and self.root is not None:
            write_env_value(self.root, row["key_env"], "")
        return row

    # ---- collecting ------------------------------------------------------------------------------

    def due(self, now: datetime) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT * FROM saas_sources WHERE enabled = 1 AND kind != 'manual'")
        due = []
        for row in rows:
            last = datetime.fromisoformat(row["last_check"]) if row["last_check"] else None
            if last is None or (now - last).total_seconds() >= INTERVALS[row["kind"]]:
                row["config"] = json.loads(row["config"] or "{}")
                due.append(row)
        return due

    def check(
        self, row: dict[str, Any], now: datetime, fetch: Fetch | None = None
    ) -> dict[str, float]:
        """Collect one source now; stores its metrics, or its error."""
        collector = Collect(fetch or http_fetch, now)
        try:
            found: dict[str, float] = getattr(collector, row["kind"])(row["config"], self.key(row))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self.db.execute(
                "UPDATE saas_sources SET last_check = ?, last_error = ? WHERE id = ?",
                (now.isoformat(), str(exc)[:300], row["id"]),
            )
            return {}
        for metric, value in found.items():
            self.record(row["company_id"], metric, value, now, source_id=row["id"])
        self.db.execute(
            "UPDATE saas_sources SET last_check = ?, last_error = '' WHERE id = ?",
            (now.isoformat(), row["id"]),
        )
        return found

    def tick(self, now: datetime, notify: Callable[..., Any], fetch: Fetch | None = None) -> int:
        """Check the due sources (one pass at a time), then the alert rules."""
        if not self._lock.acquire(blocking=False):
            return 0
        try:
            due = self.due(now)
            for row in due:
                self.check(row, now, fetch)
            for company_id in {r["company_id"] for r in due}:
                self.alerts_check(company_id, now, notify)
            cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
            self.db.execute("DELETE FROM saas_metrics WHERE ts < ?", (cutoff,))
            return len(due)
        finally:
            self._lock.release()

    def record(
        self,
        company_id: int,
        metric: str,
        value: float,
        now: datetime,
        source_id: int | None = None,
    ) -> None:
        if not METRIC.fullmatch(metric):
            raise SaasError(f"nom de métrique invalide « {metric} » (minuscules, chiffres, _)")
        self.db.execute(
            "INSERT INTO saas_metrics(company_id, source_id, metric, value, ts) "
            "VALUES(?, ?, ?, ?, ?)",
            (company_id, source_id, metric, float(value), now.isoformat()),
        )

    # ---- KPIs ----------------------------------------------------------------------------------

    def history(self, company_id: int, metric: str, since: datetime) -> list[tuple[str, float]]:
        rows = self.db.all(
            "SELECT ts, value FROM saas_metrics WHERE company_id = ? AND metric = ? AND ts >= ? "
            "ORDER BY ts",
            (company_id, metric, since.isoformat()),
        )
        return [(r["ts"], float(r["value"])) for r in rows]

    def latest(self, company_id: int, before: datetime | None = None) -> dict[str, float]:
        sql = (
            "SELECT metric, value FROM saas_metrics m WHERE company_id = ? AND id = ("
            "SELECT id FROM saas_metrics WHERE company_id = m.company_id AND metric = m.metric "
            + ("AND ts <= ? " if before else "")
            + "ORDER BY ts DESC, id DESC LIMIT 1)"
        )
        params: tuple[Any, ...] = (company_id, before.isoformat()) if before else (company_id,)
        return {r["metric"]: float(r["value"]) for r in self.db.all(sql, params)}

    def kpis(
        self, company_id: int, now: datetime, before: datetime | None = None
    ) -> dict[str, float]:
        """Latest values plus derived KPIs (at `before`, for comparisons)."""
        values = self.latest(company_id, before)
        mrr, subs = values.get("mrr"), values.get("active_subscriptions")
        if mrr is not None:
            values["arr"] = round(mrr * 12, 2)
            if subs:
                values["arpa"] = round(mrr / subs, 2)
        churn = values.get("churn_rate")
        if values.get("arpa") and churn:
            values["ltv"] = round(values["arpa"] / (churn / 100), 2)
        spend, new = values.get("marketing_spend_30d"), values.get("new_subscriptions_30d")
        if spend is not None and new:
            values["cac"] = round(spend / new, 2)
        if values.get("ltv") and values.get("cac"):
            values["ltv_cac"] = round(values["ltv"] / values["cac"], 2)
        end = before or now
        checks = [
            v
            for ts, v in self.history(company_id, "up", end - timedelta(days=7))
            if ts <= end.isoformat()
        ]
        if checks:
            values["uptime_7d"] = round(100 * sum(checks) / len(checks), 2)
        return values

    def dashboard(self, company_id: int, now: datetime) -> dict[str, Any]:
        """Tiles (value, change over 7 days, 12-point trend), sources and alert rules."""
        current = self.kpis(company_id, now)
        week_ago = self.kpis(company_id, now, before=now - timedelta(days=7))
        tiles = []
        for metric in [
            *TILES,
            *sorted(k for k in current if k not in TILES and k not in ("up", "ci_ok")),
        ]:
            if metric not in current:
                continue
            series = self.history(company_id, metric, now - timedelta(days=30))
            step = max(1, len(series) // 12)
            trend = [v for _, v in series[::step]][-12:]
            delta = current[metric] - week_ago[metric] if metric in week_ago else None
            tiles.append(
                {
                    "metric": metric,
                    "label": LABELS.get(metric, metric.replace("_", " ")),
                    "value": current[metric],
                    "delta": round(delta, 2) if delta is not None else None,
                    "good": HIGHER_IS_BETTER.get(metric),
                    "trend": trend,
                }
            )
        status = {k: current[k] for k in ("up", "ci_ok") if k in current}
        sources = [{k: v for k, v in s.items() if k != "key_env"} for s in self.sources(company_id)]
        return {
            "tiles": tiles,
            "status": status,
            "sources": sources,
            "alerts": self.alerts(company_id),
        }

    # ---- alerts ------------------------------------------------------------------------------

    def alerts(self, company_id: int) -> list[dict[str, Any]]:
        return self.db.all(
            "SELECT * FROM saas_alerts WHERE company_id = ? ORDER BY id", (company_id,)
        )

    def add_alert(
        self,
        company_id: int,
        metric: str,
        op: str,
        threshold: float,
        *,
        consecutive: int = 1,
        label: str = "",
        cooldown_h: float = 6.0,
    ) -> dict[str, Any]:
        metric, op = metric.strip(), op.strip()
        if not METRIC.fullmatch(metric):
            raise SaasError(f"métrique « {metric} » invalide")
        if op not in OPS:
            raise SaasError(f"comparaison « {op} » : au choix {' '.join(OPS)}")
        aid = self.db.execute(
            "INSERT INTO saas_alerts(company_id, metric, op, threshold, consecutive, label, "
            "cooldown_h) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                metric,
                op,
                float(threshold),
                max(1, int(consecutive)),
                label[:80],
                cooldown_h,
            ),
        )
        row = self.db.one("SELECT * FROM saas_alerts WHERE id = ?", (aid,))
        assert row is not None
        return row

    def delete_alert(self, alert_id: int) -> None:
        self.db.execute("DELETE FROM saas_alerts WHERE id = ?", (int(alert_id),))

    def alerts_check(self, company_id: int, now: datetime, notify: Callable[..., Any]) -> list[int]:
        """Fire the rules whose condition holds (respecting each one's cooldown)."""
        fired = []
        values = self.kpis(company_id, now)
        company = self.db.one("SELECT name FROM companies WHERE id = ?", (company_id,))
        name = company["name"] if company else f"#{company_id}"
        for rule in self.alerts(company_id):
            if rule["metric"] not in values:
                continue
            stored = self.history(company_id, rule["metric"], now - timedelta(days=KEEP_DAYS))
            # a collected metric: its last N checks; a derived KPI: its current value
            last = [v for _, v in stored][-rule["consecutive"] :] or [values[rule["metric"]]]
            needed = rule["consecutive"] if stored else 1
            holds = len(last) >= needed and all(OPS[rule["op"]](v, rule["threshold"]) for v in last)
            if not holds:
                if rule["active"]:
                    self.db.execute("UPDATE saas_alerts SET active = 0 WHERE id = ?", (rule["id"],))
                    notify(
                        "alerte",
                        f"{name} : rétabli",
                        f"{rule['label'] or rule['metric']} : c'est revenu à la normale.",
                    )
                continue
            if rule["last_fired"]:
                elapsed = now - datetime.fromisoformat(rule["last_fired"])
                if rule["active"] and elapsed < timedelta(hours=rule["cooldown_h"]):
                    continue
            self.db.execute(
                "UPDATE saas_alerts SET last_fired = ?, active = 1 WHERE id = ?",
                (now.isoformat(), rule["id"]),
            )
            title = f"{name} : {rule['label'] or rule['metric']}"
            body = (
                f"{LABELS.get(rule['metric'], rule['metric'])} = {fmt(values[rule['metric']])} "
                f"(seuil {rule['op']} {fmt(rule['threshold'])})."
            )
            notify("alerte", title, body)
            fired.append(rule["id"])
        return fired

    # ---- report ---------------------------------------------------------------------------------

    def report(self, company_id: int, now: datetime) -> str:
        """KPIs with their change over a week, sources in error and alerts of the week."""
        company = self.db.one("SELECT name FROM companies WHERE id = ?", (company_id,))
        data = self.dashboard(company_id, now)
        lines = [f"Tableau de bord de {company['name'] if company else company_id} :"]
        if not data["tiles"] and not data["status"]:
            lines.append("aucune donnée encore (ajoute des sources : Stripe, Supabase, site...)")
        for tile in data["tiles"]:
            delta = ""
            if tile["delta"] is not None:
                delta = f" ({'+' if tile['delta'] >= 0 else ''}{fmt(tile['delta'])} sur 7 jours)"
            lines.append(f"- {tile['label']} : {fmt(tile['value'])}{delta}")
        if "up" in data["status"]:
            lines.append(f"- Site : {'en ligne' if data['status']['up'] else 'HORS LIGNE'}")
        if "ci_ok" in data["status"]:
            lines.append(f"- CI : {'au vert' if data['status']['ci_ok'] else 'EN ÉCHEC'}")
        broken = [s for s in data["sources"] if s["last_error"]]
        for source in broken:
            lines.append(f"- Source « {source['name']} » en erreur : {source['last_error']}")
        week = (now - timedelta(days=7)).isoformat()
        fired = [a for a in data["alerts"] if a["last_fired"] and a["last_fired"] >= week]
        if fired:
            lines.append(
                "Alertes de la semaine : " + ", ".join(a["label"] or a["metric"] for a in fired)
            )
        return "\n".join(lines)


def fmt(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") if abs(value) >= 1000 else f"{value:g}"
