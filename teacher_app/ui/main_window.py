"""Spotify-inspired Teacher console: sidebar navigation, dark/light themes, HD live view, saved commands."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from shared.config import TeacherConfig, save_config
from student_app.handlers.screen_capture import list_monitors
from teacher_app.network.discovery import get_local_ipv4_addresses
from teacher_app.network.server import StudentSession, TeacherServer
from teacher_app.ui.dialogs import TeacherSettingsDialog
from teacher_app.ui.file_transfer_dialog import FileTransferDialog
from teacher_app.ui.remote_view import RemoteControlDialog
from teacher_app.ui.theme import get_stylesheet, make_status_icon


class ServerSignals(QObject):
    """Qt signal bridge for callbacks invoked by TeacherServer."""

    client_connected = Signal(object)
    client_disconnected = Signal(str)
    client_updated = Signal(object)
    screen_frame = Signal(str, int, int, int, bytes)
    log_line = Signal(str)


class StudentCardWidget(QFrame):
    """Clean Spotify-style card showing one student's live screen preview and status."""

    clicked = Signal(str)
    double_clicked = Signal(str)
    context_action = Signal(str, str)

    def __init__(self, session: StudentSession, parent=None) -> None:
        super().__init__(parent)
        self.client_id = session.client_id
        self.setObjectName("StudentCard")
        self.setFixedSize(316, 260)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(7)

        # Header row
        top = QHBoxLayout()
        top.setSpacing(6)
        self.title_lbl = QLabel(session.label)
        self.title_lbl.setStyleSheet("font-weight: 700; font-size: 13px;")

        self.mon_lbl = QLabel("")
        self.mon_lbl.setObjectName("MonBadge")
        self.mon_lbl.setVisible(False)

        self.badge_lbl = QLabel("ONLINE")
        self.badge_lbl.setObjectName("OnlineBadge")

        top.addWidget(self.title_lbl, stretch=1)
        top.addWidget(self.mon_lbl)
        top.addWidget(self.badge_lbl)
        layout.addLayout(top)

        # Screen preview
        self.preview_lbl = QLabel("Ожидание экрана...")
        self.preview_lbl.setObjectName("PreviewBox")
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lbl.setFixedSize(292, 164)
        layout.addWidget(self.preview_lbl)

        # Footer meta
        self.meta_lbl = QLabel()
        self.meta_lbl.setObjectName("MutedLabel")
        self.window_lbl = QLabel()
        self.window_lbl.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.meta_lbl)
        layout.addWidget(self.window_lbl)

        self.update_session(session)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def update_session(self, session: StudentSession) -> None:
        self.title_lbl.setText(session.label)
        ping_str = f"  •  {session.last_ping_ms:.0f} мс" if session.last_ping_ms is not None else ""
        self.meta_lbl.setText(f"{session.username} @ {session.ip}{ping_str}")
        win = session.active_window.strip()
        self.window_lbl.setText((win[:40] + "…") if len(win) > 41 else (win or "Рабочий стол"))

        mon_count = len(session.monitors)
        if mon_count > 1:
            self.mon_lbl.setText(f"{mon_count} мон.")
            self.mon_lbl.setVisible(True)
        else:
            self.mon_lbl.setVisible(False)

        self.setProperty("locked", "true" if session.locked else "false")
        if session.locked:
            self.badge_lbl.setText("ЗАБАНЕН")
            self.badge_lbl.setObjectName("BanBadge")
        else:
            self.badge_lbl.setText("ONLINE")
            self.badge_lbl.setObjectName("OnlineBadge")

        self.badge_lbl.style().unpolish(self.badge_lbl)
        self.badge_lbl.style().polish(self.badge_lbl)
        self.style().unpolish(self)
        self.style().polish(self)

    def update_thumbnail(self, jpeg_bytes: bytes) -> None:
        pm = QPixmap()
        if pm.loadFromData(jpeg_bytes, "JPG"):
            scaled = pm.scaled(
                self.preview_lbl.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_lbl.setPixmap(scaled)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.client_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.client_id)
            self.double_clicked.emit(self.client_id)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.clicked.emit(self.client_id)
        menu = QMenu(self)
        actions = [
            ("control", "Просмотр и управление ПК (выбор монитора)"),
            ("lock", "Забанить экран (чёрный экран + красный крест)"),
            ("unlock", "Разбанить экран"),
            ("send_file", "Передать файл на этот ПК..."),
            ("message", "Отправить сообщение"),
            ("powershell", "Открыть PowerShell для ПК"),
            ("ping", "Пинг и инфо о системе"),
            ("sep", ""),
            ("power_lock_os", "Питание: Заблокировать Windows"),
            ("power_reboot", "Питание: Перезагрузить ПК"),
            ("power_shutdown", "Питание: Выключить ПК"),
            ("power_cancel", "Питание: Отменить выключение"),
        ]
        for key, label in actions:
            if key == "sep":
                menu.addSeparator()
                continue
            act = QAction(label, self)
            act.triggered.connect(lambda _c=False, k=key: self.context_action.emit(self.client_id, k))
            menu.addAction(act)
        menu.exec(event.globalPos())


