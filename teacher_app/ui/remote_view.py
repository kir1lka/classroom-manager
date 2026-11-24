"""Full-resolution live screen viewer and remote mouse/keyboard control dialog."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from shared.protocol import ScreenMode
from teacher_app.network.server import StudentSession, TeacherServer

# Mapping of Qt special keys to Windows Virtual-Key (VK) codes
QT_KEY_TO_VK: dict[int, int] = {
    int(Qt.Key.Key_Backspace): 0x08,
    int(Qt.Key.Key_Tab): 0x09,
    int(Qt.Key.Key_Return): 0x0D,
    int(Qt.Key.Key_Enter): 0x0D,
    int(Qt.Key.Key_Shift): 0x10,
    int(Qt.Key.Key_Control): 0x11,
    int(Qt.Key.Key_Alt): 0x12,
    int(Qt.Key.Key_Pause): 0x13,
    int(Qt.Key.Key_CapsLock): 0x14,
    int(Qt.Key.Key_Escape): 0x1B,
    int(Qt.Key.Key_Space): 0x20,
    int(Qt.Key.Key_PageUp): 0x21,
    int(Qt.Key.Key_PageDown): 0x22,
    int(Qt.Key.Key_End): 0x23,
    int(Qt.Key.Key_Home): 0x24,
    int(Qt.Key.Key_Left): 0x25,
    int(Qt.Key.Key_Up): 0x26,
    int(Qt.Key.Key_Right): 0x27,
    int(Qt.Key.Key_Down): 0x28,
    int(Qt.Key.Key_Insert): 0x2D,
    int(Qt.Key.Key_Delete): 0x2E,
    int(Qt.Key.Key_Meta): 0x5B,
    int(Qt.Key.Key_F1): 0x70,
    int(Qt.Key.Key_F2): 0x71,
    int(Qt.Key.Key_F3): 0x72,
    int(Qt.Key.Key_F4): 0x73,
    int(Qt.Key.Key_F5): 0x74,
    int(Qt.Key.Key_F6): 0x75,
    int(Qt.Key.Key_F7): 0x76,
    int(Qt.Key.Key_F8): 0x77,
    int(Qt.Key.Key_F9): 0x78,
    int(Qt.Key.Key_F10): 0x79,
    int(Qt.Key.Key_F11): 0x7A,
    int(Qt.Key.Key_F12): 0x7B,
}


class RemoteScreenCanvas(QLabel):
    """Displays student's screen and forwards mouse/keyboard events when control is active."""

    def __init__(self, on_input: Callable[[dict[str, Any]], None], parent=None) -> None:
        super().__init__(parent)
        self._on_input = on_input
        self._control_enabled = False
        self._source_pixmap: QPixmap | None = None
        self._image_rect = QRect()
        self._last_move_ts = 0.0

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(720, 420)
        self.setStyleSheet("background-color: #020617; border: 1px solid #334155; border-radius: 6px;")
        self.setText("Ожидание видеопотока от ученика...")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_control_enabled(self, enabled: bool) -> None:
        self._control_enabled = enabled
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)
        if enabled:
            self.setFocus()

    def update_frame(self, jpeg_bytes: bytes) -> None:
        pm = QPixmap()
        if pm.loadFromData(jpeg_bytes, "JPG"):
            self._source_pixmap = pm
            self._render_scaled()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_scaled()

    def _render_scaled(self) -> None:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return
        scaled = self._source_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        self._image_rect = QRect(x, y, scaled.width(), scaled.height())
        self.setPixmap(scaled)

    def _map_pos(self, pos) -> tuple[float, float] | None:
        if self._image_rect.isEmpty():
            return None
        px = pos.x()
        py = pos.y()
        if not self._image_rect.contains(int(px), int(py)):
            return None
        nx = (px - self._image_rect.x()) / max(1, self._image_rect.width())
        ny = (py - self._image_rect.y()) / max(1, self._image_rect.height())
        return max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny))

    @staticmethod
    def _qt_button_name(btn: Qt.MouseButton) -> str | None:
        if btn == Qt.MouseButton.LeftButton:
            return "left"
        if btn == Qt.MouseButton.RightButton:
            return "right"
        if btn == Qt.MouseButton.MiddleButton:
            return "middle"
        return None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._control_enabled:
            return
        now = time.monotonic()
        if now - self._last_move_ts < 0.035:  # ~28 Hz cap
            return
        coords = self._map_pos(event.position())
        if coords is not None:
            self._last_move_ts = now
            self._on_input({"event": "mouse_move", "x": coords[0], "y": coords[1]})

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        if not self._control_enabled:
            return
        coords = self._map_pos(event.position())
        btn = self._qt_button_name(event.button())
        if coords is not None and btn:
            self._on_input({"event": "mouse_down", "button": btn, "x": coords[0], "y": coords[1]})

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._control_enabled:
            return
        coords = self._map_pos(event.position())
        btn = self._qt_button_name(event.button())
        if coords is not None and btn:
            self._on_input({"event": "mouse_up", "button": btn, "x": coords[0], "y": coords[1]})

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self._control_enabled:
            return
        delta = event.angleDelta().y()
        if delta != 0:
            self._on_input({"event": "mouse_wheel", "delta": int(delta)})

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._control_enabled:
            super().keyPressEvent(event)
            return

        qt_key = int(event.key())
        mods = event.modifiers()
        has_ctrl_or_alt = bool(
            mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        )

        # Special keys or Ctrl/Alt shortcuts go via VK codes
        if qt_key in QT_KEY_TO_VK:
            self._on_input({"event": "key_down", "vk": QT_KEY_TO_VK[qt_key]})
            event.accept()
            return

        if has_ctrl_or_alt and 0x20 <= qt_key <= 0x7E:
            self._on_input({"event": "key_down", "vk": qt_key})
            event.accept()
            return

        # Printable Unicode characters (supports both Russian and English layouts!)
        text = event.text()
        if text and text.isprintable():
            self._on_input({"event": "key_text", "text": text})
            event.accept()
            return

        vk = int(event.nativeVirtualKey())
        if 0 < vk <= 0xFE:
            self._on_input({"event": "key_down", "vk": vk})
            event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not self._control_enabled:
            super().keyReleaseEvent(event)
            return
        qt_key = int(event.key())
        if qt_key in QT_KEY_TO_VK:
            self._on_input({"event": "key_up", "vk": QT_KEY_TO_VK[qt_key]})
            event.accept()
            return
        mods = event.modifiers()
        has_ctrl_or_alt = bool(
            mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        )
        if has_ctrl_or_alt and 0x20 <= qt_key <= 0x7E:
            self._on_input({"event": "key_up", "vk": qt_key})
            event.accept()


