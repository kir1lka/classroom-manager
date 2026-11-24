"""Main Teacher console window: live screen grid, controls, PowerShell, and audit log."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from shared.config import TeacherConfig, save_config
from shared.protocol import ScreenMode
from teacher_app.network.discovery import get_local_ipv4_addresses
from teacher_app.network.server import StudentSession, TeacherServer
from teacher_app.ui.dialogs import TeacherSettingsDialog
from teacher_app.ui.remote_view import RemoteControlDialog
from teacher_app.ui.theme import make_status_icon


class ServerSignals(QObject):
    """Qt signal bridge for callbacks invoked by TeacherServer."""

    client_connected = Signal(object)
    client_disconnected = Signal(str)
    client_updated = Signal(object)
    screen_frame = Signal(str, int, int, int, bytes)
    log_line = Signal(str)


class StudentCardWidget(QFrame):
    """Interactive card showing one student's live thumbnail and status."""

    clicked = Signal(str)
    double_clicked = Signal(str)
    context_action = Signal(str, str)

    def __init__(self, session: StudentSession, parent=None) -> None:
        super().__init__(parent)
        self.client_id = session.client_id
        self.setObjectName("StudentCard")
        self.setFixedSize(310, 255)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # Header row
        top = QHBoxLayout()
        self.title_lbl = QLabel(session.label)
        self.title_lbl.setStyleSheet("font-weight: 700; font-size: 13px; background: transparent;")
        self.badge_lbl = QLabel("ONLINE")
        self.badge_lbl.setStyleSheet(
            "background-color: #065f46; color: #a7f3d0; padding: 2px 7px; "
            "border-radius: 4px; font-size: 11px; font-weight: 700;"
        )
        top.addWidget(self.title_lbl, stretch=1)
        top.addWidget(self.badge_lbl)
        layout.addLayout(top)

        # Screen preview
        self.preview_lbl = QLabel("Загрузка экрана...")
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lbl.setFixedSize(288, 162)
        self.preview_lbl.setStyleSheet(
            "background-color: #020617; color: #64748b; border-radius: 6px; border: 1px solid #334155;"
        )
        layout.addWidget(self.preview_lbl)

        # Footer meta
        self.meta_lbl = QLabel()
        self.meta_lbl.setStyleSheet("color: #94a3b8; font-size: 11px; background: transparent;")
        self.window_lbl = QLabel()
        self.window_lbl.setStyleSheet("color: #cbd5e1; font-size: 11px; background: transparent;")
        layout.addWidget(self.meta_lbl)
        layout.addWidget(self.window_lbl)

        self.update_session(session)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def update_session(self, session: StudentSession) -> None:
        self.title_lbl.setText(session.label)
        ping_str = f" | {session.last_ping_ms:.0f} мс" if session.last_ping_ms is not None else ""
        self.meta_lbl.setText(f"{session.username} @ {session.ip}{ping_str}")
        win = session.active_window.strip()
        self.window_lbl.setText((win[:42] + "…") if len(win) > 43 else (win or "Рабочий стол"))

        self.setProperty("locked", "true" if session.locked else "false")
        if session.locked:
            self.badge_lbl.setText("ЗАБЛОКИРОВАН")
            self.badge_lbl.setStyleSheet(
                "background-color: #991b1b; color: #fecaca; padding: 2px 7px; "
                "border-radius: 4px; font-size: 11px; font-weight: 700;"
            )
        else:
            self.badge_lbl.setText("ONLINE")
            self.badge_lbl.setStyleSheet(
                "background-color: #065f46; color: #a7f3d0; padding: 2px 7px; "
                "border-radius: 4px; font-size: 11px; font-weight: 700;"
            )
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
            ("control", "Просмотр и управление ПК"),
            ("lock", "Заблокировать экран (внимание)"),
            ("unlock", "Разблокировать экран"),
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
            act.triggered.connect(lambda _checked=False, k=key: self.context_action.emit(self.client_id, k))
            menu.addAction(act)
        menu.exec(event.globalPos())


