"""Fullscreen Teacher Screen Demonstration viewer overlay on Student PCs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


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
        self.setStyleSheet("background-color: #020617;")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Compact top banner (Spotify charcoal style)
        banner = QWidget()
        banner.setFixedHeight(36)
        banner.setStyleSheet("background-color: #121212; border-bottom: 1px solid #282828;")
        b_layout = QHBoxLayout(banner)
        b_layout.setContentsMargins(14, 0, 14, 0)

        self.banner_lbl = QLabel("Демонстрация экрана учителя")
        self.banner_lbl.setStyleSheet("color: #FFFFFF; font-weight: 700; font-size: 13px; background: transparent;")
        self.hint_lbl = QLabel("Прямая трансляция HD")
        self.hint_lbl.setStyleSheet("color: #A3A3A3; font-size: 11px; background: transparent;")

        b_layout.addWidget(self.banner_lbl)
        b_layout.addStretch()
        b_layout.addWidget(self.hint_lbl)
        root.addWidget(banner)

        # Live video label
        self.screen_lbl = QLabel("Подключение к трансляции экрана учителя...")
        self.screen_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.screen_lbl.setStyleSheet("color: #94a3b8; font-size: 16px; background-color: #020617;")
        root.addWidget(self.screen_lbl, stretch=1)

    def set_hotkey_hint(self, _hotkey: str) -> None:
        # Intentionally hidden so students do not see the admin hotkey
        pass

    def start_demo(self, title: str = "Демонстрация экрана учителя", fullscreen: bool = True) -> None:
        self._active = True
        self.banner_lbl.setText(title)
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
