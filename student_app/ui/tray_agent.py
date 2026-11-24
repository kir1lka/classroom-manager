"""System tray controller for the Student background agent."""

from __future__ import annotations

import asyncio
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from shared.config import StudentConfig, save_config
from student_app.handlers.router import CommandRouter
from student_app.network.client import StudentClient
from student_app.ui.demo_overlay import DemoViewerOverlay
from student_app.ui.dialogs import StudentPasswordPrompt, StudentSettingsDialog
from student_app.ui.hotkey import Win32GlobalHotkey
from student_app.ui.lock_overlay import ScreenLockOverlay
from teacher_app.ui.theme import (
    apply_window_chrome,
    make_app_icon,
    make_icon,
    make_status_icon,
)


class StudentSignals(QObject):
    state_changed = Signal(str, str)
    lock_screen = Signal(str)
    unlock_screen = Signal()
    show_message = Signal(str, str)
    demo_control = Signal(bool, str, bool)
    demo_frame = Signal(bytes)
    hotkey_triggered = Signal()


class StudentTrayAgent(QObject):
    """Background tray agent with global hotkey, password protection, and lock overlay."""

    def __init__(
        self,
        app: QApplication,
        config: StudentConfig,
        config_path: Path,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        super().__init__()
        self.app = app
        self.config = config
        self.config_path = config_path
        self._loop = loop
        self._dialog_open = False

        self.signals = StudentSignals()
        self.signals.state_changed.connect(self._on_state_changed)
        self.signals.lock_screen.connect(self._on_lock_screen)
        self.signals.unlock_screen.connect(self._on_unlock_screen)
        self.signals.show_message.connect(self._on_show_message)
        self.signals.demo_control.connect(self._on_demo_control)
        self.signals.demo_frame.connect(self._on_demo_frame)
        self.signals.hotkey_triggered.connect(self._open_protected_settings)

        self.lock_overlay = ScreenLockOverlay(config.hotkey or "Ctrl+Alt+Shift+M")
        self.demo_overlay = DemoViewerOverlay(config.hotkey or "Ctrl+Alt+Shift+M")

        self.router = CommandRouter(
            on_lock_screen=self.signals.lock_screen.emit,
            on_unlock_screen=self.signals.unlock_screen.emit,
            on_show_message=self.signals.show_message.emit,
        )
        self.client = StudentClient(
            config=config,
            config_path=config_path,
            router=self.router,
            on_state_changed=self.signals.state_changed.emit,
            on_demo_control=self.signals.demo_control.emit,
            on_demo_frame=self.signals.demo_frame.emit,
            loop=self._loop,
        )

        # System Tray Icon (Liquid Glass status orb)
        self.tray = QSystemTrayIcon(make_status_icon("#FF9F0A"), self)
        self.tray.setToolTip("Classroom Student — запуск...")

        menu = QMenu()
        self.status_action = QAction("Статус: запуск...", menu)
        self.status_action.setEnabled(False)
        menu.addAction(self.status_action)
        menu.addSeparator()

        settings_action = QAction(make_icon("settings"), "Настройки (по паролю)...", menu)
        settings_action.triggered.connect(self._open_protected_settings)
        menu.addAction(settings_action)

        exit_action = QAction(make_icon("power", "#FF453A"), "Выход (по паролю)...", menu)
        exit_action.triggered.connect(self._request_protected_exit)
        menu.addAction(exit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        # Global Windows Hotkey
        self.hotkey = Win32GlobalHotkey(1, self.signals.hotkey_triggered.emit)
        self.app.installNativeEventFilter(self.hotkey)
        self.hotkey.register(self.config.hotkey or "Ctrl+Alt+Shift+M")

    def start(self) -> None:
        self.client.start()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._open_protected_settings()

    def _on_state_changed(self, state: str, detail: str) -> None:
        colors = {
            "CONNECTED": "#30D158",
            "DISCOVERING": "#FF9F0A",
            "CONNECTING": "#FF9F0A",
            "AUTHENTICATING": "#0A84FF",
            "RECONNECTING": "#FF9F0A",
            "AUTH_ERROR": "#FF453A",
            "UNCONFIGURED": "#FF453A",
            "STOPPED": "#64748B",
        }
        self.tray.setIcon(make_status_icon(colors.get(state, "#64748B")))
        label = f"{detail or state} ({self.config.classroom_id})"
        self.status_action.setText(label)
        self.tray.setToolTip(f"Classroom Student — {label}")

    def _on_lock_screen(self, message: str) -> None:
        self.lock_overlay.set_hotkey_hint(self.config.hotkey or "Ctrl+Alt+Shift+M")
        self.lock_overlay.lock(message)

    def _on_unlock_screen(self) -> None:
        self.lock_overlay.unlock()

    def _on_demo_control(self, active: bool, title: str, fullscreen: bool) -> None:
        if active:
            self.demo_overlay.set_hotkey_hint(self.config.hotkey or "Ctrl+Alt+Shift+M")
            self.demo_overlay.start_demo(title=title, fullscreen=fullscreen)
        else:
            self.demo_overlay.stop_demo()

    def _on_demo_frame(self, jpeg_bytes: bytes) -> None:
        self.demo_overlay.update_frame(jpeg_bytes)

    def _on_show_message(self, title: str, text: str) -> None:
        box = QMessageBox()
        box.setWindowTitle(title)
        box.setWindowIcon(make_app_icon("student"))
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        apply_window_chrome(box)
        box.exec()

    def _open_protected_settings(self) -> None:
        if self._dialog_open:
            return
        self._dialog_open = True
        try:
            prompt = StudentPasswordPrompt(
                self.config.admin_password_hash,
                "Открыть настройки рабочего места",
            )
            if prompt.exec() != StudentPasswordPrompt.DialogCode.Accepted:
                return

            status_str = (
                f"{self.client.state} — {self.client.state_detail}"
                if self.client.state_detail
                else self.client.state
            )
            dlg = StudentSettingsDialog(
                self.config,
                first_run=False,
                status_text=status_str,
            )
            if dlg.exec() == StudentSettingsDialog.DialogCode.Accepted:
                if dlg.exit_requested:
                    self._schedule(self._shutdown())
                    return
                if dlg.unlock_requested:
                    self.router.screen_locked = False
                    self.lock_overlay.unlock()
                    self.demo_overlay.stop_demo()
                    return
                save_config(self.config_path, self.config)
                self.hotkey.register(self.config.hotkey or "Ctrl+Alt+Shift+M")
                self.lock_overlay.set_hotkey_hint(self.config.hotkey or "Ctrl+Alt+Shift+M")
                self.demo_overlay.set_hotkey_hint(self.config.hotkey or "Ctrl+Alt+Shift+M")
                self.client.trigger_reconnect()
        finally:
            self._dialog_open = False

    def _schedule(self, coro) -> None:
        loop = self._loop or asyncio.get_event_loop()
        loop.create_task(coro)

    def _request_protected_exit(self) -> None:
        if self._dialog_open:
            return
        self._dialog_open = True
        try:
            prompt = StudentPasswordPrompt(
                self.config.admin_password_hash,
                "Остановить и закрыть агент ученика",
            )
            if prompt.exec() == StudentPasswordPrompt.DialogCode.Accepted:
                self._schedule(self._shutdown())
        finally:
            self._dialog_open = False

    async def _shutdown(self) -> None:
        self.lock_overlay.unlock()
        self.demo_overlay.stop_demo()
        self.hotkey.unregister()
        await self.client.stop()
        self.tray.hide()
        self.app.quit()
