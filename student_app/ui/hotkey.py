"""Native Windows global hotkey registration via Win32 RegisterHotKey + Qt event filter."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter

logger = logging.getLogger("classroom_manager.student.hotkey")

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

SPECIAL_VK_MAP: dict[str, int] = {
    "F1": 0x70,
    "F2": 0x71,
    "F3": 0x72,
    "F4": 0x73,
    "F5": 0x74,
    "F6": 0x75,
    "F7": 0x76,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
    "HOME": 0x24,
    "END": 0x23,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "SPACE": 0x20,
}


def parse_hotkey_string(hotkey_str: str) -> tuple[int, int] | None:
    """Parse a string like 'Ctrl+Alt+Shift+M' into (win32_modifiers, vk_code)."""
    parts = [p.strip().upper() for p in hotkey_str.split("+") if p.strip()]
    if not parts:
        return None

    mods = MOD_NOREPEAT
    vk = 0
    for part in parts:
        if part in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif part == "ALT":
            mods |= MOD_ALT
        elif part == "SHIFT":
            mods |= MOD_SHIFT
        elif part in ("WIN", "META"):
            mods |= MOD_WIN
        elif part in SPECIAL_VK_MAP:
            vk = SPECIAL_VK_MAP[part]
        elif len(part) == 1 and ("A" <= part <= "Z" or "0" <= part <= "9"):
            vk = ord(part)
        else:
            return None

    if vk == 0:
        return None
    return mods, vk


class Win32GlobalHotkey(QAbstractNativeEventFilter):
    """Registers a thread-level Win32 global hotkey and fires a callback when pressed."""

    def __init__(self, hotkey_id: int, callback: Callable[[], None]) -> None:
        super().__init__()
        self._hotkey_id = hotkey_id
        self._callback = callback
        self._registered = False

    def register(self, hotkey_str: str) -> bool:
        if sys.platform != "win32":
            return False
        self.unregister()
        parsed = parse_hotkey_string(hotkey_str)
        if parsed is None:
            logger.warning("Invalid hotkey format: %s", hotkey_str)
            return False
        mods, vk = parsed
        ok = bool(ctypes.windll.user32.RegisterHotKey(None, self._hotkey_id, mods, vk))
        self._registered = ok
        if ok:
            logger.info("Registered global hotkey: %s", hotkey_str)
        else:
            logger.warning("Could not register global hotkey %s (already in use?)", hotkey_str)
        return ok

    def unregister(self) -> None:
        if sys.platform == "win32" and self._registered:
            ctypes.windll.user32.UnregisterHotKey(None, self._hotkey_id)
            self._registered = False

    def nativeEventFilter(self, eventType, message):  # type: ignore[override]
        if sys.platform != "win32":
            return False, 0
        try:
            if bytes(eventType) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                    self._callback()
                    return True, 0
        except Exception:
            pass
        return False, 0
