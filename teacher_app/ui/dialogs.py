"""Teacher startup wizard, password login dialog, and settings dialog (Liquid Glass UI)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from shared.config import TeacherConfig
from shared.security import generate_class_secret, hash_password, verify_password
from teacher_app.ui.theme import (
    GlassFrame,
    LiquidDialog,
    get_tokens,
    make_app_icon,
    make_brand_pixmap,
    make_icon,
)


def _make_icon_pill(icon_name: str, tooltip: str, checkable: bool = False) -> QPushButton:
    """Create a square frosted #IconPill button aligned with QLineEdit height."""
    btn = QPushButton()
    btn.setObjectName("IconPill")
    btn.setIcon(make_icon(icon_name, size=16))
    btn.setIconSize(QSize(16, 16))
    btn.setFixedSize(36, 36)
    btn.setCheckable(checkable)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip(tooltip)
    return btn


def _make_card_header(icon_name: str, title_text: str, subtitle_text: str = "") -> QHBoxLayout:
    """Create a clean section header with a tinted vector icon for GlassFrame cards."""
    tokens = get_tokens()
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 2)
    row.setSpacing(8)

    icon_lbl = QLabel()
    icon_lbl.setPixmap(make_icon(icon_name, tokens.accent, 18).pixmap(18, 18))
    icon_lbl.setFixedSize(20, 20)
    icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    row.addWidget(icon_lbl)

    title_lbl = QLabel(title_text)
    title_lbl.setObjectName("CardSectionTitle")
    row.addWidget(title_lbl)

    row.addStretch()

    if subtitle_text:
        sub_lbl = QLabel(subtitle_text)
        sub_lbl.setObjectName("MutedLabel")
        row.addWidget(sub_lbl)

    return row