class TeacherMainWindow(QMainWindow):
    """Spotify-style desktop dashboard for the Teacher application."""

    def __init__(
        self,
        config: TeacherConfig,
        config_path: Path,
        data_dir: Path,
        signals: ServerSignals,
    ) -> None:
        super().__init__()
        self.config = config
        self.config_path = config_path
        self.data_dir = data_dir
        self.signals = signals

        self.setWindowTitle(f"Classroom Manager — {config.classroom_id}")
        self.setWindowIcon(make_status_icon("#1DB954", "#000000"))
        self.resize(1340, 820)

        self.server = TeacherServer(
            config=config,
            data_dir=data_dir,
            on_client_connected=self.signals.client_connected.emit,
            on_client_disconnected=self.signals.client_disconnected.emit,
            on_client_updated=self.signals.client_updated.emit,
            on_screen_frame=lambda cid, w, h, m, data: self.signals.screen_frame.emit(cid, w, h, int(m), data),
        )

        self.cards: dict[str, StudentCardWidget] = {}
        self.selected_client_id: str | None = None
        self.remote_dialogs: dict[str, RemoteControlDialog] = {}

        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ================= LEFT SIDEBAR (Spotify-style) =================
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(272)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(16, 18, 16, 16)
        sb.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_lbl = QLabel("CLASSROOM")
        brand_lbl.setObjectName("BrandTitle")
        self.online_pill = QLabel("0 онлайн")
        self.online_pill.setObjectName("OnlineBadge")
        brand_row.addWidget(brand_lbl)
        brand_row.addStretch()
        brand_row.addWidget(self.online_pill)
        sb.addLayout(brand_row)

        self.room_sub_lbl = QLabel()
        self.room_sub_lbl.setObjectName("MutedLabel")
        sb.addWidget(self.room_sub_lbl)
        sb.addSpacing(12)

        nav_lbl = QLabel("РАЗДЕЛЫ")
        nav_lbl.setObjectName("SectionLabel")
        sb.addWidget(nav_lbl)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.nav_screens = self._make_nav_btn("Экраны класса", 0, checked=True)
        self.nav_commands = self._make_nav_btn("Команды (PowerShell)", 1)
        self.nav_logs = self._make_nav_btn("Журнал аудита", 2)
        sb.addWidget(self.nav_screens)
        sb.addWidget(self.nav_commands)
        sb.addWidget(self.nav_logs)

        sb.addSpacing(14)
        quick_lbl = QLabel("УПРАВЛЕНИЕ КЛАССОМ")
        quick_lbl.setObjectName("SectionLabel")
        sb.addWidget(quick_lbl)

        # Teacher monitor picker for Demo broadcast if teacher has >1 monitor
        self._teacher_monitors = list_monitors()
        self.demo_mon_combo = QComboBox()
        for mon in self._teacher_monitors:
            self.demo_mon_combo.addItem(f"Показ: {mon['name']}", int(mon["index"]))
        self.demo_mon_combo.setVisible(len(self._teacher_monitors) > 1)
        sb.addWidget(self.demo_mon_combo)

        self.btn_demo = QPushButton("Демонстрация экрана")
        self.btn_demo.setCheckable(True)
        self.btn_demo.setProperty("accent", "primary")
        self.btn_demo.toggled.connect(self._toggle_demo_broadcast)
        sb.addWidget(self.btn_demo)

        self.btn_files = QPushButton("Передать файл классу")
        self.btn_files.clicked.connect(lambda: self._open_file_transfer())
        sb.addWidget(self.btn_files)

        ban_row = QHBoxLayout()
        ban_row.setSpacing(6)
        self.btn_lock_all = QPushButton("Бан всех")
        self.btn_lock_all.setProperty("accent", "warning")
        self.btn_lock_all.clicked.connect(self._lock_all_students)
        self.btn_unlock_all = QPushButton("Разбан всех")
        self.btn_unlock_all.clicked.connect(self._unlock_all_students)
        ban_row.addWidget(self.btn_lock_all)
        ban_row.addWidget(self.btn_unlock_all)
        sb.addLayout(ban_row)

        sb.addStretch()

        # Bottom connection & theme card
        info_card = QFrame()
        info_card.setObjectName("SidebarCard")
        ic = QVBoxLayout(info_card)
        ic.setContentsMargins(12, 10, 12, 10)
        ic.setSpacing(6)

        self.net_info_lbl = QLabel()
        self.net_info_lbl.setObjectName("MutedLabel")
        self.net_info_lbl.setWordWrap(True)
        ic.addWidget(self.net_info_lbl)

        key_row = QHBoxLayout()
        self.secret_toggle_btn = QPushButton("Ключ")
        self.secret_toggle_btn.setCheckable(True)
        self.secret_toggle_btn.toggled.connect(self._refresh_header_labels)
        copy_key_btn = QPushButton("Копир.")
        copy_key_btn.clicked.connect(self._copy_class_secret)
        key_row.addWidget(self.secret_toggle_btn, stretch=1)
        key_row.addWidget(copy_key_btn, stretch=1)
        ic.addLayout(key_row)
        sb.addWidget(info_card)

        # Theme & Settings buttons
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)
        self.theme_btn = QPushButton()
        self.theme_btn.clicked.connect(self._toggle_theme)
        self._update_theme_button_text()

        settings_btn = QPushButton("Настройки")
        settings_btn.clicked.connect(self._open_settings)
        bottom_row.addWidget(self.theme_btn, stretch=1)
        bottom_row.addWidget(settings_btn)
        sb.addLayout(bottom_row)

        root.addWidget(sidebar)

        # ================= RIGHT CONTENT AREA =================
        content = QWidget()
        content.setObjectName("ContentArea")
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(0)

        # Contextual Top Bar
        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        tb = QHBoxLayout(top_bar)
        tb.setContentsMargins(20, 12, 20, 12)
        tb.setSpacing(8)

        self.page_title_lbl = QLabel("Экраны класса")
        self.page_title_lbl.setObjectName("PageTitle")
        tb.addWidget(self.page_title_lbl)
        tb.addStretch()

        self.btn_remote = QPushButton("Управление ПК")
        self.btn_remote.setProperty("accent", "primary")
        self.btn_remote.clicked.connect(self._open_selected_remote)

        self.btn_lock = QPushButton("Забанить")
        self.btn_lock.setProperty("accent", "warning")
        self.btn_lock.clicked.connect(lambda: self._run_on_selected("lock"))

        self.btn_unlock = QPushButton("Разбанить")
        self.btn_unlock.clicked.connect(lambda: self._run_on_selected("unlock"))

        self.btn_msg = QPushButton("Сообщение")
        self.btn_msg.clicked.connect(self._send_message_dialog)

        self.btn_ping = QPushButton("Пинг / Инфо")
        self.btn_ping.clicked.connect(lambda: self._run_on_selected("ping"))

        self.btn_power = QPushButton("Питание ▾")
        self.btn_power.setProperty("accent", "danger")
        self.btn_power.setMenu(self._build_power_menu())

        tb.addWidget(self.btn_remote)
        tb.addWidget(self.btn_lock)
        tb.addWidget(self.btn_unlock)
        tb.addWidget(self.btn_msg)
        tb.addWidget(self.btn_ping)
        tb.addWidget(self.btn_power)
        c_layout.addWidget(top_bar)

        # Stacked pages
        self.pages = QStackedWidget()

        # ---------- PAGE 0: Classroom Grid ----------
        grid_page = QWidget()
        grid_v = QVBoxLayout(grid_page)
        grid_v.setContentsMargins(20, 18, 20, 18)

        self.empty_hint = QLabel()
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setObjectName("MutedLabel")
        self.empty_hint.setStyleSheet("font-size: 14px; padding: 48px;")
        grid_v.addWidget(self.empty_hint)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_layout.setSpacing(16)
        self.scroll_area.setWidget(self.grid_widget)
        self.scroll_area.hide()
        grid_v.addWidget(self.scroll_area, stretch=1)
        self.pages.addWidget(grid_page)

        # ---------- PAGE 1: PowerShell + Saved Commands Library ----------
        ps_page = QWidget()
        ps_outer = QVBoxLayout(ps_page)
        ps_outer.setContentsMargins(20, 18, 20, 18)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left column: Saved Commands Library
        saved_panel = QFrame()
        saved_panel.setObjectName("SidebarCard")
        saved_panel.setMinimumWidth(260)
        saved_panel.setMaximumWidth(340)
        sp = QVBoxLayout(saved_panel)
        sp.setContentsMargins(12, 12, 12, 12)
        sp.setSpacing(8)

        sp_title = QLabel("СОХРАНЁННЫЕ КОМАНДЫ")
        sp_title.setObjectName("SectionLabel")
        sp.addWidget(sp_title)

        self.saved_cmd_list = QListWidget()
        self.saved_cmd_list.itemClicked.connect(self._on_saved_cmd_clicked)
        self.saved_cmd_list.itemDoubleClicked.connect(self._on_saved_cmd_double_clicked)
        sp.addWidget(self.saved_cmd_list, stretch=1)

        sp_btns = QHBoxLayout()
        sp_btns.setSpacing(6)
        save_cmd_btn = QPushButton("+ Сохранить")
        save_cmd_btn.setProperty("accent", "primary")
        save_cmd_btn.clicked.connect(self._save_current_ps_command)
        del_cmd_btn = QPushButton("Удалить")
        del_cmd_btn.clicked.connect(self._delete_selected_ps_command)
        sp_btns.addWidget(save_cmd_btn, stretch=1)
        sp_btns.addWidget(del_cmd_btn)
        sp.addLayout(sp_btns)

        run_saved_all_btn = QPushButton("Запустить выбранную на ВСЕХ")
        run_saved_all_btn.setProperty("accent", "success")
        run_saved_all_btn.clicked.connect(self._run_selected_saved_on_all)
        sp.addWidget(run_saved_all_btn)

        # Right column: Editor + Execution + Output
        exec_panel = QWidget()
        ep = QVBoxLayout(exec_panel)
        ep.setContentsMargins(14, 0, 0, 0)
        ep.setSpacing(10)

        target_row = QHBoxLayout()
        self.ps_target_combo = QComboBox()
        self.ps_target_combo.setMinimumWidth(280)
        self._refresh_ps_targets()
        target_row.addWidget(QLabel("Цель выполнения:"))
        target_row.addWidget(self.ps_target_combo)
        target_row.addStretch()
        ep.addLayout(target_row)

        self.ps_input = QPlainTextEdit()
        self.ps_input.setPlaceholderText(
            "Введите PowerShell-команду (например: Start-Process 'https://python.org') "
            "и нажмите «+ Сохранить», чтобы добавить в библиотеку слева..."
        )
        self.ps_input.setFixedHeight(96)
        self.ps_input.setStyleSheet('font-family: "Consolas", monospace; font-size: 13px;')
        ep.addWidget(self.ps_input)

        ps_btns = QHBoxLayout()
        run_ps_btn = QPushButton("Выполнить (цель)")
        run_ps_btn.setProperty("accent", "primary")
        run_ps_btn.clicked.connect(self._execute_powershell)
        run_all_ps_btn = QPushButton("Запустить на ВСЕХ ПК")
        run_all_ps_btn.setProperty("accent", "success")
        run_all_ps_btn.clicked.connect(self._execute_powershell_all)
        clear_ps_btn = QPushButton("Очистить вывод")
        clear_ps_btn.clicked.connect(lambda: self.ps_output.clear())
        ps_btns.addWidget(run_ps_btn)
        ps_btns.addWidget(run_all_ps_btn)
        ps_btns.addWidget(clear_ps_btn)
        ps_btns.addStretch()
        ep.addLayout(ps_btns)

        self.ps_output = QPlainTextEdit()
        self.ps_output.setObjectName("ConsoleBox")
        self.ps_output.setReadOnly(True)
        ep.addWidget(self.ps_output, stretch=1)

        splitter.addWidget(saved_panel)
        splitter.addWidget(exec_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        ps_outer.addWidget(splitter, stretch=1)
        self.pages.addWidget(ps_page)

        # ---------- PAGE 2: Audit Log ----------
        log_page = QWidget()
        log_v = QVBoxLayout(log_page)
        log_v.setContentsMargins(20, 18, 20, 18)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("ConsoleBox")
        self.log_view.setReadOnly(True)
        log_v.addWidget(self.log_view)
        self.pages.addWidget(log_page)

        c_layout.addWidget(self.pages, stretch=1)
        root.addWidget(content, stretch=1)

        self.setCentralWidget(central)
        self._refresh_saved_commands()
        self._refresh_header_labels()
        self._update_toolbar_state()

    def _make_nav_btn(self, text: str, page_index: int, checked: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("NavButton")
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self._switch_page(page_index, text))
        self.nav_group.addButton(btn, page_index)
        return btn

    def _switch_page(self, page_index: int, title: str) -> None:
        self.pages.setCurrentIndex(page_index)
        self.page_title_lbl.setText(title)

    def _toggle_theme(self) -> None:
        self.config.theme = "light" if self.config.theme == "dark" else "dark"
        save_config(self.config_path, self.config)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(get_stylesheet(self.config.theme))
        self._update_theme_button_text()

    def _update_theme_button_text(self) -> None:
        if self.config.theme == "dark":
            self.theme_btn.setText("Светлая тема")
        else:
            self.theme_btn.setText("Тёмная тема")

    def _copy_class_secret(self) -> None:
        QApplication.clipboard().setText(self.config.class_secret)
        self.statusBar().showMessage("Ключ класса скопирован в буфер обмена", 3000)

    def _build_power_menu(self) -> QMenu:
        menu = QMenu(self)
        items = [
            ("lock_os", False, "Выбранный ПК: Заблокировать Windows"),
            ("reboot", False, "Выбранный ПК: Перезагрузить"),
            ("shutdown", False, "Выбранный ПК: Выключить"),
            ("cancel_shutdown", False, "Выбранный ПК: Отменить выключение"),
            ("sep", False, ""),
            ("lock_os", True, "ВЕСЬ КЛАСС: Заблокировать Windows"),
            ("reboot", True, "ВЕСЬ КЛАСС: Перезагрузить все ПК"),
            ("shutdown", True, "ВЕСЬ КЛАСС: Выключить все ПК"),
            ("cancel_shutdown", True, "ВЕСЬ КЛАСС: Отменить выключение"),
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

    async def start_server(self) -> None:
        try:
            await self.server.start()
            self._refresh_header_labels()
            self.statusBar().showMessage(
                f"Сервер активен  •  TLS-порт {self.server.bound_port}  •  "
                f"Автопоиск LAN {'ВКЛ' if self.config.discovery_enabled else 'ВЫКЛ'}"
            )
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Ошибка запуска сервера",
                f"Не удалось открыть порт {self.config.tcp_port}:\n{exc}",
            )

    def _refresh_header_labels(self) -> None:
        ips = ", ".join(get_local_ipv4_addresses())
        online = len(self.server.clients)
        self.online_pill.setText(f"{online} онлайн")
        self.room_sub_lbl.setText(f"Кабинет: {self.config.classroom_id}")
        secret_disp = self.config.class_secret if self.secret_toggle_btn.isChecked() else "••••••••••••"
        self.net_info_lbl.setText(
            f"IP учителя: {ips}\n"
            f"Порт: {self.server.bound_port}  •  Ключ: {secret_disp}"
        )
        self.empty_hint.setText(
            f"Ожидание подключения учеников\n\n"
            f"Запустите ClassroomStudent.exe на компьютерах класса:\n"
            f"ID кабинета: {self.config.classroom_id}  •  LAN IP учителя: {ips}\n"
            f"Автопоиск работает автоматически (статический IP не требуется)."
        )

    def _relayout_grid(self) -> None:
        while self.grid_layout.count():
            self.grid_layout.takeAt(0)

        avail_w = max(340, self.width() - 300)
        cols = max(1, avail_w // 334)
        for idx, card in enumerate(self.cards.values()):
            r, c = divmod(idx, cols)
            self.grid_layout.addWidget(card, r, c)

        has_clients = bool(self.cards)
        self.empty_hint.setVisible(not has_clients)
        self.scroll_area.setVisible(has_clients)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.cards:
            self._relayout_grid()

    def _on_client_connected(self, session: StudentSession) -> None:
        card = self.cards.get(session.client_id)
        if card is None:
            card = StudentCardWidget(session)
            card.clicked.connect(self._select_client)
            card.double_clicked.connect(self._open_remote_for)
            card.context_action.connect(self._handle_card_action)
            self.cards[session.client_id] = card
        else:
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

    def _update_toolbar_state(self) -> None:
        has_sel = self.selected_client_id in self.server.clients
        has_any = bool(self.server.clients)
        self.btn_remote.setEnabled(has_sel)
        self.btn_lock.setEnabled(has_sel)
        self.btn_unlock.setEnabled(has_sel)
        self.btn_ping.setEnabled(has_sel)
        self.btn_lock_all.setEnabled(has_any)
        self.btn_unlock_all.setEnabled(has_any)
        self.btn_demo.setEnabled(has_any or self.btn_demo.isChecked())
        self.btn_files.setEnabled(has_any)
        self.btn_msg.setEnabled(has_any)
        self.btn_power.setEnabled(has_any)

    def _refresh_ps_targets(self) -> None:
        current = self.ps_target_combo.currentData()
        self.ps_target_combo.clear()
        self.ps_target_combo.addItem("Весь класс (все онлайн-ПК)", "__ALL__")
        for cid, s in self.server.clients.items():
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
            asyncio.create_task(self._run_ps_async("__ALL__", script))

    def _run_selected_saved_on_all(self) -> None:
        item = self.saved_cmd_list.currentItem()
        if item is None:
            self._execute_powershell_all()
            return
        script = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if script:
            self.ps_input.setPlainText(script)
            asyncio.create_task(self._run_ps_async("__ALL__", script))

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
            "Название команды (сохранится навсегда):",
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
        if checked:
            self.btn_demo.setText("Остановить показ")
            self.btn_demo.setProperty("accent", "danger")
            mon = int(self.demo_mon_combo.currentData() or 1)
            self.statusBar().showMessage("Идёт HD-демонстрация экрана учителя всем ученикам")
            asyncio.create_task(self.server.start_demo_broadcast(monitor=mon))
        else:
            self.btn_demo.setText("Демонстрация экрана")
            self.btn_demo.setProperty("accent", "primary")
            self.statusBar().showMessage("Демонстрация экрана остановлена", 4000)
            asyncio.create_task(self.server.stop_demo_broadcast())
        self.btn_demo.style().unpolish(self.btn_demo)
        self.btn_demo.style().polish(self.btn_demo)

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
            asyncio.create_task(self.server.lock_screen(client_id, "(срок бана: 1000 лет)"))
        elif action == "unlock":
            asyncio.create_task(self.server.unlock_screen(client_id))
        elif action == "send_file":
            self._open_file_transfer(preselected_id=client_id)
        elif action == "message":
            self._send_message_dialog(target_id=client_id)
        elif action == "powershell":
            self.nav_commands.setChecked(True)
            self._switch_page(1, "Команды (PowerShell)")
            idx = self.ps_target_combo.findData(client_id)
            if idx >= 0:
                self.ps_target_combo.setCurrentIndex(idx)
            self.ps_input.setFocus()
        elif action == "ping":
            asyncio.create_task(self._ping_and_show_info(client_id))
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
        asyncio.create_task(self._broadcast_lock(True))

    def _unlock_all_students(self) -> None:
        asyncio.create_task(self._broadcast_lock(False))

    async def _broadcast_lock(self, lock: bool) -> None:
        for cid in list(self.server.clients.keys()):
            if lock:
                await self.server.lock_screen(cid, "(срок бана: 1000 лет)")
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
        mon_text = ", ".join(m.get("name", "") for m in mons) if mons else f"{d.get('screen_width')}×{d.get('screen_height')}"
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
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Отправить сообщение",
            "Текст сообщения для ученика" + (" (или всего класса):" if not target_id else ":"),
        )
        if not ok or not text.strip():
            return
        if target_id:
            asyncio.create_task(self.server.show_message(target_id, "Сообщение от учителя", text.strip()))
        else:
            asyncio.create_task(
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
        if not all_students and not target_id:
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
            asyncio.create_task(self.server.broadcast_command("POWER_ACTION", {"action": action}))
        elif target_id:
            asyncio.create_task(self.server.power_action(target_id, action))

    def _execute_powershell(self) -> None:
        script = self.ps_input.toPlainText().strip()
        if not script:
            return
        target = self.ps_target_combo.currentData()
        if not target:
            return
        asyncio.create_task(self._run_ps_async(target, script))

    def _execute_powershell_all(self) -> None:
        script = self.ps_input.toPlainText().strip()
        if not script:
            return
        asyncio.create_task(self._run_ps_async("__ALL__", script))

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
            self.setWindowTitle(f"Classroom Manager — {self.config.classroom_id}")
            self._refresh_header_labels()
            if dlg.network_restart_needed:
                asyncio.create_task(self._restart_server())

    async def _restart_server(self) -> None:
        await self.server.stop()
        await self.start_server()

    def closeEvent(self, event) -> None:
        for dlg in list(self.remote_dialogs.values()):
            dlg.close()
        asyncio.create_task(self.server.stop())
        super().closeEvent(event)
