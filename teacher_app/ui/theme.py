"""iOS / macOS Liquid Glass design system: spatial backdrop, frosted glass panels, themes, and crisp vector icons."""

from __future__ import annotations

import ctypes
import math
import sys
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QDialog, QFrame, QWidget

_ACTIVE_THEME: str = "dark"


@dataclass(frozen=True)
class ThemeTokens:
    name: str
    is_dark: bool
    bg_base: str
    bg_alt: str
    text: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_soft: str
    accent_border: str
    success: str
    success_hover: str
    success_soft: str
    success_border: str
    warning: str
    warning_soft: str
    warning_border: str
    danger: str
    danger_hover: str
    danger_soft: str
    danger_border: str
    glass_bg: str
    glass_hover: str
    glass_pressed: str
    glass_border: str
    glass_border_strong: str
    input_bg: str
    input_focus_bg: str
    console_bg: str
    console_fg: str
    preview_bg: str
    menu_bg: str
    scrollbar: str


DARK_TOKENS = ThemeTokens(
    name="dark",
    is_dark=True,
    bg_base="#080C16",
    bg_alt="#121212",
    text="#F8FAFC",
    text_secondary="#CBD5E1",
    text_muted="#8B9BB4",
    accent="#0A84FF",
    accent_hover="#3399FF",
    accent_soft="rgba(10, 132, 255, 0.18)",
    accent_border="rgba(56, 166, 255, 0.48)",
    success="#30D158",
    success_hover="#28C04E",
    success_soft="rgba(48, 209, 88, 0.16)",
    success_border="rgba(48, 209, 88, 0.36)",
    warning="#FF9F0A",
    warning_soft="rgba(255, 159, 10, 0.15)",
    warning_border="rgba(255, 159, 10, 0.40)",
    danger="#FF453A",
    danger_hover="#E0352B",
    danger_soft="rgba(255, 69, 58, 0.15)",
    danger_border="rgba(255, 69, 58, 0.40)",
    glass_bg="rgba(255, 255, 255, 0.06)",
    glass_hover="rgba(255, 255, 255, 0.11)",
    glass_pressed="rgba(255, 255, 255, 0.04)",
    glass_border="rgba(255, 255, 255, 0.12)",
    glass_border_strong="rgba(255, 255, 255, 0.22)",
    input_bg="rgba(10, 15, 28, 0.62)",
    input_focus_bg="rgba(14, 21, 38, 0.82)",
    console_bg="rgba(6, 9, 18, 0.78)",
    console_fg="#E2E8F0",
    preview_bg="#121212",
    menu_bg="#131B2E",
    scrollbar="rgba(255, 255, 255, 0.18)",
)

LIGHT_TOKENS = ThemeTokens(
    name="light",
    is_dark=False,
    bg_base="#EEF3FB",
    bg_alt="#F5F5F7",
    text="#0F172A",
    text_secondary="#334155",
    text_muted="#64748B",
    accent="#007AFF",
    accent_hover="#0066DB",
    accent_soft="rgba(0, 122, 255, 0.13)",
    accent_border="rgba(0, 122, 255, 0.38)",
    success="#1EA94B",
    success_hover="#18923F",
    success_soft="rgba(30, 169, 75, 0.13)",
    success_border="rgba(30, 169, 75, 0.34)",
    warning="#D97706",
    warning_soft="rgba(245, 158, 11, 0.14)",
    warning_border="rgba(217, 119, 6, 0.34)",
    danger="#E11D48",
    danger_hover="#BE123C",
    danger_soft="rgba(225, 29, 72, 0.11)",
    danger_border="rgba(225, 29, 72, 0.32)",
    glass_bg="rgba(255, 255, 255, 0.68)",
    glass_hover="rgba(255, 255, 255, 0.90)",
    glass_pressed="rgba(241, 245, 249, 0.80)",
    glass_border="rgba(15, 23, 42, 0.09)",
    glass_border_strong="rgba(15, 23, 42, 0.17)",
    input_bg="rgba(255, 255, 255, 0.82)",
    input_focus_bg="#FFFFFF",
    console_bg="#0F172A",
    console_fg="#F1F5F9",
    preview_bg="#0F172A",
    menu_bg="#FFFFFF",
    scrollbar="rgba(15, 23, 42, 0.18)",
)


def normalize_theme(theme: str | None) -> str:
    return "light" if (theme or "dark").strip().lower() == "light" else "dark"


def set_active_theme(theme: str) -> ThemeTokens:
    global _ACTIVE_THEME
    _ACTIVE_THEME = normalize_theme(theme)
    return get_tokens(_ACTIVE_THEME)


def get_active_theme() -> str:
    return _ACTIVE_THEME


def get_tokens(theme: str | None = None) -> ThemeTokens:
    mode = normalize_theme(theme if theme is not None else _ACTIVE_THEME)
    return LIGHT_TOKENS if mode == "light" else DARK_TOKENS


def apply_window_chrome(widget: QWidget, theme: str | None = None) -> None:
    """Apply matching dark/light native Windows 11 DWM titlebar chrome when supported."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        use_dark = ctypes.c_int(1 if get_tokens(theme).is_dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.wintypes.HWND(hwnd),
            20,  # DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.byref(use_dark),
            ctypes.sizeof(use_dark),
        )
    except Exception:
        pass


def set_windows_app_id(app_id: str) -> None:
    """Register explicit Windows AppUserModelID so the taskbar displays our custom icon instead of python.exe."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(str(app_id))
    except Exception:
        pass


