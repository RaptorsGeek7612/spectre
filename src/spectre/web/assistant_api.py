"""`/api/assistant/*` routes: the web face of the voice assistant (when it is enabled)."""

from __future__ import annotations

import json
import queue
from typing import Any
from urllib.parse import unquote

from spectre.assistant import team
from spectre.assistant.meeting import Meetings
from spectre.assistant.remote import Remote
from spectre.assistant.service import AssistantService

HEARTBEAT_S = 15.0


def handle(
    handler: Any,
    service: AssistantService,
    method: str,
    parts: list[str],
    query: dict[str, list[str]],
) -> None:
    """Dispatch one request; `parts` excludes the leading `assistant`."""
    body = handler._body if method == "POST" else (lambda: {})
    match method, parts:
        case "GET", ["status"]:
            handler._json(200, service.status())
        case "GET", ["events"]:
            stream_events(handler, service)
        case "GET", ["history"]:
            handler._json(200, service.history())
        case "POST", ["chat"]:
            data = body()
            joined = [str(a) for a in data.get("attachments") or []]
            handler._json(200, {"reply": service.chat(str(data.get("text", "")), "text", joined)})
        case "POST", ["attachments"]:
            from spectre.attachments import MAX_BYTES

            name = query.get("name", ["fichier"])[0]
            handler._json(200, service.attach(name, handler._raw_body(MAX_BYTES)))
        case "POST", ["voice"]:
            handler._json(200, service.remote_voice(handler._raw_body()))
        case "POST", ["speak"]:
            handler._json(200, {"audio": service.render_speech(str(body().get("text", "")))})
        case "POST", ["frame"]:
            handler._json(200, service.remote_frame(handler._raw_body()))
        case "POST", ["talk"]:
            service.push_to_talk()
            handler._json(200, {"ok": True})
        case "GET", ["approvals"]:
            handler._json(200, service.approvals(query.get("status", ["pending"])[0]))
        case "POST", ["approvals", approval_id, "approve"]:
            handler._json(200, {"result": service.approve(int(approval_id))})
        case "POST", ["approvals", approval_id, "deny"]:
            service.deny(int(approval_id), str(body().get("reason", "")))
            handler._json(200, {"ok": True})
        case "GET", ["agents"]:
            handler._json(200, service.agents())
        case "POST", ["agents"]:
            handler._json(200, {"result": service.create_agent(body())})
        case "POST", ["agents", agent_id, "delete"]:
            handler._json(200, service.delete_agent(int(agent_id)))
        case "GET", ["team"]:
            handler._json(200, service.team())
        case "GET", ["payments", payment_id, "qr"]:
            from spectre.assistant import payments
            from spectre.assistant.actions import ActionError

            try:
                svg = payments.qr(service.ctx, int(payment_id))
            except ActionError as exc:
                raise ValueError(str(exc)) from exc
            handler._send(200, svg.encode("utf-8"), "image/svg+xml")
        case "GET", ["team", key, "portrait"]:
            found = team.portrait(service.root, unquote(key))
            if found is None:
                raise KeyError(key)
            handler._send(200, found[0], found[1])
        case "POST", ["team", key, "portrait"]:
            handler._json(200, service.team_portrait(unquote(key), handler._raw_body()))
        case "POST", ["team", key, "portrait", "delete"]:
            body()
            handler._json(200, service.team_portrait(unquote(key), None))
        case "POST", ["team", key, "portrait", "generate"]:
            body()
            handler._json(200, service.generate_portrait(unquote(key)))
        case "GET", ["team", key, "models"]:
            handler._json(200, service.team_models(unquote(key)))
        case "GET", ["team", key]:
            handler._json(200, service.team_details(unquote(key)))
        case "POST", ["team", key]:
            handler._json(200, service.team_change(unquote(key), body()))
        case "GET", ["call"]:
            since = int(query.get("since", ["0"])[0] or 0)
            handler._json(200, service.call_state(since, int(query.get("ev", ["0"])[0] or 0)))
        case "POST", ["call", "standup"]:
            body()  # read it: a body left unread would spill into the next request
            handler._json(200, service.call_standup())
        case "GET", ["call", "recap"]:
            mission = query.get("mission", [""])[0]
            hours = float(query.get("hours", ["24"])[0] or 24)
            handler._json(200, service.call_recap(int(mission) if mission else None, hours))
        case "GET", ["call", "tree"]:
            handler._json(200, service.call_tree())
        case "GET", ["call", "board"]:
            handler._json(200, service.call_board())
        case "GET", ["call", "replay", mission_id]:
            handler._json(200, service.call_replay(int(mission_id)))
        case "GET", ["call", "session", tool, sid]:
            handler._json(200, service.call_session(tool, unquote(sid)))
        case "POST", ["call", "say"]:
            data = body()
            audio = service.speak_as(str(data.get("agent", "")), str(data.get("text", "")))
            handler._json(200, {"audio": audio})
        case "GET", ["company"]:
            handler._json(200, service.companies())
        case "POST", ["company"]:
            handler._json(
                200, {"result": service.act("create_company", pick(body(), "name", "pitch"))}
            )
        case "GET", ["company", company_id]:
            handler._json(200, service.company(int(company_id)))
        case "GET", ["company", company_id, "dev"]:
            handler._json(200, service.dev(int(company_id)))
        case "POST", ["company", company_id, "dev", "config"]:
            handler._json(200, service.dev_configure(int(company_id), body()))
        case "POST", ["company", company_id, "dev"]:
            dev_args = {"company": str(int(company_id)), "request": str(body().get("request", ""))}
            handler._json(200, {"result": service.act("dev_task", dev_args)})
        case "POST", ["dev", job_id, action]:
            handler._json(200, {"result": service.dev_action(int(job_id), action)})
        case "GET", ["company", company_id, "decisions"]:
            handler._json(200, service.decisions(int(company_id)))
        case "POST", ["company", company_id, "decisions"]:
            board_args = {
                "company": str(int(company_id)),
                "question": str(body().get("question", "")),
            }
            handler._json(200, {"result": service.act("convene_board", board_args)})
        case "POST", ["decisions", decision_id, "review"]:
            handler._json(
                200, {"result": service.act("review_decision", {"decision_id": int(decision_id)})}
            )
        case "POST", ["company", company_id, "experiments"]:
            data = body()
            experiment: dict[str, Any] = {"company": str(int(company_id))} | pick(
                data, "hypothesis", "metric", "direction"
            )
            experiment |= {
                "min_change": float(data.get("min_change", 5)),
                "days": int(data.get("days", 14)),
            }
            handler._json(200, {"result": service.act("start_experiment", experiment)})
        case "POST", ["experiments", experiment_id, "stop"]:
            stop = {"experiment_id": int(experiment_id)}
            handler._json(200, {"result": service.act("stop_experiment", stop)})
        case "POST", ["company", company_id, action]:
            handler._json(200, {"result": company_action(service, company_id, action, body())})
        case "POST", ["tasks", task_id]:
            data = pick(body(), "status", "note")
            handler._json(
                200, {"result": service.act("update_task", {"task_id": int(task_id)} | data)}
            )
        case "POST", ["tasks", task_id, "start"]:
            handler._json(
                200, {"result": service.act("start_tasks", {"task_ids": str(int(task_id))})}
            )
        case "POST", ["missions", mission_id, "steer"]:
            args = {"mission_id": int(mission_id), "message": str(body().get("message", ""))}
            handler._json(200, {"result": service.act("steer_mission", args)})
        case "POST", ["missions", mission_id, "stop"]:
            handler._json(
                200, {"result": service.act("stop_mission", {"mission_id": int(mission_id)})}
            )
        case "GET", ["company", company_id, "saas"]:
            handler._json(200, service.saas_dashboard(int(company_id)))
        case "POST", ["company", company_id, "saas", "sources"]:
            handler._json(200, service.saas_add_source(int(company_id), body()))
        case "POST", ["company", company_id, "saas", "alerts"]:
            data = body()
            alert = {"company": str(int(company_id))} | pick(data, "metric", "op", "label")
            handler._json(
                200,
                {
                    "result": service.act(
                        "add_alert", alert | {"threshold": float(data.get("threshold", 0))}
                    )
                },
            )
        case "POST", ["company", company_id, "saas", "metric"]:
            data = body()
            metric = {"company": str(int(company_id)), "metric": str(data.get("metric", ""))}
            handler._json(
                200,
                {
                    "result": service.act(
                        "set_metric", metric | {"value": float(data.get("value", 0))}
                    )
                },
            )
        case "POST", ["company", company_id, "saas", "report"]:
            handler._json(200, {"result": service.saas_report_routine(int(company_id))})
        case "POST", ["saas", "sources", source_id, "check"]:
            handler._json(200, service.saas_check(int(source_id)))
        case "POST", ["saas", "sources", source_id, "delete"]:
            service.saas().delete_source(int(source_id))
            handler._json(200, {"ok": True})
        case "POST", ["saas", "alerts", alert_id, "delete"]:
            service.saas().delete_alert(int(alert_id))
            handler._json(200, {"ok": True})
        case "GET", ["learning"]:
            handler._json(200, service.learning_state())
        case "POST", ["learning", "proposals", proposal_id, decision]:
            if decision not in ("approve", "reject"):
                raise KeyError(decision)
            handler._json(200, service.learning_decide(int(proposal_id), decision == "approve"))
        case "POST", ["learning", "skills", name, action]:
            handler._json(200, service.learning_skill(unquote(name), action))
        case "GET", ["search"]:
            handler._json(200, service.search(query.get("q", [""])[0]))
        case "POST", ["missions", mission_id, "rollback"]:
            handler._json(200, {"result": service.rollback_mission(int(mission_id))})
        case "GET", ["meetings"]:
            handler._json(
                200, {"meetings": service.meetings(), "recording": service.recorder.recording}
            )
        case "GET", ["meetings", meeting_id]:
            handler._json(200, service.meeting(int(meeting_id)))
        case "POST", ["meetings", "start"]:
            data = body()
            handler._json(
                200, service.meeting_start(str(data.get("title", "")), str(data.get("company", "")))
            )
        case "POST", ["meetings", "stop"]:
            handler._json(200, service.meeting_stop())
        case "POST", ["meetings", "upload"]:
            from spectre.assistant.meeting import MAX_UPLOAD

            handler._json(
                200,
                service.meeting_upload(
                    handler._raw_body(MAX_UPLOAD),
                    query.get("title", [""])[0],
                    query.get("company", [""])[0],
                ),
            )
        case "POST", ["meetings", meeting_id, "delete"]:
            Meetings(service.db).delete(int(meeting_id))
            handler._json(200, {"ok": True})
        case "GET", ["push"]:
            handler._json(
                200,
                {"key": service.push.public_key(), "devices": len(service.push.subscriptions())},
            )
        case "POST", ["push", "subscribe"]:
            data = body()
            row = service.push.subscribe(data.get("subscription") or {}, str(data.get("label", "")))
            handler._json(200, {"ok": True, "id": row["id"]})
        case "POST", ["push", "unsubscribe"]:
            service.push.unsubscribe(str(body().get("endpoint", "")))
            handler._json(200, {"ok": True})
        case "POST", ["push", "test"]:
            sent = service.push.send("Spectre", "Les notifications fonctionnent sur cet appareil.")
            handler._json(200, {"sent": sent})
        case "GET", ["trust"]:
            handler._json(200, service.trust_board())
        case "GET", ["costs"]:
            company = query.get("company", [""])[0]
            days = query.get("days", ["30"])[0]
            handler._json(
                200,
                service.costs(
                    int(company) if company.isdigit() else None, int(days) if days.isdigit() else 30
                ),
            )
        case "GET", ["routines"]:
            handler._json(200, service.routines())
        case "POST", ["routines"]:
            fields = pick(body(), "name", "schedule", "prompt", "kind", "agent", "company")
            handler._json(200, {"result": service.act("create_routine", dict(fields))})
        case "POST", ["routines", routine_id]:
            change = {"routine": routine_id} | pick(body(), "enabled", "schedule", "prompt")
            handler._json(200, {"result": service.act("update_routine", dict(change))})
        case "POST", ["routines", routine_id, "run"]:
            handler._json(200, {"result": service.act("run_routine", {"routine": routine_id})})
        case "POST", ["routines", routine_id, "delete"]:
            from spectre.assistant.routines import Routines

            row = Routines(service.db).delete(routine_id)
            handler._json(200, {"result": f"routine supprimée : {row['name']}"})
        case "GET", ["webhooks"]:
            handler._json(200, service.webhooks_list(base_url(handler)))
        case "POST", ["webhooks"]:
            handler._json(200, service.create_webhook(body(), base_url(handler)))
        case "POST", ["webhooks", name, "delete"]:
            handler._json(200, service.delete_webhook(unquote(name)))
        case "GET", ["telegram"]:
            handler._json(200, service.telegram_status())
        case "POST", ["telegram", "token"]:
            handler._json(200, service.telegram_token(str(body().get("token", ""))))
        case "POST", ["telegram", "pair"]:
            handler._json(200, service.telegram_pair())
        case "POST", ["telegram", "unlink"]:
            handler._json(200, service.telegram_unlink(int(body().get("chat_id", 0))))
        case "GET", ["models"]:
            handler._json(200, service.models())
        case "GET", ["models", provider]:
            handler._json(200, service.provider_models(unquote(provider)))
        case "POST", ["models"]:
            handler._json(200, service.set_engine(body()))
        case "GET", ["remote"]:
            handler._json(200, remote(handler).status(handler.app.auth.enabled))
        case "POST", ["remote"]:
            handler._json(200, enable_remote(handler))
        case "GET", ["missions"]:
            handler._json(200, service.missions_list())
        case "POST", ["missions"]:
            data = body()
            handler._json(
                200,
                {
                    "result": service.start_mission(
                        str(data.get("goal", "")),
                        str(data.get("kind", "mission")),
                        str(data.get("agent", "")),
                    )
                },
            )
        case "GET", ["initiatives"]:
            handler._json(200, service.initiatives(query.get("status", ["pending"])[0]))
        case "POST", ["initiatives", initiative_id]:
            service.resolve_initiative(int(initiative_id), str(body().get("status", "")))
            handler._json(200, {"ok": True})
        case "GET", ["memory"]:
            handler._json(
                200, service.facts(query.get("q", [""])[0], query.get("category", [""])[0] or None)
            )
        case "POST", ["memory", fact_id, "forget"]:
            handler._json(200, service.forget(int(fact_id)))
        case "POST", ["memory", fact_id, "correct"]:
            handler._json(200, service.correct(int(fact_id), str(body().get("value", ""))))
        case "GET", ["audit"]:
            handler._json(200, service.audit())
        case "GET", ["faces"]:
            handler._json(
                200, {"camera": service.camera is not None, "people": service.faces.people()}
            )
        case "POST", ["faces", "enroll"]:
            name = str(body().get("name", "")).strip() or service.config.user_name
            handler._json(200, {"name": name, "samples": service.enroll_face(name)})
        case "POST", ["faces", name, "forget"]:
            handler._json(200, {"removed": service.forget_face(unquote(name))})
        case "GET", ["config"]:
            handler._json(200, service.config.__dict__)
        case "POST", ["config"]:
            handler._json(200, service.update_config(body()))
        case _:
            raise KeyError("/".join(parts))


