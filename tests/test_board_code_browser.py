"""The board's cards (history, comments, requested changes), the live code viewer, the pages
opened in Chrome, Spectre in VS Code, the new kits (Rust, VS Code, graphics, books) and the
video skills shared with the agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import activity, browser_pages, codeview, competences, toolkit, vscode
from spectre.assistant import tools as tools_mod
from spectre.assistant.actions import ActionError
from spectre.assistant.company import Companies, CompanyError
from spectre.assistant.db import Database
from spectre.assistant.service import AssistantService
from tests.test_assistant_agents import db  # noqa: F401 - fixture
from tests.test_assistant_service import api, home, service  # noqa: F401 - fixtures
from tests.test_web import Client

# ---- the board: card, history, comments, changes, reassignment ----------------------------------


def _review_task(db: Database) -> dict[str, Any]:  # noqa: F811
    companies = Companies(db)
    companies.create("Acme")
    task = companies.add_task("Acme", "Page de prix", department="marketing")
    mid = companies.start(task["id"])
    steps = [{"step": "écrire", "ok": True, "note": "fait", "name": "Kyra", "key": "chatgpt"}]
    db.execute("UPDATE missions SET steps = ? WHERE id = ?", (json.dumps(steps), mid))
    companies.mission_finished(mid, ok=False, note="à relire")
    return companies.task(task["id"])


def test_history_comments_and_changes(db: Database) -> None:  # noqa: F811
    companies = Companies(db)
    task = _review_task(db)
    assert task["status"] == "review"
    kinds = [e["kind"] for e in companies.events(task["id"])]
    assert kinds == ["created", "status", "status"]
    assert "à faire → en cours" in companies.events(task["id"])[1]["text"]
    companies.comment(task["id"], "Plus court", "toi")
    with pytest.raises(CompanyError, match="vide"):
        companies.comment(task["id"], " ")
    with pytest.raises(CompanyError, match="dis ce qu'il faut changer"):
        companies.request_changes(task["id"], "")
    again = companies.request_changes(task["id"], "Ajoute le prix annuel")
    assert again["status"] == "todo" and again["agent"] == "chatgpt"  # back to whoever did it
    assert "Changements demandés" in again["detail"] and "prix annuel" in again["detail"]
    assert companies.events(task["id"])[-1]["kind"] == "changes"
    with pytest.raises(CompanyError, match="seule une tâche"):
        companies.request_changes(task["id"], "encore")
    assert companies.assign(task["id"], "Gétro")["agent"] == "sonnet"
    assert companies.assign(task["id"], "")["agent"] == ""
    assert companies.events(task["id"])[-1]["text"] == "celui du poste"


def test_comment_reaches_running_mission(db: Database) -> None:  # noqa: F811
    companies = Companies(db)
    companies.create("Acme")
    task = companies.add_task("Acme", "Étude")
    companies.start(task["id"])
    companies.comment(task["id"], "Cite tes sources")
    notes = db.all("SELECT text FROM mission_notes")
    assert notes and "Cite tes sources" in notes[0]["text"]
    with pytest.raises(CompanyError, match="en cours"):
        companies.assign(task["id"], "Kyra")


def test_card_shows_mission_files_and_waiting(db: Database, tmp_path: Path) -> None:  # noqa: F811
    companies = Companies(db)
    task = _review_task(db)
    mid = task["mission_id"]
    file = tmp_path / "prix.html"
    file.write_text("<h1>Prix</h1>", encoding="utf-8")
    row = activity.tool_started(db, "chatgpt", mid, "write_file", {"path": str(file)})
    activity.tool_finished(db, row, "write_file", {"path": str(file), "content": "x"}, "ok", 0.0)
    approval = db.execute(
        "INSERT INTO approvals(ts, tool, args, level, category, reason) "
        "VALUES('t', 'open_url', '{}', 4, 'open', 'r')"
    )
    activity.record(
        db, "approval", agent="chatgpt", mission=mid, detail=json.dumps({"id": approval})
    )
    card = companies.card(task["id"])
    assert card["mission"]["steps"][0] == {
        "title": "écrire",
        "agent": "Kyra",
        "ok": True,
        "note": "fait",
    }
    assert [f["name"] for f in card["files"]] == ["prix.html"] and card["waiting"] == 1
    assert companies.waiting_tasks("Acme") == []  # in review, not running
    db.execute("UPDATE approvals SET status = 'approved'")
    assert companies.card(task["id"])["waiting"] == 0


def test_board_api(api: Client, service: AssistantService) -> None:  # noqa: F811
    api.json("POST", "/api/assistant/company", {"name": "Acme"})
    api.json("POST", "/api/assistant/company/1/tasks", {"title": "Visuels"})
    status, body = api.json("POST", "/api/assistant/tasks/1/comment", {"text": "Vite"})
    assert status == 200 and body["result"] == "commentaire ajouté à la tâche #1"
    status, body = api.json("POST", "/api/assistant/tasks/1/assign", {"agent": "Charlotte"})
    assert status == 200 and "Charlotte" in body["result"]
    status, body = api.json("POST", "/api/assistant/tasks/1/changes", {"text": "x"})
    assert status == 400 and "seule une tâche" in body["error"]
    card = api.json("GET", "/api/assistant/tasks/1")[1]
    assert card["task"]["agent"] == "charlotte" and card["events"][1]["text"] == "Vite"
    assert api.json("GET", "/api/assistant/company/1")[1]["waiting"] == []
    assert api.json("GET", "/api/assistant/tasks/1/file?path=C:/x")[0] == 404


# ---- the live code viewer ------------------------------------------------------------------------


def test_codeview_files_live_and_read(db: Database, tmp_path: Path) -> None:  # noqa: F811
    main = tmp_path / "main.rs"
    main.write_text('fn main() { println!("ok"); }', encoding="utf-8")
    other = tmp_path / "notes.md"
    for path in (main, other, main):
        row = activity.tool_started(db, "sonnet", 3, "write_file", {"path": str(path)})
        activity.tool_finished(db, row, "write_file", {"path": str(path)}, "écrit", 0.0)
    failed = activity.tool_started(db, "sonnet", 3, "write_file", {"path": "C:/no.txt"})
    activity.tool_finished(db, failed, "write_file", {"path": "C:/no.txt"}, "ÉCHEC : non", 0.0)
    found = codeview.files(db, agent="sonnet")
    assert [f["name"] for f in found] == ["main.rs", "notes.md"]
    assert found[0]["lang"] == "rust" and found[0]["edits"] == 2
    assert codeview.files(db, agent="chatgpt") == []
    text = codeview.read(str(main), found)
    assert text["text"].startswith("fn main") and not text["missing"]
    assert codeview.read(str(other), found)["missing"] is True
    with pytest.raises(KeyError):
        codeview.read(str(tmp_path / "secret.txt"), found)  # never a file no agent wrote
    live = codeview.live(db, "sonnet", since=0)
    assert live["changed"] and live["doing"].startswith("write_file") and live["files"]
    assert not codeview.live(db, "sonnet", since=live["last"])["changed"]
    assert codeview.language("a.unknown") == "text"


def test_codeview_api(api: Client, service: AssistantService, tmp_path: Path) -> None:  # noqa: F811
    file = tmp_path / "home" / "lib.rs"
    file.write_text("pub fn f() {}", encoding="utf-8")
    row = activity.tool_started(service.db, "celya", None, "write_file", {"path": str(file)})
    activity.tool_finished(service.db, row, "write_file", {"path": str(file)}, "ok", 0.0)
    status, data = api.json("GET", "/api/assistant/team/celya/code")
    assert status == 200 and data["files"][0]["name"] == "lib.rs"
    status, data = api.json("GET", f"/api/assistant/team/celya/code/file?path={file}")
    assert status == 200 and data["text"] == "pub fn f() {}"
    assert api.json("GET", "/api/assistant/team/nobody/code")[0] == 404


# ---- pages opened in Chrome --------------------------------------------------------------------


def test_browser_pages(db: Database, tmp_path: Path) -> None:  # noqa: F811
    root = tmp_path / "assistant"
    assert browser_pages.token(root, create=False) == ""
    assert not browser_pages.authorized(root, "Bearer x")
    key = browser_pages.token(root)
    assert browser_pages.authorized(root, f"Bearer {key}") and not browser_pages.authorized(
        root, "Bearer faux"
    )
    assert browser_pages.renew(root) != key
    pages = browser_pages.Pages(db)
    assert "Aucune page" in pages.for_agent()
    first = pages.save("https://example.org/a", "  Un   titre ", "Bonjour le monde")
    assert pages.save("https://example.org/a", "Titre", "Bonjour encore")["id"] == first["id"]
    pages.save("https://wiki.org/rust", "Rust", "ownership et emprunts")
    with pytest.raises(browser_pages.BrowserError, match="connexion"):
        pages.save("https://accounts.google.com/signin", "Connexion", "mot de passe")
    with pytest.raises(browser_pages.BrowserError, match="http"):
        pages.save("file:///C:/x.txt", "x", "y")
    listing = pages.for_agent()
    assert listing.index("wiki.org") < listing.index("example.org")
    last = pages.for_agent("derniere")
    assert last.startswith("[Contenu d'une page web") and "ownership" in last
    assert "Bonjour encore" in pages.for_agent(str(first["id"]))
    assert "wiki.org" in pages.for_agent(search="emprunts")
    assert "Aucune page" in pages.for_agent(search="introuvable")
    with pytest.raises(KeyError):
        pages.get(999)
    assert pages.forget() == 2 and pages.recent() == []


def test_browser_endpoint_and_tool(api: Client, service: AssistantService) -> None:  # noqa: F811
    page = {"url": "https://example.org", "title": "Ex", "text": "Texte de la page"}
    status, body = api.json("POST", "/browser/page", page, headers={"Authorization": "Bearer x"})
    assert status == 401
    key = api.json("POST", "/api/assistant/browser/token", {})[1]["token"]
    auth = {"Authorization": f"Bearer {key}"}
    status, body = api.json("POST", "/browser/page", page, headers=auth)
    assert status == 200 and body["result"].startswith("page #1 reçue")
    assert api.json("POST", "/browser/page", [1], headers=auth)[0] == 400
    data = api.json("GET", "/api/assistant/browser")[1]
    assert data["ready"] and data["pages"][0]["title"] == "Ex"
    assert data["extension"].endswith("chrome-extension")
    out = tools_mod.execute(service.gate, service.ctx, "browser_pages", {"page": "1"})
    assert "Texte de la page" in out
    out = tools_mod.execute(service.gate, service.ctx, "browser_pages", {"page": "42"})
    assert "introuvable" in out
    assert api.json("POST", "/api/assistant/browser/forget", {})[1] == {"forgotten": 1}


def test_extension_files_exist() -> None:
    folder = Path(__file__).resolve().parents[1] / "tools" / "chrome-extension"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3 and manifest["incognito"] == "not_allowed"
    for name in ("background.js", "options.html", "options.js", "popup.html", "popup.js"):
        assert (folder / name).is_file()


# ---- Spectre in VS Code ----------------------------------------------------------------------


def test_vscode_connect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user = tmp_path / "Code" / "User"
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert vscode.status()["installed"] is False
    with pytest.raises(ValueError, match="VS Code"):
        vscode.connect(tmp_path / "assistant")
    user.mkdir(parents=True)
    (user / "mcp.json").write_text('{"servers": {"autre": {"type": "stdio"}}}', encoding="utf-8")
    assert "branché" in vscode.connect(tmp_path / "assistant")
    data = json.loads((user / "mcp.json").read_text(encoding="utf-8"))
    assert set(data["servers"]) == {"autre", "spectre"}
    assert data["servers"]["spectre"]["args"] == ["-m", "spectre.assistant.mcp_server"]
    assert list(user.glob("mcp.json.*.bak")) and vscode.status()["connected"]
    assert "débranché" in vscode.disconnect() and "n'était pas" in vscode.disconnect()
    (user / "mcp.json").write_text("// commentaire\n{", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        vscode.connect(tmp_path / "assistant")


def test_vscode_api(api: Client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: F811
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "Code" / "User").mkdir(parents=True)
    assert api.json("GET", "/api/assistant/vscode")[1]["connected"] is False
    assert "branché" in api.json("POST", "/api/assistant/vscode/connect", {})[1]["result"]
    assert api.json("POST", "/api/assistant/vscode/nope", {})[0] == 404


# ---- the new kits: Rust, VS Code, Charlotte's and Célya's tools ------------------------------


class Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kw: Any) -> Any:
        import subprocess

        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")


@pytest.fixture
def kit_ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(toolkit, "_bin", lambda names: "C:/bin/" + names[0])
    folder = tmp_path / "folder"
    (folder / "proj").mkdir(parents=True)
    (folder / "proj" / "Cargo.toml").write_text("[package]", encoding="utf-8")
    base = Database(tmp_path / "a.db")
    ctx = tools_mod.make_context(base, tmp_path / "assistant", [str(folder)])
    ctx.runner = Runner()
    yield ctx, folder
    base.close()


def test_cargo_kit(kit_ctx: Any) -> None:
    ctx, folder = kit_ctx
    toolkit.run(ctx, "cargo", str(folder / "proj"), "clippy --strict")
    assert ctx.runner.calls[-1][1:] == [
        "clippy",
        "--manifest-path",
        str((folder / "proj" / "Cargo.toml").resolve()),
        "--",
        "-D",
        "warnings",
    ]
    toolkit.run(ctx, "cargo", str(folder / "proj"), "")
    assert ctx.runner.calls[-1][1] == "check"
    toolkit.run(ctx, "cargo", str(folder / "neuf"), "new --lib")
    assert ctx.runner.calls[-1][1:3] == ["new", "--lib"]
    with pytest.raises(ActionError, match="commande au choix"):
        toolkit.run(ctx, "cargo", str(folder / "proj"), "run")
    with pytest.raises(ActionError, match="Cargo.toml"):
        toolkit.run(ctx, "cargo", str(folder), "test")
    assert toolkit.KITS["cargo"].agents == ()  # every agent masters Rust


def test_vscode_kit(kit_ctx: Any) -> None:
    ctx, folder = kit_ctx
    file = folder / "proj" / "main.rs"
    toolkit.run(ctx, "vscode", str(file), "ligne:12")
    assert ctx.runner.calls[-1][1:] == ["--reuse-window", "--goto", f"{file.resolve()}:12"]
    toolkit.run(ctx, "vscode", str(file), f"diff:{folder / 'proj' / 'old.rs'}")
    assert ctx.runner.calls[-1][2] == "--diff"
    toolkit.run(ctx, "vscode", str(folder / "proj"), "")
    assert ctx.runner.calls[-1][1:] == ["--reuse-window", str((folder / "proj").resolve())]
    with pytest.raises(ActionError, match="ligne"):
        toolkit.run(ctx, "vscode", str(file), "ligne:x")
    with pytest.raises(ActionError, match="caractère spécial"):
        toolkit.run(ctx, "vscode", str(folder / "a&b.txt"), "")


def test_designer_and_novelist_kits(kit_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, folder = kit_ctx
    ctx.agent = "charlotte"
    logo = folder / "logo.png"
    logo.write_bytes(b"png")
    with pytest.raises(ActionError, match="code 0"):  # the runner writes no file
        toolkit.run(ctx, "vectoriser", str(logo), "noir")
    assert ctx.runner.calls[-1][-1] == "bw"
    toolkit.run(ctx, "palette", str(logo), "6")
    assert ctx.runner.calls[-1][2:4] == ["-colors", "6"]
    with pytest.raises(ActionError, match="de 2 à 24"):
        toolkit.run(ctx, "palette", str(logo), "99")
    with pytest.raises(ActionError, match="pas un outil de ton domaine"):
        toolkit.run(ctx, "livre_pdf", str(folder / "livre.typ"))
    ctx.agent = "celya"
    with pytest.raises(ActionError, match=r"\.typ"):
        toolkit.run(ctx, "livre_pdf", str(folder / "livre.md"))
    with pytest.raises(ActionError, match="format voulu"):
        toolkit.run(ctx, "ebook", str(folder / "livre.epub"), "exe")
    grammar = folder / "Apps" / "grammalecte-2.3.0" / "grammalecte-cli.py"
    monkeypatch.setattr(toolkit, "_grammalecte_cli", lambda: grammar)
    with pytest.raises(ActionError, match="pas installé"):
        toolkit.run(ctx, "grammalecte", str(folder / "ch1.md"))
    grammar.parent.mkdir(parents=True)
    grammar.write_text("", encoding="utf-8")
    toolkit.run(ctx, "grammalecte", str(folder / "ch1.md"))
    assert ctx.runner.calls[-1][1] == str(grammar)
    names = {k["name"]: k for k in toolkit.describe(None)}
    assert names["grammalecte"]["installed"] and "celya" in names["epub_verif"]["agents"]


# ---- Claude Code's video skills, shared with the agents ---------------------------------------


def _skill(folder: Path, name: str, head: str) -> None:
    (folder / name).mkdir(parents=True)
    (folder / name / "SKILL.md").write_text(f"---\n{head}\n---\n\n# {name}\n", encoding="utf-8")


def test_shared_video_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    own, shared = tmp_path / "own", tmp_path / "shared"
    _skill(own, "spectre-amitie", "name: spectre-amitie\ndescription: Amitié.")
    _skill(shared, "hyperframes", "name: hyperframes\ndescription: >\n  Vidéos HTML\n  animées.")
    _skill(shared, "motion-graphics", 'name: motion-graphics\ndescription: "Motion design."')
    _skill(shared, "skill-creator", "name: skill-creator\ndescription: Pas pour les agents.")
    monkeypatch.delenv(competences.DIR_ENV, raising=False)
    monkeypatch.setattr(competences, "skills_dir", lambda: own)
    monkeypatch.setenv(competences.SHARED_ENV, str(shared))
    names = [c.name for c in competences.available()]
    assert names == ["hyperframes", "motion-graphics", "spectre-amitie"]
    found = {c.name: c for c in competences.available()}
    assert found["hyperframes"].description == "Vidéos HTML animées."
    assert found["motion-graphics"].description == "Motion design."
    assert competences.for_agent("charlotte") == ["motion-graphics"]
    assert competences.for_agent("") == ["hyperframes", "motion-graphics"]
    assert "[vidéo, pour Kyra, Charlotte]" in competences.catalogue()
    assert competences.read("hyperframes").startswith("(Dossier de la compétence")
    assert [c.name for c in competences.available(own)] == ["spectre-amitie"]


def test_new_agents_and_skills_are_wired() -> None:
    from spectre.assistant.config import AGENT_NAMES, resolve_agent
    from spectre.assistant.missions import SPECIALTIES
    from spectre.config import AGENT_DEFAULT_ENGINES

    assert AGENT_NAMES["charlotte"] == "Charlotte" and resolve_agent("celya") == "celya"
    assert AGENT_DEFAULT_ENGINES["celya"].startswith("gemini:")
    assert "spectre-graphisme" in SPECIALTIES["charlotte"]
    assert "spectre-roman" in SPECIALTIES["celya"]
    names = {c.name for c in competences.available(competences.skills_dir())}
    assert {"spectre-rust", "spectre-graphisme", "spectre-roman"} <= names


def test_codeview_dev_worktree(db: Database, tmp_path: Path) -> None:  # noqa: F811
    import subprocess

    tree = tmp_path / "wt"
    tree.mkdir()
    git = ["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    (tree / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    (tree / "a.py").write_text("x = 2\n", encoding="utf-8")
    db.execute(
        "INSERT INTO dev_jobs(company_id, request, status, branch, worktree, created_at) "
        "VALUES(1, 'Export CSV', 'working', 'spectre/1-csv', ?, 't')",
        (str(tree),),
    )
    db.execute(
        "INSERT INTO dev_jobs(company_id, request, status, branch, worktree, created_at) "
        "VALUES(1, 'Ancien', 'done', 'b', ?, 't')",
        (str(tmp_path / "gone"),),
    )
    jobs = codeview.live(db, "sonnet")["dev"]
    assert len(jobs) == 1 and jobs[0]["changed"] == ["a.py"] and "+x = 2" in jobs[0]["diff"]
    assert codeview.live(db, "lexy")["dev"] == []
    assert codeview._git(str(tmp_path / "nowhere"), "status") == ""
