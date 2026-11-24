"""Fullscreen pure-black ban overlay with frosted crimson glass ring and razor-sharp red cross."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from teacher_app.ui.theme import make_app_icon


class _RedCrossWidget(QWidget):
    """Draws a radial crimson ambient glow, frosted glass ring, and rounded red X cross."""

    def __init__(self, size: int = 220, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        center = QPointF(w * 0.5, h * 0.5)
        outer_r = min(w, h) * 0.5

        # 1. Soft radial crimson ambient glow fading smoothly to transparent
        glow = QRadialGradient(center, outer_r)
        glow.setColorAt(0.0, QColor(255, 69, 58, 61))  # rgba(255, 69, 58, 0.24)
        glow.setColorAt(0.55, QColor(255, 69, 58, 22))
        glow.setColorAt(1.0, QColor(255, 69, 58, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(0.0, 0.0, w, h))

        # 2. Frosted dark-crimson glass ring
        inset = w * 0.165
        ring_rect = QRectF(inset, inset, w - 2.0 * inset, h - 2.0 * inset)
        painter.setBrush(QColor(255, 69, 58, 26))  # rgba(255, 69, 58, 0.10)
        painter.setPen(QPen(QColor(255, 105, 97, 115), 1.5))  # rgba(255, 105, 97, 0.45)
        painter.drawEllipse(ring_rect)

        # Subtle top glass specular highlight inside the ring
        ring_path = QPainterPath()
        ring_path.addEllipse(ring_rect)
        sheen = QLinearGradient(
            ring_rect.left(),
            ring_rect.top(),
            ring_rect.left(),
            ring_rect.top() + ring_rect.height() * 0.48,
        )
        sheen.setColorAt(0.0, QColor(255, 255, 255, 22))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(ring_path, sheen)

        # 3. Razor-sharp rounded red X cross with soft crimson bloom
        pad = w * 0.345
        p1 = QPointF(pad, pad)
        p2 = QPointF(w - pad, h - pad)
        p3 = QPointF(w - pad, pad)
        p4 = QPointF(pad, h - pad)

        bloom_pen = QPen(
            QColor(255, 69, 58, 65),
            w * 0.105,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
        painter.setPen(bloom_pen)
        painter.drawLine(p1, p2)
        painter.drawLine(p3, p4)

        cross_pen = QPen(
            QColor("#FF453A"),
            w * 0.068,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
        painter.setPen(cross_pen)
        painter.drawLine(p1, p2)
        painter.drawLine(p3, p4)

        painter.end()


class ScreenLockOverlay(QWidget):
    """Covers the entire virtual desktop with pure black, crimson glass cross, and ban notice."""

    def __init__(self, hotkey_hint: str = "Ctrl+Alt+Shift+M") -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._locked = False
        self.setWindowTitle("Экран заблокирован")
        self.setWindowIcon(make_app_icon("student"))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("ScreenLockRoot")
        self.setStyleSheet("QWidget#ScreenLockRoot { background-color: #000000; }")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(18)

        self.cross = _RedCrossWidget(220, self)
        layout.addWidget(self.cross, alignment=Qt.AlignmentFlag.AlignCenter)

        self.title_lbl = QLabel("ЗАБАНЕН")
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_lbl.setStyleSheet(
            'font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;'
            "font-size: 54px;"
            "font-weight: 900;"
            "letter-spacing: 5px;"
            "color: #F8FAFC;"
            "background: transparent;"
        )
        layout.addWidget(self.title_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

        self.msg_lbl = QLabel("срок бана: 1000 лет")
        self.msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_lbl.setWordWrap(False)
        self.msg_lbl.setMaximumWidth(900)
        self.msg_lbl.setStyleSheet(
            'font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;'
            "font-size: 19px;"
            "font-weight: 600;"
            "color: #FF6961;"
            "background-color: rgba(255, 69, 58, 0.12);"
            "border: 1px solid rgba(255, 105, 97, 0.34);"
            "border-radius: 16px;"
            "padding: 8px 24px;"
        )
        layout.addWidget(self.msg_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        painter.end()

    def set_hotkey_hint(self, _hotkey: str) -> None:
        # Intentionally hidden on the lock screen so students cannot see the admin hotkey
        pass

    def lock(self, message: str = "срок бана: 1000 лет") -> None:
        self._locked = True
        clean = (message or "").strip()
        if clean.startswith("(") and clean.endswith(")") and len(clean) > 2:
            clean = clean[1:-1].strip()
        if not clean or "Внимание на учителя" in clean:
            clean = "срок бана: 1000 лет"
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
