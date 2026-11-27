"""Full-resolution live screen viewer, monitor switcher, quality selector, and remote control (Liquid Glass HUD)."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QAction, QKeyEvent, QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from shared.protocol import ScreenMode
from teacher_app.network.server import StudentSession, TeacherServer
from teacher_app.ui.theme import (
    GlassFrame,
    LiquidDialog,
    get_tokens,
    make_app_icon,
    make_icon,
)

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

QUALITY_PRESETS: list[tuple[str, int, int, float, bool]] = [
    ("Плавный 60 FPS (1080p, 78%)", 1920, 78, 60.0, True),
    ("Игровой 60 FPS (720p, 75%)", 1280, 75, 60.0, True),
    ("HD Чёткий 30 FPS (1080p, 88%)", 1920, 88, 30.0, False),
    ("Ультра 1:1 (Оригинал, 95%)", 0, 95, 15.0, False),
]


class RemoteScreenCanvas(QLabel):
    """Displays student's screen and forwards mouse/keyboard events when control is active."""

    def __init__(self, on_input: Callable[[dict[str, Any]], None], parent=None) -> None:
        super().__init__(parent)
        self._on_input = on_input
        self._control_enabled = False
        self._monitor_index = 1
        self._fast_render = True
        self._source_pixmap: QPixmap | None = None
        self._image_rect = QRect()
        self._last_move_ts = 0.0

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(780, 450)
        self.setStyleSheet(
            "background-color: #050811; "
            "border: 1px solid rgba(255, 255, 255, 0.12); "
            "border-radius: 14px; "
            "color: #8B9BB4; "
            "font-size: 13px;"
        )
        self.setText("Ожидание HD-видеопотока от компьютера ученика...")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_monitor_index(self, monitor_index: int) -> None:
        self._monitor_index = int(monitor_index)

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

    def set_fast_render(self, fast: bool) -> None:
        self._fast_render = bool(fast)

    def _render_scaled(self) -> None:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return
        mode = (
            Qt.TransformationMode.FastTransformation
            if self._fast_render
            else Qt.TransformationMode.SmoothTransformation
        )
        scaled = self._source_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            mode,
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
        if now - self._last_move_ts < 0.014:
            return
        coords = self._map_pos(event.position())
        if coords is not None:
            self._last_move_ts = now
            self._on_input(
                {"event": "mouse_move", "x": coords[0], "y": coords[1], "monitor": self._monitor_index}
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        if not self._control_enabled:
            return
        coords = self._map_pos(event.position())
        btn = self._qt_button_name(event.button())
        if coords is not None and btn:
            self._on_input(
                {
                    "event": "mouse_down",
                    "button": btn,
                    "x": coords[0],
                    "y": coords[1],
                    "monitor": self._monitor_index,
                }
            )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._control_enabled:
            return
        coords = self._map_pos(event.position())
        btn = self._qt_button_name(event.button())
        if coords is not None and btn:
            self._on_input(
                {
                    "event": "mouse_up",
                    "button": btn,
                    "x": coords[0],
                    "y": coords[1],
                    "monitor": self._monitor_index,
                }
            )

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

        if qt_key in QT_KEY_TO_VK:
            self._on_input({"event": "key_down", "vk": QT_KEY_TO_VK[qt_key]})
            event.accept()
            return

        if has_ctrl_or_alt and 0x20 <= qt_key <= 0x7E:
            self._on_input({"event": "key_down", "vk": qt_key})
            event.accept()
            return

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


class RemoteControlDialog(LiquidDialog):
    """Live HD viewer, multi-monitor switcher, and interactive remote control window."""

    def __init__(self, server: TeacherServer, session: StudentSession, parent=None) -> None:
        super().__init__(parent)
        self.server = server
        self._session = session
        self.client_id = session.client_id
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowIcon(make_app_icon("teacher"))
        self.setWindowTitle(f"Управление ПК — {session.label} ({session.ip})")
        self.resize(1280, 760)

        tokens = get_tokens()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        # Floating Liquid Glass HUD Top Bar
        hud_frame = GlassFrame(variant="bar", radius=16)
        bar = QHBoxLayout(hud_frame)
        bar.setContentsMargins(14, 9, 14, 9)
        bar.setSpacing(8)

        # Workstation badge (label + IP pill)
        ws_title = QLabel(session.label)
        ws_title.setStyleSheet("font-weight: 700; font-size: 13px;")
        ws_ip = QLabel(session.ip)
        ws_ip.setObjectName("AccentBadge")
        bar.addWidget(ws_title)
        bar.addWidget(ws_ip)
        bar.addSpacing(4)

        # Interactive remote control toggle
        self.control_btn = QPushButton("Управление: ВЫКЛ")
        self.control_btn.setCheckable(True)
        self.control_btn.setIcon(make_icon("remote", size=15))
        self.control_btn.setIconSize(QSize(15, 15))
        self.control_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.control_btn.toggled.connect(self._toggle_control)
        bar.addWidget(self.control_btn)

        # Compact Monitor selector
        self.monitor_combo = QComboBox()
        self.monitor_combo.setMinimumWidth(165)
        self.monitor_combo.setToolTip("Выбор монитора ученика")
        monitors = session.monitors or [
            {"index": 1, "name": f"Монитор 1 ({session.screen_width}×{session.screen_height})"}
        ]
        self._monitor_count = len(monitors)
        for mon in monitors:
            idx = int(mon.get("index", 1))
            name = str(mon.get("name") or f"Монитор {idx}")
            self.monitor_combo.addItem(name, idx)
        if len(monitors) > 1:
            self.monitor_combo.addItem("Все мониторы сразу", 0)
        cur_idx = self.monitor_combo.findData(session.active_monitor)
        if cur_idx >= 0:
            self.monitor_combo.setCurrentIndex(cur_idx)
        self.monitor_combo.currentIndexChanged.connect(self._apply_stream_settings)
        bar.addWidget(self.monitor_combo)

        # Compact Quality selector (up to 60 FPS)
        self.quality_combo = QComboBox()
        self.quality_combo.setMinimumWidth(210)
        self.quality_combo.setToolTip("Качество и частота видеопотока (до 60 FPS)")
        for label, w, q, fps, fast in QUALITY_PRESETS:
            self.quality_combo.addItem(label, (w, q, fps, fast))
        self.quality_combo.currentIndexChanged.connect(self._apply_stream_settings)
        bar.addWidget(self.quality_combo)

        bar.addStretch()

        # Right side uncluttered controls
        self.fullscreen_btn = QPushButton("Во весь экран")
        self.fullscreen_btn.setCheckable(True)
        self.fullscreen_btn.setIcon(make_icon("maximize", size=15))
        self.fullscreen_btn.setIconSize(QSize(15, 15))
        self.fullscreen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fullscreen_btn.toggled.connect(self._toggle_fullscreen)

        lock_btn = QPushButton("Блок экрана")
        lock_btn.setProperty("accent", "warning")
        lock_btn.setIcon(make_icon("lock", tokens.danger, 15))
        lock_btn.setIconSize(QSize(15, 15))
        lock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lock_btn.clicked.connect(
            lambda: asyncio.create_task(self.server.lock_screen(self.client_id, "срок бана: 1000 лет"))
        )

        unlock_btn = QPushButton("Разблок")
        unlock_btn.setIcon(make_icon("unlock", size=15))
        unlock_btn.setIconSize(QSize(15, 15))
        unlock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        unlock_btn.clicked.connect(
            lambda: asyncio.create_task(self.server.unlock_screen(self.client_id))
        )

        power_btn = QPushButton("Питание ▾")
        power_btn.setProperty("accent", "danger")
        power_btn.setIcon(make_icon("power", "#FFFFFF", 15))
        power_btn.setIconSize(QSize(15, 15))
        power_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        power_btn.setMenu(self._build_power_menu())

        bar.addWidget(self.fullscreen_btn)
        bar.addWidget(lock_btn)
        bar.addWidget(unlock_btn)
        bar.addWidget(power_btn)
        layout.addWidget(hud_frame)

        # Deep rounded viewport canvas
        self.canvas = RemoteScreenCanvas(self._send_input)
        self.canvas.set_monitor_index(int(self.monitor_combo.currentData() or 1))
        layout.addWidget(self.canvas, stretch=1)

        # Subtle telemetry footer
        self.info_label = QLabel()
        self.info_label.setObjectName("MutedLabel")
        self._update_footer_label(False)
        layout.addWidget(self.info_label)

        self._apply_stream_settings()

    def _build_power_menu(self) -> QMenu:
        menu = QMenu(self)
        act_lock = QAction(make_icon("lock", size=15), "Заблокировать Windows", self)
        act_lock.triggered.connect(
            lambda: self._confirm_power("lock_os", "Заблокировать сеанс Windows на этом ПК?")
        )

        act_reboot = QAction(make_icon("refresh", size=15), "Перезагрузить ПК", self)
        act_reboot.triggered.connect(
            lambda: self._confirm_power("reboot", "Перезагрузить этот компьютер?")
        )

        act_shutdown = QAction(make_icon("power", get_tokens().danger, 15), "Выключить ПК", self)
        act_shutdown.triggered.connect(
            lambda: self._confirm_power("shutdown", "Выключить этот компьютер?")
        )

        menu.addAction(act_lock)
        menu.addAction(act_reboot)
        menu.addSeparator()
        menu.addAction(act_shutdown)
        return menu

    def _update_footer_label(self, control_active: bool) -> None:
        mode_str = (
            "Ввод мыши и клавиатуры АКТИВЕН"
            if control_active
            else "Режим наблюдения (включите «Управление», чтобы кликать и печатать)"
        )
        self.info_label.setText(
            f"ПК: {self._session.hostname}  •  Пользователь: {self._session.username}  •  "
            f"IP: {self._session.ip}  •  Мониторов: {self._monitor_count}  •  {mode_str}"
        )

    def _apply_stream_settings(self) -> None:
        mon_idx = int(
            self.monitor_combo.currentData() if self.monitor_combo.currentData() is not None else 1
        )
        preset = self.quality_combo.currentData()
        if preset:
            width, quality, fps, fast = preset
        else:
            width = self.server.config.live_width
            quality = self.server.config.live_quality
            fps = self.server.config.live_fps
            fast = fps >= 24.0

        self.canvas.set_monitor_index(mon_idx)
        self.canvas.set_fast_render(fast)
        asyncio.create_task(
            self.server.set_screen_mode(
                self.client_id,
                ScreenMode.LIVE,
                fps=fps,
                width=width,
                quality=quality,
                monitor=mon_idx,
                fast=fast,
            )
        )

    def _toggle_fullscreen(self, checked: bool) -> None:
        if checked:
            self.fullscreen_btn.setText("Оконный режим")
            self.showFullScreen()
        else:
            self.fullscreen_btn.setText("Во весь экран")
            self.showMaximized()

    def _toggle_control(self, checked: bool) -> None:
        self.canvas.set_control_enabled(checked)
        if checked:
            self.control_btn.setText("Управление: ВКЛ")
            self.control_btn.setProperty("accent", "success")
            self.control_btn.setIcon(make_icon("remote", "#FFFFFF", 15))
        else:
            self.control_btn.setText("Управление: ВЫКЛ")
            self.control_btn.setProperty("accent", "")
            self.control_btn.setIcon(make_icon("remote", size=15))
        self.control_btn.style().unpolish(self.control_btn)
        self.control_btn.style().polish(self.control_btn)
        self._update_footer_label(checked)

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
        mode = ScreenMode.THUMB if self.server.config.thumb_fps > 0 else ScreenMode.OFF
        mon_idx = int(
            self.monitor_combo.currentData() if self.monitor_combo.currentData() is not None else 1
        )
        asyncio.create_task(
            self.server.set_screen_mode(
                self.client_id,
                mode,
                fps=max(0.5, self.server.config.thumb_fps),
                width=self.server.config.thumb_width,
                quality=72,
                monitor=mon_idx,
            )
        )
        super().closeEvent(event)