class TeacherSetupWizardDialog(LiquidDialog):
    """First-run onboarding wizard to configure Teacher password, Classroom ID, PSK, and LAN ports."""

    def __init__(self, config: TeacherConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Первичная настройка — Панель учителя")
        self.setWindowIcon(make_app_icon("teacher"))
        self.setMinimumWidth(540)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(16)

        # Apple-style onboarding header
        hero_row = QHBoxLayout()
        hero_row.setSpacing(14)

        brand_lbl = QLabel()
        brand_lbl.setPixmap(make_brand_pixmap(44))
        brand_lbl.setFixedSize(48, 48)
        brand_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_row.addWidget(brand_lbl, alignment=Qt.AlignmentFlag.AlignTop)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(4)
        title = QLabel("Добро пожаловать в Classroom")
        title.setObjectName("DialogTitle")
        subtitle = QLabel(
            "Задайте пароль учителя и единый ключ класса. Эти параметры нужно указать "
            "на компьютерах учеников для защищённого подключения."
        )
        subtitle.setObjectName("MutedLabel")
        subtitle.setWordWrap(True)
        hero_text.addWidget(title)
        hero_text.addWidget(subtitle)
        hero_row.addLayout(hero_text, stretch=1)
        layout.addLayout(hero_row)

        # Card 1: Security & Classroom Identity
        sec_card = GlassFrame(variant="card", radius=16)
        sec_v = QVBoxLayout(sec_card)
        sec_v.setContentsMargins(18, 16, 18, 18)
        sec_v.setSpacing(12)
        sec_v.addLayout(_make_card_header("shield", "Защита и идентификация класса"))

        sec_form = QFormLayout()
        sec_form.setHorizontalSpacing(14)
        sec_form.setVerticalSpacing(10)
        sec_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        pwd_row = QHBoxLayout()
        pwd_row.setSpacing(8)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Минимум 4 символа")

        self.password_confirm = QLineEdit()
        self.password_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_confirm.setPlaceholderText("Повторите пароль")

        pwd_eye_btn = _make_icon_pill("eye", "Показать или скрыть пароль", checkable=True)
        pwd_eye_btn.toggled.connect(
            lambda checked: self._toggle_wizard_passwords(checked, pwd_eye_btn)
        )
        pwd_row.addWidget(self.password_edit, stretch=1)
        pwd_row.addWidget(pwd_eye_btn)

        self.room_edit = QLineEdit(config.classroom_id or "Cab-101")
        self.room_edit.setPlaceholderText("Например: Cab-101")

        secret_row = QHBoxLayout()
        secret_row.setSpacing(8)
        self.secret_edit = QLineEdit(config.class_secret or generate_class_secret())
        self.secret_edit.setPlaceholderText("Секретный ключ класса")

        gen_btn = QPushButton("Сгенерировать")
        gen_btn.setIcon(make_icon("refresh", size=15))
        gen_btn.setIconSize(QSize(15, 15))
        gen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        gen_btn.setToolTip("Создать новый случайный ключ класса")
        gen_btn.clicked.connect(lambda: self.secret_edit.setText(generate_class_secret()))

        copy_btn = QPushButton("Копировать")
        copy_btn.setIcon(make_icon("copy", size=15))
        copy_btn.setIconSize(QSize(15, 15))
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setToolTip("Скопировать ключ класса в буфер обмена")
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self.secret_edit.text().strip())
        )

        secret_row.addWidget(self.secret_edit, stretch=1)
        secret_row.addWidget(gen_btn)
        secret_row.addWidget(copy_btn)

        sec_form.addRow("Пароль учителя:", pwd_row)
        sec_form.addRow("Подтверждение:", self.password_confirm)
        self.remember_check = QCheckBox("Сохранить пароль (не спрашивать при каждом запуске)")
        self.remember_check.setChecked(bool(config.remember_login))
        self.remember_check.setCursor(Qt.CursorShape.PointingHandCursor)
        sec_form.addRow("", self.remember_check)
        sec_form.addRow("ID кабинета:", self.room_edit)
        sec_form.addRow("Ключ класса (PSK):", secret_row)
        sec_v.addLayout(sec_form)
        layout.addWidget(sec_card)

        # Card 2: LAN Network Parameters
        net_card = GlassFrame(variant="card", radius=16)
        net_v = QVBoxLayout(net_card)
        net_v.setContentsMargins(18, 16, 18, 16)
        net_v.setSpacing(12)
        net_v.addLayout(_make_card_header("bolt", "Сетевые параметры LAN"))

        ports_row = QHBoxLayout()
        ports_row.setSpacing(12)

        self.tcp_port_spin = QSpinBox()
        self.tcp_port_spin.setRange(1024, 65535)
        self.tcp_port_spin.setValue(config.tcp_port)

        self.disc_port_spin = QSpinBox()
        self.disc_port_spin.setRange(1024, 65535)
        self.disc_port_spin.setValue(config.discovery_port)

        ports_row.addWidget(QLabel("TLS TCP-порт:"))
        ports_row.addWidget(self.tcp_port_spin, stretch=1)
        ports_row.addSpacing(8)
        ports_row.addWidget(QLabel("UDP-порт поиска:"))
        ports_row.addWidget(self.disc_port_spin, stretch=1)
        net_v.addLayout(ports_row)

        self.disc_check = QCheckBox("Автопоиск в локальной сети (без настройки статических IP)")
        self.disc_check.setChecked(config.discovery_enabled)
        net_v.addWidget(self.disc_check)
        layout.addWidget(net_card)

        # Bottom action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("Сохранить и запустить")
        save_btn.setProperty("accent", "primary")
        save_btn.setIcon(make_icon("play", "#FFFFFF", 15))
        save_btn.setIconSize(QSize(15, 15))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _toggle_wizard_passwords(self, visible: bool, btn: QPushButton) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.password_edit.setEchoMode(mode)
        self.password_confirm.setEchoMode(mode)
        btn.setIcon(make_icon("eye_off" if visible else "eye", size=16))

    def _on_save(self) -> None:
        pwd = self.password_edit.text()
        confirm = self.password_confirm.text()
        room = self.room_edit.text().strip()
        secret = self.secret_edit.text().strip()

        if len(pwd) < 4:
            QMessageBox.warning(self, "Ошибка", "Пароль учителя должен содержать минимум 4 символа.")
            return
        if pwd != confirm:
            QMessageBox.warning(self, "Ошибка", "Пароли не совпадают.")
            return
        if not room:
            QMessageBox.warning(self, "Ошибка", "Укажите ID кабинета (например, Cab-101).")
            return
        if len(secret) < 6:
            QMessageBox.warning(self, "Ошибка", "Ключ класса должен быть не короче 6 символов.")
            return

        self.config.password_hash = hash_password(pwd)
        self.config.remember_login = self.remember_check.isChecked()
        self.config.classroom_id = room
        self.config.class_secret = secret
        self.config.tcp_port = self.tcp_port_spin.value()
        self.config.discovery_port = self.disc_port_spin.value()
        self.config.discovery_enabled = self.disc_check.isChecked()
        self.config.initialized = True
        self.accept()


