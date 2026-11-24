"""Fullscreen pure-black ban overlay with crisp vector red cross."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class _RedCrossWidget(QWidget):
    """Draws a razor-sharp vector red X cross centered on pure black."""

    def __init__(self, size: int = 190, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#EF4444"), 22, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        pad = 26
        w = self.width()
        h = self.height()
        painter.drawLine(pad, pad, w - pad, h - pad)
        painter.drawLine(w - pad, pad, pad, h - pad)
        painter.end()


class ScreenLockOverlay(QWidget):
    """Covers the entire virtual desktop with pure black, red cross, and ban notice."""

    def __init__(self, hotkey_hint: str = "Ctrl+Alt+Shift+M") -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._locked = False
        self.setStyleSheet("background-color: #000000;")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        self.cross = _RedCrossWidget(200, self)
        layout.addWidget(self.cross, alignment=Qt.AlignmentFlag.AlignCenter)

        self.title_lbl = QLabel("ЗАБАНЕН")
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_lbl.setStyleSheet(
            "font-size: 52px; font-weight: 900; letter-spacing: 4px; "
            "color: #FFFFFF; background: transparent;"
        )

        self.msg_lbl = QLabel("(срок бана: 1000 лет)")
        self.msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_lbl.setWordWrap(True)
        self.msg_lbl.setStyleSheet(
            "font-size: 22px; font-weight: 600; color: #EF4444; background: transparent;"
        )

        layout.addWidget(self.title_lbl)
        layout.addWidget(self.msg_lbl)

    def set_hotkey_hint(self, _hotkey: str) -> None:
        # Intentionally hidden on the lock screen so students cannot see the admin hotkey
        pass

    def lock(self, message: str = "(срок бана: 1000 лет)") -> None:
        self._locked = True
        clean = (message or "").strip()
        if not clean or "Внимание на учителя" in clean:
            clean = "(срок бана: 1000 лет)"
        self.msg_lbl.setText(clean)

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
        if self._locked:
            event.accept()
            return
        super().keyPressEvent(event)
