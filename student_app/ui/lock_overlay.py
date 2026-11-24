"""Fullscreen Attention Lock overlay controlled remotely by the Teacher."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class ScreenLockOverlay(QWidget):
    """Covers the entire virtual desktop while locked by the Teacher."""

    def __init__(self, hotkey_hint: str = "Ctrl+Alt+Shift+M") -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._locked = False
        self.setStyleSheet("background-color: #0b1120;")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(18)

        icon_lbl = QLabel("🔒")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 64px; background: transparent;")

        self.title_lbl = QLabel("Экран заблокирован учителем")
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_lbl.setStyleSheet(
            "font-size: 32px; font-weight: 700; color: #f8fafc; background: transparent;"
        )

        self.msg_lbl = QLabel("Внимание на учителя!")
        self.msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_lbl.setWordWrap(True)
        self.msg_lbl.setStyleSheet("font-size: 20px; color: #93c5fd; background: transparent;")

        self.hint_lbl = QLabel(f"Локальная разблокировка для учителя: {hotkey_hint}")
        self.hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_lbl.setStyleSheet("font-size: 12px; color: #475569; margin-top: 32px; background: transparent;")

        layout.addWidget(icon_lbl)
        layout.addWidget(self.title_lbl)
        layout.addWidget(self.msg_lbl)
        layout.addWidget(self.hint_lbl)

    def set_hotkey_hint(self, hotkey: str) -> None:
        self.hint_lbl.setText(f"Локальная разблокировка для учителя: {hotkey}")

    def lock(self, message: str = "Внимание на учителя! Экран заблокирован.") -> None:
        self._locked = True
        self.msg_lbl.setText(message)
        # Span across all connected monitors
        screens = QGuiApplication.screens()
        if screens:
            geom = screens[0].geometry()
            for scr in screens[1:]:
                geom = geom.united(scr.geometry())
            self.setGeometry(geom)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def unlock(self) -> None:
        self._locked = False
        self.hide()

    def closeEvent(self, event) -> None:
        if self._locked:
            event.ignore()
            return
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        # Ignore Escape/Alt+F4 while locked
        if self._locked:
            event.accept()
            return
        super().keyPressEvent(event)
