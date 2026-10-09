"""Many requests in one go: `spectre batch FILE`.

Two modes:
- **API** (default): the Message Batches API, 50% cheaper, asynchronous (minutes, up to 24 h).
  Each stage goes out as one batch for every request still running (all Scouts, then all
  Scribes, then all Wardens, then the revision rounds and the added agents), so a run takes as
  many batches as the longest pipeline has steps. The state is saved after each step: an
  interrupted run resumes where it stopped when the same command is run again.
- **Direct**: the requests run one after the other, right away, at the normal price.

The server-side fallback after a refusal is not used in batches: a refused request is
reported as failed.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from spectre.config import (
    AgentSpec,
    ClientSettings,
    check_max_revisions,
    load_max_revisions,
    load_prompt_cache,
    load_specs,
)
from spectre.costs import make_record, total_cost
from spectre.errors import ConfigurationError, SpectreError
from spectre.graph import next_step, pipeline_steps, run
from spectre.plugins import ExtraAgent, load_extra_agents
from spectre.state import UsageRecord
from spectre.steps import Step

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # what the Batches API accepts as custom_id
Notify = Callable[[str], None]


@dataclass
class Item:
    """One request of the batch and where it stands."""

    id: str
    request: str
    state: dict[str, Any] = field(default_factory=dict)
    next: str | None = "scout"
    error: str = ""

    def result(self) -> dict[str, Any]:
        usage: list[UsageRecord] = list(self.state.get("usage", []))
        return {
            "id": self.id,
            "request": self.request,
            "final_text": self.state.get("final_text", ""),
            "approved": self.state.get("approved", True),
            "issues": list(self.state.get("issues", [])),
            "revisions": self.state.get("revisions", 0),
            "usage": usage,
            "total_cost_usd": total_cost(usage),
            "error": self.error,
        }


def read_requests(path: Path) -> list[Item]:
    """Requests from a text file (one per line, `#` for comments) or JSON Lines
    (`{"id": ..., "request": ...}`)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigurationError(f"impossible de lire {path} : {exc}") from exc
    items: list[Item] = []
    for number, line in enumerate(lines, start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        ident = f"r{len(items) + 1:04d}"
        if text.startswith("{"):
            try:
                data = json.loads(text)
            except ValueError as exc:
                raise ConfigurationError(f"{path.name}, ligne {number} : JSON invalide") from exc
            request = str(data.get("request", "")).strip() if isinstance(data, dict) else ""
            ident = str(data.get("id", ident)).strip() if isinstance(data, dict) else ident
            if not request:
                raise ConfigurationError(f"{path.name}, ligne {number} : « request » manquant")
            text = request
        if not _ID.match(ident) or ident in {item.id for item in items}:
            raise ConfigurationError(
                f"{path.name}, ligne {number} : identifiant {ident!r} invalide ou en double "
                "(lettres, chiffres, - et _, 64 au plus)"
            )
        items.append(Item(ident, text, {"request": text, "usage": [], "revisions": 0}))
    if not items:
        raise ConfigurationError(f"{path.name} : aucune demande")
    return items


def write_results(path: Path, items: Iterable[Item]) -> None:
    lines = [json.dumps(item.result(), ensure_ascii=False) for item in items]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- direct mode ----------------------------------------------------------------------------


def run_direct(
    items: Sequence[Item], *, max_revisions: int | None = None, notify: Notify = print
) -> list[Item]:
    """Run every request now, one after the other; a failure is recorded, not raised."""
    for index, item in enumerate(items, start=1):
        notify(f"[{index}/{len(items)}] {item.id}")
        try:
            result = run(item.request, max_revisions=max_revisions)
        except SpectreError as exc:
            item.error, item.next = str(exc), None
            continue
        item.state.update(
            brief=result.brief,
            draft=result.draft,
            final_text=result.final_text,
            approved=result.approved,
            issues=result.issues,
            revisions=result.revisions,
            usage=result.usage,
        )
        item.next = None
    return list(items)


# ---- API mode -------------------------------------------------------------------------------


class BatchAPI(Protocol):
    """The part of the Message Batches API Spectre uses (a fake in the tests)."""

    def submit(self, requests: list[dict[str, Any]]) -> str: ...
    def ended(self, batch_id: str) -> bool: ...
    def results(self, batch_id: str) -> Iterator[tuple[str, str, Any]]: ...


class AnthropicBatches:
    """`BatchAPI` over the official SDK (`client.messages.batches`)."""

    def __init__(self, settings: ClientSettings) -> None:
        import anthropic

        headers = (
            {"anthropic-workspace-id": settings.workspace_id} if settings.workspace_id else None
        )
        self.client = anthropic.Anthropic(
            max_retries=settings.max_retries, timeout=settings.timeout, default_headers=headers
        )

    def submit(self, requests: list[dict[str, Any]]) -> str:
        return str(self.client.messages.batches.create(requests=requests).id)  # type: ignore[arg-type]

    def ended(self, batch_id: str) -> bool:
        return self.client.messages.batches.retrieve(batch_id).processing_status == "ended"

    def results(self, batch_id: str) -> Iterator[tuple[str, str, Any]]:
        for entry in self.client.messages.batches.results(batch_id):
            outcome = entry.result
            if outcome.type == "succeeded":
                yield entry.custom_id, "succeeded", outcome.message
            elif outcome.type == "errored":
                yield entry.custom_id, "errored", outcome.error.error.message
            else:
                yield entry.custom_id, outcome.type, outcome.type


def request_params(
    spec: AgentSpec, step: Step, state: Mapping[str, Any], cache: bool
) -> dict[str, Any]:
    """Messages API parameters for one agent call (the same settings as `ChatAnthropic`)."""
    params: dict[str, Any] = {
        "model": spec.model,
        "max_tokens": spec.max_tokens,
        "system": step.prompt,
        "messages": [{"role": "user", "content": step.build(state, cache)}],  # type: ignore[arg-type]
    }
    if spec.temperature is not None:
        params["temperature"] = spec.temperature
    if spec.effort is not None:
        params["output_config"] = {"effort": spec.effort}
    return params


def read_message(agent: str, model: str, message: Any) -> tuple[str, UsageRecord]:
    """The text and usage of a batch answer; refusals and empty answers raise SpectreError."""
    if getattr(message, "stop_reason", None) == "refusal":
        raise SpectreError("refus du modèle", agent=agent)
    text = "".join(
        str(block.text) for block in message.content if getattr(block, "type", "") == "text"
    ).strip()
    if not text:
        raise SpectreError("réponse vide", agent=agent)
    usage = message.usage
    read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    total_input = int(usage.input_tokens or 0) + read + write  # the API excludes cached tokens
    record = make_record(
        agent,
        str(getattr(message, "model", "") or model),
        total_input,
        int(usage.output_tokens or 0),
        read,
        write,
        message.stop_reason == "max_tokens",
        batch=True,
    )
    return text, record


class BatchRun:
    """Drives the requests through the pipeline, one Message Batch per stage."""

    def __init__(
        self,
        api: BatchAPI,
        state_file: Path,
        *,
        max_revisions: int | None = None,
        extra_agents: Sequence[ExtraAgent] | None = None,
        prompt_cache: bool | None = None,
        specs: Mapping[str, AgentSpec] | None = None,
        poll_s: float = 30.0,
        notify: Notify = print,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api = api
        self.state_file = state_file
        self.rounds = (
            load_max_revisions() if max_revisions is None else check_max_revisions(max_revisions)
        )
        extras = list(load_extra_agents() if extra_agents is None else extra_agents)
        self.steps = {step.name: step for step in pipeline_steps(extras)}
        self.order = list(self.steps)
        self.specs: dict[str, AgentSpec] = {extra.name: extra.spec for extra in extras}
        self.specs.update(specs if specs is not None else load_specs())
        self.cache = load_prompt_cache() if prompt_cache is None else prompt_cache
        self.poll_s = poll_s
        self.notify = notify
        self.sleep = sleep
        self.items: list[Item] = []
        self.pending: dict[str, Any] | None = None

    # ---- persistence --------------------------------------------------------------------

    def load(self, items: Sequence[Item]) -> None:
        """Resume from the state file when it matches these requests, else start fresh."""
        if self.state_file.is_file():
            saved = json.loads(self.state_file.read_text(encoding="utf-8"))
            if [i["request"] for i in saved["items"]] == [i.request for i in items]:
                self.items = [Item(**data) for data in saved["items"]]
                self.pending = saved.get("pending")
                self.notify("Reprise du lot enregistré.")
                return
        self.items = list(items)
        self.save()

    def save(self) -> None:
        data = {
            "items": [item.__dict__ for item in self.items],
            "pending": self.pending,
        }
        self.state_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # ---- the loop -----------------------------------------------------------------------

    def run(self, items: Sequence[Item]) -> list[Item]:
        self.load(items)
        while True:
            if self.pending is not None:
                self._collect()
            stage = self._next_stage()
            if stage is None:
                break
            self._submit(*stage)
        self.state_file.unlink(missing_ok=True)
        return self.items

    def _next_stage(self) -> tuple[str, list[Item]] | None:
        waiting = [item for item in self.items if item.next is not None]
        if not waiting:
            return None
        # The earliest step anyone is waiting for: the batch keeps the requests in step.
        agent = min((item.next for item in waiting if item.next), key=self.order.index)
        return agent, [item for item in waiting if item.next == agent]

    def _submit(self, agent: str, items: list[Item]) -> None:
        step, spec = self.steps[agent], self.specs[agent]
        requests = [
            {"custom_id": item.id, "params": request_params(spec, step, item.state, self.cache)}
            for item in items
        ]
        batch_id = self.api.submit(requests)
        self.pending = {"batch_id": batch_id, "agent": agent, "ids": [i.id for i in items]}
        self.save()
        self.notify(f"Lot {batch_id} envoyé : {agent}, {len(items)} demande(s).")

    def _collect(self) -> None:
        assert self.pending is not None
        batch_id, agent = self.pending["batch_id"], self.pending["agent"]
        while not self.api.ended(batch_id):
            self.notify(f"Lot {batch_id} ({agent}) en cours…")
            self.sleep(self.poll_s)
        by_id = {item.id: item for item in self.items}
        step, spec = self.steps[agent], self.specs[agent]
        seen: set[str] = set()
        for custom_id, kind, payload in self.api.results(batch_id):
            item = by_id.get(custom_id)
            if item is None:  # pragma: no cover - defensive, ids are ours
                continue
            seen.add(custom_id)
            if kind != "succeeded":
                item.error, item.next = f"{agent} : {payload}", None
                continue
            try:
                text, record = read_message(agent, spec.model, payload)
                update = step.apply(item.state, text)  # type: ignore[arg-type]
            except SpectreError as exc:
                item.error, item.next = f"{agent} : {exc}", None
                continue
            item.state.update(update)
            item.state["usage"] = [*item.state.get("usage", []), record]
            item.next = next_step(self.order, agent, item.state, self.rounds)
        for missing in set(self.pending["ids"]) - seen:
            by_id[missing].error, by_id[missing].next = f"{agent} : aucun résultat", None
        self.pending = None
        self.save()
