"""Dialog for sending one or multiple files to a student or the entire classroom."""

from __future__ import annotations

import asyncio
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from teacher_app.network.server import TeacherServer

DEST_PRESETS: list[tuple[str, str]] = [
    ("Рабочий стол ученика (Desktop)", "@desktop"),
    ("Загрузки ученика (Downloads)", "@downloads"),
    ("Документы ученика (Documents)", "@documents"),
    ("Общий рабочий стол (Public Desktop)", "@public_desktop"),
    ("Своя папка на ПК ученика...", "__CUSTOM__"),
]


class FileTransferDialog(QDialog):
    """Lets the teacher pick files, target PCs, destination folder, and monitor delivery."""

    def __init__(
        self,
        server: TeacherServer,
        preselected_client_id: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.server = server
        self._files: list[Path] = []
        self._sending = False

        self.setWindowTitle("Передача файлов ученикам")
        self.setMinimumSize(620, 520)

        layout = QVBoxLayout(self)

        title = QLabel("Отправка файлов на компьютеры учеников (по защищённому TLS)")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #38bdf8;")
        layout.addWidget(title)

        # File picker list
        file_bar = QHBoxLayout()
        add_btn = QPushButton("Выбрать файл(ы)...")
        add_btn.setProperty("accent", "primary")
        add_btn.clicked.connect(self._pick_files)
        clear_btn = QPushButton("Очистить список")
        clear_btn.clicked.connect(self._clear_files)
        file_bar.addWidget(add_btn)
        file_bar.addWidget(clear_btn)
        file_bar.addStretch()
        layout.addLayout(file_bar)

        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(110)
        self.file_list.setStyleSheet(
            "background-color: #0b1220; border: 1px solid #334155; border-radius: 6px; padding: 4px;"
        )
        layout.addWidget(self.file_list)

        # Target & destination form
        form = QFormLayout()

        self.target_combo = QComboBox()
        self.target_combo.addItem(f"Весь класс (все онлайн: {len(server.clients)})", "__ALL__")
        for cid, sess in server.clients.items():
            self.target_combo.addItem(f"{sess.label} ({sess.ip})", cid)
        if preselected_client_id:
            idx = self.target_combo.findData(preselected_client_id)
            if idx >= 0:
                self.target_combo.setCurrentIndex(idx)

        self.dest_combo = QComboBox()
        for label, token in DEST_PRESETS:
            self.dest_combo.addItem(label, token)
        self.dest_combo.currentIndexChanged.connect(self._on_dest_changed)

        self.custom_dir_edit = QLineEdit("C:\\ClassFiles")
        self.custom_dir_edit.setPlaceholderText("Например: C:\\Lessons\\Урок_1 или %USERPROFILE%\\Desktop\\Задания")
        self.custom_dir_edit.setVisible(False)
        self.custom_dir_lbl = QLabel("Путь к папке на ПК ученика:")
        self.custom_dir_lbl.setVisible(False)

        self.overwrite_check = QCheckBox("Перезаписать, если файл с таким именем уже есть")
        self.overwrite_check.setChecked(True)

        self.open_after_check = QCheckBox("Открыть файл у ученика сразу после сохранения")
        self.open_after_check.setChecked(False)

        form.addRow("Кому отправить:", self.target_combo)
        form.addRow("Куда сохранить:", self.dest_combo)
        form.addRow(self.custom_dir_lbl, self.custom_dir_edit)
        form.addRow("", self.overwrite_check)
        form.addRow("", self.open_after_check)
        layout.addLayout(form)

        # Progress & log
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Здесь появится статус доставки файлов по каждому компьютеру...")
        self.log_box.setStyleSheet(
            'background-color: #020617; color: #cbd5e1; font-family: "Consolas", monospace; font-size: 12px;'
        )
        layout.addWidget(self.log_box, stretch=1)

        # Action buttons
        btns = QHBoxLayout()
        btns.addStretch()
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.close)
        self.send_btn = QPushButton("Отправить файлы")
        self.send_btn.setProperty("accent", "success")
        self.send_btn.clicked.connect(self._start_send)
        btns.addWidget(close_btn)
        btns.addWidget(self.send_btn)
        layout.addLayout(btns)

    def _on_dest_changed(self) -> None:
        is_custom = self.dest_combo.currentData() == "__CUSTOM__"
        self.custom_dir_lbl.setVisible(is_custom)
        self.custom_dir_edit.setVisible(is_custom)

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Выберите файлы для отправки ученикам")
        for p_str in paths:
            p = Path(p_str)
            if p not in self._files:
                self._files.append(p)
                size_kb = p.stat().st_size / 1024.0
                size_lbl = f"{size_kb / 1024.0:.2f} МБ" if size_kb >= 1024 else f"{size_kb:.1f} КБ"
                self.file_list.addItem(f"{p.name}  ({size_lbl}) — {p.parent}")

    def _clear_files(self) -> None:
        self._files.clear()
        self.file_list.clear()

    def _resolve_dest_spec(self) -> str:
        token = str(self.dest_combo.currentData() or "@desktop")
        if token == "__CUSTOM__":
            return self.custom_dir_edit.text().strip()
        return token

    def _start_send(self) -> None:
        if self._sending:
            return
        if not self._files:
            QMessageBox.warning(self, "Нет файлов", "Сначала выберите хотя бы один файл.")
            return
        dest_spec = self._resolve_dest_spec()
        if not dest_spec:
            QMessageBox.warning(self, "Не указана папка", "Укажите путь к папке на ПК ученика.")
            return

        target_data = self.target_combo.currentData()
        if target_data == "__ALL__":
            targets = list(self.server.clients.keys())
        else:
            targets = [str(target_data)]

        if not targets:
            QMessageBox.warning(self, "Нет учеников", "Нет подключённых компьютеров учеников.")
            return

        asyncio.create_task(self._run_transfer(list(self._files), targets, dest_spec))

    async def _run_transfer(self, files: list[Path], targets: list[str], dest_spec: str) -> None:
        self._sending = True
        self.send_btn.setEnabled(False)
        self.progress.setValue(0)
        overwrite = self.overwrite_check.isChecked()
        open_after = self.open_after_check.isChecked()

        total_ops = len(files) * len(targets)
        done_ops = 0
        ok_count = 0

        self.log_box.appendPlainText(
            f"Начинаю передачу {len(files)} файл(ов) на {len(targets)} ПК -> {dest_spec}..."
        )

        try:
            for fpath in files:
                results = await self.server.broadcast_file(
                    fpath,
                    dest_dir=dest_spec,
                    overwrite=overwrite,
                    open_after=open_after,
                    client_ids=targets,
                )
                for cid, res in results.items():
                    done_ops += 1
                    sess = self.server.clients.get(cid)
                    name = sess.label if sess else cid
                    if res.get("ok"):
                        ok_count += 1
                        self.log_box.appendPlainText(
                            f"  [OK] {name}: {fpath.name} -> {res.get('saved_path')}"
                        )
                    else:
                        self.log_box.appendPlainText(
                            f"  [ОШИБКА] {name}: {fpath.name} — {res.get('error')}"
                        )
                    self.progress.setValue(int(done_ops * 100 / max(1, total_ops)))
            self.log_box.appendPlainText(
                f"Завершено: успешно {ok_count} из {total_ops}.\n"
            )
        finally:
            self._sending = False
            self.send_btn.setEnabled(True)
