"""`/api/assistant/*` routes: the web face of the voice assistant (when it is enabled)."""

from __future__ import annotations

import json
import queue
from typing import Any
from urllib.parse import unquote

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
            handler._json(200, {"reply": service.chat(str(data.get("text", "")), "text")})
        case "POST", ["voice"]:
            handler._json(200, service.remote_voice(handler._raw_body()))
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
        case "GET", ["missions"]:
            handler._json(200, service.missions_list())
        case "POST", ["missions"]:
            data = body()
            handler._json(
                200,
                {
                    "result": service.start_mission(
                        str(data.get("goal", "")), str(data.get("kind", "mission"))
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
