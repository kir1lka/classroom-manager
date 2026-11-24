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
from teacher_app.ui.theme import DARK_STYLE


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ClassroomManager Teacher")
    app.setStyleSheet(DARK_STYLE)

    data_dir = get_app_data_dir("teacher")
    config_path = data_dir / "config.json"
    config = load_config(config_path, TeacherConfig)

    # First-run setup or password login
    if not config.initialized or not config.password_hash:
        wizard = TeacherSetupWizardDialog(config)
        if wizard.exec() != TeacherSetupWizardDialog.DialogCode.Accepted:
            return 0
        save_config(config_path, config)
    else:
        login = TeacherLoginDialog(config.password_hash, config.classroom_id)
        if login.exec() != TeacherLoginDialog.DialogCode.Accepted:
            return 0

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
