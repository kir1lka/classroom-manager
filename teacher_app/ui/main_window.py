"""iOS / macOS Liquid Glass Teacher console: floating sidebar, live screen grid, PowerShell studio, and audit log."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QMimeData, QObject, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QDrag, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from shared.config import TeacherConfig, save_config
from student_app.handlers.screen_capture import list_monitors
from teacher_app.network.discovery import get_local_ipv4_addresses
from teacher_app.network.mcp_server import ClassroomMCPServer, build_mcp_client_config, generate_mcp_token
from teacher_app.network.server import StudentSession, TeacherServer
from teacher_app.ui.dialogs import AddClassroomDialog, TeacherSettingsDialog
from teacher_app.ui.file_transfer_dialog import FileTransferDialog
from teacher_app.ui.remote_view import RemoteControlDialog
from teacher_app.ui.theme import (
    GlassFrame,
    LiquidBackdropWidget,
    apply_window_chrome,
    get_stylesheet,
    get_tokens,
    make_app_icon,
    make_brand_pixmap,
    make_icon,
)


CARD_DRAG_MIME = "application/x-classroom-card-id"
CARD_MIN_WIDTH = 220
CARD_MAX_WIDTH = 540
CARD_DEFAULT_WIDTH = 326

GRID_SORT_MODES: list[tuple[str, str]] = [
    ("natural_asc", "По порядку (1 → 10)"),
    ("natural_desc", "Обратный (10 → 1)"),
    ("custom", "Вручную (перетаскиванием)"),
    ("ip_asc", "По IP-адресу"),
    ("locked_first", "Заблокированные сверху"),
    ("connected_at", "По подключению"),
]


def _natural_sort_key(text: str) -> list[tuple[int, int | str]]:
    """Natural alphanumeric sort key so PC1, PC2, ..., PC9, PC10 order intuitively."""
    parts = re.split(r"(\d+)", (text or "").strip().lower())
    key: list[tuple[int, int | str]] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return key


def _ip_sort_key(ip: str) -> tuple[int, ...]:
    """Numeric IPv4 sort key so 192.168.0.4 sorts before 192.168.0.27."""
    parts = (ip or "").strip().split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return tuple(int(p) for p in parts)
    return (999, 999, 999, 999)


def sort_sessions(
    sessions: list[StudentSession],
    mode: str,
    custom_order: list[str] | None = None,
) -> list[StudentSession]:
    """Sort student sessions according to the selected grid sort mode."""
    if mode == "natural_desc":
        return sorted(sessions, key=lambda s: _natural_sort_key(s.label), reverse=True)
    if mode == "ip_asc":
        return sorted(sessions, key=lambda s: (_ip_sort_key(s.ip), _natural_sort_key(s.label)))
    if mode == "locked_first":
        return sorted(sessions, key=lambda s: (0 if s.locked else 1, _natural_sort_key(s.label)))
    if mode == "connected_at":
        return sorted(sessions, key=lambda s: (s.connected_at, _natural_sort_key(s.label)))
    if mode == "custom" and custom_order:
        rank = {cid: idx for idx, cid in enumerate(custom_order)}
        fallback = len(rank)
        return sorted(
            sessions,
            key=lambda s: (rank.get(s.client_id, fallback), _natural_sort_key(s.label)),
        )
    # Default: natural_asc (PC1, PC2, ..., PC10)
    return sorted(sessions, key=lambda s: _natural_sort_key(s.label))


def _spawn_task(coro: Any) -> None:
    """Schedule a coroutine on the running asyncio/qasync loop, or close cleanly if stopped."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        coro.close()


