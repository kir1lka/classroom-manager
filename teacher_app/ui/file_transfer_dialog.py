"""Dialog for sending one or multiple files to a student or the entire classroom (Liquid Glass UI)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from teacher_app.ui.theme import (
    GlassFrame,
    LiquidDialog,
    get_tokens,
    make_app_icon,
    make_icon,
)

DEST_PRESETS: list[tuple[str, str]] = [
    ("Рабочий стол ученика (Desktop)", "@desktop"),
    ("Загрузки ученика (Downloads)", "@downloads"),
    ("Документы ученика (Documents)", "@documents"),
    ("Общий рабочий стол (Public Desktop)", "@public_desktop"),
    ("Своя папка на ПК ученика...", "__CUSTOM__"),
]


class FileTransferDialog(LiquidDialog):
    """Lets the teacher drag-and-drop or pick files, choose target PCs & destination, and track delivery."""

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
        self.setWindowIcon(make_app_icon("teacher"))
        self.setMinimumSize(680, 560)
        self.setAcceptDrops(True)

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
        b_ico.setPixmap(make_icon("send_file", tokens.accent, 20).pixmap(20, 20))
        b_ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b_lay.addWidget(b_ico)
        hdr.addWidget(badge)

        hdr_text = QVBoxLayout()
        hdr_text.setSpacing(2)
        title = QLabel("Передача файлов ученикам")
        title.setObjectName("DialogTitle")
        sub = QLabel("Зашифрованная отправка с проверкой целостности TLS + SHA-256")
        sub.setObjectName("MutedLabel")
        hdr_text.addWidget(title)
        hdr_text.addWidget(sub)
        hdr.addLayout(hdr_text, stretch=1)

        self.count_badge = QLabel("0 файлов")
        self.count_badge.setObjectName("AccentBadge")
        hdr.addWidget(self.count_badge, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(hdr)

        # Top Card: Drag & Drop Zone + File List
        self.drop_card = GlassFrame(variant="card", radius=16)
        drop_v = QVBoxLayout(self.drop_card)
        drop_v.setContentsMargins(16, 14, 16, 16)
        drop_v.setSpacing(10)

        file_bar = QHBoxLayout()
        file_bar.setSpacing(8)

        hint_icon = QLabel()
        hint_icon.setPixmap(make_icon("upload", tokens.text_muted, 16).pixmap(16, 16))
        file_bar.addWidget(hint_icon)

        self.drop_hint_lbl = QLabel("Перетащите файлы в окно или выберите вручную")
        self.drop_hint_lbl.setObjectName("MutedLabel")
        file_bar.addWidget(self.drop_hint_lbl, stretch=1)

        add_btn = QPushButton("+ Добавить файлы")
        add_btn.setProperty("accent", "primary")
        add_btn.setIcon(make_icon("upload", "#FFFFFF", 15))
        add_btn.setIconSize(QSize(15, 15))
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._pick_files)

        clear_btn = QPushButton("Очистить")
        clear_btn.setIcon(make_icon("trash", size=15))
        clear_btn.setIconSize(QSize(15, 15))
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_files)

        file_bar.addWidget(add_btn)
        file_bar.addWidget(clear_btn)
        drop_v.addLayout(file_bar)

        self.file_list = QListWidget()
        self.file_list.setAcceptDrops(False)
        self.file_list.setMinimumHeight(96)
        self.file_list.setMaximumHeight(130)
        drop_v.addWidget(self.file_list)
        layout.addWidget(self.drop_card)

        # Middle Card: Target & Destination Options
        dest_card = GlassFrame(variant="card", radius=16)
        dest_v = QVBoxLayout(dest_card)
        dest_v.setContentsMargins(16, 14, 16, 14)
        dest_v.setSpacing(10)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

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
        self.custom_dir_edit.setPlaceholderText(
            "Например: C:\\Lessons\\Урок_1 или %USERPROFILE%\\Desktop\\Задания"
        )
        self.custom_dir_edit.setVisible(False)
        self.custom_dir_lbl = QLabel("Папка на ПК:")
        self.custom_dir_lbl.setVisible(False)

        form.addRow("Кому отправить:", self.target_combo)
        form.addRow("Куда сохранить:", self.dest_combo)
        form.addRow(self.custom_dir_lbl, self.custom_dir_edit)
        dest_v.addLayout(form)

        checks_row = QHBoxLayout()
        checks_row.setSpacing(18)
        self.overwrite_check = QCheckBox("Перезаписать")
        self.overwrite_check.setToolTip("Перезаписать файл, если файл с таким именем уже существует")
        self.overwrite_check.setChecked(True)

        self.open_after_check = QCheckBox("Открыть сразу после доставки")
        self.open_after_check.setChecked(False)

        checks_row.addWidget(self.overwrite_check)
        checks_row.addWidget(self.open_after_check)
        checks_row.addStretch()
        dest_v.addLayout(checks_row)
        layout.addWidget(dest_card)

        # Progress & Delivery Log
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.log_box = QPlainTextEdit()
        self.log_box.setObjectName("ConsoleBox")
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText(
            "Журнал доставки файлов по каждому компьютеру появится здесь..."
        )
        layout.addWidget(self.log_box, stretch=1)

        # Action Buttons
        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch()

        close_btn = QPushButton("Закрыть")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)

        self.send_btn = QPushButton("Отправить файлы")
        self.send_btn.setProperty("accent", "success")
        self.send_btn.setIcon(make_icon("send_file", "#FFFFFF", 15))
        self.send_btn.setIconSize(QSize(15, 15))
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(self._start_send)

        btns.addWidget(close_btn)
        btns.addWidget(self.send_btn)
        layout.addLayout(btns)

    # ---------- Drag & Drop ----------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls() and any(u.isLocalFile() for u in mime.urls()):
            self.drop_card.setProperty("selected", "true")
            self.drop_card.update()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.drop_card.setProperty("selected", "false")
        self.drop_card.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self.drop_card.setProperty("selected", "false")
        self.drop_card.update()
        paths: list[Path] = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.exists() and p.is_file():
                    paths.append(p)
        if paths:
            self._add_file_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    # ---------- File Management ----------
    def _update_count_badge(self) -> None:
        n = len(self._files)
        if n == 0:
            self.count_badge.setText("0 файлов")
        elif n % 10 == 1 and n % 100 != 11:
            self.count_badge.setText(f"{n} файл")
        elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            self.count_badge.setText(f"{n} файла")
        else:
            self.count_badge.setText(f"{n} файлов")

    def _add_file_paths(self, paths: list[Path]) -> None:
        for p in paths:
            if p not in self._files and p.is_file():
                self._files.append(p)
                size_kb = p.stat().st_size / 1024.0
                size_lbl = f"{size_kb / 1024.0:.2f} МБ" if size_kb >= 1024 else f"{size_kb:.1f} КБ"
                self.file_list.addItem(f"{p.name}  ({size_lbl})  —  {p.parent}")
        self._update_count_badge()

    def _on_dest_changed(self) -> None:
        is_custom = self.dest_combo.currentData() == "__CUSTOM__"
        self.custom_dir_lbl.setVisible(is_custom)
        self.custom_dir_edit.setVisible(is_custom)

    def _pick_files(self) -> None:
        raw_paths, _ = QFileDialog.getOpenFileNames(self, "Выберите файлы для отправки ученикам")
        self._add_file_paths([Path(p_str) for p_str in raw_paths])

    def _clear_files(self) -> None:
        self._files.clear()
        self.file_list.clear()
        self._update_count_badge()

    def _resolve_dest_spec(self) -> str:
        token = str(self.dest_combo.currentData() or "@desktop")
        if token == "__CUSTOM__":
            return self.custom_dir_edit.text().strip()
        return token

    def _start_send(self) -> None:
        if self._sending:
            return
        if not self._files:
            QMessageBox.warning(self, "Нет файлов", "Сначала перетащите или выберите хотя бы один файл.")
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
            f"Начинаю передачу {len(files)} файл(ов) на {len(targets)} ПК → {dest_spec}..."
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
                            f"  [OK] {name}: {fpath.name} → {res.get('saved_path')}"
                        )
                    else:
                        self.log_box.appendPlainText(
                            f"  [ОШИБКА] {name}: {fpath.name} — {res.get('error')}"
                        )
                    self.progress.setValue(int(done_ops * 100 / max(1, total_ops)))
            self.log_box.appendPlainText(
                f"Завершено: успешно доставлено {ok_count} из {total_ops}.\n"
            )
        finally:
            self._sending = False
            self.send_btn.setEnabled(True)