def base_url(handler: Any) -> str:
    """The address this page was reached at (for webhook URLs)."""
    host = handler.headers.get("Host") or "127.0.0.1"
    scheme = "https" if host.endswith(".ts.net") else "http"
    return f"{scheme}://{host}"


def pick(data: dict[str, Any], *keys: str) -> dict[str, str]:
    """The given keys of a request body, as text (missing ones left out)."""
    return {k: str(data[k]) for k in keys if k in data and data[k] is not None}


def company_action(service: AssistantService, company_id: str, action: str, data: Any) -> str:
    """`POST /company/<id>/<action>`: the matching tool, through the gate."""
    company = {"company": str(int(company_id))}
    match action:
        case "post":
            return service.act("set_post", company | pick(data, "department", "agent"))
        case "autopilot":
            return service.act("set_autopilot", company | {"on": bool(data.get("on"))})
        case "tasks":
            args: dict[str, Any] = company | pick(
                data, "title", "department", "detail", "depends_on", "agent"
            )
            if "priority" in data:
                args["priority"] = int(data["priority"])
            return service.act("add_task", args)
        case "plan":
            return service.act("plan_company", company | pick(data, "objective"))
        case "start":
            return service.act("start_tasks", company | pick(data, "task_ids"))
    raise KeyError(action)


