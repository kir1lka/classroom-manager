"""Shared dark theme stylesheet and dynamic icon helpers for both desktop apps."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

DARK_STYLE = """
QWidget {
    background-color: #0f172a;
    color: #e2e8f0;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #0f172a;
}
QFrame#HeaderBar {
    background-color: #1e293b;
    border-bottom: 1px solid #334155;
    border-radius: 0px;
}
QFrame#StudentCard {
    background-color: #1e293b;
    border: 2px solid #334155;
    border-radius: 10px;
}
QFrame#StudentCard[selected="true"] {
    border: 2px solid #38bdf8;
    background-color: #1e3a5f;
}
QFrame#StudentCard[locked="true"] {
    border: 2px solid #ef4444;
}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #0b1220;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: #2563eb;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #38bdf8;
}
QPushButton {
    background-color: #1e293b;
    color: #f1f5f9;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #334155;
    border-color: #64748b;
}
QPushButton:pressed {
    background-color: #0f172a;
}
QPushButton:disabled {
    color: #64748b;
    background-color: #162032;
    border-color: #1e293b;
}
QPushButton[accent="primary"] {
    background-color: #2563eb;
    border-color: #3b82f6;
    color: #ffffff;
}
QPushButton[accent="primary"]:hover {
    background-color: #1d4ed8;
}
QPushButton[accent="success"] {
    background-color: #059669;
    border-color: #10b981;
    color: #ffffff;
}
QPushButton[accent="success"]:hover {
    background-color: #047857;
}
QPushButton[accent="danger"] {
    background-color: #dc2626;
    border-color: #ef4444;
    color: #ffffff;
}
QPushButton[accent="danger"]:hover {
    background-color: #b91c1c;
}
QPushButton[accent="warning"] {
    background-color: #d97706;
    border-color: #f59e0b;
    color: #ffffff;
}
QPushButton[accent="warning"]:hover {
    background-color: #b45309;
}
QTabWidget::pane {
    border: 1px solid #334155;
    border-radius: 8px;
    background-color: #0f172a;
}
QTabBar::tab {
    background-color: #1e293b;
    color: #94a3b8;
    padding: 8px 18px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background-color: #2563eb;
    color: #ffffff;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QMenu {
    background-color: #1e293b;
    color: #f1f5f9;
    border: 1px solid #475569;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #2563eb;
}
QGroupBox {
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 600;
    color: #93c5fd;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}
QCheckBox {
    spacing: 8px;
}
QStatusBar {
    background-color: #1e293b;
    color: #cbd5e1;
    border-top: 1px solid #334155;
}
"""


def make_status_icon(fill_hex: str, border_hex: str = "#0f172a") -> QIcon:
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
