"""SaaS monitoring: sources and collectors, metrics, KPIs, alerts, report, tools and API."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import tools
from spectre.assistant.company import Companies
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate
from spectre.assistant.providers import read_env_file
from spectre.assistant.saas import Collect, Saas, SaasError, fmt, get_path
from spectre.assistant.service import AssistantService
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client

TZ = timezone(timedelta(hours=2))
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=TZ)
DAY = 86400


class FakeHttp:
    """Answers by URL fragment: {fragment: (status, headers, body-or-json)}; records calls."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], timeout: float) -> Any:
        self.calls.append((method, url, headers))
        for fragment, answer in self.routes.items():
            if fragment in url:
                if isinstance(answer, Exception):
                    raise answer
                if callable(answer):
                    answer = answer(url)
                status, extra, body = answer
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                return status, extra, raw
        return 404, {}, b"{}"


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Database, Saas, int, Path]:
    root = tmp_path / "assistant"
    db = Database(root / "spectre.db")
    company = Companies(db).create("Acme", "SaaS")
    return db, Saas(db, root), company["id"], root


def sub(
    price: int, interval: str = "month", count: int = 1, qty: int = 1, created: int = 0
) -> dict[str, Any]:
    return {
        "id": f"sub_{price}_{interval}_{created}",
        "created": created,
        "items": {
            "data": [
                {
                    "quantity": qty,
                    "price": {
                        "unit_amount": price,
                        "recurring": {"interval": interval, "interval_count": count},
                    },
                }
            ]
        },
    }


def stripe_routes(now: datetime) -> dict[str, Any]:
    recent = int((now - timedelta(days=3)).timestamp())
    old = int((now - timedelta(days=90)).timestamp())

    def subscriptions(url: str) -> Any:
        if "status=canceled" in url:
            return (
                200,
                {},
                {
                    "data": [{"id": "c1", "canceled_at": recent}, {"id": "c2", "canceled_at": old}],
                    "has_more": False,
                },
            )
        if "starting_after" in url:
            return 200, {}, {"data": [sub(1200, "year", created=old)], "has_more": False}
        return (
            200,
            {},
            {
                "data": [sub(1000, qty=2, created=recent), sub(500, "week", count=2, created=old)],
                "has_more": True,
            },
        )

    charges = {
        "data": [
            {"id": "ch1", "status": "succeeded", "amount": 2000, "amount_refunded": 500},
            {"id": "ch2", "status": "failed", "amount": 1000},
            {"id": "ch3", "status": "succeeded", "amount": 1000},
        ],
        "has_more": False,
    }
    return {"/v1/subscriptions": subscriptions, "/v1/charges": (200, {}, charges)}


# ---- collectors ----------------------------------------------------------------------------------


def test_stripe_collector() -> None:
    fetch = FakeHttp(stripe_routes(NOW))
    found = Collect(fetch, NOW).stripe({}, "rk_test")
    # 2 x 10.00 monthly + 5.00 every 2 weeks (52/12/2 per month) + 12.00 yearly
    assert found["mrr"] == round(20 + 5 * 52 / 12 / 2 + 1, 2)
    assert found["active_subscriptions"] == 3 and found["new_subscriptions_30d"] == 1
    assert found["canceled_30d"] == 1 and found["churn_rate"] == 25.0
    assert found["failed_payments_30d"] == 1 and found["revenue_30d"] == 25.0
    assert all(h["Authorization"] == "Bearer rk_test" for _, _, h in fetch.calls)
    assert "starting_after=sub_500_week" in fetch.calls[1][1]