def remote(handler: Any) -> Remote:
    return Remote(int(handler.server.server_address[1]))


def enable_remote(handler: Any) -> dict[str, Any]:
    """Publish Spectre on the tailnet and accept its host name; only with a password."""
    if not handler.app.auth.enabled:
        raise ValueError(
            "définis d'abord un mot de passe (tools\\spectre-password.cmd) puis relance Spectre"
        )
    access = remote(handler)
    if not access.enable():
        raise ValueError(
            "Tailscale n'a pas pu publier Spectre : vérifie qu'il est connecté et que HTTPS "
            "est activé sur ton tailnet"
        )
    info = access.status(True)
    allowed = handler.app.allowed_hosts
    if info["dns"] and allowed is not None:
        allowed.add(info["dns"].lower())
    return info


def stream_events(handler: Any, service: AssistantService) -> None:
    """Server-Sent Events until the browser disconnects."""
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.close_connection = True
    events = service.subscribe()
    try:
        while True:
            try:
                event = events.get(timeout=HEARTBEAT_S)
                payload = (
                    f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                )
            except queue.Empty:
                payload = ": ping\n\n"
            handler.wfile.write(payload.encode("utf-8"))
            handler.wfile.flush()
    except OSError:
        pass
    finally:
        service.unsubscribe(events)