def paint_liquid_backdrop(painter: QPainter, rect: QRectF | object, tokens: ThemeTokens) -> None:
    """Render a soft, serene iOS-inspired spatial aurora mesh behind frosted glass layers."""
    w = max(1.0, float(rect.width()))
    h = max(1.0, float(rect.height()))
    r = QRectF(0.0, 0.0, w, h)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    base_grad = QLinearGradient(0.0, 0.0, w, h)
    if tokens.is_dark:
        base_grad.setColorAt(0.0, QColor("#070B14"))
        base_grad.setColorAt(0.5, QColor("#0B1222"))
        base_grad.setColorAt(1.0, QColor("#080D19"))
    else:
        base_grad.setColorAt(0.0, QColor("#EAF1FB"))
        base_grad.setColorAt(0.5, QColor("#F4F7FC"))
        base_grad.setColorAt(1.0, QColor("#E8EFFA"))
    painter.fillRect(r, base_grad)

    # Ambient bloom 1: Top-left cyan/sky refraction
    bloom1 = QRadialGradient(QPointF(w * 0.14, h * 0.12), max(w, h) * 0.58)
    bloom1.setColorAt(0.0, QColor(56, 189, 248, 34 if tokens.is_dark else 42))
    bloom1.setColorAt(0.55, QColor(56, 189, 248, 10 if tokens.is_dark else 14))
    bloom1.setColorAt(1.0, QColor(56, 189, 248, 0))
    painter.fillRect(r, bloom1)

    # Ambient bloom 2: Top-right indigo/iris refraction
    bloom2 = QRadialGradient(QPointF(w * 0.88, h * 0.18), max(w, h) * 0.55)
    bloom2.setColorAt(0.0, QColor(99, 102, 241, 36 if tokens.is_dark else 36))
    bloom2.setColorAt(0.55, QColor(99, 102, 241, 10 if tokens.is_dark else 12))
    bloom2.setColorAt(1.0, QColor(99, 102, 241, 0))
    painter.fillRect(r, bloom2)

    # Ambient bloom 3: Bottom-center subtle mint/teal glow
    bloom3 = QRadialGradient(QPointF(w * 0.52, h * 0.92), max(w, h) * 0.50)
    bloom3.setColorAt(0.0, QColor(20, 184, 166, 22 if tokens.is_dark else 26))
    bloom3.setColorAt(1.0, QColor(20, 184, 166, 0))
    painter.fillRect(r, bloom3)

    painter.restore()


class LiquidBackdropWidget(QWidget):
    """Root container that paints the Liquid Glass spatial canvas behind child glass panels."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("LiquidRoot")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        paint_liquid_backdrop(painter, self.rect(), get_tokens())
        painter.end()


class LiquidDialog(QDialog):
    """Modal or modeless dialog with spatial Liquid Glass backdrop and native dark/light titlebar."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    def showEvent(self, event) -> None:
        apply_window_chrome(self)
        super().showEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        paint_liquid_backdrop(painter, self.rect(), get_tokens())
        painter.end()