def test_other_collectors() -> None:
    def supabase(url: str) -> Any:
        total = "0-0/7" if "created_at=gte." in url else "*/1234"
        return 200, {"Content-Range": total}, b""

    fetch = FakeHttp(
        {
            "up.example": (200, {}, b"ok"),
            "down.example": (503, {}, b""),
            "dead.example": OSError("refused"),
            "sb.example/rest/v1/profiles": supabase,
            "api.github.com/repos/me/app/actions": (
                200,
                {},
                {
                    "workflow_runs": [
                        {"status": "in_progress"},
                        {"status": "completed", "conclusion": "failure"},
                    ]
                },
            ),
            "api.github.com/repos/me/app": (
                200,
                {},
                {"open_issues_count": 4, "default_branch": "main"},
            ),
            "json.example": (200, {}, {"data": {"count": 3, "ok": True, "list": [{"n": 9}]}}),
        }
    )
    collect = Collect(fetch, NOW)
    up = collect.uptime({"url": "https://up.example"}, "")
    assert up["up"] == 1.0 and up["latency_ms"] >= 0
    assert collect.uptime({"url": "https://down.example"}, "")["up"] == 0.0
    assert collect.uptime({"url": "https://dead.example"}, "") == {"up": 0.0}
    found = collect.supabase(
        {"url": "https://sb.example/", "table": "profiles", "date_column": "created_at"}, "svc"
    )
    assert found == {"users_total": 1234.0, "signups_7d": 7.0}
    method, url, headers = fetch.calls[-1]
    assert method == "HEAD" and headers["Prefer"] == "count=exact" and headers["apikey"] == "svc"
    assert collect.github({"repo": "me/app"}, "") == {"open_issues": 4.0, "ci_ok": 0.0}
    assert "Authorization" not in fetch.calls[-1][2]
    fields = {
        "errors": "data.count",
        "healthy": "data.ok",
        "nested": "data.list.0.n",
        "missing": "x.y",
    }
    assert collect.http_json({"url": "https://json.example", "fields": fields}, "tok") == {
        "errors": 3.0,
        "healthy": 1.0,
        "nested": 9.0,
    }
    with pytest.raises(ConnectionError, match="aucun des champs"):
        collect.http_json({"url": "https://json.example", "fields": {"x": "nope"}}, "")
    with pytest.raises(ConnectionError, match="HTTP 404"):
        collect.json("https://nowhere.example", {})
    no_range = Collect(FakeHttp({"sb": (200, {}, b"")}), NOW)
    with pytest.raises(ConnectionError, match="Content-Range"):
        no_range.supabase({"url": "https://sb", "table": "t"}, "k")
    denied = Collect(FakeHttp({"sb": (401, {}, b"no")}), NOW)
    with pytest.raises(ConnectionError, match="HTTP 401"):
        denied.count("https://sb/rest/v1/t", "k")
    assert get_path({"a": [1, {"b": 2}]}, "a.1.b") == 2 and get_path([], "0") is None


# ---- sources, metrics, KPIs ----------------------------------------------------------------------


def test_sources(setup: tuple[Database, Saas, int, Path]) -> None:
    db, saas, cid, root = setup
    site = saas.add_source(cid, "uptime", "Site", {"url": "https://acme.example"})
    assert site["config"] == {"url": "https://acme.example"} and site["key_env"] == ""
    stripe = saas.add_source(cid, "stripe", "", {}, key="rk_live_x")
    assert stripe["name"] == "stripe" and stripe["key_env"] == f"SPECTRE_SAAS_{stripe['id']}_KEY"
    assert read_env_file(root / ".env")[stripe["key_env"]] == "rk_live_x"
    listed = saas.sources(cid)
    assert [s["has_key"] for s in listed] == [False, True]
    assert [a["metric"] for a in saas.alerts(cid)] == ["up", "failed_payments_30d"]
    saas.add_source(cid, "github", "CI", {"repo": "me/app"})
    saas.add_source(
        cid,
        "supabase",
        "Base",
        {"url": "https://sb.example", "table": "profiles", "date_column": ""},
        key="svc",
    )
    saas.add_source(
        cid,
        "http_json",
        "Erreurs",
        {"url": "https://x.example", "fields": "errors=data.count, users = meta.total"},
    )
    assert saas.sources(cid)[-1]["config"]["fields"] == {
        "errors": "data.count",
        "users": "meta.total",
    }
    for kind, config, key, error in [
        ("ftp", {}, "", "type de source"),
        ("uptime", {"url": "acme.example"}, "", "http"),
        ("stripe", {}, "pk_live", "clé Stripe"),
        ("supabase", {"url": "https://s", "table": "1x"}, "k", "table"),
        ("supabase", {"url": "https://s", "table": "t"}, "", "clé Supabase"),
        ("supabase", {"url": "https://s", "table": "t", "date_column": "a b"}, "k", "colonne"),
        ("github", {"repo": "pas un dépôt"}, "", "propriétaire/nom"),
        ("http_json", {"url": "https://x", "fields": {"Bad Name": "a"}}, "", "métrique=chemin"),
    ]:
        with pytest.raises(SaasError, match=error):
            saas.add_source(cid, kind, "x", config, key)
    saas.delete_source(stripe["id"])
    assert stripe["key_env"] not in read_env_file(root / ".env")
    with pytest.raises(SaasError, match="introuvable"):
        saas.source(stripe["id"])
    with pytest.raises(SaasError, match="dossier"):
        Saas(db).add_source(cid, "stripe", "x", {}, key="rk_1")