class TeacherMainWindow(QMainWindow):
    """Main desktop dashboard for the Teacher application."""

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

        self.setWindowTitle(f"Classroom Manager — Панель учителя ({config.classroom_id})")
        self.setWindowIcon(make_status_icon("#2563eb"))
        self.resize(1240, 780)

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
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header Bar
        header = QFrame()
        header.setObjectName("HeaderBar")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 10, 16, 10)

        self.room_info_lbl = QLabel()
        self.room_info_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc; background: transparent;")
        self.net_info_lbl = QLabel()
        self.net_info_lbl.setStyleSheet("color: #94a3b8; background: transparent;")

        self.secret_toggle_btn = QPushButton("Показать ключ класса")
        self.secret_toggle_btn.setCheckable(True)
        self.secret_toggle_btn.toggled.connect(self._refresh_header_labels)

        settings_btn = QPushButton("Настройки")
        settings_btn.clicked.connect(self._open_settings)

        h_layout.addWidget(self.room_info_lbl)
        h_layout.addSpacing(16)
        h_layout.addWidget(self.net_info_lbl, stretch=1)
        h_layout.addWidget(self.secret_toggle_btn)
        h_layout.addWidget(settings_btn)
        root.addWidget(header)

        # Action Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(16, 10, 16, 6)
        toolbar.setSpacing(8)

        self.btn_remote = QPushButton("Управление ПК")
        self.btn_remote.setProperty("accent", "primary")
        self.btn_remote.clicked.connect(self._open_selected_remote)

        self.btn_lock = QPushButton("Блок экрана")
        self.btn_lock.setProperty("accent", "warning")
        self.btn_lock.clicked.connect(lambda: self._run_on_selected("lock"))

        self.btn_unlock = QPushButton("Разблок.")
        self.btn_unlock.setProperty("accent", "success")
        self.btn_unlock.clicked.connect(lambda: self._run_on_selected("unlock"))

        self.btn_lock_all = QPushButton("Блок ВСЕХ")
        self.btn_lock_all.clicked.connect(self._lock_all_students)

        self.btn_unlock_all = QPushButton("Разблок. ВСЕХ")
        self.btn_unlock_all.clicked.connect(self._unlock_all_students)

        self.btn_msg = QPushButton("Сообщение")
        self.btn_msg.clicked.connect(self._send_message_dialog)

        self.btn_ping = QPushButton("Пинг / Инфо")
        self.btn_ping.clicked.connect(lambda: self._run_on_selected("ping"))

        self.btn_power = QPushButton("Питание ▾")
        self.btn_power.setProperty("accent", "danger")
        self.btn_power.setMenu(self._build_power_menu())

        toolbar.addWidget(self.btn_remote)
        toolbar.addWidget(self.btn_lock)
        toolbar.addWidget(self.btn_unlock)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.btn_lock_all)
        toolbar.addWidget(self.btn_unlock_all)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.btn_msg)
        toolbar.addWidget(self.btn_ping)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_power)
        root.addLayout(toolbar)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setContentsMargins(12, 6, 12, 12)

        # Tab 1: Classroom Screens Grid
        grid_container = QWidget()
        grid_v = QVBoxLayout(grid_container)
        grid_v.setContentsMargins(12, 12, 12, 12)

        self.empty_hint = QLabel()
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setStyleSheet("color: #94a3b8; font-size: 14px; padding: 40px;")
        grid_v.addWidget(self.empty_hint)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_layout.setSpacing(14)
        self.scroll_area.setWidget(self.grid_widget)
        self.scroll_area.hide()
        grid_v.addWidget(self.scroll_area, stretch=1)

        self.tabs.addTab(grid_container, "Класс (Экраны)")

        # Tab 2: PowerShell Console
        ps_tab = QWidget()
        ps_layout = QVBoxLayout(ps_tab)
        ps_layout.setContentsMargins(12, 12, 12, 12)

        ps_top = QHBoxLayout()
        self.ps_target_combo = QComboBox()
        self.ps_target_combo.setMinimumWidth(260)
        self._refresh_ps_targets()

        self.ps_preset_combo = QComboBox()
        self.ps_preset_combo.addItem("Быстрые команды (шаблоны)...", "")
        self.ps_preset_combo.addItem("Имя ПК, пользователь и IP", "hostname; whoami; (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '127.*'}).IPAddress")
        self.ps_preset_combo.addItem("Топ-10 процессов по памяти", "Get-Process | Sort-Object WS -Descending | Select-Object -First 10 Name, Id, @{N='MB';E={[math]::Round($_.WS/1MB,1)}} | Format-Table -AutoSize")
        self.ps_preset_combo.addItem("Закрыть браузеры (Chrome/Edge)", "Stop-Process -Name chrome,msedge -Force -ErrorAction SilentlyContinue; 'Готово'")
        self.ps_preset_combo.addItem("Проверить время работы ПК", "(Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime")
        self.ps_preset_combo.currentIndexChanged.connect(self._apply_ps_preset)

        ps_top.addWidget(QLabel("Цель:"))
        ps_top.addWidget(self.ps_target_combo)
        ps_top.addSpacing(12)
        ps_top.addWidget(self.ps_preset_combo, stretch=1)
        ps_layout.addLayout(ps_top)

        self.ps_input = QPlainTextEdit()
        self.ps_input.setPlaceholderText("Введите PowerShell-команду, например: Get-Date; hostname")
        self.ps_input.setFixedHeight(85)
        self.ps_input.setStyleSheet('font-family: "Consolas", monospace; font-size: 13px;')
        ps_layout.addWidget(self.ps_input)

        ps_btns = QHBoxLayout()
        run_ps_btn = QPushButton("Выполнить PowerShell")
        run_ps_btn.setProperty("accent", "primary")
        run_ps_btn.clicked.connect(self._execute_powershell)
        clear_ps_btn = QPushButton("Очистить вывод")
        clear_ps_btn.clicked.connect(lambda: self.ps_output.clear())
        ps_btns.addWidget(run_ps_btn)
        ps_btns.addWidget(clear_ps_btn)
        ps_btns.addStretch()
        ps_layout.addLayout(ps_btns)

        self.ps_output = QPlainTextEdit()
        self.ps_output.setReadOnly(True)
        self.ps_output.setStyleSheet(
            'background-color: #020617; color: #e2e8f0; font-family: "Consolas", monospace; font-size: 12px;'
        )
        ps_layout.addWidget(self.ps_output, stretch=1)

        self.tabs.addTab(ps_tab, "PowerShell")

        # Tab 3: Audit Log
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_layout.setContentsMargins(12, 12, 12, 12)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            'background-color: #020617; color: #94a3b8; font-family: "Consolas", monospace; font-size: 12px;'
        )
        log_layout.addWidget(self.log_view)
        self.tabs.addTab(log_tab, "Журнал (Аудит)")

        tab_wrap = QVBoxLayout()
        tab_wrap.setContentsMargins(12, 4, 12, 12)
        tab_wrap.addWidget(self.tabs)
        root.addLayout(tab_wrap, stretch=1)

        self.setCentralWidget(central)
        self._refresh_header_labels()
        self._update_toolbar_state()

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
                f"Сервер запущен (TLS порт {self.server.bound_port}, "
                f"автопоиск {'ВКЛ' if self.config.discovery_enabled else 'ВЫКЛ'})"
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
        self.room_info_lbl.setText(f"Кабинет: {self.config.classroom_id}   |   Онлайн: {online}")
        secret_disp = self.config.class_secret if self.secret_toggle_btn.isChecked() else "••••••••••••"
        self.net_info_lbl.setText(
            f"LAN IP учителя: {ips}  |  TLS-порт: {self.server.bound_port}  |  Ключ: {secret_disp}"
        )
        self.empty_hint.setText(
            f"Пока нет подключённых учеников.\n\n"
            f"Запустите Classroom Student на ПК учеников и укажите:\n"
            f"ID кабинета: {self.config.classroom_id}\n"
            f"Автопоиск по LAN работает автоматически (статический IP не требуется).\n"
            f"Текущий LAN IP учителя: {ips}"
        )

    def _relayout_grid(self) -> None:
        while self.grid_layout.count():
            self.grid_layout.takeAt(0)

        cols = max(1, (self.width() - 60) // 330)
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

    def _on_screen_frame(self, client_id: str, _w: int, _h: int, mode_int: int, jpeg_bytes: bytes) -> None:
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

    def _apply_ps_preset(self, idx: int) -> None:
        cmd = self.ps_preset_combo.itemData(idx)
        if cmd:
            self.ps_input.setPlainText(cmd)

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
        dlg.show()

    def _handle_card_action(self, client_id: str, action: str) -> None:
        if action == "control":
            self._open_remote_for(client_id)
        elif action == "lock":
            asyncio.create_task(self.server.lock_screen(client_id))
        elif action == "unlock":
            asyncio.create_task(self.server.unlock_screen(client_id))
        elif action == "message":
            self._send_message_dialog(target_id=client_id)
        elif action == "powershell":
            self.tabs.setCurrentIndex(1)
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
                await self.server.lock_screen(cid)
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
        QMessageBox.information(
            self,
            f"Системная информация — {d.get('hostname', client_id)}",
            f"Пинг: {rtt} мс\n"
            f"Имя ПК: {d.get('hostname')}\n"
            f"Пользователь: {d.get('username')}\n"
            f"ОС: {d.get('os')}\n"
            f"Ядра CPU: {d.get('cpu_count')}\n"
            f"Экран: {d.get('screen_width')}x{d.get('screen_height')}\n"
            f"Активное окно: {d.get('active_window') or '—'}",
        )

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
            self.setWindowTitle(f"Classroom Manager — Панель учителя ({self.config.classroom_id})")
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
