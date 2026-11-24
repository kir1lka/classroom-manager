"""Password gate and settings dialog for the Student tray agent (Liquid Glass UI)."""

from __future__ import annotations

import socket

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from shared.config import StudentConfig
from shared.security import hash_password, verify_password
from student_app.ui.hotkey import parse_hotkey_string
from teacher_app.ui.theme import (
    GlassFrame,
    LiquidDialog,
    make_app_icon,
    make_icon,
    render_app_icon_pixmap,
)


def _make_eye_toggle(*edits: QLineEdit) -> QPushButton:
    """Create a compact Liquid Glass show/hide password button (#IconPill)."""
    btn = QPushButton()
    btn.setObjectName("IconPill")
    btn.setCheckable(True)
    btn.setFixedSize(34, 34)
    btn.setIconSize(QSize(16, 16))
    btn.setIcon(make_icon("eye", size=16))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setAutoDefault(False)
    btn.setDefault(False)
    btn.setToolTip("Показать или скрыть значение")

    def _on_toggled(checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        for edit in edits:
            edit.setEchoMode(mode)
        btn.setIcon(make_icon("eye_off" if checked else "eye", size=16))

    btn.toggled.connect(_on_toggled)
    return btn


def _format_status_badge(status_text: str) -> tuple[str, str]:
    """Return (badge_object_name, formatted_russian_text) for live agent status."""
    raw = status_text.strip()
    upper = raw.upper()

    is_online = "CONNECTED" in upper or "ПОДКЛЮЧЕН" in upper
    badge_id = "OnlineBadge" if is_online else "AccentBadge"

    state_map = {
        "CONNECTED": "Подключено",
        "DISCOVERING": "Поиск учителя",
        "CONNECTING": "Подключение",
        "AUTHENTICATING": "Проверка ключа",
        "RECONNECTING": "Переподключение",
        "AUTH_ERROR": "Ошибка ключа",
        "UNCONFIGURED": "Не настроен",
        "STOPPED": "Остановлен",
    }
    for code, rus in state_map.items():
        if raw == code:
            return badge_id, f"● {rus}"
        prefix = f"{code} — "
        if raw.startswith(prefix):
            detail = raw[len(prefix) :].strip()
            if detail and detail.lower() != rus.lower():
                short = (detail[:28] + "…") if len(detail) > 29 else detail
                return badge_id, f"● {short}"
            return badge_id, f"● {rus}"

    return badge_id, raw if raw.startswith("●") else f"● {raw}"


class StudentPasswordPrompt(LiquidDialog):
    """Modal Liquid Glass security gate protecting Student settings and agent exit."""

    def __init__(
        self,
        password_hash: str,
        action_title: str = "Доступ к настройкам агента",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._password_hash = password_hash
        self.setWindowTitle("Требуется пароль учителя")
        self.setWindowIcon(make_app_icon("student"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedWidth(410)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(16)

        # Header with frosted shield badge + title + muted subtitle
        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        badge_lbl = QLabel()
        badge_lbl.setFixedSize(42, 42)
        badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_lbl.setPixmap(make_icon("shield", "#0A84FF", 22).pixmap(22, 22))
        badge_lbl.setStyleSheet(
            "background-color: rgba(10, 132, 255, 0.16); "
            "border: 1px solid rgba(56, 166, 255, 0.40); "
            "border-radius: 13px;"
        )
        header_row.addWidget(badge_lbl, alignment=Qt.AlignmentFlag.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title_lbl = QLabel(action_title)
        title_lbl.setObjectName("DialogTitle")
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet("font-size: 16px; font-weight: 700;")

        hint_lbl = QLabel("Для изменения параметров введите пароль администратора")
        hint_lbl.setObjectName("MutedLabel")
        hint_lbl.setWordWrap(True)

        title_col.addWidget(title_lbl)
        title_col.addWidget(hint_lbl)
        header_row.addLayout(title_col, stretch=1)
        root.addLayout(header_row)

        # Glass card containing password input + show/hide toggle + error feedback
        card = GlassFrame(variant="card", radius=16, parent=self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 15, 16, 15)
        card_layout.setSpacing(8)

        field_lbl = QLabel("ПАРОЛЬ АДМИНИСТРАТОРА")
        field_lbl.setObjectName("SectionLabel")
        card_layout.addWidget(field_lbl)

        pwd_row = QHBoxLayout()
        pwd_row.setSpacing(8)
        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_edit.setPlaceholderText("Введите пароль администратора / учителя")
        self.pwd_edit.returnPressed.connect(self._verify)
        self.pwd_edit.textChanged.connect(self._clear_error)

        self.eye_btn = _make_eye_toggle(self.pwd_edit)
        pwd_row.addWidget(self.pwd_edit, stretch=1)
        pwd_row.addWidget(self.eye_btn)
        card_layout.addLayout(pwd_row)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet("color: #FF453A; font-size: 12px; font-weight: 600;")
        self.err_lbl.setVisible(False)
        card_layout.addWidget(self.err_lbl)

        root.addWidget(card)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setAutoDefault(False)
        cancel_btn.setDefault(False)
        cancel_btn.clicked.connect(self.reject)

        ok_btn = QPushButton("Подтвердить")
        ok_btn.setProperty("accent", "primary")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._verify)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

        self.pwd_edit.setFocus()

    def _clear_error(self) -> None:
        if self.err_lbl.text():
            self.err_lbl.clear()
            self.err_lbl.setVisible(False)

    def _verify(self) -> None:
        if verify_password(self.pwd_edit.text(), self._password_hash):
            self.accept()
        else:
            self.err_lbl.setText("Неверный пароль администратора.")
            self.err_lbl.setVisible(True)
            self.pwd_edit.selectAll()
            self.pwd_edit.setFocus()


class StudentSettingsDialog(LiquidDialog):
    """First-run setup or password-authenticated Liquid Glass settings editor for StudentApp."""

    def __init__(
        self,
        config: StudentConfig,
        first_run: bool = False,
        status_text: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.first_run = first_run
        self.exit_requested = False
        self.unlock_requested = False

        self.setWindowTitle(
            "Первичная настройка агента" if first_run else "Настройки рабочего места"
        )
        self.setWindowIcon(make_app_icon("student"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(650)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        # ── Modern Header ────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(14)

        app_badge = QLabel()
        app_badge.setFixedSize(42, 42)
        hi_pm = render_app_icon_pixmap(role="student", size=84)
        hi_pm.setDevicePixelRatio(2.0)
        app_badge.setPixmap(hi_pm)
        header.addWidget(app_badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        title_stack = QVBoxLayout()
        title_stack.setSpacing(2)
        hdr_title = QLabel(
            "Первичная настройка агента" if first_run else "Настройки рабочего места"
        )
        hdr_title.setObjectName("DialogTitle")
        hdr_sub = QLabel(
            "Укажите параметры класса и задайте пароль защиты агента"
            if first_run
            else "Параметры подключения к классу и локальной безопасности"
        )
        hdr_sub.setObjectName("PageSubtitle")
        title_stack.addWidget(hdr_title)
        title_stack.addWidget(hdr_sub)
        header.addLayout(title_stack, stretch=1)

        if status_text:
            badge_obj, badge_label = _format_status_badge(status_text)
            status_pill = QLabel(badge_label)
            status_pill.setObjectName(badge_obj)
            header.addWidget(status_pill, alignment=Qt.AlignmentFlag.AlignVCenter)

        root.addLayout(header)

        # ── Section 1: Подключение к классу ──────────────────────────────────
        conn_card = GlassFrame(variant="card", radius=16, parent=self)
        conn_vbox = QVBoxLayout(conn_card)
        conn_vbox.setContentsMargins(18, 16, 18, 16)
        conn_vbox.setSpacing(12)

        conn_hdr = QHBoxLayout()
        conn_hdr.setSpacing(8)
        conn_icon = QLabel()
        conn_icon.setPixmap(make_icon("cast", "#0A84FF", 16).pixmap(16, 16))
        conn_title = QLabel("Подключение к классу")
        conn_title.setObjectName("CardSectionTitle")
        conn_tag = QLabel("UDP + TLS")
        conn_tag.setObjectName("MonBadge")
        conn_hdr.addWidget(conn_icon)
        conn_hdr.addWidget(conn_title)
        conn_hdr.addStretch()
        conn_hdr.addWidget(conn_tag)
        conn_vbox.addLayout(conn_hdr)

        conn_form = QFormLayout()
        conn_form.setContentsMargins(0, 2, 0, 0)
        conn_form.setHorizontalSpacing(14)
        conn_form.setVerticalSpacing(10)
        conn_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.room_edit = QLineEdit(config.classroom_id or "Cab-101")
        self.room_edit.setPlaceholderText("Например: Cab-101")

        self.secret_edit = QLineEdit(config.class_secret)
        self.secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret_edit.setPlaceholderText("Ключ класса из приложения учителя")
        secret_row = QWidget()
        secret_hbox = QHBoxLayout(secret_row)
        secret_hbox.setContentsMargins(0, 0, 0, 0)
        secret_hbox.setSpacing(8)
        secret_hbox.addWidget(self.secret_edit, stretch=1)
        secret_hbox.addWidget(_make_eye_toggle(self.secret_edit))

        self.name_edit = QLineEdit(config.display_name)
        self.name_edit.setPlaceholderText(f"По умолчанию: {socket.gethostname()}")

        self.disc_check = QCheckBox(
            "Автопоиск учителя в сети LAN (UDP Broadcast, без статики IP)"
        )
        self.disc_check.setChecked(config.discovery_enabled)

        self.disc_port_spin = QSpinBox()
        self.disc_port_spin.setRange(1024, 65535)
        self.disc_port_spin.setValue(config.discovery_port)

        self.manual_port_spin = QSpinBox()
        self.manual_port_spin.setRange(1024, 65535)
        self.manual_port_spin.setValue(config.manual_port)

        ports_row = QWidget()
        ports_hbox = QHBoxLayout(ports_row)
        ports_hbox.setContentsMargins(0, 0, 0, 0)
        ports_hbox.setSpacing(10)
        udp_lbl = QLabel("UDP поиск:")
        udp_lbl.setObjectName("MutedLabel")
        tcp_lbl = QLabel("TLS TCP:")
        tcp_lbl.setObjectName("MutedLabel")
        ports_hbox.addWidget(udp_lbl)
        ports_hbox.addWidget(self.disc_port_spin, stretch=1)
        ports_hbox.addSpacing(8)
        ports_hbox.addWidget(tcp_lbl)
        ports_hbox.addWidget(self.manual_port_spin, stretch=1)

        self.manual_host_edit = QLineEdit(config.manual_host)
        self.manual_host_edit.setPlaceholderText("Необязательно: резервный IP или имя ПК учителя")

        self.fp_edit = QLineEdit(config.pinned_fingerprint)
        self.fp_edit.setPlaceholderText("Необязательно: SHA-256 отпечаток TLS-сертификата")

        conn_form.addRow("ID кабинета:", self.room_edit)
        conn_form.addRow("Ключ класса (PSK):", secret_row)
        conn_form.addRow("Имя парты / ПК:", self.name_edit)
        conn_form.addRow("", self.disc_check)
        conn_form.addRow("Сетевые порты:", ports_row)
        conn_form.addRow("Резервный IP / ПК:", self.manual_host_edit)
        conn_form.addRow("TLS SHA-256 pin:", self.fp_edit)
        conn_vbox.addLayout(conn_form)
        root.addWidget(conn_card)

        # ── Section 2: Безопасность и управление ─────────────────────────────
        sec_card = GlassFrame(variant="card", radius=16, parent=self)
        sec_vbox = QVBoxLayout(sec_card)
        sec_vbox.setContentsMargins(18, 16, 18, 16)
        sec_vbox.setSpacing(12)

        sec_hdr = QHBoxLayout()
        sec_hdr.setSpacing(8)
        sec_icon = QLabel()
        sec_icon.setPixmap(make_icon("shield", "#30D158", 16).pixmap(16, 16))
        sec_title = QLabel("Безопасность и управление")
        sec_title.setObjectName("CardSectionTitle")
        sec_hdr.addWidget(sec_icon)
        sec_hdr.addWidget(sec_title)
        sec_hdr.addStretch()
        sec_vbox.addLayout(sec_hdr)

        sec_form = QFormLayout()
        sec_form.setContentsMargins(0, 2, 0, 0)
        sec_form.setHorizontalSpacing(14)
        sec_form.setVerticalSpacing(10)
        sec_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.hotkey_edit = QLineEdit(config.hotkey or "Ctrl+Alt+Shift+M")
        self.hotkey_edit.setPlaceholderText("Например: Ctrl+Alt+Shift+M")

        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_edit.setPlaceholderText(
            "Минимум 4 символа" if first_run else "Оставьте пустым, чтобы не менять"
        )

        self.pwd_confirm = QLineEdit()
        self.pwd_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_confirm.setPlaceholderText("Повторите пароль администратора")

        pwd_row = QWidget()
        pwd_hbox = QHBoxLayout(pwd_row)
        pwd_hbox.setContentsMargins(0, 0, 0, 0)
        pwd_hbox.setSpacing(8)
        pwd_hbox.addWidget(self.pwd_edit, stretch=1)
        pwd_hbox.addWidget(_make_eye_toggle(self.pwd_edit, self.pwd_confirm))

        sec_form.addRow("Горячая клавиша:", self.hotkey_edit)
        sec_form.addRow(
            "Пароль админа:" if first_run else "Новый пароль:",
            pwd_row,
        )
        sec_form.addRow("Подтверждение:", self.pwd_confirm)
        sec_vbox.addLayout(sec_form)
        root.addWidget(sec_card)

        # ── Bottom Action Bar ────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        if not first_run:
            exit_btn = QPushButton("Остановить агент")
            exit_btn.setIcon(make_icon("power", "#FFFFFF", 15))
            exit_btn.setProperty("accent", "danger")
            exit_btn.setAutoDefault(False)
            exit_btn.setDefault(False)
            exit_btn.clicked.connect(self._on_exit_agent)
            btn_row.addWidget(exit_btn)

            unlock_btn = QPushButton("Снять блок экрана")
            unlock_btn.setIcon(make_icon("unlock", size=15))
            unlock_btn.setAutoDefault(False)
            unlock_btn.setDefault(False)
            unlock_btn.clicked.connect(self._on_unlock_local)
            btn_row.addWidget(unlock_btn)

        btn_row.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setAutoDefault(False)
        cancel_btn.setDefault(False)
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("Сохранить и подключиться" if first_run else "Сохранить")
        save_btn.setProperty("accent", "primary")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    def _on_exit_agent(self) -> None:
        self.exit_requested = True
        self.accept()

    def _on_unlock_local(self) -> None:
        self.unlock_requested = True
        self.accept()

    def _on_save(self) -> None:
        room = self.room_edit.text().strip()
        secret = self.secret_edit.text().strip()
        hotkey = self.hotkey_edit.text().strip()

        if not room:
            QMessageBox.warning(self, "Ошибка", "Укажите ID кабинета (как у учителя).")
            return
        if len(secret) < 6:
            QMessageBox.warning(self, "Ошибка", "Укажите ключ класса (не короче 6 символов).")
            return
        if parse_hotkey_string(hotkey) is None:
            QMessageBox.warning(
                self, "Ошибка", "Некорректная горячая клавиша. Пример: Ctrl+Alt+Shift+M"
            )
            return

        pwd = self.pwd_edit.text()
        confirm = self.pwd_confirm.text()
        if self.first_run or pwd or confirm:
            if len(pwd) < 4:
                QMessageBox.warning(
                    self, "Ошибка", "Пароль администратора должен быть не короче 4 символов."
                )
                return
            if pwd != confirm:
                QMessageBox.warning(self, "Ошибка", "Пароли не совпадают.")
                return
            self.config.admin_password_hash = hash_password(pwd)

        self.config.classroom_id = room
        self.config.class_secret = secret
        self.config.display_name = self.name_edit.text().strip()
        self.config.discovery_enabled = self.disc_check.isChecked()
        self.config.discovery_port = self.disc_port_spin.value()
        self.config.manual_host = self.manual_host_edit.text().strip()
        self.config.manual_port = self.manual_port_spin.value()
        self.config.pinned_fingerprint = self.fp_edit.text().strip()
        self.config.hotkey = hotkey
        self.config.initialized = True
        self.accept()
