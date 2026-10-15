"""Engines: providers, the OpenAI-compatible agent, routing, fallback and `/model`."""

from __future__ import annotations

import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import engines, providers, tools
from spectre.assistant.brain import THREAD_KV, Brain, Reply
from spectre.assistant.config import AssistantConfig, resolve_role
from spectre.assistant.custom_agents import AgentError, CustomAgents
from spectre.assistant.db import Database
from spectre.assistant.engines import Engines
from spectre.assistant.governance import Gate
from spectre.assistant.llm import HttpAgent, json_type, tool_schemas
from spectre.assistant.missions import MissionEngine
from spectre.assistant.providers import Provider, ProviderError, Providers, split_ref
from spectre.assistant.service import AssistantService
from tests.test_assistant_agents import _queue, _steps, db  # noqa: F401 - fixture
from tests.test_assistant_brain import FakeCLI
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client


class Rooted(FakeCLI):
    """A FakeCLI with the `root` and `config` the engines need."""

    def __init__(self, root: Path, *replies: str | Reply) -> None:
        super().__init__(root, *replies)
        self.root = root
        self.config = AssistantConfig()


class FakeHttp:
    """Stands in for HttpAgent: answers from a list and records calls (with the history)."""

    def __init__(self, *replies: str | Reply) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def ask(self, prompt: str, **kwargs: Any) -> Reply:
        self.calls.append({"prompt": prompt, **kwargs})
        reply = self.replies.pop(0) if self.replies else "ok http"
        return reply if isinstance(reply, Reply) else Reply(reply, "", False)


def chat(content: str = "", calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = calls
    return {"choices": [{"message": message}]}


def call(name: str, args: str, cid: str = "c1") -> dict[str, Any]:
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}


# ---- providers ------------------------------------------------------------------------------


def test_split_ref() -> None:
    assert split_ref("lmstudio:google/gemma") == ("lmstudio", "google/gemma")
    assert split_ref(" Ollama:qwen3:8b ") == ("ollama", "qwen3:8b")
    assert split_ref("sonnet") == ("", "sonnet")


def test_check_and_custom_providers(tmp_path: Path) -> None:
    (tmp_path / "providers.json").write_text(
        json.dumps(
            [
                {"id": "Maison", "base_url": "http://127.0.0.1:8080/v1/", "label": "Mon serveur"},
                {"id": "nuage", "base_url": "https://llm.example/v1", "key_env": "NUAGE_KEY"},
                {"id": "opus", "base_url": "http://x/v1"},  # a CLI engine's name: ignored
                {"id": "bad", "base_url": "ftp://x"},
                "pas un objet",
            ]
        ),
        encoding="utf-8",
    )
    found = Providers(tmp_path, environ={})
    assert found.get("maison") == Provider(
        "maison", "Mon serveur", "http://127.0.0.1:8080/v1", "", True
    )
    assert "bad" not in found.all() and "opus" not in found.all()
    assert found.get("nuage").needs_key
    assert found.check(" Sonnet ") == "sonnet"
    assert found.check("LMStudio:google/gemma-4-e4b") == "lmstudio:google/gemma-4-e4b"
    for bad, error in [
        ("gemini", "moteur inconnu"),
        ("nowhere:x", "fournisseur inconnu"),
        ("ollama:", "nom de modèle invalide"),
        ("ollama:a b", "nom de modèle invalide"),
    ]:
        with pytest.raises(ProviderError, match=error):
            found.check(bad)


def test_keys_from_env_or_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "# clés\nexport GROQ_API_KEY='g-file'\n\nOPENROUTER_API_KEY=\"o-file\"\nnoise\n",
        encoding="utf-8",
    )
    found = Providers(tmp_path, environ={"OPENROUTER_API_KEY": "o-env"})
    assert found.key(found.get("openrouter")) == "o-env"  # the environment wins
    assert found.key(found.get("groq")) == "g-file"
    assert found.key(found.get("lmstudio")) == "" and found.ready(found.get("lmstudio"))
    assert not found.ready(found.get("gemini"))
    headers = found.headers(found.get("openrouter"))
    assert headers["Authorization"] == "Bearer o-env" and headers["X-Title"] == "Spectre"
    described = {p["id"]: p for p in found.describe()}
    assert described["groq"]["ready"] and "o-env" not in json.dumps(described)
    assert providers.read_env_file(tmp_path / "absent") == {}