def _themed_icon(
    name: str,
    normal_color: str,
    disabled_color: str | None = None,
    size: int = 16,
) -> QIcon:
    """Create a crisp vector QIcon with explicit normal and disabled state contrast."""
    base = make_icon(name, normal_color, size=size)
    if not disabled_color:
        return base
    icon = QIcon()
    pm_norm = base.pixmap(QSize(size, size))
    pm_dis = make_icon(name, disabled_color, size=size).pixmap(QSize(size, size))
    icon.addPixmap(pm_norm, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pm_norm, QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(pm_norm, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(pm_norm, QIcon.Mode.Selected, QIcon.State.Off)
    icon.addPixmap(pm_dis, QIcon.Mode.Disabled, QIcon.State.Off)
    icon.addPixmap(pm_dis, QIcon.Mode.Disabled, QIcon.State.On)
    return icon


class ServerSignals(QObject):
    """Qt signal bridge for callbacks invoked by TeacherServer."""

    client_connected = Signal(object)
    client_disconnected = Signal(str)
    client_updated = Signal(object)
    screen_frame = Signal(str, int, int, int, bytes)
    log_line = Signal(str)
    mcp_activity = Signal(str)


class StudentCardWidget(GlassFrame):
    """Liquid Glass workstation card showing live 16:9 screen preview, telemetry, and quick actions."""

    clicked = Signal(str)
    double_clicked = Signal(str)
    context_action = Signal(str, str)
    card_reordered = Signal(str, str)

    def __init__(self, session: StudentSession, card_width: int = CARD_DEFAULT_WIDTH, parent=None) -> None:
        super().__init__(variant="card", radius=18.0, interactive=True, parent=parent)
        self.client_id = session.client_id
        self._locked = bool(session.locked)
        self._search_blob = ""
        self._last_session = session
        self._last_pixmap: QPixmap | None = None
        self._drag_start_pos: QPoint | None = None
        self._card_width = CARD_DEFAULT_WIDTH

        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 11, 13, 11)
        layout.setSpacing(8)

        # Header row: workstation label + multi-monitor pill + status badge
        top = QHBoxLayout()
        top.setSpacing(6)

        self.title_lbl = QLabel(session.label)
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        self.title_lbl.setFont(title_font)

        self.mon_lbl = QLabel("")
        self.mon_lbl.setObjectName("MonBadge")
        self.mon_lbl.setVisible(False)

        self.badge_lbl = QLabel("ONLINE")
        self.badge_lbl.setObjectName("OnlineBadge")

        top.addWidget(self.title_lbl, stretch=1)
        top.addWidget(self.mon_lbl)
        top.addWidget(self.badge_lbl)
        layout.addLayout(top)

        # Rounded 16:9 screen preview
        self.preview_lbl = QLabel("Ожидание кадра...")
        self.preview_lbl.setObjectName("PreviewBox")
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview_lbl)

        # Footer: left telemetry stack + right compact #IconPill quick actions
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)

        meta_col = QVBoxLayout()
        meta_col.setContentsMargins(0, 0, 0, 0)
        meta_col.setSpacing(2)

        self.meta_lbl = QLabel()
        self.meta_lbl.setObjectName("MutedLabel")
        self.window_lbl = QLabel()
        win_font = QFont()
        win_font.setPointSize(8)
        self.window_lbl.setFont(win_font)

        meta_col.addWidget(self.meta_lbl)
        meta_col.addWidget(self.window_lbl)
        footer.addLayout(meta_col, stretch=1)

        self.quick_remote_btn = QPushButton()
        self.quick_remote_btn.setObjectName("IconPill")
        self.quick_remote_btn.setFixedSize(30, 30)
        self.quick_remote_btn.setIconSize(QSize(16, 16))
        self.quick_remote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_remote_btn.setToolTip("Открыть HD-управление")
        self.quick_remote_btn.clicked.connect(self._on_quick_remote)

        self.quick_lock_btn = QPushButton()
        self.quick_lock_btn.setObjectName("IconPill")
        self.quick_lock_btn.setFixedSize(30, 30)
        self.quick_lock_btn.setIconSize(QSize(16, 16))
        self.quick_lock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_lock_btn.setToolTip("Заблокировать / Разблокировать экран")
        self.quick_lock_btn.clicked.connect(self._on_quick_lock_toggle)

        footer.addWidget(self.quick_remote_btn)
        footer.addWidget(self.quick_lock_btn)
        layout.addLayout(footer)

        self.set_card_width(card_width)
        self.update_session(session)

    def set_card_width(self, width: int) -> None:
        w = max(CARD_MIN_WIDTH, min(CARD_MAX_WIDTH, int(width)))
        self._card_width = w
        preview_w = max(180, w - 26)
        preview_h = max(100, int(round(preview_w * 9.0 / 16.0)))
        card_h = preview_h + 104
        self.setFixedSize(w, card_h)
        self.preview_lbl.setFixedSize(preview_w, preview_h)
        if self._last_pixmap is not None and not self._last_pixmap.isNull():
            self._render_pixmap(self._last_pixmap)
        if self._last_session is not None:
            self._update_elided_texts(self._last_session)

    def _update_elided_texts(self, session: StudentSession) -> None:
        scale = self._card_width / float(CARD_DEFAULT_WIDTH)
        title_lim = max(12, int(round(20 * scale)))
        meta_lim = max(18, int(round(33 * scale)))
        win_lim = max(18, int(round(34 * scale)))

        label_text = session.label
        self.title_lbl.setText((label_text[:title_lim] + "…") if len(label_text) > title_lim + 1 else label_text)
        self.title_lbl.setToolTip(f"{session.label} ({session.hostname}) — перетащите для смены порядка")

        ping_str = f", {session.last_ping_ms:.0f} мс" if session.last_ping_ms is not None else ""
        meta_raw = f"{session.username} @ {session.ip}{ping_str}"
        self.meta_lbl.setText((meta_raw[:meta_lim] + "…") if len(meta_raw) > meta_lim + 1 else meta_raw)

        win = session.active_window.strip()
        self.window_lbl.setText((win[:win_lim] + "…") if len(win) > win_lim + 1 else (win or "Рабочий стол"))
        self.window_lbl.setToolTip(win or "Рабочий стол")

    def _on_quick_remote(self) -> None:
        self.clicked.emit(self.client_id)
        self.double_clicked.emit(self.client_id)

    def _on_quick_lock_toggle(self) -> None:
        self.clicked.emit(self.client_id)
        self.context_action.emit(self.client_id, "unlock" if self._locked else "lock")

    def matches_query(self, query: str) -> bool:
        if not query:
            return True
        return query in self._search_blob

    def refresh_theme_icons(self) -> None:
        t = get_tokens()
        self.quick_remote_btn.setIcon(make_icon("remote", t.accent, size=16))
        if self._locked:
            self.quick_lock_btn.setIcon(make_icon("unlock", t.danger, size=16))
            self.quick_lock_btn.setToolTip("Разблокировать экран")
        else:
            self.quick_lock_btn.setIcon(make_icon("lock", t.text_secondary, size=16))
            self.quick_lock_btn.setToolTip("Заблокировать экран")

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def update_session(self, session: StudentSession) -> None:
        self._last_session = session
        self._locked = bool(session.locked)
        self._search_blob = (
            f"{session.label} {session.hostname} {session.username} {session.ip} {session.active_window}"
        ).lower()
        self._update_elided_texts(session)

        mon_count = len(session.monitors)
        if mon_count > 1:
            self.mon_lbl.setText(f"{mon_count} мон.")
            self.mon_lbl.setVisible(True)
        else:
            self.mon_lbl.setVisible(False)

        self.setProperty("locked", "true" if session.locked else "false")
        if session.locked:
            self.badge_lbl.setText("БЛОК")
            self.badge_lbl.setObjectName("BanBadge")
        else:
            self.badge_lbl.setText("ONLINE")
            self.badge_lbl.setObjectName("OnlineBadge")

        self.refresh_theme_icons()
        self.badge_lbl.style().unpolish(self.badge_lbl)
        self.badge_lbl.style().polish(self.badge_lbl)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _render_pixmap(self, pm: QPixmap) -> None:
        target_size = self.preview_lbl.size()
        inner_w = max(1, target_size.width() - 2)
        inner_h = max(1, target_size.height() - 2)
        scaled = pm.scaled(
            QSize(inner_w, inner_h),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        rounded = QPixmap(scaled.size())
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0.0, 0.0, float(scaled.width()), float(scaled.height())), 10.0, 10.0)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, scaled)
        painter.end()
        self.preview_lbl.setPixmap(rounded)

    def update_thumbnail(self, jpeg_bytes: bytes) -> None:
        pm = QPixmap()
        if not pm.loadFromData(jpeg_bytes, "JPG"):
            return
        self._last_pixmap = pm
        self._render_pixmap(pm)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            self.clicked.emit(self.client_id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._drag_start_pos is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
            and (event.position().toPoint() - self._drag_start_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._drag_start_pos = None
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(CARD_DRAG_MIME, self.client_id.encode("utf-8"))
            drag.setMimeData(mime)
            snap = self.grab().scaledToWidth(
                min(220, self.width()),
                Qt.TransformationMode.SmoothTransformation,
            )
            drag.setPixmap(snap)
            drag.setHotSpot(QPoint(snap.width() // 2, 24))
            drag.exec(Qt.DropAction.MoveAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(CARD_DRAG_MIME):
            src_id = bytes(event.mimeData().data(CARD_DRAG_MIME)).decode("utf-8", errors="ignore")
            if src_id and src_id != self.client_id:
                event.acceptProposedAction()
                self.setProperty("selected", "true")
                self.style().unpolish(self)
                self.style().polish(self)
                self.update()
                return
        super().dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:
        # Restore real selection state via parent refresh
        win = self.window()
        if hasattr(win, "selected_client_id"):
            self.set_selected(getattr(win, "selected_client_id") == self.client_id)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(CARD_DRAG_MIME):
            src_id = bytes(event.mimeData().data(CARD_DRAG_MIME)).decode("utf-8", errors="ignore")
            if src_id and src_id != self.client_id:
                event.acceptProposedAction()
                self.card_reordered.emit(src_id, self.client_id)
                return
        super().dropEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.client_id)
            self.double_clicked.emit(self.client_id)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.clicked.emit(self.client_id)
        t = get_tokens()
        menu = QMenu(self)
        actions = [
            ("control", "remote", t.accent, "Открыть HD-управление ПК"),
            ("lock", "lock", t.danger, "Заблокировать экран"),
            ("unlock", "unlock", t.success, "Разблокировать экран"),
            ("send_file", "send_file", t.text, "Отправить файлы на этот ПК..."),
            ("message", "message", t.text, "Отправить сообщение"),
            ("powershell", "terminal", t.text, "Открыть PowerShell для этого ПК"),
            ("ping", "pulse", t.text, "Пинг и системная информация"),
            ("sep", "", "", ""),
            ("power_lock_os", "lock", t.warning, "Питание: Заблокировать Windows"),
            ("power_reboot", "refresh", t.warning, "Питание: Перезагрузить ПК"),
            ("power_shutdown", "power", t.danger, "Питание: Выключить ПК"),
            ("power_cancel", "stop", t.text_secondary, "Питание: Отменить выключение"),
        ]
        for key, icon_name, col, label in actions:
            if key == "sep":
                menu.addSeparator()
                continue
            act = QAction(make_icon(icon_name, col, size=15), label, self)
            act.triggered.connect(lambda _c=False, k=key: self.context_action.emit(self.client_id, k))
            menu.addAction(act)
        menu.exec(event.globalPos())


class TeacherMainWindow(QMainWindow):
    """iOS / macOS Liquid Glass Teacher Command Center."""

    def __init__(
        self,
        config: TeacherConfig,
        config_path: Path,
        data_dir: Path,
        signals: ServerSignals,
    ) -> None:
        super().__init__()
        self.config = config
        self.config.ensure_classrooms()
        self.config_path = config_path
        self.data_dir = data_dir
        self.signals = signals
        self._room_filter: str = self.config.classroom_id

        self.setWindowTitle(f"Classroom Manager – {config.classroom_id}")
        self.setWindowIcon(make_app_icon("teacher"))
        self.resize(1420, 860)
        self.setMinimumSize(1120, 680)
        self.statusBar().setSizeGripEnabled(False)

        self.server = TeacherServer(
            config=config,
            data_dir=data_dir,
            on_client_connected=self.signals.client_connected.emit,
            on_client_disconnected=self.signals.client_disconnected.emit,
            on_client_updated=self.signals.client_updated.emit,
            on_screen_frame=lambda cid, w, h, m, data: self.signals.screen_frame.emit(cid, w, h, int(m), data),
        )
        if not self.config.mcp_token:
            self.config.mcp_token = generate_mcp_token()
        self.mcp_server = ClassroomMCPServer(
            teacher_server=self.server,
            port=self.config.mcp_port,
            token=self.config.mcp_token,
            on_activity=self.signals.mcp_activity.emit,
        )

        self.cards: dict[str, StudentCardWidget] = {}
        self.selected_client_id: str | None = None
        self.remote_dialogs: dict[str, RemoteControlDialog] = {}

        self._build_ui()
        self._connect_signals()

    def showEvent(self, event) -> None:
        apply_window_chrome(self, self.config.theme)
        super().showEvent(event)

    def _build_ui(self) -> None:
        central = LiquidBackdropWidget()
        central.setStyleSheet("QPushButton { min-width: 0px; }")
        root = QHBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        # ================= FLOATING LIQUID GLASS SIDEBAR =================
        sidebar = GlassFrame(variant="sidebar", radius=22)
        sidebar.setFixedWidth(298)
        sidebar.setStyleSheet("QPushButton { padding: 7px 10px; } QPushButton#NavButton { padding: 9px 12px; }")
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(16, 18, 16, 16)
        sb.setSpacing(8)

        # Brand Row
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)

        self.brand_logo_lbl = QLabel()
        self.brand_logo_lbl.setFixedSize(36, 36)
        self.brand_logo_lbl.setPixmap(make_brand_pixmap(36))
        brand_row.addWidget(self.brand_logo_lbl)

        brand_stack = QVBoxLayout()
        brand_stack.setContentsMargins(0, 0, 0, 0)
        brand_stack.setSpacing(1)
        brand_lbl = QLabel("CLASSROOM")
        brand_lbl.setObjectName("BrandTitle")
        self.room_sub_lbl = QLabel()
        self.room_sub_lbl.setObjectName("BrandSub")
        brand_stack.addWidget(brand_lbl)
        brand_stack.addWidget(self.room_sub_lbl)
        brand_row.addLayout(brand_stack, stretch=1)

        self.online_pill = QLabel("0 онлайн")
        self.online_pill.setObjectName("OnlineBadge")
        brand_row.addWidget(self.online_pill, alignment=Qt.AlignmentFlag.AlignVCenter)
        sb.addLayout(brand_row)

        sb.addSpacing(8)

        # Multi-Classroom Switcher
        rooms_lbl = QLabel("КАБИНЕТЫ")
        rooms_lbl.setObjectName("SectionLabel")
        sb.addWidget(rooms_lbl)

        room_row = QHBoxLayout()
        room_row.setSpacing(6)
        self.classroom_combo = QComboBox()
        self.classroom_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.classroom_combo.currentIndexChanged.connect(self._on_classroom_changed)

        self.btn_add_room = QPushButton()
        self.btn_add_room.setObjectName("IconPill")
        self.btn_add_room.setFixedSize(34, 34)
        self.btn_add_room.setIconSize(QSize(16, 16))
        self.btn_add_room.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_room.setToolTip("Добавить новый кабинет")
        self.btn_add_room.clicked.connect(self._add_classroom_dialog)

        self.btn_del_room = QPushButton()
        self.btn_del_room.setObjectName("IconPill")
        self.btn_del_room.setFixedSize(34, 34)
        self.btn_del_room.setIconSize(QSize(15, 15))
        self.btn_del_room.clicked.connect(self._delete_current_classroom)

        room_row.addWidget(self.classroom_combo, stretch=1)
        room_row.addWidget(self.btn_add_room)
        room_row.addWidget(self.btn_del_room)
        sb.addLayout(room_row)

        sb.addSpacing(8)

        # Navigation Section
        nav_lbl = QLabel("РАЗДЕЛЫ")
        nav_lbl.setObjectName("SectionLabel")
        sb.addWidget(nav_lbl)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.nav_screens = self._make_nav_btn("Экраны класса", "grid", 0, checked=True)
        self.nav_commands = self._make_nav_btn("Терминал PowerShell", "terminal", 1)
        self.nav_logs = self._make_nav_btn("Журнал событий", "shield", 2)
        sb.addWidget(self.nav_screens)
        sb.addWidget(self.nav_commands)
        sb.addWidget(self.nav_logs)

        sb.addSpacing(12)

        # Quick Class Controls
        quick_lbl = QLabel("БЫСТРЫЕ ДЕЙСТВИЯ")
        quick_lbl.setObjectName("SectionLabel")
        sb.addWidget(quick_lbl)

        self._teacher_monitors = list_monitors()
        self.demo_mon_combo = QComboBox()
        for mon in self._teacher_monitors:
            self.demo_mon_combo.addItem(f"Экран показа: {mon['name']}", int(mon["index"]))
        self.demo_mon_combo.setVisible(len(self._teacher_monitors) > 1)
        sb.addWidget(self.demo_mon_combo)

        self.btn_demo = QPushButton("Демонстрация экрана")
        self.btn_demo.setCheckable(True)
        self.btn_demo.setIconSize(QSize(17, 17))
        self.btn_demo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_demo.setProperty("accent", "primary")
        self.btn_demo.toggled.connect(self._toggle_demo_broadcast)
        sb.addWidget(self.btn_demo)

        self.btn_files = QPushButton("Отправить файлы")
        self.btn_files.setIconSize(QSize(17, 17))
        self.btn_files.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_files.clicked.connect(lambda: self._open_file_transfer())
        sb.addWidget(self.btn_files)

        lock_all_row = QHBoxLayout()
        lock_all_row.setSpacing(8)
        self.btn_lock_all = QPushButton("Блок всех")
        self.btn_lock_all.setIconSize(QSize(16, 16))
        self.btn_lock_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lock_all.setProperty("accent", "warning")
        self.btn_lock_all.clicked.connect(self._lock_all_students)

        self.btn_unlock_all = QPushButton("Разблок")
        self.btn_unlock_all.setIconSize(QSize(16, 16))
        self.btn_unlock_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_unlock_all.clicked.connect(self._unlock_all_students)

        lock_all_row.addWidget(self.btn_lock_all, stretch=1)
        lock_all_row.addWidget(self.btn_unlock_all, stretch=1)
        sb.addLayout(lock_all_row)

        sb.addStretch(1)

        # Connection Pod at bottom
        info_card = GlassFrame(variant="inset", radius=14)
        ic = QVBoxLayout(info_card)
        ic.setContentsMargins(12, 10, 12, 10)
        ic.setSpacing(8)

        self.net_info_lbl = QLabel()
        self.net_info_lbl.setObjectName("MutedLabel")
        self.net_info_lbl.setWordWrap(True)
        ic.addWidget(self.net_info_lbl)

        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        self.secret_toggle_btn = QPushButton("Ключ")
        self.secret_toggle_btn.setCheckable(True)
        self.secret_toggle_btn.setIconSize(QSize(15, 15))
        self.secret_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.secret_toggle_btn.toggled.connect(self._on_secret_toggle)

        copy_key_btn = QPushButton("Копировать")
        copy_key_btn.setIconSize(QSize(15, 15))
        copy_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_key_btn.clicked.connect(self._copy_class_secret)
        self.copy_key_btn = copy_key_btn

        key_row.addWidget(self.secret_toggle_btn)
        key_row.addWidget(copy_key_btn, stretch=1)
        ic.addLayout(key_row)
        sb.addWidget(info_card)

        # Bottom utility row: Theme + Settings
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        self.theme_btn = QPushButton()
        self.theme_btn.setIconSize(QSize(16, 16))
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.clicked.connect(self._toggle_theme)

        settings_btn = QPushButton("Настройки")
        settings_btn.setIconSize(QSize(16, 16))
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(self._open_settings)
        self.settings_btn = settings_btn

        bottom_row.addWidget(self.theme_btn, stretch=1)
        bottom_row.addWidget(settings_btn, stretch=1)
        sb.addLayout(bottom_row)

        root.addWidget(sidebar)

        # ================= RIGHT WORKSPACE AREA =================
        content = QWidget()
        content.setObjectName("ContentArea")
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(14)

        # Uncluttered Contextual Top Glass Bar
        top_bar = GlassFrame(variant="bar", radius=20)
        tb_outer = QVBoxLayout(top_bar)
        tb_outer.setContentsMargins(18, 12, 18, 12)
        tb_outer.setSpacing(10)

        tb_header = QHBoxLayout()
        tb_header.setContentsMargins(0, 0, 0, 0)
        tb_header.setSpacing(12)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(2)
        self.page_title_lbl = QLabel("Экраны класса")
        self.page_title_lbl.setObjectName("PageTitle")
        self.page_subtitle_lbl = QLabel()
        self.page_subtitle_lbl.setObjectName("PageSubtitle")
        title_stack.addWidget(self.page_title_lbl)
        title_stack.addWidget(self.page_subtitle_lbl)
        tb_header.addLayout(title_stack)
        tb_header.addStretch(1)

        self.grid_view_controls = QWidget()
        self.grid_view_controls.setObjectName("TransparentPage")
        gvc = QHBoxLayout(self.grid_view_controls)
        gvc.setContentsMargins(0, 0, 0, 0)
        gvc.setSpacing(8)

        # Sort mode selector
        self.sort_combo = QComboBox()
        self.sort_combo.setMinimumWidth(196)
        self.sort_combo.setToolTip("Порядок отображения карточек ПК учеников")
        for key, label in GRID_SORT_MODES:
            self.sort_combo.addItem(label, key)
        cur_sort_idx = self.sort_combo.findData(self.config.grid_sort_mode)
        self.sort_combo.setCurrentIndex(cur_sort_idx if cur_sort_idx >= 0 else 0)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_mode_changed)

        # Card size controls (- [slider] + width)
        size_pod = GlassFrame(variant="inset", radius=12)
        sp_row = QHBoxLayout(size_pod)
        sp_row.setContentsMargins(8, 3, 8, 3)
        sp_row.setSpacing(6)

        self.btn_size_down = QPushButton("−")
        self.btn_size_down.setObjectName("IconPill")
        self.btn_size_down.setFixedSize(24, 24)
        self.btn_size_down.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_size_down.setToolTip("Уменьшить карточки")
        self.btn_size_down.clicked.connect(lambda: self._step_card_size(-36))

        self.card_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.card_size_slider.setRange(CARD_MIN_WIDTH, CARD_MAX_WIDTH)
        self.card_size_slider.setSingleStep(16)
        self.card_size_slider.setPageStep(36)
        self.card_size_slider.setFixedWidth(92)
        self.card_size_slider.setToolTip("Размер карточек экранов учеников")
        init_w = max(CARD_MIN_WIDTH, min(CARD_MAX_WIDTH, int(self.config.grid_card_width or CARD_DEFAULT_WIDTH)))
        self.card_size_slider.setValue(init_w)
        self.card_size_slider.valueChanged.connect(self._on_card_size_changed)

        self.btn_size_up = QPushButton("+")
        self.btn_size_up.setObjectName("IconPill")
        self.btn_size_up.setFixedSize(24, 24)
        self.btn_size_up.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_size_up.setToolTip("Увеличить карточки")
        self.btn_size_up.clicked.connect(lambda: self._step_card_size(36))

        self.card_size_lbl = QLabel(self._format_size_tag(init_w))
        self.card_size_lbl.setObjectName("MutedLabel")
        self.card_size_lbl.setFixedWidth(34)
        self.card_size_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        sp_row.addWidget(self.btn_size_down)
        sp_row.addWidget(self.card_size_slider)
        sp_row.addWidget(self.btn_size_up)
        sp_row.addWidget(self.card_size_lbl)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("SearchPill")
        self.search_input.setPlaceholderText("Поиск ПК, имени или IP...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedWidth(220)
        self._search_icon_action = self.search_input.addAction(
            make_icon("search", size=15),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.search_input.textChanged.connect(lambda _t: self._relayout_grid())

        gvc.addWidget(self.sort_combo)
        gvc.addWidget(size_pod)
        gvc.addWidget(self.search_input)
        tb_header.addWidget(self.grid_view_controls, alignment=Qt.AlignmentFlag.AlignVCenter)
        tb_outer.addLayout(tb_header)

        # Contextual Workstation Action Bar (shown ONLY on Page 0 when students are connected)
        self.grid_toolbar_widget = GlassFrame(variant="inset", radius=14)
        ag = QHBoxLayout(self.grid_toolbar_widget)
        ag.setContentsMargins(12, 8, 12, 8)
        ag.setSpacing(8)

        self.selected_badge_lbl = QLabel("Выбран ПК")
        self.selected_badge_lbl.setObjectName("AccentBadge")
        ag.addWidget(self.selected_badge_lbl)
        ag.addSpacing(4)

        self.btn_remote = QPushButton("Управление")
        self.btn_remote.setIconSize(QSize(15, 15))
        self.btn_remote.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remote.setProperty("accent", "primary")
        self.btn_remote.clicked.connect(self._open_selected_remote)

        self.btn_lock = QPushButton("Блок")
        self.btn_lock.setIconSize(QSize(15, 15))
        self.btn_lock.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lock.setProperty("accent", "warning")
        self.btn_lock.clicked.connect(lambda: self._run_on_selected("lock"))

        self.btn_unlock = QPushButton("Разблок")
        self.btn_unlock.setIconSize(QSize(15, 15))
        self.btn_unlock.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_unlock.clicked.connect(lambda: self._run_on_selected("unlock"))

        self.btn_msg = QPushButton("Сообщение")
        self.btn_msg.setIconSize(QSize(15, 15))
        self.btn_msg.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_msg.clicked.connect(lambda: self._send_message_dialog(self.selected_client_id))

        self.btn_ping = QPushButton("Инфо")
        self.btn_ping.setIconSize(QSize(15, 15))
        self.btn_ping.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ping.clicked.connect(lambda: self._run_on_selected("ping"))

        self.btn_power = QPushButton("Питание")
        self.btn_power.setIconSize(QSize(15, 15))
        self.btn_power.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_power.setProperty("accent", "danger")
        self.btn_power.setMenu(self._build_power_menu())

        # Left group: selected PC + everyday safe actions
        ag.addWidget(self.btn_remote)
        ag.addWidget(self.btn_msg)
        ag.addWidget(self.btn_ping)

        # Visual separation between everyday actions and restriction/power controls
        ag.addStretch(1)

        # Right group: screen lock & power controls
        ag.addWidget(self.btn_lock)
        ag.addWidget(self.btn_unlock)
        ag.addWidget(self.btn_power)

        tb_outer.addWidget(self.grid_toolbar_widget)
        c_layout.addWidget(top_bar)

        # ================= STACKED PAGES =================
        self.pages = QStackedWidget()

        # ---------- PAGE 0: Classroom Screen Grid & Onboarding Empty State ----------
        grid_page = QWidget()
        grid_page.setObjectName("TransparentPage")
        grid_v = QVBoxLayout(grid_page)
        grid_v.setContentsMargins(0, 0, 0, 0)
        grid_v.setSpacing(0)

        # Centered Empty State Onboarding Card
        self.empty_state_wrap = QWidget()
        self.empty_state_wrap.setObjectName("TransparentPage")
        empty_outer = QVBoxLayout(self.empty_state_wrap)
        empty_outer.setContentsMargins(20, 20, 20, 20)
        empty_outer.addStretch(1)

        empty_card = GlassFrame(variant="card", radius=22)
        empty_card.setMaximumWidth(540)
        ec_layout = QVBoxLayout(empty_card)
        ec_layout.setContentsMargins(36, 34, 36, 32)
        ec_layout.setSpacing(12)

        empty_icon_lbl = QLabel()
        empty_icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon_lbl.setPixmap(make_brand_pixmap(54))
        ec_layout.addWidget(empty_icon_lbl)

        empty_title = QLabel("Ожидание подключения учеников")
        empty_title.setObjectName("DialogTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ec_layout.addWidget(empty_title)

        self.empty_hint = QLabel()
        self.empty_hint.setObjectName("MutedLabel")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        ec_layout.addWidget(self.empty_hint)

        ec_layout.addSpacing(6)
        empty_btn_row = QHBoxLayout()
        empty_btn_row.addStretch(1)
        self.empty_copy_key_btn = QPushButton("Скопировать ключ класса")
        self.empty_copy_key_btn.setIconSize(QSize(16, 16))
        self.empty_copy_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.empty_copy_key_btn.setProperty("accent", "primary")
        self.empty_copy_key_btn.clicked.connect(self._copy_class_secret)
        empty_btn_row.addWidget(self.empty_copy_key_btn)
        empty_btn_row.addStretch(1)
        ec_layout.addLayout(empty_btn_row)

        empty_h = QHBoxLayout()
        empty_h.addStretch(1)
        empty_h.addWidget(empty_card, stretch=1)
        empty_h.addStretch(1)
        empty_outer.addLayout(empty_h)
        empty_outer.addStretch(1)
        grid_v.addWidget(self.empty_state_wrap, stretch=1)

        # Search filter empty hint (when clients exist, but 0 match query)
        self.no_match_lbl = QLabel()
        self.no_match_lbl.setObjectName("MutedLabel")
        self.no_match_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_match_lbl.hide()
        grid_v.addWidget(self.no_match_lbl)

        # Scrollable Workstation Grid
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.grid_widget = QWidget()
        self.grid_widget.setObjectName("TransparentPage")
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(2, 2, 2, 8)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_layout.setSpacing(14)
        self.scroll_area.setWidget(self.grid_widget)
        self.scroll_area.hide()
        grid_v.addWidget(self.scroll_area, stretch=1)

        self.pages.addWidget(grid_page)

        # ---------- PAGE 1: PowerShell Studio + Saved Commands + MCP AI Bridge ----------
        ps_page = QWidget()
        ps_page.setObjectName("TransparentPage")
        ps_outer = QVBoxLayout(ps_page)
        ps_outer.setContentsMargins(0, 0, 0, 0)
        ps_outer.setSpacing(14)

        # Compact Liquid Glass MCP Control Bar for AI assistants
        mcp_bar = GlassFrame(variant="card", radius=16)
        mcp_lay = QHBoxLayout(mcp_bar)
        mcp_lay.setContentsMargins(16, 12, 16, 12)
        mcp_lay.setSpacing(12)

        mcp_text_col = QVBoxLayout()
        mcp_text_col.setContentsMargins(0, 0, 0, 0)
        mcp_text_col.setSpacing(2)
        mcp_title_row = QHBoxLayout()
        mcp_title_row.setSpacing(8)
        mcp_title_lbl = QLabel("MCP-сервер для нейросетей")
        mcp_title_lbl.setObjectName("CardSectionTitle")
        self.mcp_status_badge = QLabel("Выключен")
        self.mcp_status_badge.setObjectName("MonBadge")
        mcp_title_row.addWidget(mcp_title_lbl)
        mcp_title_row.addWidget(self.mcp_status_badge)
        mcp_title_row.addStretch(1)

        self.mcp_sub_lbl = QLabel(
            f"Подключение ИИ к PowerShell класса: http://127.0.0.1:{self.config.mcp_port}/mcp"
        )
        self.mcp_sub_lbl.setObjectName("MutedLabel")
        mcp_text_col.addLayout(mcp_title_row)
        mcp_text_col.addWidget(self.mcp_sub_lbl)
        mcp_lay.addLayout(mcp_text_col, stretch=1)

        self.btn_mcp_toggle = QPushButton("Включить MCP")
        self.btn_mcp_toggle.setCheckable(True)
        self.btn_mcp_toggle.setMinimumWidth(148)
        self.btn_mcp_toggle.setIconSize(QSize(15, 15))
        self.btn_mcp_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mcp_toggle.setProperty("accent", "primary")
        self.btn_mcp_toggle.toggled.connect(self._toggle_mcp_server)

        self.btn_mcp_copy_cfg = QPushButton("Копировать JSON")
        self.btn_mcp_copy_cfg.setMinimumWidth(156)
        self.btn_mcp_copy_cfg.setIconSize(QSize(15, 15))
        self.btn_mcp_copy_cfg.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mcp_copy_cfg.setToolTip("Скопировать готовый конфиг mcpServers с токеном для подключения нейросети")
        self.btn_mcp_copy_cfg.clicked.connect(self._copy_mcp_config)

        self.btn_mcp_regen_token = QPushButton("Новый токен")
        self.btn_mcp_regen_token.setMinimumWidth(128)
        self.btn_mcp_regen_token.setIconSize(QSize(15, 15))
        self.btn_mcp_regen_token.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mcp_regen_token.setToolTip("Сгенерировать новый секретный Bearer-токен для MCP")
        self.btn_mcp_regen_token.clicked.connect(self._regenerate_mcp_token)

        mcp_lay.addWidget(self.btn_mcp_toggle)
        mcp_lay.addWidget(self.btn_mcp_copy_cfg)
        mcp_lay.addWidget(self.btn_mcp_regen_token)
        ps_outer.addWidget(mcp_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(16)

        # Left Glass Card: Saved Commands Library
        saved_panel = GlassFrame(variant="card", radius=18)
        saved_panel.setMinimumWidth(280)
        saved_panel.setMaximumWidth(360)
        sp = QVBoxLayout(saved_panel)
        sp.setContentsMargins(18, 18, 18, 18)
        sp.setSpacing(12)

        sp_title = QLabel("СОХРАНЁННЫЕ КОМАНДЫ")
        sp_title.setObjectName("SectionLabel")
        sp.addWidget(sp_title)

        self.saved_cmd_list = QListWidget()
        self.saved_cmd_list.itemClicked.connect(self._on_saved_cmd_clicked)
        self.saved_cmd_list.itemDoubleClicked.connect(self._on_saved_cmd_double_clicked)
        sp.addWidget(self.saved_cmd_list, stretch=1)

        sp_btns = QHBoxLayout()
        sp_btns.setSpacing(8)
        self.save_cmd_btn = QPushButton("Сохранить")
        self.save_cmd_btn.setIconSize(QSize(15, 15))
        self.save_cmd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_cmd_btn.setProperty("accent", "primary")
        self.save_cmd_btn.clicked.connect(self._save_current_ps_command)

        self.del_cmd_btn = QPushButton("Удалить")
        self.del_cmd_btn.setIconSize(QSize(15, 15))
        self.del_cmd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.del_cmd_btn.clicked.connect(self._delete_selected_ps_command)

        sp_btns.addWidget(self.save_cmd_btn, stretch=1)
        sp_btns.addWidget(self.del_cmd_btn)
        sp.addLayout(sp_btns)

        self.run_saved_all_btn = QPushButton("Запустить на всех ПК")
        self.run_saved_all_btn.setIconSize(QSize(15, 15))
        self.run_saved_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_saved_all_btn.setProperty("accent", "success")
        self.run_saved_all_btn.clicked.connect(self._run_selected_saved_on_all)
        sp.addWidget(self.run_saved_all_btn)

        # Right Glass Card: Script Editor & Output Console
        exec_panel = GlassFrame(variant="card", radius=18)
        ep = QVBoxLayout(exec_panel)
        ep.setContentsMargins(18, 18, 18, 18)
        ep.setSpacing(12)

        target_row = QHBoxLayout()
        target_row.setSpacing(10)
        target_lbl = QLabel("Цель выполнения:")
        target_lbl.setObjectName("MutedLabel")
        self.ps_target_combo = QComboBox()
        self.ps_target_combo.setMinimumWidth(290)
        self._refresh_ps_targets()
        target_row.addWidget(target_lbl)
        target_row.addWidget(self.ps_target_combo)
        target_row.addStretch(1)
        ep.addLayout(target_row)

        self.ps_input = QPlainTextEdit()
        mono_font = QFont()
        mono_font.setFamilies(["Cascadia Mono", "Consolas", "Courier New"])
        mono_font.setPointSize(10)
        self.ps_input.setFont(mono_font)
        self.ps_input.setPlaceholderText(
            "Введите команду PowerShell (например: Start-Process 'https://python.org') "
            "или выберите готовый сценарий слева..."
        )
        self.ps_input.setFixedHeight(104)
        ep.addWidget(self.ps_input)

        ps_btns = QHBoxLayout()
        ps_btns.setSpacing(8)
        self.run_ps_btn = QPushButton("Выполнить (цель)")
        self.run_ps_btn.setIconSize(QSize(15, 15))
        self.run_ps_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_ps_btn.setProperty("accent", "primary")
        self.run_ps_btn.clicked.connect(self._execute_powershell)

        self.run_all_ps_btn = QPushButton("На всех ПК")
        self.run_all_ps_btn.setIconSize(QSize(15, 15))
        self.run_all_ps_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_all_ps_btn.setProperty("accent", "success")
        self.run_all_ps_btn.clicked.connect(self._execute_powershell_all)

        self.clear_ps_btn = QPushButton("Очистить вывод")
        self.clear_ps_btn.setIconSize(QSize(15, 15))
        self.clear_ps_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_ps_btn.clicked.connect(lambda: self.ps_output.clear())

        ps_btns.addWidget(self.run_ps_btn)
        ps_btns.addWidget(self.run_all_ps_btn)
        ps_btns.addWidget(self.clear_ps_btn)
        ps_btns.addStretch(1)
        ep.addLayout(ps_btns)

        self.ps_output = QPlainTextEdit()
        self.ps_output.setObjectName("ConsoleBox")
        self.ps_output.setReadOnly(True)
        self.ps_output.setPlaceholderText("Вывод удалённых команд PowerShell появится здесь...")
        ep.addWidget(self.ps_output, stretch=1)

        splitter.addWidget(saved_panel)
        splitter.addWidget(exec_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        ps_outer.addWidget(splitter, stretch=1)
        self.pages.addWidget(ps_page)

        # ---------- PAGE 2: Audit Log ----------
        log_page = QWidget()
        log_page.setObjectName("TransparentPage")
        log_outer = QVBoxLayout(log_page)
        log_outer.setContentsMargins(0, 0, 0, 0)

        log_card = GlassFrame(variant="card", radius=18)
        log_v = QVBoxLayout(log_card)
        log_v.setContentsMargins(16, 14, 16, 16)
        log_v.setSpacing(10)

        log_bar = QHBoxLayout()
        log_bar.setSpacing(8)
        log_sec_lbl = QLabel("СИСТЕМНЫЙ ЖУРНАЛ СЕССИИ И АУДИТА")
        log_sec_lbl.setObjectName("SectionLabel")
        log_bar.addWidget(log_sec_lbl)
        log_bar.addStretch(1)

        self.btn_copy_log = QPushButton("Копировать журнал")
        self.btn_copy_log.setIconSize(QSize(15, 15))
        self.btn_copy_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_log.clicked.connect(self._copy_audit_log)

        self.btn_clear_log = QPushButton("Очистить вид")
        self.btn_clear_log.setIconSize(QSize(15, 15))
        self.btn_clear_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_log.clicked.connect(self._clear_audit_log_view)

        log_bar.addWidget(self.btn_copy_log)
        log_bar.addWidget(self.btn_clear_log)
        log_v.addLayout(log_bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("ConsoleBox")
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("События запуска TLS-сервера, подключений и действий в классе...")
        log_v.addWidget(self.log_view, stretch=1)

        log_outer.addWidget(log_card, stretch=1)
        self.pages.addWidget(log_page)

        c_layout.addWidget(self.pages, stretch=1)
        root.addWidget(content, stretch=1)

        self.setCentralWidget(central)
        self._refresh_classroom_combo()
        self._refresh_saved_commands()
        self._refresh_header_labels()
        self._refresh_icons()
        self._update_page_header()
        self._update_toolbar_state()

    @staticmethod
    def _set_btn_state(btn: QPushButton, enabled: bool, tooltip: str = "") -> None:
        btn.setEnabled(enabled)
        btn.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ForbiddenCursor
        )
        if tooltip:
            btn.setToolTip(tooltip)

    def _active_clients(self) -> dict[str, StudentSession]:
        if self._room_filter == "__ALL_ROOMS__":
            return dict(self.server.clients)
        target = self._room_filter.strip().lower()
        return {
            cid: s
            for cid, s in self.server.clients.items()
            if not s.classroom_id or s.classroom_id.strip().lower() == target
        }

    def _room_online_count(self, room_id: str) -> int:
        target = room_id.strip().lower()
        return sum(
            1
            for s in self.server.clients.values()
            if (s.classroom_id or self.config.classroom_id).strip().lower() == target
        )

    def _refresh_classroom_combo(self) -> None:
        rooms = self.config.ensure_classrooms()
        self.classroom_combo.blockSignals(True)
        self.classroom_combo.clear()
        for room in rooms:
            rid = room["id"]
            cnt = self._room_online_count(rid)
            self.classroom_combo.addItem(f"{rid}  ({cnt})", rid)
        if len(rooms) > 1:
            self.classroom_combo.addItem(f"Все кабинеты  ({len(self.server.clients)})", "__ALL_ROOMS__")
        idx = self.classroom_combo.findData(self._room_filter)
        if idx < 0:
            idx = self.classroom_combo.findData(self.config.classroom_id)
        if idx < 0:
            idx = 0
        self.classroom_combo.setCurrentIndex(idx)
        self._room_filter = str(self.classroom_combo.currentData() or self.config.classroom_id)
        self.classroom_combo.blockSignals(False)

    def _on_classroom_changed(self) -> None:
        selected = str(self.classroom_combo.currentData() or "")
        if not selected:
            return
        self._room_filter = selected
        if selected != "__ALL_ROOMS__":
            if self.config.set_active_classroom(selected):
                save_config(self.config_path, self.config)
            self.setWindowTitle(f"Classroom Manager — {self.config.classroom_id}")
        else:
            self.setWindowTitle("Classroom Manager — Все кабинеты")

        active = self._active_clients()
        if self.selected_client_id not in active:
            self.selected_client_id = next(iter(active.keys()), None)
        for cid, card in self.cards.items():
            card.set_selected(cid == self.selected_client_id)

        self._relayout_grid()
        self._refresh_header_labels()
        self._refresh_ps_targets()
        self._update_toolbar_state()

    def _add_classroom_dialog(self) -> None:
        existing = [r["id"] for r in self.config.ensure_classrooms()]
        dlg = AddClassroomDialog(existing, self)
        if dlg.exec() != AddClassroomDialog.DialogCode.Accepted:
            return
        self.config.add_or_update_classroom(dlg.created_room_id, dlg.created_secret)
        self.config.set_active_classroom(dlg.created_room_id)
        save_config(self.config_path, self.config)
        self._room_filter = dlg.created_room_id
        self.setWindowTitle(f"Classroom Manager — {self.config.classroom_id}")
        self._refresh_classroom_combo()
        self._relayout_grid()
        self._refresh_header_labels()
        self._refresh_ps_targets()
        self._update_toolbar_state()
        self.statusBar().showMessage(f"Кабинет «{dlg.created_room_id}» создан и выбран активным", 4000)

    def _delete_current_classroom(self) -> None:
        rooms = self.config.ensure_classrooms()
        if len(rooms) <= 1 or self._room_filter == "__ALL_ROOMS__":
            return
        rid = self._room_filter
        reply = QMessageBox.question(
            self,
            "Удалить кабинет",
            f"Удалить кабинет «{rid}» из списка?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self.config.remove_classroom(rid):
            save_config(self.config_path, self.config)
            self._room_filter = self.config.classroom_id
            self.setWindowTitle(f"Classroom Manager — {self.config.classroom_id}")
            self._refresh_classroom_combo()
            self._relayout_grid()
            self._refresh_header_labels()
            self._refresh_ps_targets()
            self._update_toolbar_state()
            self.statusBar().showMessage(f"Кабинет «{rid}» удалён", 4000)

    def _make_nav_btn(self, text: str, icon_name: str, page_index: int, checked: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("NavButton")
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setIconSize(QSize(18, 18))
        btn.setProperty("icon_name", icon_name)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self._switch_page(page_index))
        self.nav_group.addButton(btn, page_index)
        return btn

    def _switch_page(self, page_index: int, title: str | None = None) -> None:
        self.pages.setCurrentIndex(page_index)
        is_grid = page_index == 0
        self.grid_view_controls.setVisible(is_grid)
        self.grid_toolbar_widget.setVisible(is_grid and bool(self._active_clients()))
        self._update_page_header(explicit_title=title)
        self._refresh_nav_icons()

    def _update_page_header(self, explicit_title: str | None = None) -> None:
        idx = self.pages.currentIndex()
        online = len(self._active_clients())
        room_tag = "Все кабинеты" if self._room_filter == "__ALL_ROOMS__" else self.config.classroom_id
        if idx == 0:
            self.page_title_lbl.setText(explicit_title or f"Экраны класса – {room_tag}")
            if online == 0:
                self.page_subtitle_lbl.setText(f"Кабинет {room_tag} – ожидание подключений в локальной сети")
            else:
                self.page_subtitle_lbl.setText(f"Онлайн: {online} ПК – двойной клик для HD-управления")
        elif idx == 1:
            self.page_title_lbl.setText(explicit_title or "Терминал PowerShell")
            self.page_subtitle_lbl.setText("Удалённое выполнение команд, библиотека сценариев и MCP для ИИ")
        else:
            self.page_title_lbl.setText(explicit_title or "Журнал событий")
            self.page_subtitle_lbl.setText("Аудит TLS-подключений, команд управления и событий безопасности")

    def _refresh_nav_icons(self) -> None:
        t = get_tokens(self.config.theme)
        active_col = "#FFFFFF" if t.is_dark else "#005EC4"
        for btn in (self.nav_screens, self.nav_commands, self.nav_logs):
            icon_name = str(btn.property("icon_name") or "grid")
            col = active_col if btn.isChecked() else t.text_secondary
            btn.setIcon(make_icon(icon_name, col, size=18))

    def _refresh_icons(self) -> None:
        t = get_tokens(self.config.theme)
        dim = "#3A475E" if t.is_dark else "#CBD5E1"
        self._refresh_nav_icons()

        # Multi-classroom buttons
        self.btn_add_room.setIcon(_themed_icon("plus", t.accent, dim, size=16))
        self.btn_del_room.setIcon(_themed_icon("trash", t.danger, dim, size=15))

        # Sidebar quick actions
        if self.btn_demo.isChecked():
            self.btn_demo.setIcon(_themed_icon("stop", "#FFFFFF", dim, size=17))
        else:
            self.btn_demo.setIcon(_themed_icon("cast", "#FFFFFF", dim, size=17))

        self.btn_files.setIcon(_themed_icon("send_file", t.text, dim, size=17))
        self.btn_lock_all.setIcon(_themed_icon("lock", t.danger, dim, size=16))
        self.btn_unlock_all.setIcon(_themed_icon("unlock", t.text, dim, size=16))

        # Connection pod & bottom bar
        secret_icon = "eye_off" if self.secret_toggle_btn.isChecked() else "eye"
        secret_col = t.accent if self.secret_toggle_btn.isChecked() else t.text_secondary
        self.secret_toggle_btn.setIcon(make_icon(secret_icon, secret_col, size=15))
        self.copy_key_btn.setIcon(make_icon("copy", t.text, size=15))
        self.settings_btn.setIcon(make_icon("settings", t.text, size=16))
        self._update_theme_button()

        # Top glass bar contextual controls
        self._search_icon_action.setIcon(make_icon("search", t.text_muted, size=15))
        self.btn_remote.setIcon(_themed_icon("remote", "#FFFFFF", dim, size=15))
        self.btn_lock.setIcon(_themed_icon("lock", t.danger, dim, size=15))
        unlock_active_col = "#FFFFFF" if self.btn_unlock.property("accent") == "success" else t.text
        self.btn_unlock.setIcon(_themed_icon("unlock", unlock_active_col, dim, size=15))
        self.btn_msg.setIcon(_themed_icon("message", t.text, dim, size=15))
        self.btn_ping.setIcon(_themed_icon("pulse", t.text, dim, size=15))
        self.btn_power.setIcon(_themed_icon("power", "#FFFFFF", dim, size=15))

        # Empty state & PowerShell & MCP & Audit Log buttons
        self.empty_copy_key_btn.setIcon(make_icon("copy", "#FFFFFF", size=16))
        self.btn_mcp_toggle.setIcon(make_icon("stop" if self.btn_mcp_toggle.isChecked() else "bolt", "#FFFFFF", size=15))
        self.btn_mcp_copy_cfg.setIcon(make_icon("copy", t.text, size=15))
        self.btn_mcp_regen_token.setIcon(make_icon("refresh", t.text, size=15))
        self.save_cmd_btn.setIcon(_themed_icon("plus", "#FFFFFF", dim, size=15))
        self.del_cmd_btn.setIcon(_themed_icon("trash", t.text, dim, size=15))
        self.run_saved_all_btn.setIcon(_themed_icon("bolt", "#FFFFFF", dim, size=15))
        self.run_ps_btn.setIcon(_themed_icon("play", "#FFFFFF", dim, size=15))
        self.run_all_ps_btn.setIcon(_themed_icon("bolt", "#FFFFFF", dim, size=15))
        self.clear_ps_btn.setIcon(_themed_icon("trash", t.text, dim, size=15))
        self.btn_copy_log.setIcon(_themed_icon("copy", t.text, dim, size=15))
        self.btn_clear_log.setIcon(_themed_icon("trash", t.text, dim, size=15))

        for card in self.cards.values():
            card.refresh_theme_icons()
            card.update()

    def _on_secret_toggle(self) -> None:
        t = get_tokens(self.config.theme)
        secret_icon = "eye_off" if self.secret_toggle_btn.isChecked() else "eye"
        self.secret_toggle_btn.setIcon(make_icon(secret_icon, t.text_secondary, size=15))
        self._refresh_header_labels()

    def _toggle_theme(self) -> None:
        self.config.theme = "light" if self.config.theme == "dark" else "dark"
        save_config(self.config_path, self.config)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(get_stylesheet(self.config.theme))
        apply_window_chrome(self, self.config.theme)
        self._refresh_icons()
        if self.centralWidget() is not None:
            self.centralWidget().update()

    def _update_theme_button(self) -> None:
        t = get_tokens(self.config.theme)
        if t.is_dark:
            self.theme_btn.setText("Светлая")
            self.theme_btn.setIcon(make_icon("sun", t.text, size=16))
        else:
            self.theme_btn.setText("Тёмная")
            self.theme_btn.setIcon(make_icon("moon", t.text, size=16))

    def _copy_class_secret(self) -> None:
        QApplication.clipboard().setText(self.config.class_secret)
        self.statusBar().showMessage("Ключ класса скопирован в буфер обмена", 3000)

    def _copy_audit_log(self) -> None:
        QApplication.clipboard().setText(self.log_view.toPlainText())
        self.statusBar().showMessage("Журнал событий скопирован в буфер обмена", 3000)

    def _clear_audit_log_view(self) -> None:
        self.log_view.clear()
        self.statusBar().showMessage("Экран журнала очищен (файлы логов на диске сохранены)", 3000)

    def _build_power_menu(self) -> QMenu:
        menu = QMenu(self)
        items = [
            ("lock_os", False, "Выбранный ПК: Заблокировать Windows"),
            ("reboot", False, "Выбранный ПК: Перезагрузить"),
            ("shutdown", False, "Выбранный ПК: Выключить"),
            ("cancel_shutdown", False, "Выбранный ПК: Отменить выключение"),
            ("sep", False, ""),
            ("lock_os", True, "Весь класс: Заблокировать Windows"),
            ("reboot", True, "Весь класс: Перезагрузить все ПК"),
            ("shutdown", True, "Весь класс: Выключить все ПК"),
            ("cancel_shutdown", True, "Весь класс: Отменить выключение"),
        ]
        for act_key, all_flag, label in items:
            if act_key == "sep":
                menu.addSeparator()
                continue
            action = QAction(label, self)
            action.triggered.connect(
                lambda _c=False, a=act_key, all_f=all_flag: self._trigger_power(a, all_f)
            )
            menu.addAction(action)
        return menu

    def _connect_signals(self) -> None:
        self.signals.client_connected.connect(self._on_client_connected)
        self.signals.client_disconnected.connect(self._on_client_disconnected)
        self.signals.client_updated.connect(self._on_client_updated)
        self.signals.screen_frame.connect(self._on_screen_frame)
        self.signals.log_line.connect(self._on_log_line)
        self.signals.mcp_activity.connect(self._on_mcp_activity)

    def _on_mcp_activity(self, line: str) -> None:
        self.ps_output.appendPlainText(f"[MCP] {line}")

    def _toggle_mcp_server(self, checked: bool) -> None:
        if checked:
            self.config.mcp_enabled = True
            if not self.config.mcp_token:
                self.config.mcp_token = generate_mcp_token()
                self.mcp_server.token = self.config.mcp_token
            save_config(self.config_path, self.config)
            _spawn_task(self._start_mcp_async())
        else:
            self.config.mcp_enabled = False
            save_config(self.config_path, self.config)
            _spawn_task(self._stop_mcp_async())

    async def _start_mcp_async(self) -> None:
        try:
            await self.mcp_server.start()
            self._update_mcp_ui()
            self.statusBar().showMessage(f"MCP-сервер запущен: {self.mcp_server.endpoint_url}", 5000)
        except OSError as exc:
            self.btn_mcp_toggle.blockSignals(True)
            self.btn_mcp_toggle.setChecked(False)
            self.btn_mcp_toggle.blockSignals(False)
            self.config.mcp_enabled = False
            save_config(self.config_path, self.config)
            self._update_mcp_ui()
            QMessageBox.warning(
                self,
                "Ошибка запуска MCP",
                f"Не удалось открыть локальный порт {self.config.mcp_port}:\n{exc}",
            )

    async def _stop_mcp_async(self) -> None:
        await self.mcp_server.stop()
        self._update_mcp_ui()
        self.statusBar().showMessage("MCP-сервер остановлен", 3000)

    def _update_mcp_ui(self) -> None:
        running = self.mcp_server.is_running
        self.btn_mcp_toggle.blockSignals(True)
        self.btn_mcp_toggle.setChecked(running)
        self.btn_mcp_toggle.blockSignals(False)
        if running:
            self.mcp_status_badge.setText(f"Активен :{self.mcp_server.bound_port}")
            self.mcp_status_badge.setObjectName("OnlineBadge")
            self.btn_mcp_toggle.setText("Выключить MCP")
            self.btn_mcp_toggle.setProperty("accent", "danger")
            self.btn_mcp_toggle.setIcon(make_icon("stop", "#FFFFFF", size=15))
        else:
            self.mcp_status_badge.setText("Выключен")
            self.mcp_status_badge.setObjectName("MonBadge")
            self.btn_mcp_toggle.setText("Включить MCP")
            self.btn_mcp_toggle.setProperty("accent", "primary")
            self.btn_mcp_toggle.setIcon(make_icon("bolt", "#FFFFFF", size=15))
        self.mcp_status_badge.style().unpolish(self.mcp_status_badge)
        self.mcp_status_badge.style().polish(self.mcp_status_badge)
        self.btn_mcp_toggle.style().unpolish(self.btn_mcp_toggle)
        self.btn_mcp_toggle.style().polish(self.btn_mcp_toggle)

    def _copy_mcp_config(self) -> None:
        if not self.config.mcp_token:
            self.config.mcp_token = generate_mcp_token()
            self.mcp_server.token = self.config.mcp_token
            save_config(self.config_path, self.config)
        cfg_json = build_mcp_client_config(self.mcp_server.bound_port, self.config.mcp_token)
        QApplication.clipboard().setText(cfg_json)
        self.statusBar().showMessage("JSON-конфиг MCP скопирован в буфер обмена", 4000)

    def _regenerate_mcp_token(self) -> None:
        self.config.mcp_token = generate_mcp_token()
        self.mcp_server.token = self.config.mcp_token
        save_config(self.config_path, self.config)
        self.statusBar().showMessage("Сгенерирован новый Bearer-токен MCP (скопируйте JSON заново)", 5000)

    async def start_server(self) -> None:
        try:
            await self.server.start()
            if self.config.mcp_enabled:
                await self._start_mcp_async()
            self._refresh_header_labels()
            self.statusBar().showMessage(
                f"Сервер активен, TLS-порт {self.server.bound_port}, "
                f"автопоиск LAN {'ВКЛ' if self.config.discovery_enabled else 'ВЫКЛ'}"
            )
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Ошибка запуска сервера",
                f"Не удалось открыть порт {self.config.tcp_port}:\n{exc}",
            )

    def _refresh_header_labels(self) -> None:
        ips = ", ".join(get_local_ipv4_addresses())
        active = self._active_clients()
        online = len(active)
        self.online_pill.setText(f"{online} онлайн")
        room_label = "Все кабинеты" if self._room_filter == "__ALL_ROOMS__" else self.config.classroom_id
        self.room_sub_lbl.setText(f"Кабинет {room_label}")

        secret_disp = self.config.class_secret if self.secret_toggle_btn.isChecked() else "••••••••••••"
        self.net_info_lbl.setText(
            f"Кабинет: {self.config.classroom_id}\n"
            f"LAN IP: {ips}\n"
            f"TLS-порт: {self.server.bound_port}  Ключ: {secret_disp}"
        )

        lan_status = "Автопоиск LAN активен" if self.config.discovery_enabled else "Ручное подключение по IP"
        self.empty_hint.setText(
            f"Запустите агент ученика на компьютерах кабинета «{self.config.classroom_id}» – они появятся здесь автоматически.\n\n"
            f"ID кабинета: {self.config.classroom_id}   IP учителя: {ips}:{self.server.bound_port}\n"
            f"{lan_status}"
        )
        self._refresh_classroom_combo()
        self._update_page_header()

    @staticmethod
    def _format_size_tag(width: int) -> str:
        if width <= 260:
            return "S"
        if width <= 350:
            return "M"
        if width <= 440:
            return "L"
        return "XL"

    def _current_order_room_key(self) -> str:
        return (self._room_filter or self.config.classroom_id or "default").strip().lower()

    def _on_sort_mode_changed(self) -> None:
        mode = str(self.sort_combo.currentData() or "natural_asc")
        if self.config.grid_sort_mode != mode:
            self.config.grid_sort_mode = mode
            save_config(self.config_path, self.config)
        self._relayout_grid()

    def _step_card_size(self, delta: int) -> None:
        val = max(CARD_MIN_WIDTH, min(CARD_MAX_WIDTH, self.card_size_slider.value() + delta))
        self.card_size_slider.setValue(val)

    def _on_card_size_changed(self, value: int) -> None:
        w = max(CARD_MIN_WIDTH, min(CARD_MAX_WIDTH, int(value)))
        self.card_size_lbl.setText(self._format_size_tag(w))
        if self.config.grid_card_width != w:
            self.config.grid_card_width = w
            save_config(self.config_path, self.config)
        for card in self.cards.values():
            card.set_card_width(w)
        self._relayout_grid()

    def _on_card_reordered(self, source_id: str, target_id: str) -> None:
        if source_id == target_id:
            return
        active = self._active_clients()
        if source_id not in active or target_id not in active:
            return

        room_key = self._current_order_room_key()
        current_sorted = sort_sessions(
            list(active.values()),
            self.config.grid_sort_mode,
            self.config.grid_custom_order.get(room_key),
        )
        order = [s.client_id for s in current_sorted]
        if source_id not in order or target_id not in order:
            return

        order.remove(source_id)
        target_idx = order.index(target_id)
        order.insert(target_idx, source_id)

        self.config.grid_custom_order[room_key] = order
        self.config.grid_sort_mode = "custom"
        save_config(self.config_path, self.config)

        self.sort_combo.blockSignals(True)
        idx = self.sort_combo.findData("custom")
        if idx >= 0:
            self.sort_combo.setCurrentIndex(idx)
        self.sort_combo.blockSignals(False)

        self._select_client(source_id)
        self._relayout_grid()
        self.statusBar().showMessage("Порядок ПК сохранён (режим: Вручную)", 3500)

    def _relayout_grid(self) -> None:
        while self.grid_layout.count():
            self.grid_layout.takeAt(0)

        active = self._active_clients()
        for cid, card in self.cards.items():
            if cid not in active:
                card.setVisible(False)

        if not active:
            self.empty_state_wrap.setVisible(True)
            self.no_match_lbl.setVisible(False)
            self.scroll_area.setVisible(False)
            return

        self.empty_state_wrap.setVisible(False)
        query = self.search_input.text().strip().lower()
        room_key = self._current_order_room_key()
        ordered_sessions = sort_sessions(
            list(active.values()),
            self.config.grid_sort_mode,
            self.config.grid_custom_order.get(room_key),
        )

        matched: list[StudentCardWidget] = []
        for sess in ordered_sessions:
            card = self.cards.get(sess.client_id)
            if card is None:
                continue
            if card.matches_query(query):
                card.setVisible(True)
                matched.append(card)
            else:
                card.setVisible(False)

        if not matched:
            self.no_match_lbl.setText(f"По запросу «{self.search_input.text().strip()}» компьютеры не найдены")
            self.no_match_lbl.setVisible(True)
            self.scroll_area.setVisible(False)
            return

        self.no_match_lbl.setVisible(False)
        self.scroll_area.setVisible(True)

        card_w = max(CARD_MIN_WIDTH, min(CARD_MAX_WIDTH, int(self.config.grid_card_width or CARD_DEFAULT_WIDTH)))
        vp_w = self.scroll_area.viewport().width()
        avail_w = vp_w if vp_w >= 260 else max(340, self.width() - 330)
        cols = max(1, (avail_w + 14) // (card_w + 14))
        for idx, card in enumerate(matched):
            r, c = divmod(idx, cols)
            self.grid_layout.addWidget(card, r, c)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.cards:
            self._relayout_grid()

    def _on_client_connected(self, session: StudentSession) -> None:
        card = self.cards.get(session.client_id)
        card_w = max(CARD_MIN_WIDTH, min(CARD_MAX_WIDTH, int(self.config.grid_card_width or CARD_DEFAULT_WIDTH)))
        if card is None:
            card = StudentCardWidget(session, card_width=card_w)
            card.clicked.connect(self._select_client)
            card.double_clicked.connect(self._open_remote_for)
            card.context_action.connect(self._handle_card_action)
            card.card_reordered.connect(self._on_card_reordered)
            self.cards[session.client_id] = card
        else:
            card.set_card_width(card_w)
            card.update_session(session)

        if self.selected_client_id is None:
            self._select_client(session.client_id)

        self._relayout_grid()
        self._refresh_header_labels()
        self._refresh_ps_targets()
        self._update_toolbar_state()

    def _on_client_disconnected(self, client_id: str) -> None:
        card = self.cards.pop(client_id, None)
        if card is not None:
            card.setParent(None)
            card.deleteLater()

        dlg = self.remote_dialogs.pop(client_id, None)
        if dlg is not None:
            dlg.close()

        if self.selected_client_id == client_id:
            self.selected_client_id = next(iter(self.cards.keys()), None)
            if self.selected_client_id:
                self._select_client(self.selected_client_id)

        self._relayout_grid()
        self._refresh_header_labels()
        self._refresh_ps_targets()
        self._update_toolbar_state()

    def _on_client_updated(self, session: StudentSession) -> None:
        card = self.cards.get(session.client_id)
        if card is not None:
            card.update_session(session)
        self._update_toolbar_state()
        if self.search_input.text().strip() or self.config.grid_sort_mode == "locked_first":
            self._relayout_grid()

    def _on_screen_frame(self, client_id: str, _w: int, _h: int, _mode_int: int, jpeg_bytes: bytes) -> None:
        card = self.cards.get(client_id)
        if card is not None:
            card.update_thumbnail(jpeg_bytes)
        dlg = self.remote_dialogs.get(client_id)
        if dlg is not None and dlg.isVisible():
            dlg.on_frame(jpeg_bytes)

    def _on_log_line(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def _select_client(self, client_id: str) -> None:
        self.selected_client_id = client_id
        for cid, card in self.cards.items():
            card.set_selected(cid == client_id)
        self._update_toolbar_state()

    def _update_selected_badge(self) -> None:
        sess = self._active_clients().get(self.selected_client_id or "")
        if sess is not None:
            lbl = sess.label
            short = (lbl[:18] + "…") if len(lbl) > 19 else lbl
            self.selected_badge_lbl.setText(f"Выбран: {short}")
            self.selected_badge_lbl.setToolTip(f"{sess.label} ({sess.ip})")
        else:
            self.selected_badge_lbl.setText("Выбран ПК")
            self.selected_badge_lbl.setToolTip("")

    def _update_toolbar_state(self) -> None:
        active = self._active_clients()
        sel_sess = active.get(self.selected_client_id or "")
        has_sel = sel_sess is not None
        has_any = bool(active)
        any_unlocked = any(not s.locked for s in active.values())
        any_locked = any(s.locked for s in active.values())
        self._update_selected_badge()

        # Hide empty action bar completely when 0 students are connected on Page 0
        self.grid_toolbar_widget.setVisible(self.pages.currentIndex() == 0 and has_any)

        # Classroom delete pill state
        can_del_room = len(self.config.ensure_classrooms()) > 1 and self._room_filter != "__ALL_ROOMS__"
        self._set_btn_state(
            self.btn_del_room,
            can_del_room,
            "Удалить текущий кабинет" if can_del_room else "Нельзя удалить единственный кабинет",
        )

        # Selected PC controls
        self._set_btn_state(
            self.btn_remote,
            has_sel,
            "Открыть HD-управление выбранным ПК" if has_sel else "Сначала выберите ПК ученика",
        )
        can_lock_sel = bool(sel_sess is not None and not sel_sess.locked)
        self._set_btn_state(
            self.btn_lock,
            can_lock_sel,
            "Заблокировать экран выбранного ПК"
            if can_lock_sel
            else ("Экран уже заблокирован" if has_sel else "Сначала выберите ПК ученика"),
        )
        can_unlock_sel = bool(sel_sess is not None and sel_sess.locked)
        self.btn_unlock.setProperty("accent", "success" if can_unlock_sel else "")
        self.btn_unlock.style().unpolish(self.btn_unlock)
        self.btn_unlock.style().polish(self.btn_unlock)
        t = get_tokens(self.config.theme)
        dim = "#3A475E" if t.is_dark else "#CBD5E1"
        self.btn_unlock.setIcon(_themed_icon("unlock", "#FFFFFF" if can_unlock_sel else t.text, dim, size=15))
        self._set_btn_state(
            self.btn_unlock,
            can_unlock_sel,
            "Разблокировать экран выбранного ПК"
            if can_unlock_sel
            else ("Экран этого ПК не заблокирован" if has_sel else "Сначала выберите ПК ученика"),
        )
        self._set_btn_state(
            self.btn_ping,
            has_sel,
            "Пинг и системная информация ПК" if has_sel else "Сначала выберите ПК ученика",
        )

        # Classroom-wide actions
        self._set_btn_state(
            self.btn_lock_all,
            any_unlocked,
            "Заблокировать экраны всех открытых ПК"
            if any_unlocked
            else ("Все ПК уже заблокированы" if has_any else "Нет подключённых учеников"),
        )
        self._set_btn_state(
            self.btn_unlock_all,
            any_locked,
            "Разблокировать все заблокированные ПК"
            if any_locked
            else ("Нет заблокированных ПК" if has_any else "Нет подключённых учеников"),
        )
        can_demo = has_any or self.btn_demo.isChecked()
        self._set_btn_state(
            self.btn_demo,
            can_demo,
            "Остановить трансляцию экрана"
            if self.btn_demo.isChecked()
            else ("Транслировать экран учителя всему классу" if has_any else "Нет подключённых учеников"),
        )
        self._set_btn_state(
            self.btn_files,
            has_any,
            "Передать файлы на ПК учеников" if has_any else "Нет подключённых учеников",
        )
        self._set_btn_state(
            self.btn_msg,
            has_any,
            "Отправить сообщение ученику или всему классу" if has_any else "Нет подключённых учеников",
        )
        self._set_btn_state(
            self.btn_power,
            has_any,
            "Управление питанием ПК" if has_any else "Нет подключённых учеников",
        )
        self._set_btn_state(
            self.run_ps_btn,
            has_any,
            "Выполнить скрипт на выбранной цели" if has_any else "Нет подключённых учеников",
        )
        self._set_btn_state(
            self.run_all_ps_btn,
            has_any,
            "Выполнить скрипт на всех онлайн-ПК" if has_any else "Нет подключённых учеников",
        )
        self._set_btn_state(
            self.run_saved_all_btn,
            has_any,
            "Запустить выбранную команду на всех онлайн-ПК" if has_any else "Нет подключённых учеников",
        )

    def _refresh_ps_targets(self) -> None:
        current = self.ps_target_combo.currentData()
        self.ps_target_combo.clear()
        self.ps_target_combo.addItem("Весь класс (все онлайн-ПК)", "__ALL__")
        for cid, s in self._active_clients().items():
            self.ps_target_combo.addItem(f"{s.label} ({s.ip})", cid)
        if current:
            idx = self.ps_target_combo.findData(current)
            if idx >= 0:
                self.ps_target_combo.setCurrentIndex(idx)

    # ---------- Saved PowerShell Commands ----------
    def _refresh_saved_commands(self) -> None:
        self.saved_cmd_list.clear()
        for item in self.config.saved_commands:
            name = str(item.get("name", "")).strip()
            script = str(item.get("script", "")).strip()
            if name and script:
                lw_item = QListWidgetItem(name)
                lw_item.setData(Qt.ItemDataRole.UserRole, script)
                lw_item.setToolTip(script)
                self.saved_cmd_list.addItem(lw_item)

    def _on_saved_cmd_clicked(self, item: QListWidgetItem) -> None:
        script = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if script:
            self.ps_input.setPlainText(script)

    def _on_saved_cmd_double_clicked(self, item: QListWidgetItem) -> None:
        script = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if script:
            self.ps_input.setPlainText(script)
            _spawn_task(self._run_ps_async("__ALL__", script))

    def _run_selected_saved_on_all(self) -> None:
        item = self.saved_cmd_list.currentItem()
        if item is None:
            self._execute_powershell_all()
            return
        script = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if script:
            self.ps_input.setPlainText(script)
            _spawn_task(self._run_ps_async("__ALL__", script))

    def _save_current_ps_command(self) -> None:
        script = self.ps_input.toPlainText().strip()
        if not script:
            QMessageBox.warning(self, "Пустая команда", "Сначала введите PowerShell-команду в поле редактора.")
            return
        cur_item = self.saved_cmd_list.currentItem()
        default_name = cur_item.text() if cur_item else ""
        name, ok = QInputDialog.getText(
            self,
            "Сохранить команду",
            "Название команды в библиотеке:",
            text=default_name,
        )
        if not ok or not name.strip():
            return
        clean_name = name.strip()
        updated = False
        for item in self.config.saved_commands:
            if str(item.get("name", "")).strip().lower() == clean_name.lower():
                item["name"] = clean_name
                item["script"] = script
                updated = True
                break
        if not updated:
            self.config.saved_commands.append({"name": clean_name, "script": script})
        save_config(self.config_path, self.config)
        self._refresh_saved_commands()
        self.statusBar().showMessage(f"Команда «{clean_name}» сохранена в библиотеку", 4000)

    def _delete_selected_ps_command(self) -> None:
        item = self.saved_cmd_list.currentItem()
        if item is None:
            return
        name = item.text()
        reply = QMessageBox.question(
            self,
            "Удалить команду",
            f"Удалить сохранённую команду «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.config.saved_commands = [
            cmd for cmd in self.config.saved_commands if str(cmd.get("name", "")) != name
        ]
        save_config(self.config_path, self.config)
        self._refresh_saved_commands()

    # ---------- Teacher Demo Broadcast ----------
    def _toggle_demo_broadcast(self, checked: bool) -> None:
        t = get_tokens(self.config.theme)
        if checked:
            self.btn_demo.setText("Остановить показ")
            self.btn_demo.setProperty("accent", "danger")
            self.btn_demo.setIcon(_themed_icon("stop", "#FFFFFF", t.text_muted, size=17))
            mon = int(self.demo_mon_combo.currentData() or 1)
            self.statusBar().showMessage("Идёт HD-демонстрация экрана учителя всем ученикам")
            _spawn_task(self.server.start_demo_broadcast(monitor=mon))
        else:
            self.btn_demo.setText("Демонстрация экрана")
            self.btn_demo.setProperty("accent", "primary")
            self.btn_demo.setIcon(_themed_icon("cast", "#FFFFFF", t.text_muted, size=17))
            self.statusBar().showMessage("Демонстрация экрана остановлена", 4000)
            _spawn_task(self.server.stop_demo_broadcast())
        self.btn_demo.style().unpolish(self.btn_demo)
        self.btn_demo.style().polish(self.btn_demo)
        self._update_toolbar_state()

    # ---------- Student Actions ----------
    def _open_selected_remote(self) -> None:
        if self.selected_client_id:
            self._open_remote_for(self.selected_client_id)

    def _open_remote_for(self, client_id: str) -> None:
        session = self.server.clients.get(client_id)
        if session is None:
            return
        existing = self.remote_dialogs.get(client_id)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dlg = RemoteControlDialog(self.server, session, self)
        dlg.finished.connect(lambda _r, cid=client_id: self.remote_dialogs.pop(cid, None))
        self.remote_dialogs[client_id] = dlg
        dlg.showMaximized()

    def _handle_card_action(self, client_id: str, action: str) -> None:
        if action == "control":
            self._open_remote_for(client_id)
        elif action == "lock":
            _spawn_task(self.server.lock_screen(client_id, "срок бана: 1000 лет"))
        elif action == "unlock":
            _spawn_task(self.server.unlock_screen(client_id))
        elif action == "send_file":
            self._open_file_transfer(preselected_id=client_id)
        elif action == "message":
            self._send_message_dialog(target_id=client_id)
        elif action == "powershell":
            self.nav_commands.setChecked(True)
            self._switch_page(1)
            idx = self.ps_target_combo.findData(client_id)
            if idx >= 0:
                self.ps_target_combo.setCurrentIndex(idx)
            self.ps_input.setFocus()
        elif action == "ping":
            _spawn_task(self._ping_and_show_info(client_id))
        elif action == "power_lock_os":
            self._trigger_power("lock_os", False, client_id)
        elif action == "power_reboot":
            self._trigger_power("reboot", False, client_id)
        elif action == "power_shutdown":
            self._trigger_power("shutdown", False, client_id)
        elif action == "power_cancel":
            self._trigger_power("cancel_shutdown", False, client_id)

    def _run_on_selected(self, action: str) -> None:
        if self.selected_client_id:
            self._handle_card_action(self.selected_client_id, action)

    def _lock_all_students(self) -> None:
        _spawn_task(self._broadcast_lock(True))

    def _unlock_all_students(self) -> None:
        _spawn_task(self._broadcast_lock(False))

    async def _broadcast_lock(self, lock: bool) -> None:
        for cid in list(self._active_clients().keys()):
            if lock:
                await self.server.lock_screen(cid, "срок бана: 1000 лет")
            else:
                await self.server.unlock_screen(cid)

    async def _ping_and_show_info(self, client_id: str) -> None:
        ping_res = await self.server.ping_client(client_id)
        info_res = await self.server.send_command(client_id, "GET_SYSTEM_INFO", timeout=8.0)
        if not info_res.get("ok"):
            QMessageBox.warning(self, "Инфо о ПК", f"Ошибка: {info_res.get('error')}")
            return
        d = info_res.get("data", {})
        rtt = ping_res.get("data", {}).get("rtt_ms", "?")
        mons = d.get("monitors") or []
        mon_text = (
            ", ".join(m.get("name", "") for m in mons)
            if mons
            else f"{d.get('screen_width')}×{d.get('screen_height')}"
        )
        QMessageBox.information(
            self,
            f"Системная информация — {d.get('hostname', client_id)}",
            f"Пинг: {rtt} мс\n"
            f"Имя ПК: {d.get('hostname')}\n"
            f"Пользователь: {d.get('username')}\n"
            f"ОС: {d.get('os')}\n"
            f"Ядра CPU: {d.get('cpu_count')}\n"
            f"Мониторы: {mon_text}\n"
            f"Активное окно: {d.get('active_window') or '—'}",
        )

    def _open_file_transfer(self, preselected_id: str | None = None) -> None:
        dlg = FileTransferDialog(
            self.server,
            preselected_client_id=preselected_id or self.selected_client_id,
            parent=self,
        )
        dlg.exec()

    def _send_message_dialog(self, target_id: str | None = None) -> None:
        has_target = bool(target_id and target_id in self.server.clients)
        who_hint = (
            f" для {self.server.clients[target_id].label}:"
            if has_target and target_id
            else " для всего класса:"
        )
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Отправить сообщение",
            "Текст сообщения" + who_hint,
        )
        if not ok or not text.strip():
            return
        if has_target and target_id:
            _spawn_task(self.server.show_message(target_id, "Сообщение от учителя", text.strip()))
        else:
            _spawn_task(
                self.server.broadcast_command(
                    "SHOW_MESSAGE",
                    {"title": "Сообщение от учителя", "text": text.strip()},
                )
            )

    def _trigger_power(self, action: str, all_students: bool, explicit_id: str | None = None) -> None:
        labels = {
            "lock_os": "заблокировать Windows",
            "reboot": "перезагрузить ПК",
            "shutdown": "выключить ПК",
            "cancel_shutdown": "отменить запланированное выключение",
        }
        target_id = explicit_id or self.selected_client_id
        if not all_students and (not target_id or target_id not in self.server.clients):
            return
        who = "на ВСЕХ подключённых ПК" if all_students else f"на ПК {self.server.clients[target_id].label}"
        reply = QMessageBox.question(
            self,
            "Подтверждение команды питания",
            f"Вы уверены, что хотите {labels.get(action, action)} {who}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if all_students:
            _spawn_task(self.server.broadcast_command("POWER_ACTION", {"action": action}))
        elif target_id:
            _spawn_task(self.server.power_action(target_id, action))

    def _execute_powershell(self) -> None:
        script = self.ps_input.toPlainText().strip()
        if not script:
            return
        target = self.ps_target_combo.currentData()
        if not target:
            return
        _spawn_task(self._run_ps_async(target, script))

    def _execute_powershell_all(self) -> None:
        script = self.ps_input.toPlainText().strip()
        if not script:
            return
        _spawn_task(self._run_ps_async("__ALL__", script))

    async def _run_ps_async(self, target: str, script: str) -> None:
        self.ps_output.appendPlainText(f"\n>>> PS> {script}")
        if target == "__ALL__":
            results = await self.server.broadcast_command(
                "POWERSHELL",
                {"script": script, "timeout": 30.0},
                timeout=35.0,
            )
            if not results:
                self.ps_output.appendPlainText("[Нет подключённых учеников]")
                return
            for cid, res in results.items():
                sess = self.server.clients.get(cid)
                name = sess.label if sess else cid
                self._append_ps_result(name, res)
        else:
            sess = self.server.clients.get(target)
            name = sess.label if sess else target
            res = await self.server.run_powershell(target, script, timeout=30.0)
            self._append_ps_result(name, res)

    def _append_ps_result(self, name: str, res: dict[str, Any]) -> None:
        if not res.get("ok"):
            self.ps_output.appendPlainText(f"[{name}] ОШИБКА: {res.get('error')}")
            return
        data = res.get("data", {})
        rc = data.get("returncode", 0)
        stdout = (data.get("stdout") or "").rstrip()
        stderr = (data.get("stderr") or "").rstrip()
        self.ps_output.appendPlainText(f"--- [{name}] exit={rc} ---")
        if stdout:
            self.ps_output.appendPlainText(stdout)
        if stderr:
            self.ps_output.appendPlainText(f"[stderr] {stderr}")

    def _open_settings(self) -> None:
        dlg = TeacherSettingsDialog(self.config, self.server.cert_fingerprint, self)
        if dlg.exec() == TeacherSettingsDialog.DialogCode.Accepted:
            save_config(self.config_path, self.config)
            if self._room_filter != "__ALL_ROOMS__":
                self._room_filter = self.config.classroom_id
            self.setWindowTitle(f"Classroom Manager — {self.config.classroom_id}")
            self._refresh_header_labels()
            self._update_toolbar_state()
            if dlg.network_restart_needed:
                _spawn_task(self._restart_server())

    async def _restart_server(self) -> None:
        await self.server.stop()
        await self.start_server()

    def closeEvent(self, event) -> None:
        for dlg in list(self.remote_dialogs.values()):
            dlg.close()
        _spawn_task(self.mcp_server.stop())
        _spawn_task(self.server.stop())
        super().closeEvent(event)
