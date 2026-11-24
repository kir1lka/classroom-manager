"""Entry point for the Student background tray agent."""

from __future__ import annotations

import asyncio
import ctypes
import os
import sys

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from shared.config import StudentConfig, get_app_data_dir, load_config, save_config
from shared.logging_setup import setup_logging
from student_app.ui.dialogs import StudentSettingsDialog
from student_app.ui.tray_agent import StudentTrayAgent
from teacher_app.ui.theme import DARK_STYLE

ERROR_ALREADY_EXISTS = 183


def _acquire_single_instance_mutex():
    """Prevent duplicate background agents unless CLASSROOM_ALLOW_MULTI=1 is set."""
    if sys.platform != "win32" or os.environ.get("CLASSROOM_ALLOW_MULTI") == "1":
        return None
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ClassroomManagerStudentAgent")
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False
    return handle


def main() -> int:
    mutex = _acquire_single_instance_mutex()
    if mutex is False:
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("ClassroomManager Student")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(DARK_STYLE)

    data_dir = get_app_data_dir("student")
    config_path = data_dir / "config.json"
    config = load_config(config_path, StudentConfig)

    # First-run setup wizard (must be configured by teacher/admin once)
    if not config.initialized or not config.admin_password_hash:
        setup_dlg = StudentSettingsDialog(config, first_run=True)
        if setup_dlg.exec() != StudentSettingsDialog.DialogCode.Accepted:
            return 0
        save_config(config_path, config)

    setup_logging(data_dir / "logs", "student")

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    agent = StudentTrayAgent(app, config, config_path, loop=loop)

    with loop:
        loop.call_soon(agent.start)
        loop.run_forever()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
