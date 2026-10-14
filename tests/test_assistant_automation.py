"""Automation: routines (schedules), signed webhooks, the Telegram gateway, agent questions."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import tools
from spectre.assistant.brain import Reply
from spectre.assistant.db import Database
from spectre.assistant.engines import Engines
from spectre.assistant.governance import Gate
from spectre.assistant.routines import (
    RoutineError,
    Routines,
    cron_next,
    describe,
    next_run,
    parse_schedule,
)
from spectre.assistant.service import AssistantService
from spectre.assistant.telegram import Telegram, read_token, save_token
from spectre.assistant.webhooks import (
    Rejected,
    WebhookError,
    Webhooks,
    sign_github,
    sign_stripe,
    summary,
)
from tests.test_assistant_agents import db  # noqa: F401 - fixture
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client

TZ = timezone(timedelta(hours=2))
NOW = datetime(2026, 10, 14, 10, 30, tzinfo=TZ)  # a Wednesday


# ---- schedules -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "canonical"),
    [
        ("tous les jours à 9h", "cron:0 9 * * *"),
        ("Chaque jour à 18h30", "cron:30 18 * * *"),
        ("every day at 7:05", "cron:5 7 * * *"),
        ("9h15", "cron:15 9 * * *"),
        ("en semaine à 8h30", "cron:30 8 * * 1-5"),
        ("le week-end à 10h", "cron:0 10 * * 0,6"),
        ("chaque lundi à 9h", "cron:0 9 * * 1"),
        ("lundi et jeudi à 18h", "cron:0 18 * * 1,4"),
        ("le 1er de chaque mois à 9h", "cron:0 9 1 * *"),
        ("toutes les 2 heures", "every:7200"),
        ("toutes les heures", "every:3600"),
        ("every 30 minutes", "every:1800"),
        ("0 9 * * 1", "cron:0 9 * * 1"),
        ("*/15 8-18 * * 1-5", "cron:*/15 8-18 * * 1-5"),
        ("dans 30 minutes", "once:2026-10-14T11:00:00+02:00"),
        ("dans 2 jours", "once:2026-10-16T10:30:00+02:00"),
        ("2026-11-02 à 14h", "once:2026-11-02T14:00:00+02:00"),
    ],
)
def test_parse_schedule(spec: str, canonical: str) -> None:
    assert parse_schedule(spec, NOW) == canonical


@pytest.mark.parametrize(
    ("spec", "error"),
    [
        ("", "horaire vide"),
        ("toutes les 2 minutes", "5 minutes"),
        ("quand il pleut", "horaire illisible"),
        ("2026-01-01 à 9h", "déjà passée"),
        ("tous les jours à 25h", "heure invalide"),
        ("le 30 de chaque mois à 9h", "de 1 à 28"),
        ("61 * * * *", "hors limites"),
    ],
)
def test_parse_schedule_errors(spec: str, error: str) -> None:
    with pytest.raises(RoutineError, match=error):
        parse_schedule(spec, NOW)


def test_next_run_and_describe() -> None:
    assert cron_next("0 9 * * *", NOW) == datetime(2026, 10, 15, 9, 0, tzinfo=TZ)
    assert cron_next("0 9 * * 1", NOW) == datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
    assert cron_next("0 9 1 * *", NOW) == datetime(2026, 11, 1, 9, 0, tzinfo=TZ)
    assert cron_next("0 9 13 * 5", NOW) == datetime(2026, 10, 16, 9, 0, tzinfo=TZ)  # either one
    assert cron_next("45 10 * * *", NOW) == datetime(2026, 10, 14, 10, 45, tzinfo=TZ)
    assert next_run("every:3600", NOW) == NOW + timedelta(hours=1)
    assert next_run("once:2026-10-14T09:00:00+02:00", NOW) is None
    with pytest.raises(RoutineError, match="aucune date"):
        cron_next("0 9 31 2 *", NOW)
    with pytest.raises(RoutineError, match="5 champs"):
        cron_next("0 9 *", NOW)
    assert describe("cron:0 9 * * *") == "tous les jours à 9h"
    assert describe("cron:30 8 * * 1-5") == "en semaine à 8h30"
    assert describe("cron:0 18 * * 1,4") == "chaque lundi et jeudi à 18h"
    assert describe("cron:0 9 1 * *") == "le 1 de chaque mois à 9h"
    assert describe("cron:*/15 8-18 * * 1-5") == "cron */15 8-18 * * 1-5"
    assert describe("cron:0 9 * 1 1-5") == "cron 0 9 * 1 1-5"
    assert describe("every:7200") == "toutes les 2 heures"
    assert describe("every:3600") == "toutes les heures"
    assert describe("every:1800") == "toutes les 30 minutes"
    assert describe("once:2026-11-02T14:00:00+02:00") == "une fois, le 02/11/2026 à 14:00"


# ---- routines ------------------------------------------------------------------------------------


def test_routines_storage(db: Database) -> None:  # noqa: F811
    routines = Routines(db)
    row = routines.create("Point ventes", "chaque lundi à 9h", "Résume les ventes", now=NOW)
    assert row["when"] == "chaque lundi à 9h" and row["next_run"] == "2026-10-19T09:00:00+02:00"
    assert routines.get("point ventes")["id"] == row["id"] and routines.get(f"#{row['id']}")
    for args, error in [
        (("P", "9h", "x y z"), "2 à 60"),
        (("Point ventes", "9h", "faire"), "existe déjà|s'appelle déjà"),
        (("Autre", "9h", "ok"), "décris"),
    ]:
        with pytest.raises(RoutineError, match=error):
            routines.create(*args, now=NOW)
    with pytest.raises(RoutineError, match="type"):
        routines.create("Autre", "9h", "faire ça", kind="poème", now=NOW)
    paused = routines.update(row["id"], enabled=False, now=NOW)
    assert paused["enabled"] == 0
    moved = routines.update(
        row["id"], schedule="tous les jours à 7h", prompt="Autre chose", enabled=True, now=NOW
    )
    assert moved["when"] == "tous les jours à 7h" and moved["prompt"] == "Autre chose"
    assert moved["next_run"] == "2026-10-15T07:00:00+02:00" and moved["enabled"] == 1
    once = routines.create("Unique", "dans 30 minutes", "Rappelle-moi", kind="rappel", now=NOW)
    with pytest.raises(RoutineError, match="déjà passée"):
        routines.update(once["id"], enabled=True, now=NOW + timedelta(hours=2))
    assert routines.delete("unique")["name"] == "Unique"
    with pytest.raises(RoutineError, match="introuvable"):
        routines.get("Unique")


def test_routines_tick(db: Database) -> None:  # noqa: F811
    from spectre.assistant.company import Companies

    routines = Routines(db)
    acme = Companies(db).create("Acme", "SaaS")
    remind = routines.create("Eau", "toutes les 2 heures", "Bois de l'eau", kind="rappel", now=NOW)
    weekly = routines.create(
        "Ventes",
        "chaque lundi à 9h",
        "Point des ventes",
        agent="Gétro",
        company_id=acme["id"],
        now=NOW,
    )
    ask = routines.create("Veille", "dans 1 heure", "Quoi de neuf ?", kind="question", now=NOW)
    notes: list[tuple[str, str, str]] = []
    asked: list[str] = []

    def answer(prompt: str, system: str) -> Reply:
        asked.append(prompt)
        return Reply("Rien de neuf.", "", False)

    later = NOW + timedelta(days=6)  # PC off for days: each due routine runs once
    assert routines.tick(later, lambda *a: notes.append(a), answer, background=False) == [
        remind["id"],
        weekly["id"],
        ask["id"],
    ]
    assert notes == [("routine", "Eau", "Bois de l'eau"), ("routine", "Veille", "Rien de neuf.")]
    mission = db.one("SELECT * FROM missions")
    assert mission is not None and mission["goal"] == "Point des ventes"
    plan = json.loads(mission["plan"])
    assert (
        plan["agent"] == "sonnet"
        and plan["routine"] == weekly["id"]
        and "« Acme » : SaaS" in plan["brief"]
    )
    assert routines.get(weekly["id"])["last_status"] == "mission #1"
    assert routines.get(ask["id"])["enabled"] == 0  # once: done
    assert routines.tick(later, lambda *a: None, answer, background=False) == []
    assert routines.get(remind["id"])["next_run"] == (later + timedelta(hours=2)).isoformat()


def test_routine_failures(db: Database) -> None:  # noqa: F811
    routines = Routines(db)
    row = routines.create("Veille", "toutes les heures", "Quoi de neuf ?", kind="question", now=NOW)
    notes: list[tuple[str, str, str]] = []

    def broken(prompt: str, system: str) -> Reply:
        raise RuntimeError("plus de quota")

    for _ in range(3):
        routines.run(routines.get(row["id"]), lambda *a: notes.append(a), broken, background=False)
    assert routines.get(row["id"])["failures"] == 3
    assert notes[0][1] == "Routine « Veille » en échec" and "plus de quota" in notes[0][2]
    assert "3 échecs d'affilée" in notes[-1][2]
    routines.run(
        routines.get(row["id"]),
        lambda *a: None,
        lambda p, s: Reply("ok", "", False),
        background=False,
    )
    assert routines.get(row["id"])["failures"] == 0
    routines.run(
        routines.get(row["id"]),
        lambda *a: notes.append(a),
        lambda p, s: Reply("down", "", True),
        background=False,
    )
    assert notes[-1][2] == "Échec : down"


def test_routine_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "assistant"
    database = Database(root / "spectre.db")
    gate, ctx = Gate(database), tools.make_context(database, root, [str(tmp_path)])
    run = lambda tool, **args: tools.execute(gate, ctx, tool, args)  # noqa: E731
    assert run("list_routines") == "aucune routine"
    created = run(
        "create_routine", name="Eau", schedule="toutes les 2 heures", prompt="Bois", kind="rappel"
    )
    assert created.startswith("routine #1 « Eau » : toutes les 2 heures (prochaine : ")
    assert run("create_routine", name="X", schedule="jamais", prompt="truc").startswith(
        "ÉCHEC : le nom"
    )
    assert run("create_routine", name="Xy", schedule="9h", prompt="truc", agent="Zorg").startswith(
        "ÉCHEC : agent inconnu"
    )
    assert run(
        "create_routine", name="Xy", schedule="9h", prompt="truc", company="Nulle"
    ).startswith("ÉCHEC : entreprise")
    assert "#1 Eau [rappel] toutes les 2 heures — Bois" in run("list_routines")
    assert (
        run("update_routine", routine="eau", enabled="non")
        == "routine #1 : toutes les 2 heures, en pause"
    )
    assert "[rappel, en pause]" in run("list_routines")
    assert run("run_routine", routine="1") == "routine « Eau » lancée (dans moins d'une minute)"
    assert Routines(database).get(1)["enabled"] == 1
    assert run("delete_routine", routine="1").startswith("EN ATTENTE DE VALIDATION")
    assert run("list_webhooks").startswith("aucun webhook")
    Webhooks(database).create("ci", "github")
    assert run("list_webhooks") == "/hooks/ci (github, notify) : 0 reçu(s)"


def test_proactive_runs_routines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from spectre.assistant.config import AssistantConfig
    from spectre.assistant.proactive import Proactive
    from tests.test_assistant_engines import Rooted

    root = tmp_path / "assistant"
    database = Database(root / "spectre.db")
    Routines(database).create(
        "Veille", "toutes les heures", "Quoi de neuf ?", kind="question", now=NOW
    )
    seen: list[Any] = []
    monkeypatch.setattr(
        Engines,
        "ask_chain",
        lambda self, refs, p, s, **kw: (
            seen.append((refs, kw)) or (Reply("Calme.", "", False), refs[0])
        ),
    )
    config = AssistantConfig(fallback_models=["haiku"])
    notes: list[Any] = []
    proactive = Proactive(
        database, Rooted(root), config, lambda *a: notes.append(a), fetch=lambda u: {}
    )  # type: ignore[arg-type]
    assert proactive.routines(NOW + timedelta(hours=2), background=False) == [1]
    assert seen == [(["opus", "haiku"], {"tools": True})]
    assert notes[-1] == ("routine", "Veille", "Calme.")


# ---- webhooks ------------------------------------------------------------------------------------


def github(
    secret: str, payload: dict[str, Any], event: str = "pull_request", delivery: str = "d1"
) -> tuple[dict[str, str], bytes]:
    body = json.dumps(payload).encode()
    return (
        {
            "X-Hub-Signature-256": sign_github(secret, body),
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
        },
        body,
    )


def test_webhook_config(db: Database) -> None:  # noqa: F811
    hooks = Webhooks(db)
    row = hooks.create("Mon CI !", "github", events=["workflow_run", " "])
    assert (
        row["name"] == "mon-ci" and len(row["secret"]) == 48 and row["events"] == ["workflow_run"]
    )
    for args, kwargs, error in [
        (("x", "github"), {}, "2 à 40"),
        (("ci2", "gitlab"), {}, "source"),
        (("ci2", "github"), {"action": "dance"}, "action"),
        (("ci2", "github"), {"action": "mission"}, "dis ce que"),
        (("pay", "stripe"), {"secret": "abc"}, "whsec_"),
        (("mon ci", "github"), {}, "existe déjà"),
    ]:
        with pytest.raises(WebhookError, match=error):
            hooks.create(*args, **kwargs)
    assert hooks.delete("mon-ci")["name"] == "mon-ci"
    with pytest.raises(WebhookError, match="introuvable"):
        hooks.get("mon-ci")


def test_github_webhook(db: Database) -> None:  # noqa: F811
    hooks = Webhooks(db)
    secret = hooks.create("ci", "github", events=["pull_request", "workflow_run.completed"])[
        "secret"
    ]
    notes: list[Any] = []
    payload = {
        "action": "opened",
        "repository": {"full_name": "me/spectre"},
        "sender": {"login": "me"},
        "pull_request": {"title": "v0.9"},
    }
    headers, body = github(secret, payload)
    assert hooks.receive("ci", headers, body, lambda *a: notes.append(a)) == "notification envoyée"
    assert notes == [
        ("webhook", "Webhook « ci »", "GitHub pull_request.opened sur me/spectre « v0.9 » (par me)")
    ]
    assert hooks.receive("ci", headers, body, lambda *a: notes.append(a)) == "déjà reçu"
    assert hooks.get("ci")["received"] == 1
    headers, body = github(secret, {"action": "created"}, event="issue_comment", delivery="d2")
    assert (
        hooks.receive("ci", headers, body, print)
        == "ignoré (issue_comment.created n'est pas suivi)"
    )
    headers, body = github(secret, {"zen": "x"}, event="ping", delivery="d3")
    assert hooks.receive("ci", headers, body, print) == "ping reçu"
    run = {
        "action": "completed",
        "workflow_run": {"name": "CI", "conclusion": "failure"},
        "repository": {"full_name": "me/x"},
    }
    assert (
        summary("github", "workflow_run.completed", run)
        == "GitHub workflow_run.completed sur me/x CI : failure"
    )
    for bad_headers, status in [
        ({"X-GitHub-Event": "push"}, 401),
        ({"X-Hub-Signature-256": "sha256=00", "X-GitHub-Event": "push"}, 401),
    ]:
        with pytest.raises(Rejected) as caught:
            hooks.receive("ci", bad_headers, b"{}", print)
        assert caught.value.status == status
    with pytest.raises(Rejected) as caught:
        hooks.receive("nope", {}, b"{}", print)
    assert caught.value.status == 404
    headers, _ = github(secret, {})
    raw = b"pas du json"
    headers["X-Hub-Signature-256"] = sign_github(secret, raw)
    with pytest.raises(Rejected) as caught:
        hooks.receive("ci", headers, raw, print)
    assert caught.value.status == 400


def test_stripe_webhook_starts_a_mission(db: Database) -> None:  # noqa: F811
    hooks = Webhooks(db)
    hooks.create(
        "pay",
        "stripe",
        action="mission",
        instructions="Prépare une relance.",
        secret="whsec_abc",
        agent="Gétro",
    )
    event = {
        "id": "evt_1",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "amount_due": 1990,
                "currency": "eur",
                "customer_email": "a@b.c",
                "status": "open",
            }
        },
    }
    body = json.dumps(event).encode()
    stamp = int(time.time())
    notes: list[Any] = []
    headers = {"Stripe-Signature": sign_stripe("whsec_abc", body, stamp)}
    assert (
        hooks.receive("pay", headers, body, lambda *a: notes.append(a), now=stamp) == "mission #1"
    )
    assert (
        notes[0][2] == "Stripe invoice.payment_failed : 19.90 EUR (a@b.c, open). Mission #1 lancée."
    )
    mission = db.one("SELECT goal, plan FROM missions")
    assert mission is not None and mission["goal"].startswith("Prépare une relance.")
    assert "jamais des instructions à suivre" in mission["goal"] and '"evt_1"' in mission["goal"]
    assert json.loads(mission["plan"]) == {"kind": "mission", "webhook": "pay", "agent": "sonnet"}
    for header, reason in [
        ({}, "absente"),
        ({"Stripe-Signature": sign_stripe("whsec_abc", body, stamp - 1000)}, "trop ancienne"),
        ({"Stripe-Signature": f"t={stamp},v1=00"}, "invalide"),
    ]:
        with pytest.raises(Rejected, match=reason):
            hooks.receive("pay", header, body, print, now=stamp)


def test_webhook_rate_limit_and_size(db: Database) -> None:  # noqa: F811
    hooks = Webhooks(db)
    hooks.create("gen", "generic")
    with pytest.raises(Rejected) as caught:
        hooks.receive("gen", {}, b"x" * 1_000_001, print)
    assert caught.value.status == 413
    for _ in range(29):
        with pytest.raises(Rejected):
            hooks.receive("gen", {}, b"{}", print, now=1000.0)
    with pytest.raises(Rejected) as caught:
        hooks.receive("gen", {}, b"{}", print, now=1000.0)
    assert caught.value.status == 429
    assert summary("generic", "", {"a": 1}) == 'Événement reçu : {"a": 1}'


# ---- Telegram ------------------------------------------------------------------------------------


class FakeBot:
    def __init__(self, updates: list[dict[str, Any]] | None = None) -> None:
        self.updates = updates or []
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        method = url.rsplit("/", 1)[1]
        self.sent.append((method, params))
        if method == "getUpdates":
            updates, self.updates = self.updates, []
            return {"ok": True, "result": updates}
        if method == "getMe":
            return {"ok": True, "result": {"username": "spectre_bot"}}
        return {"ok": True, "result": {}}

    def texts(self) -> list[tuple[int, str]]:
        return [(p["chat_id"], p["text"]) for m, p in self.sent if m == "sendMessage"]


def update(uid: int, chat: int, text: str, kind: str = "private") -> dict[str, Any]:
    return {
        "update_id": uid,
        "message": {"chat": {"id": chat, "type": kind, "first_name": "Olivier"}, "text": text},
    }


TOKEN = "123456789:" + "A" * 35


def test_token_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("GROQ_API_KEY=x\nTELEGRAM_BOT_TOKEN=old\n", encoding="utf-8")
    save_token(tmp_path, TOKEN)
    assert (tmp_path / ".env").read_text(
        encoding="utf-8"
    ) == f"GROQ_API_KEY=x\nTELEGRAM_BOT_TOKEN={TOKEN}\n"
    assert (
        read_token(tmp_path, {}) == TOKEN
        and read_token(tmp_path, {"TELEGRAM_BOT_TOKEN": "env"}) == "env"
    )
    with pytest.raises(ValueError, match="BotFather"):
        save_token(tmp_path, "pas un jeton")


def test_telegram_pairing_and_chat(db: Database, tmp_path: Path) -> None:  # noqa: F811
    bot = FakeBot()
    replies: list[tuple[str, int]] = []
    tg = Telegram(
        tmp_path,
        db,
        lambda text, chat: replies.append((text, chat)) or f"écho : {text}",
        transport=bot,
        environ={"TELEGRAM_BOT_TOKEN": TOKEN},
    )
    assert tg.connect() == "spectre_bot"
    code = tg.pairing_code(now=1000.0)
    bot.updates = [
        update(1, 42, "salut"),  # not paired: ignored, no answer
        update(2, 7, f"/start {code}", kind="group"),  # groups are never served
        update(3, 42, "/start 000000" if code != "000000" else "/start 111111"),
        update(4, 42, f"/start {code}"),
        update(5, 42, "Quelle heure ?"),
        update(6, 42, "/aide"),
        {"update_id": 7, "message": {"chat": {"id": 42}}},
    ]
    assert tg.poll(timeout=0, now=1000.0) == 3
    assert tg.offset == 8 and tg.chats() == [{"id": 42, "name": "Olivier"}]
    assert replies == [("Quelle heure ?", 42)]
    texts = bot.texts()
    assert texts[0][1].startswith("C'est fait : je te reconnais ici.")
    assert texts[1] == (42, "écho : Quelle heure ?") and texts[2][1].startswith("Écris-moi")
    assert tg.pending_code(now=1000.0) == ""  # used once
    assert tg.pairing_code(now=0.0) and tg.pending_code(now=10_000.0) == ""  # expired
    bot.sent.clear()
    assert tg.broadcast("x" * 4500) == 1
    assert [len(t) for _, t in bot.texts()] == [4000, 500]
    tg.unlink(42)
    assert tg.chats() == [] and tg.status()["configured"] is True
    assert Telegram(tmp_path, db, print, transport=bot, environ={}).broadcast("x") == 0


def test_telegram_errors(db: Database, tmp_path: Path) -> None:  # noqa: F811
    tg = Telegram(
        tmp_path,
        db,
        print,
        transport=lambda *a: {"ok": False, "description": "Unauthorized"},
        environ={"TELEGRAM_BOT_TOKEN": TOKEN},
    )
    with pytest.raises(ConnectionError, match="Unauthorized"):
        tg.connect()
    db.set_kv("telegram_chats", "pas du json")
    assert tg.chats() == []
    db.set_kv("telegram_pair", "123|jamais")
    assert tg.pending_code() == ""
    assert not Telegram(tmp_path, db, print, environ={}).start()


# ---- service, server and tools -------------------------------------------------------------------


def test_service_telegram(service: AssistantService, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    bot = FakeBot()
    service.telegram.transport = bot
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    with pytest.raises(ValueError, match="BotFather"):
        service.telegram_token("faux")
    monkeypatch.setattr(service.telegram, "start", lambda: True)
    assert service.telegram_token(TOKEN)["username"] == "spectre_bot"
    code = service.telegram_pair()["code"]
    assert len(code) == 6
    service.telegram.handle(
        {"id": 5, "type": "private", "first_name": "O"}, f"/start {code}", time.time()
    )
    assert service.telegram_status()["chats"] == [{"id": 5, "name": "O"}]
    approval = tools.execute(service.gate, service.ctx, "delete_file", {"path": "x"})
    assert approval.startswith("EN ATTENTE")
    assert service._telegram_reply("/deny 1", 5) == "Refusé."
    assert service._telegram_reply("/approve 1", 5).startswith(
        "Impossible : demande #1 déjà traitée"
    )
    assert service._telegram_reply("/status", 5).startswith("Cerveau : Opus 5.5.")
    assert service._telegram_reply("bonjour", 5) == "Réponse."
    sent: list[str] = []
    monkeypatch.setattr(service.telegram, "broadcast", lambda text: sent.append(text) or 1)
    monkeypatch.setattr("threading.Thread.start", lambda self: self.run())
    service._on_initiative("mission", "Mission terminée", "Rapport prêt.")
    tools.execute(service.gate, service.ctx, "delete_file", {"path": "y"})
    service.poll_changes()
    assert sent[0] == "Mission terminée\nRapport prêt."
    assert (
        sent[1].startswith("Spectre attend ta validation (#2, delete_file)")
        and "/approve 2" in sent[1]
    )
    service.config.telegram_notify = False
    service._on_initiative("mission", "x", "y")
    assert len(sent) == 2
    assert service.telegram_unlink(5)["chats"] == []
    service.telegram.environ = {}
    (service.root / ".env").unlink()
    with pytest.raises(ValueError, match="jeton du bot"):
        service.telegram_pair()


def test_hooks_endpoint(api: Client, service: AssistantService) -> None:  # noqa: F811
    status, created = api.json(
        "POST",
        "/api/assistant/webhooks",
        {"name": "ci", "source": "github", "events": "pull_request, push"},
    )
    assert status == 200 and created["url"].endswith("/hooks/ci") and len(created["secret"]) == 48
    assert created["events"] == ["pull_request", "push"]
    listed = api.json("GET", "/api/assistant/webhooks")[1]
    assert listed[0]["secret"] == created["secret"][:6] + "…"
    headers, body = github(
        created["secret"], {"action": "opened", "repository": {"full_name": "me/x"}}
    )
    status, data = api.json("POST", "/hooks/ci", raw=body, headers=headers)
    assert status == 200 and data["result"] == "notification envoyée"
    status, data = api.json("POST", "/hooks/ci", raw=body, headers={"X-GitHub-Event": "push"})
    assert status == 401 and data["result"] == "signature absente"
    assert service.db.all("SELECT text FROM events WHERE kind = 'webhook_refused'") == [
        {"text": "ci: signature absente"}
    ]
    assert api.json("POST", "/api/assistant/webhooks/ci/delete", {})[1] == {"name": "ci"}
    status, data = api.json("POST", "/api/assistant/webhooks", {"name": "x"})
    assert status == 400


def test_automation_api(api: Client, service: AssistantService) -> None:  # noqa: F811
    status, body = api.json(
        "POST",
        "/api/assistant/routines",
        {"name": "Eau", "schedule": "toutes les heures", "prompt": "Bois", "kind": "rappel"},
    )
    assert status == 200 and body["result"].startswith("routine #1 « Eau »")
    assert api.json("GET", "/api/assistant/routines")[1][0]["when"] == "toutes les heures"
    assert api.json("POST", "/api/assistant/routines/1", {"enabled": "non"})[1]["result"].endswith(
        "en pause"
    )
    assert api.json("POST", "/api/assistant/routines/1/run", {})[1]["result"].startswith(
        "routine « Eau » lancée"
    )
    assert (
        api.json("POST", "/api/assistant/routines/1/delete", {})[1]["result"]
        == "routine supprimée : Eau"
    )
    status, body = api.json(
        "POST", "/api/assistant/routines", {"name": "Eau", "schedule": "jamais", "prompt": "Bois"}
    )
    assert status == 400 and "horaire illisible" in body["error"]
    tg = api.json("GET", "/api/assistant/telegram")[1]
    assert tg["notify"] is True and tg["chats"] == []
    assert api.json("POST", "/api/assistant/telegram/unlink", {"chat_id": 3})[1]["chats"] == []


def test_ask_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from spectre.assistant.custom_agents import CustomAgents

    root = tmp_path / "assistant"
    database = Database(root / "spectre.db")
    from spectre.assistant.providers import Providers

    CustomAgents(database, Providers(root, environ={})).create(
        "Nova", "lmstudio:gemma", "Finance", "Chiffres sourcés"
    )
    calls: list[Any] = []

    def ask_chain(self: Engines, refs: list[str], prompt: str, system: str, **kw: Any) -> Any:
        calls.append((refs, prompt, system))
        return (
            Reply("Marge de 40 %.", "", False) if refs[0] != "mistral" else Reply("panne", "", True)
        ), refs[0]

    monkeypatch.setattr(Engines, "ask_chain", ask_chain)
    gate, ctx = Gate(database), tools.make_context(database, root, [str(tmp_path)])
    run = lambda tool, **args: tools.execute(gate, ctx, tool, args)  # noqa: E731
    assert (
        run("ask_agent", agent="nova", message="Quelle marge ?") == "Nova répond : Marge de 40 %."
    )
    refs, prompt, system = calls[0]
    assert refs == ["lmstudio:gemma"] and "Tu es Nova" in system and "Ton rôle : Finance" in system
    assert "Tes consignes : Chiffres sourcés" in system
    assert run("ask_agent", agent="Kyra", message="Une idée ?") == "Kyra répond : Marge de 40 %."
    assert calls[1][0] == ["chatgpt"]
    assert run("ask_agent", agent="Syfer", message="Audit ?").startswith(
        "ÉCHEC : Syfer n'a pas pu répondre"
    )
    assert run("ask_agent", agent="Zorg", message="?").startswith("ÉCHEC : agent inconnu")
    assert run("ask_agent", agent="Nova", message=" ").startswith("ÉCHEC : message vide")
    assert (
        database.all("SELECT text FROM events WHERE kind = 'agent_message'")[0]["text"]
        == "→ Nova : Quelle marge ?"
    )
