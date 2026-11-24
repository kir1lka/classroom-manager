"""Spotify-inspired monochrome Dark & Light themes and dynamic icon helpers."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def get_stylesheet(theme: str = "dark") -> str:
    """Return a polished Spotify-style monochrome stylesheet ('dark' or 'light')."""
    if (theme or "dark").strip().lower() == "light":
        bg = "#F5F5F7"
        sidebar_bg = "#FFFFFF"
        surface = "#FFFFFF"
        surface_hover = "#F0F0F2"
        input_bg = "#FAFAFA"
        console_bg = "#141414"
        console_fg = "#E5E5E5"
        border = "#E4E4E7"
        border_strong = "#D4D4D8"
        text = "#111111"
        text_muted = "#63636B"
        primary_bg = "#18181B"
        primary_fg = "#FFFFFF"
        primary_hover = "#2E2E32"
        primary_border = "#18181B"
        nav_active_bg = "#EBEBEF"
        nav_active_fg = "#111111"
        card_selected_bg = "#F4F4F6"
        card_selected_border = "#141414"
        badge_online_bg = "#DCFCE7"
        badge_online_fg = "#166534"
        badge_ban_bg = "#FEE2E2"
        badge_ban_fg = "#B91C1C"
        preview_bg = "#121212"
    else:
        bg = "#121212"
        sidebar_bg = "#000000"
        surface = "#181818"
        surface_hover = "#242424"
        input_bg = "#101010"
        console_bg = "#0A0A0A"
        console_fg = "#E5E5E5"
        border = "#282828"
        border_strong = "#3E3E3E"
        text = "#FFFFFF"
        text_muted = "#A3A3A3"
        primary_bg = "#2A2A2E"
        primary_fg = "#FFFFFF"
        primary_hover = "#3A3A40"
        primary_border = "#52525B"
        nav_active_bg = "#242424"
        nav_active_fg = "#FFFFFF"
        card_selected_bg = "#202020"
        card_selected_border = "#E5E5E5"
        badge_online_bg = "#143521"
        badge_online_fg = "#1DB954"
        badge_ban_bg = "#3D1214"
        badge_ban_fg = "#F87171"
        preview_bg = "#0A0A0A"

    return f"""