def test_models_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def urlopen(request: Any, timeout: float) -> Any:
        seen.append(request.full_url)
        if "11434" in request.full_url:
            raise OSError("refusé")
        return io.BytesIO(json.dumps({"data": [{"id": "b"}, {"id": "a"}, {}]}).encode())

    monkeypatch.setattr(providers.urllib.request, "urlopen", urlopen)
    found = Providers(tmp_path, environ={})
    assert found.models("lmstudio") == ["a", "b"]
    assert found.models("ollama") == []  # not running
    assert found.models("groq") == []  # no key: not even tried
    assert seen == ["http://127.0.0.1:1234/v1/models", "http://127.0.0.1:11434/v1/models"]


# ---- the OpenAI-compatible agent ------------------------------------------------------------


def test_tool_schemas() -> None:
    assert json_type(int) == "integer" and json_type(int | None) == "integer"
    assert json_type(bool) == "boolean" and json_type(list) == "string"
    schemas = {
        s["function"]["name"]: s["function"] for s in tool_schemas(list(tools.TOOLS.values()))
    }
    assert schemas["read_file"]["parameters"] == {
        "type": "object",
        "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}},
        "required": ["path"],
    }
    assert "set_model" in schemas and schemas["current_time"]["parameters"]["required"] == []


def test_http_agent_tool_loop(tmp_path: Path) -> None:
    answers = [
        chat(calls=[call("current_time", "{}"), call("recall", "pas du json", "c2")]),
        chat("Il est midi."),
    ]
    sent: list[dict[str, Any]] = []
    ran: list[tuple[str, dict[str, Any]]] = []

    def transport(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> Any:
        sent.append({"url": url, "body": json.loads(json.dumps(body))})
        return answers.pop(0)

    agent = HttpAgent(
        AssistantConfig(),
        tmp_path,
        providers=Providers(tmp_path, environ={}),
        transport=transport,
        call_tool=lambda name, args: ran.append((name, args)) or "12:00",
    )
    reply = agent.ask(
        "Quelle heure ?",
        system="Tu es Spectre.",
        model="lmstudio:gemma",
        history=[{"role": "user", "content": "salut"}, {"role": "assistant", "content": "yo"}],
    )
    assert reply == Reply("Il est midi.", "", False)
    assert ran == [("current_time", {})]  # the unreadable call never ran
    first, second = sent
    assert first["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert first["body"]["model"] == "gemma" and first["body"]["tools"]
    assert [m["role"] for m in first["body"]["messages"]] == ["system", "user", "assistant", "user"]
    results = [m for m in second["body"]["messages"] if m["role"] == "tool"]
    assert [(m["tool_call_id"], m["content"]) for m in results] == [
        ("c1", "12:00"),
        ("c2", "ÉCHEC : arguments illisibles (JSON attendu)"),
    ]


def test_http_agent_failures(tmp_path: Path) -> None:
    config = AssistantConfig()
    found = Providers(tmp_path, environ={})

    def agent(*answers: Any) -> HttpAgent:
        queue = list(answers)

        def transport(*_: Any) -> Any:
            item = queue.pop(0) if queue else chat(calls=[call("current_time", "{}")])
            if isinstance(item, Exception):
                raise item
            return item

        return HttpAgent(
            config, tmp_path, providers=found, transport=transport, call_tool=lambda *a: "x"
        )

    ask = {"system": "s", "with_tools": False}
    assert "clé de Groq" in agent().ask("q", model="groq:llama", **ask).text  # type: ignore[arg-type]
    assert "fournisseur inconnu" in agent().ask("q", model="nowhere:x", **ask).text  # type: ignore[arg-type]
    down = agent(ConnectionError("HTTP 500 : boom")).ask("q", model="lmstudio:m", **ask)  # type: ignore[arg-type]
    assert down.is_error and "HTTP 500" in down.text
    empty = agent({"error": {"message": "modèle absent"}}).ask("q", model="lmstudio:m", **ask)  # type: ignore[arg-type]
    assert empty.is_error and "modèle absent" in empty.text
    loop = agent().ask("q", model="lmstudio:m", system="s")
    assert loop.is_error and "trop d'appels" in loop.text


def test_http_agent_goes_through_the_gate(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    agent = HttpAgent(
        AssistantConfig(),
        root,
        providers=Providers(root, environ={}),
        transport=lambda *a: (
            chat("fini")
            if len(a[2]["messages"]) > 2
            else chat(calls=[call("delete_file", '{"path": "x"}')])
        ),
    )
    assert agent.ask("efface x", system="s", model="lmstudio:m").text == "fini"
    rows = Database(root / "spectre.db").all("SELECT tool, decision FROM audit")
    assert rows == [{"tool": "delete_file", "decision": "approval"}]  # it waits for the user


# ---- routing and fallback -------------------------------------------------------------------


def test_worker_routing(tmp_path: Path) -> None:
    cli, http, vibe = Rooted(tmp_path), FakeHttp(), FakeCLI(tmp_path)
    found = Engines(cli, agents={"http": http, "mistral": vibe})
    assert found.worker("sonnet") == (cli, "sonnet")
    assert found.worker("mistral") == (vibe, "mistral")
    assert found.worker("ollama:qwen3:8b") == (http, "ollama:qwen3:8b")
    fresh = Engines(cli)
    assert isinstance(fresh.worker("lmstudio:m")[0], HttpAgent)
    assert fresh.worker("chatgpt")[0].__class__.__name__ == "CodexCLI"


def test_ask_sends_the_thread(tmp_path: Path) -> None:
    cli, http = Rooted(tmp_path, "réponse"), FakeHttp("http")
    found = Engines(cli, agents={"http": http})
    history = [{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}]
    found.ask("haiku", "Q", "sys", history=history)
    assert cli.calls[0]["prompt"] == "[Fil de la conversation :\nUtilisateur : A\nToi : B]\n\nQ"
    found.ask("lmstudio:m", "Q", "sys", tools=True, history=history)
    assert http.calls[0]["history"] == history and http.calls[0]["with_tools"] is True


def test_ask_chain(tmp_path: Path) -> None:
    limit = Reply("You've hit your limit · resets 5pm", "", False)
    cli, http = Rooted(tmp_path, limit, Reply("panne", "", True)), FakeHttp("secours")
    found = Engines(cli, agents={"http": http})
    assert found.ask_chain(["opus", "opus", "lmstudio:m"], "q", "s") == (
        Reply("secours", "", False),
        "lmstudio:m",
    )
    assert len(cli.calls) == 1  # opus once: the duplicate is dropped
    http.replies = [Reply("down", "", True)]
    cli.replies = [Reply("raté", "", True)]
    assert found.ask_chain(["haiku", "lmstudio:m"], "q", "s") == (Reply("raté", "", True), "haiku")
    assert found.ask_chain([], "q", "s")[0].is_error


def test_assign_and_fallbacks(tmp_path: Path) -> None:
    config, found = AssistantConfig(), Providers(tmp_path, environ={})
    assert engines.assign(config, found, "Vérificateur", "lmstudio:m") == "verifier_model"
    assert config.verifier_model == "lmstudio:m"
    engines.assign(config, found, "planificateur", "cerveau")
    assert config.planner_model == ""
    with pytest.raises(ProviderError, match="rôle inconnu"):
        engines.assign(config, found, "chef", "opus")
    engines.set_fallbacks(config, found, ["lmstudio:m", " haiku", "", "haiku"])
    assert config.fallback_models == ["lmstudio:m", "haiku"]
    with pytest.raises(ProviderError, match="au maximum"):
        engines.set_fallbacks(config, found, [f"ollama:m{i}" for i in range(6)])
    assert (
        resolve_role("brain") == "brain_model"
        and resolve_role("verifier_model") == "verifier_model"
    )
    assert resolve_role("nimporte") == ""
    text = engines.summary(config, found, with_models=False)
    assert "verifier_model" in text and "Secours, dans l'ordre : lmstudio:m, haiku" in text
    assert "clé manquante (GROQ_API_KEY)" in text


# ---- the brain --------------------------------------------------------------------------------


def test_brain_on_another_engine(db: Database, tmp_path: Path) -> None:  # noqa: F811
    config = AssistantConfig(brain_model="lmstudio:gemma")
    cli, http = Rooted(tmp_path), FakeHttp("Bonjour !", "Ça va.")
    brain = Brain(db, cli, config)
    brain.engines.agents["http"] = http
    assert brain.ask("salut").text == "Bonjour !"
    assert brain.ask("ça va ?").text == "Ça va."
    assert cli.calls == []
    first, second = http.calls
    assert first["history"] == [] and first["model"] == "lmstudio:gemma"
    assert second["history"] == [
        {"role": "user", "content": "salut"},
        {"role": "assistant", "content": "Bonjour !"},
    ]
    assert db.get_kv(THREAD_KV) == "1"
    # back on Claude: its session never saw these turns, so they come along
    config.brain_model = "opus"
    cli.replies = [Reply("De retour.", "s9", False)]
    brain.ask("et toi ?")
    assert (
        cli.calls[0]["resume"] is None and "[Tu reprends la conversation." in cli.calls[0]["prompt"]
    )
    assert "Utilisateur : ça va ?" in cli.calls[0]["prompt"] and db.get_kv(THREAD_KV) == ""


def test_brain_falls_back(db: Database, tmp_path: Path) -> None:  # noqa: F811
    config = AssistantConfig(fallback_models=["lmstudio:gemma"])
    cli = Rooted(tmp_path, Reply("You've hit your limit · resets 5pm", "s1", False))
    http = FakeHttp("Je prends le relais.")
    brain = Brain(db, cli, config)
    brain.engines.agents["http"] = http
    assert brain.ask("salut") == Reply("Je prends le relais.", "", False)
    assert db.all("SELECT text FROM events WHERE kind = 'fallback'") == [
        {"text": "réponse par lmstudio:gemma"}
    ]
    http.replies = [Reply("down", "", True)]
    cli.replies = [Reply("You've hit your limit · resets 5pm", "s1", False)]
    reply = brain.ask("encore ?")
    assert reply.is_error and "se réinitialise à 17 h" in reply.text  # the clearest error


# ---- missions -----------------------------------------------------------------------------------


def test_mission_engines(db: Database, tmp_path: Path) -> None:  # noqa: F811
    claude = Rooted(tmp_path, Reply("panne", "", True), "rapport")
    http = FakeHttp("fait en local", '{"ok": true}')
    engine = MissionEngine(
        db,
        claude,  # type: ignore[arg-type]
        lambda *a: None,
        model="sonnet",
        verifier_model="lmstudio:juge",
        fallbacks=["lmstudio:secours"],
    )
    engine.engines.agents["http"] = http
    mid = _queue(db, {"kind": "mission", "steps": ["unique"]})
    engine.run_next()
    step = _steps(db, mid)[0]
    assert step["result"] == "fait en local" and step["ok"] and step["agent"] == "lmstudio:secours"
    assert [c["model"] for c in http.calls] == ["lmstudio:secours", "lmstudio:juge"]
    assert claude.calls[0]["model"] == "sonnet" and claude.calls[1]["model"] == "opus"


def test_mission_on_a_provider_agent(db: Database, tmp_path: Path) -> None:  # noqa: F811
    nova = CustomAgents(db, Providers(tmp_path, environ={})).create(
        "Nova", "lmstudio:gemma", "Cuisine"
    )
    assert nova["engine"] == "lmstudio:gemma"
    with pytest.raises(AgentError, match="fournisseur inconnu"):
        CustomAgents(db, Providers(tmp_path, environ={})).create("Lune", "nulle:part", "x")
    claude, http = Rooted(tmp_path, '{"ok": true}', "rapport"), FakeHttp("menus")
    engine = MissionEngine(db, claude, lambda *a: None)  # type: ignore[arg-type]
    engine.engines.agents["http"] = http
    mid = _queue(db, {"kind": "mission", "steps": ["menus"], "agent": f"agent:{nova['id']}"})
    engine.run_next()
    assert http.calls[0]["model"] == "lmstudio:gemma" and "Tu es Nova" in http.calls[0]["system"]
    assert _steps(db, mid)[0]["name"] == "Nova"


# ---- tools, service and API ------------------------------------------------------------------


def test_model_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Providers, "models", lambda self, pid, timeout=5.0: [])  # no network
    root = tmp_path / "assistant"
    database = Database(root / "spectre.db")
    gate, ctx = Gate(database), tools.make_context(database, root, [str(tmp_path)])
    run = lambda tool, **args: tools.execute(gate, ctx, tool, args)  # noqa: E731
    assert run("set_model", role="mission", engine="lmstudio:m") == (
        "moteur changé : mission_model = lmstudio:m"
    )
    assert (
        run("set_fallbacks", engines="haiku; lmstudio:m")
        == "moteurs de secours : haiku, lmstudio:m"
    )
    assert run("set_model", role="cerveau", engine="nulle:part").startswith("ÉCHEC : fournisseur")
    saved = AssistantConfig.load(root)
    assert saved.mission_model == "lmstudio:m" and saved.fallback_models == ["haiku", "lmstudio:m"]
    assert "Moteurs par rôle" in run("list_models")
    created = run("create_agent", name="Nova", engine="lmstudio:gemma", role="Cuisine")
    assert created.startswith("agent créé : Nova (moteur lmstudio:gemma")


def test_service_model_command(
    service: AssistantService,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Providers, "models", lambda self, pid, timeout=5.0: ["gemma"])
    assert service.chat("/model lmstudio:gemma") == "C'est fait : cerveau sur lmstudio:gemma."
    assert service.config.brain_model == "lmstudio:gemma"
    assert service.chat("/model verificateur haiku").startswith("C'est fait : vérification")
    assert (
        service.chat("/model secours lmstudio:a, haiku") == "Moteurs de secours : lmstudio:a, haiku"
    )
    assert service.missions.fallbacks == ["lmstudio:a", "haiku"]
    assert service.chat("/model planificateur cerveau").endswith("sur le cerveau.")
    assert service.missions.lead_model == "lmstudio:gemma"
    assert service.chat("/model chef opus").startswith("Impossible : rôle inconnu")
    assert service.chat("/model nulle:part").startswith("Impossible : fournisseur inconnu")
    assert "lmstudio : LM Studio (local), prêt ; modèles : gemma" in service.chat("/model")
    assert AssistantConfig.load(service.root).brain_model == "lmstudio:gemma"


def test_service_reloads_config(service: AssistantService) -> None:  # noqa: F811
    assert not service.reload_config()
    changed = AssistantConfig.load(service.root)
    changed.mission_model = "lmstudio:m"
    changed.save(service.root)
    stamp = service._config_mtime + 5
    os.utime(service.root / "config.json", (stamp, stamp))
    queue = service.subscribe()
    assert service.reload_config() and service.missions.model == "lmstudio:m"
    assert service.config.mission_model == "lmstudio:m"
    events = [queue.get_nowait() for _ in range(queue.qsize())]
    assert {"type": "config", "brain_model": "opus"} in events


def test_update_config_checks_engines(service: AssistantService) -> None:  # noqa: F811
    with pytest.raises(ProviderError):
        service.update_config({"brain_model": "gemini"})
    with pytest.raises(ProviderError):
        service.update_config({"fallback_models": ["nulle:part"]})
    service.update_config({"planner_model": "", "verifier_model": "Haiku"})
    assert service.config.verifier_model == "haiku"


def test_models_api(
    api: Client,  # noqa: F811
    service: AssistantService,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service.providers, "models", lambda pid, timeout=5.0: [f"{pid}-m"])
    status, data = api.json("GET", "/api/assistant/models")
    assert status == 200 and data["roles"][0] == {
        "role": "brain_model",
        "label": "cerveau : la conversation avec toi",
        "engine": "opus",
    }
    assert data["cli"][0] == "opus" and any(p["id"] == "lmstudio" for p in data["providers"])
    assert api.json("GET", "/api/assistant/models/lmstudio")[1] == {
        "provider": "lmstudio",
        "models": ["lmstudio-m"],
    }
    status, data = api.json(
        "POST", "/api/assistant/models", {"role": "mission", "engine": "ollama:q"}
    )
    assert status == 200 and data["roles"][1]["engine"] == "ollama:q"
    status, data = api.json("POST", "/api/assistant/models", {"fallbacks": ["haiku"]})
    assert data["fallbacks"] == ["haiku"]
    status, data = api.json("POST", "/api/assistant/models", {"role": "x", "engine": "opus"})
    assert status == 400 and "rôle inconnu" in data["error"]
    status, data = api.json("POST", "/api/assistant/models", {"role": "brain", "engine": "nul:x"})
    assert status == 400 and "fournisseur inconnu" in data["error"]
    service.create_agent({"name": "Nova", "engine": "lmstudio:gemma", "role": "Cuisine"})
    created = api.json("GET", "/api/assistant/agents")[1]["created"]
    assert created[0]["engine"] == "gemma · LM Studio (local)"


def test_befriend_on_another_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from spectre.assistant.proactive import Proactive

    root = tmp_path / "assistant"
    database = Database(root / "spectre.db")
    asked: list[Any] = []

    def ask_chain(self: Engines, refs: list[str], prompt: str, system: str, **kw: Any) -> Any:
        asked.append(refs)
        return Reply('{"text": "Coucou !", "topic": "x"}', "", False), refs[0]

    monkeypatch.setattr(Engines, "ask_chain", ask_chain)
    config = AssistantConfig(brain_model="lmstudio:gemma", fallback_models=["haiku"])
    proactive = Proactive(database, Rooted(root), config, lambda *a: None, fetch=lambda u: {})  # type: ignore[arg-type]
    assert proactive.befriend(datetime.now().astimezone()) == "Coucou !"
    assert asked == [["lmstudio:gemma", "haiku"]]
