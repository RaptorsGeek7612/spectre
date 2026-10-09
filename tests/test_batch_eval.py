"""Tests for v0.5: `spectre batch` (Message Batches API and direct mode) and `spectre eval`."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from spectre import cli
from spectre.batch import (
    BatchRun,
    Item,
    read_message,
    read_requests,
    request_params,
    run_direct,
    write_results,
)
from spectre.config import DEFAULT_SPECS
from spectre.errors import AgentRefusalError, ConfigurationError, SpectreError
from spectre.evaluation import (
    Case,
    check,
    count_words,
    format_report,
    judge,
    load_cases,
    run_eval,
)
from spectre.graph import SpectreResult
from spectre.graph import run as real_run
from spectre.steps import SCOUT, WARDEN
from tests.conftest import fake, make_ai

REJECT = 'V1\n=== VERDICT ===\n{"approved": false, "issues": ["Plus court"]}'


def _message(text: str, stop: str = "end_turn", model: str = "claude-opus-5-5") -> Any:
    usage = SimpleNamespace(
        input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    blocks = [SimpleNamespace(type="thinking", text=""), SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=blocks, stop_reason=stop, model=model, usage=usage)


class FakeBatches:
    """Answers each batch from `answer(agent, custom_id, params)`; ends after `wait` checks."""

    def __init__(self, answer: Any, wait: int = 1) -> None:
        self.answer = answer
        self.wait = wait
        self.batches: dict[str, list[dict[str, Any]]] = {}
        self.checks = 0

    def submit(self, requests: list[dict[str, Any]]) -> str:
        batch_id = f"b{len(self.batches) + 1}"
        self.batches[batch_id] = requests
        return batch_id

    def ended(self, batch_id: str) -> bool:
        self.checks += 1
        return self.checks % (self.wait + 1) == 0 if self.wait else True

    def results(self, batch_id: str) -> Iterator[tuple[str, str, Any]]:
        for request in self.batches[batch_id]:
            outcome = self.answer(request["params"], request["custom_id"])
            if outcome is not None:
                yield request["custom_id"], *outcome


def _agent(params: dict[str, Any]) -> str:
    return {"Scout": "scout", "Scribe": "scribe", "Warden": "warden"}[
        params["system"].split()[2].rstrip(",")
    ]


_WARDEN_CALLS: dict[str, int] = {}


def _answers(params: dict[str, Any], custom_id: str) -> tuple[str, Any] | None:
    agent = _agent(params)
    if custom_id == "boom":
        return "errored", "overloaded"
    if agent == "warden" and custom_id == "r0002":
        _WARDEN_CALLS[custom_id] = _WARDEN_CALLS.get(custom_id, 0) + 1
        return "succeeded", _message(REJECT if _WARDEN_CALLS[custom_id] == 1 else "OK")
    return "succeeded", _message(f"{agent.upper()}-{custom_id}")


# ---- reading and writing -------------------------------------------------------------------


def test_read_requests(tmp_path: Path) -> None:
    path = tmp_path / "demandes.txt"
    path.write_text(
        '# commentaire\nÉcris un haïku\n\n{"id": "lettre", "request": "Une lettre"}\n',
        encoding="utf-8",
    )
    items = read_requests(path)
    assert [(i.id, i.request) for i in items] == [
        ("r0001", "Écris un haïku"),
        ("lettre", "Une lettre"),
    ]
    assert items[0].state == {"request": "Écris un haïku", "usage": [], "revisions": 0}


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("", "aucune demande"),
        ("{pas du json", "JSON invalide"),
        ('{"id": "x"}', "request"),
        ('{"id": "a b", "request": "r"}', "identifiant"),
        ('{"id": "a", "request": "r"}\n{"id": "a", "request": "s"}', "double"),
    ],
)
def test_bad_request_files(tmp_path: Path, body: str, message: str) -> None:
    path = tmp_path / "d.jsonl"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigurationError, match=message):
        read_requests(path)
    with pytest.raises(ConfigurationError, match="impossible de lire"):
        read_requests(tmp_path / "absent.txt")


def test_request_params_and_messages() -> None:
    state = {"request": "R", "draft": "D", "usage": []}
    warden = request_params(DEFAULT_SPECS["warden"], WARDEN, state, True)
    assert warden["output_config"] == {"effort": "high"} and "temperature" not in warden
    assert warden["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    scout = request_params(DEFAULT_SPECS["scout"], SCOUT, state, False)
    assert scout["temperature"] == 0.2 and "output_config" not in scout
    text, record = read_message("warden", "claude-opus-5-5", _message("Texte", stop="max_tokens"))
    assert (
        text == "Texte"
        and record["truncated"]
        and record["cost_usd"] == pytest.approx((100 * 4 + 20 * 20) / 1e6 / 2)
    )
    with pytest.raises(SpectreError, match="refus"):
        read_message("warden", "m", _message("x", stop="refusal"))
    with pytest.raises(SpectreError, match="vide"):
        read_message("warden", "m", _message("  "))


# ---- the batch run -------------------------------------------------------------------------


def _items(*ids: str) -> list[Item]:
    return [
        Item(i, f"demande {i}", {"request": f"demande {i}", "usage": [], "revisions": 0})
        for i in ids
    ]


def test_batch_run_stage_by_stage_with_a_revision(tmp_path: Path) -> None:
    _WARDEN_CALLS.clear()
    api = FakeBatches(_answers)
    notes: list[str] = []
    state = tmp_path / "lot.state.json"
    runner = BatchRun(
        api,
        state,
        max_revisions=1,
        extra_agents=[],
        prompt_cache=False,
        poll_s=0,
        notify=notes.append,
        sleep=lambda s: None,
    )
    items = runner.run(_items("r0001", "r0002", "boom"))
    stages = [
        (_agent(reqs[0]["params"]), [r["custom_id"] for r in reqs]) for reqs in api.batches.values()
    ]
    assert stages == [
        ("scout", ["r0001", "r0002", "boom"]),
        ("scribe", ["r0001", "r0002"]),
        ("warden", ["r0001", "r0002"]),
        ("scribe", ["r0002"]),
        ("warden", ["r0002"]),
    ]
    done = {item.id: item.result() for item in items}
    assert done["r0001"]["final_text"] == "WARDEN-r0001" and done["r0001"]["revisions"] == 0
    assert done["r0002"]["final_text"] == "OK" and done["r0002"]["revisions"] == 1
    assert len(done["r0002"]["usage"]) == 5 and done["r0002"]["total_cost_usd"] > 0
    assert "overloaded" in done["boom"]["error"]
    assert not state.exists() and any("en cours" in n for n in notes)
    out = tmp_path / "res.jsonl"
    write_results(out, items)
    assert [json.loads(line)["id"] for line in out.read_text(encoding="utf-8").splitlines()] == [
        "r0001",
        "r0002",
        "boom",
    ]


def test_batch_run_resumes_from_its_state(tmp_path: Path) -> None:
    state = tmp_path / "lot.state.json"

    class Interrupt(FakeBatches):
        def ended(self, batch_id: str) -> bool:
            if batch_id == "b2":
                raise KeyboardInterrupt
            return True

    first = Interrupt(_answers)
    runner = BatchRun(
        first,
        state,
        max_revisions=0,
        extra_agents=[],
        prompt_cache=False,
        poll_s=0,
        notify=lambda m: None,
    )
    with pytest.raises(KeyboardInterrupt):
        runner.run(_items("r0001"))
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert (
        saved["pending"]["agent"] == "scribe"
        and saved["items"][0]["state"]["brief"] == "SCOUT-r0001"
    )

    second = FakeBatches(_answers, wait=0)
    second.batches = dict(first.batches)  # the server still holds the batch sent before
    notes: list[str] = []
    resumed = BatchRun(
        second,
        state,
        max_revisions=0,
        extra_agents=[],
        prompt_cache=False,
        poll_s=0,
        notify=notes.append,
    )
    (item,) = resumed.run(_items("r0001"))
    assert item.result()["final_text"] == "WARDEN-r0001" and "Reprise" in notes[0]
    # other requests: the old state is ignored
    third = BatchRun(
        FakeBatches(_answers, wait=0),
        state,
        max_revisions=0,
        extra_agents=[],
        prompt_cache=False,
        poll_s=0,
        notify=lambda m: None,
    )
    state.write_text(
        state.read_text(encoding="utf-8")
        if state.exists()
        else json.dumps(
            {
                "items": [{"id": "x", "request": "autre", "state": {}, "next": None, "error": ""}],
                "pending": None,
            }
        ),
        encoding="utf-8",
    )
    assert third.run(_items("r0009"))[0].result()["final_text"] == "WARDEN-r0009"


def test_batch_failures_inside_results(tmp_path: Path) -> None:
    def answers(params: dict[str, Any], custom_id: str) -> tuple[str, Any] | None:
        if custom_id == "refus":
            return "succeeded", _message("x", stop="refusal")
        if custom_id == "perdu":
            return None  # no result at all
        if custom_id == "expire":
            return "expired", "expired"
        return "succeeded", _message("T")

    runner = BatchRun(
        FakeBatches(answers, wait=0),
        tmp_path / "s.json",
        max_revisions=0,
        extra_agents=[],
        prompt_cache=False,
        notify=lambda m: None,
    )
    items = {i.id: i for i in runner.run(_items("refus", "perdu", "expire"))}
    assert "refus" in items["refus"].error and "aucun résultat" in items["perdu"].error
    assert "expired" in items["expire"].error


def test_run_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(request: str, **kwargs: Any) -> SpectreResult:
        if "casse" in request:
            raise AgentRefusalError("warden")
        return SpectreResult("B", "D", f"F:{request}", [], True, [], 0)

    monkeypatch.setattr("spectre.batch.run", fake_run)
    items = run_direct(_items("ok", "casse"), notify=lambda m: None)
    assert items[0].result()["final_text"] == "F:demande ok" and items[0].next is None
    assert "refusé" in items[1].error or items[1].error


# ---- evaluation ----------------------------------------------------------------------------


def _result(text: str, approved: bool = True, cost: float = 0.01) -> SpectreResult:
    usage = [
        {
            "agent": "warden",
            "model": "m",
            "input_tokens": 1,
            "output_tokens": 1,
            "cost_usd": cost,
            "truncated": False,
        }
    ]
    return SpectreResult("B", "D", text, usage, approved, [], 0)  # type: ignore[list-item]


def test_checks() -> None:
    case = Case(
        "c",
        "r",
        {
            "min_words": 3,
            "max_words": 5,
            "include": ["Bonjour"],
            "exclude": ["lorem"],
            "approved": True,
            "max_cost_usd": 0.05,
        },
    )
    assert check(case, _result("Bonjour à toi l'ami")) == []
    failures = check(case, _result("lorem", approved=False, cost=0.2))
    assert failures == [
        "1 mots, minimum 3",
        "absent : « Bonjour »",
        "présent : « lorem »",
        "Warden n'a pas validé le texte",
        "coût 0.2000 $ > 0.0500 $",
    ]
    long = check(Case("c", "r", {"max_words": 2, "approved": False}), _result("un deux trois"))
    assert long == ["3 mots, maximum 2", "validé"]
    assert count_words("aujourd'hui, c'est-à-dire 2 fois") == 4


def test_load_cases(tmp_path: Path) -> None:
    lines = tmp_path / "cas.jsonl"
    lines.write_text(
        '{"id": "a", "request": "R", "criteria": ["Poli"]}\n\n{"request": "S"}\n', encoding="utf-8"
    )
    cases = load_cases(lines)
    assert [(c.id, c.request, list(c.criteria)) for c in cases] == [
        ("a", "R", ["Poli"]),
        ("cas2", "S", []),
    ]
    single = tmp_path / "cas.json"
    single.write_text('{"request": "R"}', encoding="utf-8")
    assert load_cases(single)[0].id == "cas1"
    for body, message in (
        ("[]", "aucun cas"),
        ("{x", "JSON invalide"),
        ('{"id": 1}', "request"),
        ('{"request": "R", "checks": {"taille": 1}}', "checks"),
        ('{"request": "R", "criteria": "poli"}', "criteria"),
    ):
        bad = tmp_path / "bad.json"
        bad.write_text(body, encoding="utf-8")
        with pytest.raises(ConfigurationError, match=message):
            load_cases(bad)
    with pytest.raises(ConfigurationError, match="impossible de lire"):
        load_cases(tmp_path / "absent.jsonl")


def test_judge_and_report() -> None:
    case = Case("c", "Une lettre", {}, ["Poli", "Daté", "Signé"])
    model = fake(
        "juge",
        make_ai('{"results": [{"ok": true, "note": "oui"}, {"ok": false, "note": "pas de date"}]}'),
    )
    judgments, _ = judge(case, "Texte", model)
    assert [j["ok"] for j in judgments] == [True, False, False]
    assert judgments[2]["note"] == "jugement illisible"
    assert "<criteres>\n1. Poli\n2. Daté\n3. Signé" in model.received[0][1].content
    broken, _ = judge(case, "T", fake("juge", make_ai("je ne sais pas")))
    assert not any(j["ok"] for j in broken)

    def runner(request: str, **kwargs: Any) -> SpectreResult:
        if request == "casse":
            raise AgentRefusalError("warden")
        return _result("Bonjour")

    judge_model = fake("juge", make_ai('{"results": [{"ok": true}, {"ok": true}, {"ok": false}]}'))
    results = run_eval(
        [case, Case("x", "casse"), Case("ok", "r", {"include": ["Bonjour"]})],
        runner=runner,
        judge_model=judge_model,
        judge_name="claude-opus-5-5",
        notify=lambda m: None,
    )
    assert [r.passed for r in results] == [False, False, True]
    assert results[0].failures == ["critère : Signé"] and results[0].usage[-1]["agent"] == "juge"
    report = format_report(results)
    assert "1/3 cas réussis" in report and "échec" in report and "refus" in report.lower()
    assert results[2].to_dict()["passed"] is True


# ---- CLI -----------------------------------------------------------------------------------


def test_cli_batch_direct(
    api_key: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "spectre.batch.run", lambda request, **kw: SpectreResult("B", "D", "F", [], True, [], 0)
    )
    path = tmp_path / "d.txt"
    path.write_text("Une\nDeux\n", encoding="utf-8")
    assert cli.main(["batch", str(path), "--direct"]) == 0
    out = tmp_path / "d.results.jsonl"
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2
    assert "2/2 demande(s)" in capsys.readouterr().err


def test_cli_batch_api(
    api_key: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "spectre.batch.AnthropicBatches", lambda settings: FakeBatches(_answers, wait=0)
    )
    monkeypatch.setenv("SPECTRE_MAX_REVISIONS", "0")
    path = tmp_path / "d.txt"
    path.write_text("Une\n", encoding="utf-8")
    out = tmp_path / "res.jsonl"
    assert cli.main(["batch", str(path), "--out", str(out), "--poll", "0"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["final_text"] == "WARDEN-r0001"
    path.write_text('{"id": "boom", "request": "x"}\n', encoding="utf-8")
    assert cli.main(["batch", str(path), "--out", str(out), "--poll", "0"]) == 1
    assert "échec boom" in capsys.readouterr().err


def test_cli_batch_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "d.txt"
    path.write_text("Une\n", encoding="utf-8")
    assert cli.main(["batch", str(path)]) == 1  # no key
    assert cli.main(["batch", str(tmp_path / "absent.txt")]) == 1
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    def interrupted(*a: Any, **k: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr("spectre.batch.run_direct", interrupted)
    assert cli.main(["batch", str(path), "--direct"]) == 130
    assert "relancez" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["batch", str(path), "--revisions", "9"])


def test_cli_eval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cases = tmp_path / "cas.jsonl"
    cases.write_text(
        '{"id": "a", "request": "Un haïku", "checks": {"min_words": 1}}\n', encoding="utf-8"
    )
    assert cli.main(["eval", str(cases), "--demo"]) == 0
    assert "1/1 cas réussis" in capsys.readouterr().out
    assert cli.main(["eval", str(cases), "--demo", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["passed"] is True
    with pytest.raises(SystemExit):
        cli.main(["eval", str(cases), "--demo", "--judge"])
    assert cli.main(["eval", str(cases)]) == 1  # no key
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    seen: dict[str, Any] = {}

    def fake_eval(cases: Any, **kwargs: Any) -> list[Any]:
        seen.update(kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr("spectre.evaluation.run_eval", fake_eval)
    assert cli.main(["eval", str(cases), "--judge"]) == 130
    assert seen["judge_name"] == "claude-opus-5-5" and seen["judge_model"].reasoning_effort == "low"
    monkeypatch.setattr(
        "spectre.evaluation.run_eval",
        lambda *a, **k: (_ for _ in ()).throw(AgentRefusalError("warden")),
    )
    assert cli.main(["eval", str(cases)]) == 1
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"request": "x", "checks": {"max_words": 1}}\n', encoding="utf-8")
    monkeypatch.undo()
    assert cli.main(["eval", str(bad), "--demo"]) == 1


def test_cli_help_mentions_subcommands() -> None:
    assert "spectre batch" in cli.build_parser().epilog  # type: ignore[operator]
    assert real_run is not None


def test_anthropic_batches_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    import anthropic

    from spectre.batch import AnthropicBatches
    from spectre.config import ClientSettings

    created: dict[str, Any] = {}

    class Batches:
        def create(self, requests: list[dict[str, Any]]) -> Any:
            created["requests"] = requests
            return SimpleNamespace(id="msgbatch_1")

        def retrieve(self, batch_id: str) -> Any:
            return SimpleNamespace(processing_status="ended")

        def results(self, batch_id: str) -> Any:
            ok = SimpleNamespace(type="succeeded", message="MSG")
            bad = SimpleNamespace(
                type="errored", error=SimpleNamespace(error=SimpleNamespace(message="surcharge"))
            )
            gone = SimpleNamespace(type="expired")
            return [
                SimpleNamespace(custom_id=i, result=r)
                for i, r in (("a", ok), ("b", bad), ("c", gone))
            ]

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            created["kwargs"] = kwargs
            self.messages = SimpleNamespace(batches=Batches())

    monkeypatch.setattr(anthropic, "Anthropic", Client)
    api = AnthropicBatches(ClientSettings(max_retries=2, timeout=60, workspace_id="wrkspc_x"))
    assert created["kwargs"]["default_headers"] == {"anthropic-workspace-id": "wrkspc_x"}
    assert api.submit([{"custom_id": "a"}]) == "msgbatch_1" and api.ended("msgbatch_1")
    assert list(api.results("msgbatch_1")) == [
        ("a", "succeeded", "MSG"),
        ("b", "errored", "surcharge"),
        ("c", "expired", "expired"),
    ]
    AnthropicBatches(ClientSettings())
    assert created["kwargs"]["default_headers"] is None


def test_judge_with_broken_json() -> None:
    judgments, _ = judge(Case("c", "r", {}, ["Poli"]), "T", fake("juge", make_ai("{pas: du json}")))
    assert judgments == [{"criterion": "Poli", "ok": False, "note": "jugement illisible"}]
