"""Windows desktop helpers (ctypes): list monitors, find the window a launch created, move it.

Everything here is best effort and Windows-only; other platforms get no-ops.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Monitor:
    index: int
    left: int
    top: int
    width: int
    height: int
    primary: bool


IS_WINDOWS = sys.platform == "win32"


def power_status() -> dict[str, Any]:  # pragma: no cover - needs a real Windows machine
    """On battery or mains, and the charge (empty elsewhere or when Windows does not know)."""
    if sys.platform != "win32":
        return {}
    import ctypes

    class SystemPowerStatus(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_ubyte),
            ("BatteryFlag", ctypes.c_ubyte),
            ("BatteryLifePercent", ctypes.c_ubyte),
            ("SystemStatusFlag", ctypes.c_ubyte),
            ("BatteryLifeTime", ctypes.c_ulong),
            ("BatteryFullLifeTime", ctypes.c_ulong),
        ]

    state = SystemPowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(state)):
        return {}
    return {
        "on_battery": state.ACLineStatus == 0,
        "percent": None if state.BatteryLifePercent == 255 else int(state.BatteryLifePercent),
    }


def monitors() -> list[Monitor]:  # pragma: no cover - needs a real Windows desktop
    """Connected monitors, primary first, then left to right."""
    if sys.platform != "win32":  # literal check: lets mypy skip Win32 code elsewhere
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

    def callback(hmon: int, _hdc: int, _rect: object, _data: int) -> bool:
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        r = info.rcWork
        found.append((r.left, r.top, r.right - r.left, r.bottom - r.top, bool(info.dwFlags & 1)))
        return True

    user32.EnumDisplayMonitors(None, None, proc_type(callback), 0)
    found.sort(key=lambda m: (not m[4], m[0], m[1]))
    return [Monitor(i, *m) for i, m in enumerate(found, start=1)]  # as people say them


def visible_windows() -> set[int]:  # pragma: no cover - needs a real Windows desktop
    """Handles of visible top-level windows that have a title."""
    if sys.platform != "win32":  # literal check: lets mypy skip Win32 code elsewhere
        return set()
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    handles: set[int] = set()
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _data: int) -> bool:
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            handles.add(int(hwnd))
        return True

    user32.EnumWindows(proc_type(callback), 0)
    return handles


def move_new_window(
    before: set[int], monitor_index: int, timeout_s: float = 8.0
) -> bool:  # pragma: no cover
    """Wait for a window that was not in `before` and maximise it on the given monitor."""
    if sys.platform != "win32":  # literal check: lets mypy skip Win32 code elsewhere
        return False
    import ctypes

    target = next((m for m in monitors() if m.index == monitor_index), None)
    if target is None:
        return False
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
