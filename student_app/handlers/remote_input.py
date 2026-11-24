"""Native Windows remote mouse and keyboard injection via Win32 SendInput."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


def _send_input(*events: INPUT) -> None:
    if sys.platform != "win32" or not events:
        return
    arr = (INPUT * len(events))(*events)
    ctypes.windll.user32.SendInput(len(events), ctypes.byref(arr), ctypes.sizeof(INPUT))


def _norm_coord(val: float) -> int:
    clamped = max(0.0, min(1.0, float(val)))
    return int(round(clamped * 65535))


def handle_remote_input(payload: dict[str, Any]) -> None:
    """Apply a remote mouse or keyboard event received from the Teacher console."""
    if sys.platform != "win32":
        return

    event = str(payload.get("event", ""))

    if event == "mouse_move":
        dx = _norm_coord(payload.get("x", 0.0))
        dy = _norm_coord(payload.get("y", 0.0))
        inp = INPUT(
            type=INPUT_MOUSE,
            union=_INPUT_UNION(mi=MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, 0)),
        )
        _send_input(inp)

    elif event in ("mouse_down", "mouse_up"):
        dx = _norm_coord(payload.get("x", 0.0))
        dy = _norm_coord(payload.get("y", 0.0))
        button = str(payload.get("button", "left"))
        down = event == "mouse_down"
        flag_map = {
            ("left", True): MOUSEEVENTF_LEFTDOWN,
            ("left", False): MOUSEEVENTF_LEFTUP,
            ("right", True): MOUSEEVENTF_RIGHTDOWN,
            ("right", False): MOUSEEVENTF_RIGHTUP,
            ("middle", True): MOUSEEVENTF_MIDDLEDOWN,
            ("middle", False): MOUSEEVENTF_MIDDLEUP,
        }
        btn_flag = flag_map.get((button, down))
        if btn_flag is None:
            return
        move_inp = INPUT(
            type=INPUT_MOUSE,
            union=_INPUT_UNION(mi=MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, 0)),
        )
        btn_inp = INPUT(
            type=INPUT_MOUSE,
            union=_INPUT_UNION(mi=MOUSEINPUT(dx, dy, 0, btn_flag | MOUSEEVENTF_ABSOLUTE, 0, 0)),
        )
        _send_input(move_inp, btn_inp)

    elif event == "mouse_wheel":
        delta = int(payload.get("delta", 0))
        inp = INPUT(
            type=INPUT_MOUSE,
            union=_INPUT_UNION(mi=MOUSEINPUT(0, 0, ctypes.c_uint32(delta).value, MOUSEEVENTF_WHEEL, 0, 0)),
        )
        _send_input(inp)

    elif event in ("key_down", "key_up"):
        vk = int(payload.get("vk", 0))
        if vk <= 0 or vk > 0xFE:
            return
        flags = 0 if event == "key_down" else KEYEVENTF_KEYUP
        inp = INPUT(
            type=INPUT_KEYBOARD,
            union=_INPUT_UNION(ki=KEYBDINPUT(vk, 0, flags, 0, 0)),
        )
        _send_input(inp)

    elif event == "key_text":
        text = str(payload.get("text", ""))
        events: list[INPUT] = []
        for ch in text:
            code = ord(ch)
            events.append(
                INPUT(
                    type=INPUT_KEYBOARD,
                    union=_INPUT_UNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, 0)),
                )
            )
            events.append(
                INPUT(
                    type=INPUT_KEYBOARD,
                    union=_INPUT_UNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)),
                )
            )
        if events:
            _send_input(*events)
