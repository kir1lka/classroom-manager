"""Fullscreen Teacher Screen Demonstration viewer overlay on Student PCs (Liquid Glass HUD)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from teacher_app.ui.theme import make_app_icon, make_icon


class DemoViewerOverlay(QWidget):
    """Displays the Teacher's live screen broadcast across the student's display."""

    def __init__(self, hotkey_hint: str = "Ctrl+Alt+Shift+M") -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._active = False
        self._last_pixmap: QPixmap | None = None
        self.setWindowTitle("Демонстрация экрана учителя")
        self.setWindowIcon(make_app_icon("student"))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("DemoViewerRoot")
        self.setStyleSheet("QWidget#DemoViewerRoot { background-color: #050811; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Liquid Glass Top HUD Bar (44px)
        banner = QWidget(self)
        banner.setObjectName("DemoHudBar")
        banner.setFixedHeight(44)
        banner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        banner.setStyleSheet(
            "QWidget#DemoHudBar {"
            "  background-color: rgba(14, 21, 36, 0.88);"
            "  border-bottom: 1px solid rgba(255, 255, 255, 0.12);"
            "}"
        )
        b_layout = QHBoxLayout(banner)
        b_layout.setContentsMargins(16, 0, 18, 0)
        b_layout.setSpacing(12)

        self.live_badge = QLabel("● LIVE HD")
        self.live_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.live_badge.setStyleSheet(
            "color: #FF453A;"
            "background-color: rgba(255, 69, 58, 0.16);"
            "border: 1px solid rgba(255, 105, 97, 0.42);"
            "border-radius: 10px;"
            "padding: 3px 10px;"
            'font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;'
            "font-size: 11px;"
            "font-weight: 800;"
            "letter-spacing: 0.7px;"
        )

        cast_icon = QLabel()
        cast_icon.setPixmap(make_icon("cast", "#38BDF8", 16).pixmap(16, 16))
        cast_icon.setStyleSheet("background: transparent;")

        self.banner_lbl = QLabel("Демонстрация экрана учителя")
        self.banner_lbl.setStyleSheet(
            "color: #F8FAFC;"
            'font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;'
            "font-weight: 700;"
            "font-size: 13px;"
            "background: transparent;"
        )

        self.hint_lbl = QLabel("Трансляция в реальном времени")
        self.hint_lbl.setStyleSheet(
            "color: #8B9BB4;"
            "font-size: 12px;"
            "font-weight: 500;"
            "background: transparent;"
        )

        b_layout.addWidget(self.live_badge)
        b_layout.addWidget(cast_icon)
        b_layout.addWidget(self.banner_lbl)
        b_layout.addStretch()
        b_layout.addWidget(self.hint_lbl)
        root.addWidget(banner)

        # Live video canvas
        self.screen_lbl = QLabel("Подключение к трансляции экрана учителя...")
        self.screen_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.screen_lbl.setStyleSheet(
            "color: #8B9BB4;"
            'font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;'
            "font-size: 15px;"
            "font-weight: 500;"
            "background-color: #050811;"
        )
        root.addWidget(self.screen_lbl, stretch=1)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#050811"))
        painter.end()

    def set_hotkey_hint(self, _hotkey: str) -> None:
        # Intentionally hidden so students do not see the admin hotkey
        pass

    def start_demo(
        self, title: str = "Демонстрация экрана учителя", fullscreen: bool = True
    ) -> None:
        self._active = True
        self.banner_lbl.setText(title)
        if self._last_pixmap is None:
            self.screen_lbl.setText("Подключение к трансляции экрана учителя...")
        primary = QGuiApplication.primaryScreen()
        if fullscreen and primary is not None:
            self.setGeometry(primary.geometry())
            self.showFullScreen()
        else:
            self.resize(1100, 680)
            self.show()
        self.raise_()
        self.activateWindow()

    def stop_demo(self) -> None:
        self._active = False
        self._last_pixmap = None
        self.screen_lbl.clear()
        self.hide()

    def update_frame(self, jpeg_bytes: bytes) -> None:
        if not self._active:
            return
        pm = QPixmap()
        if pm.loadFromData(jpeg_bytes, "JPG"):
            self._last_pixmap = pm
            self._render_scaled()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_scaled()

    def _render_scaled(self) -> None:
        if self._last_pixmap is None or self._last_pixmap.isNull():
            return
        scaled = self._last_pixmap.scaled(
            self.screen_lbl.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.screen_lbl.setPixmap(scaled)

    def closeEvent(self, event) -> None:
        if self._active:
            event.ignore()
            return
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if self._active:
            event.accept()
            return
        super().keyPressEvent(event)
