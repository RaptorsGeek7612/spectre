"""Windows desktop helpers (ctypes): list monitors, find the window a launch created, move it.

Everything here is best effort and Windows-only; other platforms get no-ops.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Monitor:
    index: int
    left: int
    top: int
    width: int
    height: int
    primary: bool


IS_WINDOWS = sys.platform == "win32"


def monitors() -> list[Monitor]:  # pragma: no cover - needs a real Windows desktop
    """Connected monitors, primary first, then left to right."""
    if not IS_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[tuple[int, int, int, int, bool]] = []

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    proc_type = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def callback(hmon, _hdc, _rect, _data):  # type: ignore[no-untyped-def]
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        r = info.rcWork
        found.append((r.left, r.top, r.right - r.left, r.bottom - r.top, bool(info.dwFlags & 1)))
        return 1

    user32.EnumDisplayMonitors(None, None, proc_type(callback), 0)
    found.sort(key=lambda m: (not m[4], m[0], m[1]))
    return [Monitor(i, *m) for i, m in enumerate(found)]


def visible_windows() -> set[int]:  # pragma: no cover - needs a real Windows desktop
    """Handles of visible top-level windows that have a title."""
    if not IS_WINDOWS:
        return set()
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    handles: set[int] = set()
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _data):  # type: ignore[no-untyped-def]
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            handles.add(int(hwnd))
        return True

    user32.EnumWindows(proc_type(callback), 0)
    return handles


def move_new_window(
    before: set[int], monitor_index: int, timeout_s: float = 8.0
) -> bool:  # pragma: no cover
    """Wait for a window that was not in `before` and maximise it on the given monitor."""
    if not IS_WINDOWS:
        return False
    import ctypes

    screens = monitors()
    if not 0 <= monitor_index < len(screens):
        return False
    target = screens[monitor_index]
    user32 = ctypes.windll.user32
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        new = visible_windows() - before
        if new:
            hwnd = max(new)
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetWindowPos(
                hwnd, None, target.left, target.top, target.width, target.height, 0x0004
            )
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            return True
        time.sleep(0.25)
    return False
