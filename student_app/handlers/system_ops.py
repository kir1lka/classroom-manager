"""Windows system info, PowerShell execution, and power actions for the Student agent."""

from __future__ import annotations

import asyncio
import ctypes
import getpass
import os
import platform
import socket
import subprocess
import sys
from typing import Any


def get_active_window_title() -> str:
    """Return the title of the currently focused Windows window."""
    if sys.platform != "win32":
        return ""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value[:120]
    except Exception:
        return ""


def get_screen_resolution() -> tuple[int, int]:
    """Return primary monitor resolution on Windows."""
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
        except Exception:
            pass
    return 1920, 1080


def get_system_info() -> dict[str, Any]:
    """Collect host metadata reported to the Teacher console."""
    w, h = get_screen_resolution()
    return {
        "hostname": socket.gethostname(),
        "username": getpass.getuser(),
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "cpu_count": os.cpu_count() or 1,
        "screen_width": w,
        "screen_height": h,
        "active_window": get_active_window_title(),
    }


async def run_powershell(script: str, timeout: float = 30.0) -> dict[str, Any]:
    """Execute a PowerShell command asynchronously with UTF-8 output and timeout."""
    if not script or not script.strip():
        return {"returncode": -1, "stdout": "", "stderr": "Пустая команда"}

    wrapped = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$OutputEncoding = [System.Text.Encoding]::UTF8; "
        + script
    )

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = await asyncio.create_subprocess_exec(
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        wrapped,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=creation_flags,
    )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Превышен таймаут выполнения ({timeout:.0f} с)",
            "timed_out": True,
        }

    return {
        "returncode": int(proc.returncode or 0),
        "stdout": stdout_b.decode("utf-8", errors="replace"),
        "stderr": stderr_b.decode("utf-8", errors="replace"),
        "timed_out": False,
    }


def execute_power_action(action: str) -> dict[str, Any]:
    """Execute a Windows lock/shutdown/reboot/logoff command."""
    if sys.platform != "win32":
        return {"ok": False, "detail": "Доступно только на Windows"}

    action = action.strip().lower()
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    if action == "lock_os":
        ctypes.windll.user32.LockWorkStation()
        return {"ok": True, "detail": "Рабочая станция Windows заблокирована"}

    if action == "shutdown":
        subprocess.Popen(
            ["shutdown", "/s", "/t", "5", "/c", "Команда учителя: выключение ПК"],
            creationflags=creation_flags,
        )
        return {"ok": True, "detail": "Выключение запланировано через 5 секунд"}

    if action == "reboot":
        subprocess.Popen(
            ["shutdown", "/r", "/t", "5", "/c", "Команда учителя: перезагрузка ПК"],
            creationflags=creation_flags,
        )
        return {"ok": True, "detail": "Перезагрузка запланирована через 5 секунд"}

    if action == "logoff":
        subprocess.Popen(["shutdown", "/l"], creationflags=creation_flags)
        return {"ok": True, "detail": "Выход из сеанса Windows выполнен"}

    if action == "cancel_shutdown":
        subprocess.Popen(["shutdown", "/a"], creationflags=creation_flags)
        return {"ok": True, "detail": "Отмена выключения/перезагрузки отправлена"}

    return {"ok": False, "detail": f"Неизвестное действие питания: {action}"}