class TeacherLoginDialog(LiquidDialog):
    """Password authentication prompt shown when TeacherApp starts."""

    def __init__(
        self,
        password_hash: str,
        classroom_id: str,
        remember_login: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._password_hash = password_hash
        self.setWindowTitle("Авторизация — Панель учителя")
        self.setWindowIcon(make_app_icon("teacher"))
        self.setFixedWidth(420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(12)

        # Centered Liquid Glass emblem
        emblem = QLabel()
        emblem.setPixmap(make_brand_pixmap(48))
        emblem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(emblem)

        # Hero title
        title = QLabel("Вход в панель учителя")
        title.setObjectName("DialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Classroom pill badge
        badge_row = QHBoxLayout()
        badge_row.addStretch()
        room_badge = QLabel(f"Кабинет {classroom_id}")
        room_badge.setObjectName("AccentBadge")
        room_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_row.addWidget(room_badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)

        layout.addSpacing(4)

        # Frosted password card
        card = GlassFrame(variant="card", radius=18)
        card_v = QVBoxLayout(card)
        card_v.setContentsMargins(18, 16, 18, 16)
        card_v.setSpacing(8)

        field_lbl = QLabel("Пароль учителя")
        field_lbl.setObjectName("MutedLabel")
        card_v.addWidget(field_lbl)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Введите пароль для разблокировки")
        self.password_edit.returnPressed.connect(self._check_password)
        self.password_edit.textChanged.connect(self._clear_error)

        eye_btn = _make_icon_pill("eye", "Показать или скрыть пароль", checkable=True)
        eye_btn.toggled.connect(
            lambda checked: (
                self.password_edit.setEchoMode(
                    QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
                ),
                eye_btn.setIcon(make_icon("eye_off" if checked else "eye", size=16)),
            )
        )

        input_row.addWidget(self.password_edit, stretch=1)
        input_row.addWidget(eye_btn)
        card_v.addLayout(input_row)

        self.remember_check = QCheckBox("Сохранить пароль (входить автоматически)")
        self.remember_check.setChecked(bool(remember_login))
        self.remember_check.setCursor(Qt.CursorShape.PointingHandCursor)
        card_v.addWidget(self.remember_check)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #FF453A; font-size: 12px; font-weight: 600;")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        card_v.addWidget(self.error_label)

        layout.addWidget(card)
        layout.addSpacing(4)

        # Spacious bottom buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        exit_btn = QPushButton("Выход")
        exit_btn.setMinimumHeight(34)
        exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        exit_btn.clicked.connect(self.reject)

        login_btn = QPushButton("Войти")
        login_btn.setProperty("accent", "primary")
        login_btn.setIcon(make_icon("unlock", "#FFFFFF", 16))
        login_btn.setIconSize(QSize(16, 16))
        login_btn.setMinimumHeight(34)
        login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        login_btn.setDefault(True)
        login_btn.clicked.connect(self._check_password)

        btn_row.addWidget(exit_btn, stretch=1)
        btn_row.addWidget(login_btn, stretch=2)
        layout.addLayout(btn_row)

        self.password_edit.setFocus()

    @property
    def remember_login(self) -> bool:
        return self.remember_check.isChecked()

    def _clear_error(self) -> None:
        if self.error_label.text():
            self.error_label.setText("")
            self.error_label.setVisible(False)

    def _check_password(self) -> None:
        if verify_password(self.password_edit.text(), self._password_hash):
            self.accept()
        else:
            self.error_label.setText("Неверный пароль. Проверьте раскладку и попробуйте снова.")
            self.error_label.setVisible(True)
            self.password_edit.selectAll()
            self.password_edit.setFocus()


class TeacherSettingsDialog(LiquidDialog):
    """Settings editor for Teacher network, classroom secret, streaming quality, and password."""

    def __init__(self, config: TeacherConfig, cert_fingerprint: str, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.network_restart_needed = False
        self.setWindowTitle("Настройки класса — Панель учителя")
        self.setWindowIcon(make_app_icon("teacher"))
        self.setMinimumWidth(580)
        self.setModal(True)

        tokens = get_tokens()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        # Dialog Header
        hdr = QHBoxLayout()
        hdr.setSpacing(12)

        badge = GlassFrame(variant="accent", radius=12)
        badge.setFixedSize(40, 40)
        b_lay = QVBoxLayout(badge)
        b_lay.setContentsMargins(0, 0, 0, 0)
        b_ico = QLabel()
        b_ico.setPixmap(make_icon("settings", tokens.accent, 20).pixmap(20, 20))
        b_ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b_lay.addWidget(b_ico)
        hdr.addWidget(badge)

        hdr_text = QVBoxLayout()
        hdr_text.setSpacing(2)
        title_lbl = QLabel("Настройки класса")
        title_lbl.setObjectName("DialogTitle")
        sub_lbl = QLabel("Управление сетью, ключом доступа, частотой кадров и паролем")
        sub_lbl.setObjectName("MutedLabel")
        hdr_text.addWidget(title_lbl)
        hdr_text.addWidget(sub_lbl)
        hdr.addLayout(hdr_text, stretch=1)
        layout.addLayout(hdr)

        # Card 1: Network & Connection Key
        net_card = GlassFrame(variant="card", radius=16)
        net_v = QVBoxLayout(net_card)
        net_v.setContentsMargins(18, 15, 18, 16)
        net_v.setSpacing(10)
        net_v.addLayout(_make_card_header("key", "Сеть и ключ подключения"))

        net_form = QFormLayout()
        net_form.setHorizontalSpacing(14)
        net_form.setVerticalSpacing(9)
        net_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.room_edit = QLineEdit(config.classroom_id)
        self.room_edit.setPlaceholderText("Например: Cab-101")

        secret_row = QHBoxLayout()
        secret_row.setSpacing(6)
        self.secret_edit = QLineEdit(config.class_secret)
        self.secret_edit.setEchoMode(QLineEdit.EchoMode.Password)

        toggle_btn = _make_icon_pill("eye", "Показать или скрыть ключ класса", checkable=True)
        toggle_btn.toggled.connect(
            lambda checked: (
                self.secret_edit.setEchoMode(
                    QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
                ),
                toggle_btn.setIcon(make_icon("eye_off" if checked else "eye", size=16)),
            )
        )

        copy_secret_btn = _make_icon_pill("copy", "Скопировать ключ класса")
        copy_secret_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self.secret_edit.text())
        )

        secret_row.addWidget(self.secret_edit, stretch=1)
        secret_row.addWidget(toggle_btn)
        secret_row.addWidget(copy_secret_btn)

        ports_widget = QWidget()
        ports_row = QHBoxLayout(ports_widget)
        ports_row.setContentsMargins(0, 0, 0, 0)
        ports_row.setSpacing(10)

        self.tcp_spin = QSpinBox()
        self.tcp_spin.setRange(1024, 65535)
        self.tcp_spin.setValue(config.tcp_port)

        self.disc_spin = QSpinBox()
        self.disc_spin.setRange(1024, 65535)
        self.disc_spin.setValue(config.discovery_port)

        ports_row.addWidget(self.tcp_spin, stretch=1)
        udp_lbl = QLabel("UDP автопоиск:")
        udp_lbl.setObjectName("MutedLabel")
        ports_row.addWidget(udp_lbl)
        ports_row.addWidget(self.disc_spin, stretch=1)

        self.disc_check = QCheckBox("Отвечать на автопоиск учеников (UDP Broadcast)")
        self.disc_check.setChecked(config.discovery_enabled)

        fp_row = QHBoxLayout()
        fp_row.setSpacing(6)
        self.fp_edit = QLineEdit(cert_fingerprint)
        self.fp_edit.setReadOnly(True)
        self.fp_edit.setStyleSheet('font-family: "Cascadia Mono", "Consolas", monospace; font-size: 11px;')
        copy_fp_btn = _make_icon_pill("copy", "Скопировать SHA-256 отпечаток сертификата")
        copy_fp_btn.clicked.connect(lambda: QApplication.clipboard().setText(cert_fingerprint))
        fp_row.addWidget(self.fp_edit, stretch=1)
        fp_row.addWidget(copy_fp_btn)

        net_form.addRow("ID кабинета:", self.room_edit)
        net_form.addRow("Ключ класса (PSK):", secret_row)
        net_form.addRow("TLS TCP-порт:", ports_widget)
        net_form.addRow("", self.disc_check)
        net_form.addRow("TLS SHA-256:", fp_row)
        net_v.addLayout(net_form)
        layout.addWidget(net_card)

        # Card 2: Screen Streaming Quality
        stream_card = GlassFrame(variant="card", radius=16)
        stream_v = QVBoxLayout(stream_card)
        stream_v.setContentsMargins(18, 15, 18, 16)
        stream_v.setSpacing(10)
        stream_v.addLayout(_make_card_header("cast", "Качество трансляции экранов"))

        stream_row = QHBoxLayout()
        stream_row.setSpacing(12)

        self.thumb_fps_spin = QDoubleSpinBox()
        self.thumb_fps_spin.setRange(0.0, 5.0)
        self.thumb_fps_spin.setSingleStep(0.5)
        self.thumb_fps_spin.setSuffix(" кадр/с")
        self.thumb_fps_spin.setValue(config.thumb_fps)

        self.live_fps_spin = QDoubleSpinBox()
        self.live_fps_spin.setRange(1.0, 60.0)
        self.live_fps_spin.setSingleStep(5.0)
        self.live_fps_spin.setSuffix(" кадр/с")
        self.live_fps_spin.setValue(config.live_fps)

        stream_row.addWidget(QLabel("Сетка миниатюр (0 = выкл):"))
        stream_row.addWidget(self.thumb_fps_spin, stretch=1)
        stream_row.addSpacing(6)
        stream_row.addWidget(QLabel("Live-управление:"))
        stream_row.addWidget(self.live_fps_spin, stretch=1)
        stream_v.addLayout(stream_row)
        layout.addWidget(stream_card)

        # Card 3: Teacher Password Change (Optional & Compact)
        pwd_card = GlassFrame(variant="card", radius=16)
        pwd_v = QVBoxLayout(pwd_card)
        pwd_v.setContentsMargins(18, 15, 18, 16)
        pwd_v.setSpacing(10)
        pwd_v.addLayout(_make_card_header("lock", "Смена пароля учителя", "Необязательно"))

        pwd_grid_top = QHBoxLayout()
        pwd_grid_top.setSpacing(8)
        self.cur_pwd = QLineEdit()
        self.cur_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.cur_pwd.setPlaceholderText("Текущий пароль")

        self.new_pwd = QLineEdit()
        self.new_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pwd.setPlaceholderText("Новый пароль (от 4 симв.)")

        self.confirm_pwd = QLineEdit()
        self.confirm_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_pwd.setPlaceholderText("Повтор нового")

        pwd_eye = _make_icon_pill("eye", "Показать или скрыть вводимые пароли", checkable=True)
        pwd_eye.toggled.connect(
            lambda checked: self._toggle_pwd_fields(checked, pwd_eye)
        )

        pwd_grid_top.addWidget(self.cur_pwd, stretch=1)
        pwd_grid_top.addWidget(self.new_pwd, stretch=1)
        pwd_grid_top.addWidget(self.confirm_pwd, stretch=1)
        pwd_grid_top.addWidget(pwd_eye)
        pwd_v.addLayout(pwd_grid_top)

        self.remember_check = QCheckBox("Сохранять пароль (входить без повторного ввода при запуске)")
        self.remember_check.setChecked(bool(config.remember_login))
        self.remember_check.setCursor(Qt.CursorShape.PointingHandCursor)
        pwd_v.addWidget(self.remember_check)

        layout.addWidget(pwd_card)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("Сохранить")
        save_btn.setProperty("accent", "primary")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _toggle_pwd_fields(self, visible: bool, btn: QPushButton) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.cur_pwd.setEchoMode(mode)
        self.new_pwd.setEchoMode(mode)
        self.confirm_pwd.setEchoMode(mode)
        btn.setIcon(make_icon("eye_off" if visible else "eye", size=16))

    def _on_save(self) -> None:
        room = self.room_edit.text().strip()
        secret = self.secret_edit.text().strip()
        if not room or len(secret) < 6:
            QMessageBox.warning(self, "Ошибка", "Укажите ID кабинета и ключ класса (от 6 символов).")
            return

        if self.new_pwd.text() or self.confirm_pwd.text():
            if not verify_password(self.cur_pwd.text(), self.config.password_hash):
                QMessageBox.warning(self, "Ошибка", "Неверный текущий пароль.")
                return
            if len(self.new_pwd.text()) < 4:
                QMessageBox.warning(self, "Ошибка", "Новый пароль должен быть не короче 4 символов.")
                return
            if self.new_pwd.text() != self.confirm_pwd.text():
                QMessageBox.warning(self, "Ошибка", "Новые пароли не совпадают.")
                return
            self.config.password_hash = hash_password(self.new_pwd.text())

        old_net = (
            self.config.tcp_port,
            self.config.discovery_port,
            self.config.discovery_enabled,
        )
        new_net = (
            self.tcp_spin.value(),
            self.disc_spin.value(),
            self.disc_check.isChecked(),
        )
        self.network_restart_needed = old_net != new_net

        self.config.classroom_id = room
        self.config.class_secret = secret
        self.config.add_or_update_classroom(room, secret)
        self.config.set_active_classroom(room)
        self.config.tcp_port = self.tcp_spin.value()
        self.config.discovery_port = self.disc_spin.value()
        self.config.discovery_enabled = self.disc_check.isChecked()
        self.config.thumb_fps = self.thumb_fps_spin.value()
        self.config.live_fps = self.live_fps_spin.value()
        self.config.remember_login = self.remember_check.isChecked()
        self.accept()


class AddClassroomDialog(LiquidDialog):
    """Liquid Glass dialog for creating a new classroom with its own ID and PSK secret."""

    def __init__(self, existing_ids: list[str], parent=None) -> None:
        super().__init__(parent)
        self._existing_lower = {rid.strip().lower() for rid in existing_ids if rid.strip()}
        self.created_room_id = ""
        self.created_secret = ""

        self.setWindowTitle("Новый кабинет — Classroom Manager")
        self.setWindowIcon(make_app_icon("teacher"))
        self.setFixedWidth(460)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        hdr = QHBoxLayout()
        hdr.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(make_brand_pixmap(40))
        logo.setFixedSize(40, 40)
        hdr.addWidget(logo)

        hdr_text = QVBoxLayout()
        hdr_text.setSpacing(2)
        title = QLabel("Добавить кабинет")
        title.setObjectName("DialogTitle")
        sub = QLabel("Каждый кабинет получает свой ID и отдельный ключ доступа (PSK)")
        sub.setObjectName("MutedLabel")
        sub.setWordWrap(True)
        hdr_text.addWidget(title)
        hdr_text.addWidget(sub)
        hdr.addLayout(hdr_text, stretch=1)
        layout.addLayout(hdr)

        card = GlassFrame(variant="card", radius=16)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(18, 16, 18, 16)
        cv.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.room_edit = QLineEdit()
        self.room_edit.setPlaceholderText("Например: Cab-204 или Lab-IT")

        secret_row = QHBoxLayout()
        secret_row.setSpacing(6)
        self.secret_edit = QLineEdit(generate_class_secret())
        self.secret_edit.setPlaceholderText("Минимум 6 символов")

        gen_btn = _make_icon_pill("refresh", "Сгенерировать новый ключ класса")
        gen_btn.clicked.connect(lambda: self.secret_edit.setText(generate_class_secret()))

        copy_btn = _make_icon_pill("copy", "Скопировать ключ класса")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.secret_edit.text()))

        secret_row.addWidget(self.secret_edit, stretch=1)
        secret_row.addWidget(gen_btn)
        secret_row.addWidget(copy_btn)

        form.addRow("ID кабинета:", self.room_edit)
        form.addRow("Ключ класса (PSK):", secret_row)
        cv.addLayout(form)
        layout.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        create_btn = QPushButton("Создать кабинет")
        create_btn.setProperty("accent", "primary")
        create_btn.setIcon(make_icon("plus", "#FFFFFF", 15))
        create_btn.setIconSize(QSize(15, 15))
        create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        create_btn.setDefault(True)
        create_btn.clicked.connect(self._on_create)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(create_btn)
        layout.addLayout(btn_row)

        self.room_edit.setFocus()

    def _on_create(self) -> None:
        rid = self.room_edit.text().strip()
        sec = self.secret_edit.text().strip()
        if not rid:
            QMessageBox.warning(self, "Ошибка", "Укажите ID нового кабинета (например, Cab-204).")
            return
        if rid.lower() in self._existing_lower:
            QMessageBox.warning(self, "Ошибка", f"Кабинет «{rid}» уже существует.")
            return
        if len(sec) < 6:
            QMessageBox.warning(self, "Ошибка", "Ключ класса должен содержать минимум 6 символов.")
            return
        self.created_room_id = rid
        self.created_secret = sec
        self.accept()