QWidget {{
    background-color: {bg};
    color: {text};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {bg};
}}
QFrame#Sidebar {{
    background-color: {sidebar_bg};
    border-right: 1px solid {border};
}}
QFrame#SidebarCard {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: 10px;
}}
QFrame#TopBar {{
    background-color: {surface};
    border-bottom: 1px solid {border};
}}
QWidget#ContentArea {{
    background-color: {bg};
}}
QLabel {{
    background-color: transparent;
}}
QLabel#BrandTitle {{
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 0.6px;
    color: {text};
}}
QLabel#SectionLabel {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.9px;
    color: {text_muted};
}}
QLabel#PageTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {text};
}}
QLabel#MutedLabel {{
    color: {text_muted};
    font-size: 12px;
}}
QLabel#OnlineBadge {{
    background-color: {badge_online_bg};
    color: {badge_online_fg};
    padding: 3px 9px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel#BanBadge {{
    background-color: {badge_ban_bg};
    color: {badge_ban_fg};
    padding: 3px 9px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel#MonBadge {{
    background-color: {surface_hover};
    color: {text_muted};
    padding: 2px 7px;
    border-radius: 8px;
    font-size: 10px;
    font-weight: 600;
}}
QFrame#StudentCard {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: 12px;
}}
QFrame#StudentCard:hover {{
    background-color: {surface_hover};
    border-color: {border_strong};
}}
QFrame#StudentCard[selected="true"] {{
    background-color: {card_selected_bg};
    border: 2px solid {card_selected_border};
}}
QFrame#StudentCard[locked="true"] {{
    border: 2px solid #E53935;
}}
QLabel#PreviewBox {{
    background-color: {preview_bg};
    color: #737373;
    border-radius: 8px;
    border: 1px solid {border};
}}
QPushButton {{
    background-color: {surface};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: 10px;
    min-height: 20px;
    padding: 7px 14px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {surface_hover};
}}
QPushButton:pressed {{
    background-color: {bg};
}}
QPushButton:disabled {{
    color: {text_muted};
    background-color: {surface};
    border-color: {border};
}}
QPushButton#NavButton {{
    background-color: transparent;
    color: {text_muted};
    border: none;
    border-radius: 10px;
    min-height: 22px;
    padding: 9px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#NavButton:hover {{
    background-color: {surface_hover};
    color: {text};
}}
QPushButton#NavButton:checked {{
    background-color: {nav_active_bg};
    color: {nav_active_fg};
    font-weight: 700;
}}
QPushButton[accent="primary"] {{
    background-color: {primary_bg};
    color: {primary_fg};
    border: 1px solid {primary_border};
    border-radius: 14px;
    min-height: 22px;
    padding: 7px 16px;
    font-weight: 700;
}}
QPushButton[accent="primary"]:hover {{
    background-color: {primary_hover};
}}
QPushButton[accent="success"] {{
    background-color: #1DB954;
    color: #09090B;
    border: 1px solid #1DB954;
    border-radius: 14px;
    min-height: 22px;
    padding: 7px 16px;
    font-weight: 700;
}}
QPushButton[accent="success"]:hover {{
    background-color: #1ED760;
}}
QPushButton[accent="danger"] {{
    background-color: #DC2626;
    color: #FFFFFF;
    border: 1px solid #DC2626;
    border-radius: 10px;
    min-height: 20px;
    padding: 7px 14px;
    font-weight: 700;
}}
QPushButton[accent="danger"]:hover {{
    background-color: #B91C1C;
}}
QPushButton[accent="warning"] {{
    background-color: #27272A;
    color: #F87171;
    border: 1px solid #DC2626;
    border-radius: 10px;
    min-height: 20px;
    padding: 7px 14px;
    font-weight: 700;
}}
QPushButton[accent="warning"]:hover {{
    background-color: #3F1517;
}}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget {{
    background-color: {input_bg};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: #1DB954;
    selection-color: #000000;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus, QListWidget:focus {{
    border: 1px solid {text};
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
}}
QListWidget::item:hover {{
    background-color: {surface_hover};
}}
QListWidget::item:selected {{
    background-color: {nav_active_bg};
    color: {nav_active_fg};
    font-weight: 700;
}}
QPlainTextEdit#ConsoleBox {{
    background-color: {console_bg};
    color: {console_fg};
    border: 1px solid {border};
    border-radius: 10px;
    font-family: "Consolas", monospace;
    font-size: 12px;
    padding: 10px;
}}
QScrollArea {{
    border: none;
    background-color: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {border_strong};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QMenu {{
    background-color: {surface};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 18px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {surface_hover};
}}
QGroupBox {{
    border: 1px solid {border};
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 12px;
    font-weight: 700;
    color: {text};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}
QProgressBar {{
    background-color: {input_bg};
    border: 1px solid {border};
    border-radius: 6px;
    text-align: center;
    height: 16px;
}}
QProgressBar::chunk {{
    background-color: #1DB954;
    border-radius: 5px;
}}
QStatusBar {{
    background-color: {sidebar_bg};
    color: {text_muted};
    border-top: 1px solid {border};
}}
"""


DARK_STYLE = get_stylesheet("dark")
LIGHT_STYLE = get_stylesheet("light")


def make_status_icon(fill_hex: str, border_hex: str = "#121212") -> QIcon:
    """Create a crisp circular status icon for system tray / window icon."""
    size = 64
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(border_hex), 4))
    painter.setBrush(QColor(fill_hex))
    painter.drawEllipse(6, 6, size - 12, size - 12)
    painter.end()
    return QIcon(pm)
