"""Unified Liquid Glass Dark-Theme Installer for Classroom Manager (Teacher & Student)."""

from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from installer_app.installer_ops import (
    InstallOptions,
    default_install_dir,
    is_admin,
    run_installation,
)
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

GITHUB_REPO_URL = "https://github.com/kir1lka/classroom-manager"
GITHUB_RELEASES_URL = "https://github.com/kir1lka/classroom-manager/releases"
INSTALLER_VERSION = "v3.0.1"

USEFUL_COMMANDS: list[tuple[str, str, str]] = [
    (
        "Интернет в браузерах ВЫКЛ (локалка работает)",
        "Мгновенно отключает интернет в Chrome, Edge и Яндекс.Браузере без прав администратора. Связь с учителем и локальный сервер продолжают работать.",
        '$p = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings"\n'
        'Set-ItemProperty -Path $p -Name ProxyEnable -Value 1\n'
        'Set-ItemProperty -Path $p -Name ProxyServer -Value "127.0.0.1:9"\n'
        'Set-ItemProperty -Path $p -Name ProxyOverride -Value "localhost;127.0.0.1;192.168.*;10.*;172.16.*;<local>"\n'
        '$code = \'using System; using System.Runtime.InteropServices; public class Inet { [DllImport("wininet.dll", SetLastError=true)] public static extern bool InternetSetOption(IntPtr h, int opt, IntPtr buf, int len); }\'\n'
        'Add-Type -TypeDefinition $code\n'
        '[Inet]::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0) | Out-Null\n'
        '[Inet]::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0) | Out-Null\n'
        '"Интернет в браузерах выключен"',
    ),
    (
        "Интернет в браузерах ВКЛ",
        "Мгновенно возвращает интернет во всех браузерах.",
        '$p = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings"\n'
        'Set-ItemProperty -Path $p -Name ProxyEnable -Value 0\n'
        '$code = \'using System; using System.Runtime.InteropServices; public class Inet { [DllImport("wininet.dll", SetLastError=true)] public static extern bool InternetSetOption(IntPtr h, int opt, IntPtr buf, int len); }\'\n'
        'Add-Type -TypeDefinition $code\n'
        '[Inet]::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0) | Out-Null\n'
        '[Inet]::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0) | Out-Null\n'
        '"Интернет в браузерах включён"',
    ),
    (
        "Закрыть все браузеры (Яндекс, Chrome, Edge, Opera, Firefox)",
        "Принудительно закрывает открытые браузеры на ПК учеников.",
        "Stop-Process -Name browser,chrome,msedge,opera,firefox,brave -Force -ErrorAction SilentlyContinue; 'Все браузеры закрыты'",
    ),
    (
        "Имя ПК, пользователь и LAN IP",
        "Выводит сетевую диагностику каждого компьютера класса.",
        "hostname; whoami; (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '127.*'}).IPAddress",
    ),
]


class _InstallSignals(QObject):
    log_line = Signal(str)
    progress = Signal(int)
    finished = Signal(bool)


