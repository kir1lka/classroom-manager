"""Password gate and settings dialog for the Student tray agent."""

from __future__ import annotations

import socket

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
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

from shared.config import StudentConfig
from shared.security import hash_password, verify_password
from student_app.ui.hotkey import parse_hotkey_string


class StudentPasswordPrompt(QDialog):
    """Modal password prompt protecting Student settings and agent exit."""

    def __init__(self, password_hash: str, action_title: str = "Доступ к настройкам агента", parent=None) -> None:
        super().__init__(parent)
        self._password_hash = password_hash
        self.setWindowTitle("Требуется пароль учителя")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedWidth(380)
        self.setModal(True)

        layout = QVBoxLayout(self)
        title = QLabel(action_title)
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #38bdf8;")
        layout.addWidget(title)

        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_edit.setPlaceholderText("Введите пароль администратора/учителя")
        self.pwd_edit.returnPressed.connect(self._verify)
        layout.addWidget(self.pwd_edit)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet("color: #f87171;")
        layout.addWidget(self.err_lbl)

        row = QHBoxLayout()
        row.addStretch()
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Подтвердить")
        ok_btn.setProperty("accent", "primary")
        ok_btn.clicked.connect(self._verify)
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
        layout.addLayout(row)

    def _verify(self) -> None:
        if verify_password(self.pwd_edit.text(), self._password_hash):
            self.accept()
        else:
            self.err_lbl.setText("Неверный пароль.")
            self.pwd_edit.selectAll()
            self.pwd_edit.setFocus()


class StudentSettingsDialog(QDialog):
    """First-run setup or password-authenticated settings editor for StudentApp."""

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
            "Первичная настройка — Агент ученика" if first_run else "Настройки агента ученика"
        )
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(520)
        self.setModal(True)

        layout = QVBoxLayout(self)

        if status_text:
            st = QLabel(f"Текущий статус: {status_text}")
            st.setStyleSheet(
                "background-color: #1e293b; border: 1px solid #334155; "
                "border-radius: 6px; padding: 8px; color: #93c5fd; font-weight: 600;"
            )
            layout.addWidget(st)

        # Classroom & Smart Discovery group
        conn_group = QGroupBox("Подключение к учителю (динамический IP поддерживается)")
        conn_form = QFormLayout(conn_group)

        self.room_edit = QLineEdit(config.classroom_id or "Cab-101")
        self.secret_edit = QLineEdit(config.class_secret)
        self.secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret_edit.setPlaceholderText("Ключ класса из приложения учителя")

        self.name_edit = QLineEdit(config.display_name)
        self.name_edit.setPlaceholderText(f"По умолчанию: {socket.gethostname()}")

        self.disc_check = QCheckBox("Автоматически находить учителя в LAN (UDP Broadcast, без статич. IP)")
        self.disc_check.setChecked(config.discovery_enabled)

        self.disc_port_spin = QSpinBox()
        self.disc_port_spin.setRange(1024, 65535)
        self.disc_port_spin.setValue(config.discovery_port)

        self.manual_host_edit = QLineEdit(config.manual_host)
        self.manual_host_edit.setPlaceholderText("Необязательно: IP или имя ПК учителя (резерв)")

        self.manual_port_spin = QSpinBox()
        self.manual_port_spin.setRange(1024, 65535)
        self.manual_port_spin.setValue(config.manual_port)

        self.fp_edit = QLineEdit(config.pinned_fingerprint)
        self.fp_edit.setPlaceholderText("Необязательно: SHA-256 отпечаток TLS-сертификата учителя")

        conn_form.addRow("ID кабинета:", self.room_edit)
        conn_form.addRow("Ключ класса (PSK):", self.secret_edit)
        conn_form.addRow("Имя парты / ПК:", self.name_edit)
        conn_form.addRow("", self.disc_check)
        conn_form.addRow("UDP-порт поиска:", self.disc_port_spin)
        conn_form.addRow("Резервный IP / Hostname:", self.manual_host_edit)
        conn_form.addRow("TLS TCP-порт:", self.manual_port_spin)
        conn_form.addRow("TLS-отпечаток (pin):", self.fp_edit)
        layout.addWidget(conn_group)

        # Hotkey & Protection group
        sec_group = QGroupBox("Защита агента и горячая клавиша")
        sec_form = QFormLayout(sec_group)

        self.hotkey_edit = QLineEdit(config.hotkey or "Ctrl+Alt+Shift+M")
        self.hotkey_edit.setPlaceholderText("Например: Ctrl+Alt+Shift+M")

        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_edit.setPlaceholderText(
            "Задайте пароль администратора (мин. 4 символа)" if first_run else "Оставьте пустым, чтобы не менять"
        )
        self.pwd_confirm = QLineEdit()
        self.pwd_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_confirm.setPlaceholderText("Повторите пароль")

        sec_form.addRow("Глобальная горячая клавиша:", self.hotkey_edit)
        sec_form.addRow("Пароль администратора:" if first_run else "Новый пароль:", self.pwd_edit)
        sec_form.addRow("Повтор пароля:", self.pwd_confirm)
        layout.addWidget(sec_group)

        # Bottom buttons
        btn_row = QHBoxLayout()
        if not first_run:
            exit_btn = QPushButton("Остановить и выйти")
            exit_btn.setProperty("accent", "danger")
            exit_btn.clicked.connect(self._on_exit_agent)
            btn_row.addWidget(exit_btn)

            unlock_btn = QPushButton("Снять блок. экрана")
            unlock_btn.clicked.connect(self._on_unlock_local)
            btn_row.addWidget(unlock_btn)

        btn_row.addStretch()
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Сохранить и подключиться" if first_run else "Сохранить")
        save_btn.setProperty("accent", "primary")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

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
            QMessageBox.warning(self, "Ошибка", "Некорректная горячая клавиша. Пример: Ctrl+Alt+Shift+M")
            return

        pwd = self.pwd_edit.text()
        confirm = self.pwd_confirm.text()
        if self.first_run or pwd or confirm:
            if len(pwd) < 4:
                QMessageBox.warning(self, "Ошибка", "Пароль администратора должен быть не короче 4 символов.")
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
