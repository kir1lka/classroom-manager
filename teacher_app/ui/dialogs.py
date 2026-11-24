"""Teacher startup wizard, password login dialog, and settings dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from shared.config import TeacherConfig
from shared.security import generate_class_secret, hash_password, verify_password


class TeacherSetupWizardDialog(QDialog):
    """First-run wizard to set Teacher password, Classroom ID, and Class Secret."""

    def __init__(self, config: TeacherConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Первичная настройка — Панель учителя")
        self.setMinimumWidth(480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        title = QLabel("Добро пожаловать в Classroom Manager (Учитель)")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #38bdf8;")
        subtitle = QLabel(
            "Задайте пароль для входа в панель учителя и ключ класса.\n"
            "Ключ класса и ID кабинета нужно будет указать в приложении учеников."
        )
        subtitle.setStyleSheet("color: #94a3b8;")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Минимум 4 символа")

        self.password_confirm = QLineEdit()
        self.password_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_confirm.setPlaceholderText("Повторите пароль")

        self.room_edit = QLineEdit(config.classroom_id or "Cab-101")

        secret_row = QHBoxLayout()
        self.secret_edit = QLineEdit(config.class_secret or generate_class_secret())
        gen_btn = QPushButton("Сгенерировать")
        gen_btn.clicked.connect(lambda: self.secret_edit.setText(generate_class_secret()))
        secret_row.addWidget(self.secret_edit)
        secret_row.addWidget(gen_btn)

        self.tcp_port_spin = QSpinBox()
        self.tcp_port_spin.setRange(1024, 65535)
        self.tcp_port_spin.setValue(config.tcp_port)

        self.disc_port_spin = QSpinBox()
        self.disc_port_spin.setRange(1024, 65535)
        self.disc_port_spin.setValue(config.discovery_port)

        self.disc_check = QCheckBox("Автопоиск в локальной сети (без статических IP)")
        self.disc_check.setChecked(config.discovery_enabled)

        form.addRow("Пароль учителя:", self.password_edit)
        form.addRow("Повтор пароля:", self.password_confirm)
        form.addRow("ID кабинета:", self.room_edit)
        form.addRow("Ключ класса (PSK):", secret_row)
        form.addRow("TLS TCP-порт:", self.tcp_port_spin)
        form.addRow("UDP-порт поиска:", self.disc_port_spin)
        form.addRow("", self.disc_check)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Сохранить и запустить")
        save_btn.setProperty("accent", "primary")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

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
        self.config.classroom_id = room
        self.config.class_secret = secret
        self.config.tcp_port = self.tcp_port_spin.value()
        self.config.discovery_port = self.disc_port_spin.value()
        self.config.discovery_enabled = self.disc_check.isChecked()
        self.config.initialized = True
        self.accept()


class TeacherLoginDialog(QDialog):
    """Password authentication prompt shown every time TeacherApp starts."""

    def __init__(self, password_hash: str, classroom_id: str, parent=None) -> None:
        super().__init__(parent)
        self._password_hash = password_hash
        self.setWindowTitle("Авторизация — Панель учителя")
        self.setFixedWidth(380)
        self.setModal(True)

        layout = QVBoxLayout(self)
        title = QLabel(f"Вход в панель учителя ({classroom_id})")
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #38bdf8;")
        layout.addWidget(title)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Введите пароль учителя")
        self.password_edit.returnPressed.connect(self._check_password)
        layout.addWidget(self.password_edit)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #f87171;")
        layout.addWidget(self.error_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        exit_btn = QPushButton("Выход")
        exit_btn.clicked.connect(self.reject)
        login_btn = QPushButton("Войти")
        login_btn.setProperty("accent", "primary")
        login_btn.clicked.connect(self._check_password)
        btn_row.addWidget(exit_btn)
        btn_row.addWidget(login_btn)
        layout.addLayout(btn_row)

    def _check_password(self) -> None:
        if verify_password(self.password_edit.text(), self._password_hash):
            self.accept()
        else:
            self.error_label.setText("Неверный пароль. Попробуйте снова.")
            self.password_edit.selectAll()
            self.password_edit.setFocus()


class TeacherSettingsDialog(QDialog):
    """Settings editor for Teacher network, classroom secret, streaming, and password."""

    def __init__(self, config: TeacherConfig, cert_fingerprint: str, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.network_restart_needed = False
        self.setWindowTitle("Настройки — Панель учителя")
        self.setMinimumWidth(540)
        self.setModal(True)

        layout = QVBoxLayout(self)

        # Network & Classroom Group
        net_group = QGroupBox("Сеть и безопасность класса")
        net_form = QFormLayout(net_group)

        self.room_edit = QLineEdit(config.classroom_id)

        secret_row = QHBoxLayout()
        self.secret_edit = QLineEdit(config.class_secret)
        self.secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        toggle_btn = QPushButton("Показать")
        toggle_btn.setCheckable(True)
        toggle_btn.toggled.connect(
            lambda checked: (
                self.secret_edit.setEchoMode(
                    QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
                ),
                toggle_btn.setText("Скрыть" if checked else "Показать"),
            )
        )
        copy_secret_btn = QPushButton("Копировать")
        copy_secret_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self.secret_edit.text())
        )
        secret_row.addWidget(self.secret_edit)
        secret_row.addWidget(toggle_btn)
        secret_row.addWidget(copy_secret_btn)

        self.tcp_spin = QSpinBox()
        self.tcp_spin.setRange(1024, 65535)
        self.tcp_spin.setValue(config.tcp_port)

        self.disc_spin = QSpinBox()
        self.disc_spin.setRange(1024, 65535)
        self.disc_spin.setValue(config.discovery_port)

        self.disc_check = QCheckBox("Отвечать на автопоиск учеников (UDP Broadcast)")
        self.disc_check.setChecked(config.discovery_enabled)

        fp_row = QHBoxLayout()
        self.fp_edit = QLineEdit(cert_fingerprint)
        self.fp_edit.setReadOnly(True)
        copy_fp_btn = QPushButton("Копировать")
        copy_fp_btn.clicked.connect(lambda: QApplication.clipboard().setText(cert_fingerprint))
        fp_row.addWidget(self.fp_edit)
        fp_row.addWidget(copy_fp_btn)

        net_form.addRow("ID кабинета:", self.room_edit)
        net_form.addRow("Ключ класса (PSK):", secret_row)
        net_form.addRow("TLS TCP-порт:", self.tcp_spin)
        net_form.addRow("UDP-порт автопоиска:", self.disc_spin)
        net_form.addRow("", self.disc_check)
        net_form.addRow("TLS-отпечаток (SHA-256):", fp_row)
        layout.addWidget(net_group)

        # Streaming Group
        stream_group = QGroupBox("Мониторинг экранов")
        stream_form = QFormLayout(stream_group)
        self.thumb_fps_spin = QDoubleSpinBox()
        self.thumb_fps_spin.setRange(0.0, 5.0)
        self.thumb_fps_spin.setSingleStep(0.5)
        self.thumb_fps_spin.setValue(config.thumb_fps)

        self.live_fps_spin = QDoubleSpinBox()
        self.live_fps_spin.setRange(1.0, 20.0)
        self.live_fps_spin.setSingleStep(1.0)
        self.live_fps_spin.setValue(config.live_fps)

        stream_form.addRow("FPS миниатюр в сетке (0 = выкл):", self.thumb_fps_spin)
        stream_form.addRow("FPS при удалённом управлении:", self.live_fps_spin)
        layout.addWidget(stream_group)

        # Password Change Group
        pwd_group = QGroupBox("Смена пароля учителя (необязательно)")
        pwd_form = QFormLayout(pwd_group)
        self.cur_pwd = QLineEdit()
        self.cur_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pwd = QLineEdit()
        self.new_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_pwd = QLineEdit()
        self.confirm_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_form.addRow("Текущий пароль:", self.cur_pwd)
        pwd_form.addRow("Новый пароль:", self.new_pwd)
        pwd_form.addRow("Повтор нового:", self.confirm_pwd)
        layout.addWidget(pwd_group)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Сохранить")
        save_btn.setProperty("accent", "primary")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

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
        self.config.tcp_port = self.tcp_spin.value()
        self.config.discovery_port = self.disc_spin.value()
        self.config.discovery_enabled = self.disc_check.isChecked()
        self.config.thumb_fps = self.thumb_fps_spin.value()
        self.config.live_fps = self.live_fps_spin.value()
        self.accept()