class ClassroomInstallerWindow(QMainWindow):
    """Dark-theme-only Liquid Glass installer with built-in guide, troubleshooting, and commands."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Classroom Manager {INSTALLER_VERSION} — Установщик")
        self.setWindowIcon(make_app_icon("teacher"))
        self.resize(1040, 680)
        self.setMinimumSize(940, 620)
        apply_window_chrome(self, "dark")

        self._installing = False
        self._signals = _InstallSignals()
        self._signals.log_line.connect(self._append_log)
        self._signals.progress.connect(self._set_progress)
        self._signals.finished.connect(self._on_install_finished)

        self._build_ui()

    def _build_ui(self) -> None:
        t = get_tokens("dark")
        backdrop = LiquidBackdropWidget()
        root = QHBoxLayout(backdrop)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # ================= LEFT NAVIGATION RAIL (No Theme Toggle!) =================
        sidebar = GlassFrame(variant="sidebar", radius=20)
        sidebar.setFixedWidth(252)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(16, 20, 16, 16)
        sb.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        logo_lbl = QLabel()
        logo_lbl.setPixmap(make_brand_pixmap(38))
        brand_row.addWidget(logo_lbl)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(1)
        b_title = QLabel("CLASSROOM")
        b_title.setObjectName("BrandTitle")
        b_ver = QLabel(f"Установщик {INSTALLER_VERSION}")
        b_ver.setObjectName("MutedLabel")
        brand_col.addWidget(b_title)
        brand_col.addWidget(b_ver)
        brand_row.addLayout(brand_col, stretch=1)
        sb.addLayout(brand_row)

        admin_badge = QLabel("Права: Администратор" if is_admin() else "Режим: Пользователь")
        admin_badge.setObjectName("OnlineBadge" if is_admin() else "MonBadge")
        admin_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sb.addWidget(admin_badge)
        sb.addSpacing(12)

        sec_lbl = QLabel("РАЗДЕЛЫ")
        sec_lbl.setObjectName("SectionLabel")
        sb.addWidget(sec_lbl)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.nav_install = self._make_nav_btn("Установка", "download", 0, checked=True)
        self.nav_guide = self._make_nav_btn("Инструкция", "info", 1)
        self.nav_trouble = self._make_nav_btn("Решение проблем", "shield", 2)
        self.nav_cmds = self._make_nav_btn("Полезные команды", "terminal", 3)

        sb.addWidget(self.nav_install)
        sb.addWidget(self.nav_guide)
        sb.addWidget(self.nav_trouble)
        sb.addWidget(self.nav_cmds)

        sb.addStretch(1)

        # External GitHub & Releases Card (no theme switch!)
        links_card = GlassFrame(variant="inset", radius=14)
        lc = QVBoxLayout(links_card)
        lc.setContentsMargins(12, 12, 12, 12)
        lc.setSpacing(8)

        lc_title = QLabel("ДОКУМЕНТАЦИЯ И ОБНОВЛЕНИЯ")
        lc_title.setObjectName("SectionLabel")
        lc.addWidget(lc_title)

        btn_github = QPushButton("Открыть сайт / GitHub")
        btn_github.setIcon(make_icon("globe", t.accent, 15))
        btn_github.setIconSize(QSize(15, 15))
        btn_github.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_github.clicked.connect(lambda: webbrowser.open(GITHUB_REPO_URL))

        btn_releases = QPushButton("Проверить релизы")
        btn_releases.setIcon(make_icon("refresh", t.text_secondary, 15))
        btn_releases.setIconSize(QSize(15, 15))
        btn_releases.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_releases.clicked.connect(lambda: webbrowser.open(GITHUB_RELEASES_URL))

        lc.addWidget(btn_github)
        lc.addWidget(btn_releases)
        sb.addWidget(links_card)

        root.addWidget(sidebar)

        # ================= RIGHT STACKED PAGES =================
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_install_page())
        self.pages.addWidget(self._build_guide_page())
        self.pages.addWidget(self._build_troubleshooting_page())
        self.pages.addWidget(self._build_commands_page())

        root.addWidget(self.pages, stretch=1)
        self.setCentralWidget(backdrop)
        self._refresh_nav_icons()

    def _make_nav_btn(self, text: str, icon_name: str, idx: int, checked: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("NavButton")
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setIconSize(QSize(17, 17))
        btn.setProperty("icon_name", icon_name)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self._switch_page(idx))
        self.nav_group.addButton(btn, idx)
        return btn

    def _switch_page(self, idx: int) -> None:
        self.pages.setCurrentIndex(idx)
        self._refresh_nav_icons()

    def _refresh_nav_icons(self) -> None:
        t = get_tokens("dark")
        for btn in (self.nav_install, self.nav_guide, self.nav_trouble, self.nav_cmds):
            icon_name = str(btn.property("icon_name") or "info")
            col = "#FFFFFF" if btn.isChecked() else t.text_secondary
            btn.setIcon(make_icon(icon_name, col, 17))

    # ================= PAGE 0: INSTALLER =================
    def _build_install_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("TransparentPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # Header
        hdr = GlassFrame(variant="bar", radius=18)
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(20, 14, 20, 14)
        hl.setSpacing(3)
        title = QLabel("Установка Classroom Manager")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "Выберите роль компьютера — установщик автоматически скопирует программу, "
            "откроет порты Брандмауэра Windows и настроит автозагрузку."
        )
        sub.setObjectName("MutedLabel")
        sub.setWordWrap(True)
        hl.addWidget(title)
        hl.addWidget(sub)
        lay.addWidget(hdr)

        # Scrollable form body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("TransparentPage")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 4, 0)
        bl.setSpacing(12)

        # Role Selection Card
        role_card = GlassFrame(variant="card", radius=16)
        rl = QVBoxLayout(role_card)
        rl.setContentsMargins(18, 14, 18, 16)
        rl.setSpacing(8)
        r_hdr = QLabel("1. ВЫБЕРИТЕ, ЧТО УСТАНОВИТЬ НА ЭТОТ КОМПЬЮТЕР")
        r_hdr.setObjectName("SectionLabel")
        rl.addWidget(r_hdr)

        self.rb_teacher = QRadioButton("Компьютер учителя (ClassroomTeacher.exe — панель управления классом)")
        self.rb_student = QRadioButton("Компьютер ученика (ClassroomStudent.exe — фоновый агент в трее)")
        self.rb_both = QRadioButton("Установить оба приложения (удобно для тестирования на одном ПК)")
        self.rb_teacher.setChecked(True)
        self.rb_teacher.toggled.connect(self._on_role_changed)
        self.rb_student.toggled.connect(self._on_role_changed)
        self.rb_both.toggled.connect(self._on_role_changed)

        rl.addWidget(self.rb_teacher)
        rl.addWidget(self.rb_student)
        rl.addWidget(self.rb_both)
        bl.addWidget(role_card)

        # Folder & Automation Options Card
        opt_card = GlassFrame(variant="card", radius=16)
        ol = QVBoxLayout(opt_card)
        ol.setContentsMargins(18, 14, 18, 16)
        ol.setSpacing(10)
        o_hdr = QLabel("2. ПАПКА И АВТОМАТИЧЕСКАЯ НАСТРОЙКА WINDOWS")
        o_hdr.setObjectName("SectionLabel")
        ol.addWidget(o_hdr)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self.dir_edit = QLineEdit(str(default_install_dir()))
        browse_btn = QPushButton("Обзор...")
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._pick_install_dir)
        dir_row.addWidget(self.dir_edit, stretch=1)
        dir_row.addWidget(browse_btn)
        ol.addLayout(dir_row)

        self.chk_firewall = QCheckBox("Автоматически открыть порты LAN в Брандмауэре Windows (PowerShell-скрипт)")
        self.chk_firewall.setChecked(True)
        self.chk_autostart = QCheckBox("Добавить в автозагрузку Windows при входе в систему")
        self.chk_autostart.setChecked(True)
        self.chk_shortcuts = QCheckBox("Создать ярлыки (Рабочий стол / меню «Пуск»)")
        self.chk_shortcuts.setChecked(True)
        self.chk_launch = QCheckBox("Запустить приложение сразу после установки")
        self.chk_launch.setChecked(True)

        ol.addWidget(self.chk_firewall)
        ol.addWidget(self.chk_autostart)
        ol.addWidget(self.chk_shortcuts)
        ol.addWidget(self.chk_launch)
        bl.addWidget(opt_card)

        # Optional Student Pre-Configuration Card (shown only when Student is selected)
        self.student_pre_card = GlassFrame(variant="card", radius=16)
        sl = QVBoxLayout(self.student_pre_card)
        sl.setContentsMargins(18, 14, 18, 16)
        sl.setSpacing(8)
        s_hdr = QLabel("3. БЫСТРАЯ ПРЕДНАСТРОЙКА УЧЕНИКА (НЕОБЯЗАТЕЛЬНО)")
        s_hdr.setObjectName("SectionLabel")
        s_sub = QLabel(
            "Если заполните эти поля, агент ученика сразу подключится к вашему кабинету без окна первого запуска. "
            "Если оставить пустыми — настройки спросит при первом старте."
        )
        s_sub.setObjectName("MutedLabel")
        s_sub.setWordWrap(True)
        sl.addWidget(s_hdr)
        sl.addWidget(s_sub)

        s_form = QFormLayout()
        s_form.setSpacing(8)
        self.s_room_edit = QLineEdit()
        self.s_room_edit.setPlaceholderText("Например: Cab-101 или VR1")
        self.s_secret_edit = QLineEdit()
        self.s_secret_edit.setPlaceholderText("Ключ класса из панели учителя (например: 6JR2-XGZ2-4PUE)")
        self.s_pwd_edit = QLineEdit()
        self.s_pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.s_pwd_edit.setPlaceholderText("Пароль для доступа к настройкам/выходу (мин. 4 символа)")
        self.s_name_edit = QLineEdit()
        self.s_name_edit.setPlaceholderText("Например: PC1 (необязательно)")

        s_form.addRow("ID кабинета:", self.s_room_edit)
        s_form.addRow("Ключ класса (PSK):", self.s_secret_edit)
        s_form.addRow("Пароль админа:", self.s_pwd_edit)
        s_form.addRow("Имя ПК / парты:", self.s_name_edit)
        sl.addLayout(s_form)
        self.student_pre_card.setVisible(False)
        bl.addWidget(self.student_pre_card)

        # Progress & Log Card
        prog_card = GlassFrame(variant="card", radius=16)
        pl = QVBoxLayout(prog_card)
        pl.setContentsMargins(18, 14, 18, 14)
        pl.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        pl.addWidget(self.progress_bar)

        self.log_box = QPlainTextEdit()
        self.log_box.setObjectName("ConsoleBox")
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(96)
        self.log_box.setMaximumHeight(135)
        self.log_box.setPlaceholderText("Нажмите «Установить», чтобы начать установку...")
        pl.addWidget(self.log_box)
        bl.addWidget(prog_card)

        bl.addStretch(1)
        scroll.setWidget(body)
        lay.addWidget(scroll, stretch=1)

        # Bottom Action Row
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.install_btn = QPushButton("Установить Classroom Manager")
        self.install_btn.setProperty("accent", "primary")
        self.install_btn.setIcon(make_icon("download", "#FFFFFF", 16))
        self.install_btn.setIconSize(QSize(16, 16))
        self.install_btn.setMinimumHeight(40)
        self.install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_btn.clicked.connect(self._start_install)
        btn_row.addWidget(self.install_btn)
        lay.addLayout(btn_row)
        return page

    # ================= PAGE 1: GUIDE =================
    def _build_guide_page(self) -> QWidget:
        return self._make_info_scroll_page(
            "Инструкция по запуску и работе",
            "Краткое пошаговое руководство по настройке класса за 2 минуты",
            [
                (
                    "1. Установка на компьютер учителя",
                    "• Выберите «Компьютер учителя» на вкладке «Установка» и нажмите «Установить».\n"
                    "• При первом запуске ClassroomTeacher.exe откроется мастер: задайте пароль учителя, ID кабинета (например, VR1) и сохраните сгенерированный Ключ класса.\n"
                    "• В верхней панели вы можете добавлять дополнительные кабинеты (+), переключаться между ними или выбрать «Все кабинеты».",
                ),
                (
                    "2. Установка на компьютеры учеников",
                    "• Запустите этот же установщик на ПК ученика и выберите «Компьютер ученика».\n"
                    "• Можно сразу ввести ID кабинета, Ключ класса и пароль администратора прямо в установщике — агент сам добавится в автозагрузку, откроет Брандмауэр и подключится.\n"
                    "• Агент работает скрыто в трее (зелёный значок = подключён). Настройки и выход открываются по горячей клавише Ctrl+Alt+Shift+M + пароль.",
                ),
                (
                    "3. Работа нескольких учителей и нескольких кабинетов одновременно",
                    "• Начиная с v3.0.0 ученический агент поддерживает одновременное подключение к нескольким ПК учителей!\n"
                    "• Если два учителя добавили один и тот же кабинет (с одинаковым ID и Ключом класса), оба учителя будут одновременно видеть и управлять компьютерами этого кабинета.\n"
                    "• Один учитель также может добавить сколько угодно кабинетов и следить за всеми сразу.",
                ),
                (
                    "4. Быстрое переключение мониторов и 60 FPS",
                    "• Если у ученика 2+ монитора, прямо на его карточке рядом с ONLINE появится кнопка «Экран 1» — нажмите на неё, чтобы мгновенно переключить миниатюру на «Экран 2».\n"
                    "• При двойном клике по карточке открывается управление на весь экран с режимами до 60 FPS («Плавный 60 FPS 1080p» / «Игровой 60 FPS 720p» / «HD Чёткий 30 FPS»).",
                ),
            ],
        )

    # ================= PAGE 2: TROUBLESHOOTING =================
    def _build_troubleshooting_page(self) -> QWidget:
        return self._make_info_scroll_page(
            "Решение проблем",
            "Частые вопросы при развёртывании в школьной локальной сети",
            [
                (
                    "Компьютер ученика не находит учителя (жёлтая иконка в трее)",
                    "• Убедитесь, что ПК учителя и ученика подключены к одной локальной сети (Wi-Fi или Ethernet). Статический IP настраивать НЕ нужно.\n"
                    "• Проверьте в Параметрах Windows на ПК учителя: Сеть и интернет → Свойства сети → профиль должен быть «Частная сеть» (не «Общедоступная»).\n"
                    "• Убедитесь, что порты TCP 45455 и UDP 45454 открыты в Брандмауэре Windows (установщик открывает их автоматически, либо запустите setup_firewall.ps1 от имени Администратора).",
                ),
                (
                    "В школе разные подсети / VLAN и UDP-автопоиск не доходит",
                    "• Посмотрите LAN IP учителя в левой нижней панели ClassroomTeacher.\n"
                    "• На ПК ученика нажмите Ctrl+Alt+Shift+M → введите пароль → укажите этот IP в поле «Резервный IP / Hostname». Можно указать несколько IP через запятую.",
                ),
                (
                    "Не срабатывают PowerShell-команды для маршрутов / Брандмауэра",
                    "• Для системных команд Windows (Remove-NetRoute, New-NetFirewallRule) агент ученика должен быть запущен от имени Администратора.\n"
                    "• Запускайте этот установщик от имени Администратора — тогда он создаст задачу в Планировщике с наивысшими правами автоматически.\n"
                    "• Для отключения интернета в браузерах без прав админа используйте готовую команду через Proxy + InternetSetOption из раздела «Полезные команды».",
                ),
                (
                    "Windows SmartScreen предупреждает при первом запуске .exe",
                    "• Так как приложение открытое и не подписано платным коммерческим сертификатом, Windows может показать «Система защитила ваш компьютер».\n"
                    "• Нажмите «Подробнее» → «Выполнить в любом случае». Исходный код полностью открыт на GitHub.",
                ),
            ],
        )

    # ================= PAGE 3: USEFUL COMMANDS =================
    def _build_commands_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("TransparentPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        hdr = GlassFrame(variant="bar", radius=18)
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(20, 14, 20, 14)
        hl.setSpacing(3)
        title = QLabel("Полезные PowerShell-команды")
        title.setObjectName("PageTitle")
        sub = QLabel("Нажмите «Копировать» и сохраните команду во вкладке «Терминал PowerShell» в панели учителя")
        sub.setObjectName("MutedLabel")
        hl.addWidget(title)
        hl.addWidget(sub)
        lay.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("TransparentPage")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 4, 0)
        bl.setSpacing(12)

        t = get_tokens("dark")
        for name, desc, code in USEFUL_COMMANDS:
            card = GlassFrame(variant="card", radius=16)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 14, 16, 14)
            cl.setSpacing(6)

            top = QHBoxLayout()
            lbl = QLabel(name)
            lbl.setStyleSheet("font-weight: 700; font-size: 13px;")
            copy_btn = QPushButton("Копировать")
            copy_btn.setIcon(make_icon("copy", t.accent, 14))
            copy_btn.setIconSize(QSize(14, 14))
            copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_btn.clicked.connect(lambda _c=False, c=code, n=name: self._copy_cmd(c, n))
            top.addWidget(lbl, stretch=1)
            top.addWidget(copy_btn)
            cl.addLayout(top)

            d_lbl = QLabel(desc)
            d_lbl.setObjectName("MutedLabel")
            d_lbl.setWordWrap(True)
            cl.addWidget(d_lbl)

            code_box = QPlainTextEdit(code)
            code_box.setObjectName("ConsoleBox")
            code_box.setReadOnly(True)
            mono = QFont()
            mono.setFamilies(["Cascadia Mono", "Consolas", "Courier New"])
            mono.setPointSize(9)
            code_box.setFont(mono)
            line_count = min(6, max(2, code.count("\n") + 1))
            code_box.setFixedHeight(line_count * 18 + 20)
            cl.addWidget(code_box)
            bl.addWidget(card)

        bl.addStretch(1)
        scroll.setWidget(body)
        lay.addWidget(scroll, stretch=1)
        return page

    def _make_info_scroll_page(
        self,
        title_text: str,
        subtitle_text: str,
        sections: list[tuple[str, str]],
    ) -> QWidget:
        page = QWidget()
        page.setObjectName("TransparentPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        hdr = GlassFrame(variant="bar", radius=18)
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(20, 14, 20, 14)
        hl.setSpacing(3)
        title = QLabel(title_text)
        title.setObjectName("PageTitle")
        sub = QLabel(subtitle_text)
        sub.setObjectName("MutedLabel")
        hl.addWidget(title)
        hl.addWidget(sub)
        lay.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("TransparentPage")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 4, 0)
        bl.setSpacing(12)

        for heading, text in sections:
            card = GlassFrame(variant="card", radius=16)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(18, 14, 18, 14)
            cl.setSpacing(6)
            h_lbl = QLabel(heading)
            h_lbl.setStyleSheet("font-weight: 700; font-size: 14px;")
            b_lbl = QLabel(text)
            b_lbl.setObjectName("MutedLabel")
            b_lbl.setWordWrap(True)
            b_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cl.addWidget(h_lbl)
            cl.addWidget(b_lbl)
            bl.addWidget(card)

        bl.addStretch(1)
        scroll.setWidget(body)
        lay.addWidget(scroll, stretch=1)
        return page

    def _copy_cmd(self, code: str, name: str) -> None:
        QApplication.clipboard().setText(code)
        QMessageBox.information(self, "Скопировано", f"Команда «{name}» скопирована в буфер обмена.")

    def _on_role_changed(self) -> None:
        show_student = self.rb_student.isChecked() or self.rb_both.isChecked()
        self.student_pre_card.setVisible(show_student)

    def _pick_install_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Выберите папку установки", self.dir_edit.text())
        if chosen:
            self.dir_edit.setText(chosen)

    def _start_install(self) -> None:
        if self._installing:
            return
        install_dir = Path(self.dir_edit.text().strip() or str(default_install_dir()))
        opts = InstallOptions(
            install_teacher=self.rb_teacher.isChecked() or self.rb_both.isChecked(),
            install_student=self.rb_student.isChecked() or self.rb_both.isChecked(),
            install_dir=install_dir,
            configure_firewall=self.chk_firewall.isChecked(),
            add_autostart=self.chk_autostart.isChecked(),
            create_shortcuts=self.chk_shortcuts.isChecked(),
            launch_after=self.chk_launch.isChecked(),
            student_room_id=self.s_room_edit.text().strip(),
            student_class_secret=self.s_secret_edit.text().strip(),
            student_admin_password=self.s_pwd_edit.text(),
            student_display_name=self.s_name_edit.text().strip(),
        )

        self._installing = True
        self.install_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_box.clear()

        def _worker() -> None:
            ok, _exes = run_installation(
                opts,
                log=self._signals.log_line.emit,
                on_progress=self._signals.progress.emit,
            )
            self._signals.finished.emit(ok)

        threading.Thread(target=_worker, daemon=True).start()

    def _append_log(self, line: str) -> None:
        self.log_box.appendPlainText(line)

    def _set_progress(self, pct: int) -> None:
        self.progress_bar.setValue(pct)

    def _on_install_finished(self, ok: bool) -> None:
        self._installing = False
        self.install_btn.setEnabled(True)
        if ok:
            QMessageBox.information(
                self,
                "Установка завершена",
                "Classroom Manager успешно установлен и настроен!\n"
                "Если нужно, откройте разделы «Инструкция» или «Полезные команды» слева.",
            )
        else:
            QMessageBox.warning(
                self,
                "Ошибка установки",
                "Во время установки возникла ошибка. Подробности смотрите в журнале выше.",
            )


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ClassroomManager Installer")
    # Strictly dark theme only for the installer (no light theme switcher)
    app.setStyleSheet(get_stylesheet("dark"))
    win = ClassroomInstallerWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
