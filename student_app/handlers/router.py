"""Command dispatcher for the Student agent."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from student_app.handlers.system_ops import (
    execute_power_action,
    get_system_info,
    run_powershell,
)

logger = logging.getLogger("classroom_manager.student.router")


class CommandRouter:
    """Executes authenticated commands received from the Teacher server."""

    def __init__(
        self,
        on_lock_screen: Callable[[str], None] | None = None,
        on_unlock_screen: Callable[[], None] | None = None,
        on_show_message: Callable[[str, str], None] | None = None,
    ) -> None:
        self.on_lock_screen = on_lock_screen
        self.on_unlock_screen = on_unlock_screen
        self.on_show_message = on_show_message
        self.screen_locked = False

    async def dispatch(self, command: str, params: dict[str, Any]) -> dict[str, Any]:
        cmd = command.strip().upper()
        try:
            if cmd == "PING":
                return {"ok": True, "data": {"pong": True, "ts": time.time()}}

            if cmd == "GET_SYSTEM_INFO":
                return {"ok": True, "data": get_system_info()}

            if cmd == "POWERSHELL":
                script = str(params.get("script", ""))
                timeout = float(params.get("timeout", 30.0))
                result = await run_powershell(script, timeout=timeout)
                return {"ok": True, "data": result}

            if cmd == "LOCK_SCREEN":
                message = str(params.get("message") or "(срок бана: 1000 лет)")
                self.screen_locked = True
                if self.on_lock_screen:
                    self.on_lock_screen(message)
                return {"ok": True, "data": {"locked": True}}

            if cmd == "UNLOCK_SCREEN":
                self.screen_locked = False
                if self.on_unlock_screen:
                    self.on_unlock_screen()
                return {"ok": True, "data": {"locked": False}}

            if cmd == "POWER_ACTION":
                action = str(params.get("action", ""))
                res = execute_power_action(action)
                return {"ok": bool(res.get("ok")), "data": res, "error": "" if res.get("ok") else res.get("detail", "")}

            if cmd == "SHOW_MESSAGE":
                title = str(params.get("title") or "Сообщение от учителя")
                text = str(params.get("text") or "")
                if self.on_show_message:
                    self.on_show_message(title, text)
                return {"ok": True, "data": {"shown": True}}

            return {"ok": False, "error": f"Неизвестная команда: {command}"}
        except Exception as exc:
            logger.exception("Command %s failed: %s", cmd, exc)
            return {"ok": False, "error": str(exc)}