class RemoteControlDialog(QDialog):
    """Live view and interactive remote control window for one student PC."""

    def __init__(self, server: TeacherServer, session: StudentSession, parent=None) -> None:
        super().__init__(parent)
        self.server = server
        self.client_id = session.client_id
        self.setWindowTitle(f"Просмотр и управление — {session.label} ({session.ip})")
        self.resize(1100, 680)

        layout = QVBoxLayout(self)

        # Toolbar
        bar = QHBoxLayout()
        self.control_btn = QPushButton("Управление мышью и клавиатурой: ВЫКЛ")
        self.control_btn.setCheckable(True)
        self.control_btn.toggled.connect(self._toggle_control)

        lock_btn = QPushButton("Заблокировать экран")
        lock_btn.setProperty("accent", "warning")
        lock_btn.clicked.connect(lambda: asyncio.create_task(self.server.lock_screen(self.client_id)))

        unlock_btn = QPushButton("Разблокировать")
        unlock_btn.setProperty("accent", "success")
        unlock_btn.clicked.connect(lambda: asyncio.create_task(self.server.unlock_screen(self.client_id)))

        lock_os_btn = QPushButton("Блок Windows")
        lock_os_btn.clicked.connect(lambda: self._confirm_power("lock_os", "Заблокировать сеанс Windows?"))

        reboot_btn = QPushButton("Перезагрузка")
        reboot_btn.clicked.connect(lambda: self._confirm_power("reboot", "Перезагрузить этот ПК?"))

        shutdown_btn = QPushButton("Выключить ПК")
        shutdown_btn.setProperty("accent", "danger")
        shutdown_btn.clicked.connect(lambda: self._confirm_power("shutdown", "Выключить этот ПК?"))

        bar.addWidget(self.control_btn)
        bar.addStretch()
        bar.addWidget(lock_btn)
        bar.addWidget(unlock_btn)
        bar.addWidget(lock_os_btn)
        bar.addWidget(reboot_btn)
        bar.addWidget(shutdown_btn)
        layout.addLayout(bar)

        self.canvas = RemoteScreenCanvas(self._send_input)
        layout.addWidget(self.canvas, stretch=1)

        self.info_label = QLabel(
            f"ПК: {session.hostname} | Пользователь: {session.username} | IP: {session.ip} | "
            "Совет: включите кнопку «Управление», чтобы кликать и печатать на этом компьютере."
        )
        self.info_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(self.info_label)

        # Request high-resolution live stream
        asyncio.create_task(
            self.server.set_screen_mode(
                self.client_id,
                ScreenMode.LIVE,
                fps=self.server.config.live_fps,
                width=self.server.config.live_width,
                quality=70,
            )
        )

    def _toggle_control(self, checked: bool) -> None:
        self.canvas.set_control_enabled(checked)
        if checked:
            self.control_btn.setText("Управление мышью и клавиатурой: ВКЛ")
            self.control_btn.setProperty("accent", "primary")
        else:
            self.control_btn.setText("Управление мышью и клавиатурой: ВЫКЛ")
            self.control_btn.setProperty("accent", "")
        self.control_btn.style().unpolish(self.control_btn)
        self.control_btn.style().polish(self.control_btn)

    def _send_input(self, payload: dict[str, Any]) -> None:
        asyncio.create_task(self.server.send_remote_input(self.client_id, payload))

    def _confirm_power(self, action: str, question: str) -> None:
        reply = QMessageBox.question(
            self,
            "Подтверждение действия",
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            asyncio.create_task(self.server.power_action(self.client_id, action))

    def on_frame(self, jpeg_bytes: bytes) -> None:
        self.canvas.update_frame(jpeg_bytes)

    def closeEvent(self, event) -> None:
        # Downgrade back to lightweight thumbnail stream
        mode = ScreenMode.THUMB if self.server.config.thumb_fps > 0 else ScreenMode.OFF
        asyncio.create_task(
            self.server.set_screen_mode(
                self.client_id,
                mode,
                fps=max(0.5, self.server.config.thumb_fps),
                width=self.server.config.thumb_width,
                quality=50,
            )
        )
        super().closeEvent(event)