def test_check_tick_and_kpis(
    setup: tuple[Database, Saas, int, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    db, saas, cid, root = setup
    monkeypatch.setenv("SPECTRE_SAAS_1_KEY", "rk_env")
    stripe = saas.add_source(cid, "stripe", "Stripe", {}, key="rk_file")
    site = saas.add_source(cid, "uptime", "Site", {"url": "https://acme.example"})
    assert saas.key(saas.source(stripe["id"])) == "rk_env"  # the environment wins
    routes = stripe_routes(NOW) | {"acme.example": (200, {}, b"ok")}
    fetch = FakeHttp(routes)
    notes: list[Any] = []
    assert saas.tick(NOW, lambda *a: notes.append(a), fetch) == 2
    assert saas.due(NOW + timedelta(minutes=1)) == []
    assert [s["id"] for s in saas.due(NOW + timedelta(minutes=6))] == [site["id"]]
    saas.record(cid, "marketing_spend_30d", 300, NOW)
    kpis = saas.kpis(cid, NOW)
    assert kpis["arr"] == round(kpis["mrr"] * 12, 2) and kpis["arpa"] == round(kpis["mrr"] / 3, 2)
    assert kpis["ltv"] == round(kpis["arpa"] / 0.25, 2) and kpis["cac"] == 300.0
    assert kpis["ltv_cac"] == round(kpis["ltv"] / 300, 2) and kpis["uptime_7d"] == 100.0
    assert notes[0][1] == "Acme : Paiements échoués"  # one failed charge in 30 days
    with pytest.raises(SaasError, match="nom de métrique"):
        saas.record(cid, "Bad", 1, NOW)
    broken = FakeHttp({"acme.example": OSError("x"), "api.stripe.com": (401, {}, b"bad key")})
    assert saas.check(saas.source(stripe["id"]), NOW, broken) == {}
    assert saas.source(stripe["id"])["last_error"].startswith("HTTP 401")
    # old metrics are pruned
    saas.record(cid, "mrr", 1, NOW - timedelta(days=200))
    saas.tick(NOW + timedelta(hours=2), lambda *a: None, FakeHttp(routes))
    assert (
        db.one(
            "SELECT COUNT(*) AS n FROM saas_metrics WHERE ts < ?",
            ((NOW - timedelta(days=150)).isoformat(),),
        )["n"]
        == 0
    )
    saas._lock.acquire()
    assert saas.tick(NOW + timedelta(hours=5), print, fetch) == 0  # one pass at a time
    saas._lock.release()


def test_dashboard_and_report(setup: tuple[Database, Saas, int, Path]) -> None:
    db, saas, cid, root = setup
    assert "aucune donnée encore" in saas.report(cid, NOW)
    for days, mrr in ((20, 800.0), (8, 900.0), (1, 1000.0)):
        saas.record(cid, "mrr", mrr, NOW - timedelta(days=days))
    saas.record(cid, "churn_rate", 4.0, NOW - timedelta(days=1))
    saas.record(cid, "up", 0.0, NOW)
    saas.record(cid, "ci_ok", 1.0, NOW)
    saas.record(cid, "custom_metric", 7, NOW)
    board = saas.dashboard(cid, NOW)
    tiles = {t["metric"]: t for t in board["tiles"]}
    assert (
        tiles["mrr"]["value"] == 1000.0
        and tiles["mrr"]["delta"] == 100.0
        and tiles["mrr"]["good"] is True
    )
    assert tiles["mrr"]["trend"] == [800.0, 900.0, 1000.0] and tiles["arr"]["value"] == 12000.0
    assert (
        tiles["churn_rate"]["good"] is False and tiles["custom_metric"]["label"] == "custom metric"
    )
    assert board["status"] == {"up": 0.0, "ci_ok": 1.0} and "up" not in tiles
    saas.add_source(cid, "uptime", "Site", {"url": "https://acme.example"})
    db.execute("UPDATE saas_sources SET last_error = 'timeout'")
    db.execute("UPDATE saas_alerts SET last_fired = ?", (NOW.isoformat(),))
    report = saas.report(cid, NOW)
    assert "- MRR : 1 000 (+100 sur 7 jours)" in report and "- ARR : 12 000" in report
    assert "- Site : HORS LIGNE" in report and "- CI : au vert" in report
    assert (
        "Source « Site » en erreur : timeout" in report
        and "Alertes de la semaine : Site indisponible" in report
    )
    assert fmt(1234567.0) == "1 234 567" and fmt(2.5) == "2.5"


def test_alerts(setup: tuple[Database, Saas, int, Path]) -> None:
    db, saas, cid, root = setup
    saas.add_source(cid, "uptime", "Site", {"url": "https://acme.example"})
    churn = saas.add_alert(cid, "churn_rate", ">", 5, label="Churn élevé", cooldown_h=1)
    ltv_rule = saas.add_alert(cid, "arr", "<", 1000)
    notes: list[Any] = []
    notify = lambda *a: notes.append(a)  # noqa: E731
    saas.record(cid, "up", 0, NOW)
    assert saas.alerts_check(cid, NOW, notify) == []  # one failed check: not yet
    saas.record(cid, "up", 0, NOW + timedelta(minutes=5))
    assert saas.alerts_check(cid, NOW + timedelta(minutes=5), notify) == [1]
    assert notes[-1] == ("alerte", "Acme : Site indisponible", "Site en ligne = 0 (seuil < 1).")
    saas.record(cid, "up", 0, NOW + timedelta(minutes=10))
    assert saas.alerts_check(cid, NOW + timedelta(minutes=10), notify) == []  # cooldown
    saas.record(cid, "up", 1, NOW + timedelta(minutes=15))
    saas.alerts_check(cid, NOW + timedelta(minutes=15), notify)
    assert notes[-1][1] == "Acme : rétabli"
    saas.record(cid, "churn_rate", 9, NOW)
    saas.record(cid, "mrr", 50, NOW)
    fired = saas.alerts_check(cid, NOW + timedelta(minutes=20), notify)
    assert fired == [churn["id"], ltv_rule["id"]]  # a derived KPI (ARR = 600) works too
    assert saas.alerts_check(cid, NOW + timedelta(hours=2), notify) == [churn["id"]]  # after 1 h
    for metric, op, error in [("Bad", ">", "invalide"), ("mrr", "!=", "comparaison")]:
        with pytest.raises(SaasError, match=error):
            saas.add_alert(cid, metric, op, 1)
    saas.delete_alert(churn["id"])
    assert churn["id"] not in [a["id"] for a in saas.alerts(cid)]


# ---- tools, service, API -------------------------------------------------------------------------


def test_saas_tools(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    database = Database(root / "spectre.db")
    Companies(database).create("Acme")
    gate, ctx = Gate(database), tools.make_context(database, root, [str(tmp_path)])
    run = lambda tool, **args: tools.execute(gate, ctx, tool, args)  # noqa: E731
    assert run("set_metric", company="acme", metric="marketing_spend_30d", value=250) == (
        "marketing_spend_30d = 250 enregistré pour Acme"
    )
    assert run("add_monitor", company="", url="https://acme.example").startswith(
        "surveillance #1 de https://acme.example ajoutée pour Acme"
    )
    assert run("add_alert", company="acme", metric="churn_rate", op=">", threshold=5) == (
        "alerte #2 : churn_rate > 5"
    )
    assert "Dépenses marketing (30 j) : 250" in run("saas_report", company="acme")
    assert run("add_monitor", company="acme", url="pas une url").startswith("ÉCHEC : adresse")
    assert run("saas_report", company="Nulle").startswith("ÉCHEC : entreprise")


def test_saas_api(api: Client, service: AssistantService, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from spectre.assistant import saas as saas_module

    monkeypatch.setattr(saas_module, "http_fetch", FakeHttp({"acme.example": (200, {}, b"ok")}))
    monkeypatch.setattr("threading.Thread.start", lambda self: self.run())
    api.json("POST", "/api/assistant/company", {"name": "Acme"})
    status, source = api.json(
        "POST",
        "/api/assistant/company/1/saas/sources",
        {"kind": "uptime", "name": "Site", "url": "https://acme.example", "key": ""},
    )
    assert status == 200 and source["name"] == "Site" and "key_env" not in source
    status, stripe = api.json(
        "POST", "/api/assistant/company/1/saas/sources", {"kind": "stripe", "key": "rk_x"}
    )
    assert status == 200 and "rk_x" not in json.dumps(stripe)
    board = api.json("GET", "/api/assistant/company/1/saas")[1]
    assert board["status"] == {"up": 1.0} and all("key_env" not in s for s in board["sources"])
    assert any(t["metric"] == "uptime_7d" for t in board["tiles"])
    checked = api.json("POST", f"/api/assistant/saas/sources/{stripe['id']}/check", {})[1]
    assert checked["metrics"] == {} and checked["error"].startswith("HTTP 404")
    assert api.json(
        "POST",
        "/api/assistant/company/1/saas/alerts",
        {"metric": "mrr", "op": "<", "threshold": 100},
    )[1]["result"].startswith("alerte #")
    assert api.json(
        "POST",
        "/api/assistant/company/1/saas/metric",
        {"metric": "marketing_spend_30d", "value": 90},
    )[1]["result"].startswith("marketing_spend_30d = 90.0")
    routine = api.json("POST", "/api/assistant/company/1/saas/report", {})[1]["result"]
    assert routine.startswith("routine #1 « Rapport hebdo Acme » : chaque lundi à 9h")
    alert_id = api.json("GET", "/api/assistant/company/1/saas")[1]["alerts"][0]["id"]
    assert api.json("POST", f"/api/assistant/saas/alerts/{alert_id}/delete", {})[1] == {"ok": True}
    assert api.json("POST", f"/api/assistant/saas/sources/{stripe['id']}/delete", {})[1] == {
        "ok": True
    }
    status, body = api.json("POST", "/api/assistant/company/1/saas/sources", {"kind": "ftp"})
    assert status == 400 and "type de source" in body["error"]
    assert api.json("GET", "/api/assistant/company/9/saas")[0] == 400


def test_proactive_collects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from spectre.assistant import saas as saas_module
    from spectre.assistant.config import AssistantConfig
    from spectre.assistant.proactive import Proactive
    from tests.test_assistant_engines import Rooted

    root = tmp_path / "assistant"
    database = Database(root / "spectre.db")
    cid = Companies(database).create("Acme")["id"]
    Saas(database, root).add_source(cid, "uptime", "Site", {"url": "https://acme.example"})
    monkeypatch.setattr(saas_module, "http_fetch", FakeHttp({"acme.example": (500, {}, b"")}))
    proactive = Proactive(
        database, Rooted(root), AssistantConfig(), lambda *a: None, fetch=lambda u: {}
    )  # type: ignore[arg-type]
    proactive.saas(NOW, background=False)
    assert Saas(database, root).latest(cid)["up"] == 0.0
    proactive.saas(NOW + timedelta(minutes=1), background=False)  # nothing due: no call
    assert len(Saas(database, root).history(cid, "up", NOW - timedelta(days=1))) == 1
