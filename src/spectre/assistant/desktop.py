"""The programs the user opens on this PC, seen by Spectre (nothing leaves the machine).

Every few seconds a watcher lists the visible windows (title, program) and notes in the
database when a program appears or goes away, and which one is in front. Spectre reads it with
the `desktop_apps` tool: what is open now, and what was opened or closed lately. The pages of
Chrome come from Spectre's extension instead (`browser_pages.py`).

Private windows (InPrivate, incognito), password managers and sign-in screens are never kept;
titles are shortened. The user turns the watcher off with the `desktop_watch` setting, or
forgets everything in one call (`forget`).
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePath

from spectre.assistant.db import Database, now_iso

KEEP_DAYS = 30
TITLE_MAX = 160
SHOWN = 40  # events listed at once
# never kept: private browsing, password managers, sign-in and payment screens
PRIVATE_TITLES = ("inprivate", "incognito", "navigation privée", "private browsing")
PRIVATE_APPS = ("keepass", "keepassxc", "bitwarden", "1password", "dashlane", "lastpass")
SECRET_WORDS = ("mot de passe", "password", "connexion", "sign in", "login", "paiement")
# the shell and system windows are noise
IGNORED_APPS = (
    "explorer",
    "textinputhost",
    "applicationframehost",
    "shellexperiencehost",
    "searchhost",
    "startmenuexperiencehost",
    "systemsettings",
    "lockapp",
)
FRIENDLY = {
    "chrome": "Chrome",
    "msedge": "Edge",
    "firefox": "Firefox",
    "code": "VS Code",
    "windowsterminal": "Terminal",
    "winword": "Word",
    "excel": "Excel",
    "powerpnt": "PowerPoint",
    "obs64": "OBS Studio",
}


@dataclass(frozen=True)
class Window:
    app: str  # the program's file name without .exe, lower case ("chrome", "kdenlive")
    title: str


def label(app: str) -> str:
    return FRIENDLY.get(app, app[:1].upper() + app[1:])


def private(window: Window) -> bool:
    title = window.title.lower()
    return (
        window.app in PRIVATE_APPS
        or any(word in title for word in PRIVATE_TITLES)
        or any(word in title for word in SECRET_WORDS)
    )


def clean(windows: Iterable[Window]) -> list[Window]:
    """The windows worth knowing about: no system noise, nothing private, short titles."""
    kept = []
    for window in windows:
        if not window.app or window.app in IGNORED_APPS or private(window):
            continue
        kept.append(Window(window.app, " ".join(window.title.split())[:TITLE_MAX]))
    return kept


class Desktop:
    """What the user has open, and what changed: kept in the database, read by Spectre."""

    def __init__(self, db: Database, lister: Callable[[], list[Window]] | None = None) -> None:
        self.db = db
        self.lister = lister or open_windows
        self._apps: set[str] | None = None  # programs seen at the last look
        self._front = ""

    def observe(self, windows: list[Window] | None = None, front: Window | None = None) -> int:
        """Note the programs opened and closed since the last look; returns the changes."""
        seen = clean(self.lister() if windows is None else windows)
        apps = {w.app for w in seen}
        titles = {w.app: w.title for w in seen}
        changes = 0
        if self._apps is not None:  # the first look only sets the baseline
            for app in sorted(apps - self._apps):
                self._note("ouvert", app, titles.get(app, ""))
                changes += 1
            for app in sorted(self._apps - apps):
                self._note("fermé", app, "")
                changes += 1
        self._apps = apps
        if front is not None and clean([front]):
            shown = clean([front])[0]
            key = f"{shown.app}|{shown.title}"
            if key != self._front:
                self._front = key
                self.db.set_kv("desktop_front", f"{now_iso()}|{shown.app}|{shown.title}")
        if changes:
            cutoff = (datetime.now(UTC) - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
            self.db.execute("DELETE FROM desktop_events WHERE ts < ?", (cutoff,))
        return changes

    def _note(self, kind: str, app: str, title: str) -> None:
        self.db.execute(
            "INSERT INTO desktop_events(ts, kind, app, title) VALUES(?, ?, ?, ?)",
            (now_iso(), kind, app, title),
        )

    def now(self, windows: list[Window] | None = None) -> str:
        """The programs open right now and their windows' titles."""
        seen = clean(self.lister() if windows is None else windows)
        if not seen:
            return "Aucun logiciel ouvert (ou observation des fenêtres indisponible)."
        by_app: dict[str, list[str]] = {}
        for window in seen:
            by_app.setdefault(window.app, []).append(window.title)
        lines = [
            f"- {label(app)} : " + " | ".join(dict.fromkeys(titles))[:400]
            for app, titles in sorted(by_app.items())
        ]
        front = self.db.get_kv("desktop_front")
        stamp, _, rest = front.partition("|")
        app, _, title = rest.partition("|")
        head = "Logiciels ouverts par l'utilisateur en ce moment"
        if app:
            head += f" (au premier plan : {label(app)} — {title}, depuis {stamp[11:16]} UTC)"
        return head + " :\n" + "\n".join(lines)

    def history(self, search: str = "", limit: int = SHOWN) -> str:
        """The programs opened and closed lately, newest first."""
        if search.strip():
            like = f"%{search.strip().lower()}%"
            rows = self.db.all(
                "SELECT * FROM desktop_events WHERE lower(app) LIKE ? OR lower(title) LIKE ? "
                "ORDER BY id DESC LIMIT ?",
                (like, like, limit),
            )
        else:
            rows = self.db.all("SELECT * FROM desktop_events ORDER BY id DESC LIMIT ?", (limit,))
        if not rows:
            return "Rien de noté (l'observation des logiciels est arrêtée ou vient de démarrer)."
        return "Logiciels ouverts et fermés, le plus récent d'abord (heures UTC) :\n" + "\n".join(
            f"- {r['ts'][:16].replace('T', ' ')} {r['kind']} : {label(r['app'])}"
            + (f" — {r['title']}" if r["title"] else "")
            for r in rows
        )

    def forget(self) -> int:
        count = len(self.db.all("SELECT id FROM desktop_events"))
        self.db.execute("DELETE FROM desktop_events")
        self.db.set_kv("desktop_front", "")
        self._apps = None
        return count


def _app_of(path: str) -> str:
    name = PurePath(path.replace("\\", "/")).name.lower()
    return name[:-4] if name.endswith(".exe") else name


def open_windows() -> list[Window]:  # pragma: no cover - needs a real Windows desktop
    """The visible top-level windows with a title, and the program of each."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[Window] = []
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _data: int) -> bool:
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            window = _describe(hwnd)
            if window is not None:
                found.append(window)
        return True

    user32.EnumWindows(proc_type(callback), 0)
    return found


def front_window() -> Window | None:  # pragma: no cover - needs a real Windows desktop
    if sys.platform != "win32":
        return None
    import ctypes

    hwnd = ctypes.windll.user32.GetForegroundWindow()
    return _describe(hwnd) if hwnd else None


def _describe(hwnd: int) -> Window | None:  # pragma: no cover - needs a real Windows desktop
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    length = u32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    u32.GetWindowTextW(hwnd, buffer, length + 1)
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = k32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        path = ctypes.create_unicode_buffer(size.value)
        if not k32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            return None
    finally:
        k32.CloseHandle(handle)
    return Window(_app_of(path.value), buffer.value)
