"""Entry point for the Teacher desktop application."""

from __future__ import annotations

import asyncio
import sys

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from shared.config import TeacherConfig, get_app_data_dir, load_config, save_config
from shared.logging_setup import setup_logging
from teacher_app.ui.dialogs import TeacherLoginDialog, TeacherSetupWizardDialog
from teacher_app.ui.main_window import ServerSignals, TeacherMainWindow
from teacher_app.ui.theme import get_stylesheet, make_app_icon, set_windows_app_id


def main() -> int:
    set_windows_app_id("ClassroomManager.Teacher.Console")

    app = QApplication(sys.argv)
    app.setApplicationName("ClassroomManager Teacher")
    app.setWindowIcon(make_app_icon("teacher"))

    data_dir = get_app_data_dir("teacher")
    config_path = data_dir / "config.json"
    config = load_config(config_path, TeacherConfig)
    app.setStyleSheet(get_stylesheet(config.theme))

    # First-run setup or password login (skipped when "remember_login" is enabled)
    if not config.initialized or not config.password_hash:
        wizard = TeacherSetupWizardDialog(config)
        if wizard.exec() != TeacherSetupWizardDialog.DialogCode.Accepted:
            return 0
        save_config(config_path, config)
    elif not config.remember_login:
        login = TeacherLoginDialog(
            config.password_hash,
            config.classroom_id,
            remember_login=config.remember_login,
        )
        if login.exec() != TeacherLoginDialog.DialogCode.Accepted:
            return 0
        if login.remember_login != config.remember_login:
            config.remember_login = login.remember_login
            save_config(config_path, config)

    signals = ServerSignals()
    setup_logging(data_dir / "logs", "teacher", ui_callback=signals.log_line.emit)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = TeacherMainWindow(config, config_path, data_dir, signals)
    window.show()

    with loop:
        loop.create_task(window.start_server())
        loop.run_forever()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