DEMO_PRESETS: list[tuple[str, float, int, int]] = [
    ("HD Чёткий 15 FPS (1080p, 88%)", 15.0, 1920, 88),
    ("Плавный 30 FPS (1080p, 78%)", 30.0, 1920, 78),
    ("Игровой / Видео 60 FPS (720p, 72%)", 60.0, 1280, 72),
    ("Ультра 1:1 (Оригинал, 10 FPS, 92%)", 10.0, 0, 92),
    ("Настраиваемый (вручную)", -1.0, -1, -1),
]


class DemoBroadcastDialog(LiquidDialog):
    """Liquid Glass dialog for configuring Teacher screen demonstration and selecting target PCs."""

    def __init__(
        self,
        config: TeacherConfig,
        monitors: list[dict],
        students: list[tuple[str, str]],
        active: bool = False,
        current_target_ids: set[str] | None = None,
        preselected_ids: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._active = active
        self.start_requested = False
        self.selected_target_ids: list[str] | None = None

        self.setWindowTitle("Настройка демонстрации экрана учителя")
        self.setWindowIcon(make_app_icon("teacher"))
        self.setMinimumWidth(560)
        self.setModal(True)

        tokens = get_tokens()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        # Header
        hdr = QHBoxLayout()
        hdr.setSpacing(12)
        badge = GlassFrame(variant="accent", radius=12)
        badge.setFixedSize(40, 40)
        b_lay = QVBoxLayout(badge)
        b_lay.setContentsMargins(0, 0, 0, 0)
        b_ico = QLabel()
        b_ico.setPixmap(make_icon("cast", tokens.accent, 20).pixmap(20, 20))
        b_ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b_lay.addWidget(b_ico)
        hdr.addWidget(badge)

        hdr_text = QVBoxLayout()
        hdr_text.setSpacing(2)
        title = QLabel("Демонстрация экрана учителя")
        title.setObjectName("DialogTitle")
        sub = QLabel(
            "Выберите, кому показывать экран (всему классу или отдельным ПК), и настройте качество эфира"
        )
        sub.setObjectName("MutedLabel")
        sub.setWordWrap(True)
        hdr_text.addWidget(title)
        hdr_text.addWidget(sub)
        hdr.addLayout(hdr_text, stretch=1)
        layout.addLayout(hdr)

        # Card 1: Target Audience (All vs Selected PCs)
        tgt_card = GlassFrame(variant="card", radius=16)
        tgt_v = QVBoxLayout(tgt_card)
        tgt_v.setContentsMargins(18, 15, 18, 16)
        tgt_v.setSpacing(10)
        tgt_v.addLayout(
            _make_card_header("monitor", "Кому показывать экран", f"Онлайн: {len(students)} ПК")
        )

        self.rb_all = QRadioButton("Всем ученикам в классе (новые ПК подключаются автоматически)")
        self.rb_selected = QRadioButton("Только выбранным компьютерам:")
        self.rb_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rb_selected.setCursor(Qt.CursorShape.PointingHandCursor)

        use_selected = preselected_ids is not None or (active and current_target_ids is not None)
        if use_selected:
            self.rb_selected.setChecked(True)
        else:
            self.rb_all.setChecked(True)

        tgt_v.addWidget(self.rb_all)
        tgt_v.addWidget(self.rb_selected)

        sel_tools = QHBoxLayout()
        sel_tools.setSpacing(8)
        self.btn_sel_all = QPushButton("Выбрать всех")
        self.btn_sel_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sel_all.clicked.connect(lambda: self._set_all_checked(True))
        self.btn_sel_none = QPushButton("Снять выбор")
        self.btn_sel_none.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sel_none.clicked.connect(lambda: self._set_all_checked(False))
        self.sel_count_lbl = QLabel("")
        self.sel_count_lbl.setObjectName("MutedLabel")
        sel_tools.addWidget(self.btn_sel_all)
        sel_tools.addWidget(self.btn_sel_none)
        sel_tools.addStretch()
        sel_tools.addWidget(self.sel_count_lbl)
        tgt_v.addLayout(sel_tools)

        self.students_list = QListWidget()
        self.students_list.setMinimumHeight(115)
        self.students_list.setMaximumHeight(165)
        checked_set: set[str] | None = None
        if preselected_ids is not None:
            checked_set = set(preselected_ids)
        elif active and current_target_ids is not None:
            checked_set = set(current_target_ids)

        if not students:
            empty_item = QListWidgetItem("Нет подключённых учеников онлайн")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.students_list.addItem(empty_item)
        else:
            for cid, label in students:
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, cid)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                is_checked = checked_set is None or cid in checked_set
                item.setCheckState(
                    Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked
                )
                self.students_list.addItem(item)

        self.students_list.itemChanged.connect(lambda _it: self._update_sel_count())
        tgt_v.addWidget(self.students_list)
        layout.addWidget(tgt_card)

        # Card 2: Stream Quality & Display Parameters
        opt_card = GlassFrame(variant="card", radius=16)
        opt_v = QVBoxLayout(opt_card)
        opt_v.setContentsMargins(18, 15, 18, 16)
        opt_v.setSpacing(10)
        opt_v.addLayout(_make_card_header("settings", "Параметры трансляции"))

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.mon_combo = QComboBox()
        for mon in monitors:
            self.mon_combo.addItem(str(mon["name"]), int(mon["index"]))
        if len(monitors) > 1:
            self.mon_combo.addItem("Все мониторы сразу", 0)
        saved_mon_idx = self.mon_combo.findData(int(config.demo_monitor))
        if saved_mon_idx >= 0:
            self.mon_combo.setCurrentIndex(saved_mon_idx)

        self.preset_combo = QComboBox()
        for name, _f, _w, _q in DEMO_PRESETS:
            self.preset_combo.addItem(name)

        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(1.0, 60.0)
        self.fps_spin.setSingleStep(5.0)
        self.fps_spin.setSuffix(" FPS")
        self.fps_spin.setValue(float(config.demo_fps))

        self.width_spin = QSpinBox()
        self.width_spin.setRange(0, 3840)
        self.width_spin.setSingleStep(160)
        self.width_spin.setSpecialValueText("Оригинал 1:1")
        self.width_spin.setSuffix(" px")
        self.width_spin.setValue(int(config.demo_width))

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(40, 95)
        self.quality_spin.setSingleStep(5)
        self.quality_spin.setSuffix(" %")
        self.quality_spin.setValue(int(config.demo_quality))

        manual_row = QHBoxLayout()
        manual_row.setSpacing(8)
        manual_row.addWidget(self.fps_spin, stretch=1)
        manual_row.addWidget(self.width_spin, stretch=1)
        manual_row.addWidget(self.quality_spin, stretch=1)

        self.fullscreen_check = QCheckBox(
            "Полноэкранный режим у учеников (снять — открыть в окне, чтобы повторять параллельно)"
        )
        self.fullscreen_check.setChecked(bool(config.demo_fullscreen))
        self.fullscreen_check.setCursor(Qt.CursorShape.PointingHandCursor)

        self.title_edit = QLineEdit(config.demo_title or "")
        self.title_edit.setPlaceholderText(
            f"По умолчанию: Демонстрация экрана учителя ({config.classroom_id})"
        )

        form.addRow("Монитор учителя:", self.mon_combo)
        form.addRow("Пресет качества:", self.preset_combo)
        form.addRow("FPS / Ширина / JPEG:", manual_row)
        form.addRow("Заголовок плашки:", self.title_edit)
        opt_v.addLayout(form)
        opt_v.addWidget(self.fullscreen_check)
        layout.addWidget(opt_card)

        # Match current values to a preset or "Custom"
        self._sync_preset_from_spins()
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)

        # Bottom Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        save_only_btn = QPushButton("Сохранить настройки")
        save_only_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_only_btn.clicked.connect(self._on_save_only)

        start_label = "Применить к эфиру" if active else "Начать демонстрацию"
        self.start_btn = QPushButton(start_label)
        self.start_btn.setProperty("accent", "primary")
        self.start_btn.setIcon(make_icon("cast", "#FFFFFF", 15))
        self.start_btn.setIconSize(QSize(15, 15))
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self._on_start)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_only_btn)
        btn_row.addWidget(self.start_btn)
        layout.addLayout(btn_row)

        self.rb_all.toggled.connect(self._update_target_controls)
        self.rb_selected.toggled.connect(self._update_target_controls)
        self._update_target_controls()
        self._update_sel_count()

    def _sync_preset_from_spins(self) -> None:
        cur = (round(self.fps_spin.value(), 1), self.width_spin.value(), self.quality_spin.value())
        for idx, (_name, fps, width, qual) in enumerate(DEMO_PRESETS[:-1]):
            if (round(fps, 1), width, qual) == cur:
                self.preset_combo.setCurrentIndex(idx)
                return
        self.preset_combo.setCurrentIndex(len(DEMO_PRESETS) - 1)

    def _on_preset_changed(self, idx: int) -> None:
        if 0 <= idx < len(DEMO_PRESETS) - 1:
            _name, fps, width, qual = DEMO_PRESETS[idx]
            self.fps_spin.setValue(fps)
            self.width_spin.setValue(width)
            self.quality_spin.setValue(qual)

    def _update_target_controls(self) -> None:
        selective = self.rb_selected.isChecked()
        self.students_list.setEnabled(selective)
        self.btn_sel_all.setEnabled(selective)
        self.btn_sel_none.setEnabled(selective)
        self._update_sel_count()

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.students_list.blockSignals(True)
        for i in range(self.students_list.count()):
            it = self.students_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole):
                it.setCheckState(state)
        self.students_list.blockSignals(False)
        self._update_sel_count()

    def _checked_client_ids(self) -> list[str]:
        ids: list[str] = []
        for i in range(self.students_list.count()):
            it = self.students_list.item(i)
            cid = it.data(Qt.ItemDataRole.UserRole)
            if cid and it.checkState() == Qt.CheckState.Checked:
                ids.append(str(cid))
        return ids

    def _update_sel_count(self) -> None:
        total = sum(
            1
            for i in range(self.students_list.count())
            if self.students_list.item(i).data(Qt.ItemDataRole.UserRole)
        )
        if self.rb_all.isChecked():
            self.sel_count_lbl.setText(f"Показ всем ({total} онлайн)")
        else:
            sel = len(self._checked_client_ids())
            self.sel_count_lbl.setText(f"Выбрано: {sel} из {total}")

    def _save_to_config(self) -> None:
        self.config.demo_monitor = int(self.mon_combo.currentData() if self.mon_combo.currentData() is not None else 1)
        self.config.demo_fps = float(self.fps_spin.value())
        self.config.demo_width = int(self.width_spin.value())
        self.config.demo_quality = int(self.quality_spin.value())
        self.config.demo_fullscreen = self.fullscreen_check.isChecked()
        self.config.demo_title = self.title_edit.text().strip()

    def _on_save_only(self) -> None:
        self._save_to_config()
        self.start_requested = False
        self.accept()

    def _on_start(self) -> None:
        if self.rb_selected.isChecked():
            chosen = self._checked_client_ids()
            if not chosen:
                QMessageBox.warning(
                    self,
                    "Не выбраны компьютеры",
                    "Отметьте хотя бы один компьютер ученика или выберите «Всем ученикам в классе».",
                )
                return
            self.selected_target_ids = chosen
        else:
            self.selected_target_ids = None

        self._save_to_config()
        self.start_requested = True
        self.accept()