class GlassFrame(QFrame):
    """Frosted Liquid Glass container with specular top sheen and diagonal refraction rim."""

    def __init__(
        self,
        variant: str = "card",
        radius: float = 18.0,
        interactive: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._variant = variant
        self._radius = float(radius)
        self._interactive = interactive
        self._hovered = False
        self.setObjectName("GlassFrame")
        if interactive:
            self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def enterEvent(self, event) -> None:
        if self._interactive:
            self._hovered = True
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._interactive:
            self._hovered = False
            self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        tokens = get_tokens()
        is_dark = tokens.is_dark
        selected = self.property("selected") == "true"
        locked = self.property("locked") == "true"

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        r = self._radius

        # 1. Outer ambient glow for selected or locked cards
        if locked:
            glow_rect = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
            painter.setPen(QPen(QColor(255, 69, 58, 70 if is_dark else 55), 2.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(glow_rect, r + 1.0, r + 1.0)
        elif selected:
            glow_rect = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
            painter.setPen(QPen(QColor(10, 132, 255, 85 if is_dark else 65), 2.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(glow_rect, r + 1.0, r + 1.0)

        # 2. Translucent frosted glass body fill
        if is_dark:
            if self._variant == "sidebar":
                fill = QColor(14, 21, 36, 188)
            elif self._variant == "bar":
                fill = QColor(16, 24, 42, 175)
            elif self._variant == "inset":
                fill = QColor(8, 13, 24, 155)
            elif self._variant == "accent":
                fill = QColor(10, 132, 255, 36)
            else:
                if selected:
                    fill = QColor(20, 36, 66, 200)
                elif self._hovered and self._interactive:
                    fill = QColor(26, 37, 60, 195)
                else:
                    fill = QColor(18, 26, 44, 168)
        else:
            if self._variant == "sidebar":
                fill = QColor(255, 255, 255, 196)
            elif self._variant == "bar":
                fill = QColor(255, 255, 255, 190)
            elif self._variant == "inset":
                fill = QColor(241, 245, 252, 195)
            elif self._variant == "accent":
                fill = QColor(0, 122, 255, 24)
            else:
                if selected:
                    fill = QColor(238, 246, 255, 232)
                elif self._hovered and self._interactive:
                    fill = QColor(255, 255, 255, 238)
                else:
                    fill = QColor(255, 255, 255, 198)

        path = QPainterPath()
        path.addRoundedRect(rect, r, r)
        painter.fillPath(path, fill)

        # 3. Soft top specular highlight (Liquid Glass surface sheen)
        sheen = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + rect.height() * 0.48)
        if is_dark:
            top_alpha = 24 if (self._hovered and self._interactive) else 15
            sheen.setColorAt(0.0, QColor(255, 255, 255, top_alpha))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        else:
            sheen.setColorAt(0.0, QColor(255, 255, 255, 145))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, sheen)

        # 4. Crisp 1px diagonal refraction rim
        if locked:
            rim_pen = QPen(QColor("#FF453A" if is_dark else "#E11D48"), 1.6)
        elif selected:
            rim_pen = QPen(QColor("#0A84FF" if is_dark else "#007AFF"), 1.7)
        else:
            rim_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            if is_dark:
                hi = 72 if (self._hovered and self._interactive) else 50
                rim_grad.setColorAt(0.0, QColor(255, 255, 255, hi))
                rim_grad.setColorAt(0.45, QColor(255, 255, 255, 20))
                rim_grad.setColorAt(1.0, QColor(125, 175, 255, 34))
            else:
                rim_grad.setColorAt(0.0, QColor(255, 255, 255, 245))
                rim_grad.setColorAt(0.5, QColor(148, 163, 184, 58))
                rim_grad.setColorAt(1.0, QColor(100, 116, 139, 72))
            rim_pen = QPen(rim_grad, 1.15)

        painter.setPen(rim_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, r, r)
        painter.end()


def get_stylesheet(theme: str = "dark") -> str:
    """Return the Liquid Glass Qt stylesheet ('dark' or 'light')."""
    t = set_active_theme(theme)

    nav_active_bg = "rgba(10, 132, 255, 0.20)" if t.is_dark else "rgba(0, 122, 255, 0.13)"
    nav_active_border = "rgba(56, 166, 255, 0.42)" if t.is_dark else "rgba(0, 122, 255, 0.30)"
    nav_active_fg = "#FFFFFF" if t.is_dark else "#005EC4"
    list_sel_bg = nav_active_bg
    list_sel_fg = nav_active_fg
    disabled_bg = "rgba(255, 255, 255, 0.02)" if t.is_dark else "rgba(15, 23, 42, 0.035)"
    disabled_fg = "rgba(148, 163, 184, 0.34)" if t.is_dark else "rgba(100, 116, 139, 0.42)"
    disabled_border = "rgba(255, 255, 255, 0.07)" if t.is_dark else "rgba(15, 23, 42, 0.10)"

    return f"""
/* Liquid Glass Theme ({t.name}) — fallback surface token {t.bg_alt} */
QWidget {{
    color: {t.text};
    font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {t.bg_base};
}}
QWidget#LiquidRoot, QWidget#ContentArea, QWidget#TransparentPage {{
    background: transparent;
}}
GlassFrame, QFrame#GlassFrame {{
    background: transparent;
    border: none;
}}
QLabel {{
    background: transparent;
}}
QLabel#BrandTitle {{
    font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 0.3px;
    color: {t.text};
}}
QLabel#BrandSub {{
    font-size: 11px;
    font-weight: 600;
    color: {t.text_muted};
}}
QLabel#SectionLabel {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.1px;
    color: {t.text_muted};
}}
QLabel#PageTitle {{
    font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;
    font-size: 20px;
    font-weight: 700;
    color: {t.text};
}}
QLabel#PageSubtitle {{
    font-size: 12px;
    color: {t.text_muted};
}}
QLabel#DialogTitle {{
    font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;
    font-size: 19px;
    font-weight: 700;
    color: {t.text};
}}
QLabel#CardSectionTitle {{
    font-size: 13px;
    font-weight: 700;
    color: {t.text};
}}
QLabel#MutedLabel {{
    color: {t.text_muted};
    font-size: 12px;
}}
QLabel#OnlineBadge {{
    background-color: {t.success_soft};
    color: {t.success};
    border: 1px solid {t.success_border};
    padding: 3px 10px;
    border-radius: 8px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel#BanBadge {{
    background-color: {t.danger_soft};
    color: {t.danger};
    border: 1px solid {t.danger_border};
    padding: 3px 10px;
    border-radius: 8px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel#AccentBadge {{
    background-color: {t.accent_soft};
    color: {t.accent};
    border: 1px solid {t.accent_border};
    padding: 3px 10px;
    border-radius: 8px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel#MonBadge {{
    background-color: {t.glass_bg};
    color: {t.text_secondary};
    border: 1px solid {t.glass_border};
    padding: 2px 8px;
    border-radius: 7px;
    font-size: 10px;
    font-weight: 600;
}}
QLabel#PreviewBox {{
    background-color: {t.preview_bg};
    color: #64748B;
    border-radius: 12px;
    border: 1px solid {t.glass_border};
    font-size: 12px;
}}
QPushButton {{
    background-color: {t.glass_bg};
    color: {t.text};
    border: 1px solid {t.glass_border};
    border-radius: 12px;
    min-height: 20px;
    padding: 7px 14px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {t.glass_hover};
    border-color: {t.glass_border_strong};
}}
QPushButton:pressed {{
    background-color: {t.glass_pressed};
}}
QPushButton:checked {{
    background-color: {nav_active_bg};
    color: {nav_active_fg};
    border: 1.5px solid {t.accent};
    font-weight: 700;
}}
QPushButton:disabled {{
    color: {disabled_fg};
    background-color: {disabled_bg};
    border: 1px dashed {disabled_border};
}}
QPushButton#NavButton {{
    background-color: transparent;
    color: {t.text_secondary};
    border: 1px solid transparent;
    border-radius: 12px;
    min-height: 22px;
    padding: 9px 12px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#NavButton:hover {{
    background-color: {t.glass_bg};
    color: {t.text};
}}
QPushButton#NavButton:checked {{
    background-color: {nav_active_bg};
    border: 1px solid {nav_active_border};
    color: {nav_active_fg};
    font-weight: 700;
}}
QPushButton#IconPill {{
    background-color: {t.glass_bg};
    border: 1px solid {t.glass_border};
    border-radius: 10px;
    padding: 5px;
    min-height: 18px;
    min-width: 18px;
}}
QPushButton#IconPill:hover {{
    background-color: {t.glass_hover};
    border-color: {t.accent_border};
}}
QPushButton#IconPill:checked {{
    background-color: {nav_active_bg};
    border: 1.5px solid {t.accent};
}}
QPushButton#IconPill:disabled {{
    background-color: {disabled_bg};
    border: 1px dashed {disabled_border};
    color: {disabled_fg};
}}
QPushButton[accent="primary"] {{
    background-color: {t.accent};
    color: #FFFFFF;
    border: 1px solid {t.accent_border};
    border-radius: 12px;
    min-height: 22px;
    padding: 7px 16px;
    font-weight: 700;
}}
QPushButton[accent="primary"]:hover {{
    background-color: {t.accent_hover};
}}
QPushButton[accent="primary"]:disabled {{
    background-color: {disabled_bg};
    color: {disabled_fg};
    border: 1px dashed {disabled_border};
}}
QPushButton[accent="success"] {{
    background-color: {t.success};
    color: #FFFFFF;
    border: 1px solid {t.success_border};
    border-radius: 12px;
    min-height: 22px;
    padding: 7px 16px;
    font-weight: 700;
}}
QPushButton[accent="success"]:hover {{
    background-color: {t.success_hover};
}}
QPushButton[accent="success"]:disabled {{
    background-color: {disabled_bg};
    color: {disabled_fg};
    border: 1px dashed {disabled_border};
}}
QPushButton[accent="warning"] {{
    background-color: {t.danger_soft};
    color: {t.danger};
    border: 1px solid {t.danger_border};
    border-radius: 12px;
    min-height: 20px;
    padding: 7px 14px;
    font-weight: 700;
}}
QPushButton[accent="warning"]:hover {{
    background-color: {t.danger};
    color: #FFFFFF;
}}
QPushButton[accent="warning"]:disabled {{
    background-color: {disabled_bg};
    color: {disabled_fg};
    border: 1px dashed {disabled_border};
}}
QPushButton[accent="danger"] {{
    background-color: {t.danger};
    color: #FFFFFF;
    border: 1px solid {t.danger};
    border-radius: 12px;
    min-height: 20px;
    padding: 7px 14px;
    font-weight: 700;
}}
QPushButton[accent="danger"]:hover {{
    background-color: {t.danger_hover};
}}
QPushButton[accent="danger"]:disabled {{
    background-color: {disabled_bg};
    color: {disabled_fg};
    border: 1px dashed {disabled_border};
}}
QPushButton[accent="ghost"] {{
    background-color: transparent;
    color: {t.text_secondary};
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 6px 10px;
}}
QPushButton[accent="ghost"]:hover {{
    background-color: {t.glass_bg};
    color: {t.text};
}}
QPushButton::menu-indicator {{
    width: 10px;
    subcontrol-position: right center;
    subcontrol-origin: padding;
    right: 8px;
}}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {t.input_bg};
    color: {t.text};
    border: 1px solid {t.glass_border_strong};
    border-radius: 11px;
    padding: 7px 12px;
    min-height: 20px;
    selection-background-color: {t.accent};
    selection-color: #FFFFFF;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    background-color: {t.input_focus_bg};
    border: 1.5px solid {t.accent};
}}
QLineEdit#SearchPill {{
    border-radius: 15px;
    padding: 6px 14px;
    min-height: 18px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: transparent;
    border: none;
    width: 18px;
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
    background: transparent;
}}
QComboBox QAbstractItemView {{
    background-color: {t.menu_bg};
    color: {t.text};
    border: 1px solid {t.glass_border_strong};
    border-radius: 10px;
    padding: 4px;
    selection-background-color: {nav_active_bg};
    selection-color: {nav_active_fg};
    outline: none;
}}
QListWidget {{
    background-color: {t.input_bg};
    color: {t.text};
    border: 1px solid {t.glass_border};
    border-radius: 12px;
    padding: 6px;
    outline: none;
}}
QListWidget::item {{
    padding: 9px 12px;
    border-radius: 9px;
    margin-bottom: 2px;
}}
QListWidget::item:hover {{
    background-color: {t.glass_bg};
}}
QListWidget::item:selected {{
    background-color: {list_sel_bg};
    color: {list_sel_fg};
    font-weight: 700;
}}
QPlainTextEdit#ConsoleBox {{
    background-color: {t.console_bg};
    color: {t.console_fg};
    border: 1px solid {t.glass_border};
    border-radius: 14px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    padding: 12px;
}}
QCheckBox {{
    spacing: 8px;
    color: {t.text_secondary};
    background: transparent;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1px solid {t.glass_border_strong};
    background-color: {t.input_bg};
}}
QCheckBox::indicator:checked {{
    background-color: {t.accent};
    border-color: {t.accent};
}}
QScrollArea, QScrollArea > QWidget > QWidget {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: {t.scrollbar};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t.text_muted};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background: {t.scrollbar};
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QSplitter::handle {{
    background: transparent;
    width: 16px;
}}
QMenu {{
    background-color: {t.menu_bg};
    color: {t.text};
    border: 1px solid {t.glass_border_strong};
    border-radius: 12px;
    padding: 6px;
}}
QMenu::item {{
    padding: 8px 18px;
    border-radius: 8px;
}}
QMenu::item:selected {{
    background-color: {nav_active_bg};
    color: {nav_active_fg};
}}
QMenu::separator {{
    height: 1px;
    background: {t.glass_border};
    margin: 5px 8px;
}}
QGroupBox {{
    background-color: {t.glass_bg};
    border: 1px solid {t.glass_border};
    border-radius: 14px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
    font-weight: 700;
    color: {t.text};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: {t.text_secondary};
}}
QProgressBar {{
    background-color: {t.input_bg};
    border: 1px solid {t.glass_border};
    border-radius: 8px;
    text-align: center;
    font-size: 11px;
    font-weight: 700;
    color: {t.text};
    min-height: 16px;
    max-height: 16px;
}}
QProgressBar::chunk {{
    background-color: {t.accent};
    border-radius: 7px;
}}
QStatusBar {{
    background: transparent;
    color: {t.text_muted};
    border: none;
    font-size: 11px;
    padding: 0px 10px 4px 10px;
}}
QToolTip {{
    background-color: {t.menu_bg};
    color: {t.text};
    border: 1px solid {t.glass_border_strong};
    border-radius: 8px;
    padding: 5px 9px;
}}
QMessageBox, QInputDialog {{
    background-color: {t.bg_base};
}}
"""


DARK_STYLE = get_stylesheet("dark")
LIGHT_STYLE = get_stylesheet("light")
_ACTIVE_THEME = "dark"


def make_status_icon(fill_hex: str, border_hex: str = "#0B1120") -> QIcon:
    """Create a luminous Liquid Glass status icon for system tray or window emblem."""
    size = 64
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Outer frosted squircle
    rect = QRectF(4, 4, size - 8, size - 8)
    bg_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    bg_grad.setColorAt(0.0, QColor("#16223B"))
    bg_grad.setColorAt(1.0, QColor(border_hex))
    painter.setPen(QPen(QColor(255, 255, 255, 55), 2.0))
    painter.setBrush(bg_grad)
    painter.drawRoundedRect(rect, 16, 16)

    # Inner glowing status orb
    orb_rect = QRectF(17, 17, size - 34, size - 34)
    orb_grad = QRadialGradient(QPointF(size * 0.42, size * 0.38), size * 0.32)
    base_col = QColor(fill_hex)
    lighter = base_col.lighter(135)
    orb_grad.setColorAt(0.0, lighter)
    orb_grad.setColorAt(1.0, base_col)
    painter.setPen(QPen(QColor(255, 255, 255, 90), 1.5))
    painter.setBrush(orb_grad)
    painter.drawEllipse(orb_rect)

    painter.end()
    return QIcon(pm)


def make_brand_pixmap(size: int = 36) -> QPixmap:
    """Render an iOS-style Liquid Glass app squircle badge with a crisp classroom display glyph."""
    dpr = 2.0
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    rect = QRectF(1.5, 1.5, size - 3.0, size - 3.0)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor("#38BDF8"))
    grad.setColorAt(0.5, QColor("#0A84FF"))
    grad.setColorAt(1.0, QColor("#4F46E5"))

    painter.setPen(QPen(QColor(255, 255, 255, 110), 1.1))
    painter.setBrush(grad)
    painter.drawRoundedRect(rect, size * 0.28, size * 0.28)

    # Specular top gloss
    gloss = QLinearGradient(0, 1.5, 0, size * 0.5)
    gloss.setColorAt(0.0, QColor(255, 255, 255, 95))
    gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
    gloss_path = QPainterPath()
    gloss_path.addRoundedRect(rect, size * 0.28, size * 0.28)
    painter.fillPath(gloss_path, gloss)

    # White display glyph inside
    pen = QPen(QColor("#FFFFFF"), 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    scr = QRectF(size * 0.24, size * 0.27, size * 0.52, size * 0.36)
    painter.drawRoundedRect(scr, 3.0, 3.0)
    painter.drawLine(QPointF(size * 0.50, size * 0.63), QPointF(size * 0.50, size * 0.73))
    painter.drawLine(QPointF(size * 0.36, size * 0.73), QPointF(size * 0.64, size * 0.73))

    painter.end()
    return pm


def render_app_icon_pixmap(role: str = "teacher", size: int = 256) -> QPixmap:
    """Render a high-DPI iOS Liquid Glass squircle icon for Teacher or Student app (.ico, taskbar, titlebar)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    pad = max(1.0, s * 0.055)
    rect = QRectF(pad, pad, s - 2 * pad, s - 2 * pad)
    rad = s * 0.235

    # Outer Liquid Glass squircle gradient
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    if role == "student":
        grad.setColorAt(0.0, QColor("#34D399"))
        grad.setColorAt(0.5, QColor("#0EA5E9"))
        grad.setColorAt(1.0, QColor("#0F766E"))
    else:
        grad.setColorAt(0.0, QColor("#38BDF8"))
        grad.setColorAt(0.5, QColor("#0A84FF"))
        grad.setColorAt(1.0, QColor("#4338CA"))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(rect, rad, rad)

    # Inner frosted glass card layer
    inner = rect.adjusted(s * 0.12, s * 0.12, -s * 0.12, -s * 0.12)
    p.setBrush(QColor(255, 255, 255, 36))
    p.setPen(QPen(QColor(255, 255, 255, 95), max(1.0, s * 0.016)))
    p.drawRoundedRect(inner, rad * 0.68, rad * 0.68)

    # Top Liquid Glass specular sheen
    gloss = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + rect.height() * 0.52)
    gloss.setColorAt(0.0, QColor(255, 255, 255, 115))
    gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
    sq_path = QPainterPath()
    sq_path.addRoundedRect(rect, rad, rad)
    p.fillPath(sq_path, gloss)

    # Crisp diagonal glass rim
    rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
    rim.setColorAt(0.0, QColor(255, 255, 255, 190))
    rim.setColorAt(0.5, QColor(255, 255, 255, 55))
    rim.setColorAt(1.0, QColor(255, 255, 255, 110))
    p.setPen(QPen(rim, max(1.0, s * 0.022)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(rect, rad, rad)

    # Crisp central white vector glyph
    stroke = max(1.4, s * 0.052)
    glyph_pen = QPen(QColor("#FFFFFF"), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(glyph_pen)

    if role == "student":
        # Workstation monitor + connected status check
        scr = QRectF(s * 0.27, s * 0.28, s * 0.46, s * 0.33)
        p.drawRoundedRect(scr, s * 0.05, s * 0.05)
        p.drawLine(QPointF(s * 0.50, s * 0.61), QPointF(s * 0.50, s * 0.71))
        p.drawLine(QPointF(s * 0.37, s * 0.71), QPointF(s * 0.63, s * 0.71))
        check_pen = QPen(QColor("#FFFFFF"), max(1.3, s * 0.044), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(check_pen)
        p.drawLine(QPointF(s * 0.42, s * 0.44), QPointF(s * 0.48, s * 0.50))
        p.drawLine(QPointF(s * 0.48, s * 0.50), QPointF(s * 0.59, s * 0.39))
    else:
        # Teacher command center: 2x2 classroom screen grid glyph
        cell = s * 0.18
        gap = s * 0.06
        start_x = (s - (2 * cell + gap)) / 2.0
        start_y = (s - (2 * cell + gap)) / 2.0
        for ix in range(2):
            for iy in range(2):
                cx = start_x + ix * (cell + gap)
                cy = start_y + iy * (cell + gap)
                if ix == 0 and iy == 0:
                    p.setBrush(QColor(255, 255, 255, 235))
                else:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(cx, cy, cell, cell), s * 0.042, s * 0.042)

    p.end()
    return pm


def make_app_icon(role: str = "teacher") -> QIcon:
    """Build a multi-resolution QIcon (16..256px) for crisp taskbar, Alt+Tab, and window titlebars."""
    from pathlib import Path

    # Prefer bundled .ico if available alongside package/exe, while also populating multi-DPI pixmaps
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(render_app_icon_pixmap(role=role, size=sz))
    try:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        ico_file = base / "assets" / (f"{role}.ico")
        if ico_file.exists():
            disk_icon = QIcon(str(ico_file))
            if not disk_icon.isNull():
                return disk_icon
    except Exception:
        pass
    return icon


def make_icon(name: str, color: str | None = None, size: int = 18) -> QIcon:
    """Render crisp 2x HiDPI vector icons (SF Symbols / Lucide minimal line style)."""
    tokens = get_tokens()
    stroke_hex = color or tokens.text
    dpr = 2.0
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor(stroke_hex)
    pen = QPen(col, 1.65, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    s = float(size)
    m = s * 0.16
    w = s - 2 * m

    if name == "grid":
        g = w * 0.43
        gap = w - 2 * g
        for rx in (m, m + g + gap):
            for ry in (m, m + g + gap):
                p.drawRoundedRect(QRectF(rx, ry, g, g), 2.2, 2.2)

    elif name == "terminal":
        p.drawRoundedRect(QRectF(m, m + 1.0, w, w - 2.0), 3.2, 3.2)
        p.drawLine(QPointF(s * 0.30, s * 0.40), QPointF(s * 0.42, s * 0.50))
        p.drawLine(QPointF(s * 0.42, s * 0.50), QPointF(s * 0.30, s * 0.60))
        p.drawLine(QPointF(s * 0.48, s * 0.60), QPointF(s * 0.66, s * 0.60))

    elif name == "shield":
        path = QPainterPath()
        path.moveTo(s * 0.50, s * 0.15)
        path.lineTo(s * 0.80, s * 0.27)
        path.quadTo(s * 0.80, s * 0.64, s * 0.50, s * 0.85)
        path.quadTo(s * 0.20, s * 0.64, s * 0.20, s * 0.27)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.38, s * 0.50), QPointF(s * 0.47, s * 0.59))
        p.drawLine(QPointF(s * 0.47, s * 0.59), QPointF(s * 0.63, s * 0.42))

    elif name == "cast":
        p.drawRoundedRect(QRectF(m, s * 0.20, w, s * 0.52), 3.0, 3.0)
        p.drawLine(QPointF(s * 0.36, s * 0.82), QPointF(s * 0.64, s * 0.82))
        p.drawLine(QPointF(s * 0.50, s * 0.72), QPointF(s * 0.50, s * 0.82))
        p.setBrush(col)
        tri = QPolygonF([QPointF(s * 0.44, s * 0.36), QPointF(s * 0.44, s * 0.56), QPointF(s * 0.60, s * 0.46)])
        p.drawPolygon(tri)

    elif name == "stop":
        p.drawEllipse(QRectF(m, m, w, w))
        p.setBrush(col)
        sq = s * 0.28
        p.drawRoundedRect(QRectF((s - sq) / 2, (s - sq) / 2, sq, sq), 1.8, 1.8)

    elif name == "send_file":
        path = QPainterPath()
        path.moveTo(s * 0.16, s * 0.46)
        path.lineTo(s * 0.82, s * 0.18)
        path.lineTo(s * 0.56, s * 0.84)
        path.lineTo(s * 0.44, s * 0.56)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.44, s * 0.56), QPointF(s * 0.82, s * 0.18))

    elif name == "lock":
        body = QRectF(s * 0.23, s * 0.46, s * 0.54, s * 0.39)
        p.drawRoundedRect(body, 2.8, 2.8)
        shackle = QPainterPath()
        shackle.moveTo(s * 0.34, s * 0.46)
        shackle.lineTo(s * 0.34, s * 0.33)
        shackle.arcTo(QRectF(s * 0.34, s * 0.17, s * 0.32, s * 0.30), 180, -180)
        shackle.lineTo(s * 0.66, s * 0.46)
        p.drawPath(shackle)

    elif name == "unlock":
        body = QRectF(s * 0.23, s * 0.46, s * 0.54, s * 0.39)
        p.drawRoundedRect(body, 2.8, 2.8)
        shackle = QPainterPath()
        shackle.moveTo(s * 0.34, s * 0.46)
        shackle.lineTo(s * 0.34, s * 0.31)
        shackle.arcTo(QRectF(s * 0.34, s * 0.16, s * 0.32, s * 0.30), 180, -135)
        p.drawPath(shackle)

    elif name == "remote":
        p.drawRoundedRect(QRectF(m, s * 0.20, w, s * 0.48), 3.0, 3.0)
        p.drawLine(QPointF(s * 0.35, s * 0.80), QPointF(s * 0.65, s * 0.80))
        p.drawLine(QPointF(s * 0.50, s * 0.68), QPointF(s * 0.50, s * 0.80))
        p.drawLine(QPointF(s * 0.44, s * 0.38), QPointF(s * 0.56, s * 0.50))
        p.drawLine(QPointF(s * 0.44, s * 0.38), QPointF(s * 0.44, s * 0.48))
        p.drawLine(QPointF(s * 0.44, s * 0.38), QPointF(s * 0.54, s * 0.38))

    elif name == "message":
        path = QPainterPath()
        path.addRoundedRect(QRectF(m, s * 0.20, w, s * 0.50), 4.0, 4.0)
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.32, s * 0.70), QPointF(s * 0.24, s * 0.83))
        p.drawLine(QPointF(s * 0.24, s * 0.83), QPointF(s * 0.44, s * 0.70))

    elif name == "pulse":
        pts = [
            QPointF(s * 0.14, s * 0.52),
            QPointF(s * 0.32, s * 0.52),
            QPointF(s * 0.43, s * 0.24),
            QPointF(s * 0.56, s * 0.76),
            QPointF(s * 0.67, s * 0.52),
            QPointF(s * 0.86, s * 0.52),
        ]
        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])

    elif name == "power":
        arc_rect = QRectF(s * 0.22, s * 0.24, s * 0.56, s * 0.56)
        p.drawArc(arc_rect, 130 * 16, 280 * 16)
        p.drawLine(QPointF(s * 0.50, s * 0.16), QPointF(s * 0.50, s * 0.48))

    elif name == "search":
        p.drawEllipse(QRectF(s * 0.18, s * 0.18, s * 0.48, s * 0.48))
        p.drawLine(QPointF(s * 0.60, s * 0.60), QPointF(s * 0.82, s * 0.82))

    elif name == "sun":
        p.drawEllipse(QRectF(s * 0.32, s * 0.32, s * 0.36, s * 0.36))
        for deg in range(0, 360, 45):
            rad = math.radians(deg)
            p.drawLine(
                QPointF(s * 0.5 + math.cos(rad) * s * 0.27, s * 0.5 + math.sin(rad) * s * 0.27),
                QPointF(s * 0.5 + math.cos(rad) * s * 0.38, s * 0.5 + math.sin(rad) * s * 0.38),
            )

    elif name == "moon":
        path = QPainterPath()
        path.moveTo(s * 0.62, s * 0.20)
        path.arcTo(QRectF(s * 0.20, s * 0.20, s * 0.60, s * 0.60), 75, 225)
        path.arcTo(QRectF(s * 0.36, s * 0.12, s * 0.52, s * 0.52), 285, -195)
        p.drawPath(path)

    elif name == "settings":
        # Classic 8-tooth mechanical gear outline + center hole
        cx, cy = s * 0.5, s * 0.5
        r_outer = s * 0.39
        r_inner = s * 0.28
        teeth = 8
        gear = QPainterPath()
        pts: list[QPointF] = []
        for i in range(teeth):
            base_deg = i * (360.0 / teeth)
            for offset, rad_r in ((-14.0, r_inner), (-8.5, r_outer), (8.5, r_outer), (14.0, r_inner)):
                a = math.radians(base_deg + offset)
                pts.append(QPointF(cx + math.cos(a) * rad_r, cy + math.sin(a) * rad_r))
        gear.moveTo(pts[0])
        for pt in pts[1:]:
            gear.lineTo(pt)
        gear.closeSubpath()
        p.drawPath(gear)
        p.drawEllipse(QRectF(cx - s * 0.13, cy - s * 0.13, s * 0.26, s * 0.26))

    elif name == "key":
        p.drawEllipse(QRectF(s * 0.16, s * 0.32, s * 0.34, s * 0.34))
        p.drawLine(QPointF(s * 0.50, s * 0.49), QPointF(s * 0.84, s * 0.49))
        p.drawLine(QPointF(s * 0.70, s * 0.49), QPointF(s * 0.70, s * 0.64))
        p.drawLine(QPointF(s * 0.82, s * 0.49), QPointF(s * 0.82, s * 0.61))

    elif name == "copy":
        p.drawRoundedRect(QRectF(s * 0.34, s * 0.32, s * 0.46, s * 0.48), 2.5, 2.5)
        path = QPainterPath()
        path.moveTo(s * 0.26, s * 0.64)
        path.lineTo(s * 0.20, s * 0.64)
        path.lineTo(s * 0.20, s * 0.20)
        path.lineTo(s * 0.62, s * 0.20)
        path.lineTo(s * 0.62, s * 0.26)
        p.drawPath(path)

    elif name in ("eye", "eye_off"):
        path = QPainterPath()
        path.moveTo(s * 0.14, s * 0.50)
        path.quadTo(s * 0.50, s * 0.20, s * 0.86, s * 0.50)
        path.quadTo(s * 0.50, s * 0.80, s * 0.14, s * 0.50)
        p.drawPath(path)
        p.drawEllipse(QRectF(s * 0.40, s * 0.40, s * 0.20, s * 0.20))
        if name == "eye_off":
            p.drawLine(QPointF(s * 0.20, s * 0.80), QPointF(s * 0.80, s * 0.20))

    elif name == "play":
        p.setBrush(col)
        tri = QPolygonF([QPointF(s * 0.30, s * 0.22), QPointF(s * 0.30, s * 0.78), QPointF(s * 0.78, s * 0.50)])
        p.drawPolygon(tri)

    elif name == "bolt":
        poly = QPolygonF(
            [
                QPointF(s * 0.56, s * 0.14),
                QPointF(s * 0.26, s * 0.54),
                QPointF(s * 0.50, s * 0.54),
                QPointF(s * 0.44, s * 0.86),
                QPointF(s * 0.74, s * 0.46),
                QPointF(s * 0.50, s * 0.46),
            ]
        )
        p.drawPolygon(poly)

    elif name == "plus":
        p.drawLine(QPointF(s * 0.50, s * 0.22), QPointF(s * 0.50, s * 0.78))
        p.drawLine(QPointF(s * 0.22, s * 0.50), QPointF(s * 0.78, s * 0.50))

    elif name == "trash":
        p.drawLine(QPointF(s * 0.22, s * 0.28), QPointF(s * 0.78, s * 0.28))
        p.drawLine(QPointF(s * 0.40, s * 0.20), QPointF(s * 0.60, s * 0.20))
        p.drawRoundedRect(QRectF(s * 0.29, s * 0.28, s * 0.42, s * 0.54), 2.5, 2.5)

    elif name == "maximize":
        p.drawLine(QPointF(s * 0.20, s * 0.38), QPointF(s * 0.20, s * 0.20))
        p.drawLine(QPointF(s * 0.20, s * 0.20), QPointF(s * 0.38, s * 0.20))
        p.drawLine(QPointF(s * 0.80, s * 0.62), QPointF(s * 0.80, s * 0.80))
        p.drawLine(QPointF(s * 0.80, s * 0.80), QPointF(s * 0.62, s * 0.80))
        p.drawLine(QPointF(s * 0.22, s * 0.22), QPointF(s * 0.42, s * 0.42))
        p.drawLine(QPointF(s * 0.78, s * 0.78), QPointF(s * 0.58, s * 0.58))

    elif name == "upload":
        p.drawLine(QPointF(s * 0.50, s * 0.66), QPointF(s * 0.50, s * 0.20))
        p.drawLine(QPointF(s * 0.33, s * 0.36), QPointF(s * 0.50, s * 0.20))
        p.drawLine(QPointF(s * 0.67, s * 0.36), QPointF(s * 0.50, s * 0.20))
        p.drawLine(QPointF(s * 0.22, s * 0.80), QPointF(s * 0.78, s * 0.80))

    elif name == "refresh":
        p.drawArc(QRectF(s * 0.20, s * 0.20, s * 0.60, s * 0.60), 35 * 16, 290 * 16)
        p.drawLine(QPointF(s * 0.76, s * 0.22), QPointF(s * 0.78, s * 0.38))
        p.drawLine(QPointF(s * 0.62, s * 0.36), QPointF(s * 0.78, s * 0.38))

    else:
        p.drawEllipse(QRectF(s * 0.28, s * 0.28, s * 0.44, s * 0.44))

    p.end()
    return QIcon(pm)
