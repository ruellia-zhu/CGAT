"""Design tokens and stylesheet for Circos Studio.

One source of truth for colours, metrics and the QSS.  Two themes (light / dark)
are the same template with different token values, so a theme switch is a single
`apply_theme(app, "dark")` call.
"""
from __future__ import annotations

from string import Template

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# --- tokens -----------------------------------------------------------------
LIGHT = {
    "bg": "#F7F7F4",
    "panel": "#FFFFFF",
    "card": "#FFFFFF",
    "canvas": "#FFFFFF",
    "border": "#E8E8E3",
    "border_strong": "#D8D8D2",
    "ink": "#1C1C1E",
    "ink2": "#6B6B70",
    "ink3": "#9A9AA0",
    "accent": "#2F6B5E",
    "accent_hover": "#275A4F",
    "accent_press": "#1F4A41",
    "accent_soft": "#E8F1EE",
    "accent_ink": "#FFFFFF",
    "danger": "#B4472F",
    "danger_soft": "#FBEDE9",
    "ok": "#2F6B5E",
    "track": "#E4E4DF",
    "hover": "#F0F0EC",
    "shadow": "rgba(0,0,0,0.06)",
}

DARK = {
    "bg": "#141518",
    "panel": "#1B1C20",
    "card": "#22242A",
    "canvas": "#1B1C20",
    "border": "#2C2E35",
    "border_strong": "#3A3D46",
    "ink": "#F2F2F4",
    "ink2": "#A2A2AA",
    "ink3": "#71717A",
    "accent": "#4E9C8B",
    "accent_hover": "#5CAF9C",
    "accent_press": "#3F8577",
    "accent_soft": "#1F2C29",
    "accent_ink": "#0E1513",
    "danger": "#E0725A",
    "danger_soft": "#2A1C18",
    "ok": "#4E9C8B",
    "track": "#2E3038",
    "hover": "#262830",
    "shadow": "rgba(0,0,0,0.35)",
}

FONT_UI = '"Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", sans-serif'
FONT_DISPLAY = '"Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI", "Microsoft YaHei UI", sans-serif'

_QSS = Template(
    """
* { outline: none; }

QWidget {
    color: $ink;
    font-family: $font;
    font-size: 13px;
}

QWidget#root { background: $bg; }

/* ---------------- panel / stage ---------------- */
QWidget#panel { background: $bg; border-right: 1px solid $border; }
QWidget#panelFooter { background: $bg; border-top: 1px solid $border; }
QWidget#stage { background: $bg; }

/* ---------------- title bar ---------------- */
QWidget#titleBar { background: $bg; border-bottom: 1px solid $border; }
QLabel#appName { font-family: $fontDisplay; font-size: 14px; font-weight: 600; color: $ink; }
QLabel#appTag  { font-size: 11px; color: $ink3; }

QToolButton#winBtn {
    background: transparent; border: none; border-radius: 6px;
    padding: 0px; min-width: 34px; min-height: 28px;
}
QToolButton#winBtn:hover { background: $hover; }
QToolButton#winClose:hover { background: #D64545; }
QToolButton#winClose:hover:hover { background: #D64545; }

/* ---------------- cards ---------------- */
QFrame#card {
    background: $card;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#cardFlat { background: $card; border: 1px solid $border; border-radius: 10px; }
QLabel#sectionTitle {
    font-family: $fontDisplay; font-size: 12px; font-weight: 600;
    color: $ink; letter-spacing: 0.3px;
}
QLabel#sectionIndex {
    font-family: $fontDisplay; font-size: 11px; font-weight: 600;
    color: $accent; background: $accent_soft;
    border-radius: 7px; padding: 1px 7px;
}
QLabel#fieldLabel { font-size: 12px; color: $ink2; }
QLabel#hint { font-size: 11px; color: $ink3; }
QLabel#valueChip {
    font-family: $fontDisplay; font-size: 12px; font-weight: 600;
    color: $accent; background: $accent_soft;
    border-radius: 6px; padding: 1px 8px;
}
QFrame#divider { background: $border; border: none; }

/* ---------------- buttons ---------------- */
QPushButton#primary {
    background: $accent; color: $accent_ink; border: none; border-radius: 8px;
    font-size: 13px; font-weight: 600; padding: 0 18px; min-height: 36px;
}
QPushButton#primary:hover  { background: $accent_hover; }
QPushButton#primary:pressed{ background: $accent_press; }
QPushButton#primary:disabled { background: $track; color: $ink3; }

QPushButton#ghost {
    background: transparent; color: $ink2; border: 1px solid $border;
    border-radius: 8px; font-size: 12px; padding: 0 12px; min-height: 30px;
}
QPushButton#ghost:hover { background: $hover; color: $ink; }

QToolButton#ghostIcon {
    background: transparent; border: none; border-radius: 6px; padding: 4px;
}
QToolButton#ghostIcon:hover { background: $hover; }
QPushButton#ghostIcon {
    background: transparent; border: none; border-radius: 6px; padding: 4px;
}
QPushButton#ghostIcon:hover { background: $hover; }

/* ---------------- segmented (the pill is painted by the widget) ---------- */
QPushButton#segItem {
    background: transparent; border: none; border-radius: 6px;
    color: $ink2; font-size: 12px; padding: 0 12px; min-height: 28px;
}
QPushButton#segItem:hover { color: $ink; }
QPushButton#segItem:checked { background: $card; color: $ink; font-weight: 600; }

/* ---------------- slider ---------------- */
QSlider::groove:horizontal {
    height: 4px; background: $track; border-radius: 2px;
}
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; height: 14px; margin: -6px 0;
    border-radius: 8px; background: $card; border: 2px solid $accent;
}
QSlider::handle:horizontal:hover { border-color: $accent_hover; }

/* ---------------- text fields ---------------- */
QLineEdit {
    background: $card; border: 1px solid $border; border-radius: 8px;
    padding: 3px 8px; min-height: 22px; color: $ink; font-size: 12px;
    selection-background-color: $accent_soft; selection-color: $ink;
}
QLineEdit:hover { border-color: $border_strong; }
QLineEdit:focus { border-color: $accent; }
QLineEdit:read-only { color: $ink2; }
QLineEdit::placeholder { color: $ink3; }

QSpinBox {
    background: $card; border: 1px solid $border; border-radius: 8px;
    padding: 2px 16px 2px 8px; min-height: 22px; color: $ink; font-size: 12px;
}
QSpinBox:hover { border-color: $border_strong; }
QSpinBox:focus { border-color: $accent; }
QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; }

/* ---------------- combo box ---------------- */
QComboBox {
    background: $card; border: 1px solid $border; border-radius: 8px;
    padding: 4px 10px; min-height: 26px; color: $ink; font-size: 12px;
}
QComboBox:hover { border-color: $border_strong; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: $card; border: 1px solid $border; border-radius: 8px;
    color: $ink; selection-background-color: $accent_soft; selection-color: $ink;
    outline: none; padding: 4px;
}

/* ---------------- checkbox / radio ---------------- */
QCheckBox { font-size: 12px; color: $ink2; spacing: 8px; }
QCheckBox::indicator {
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid $border_strong; background: $card;
}
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }

/* ---------------- scroll ---------------- */
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical {
    background: $border_strong; border-radius: 4px; min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: $ink3; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---------------- canvas ---------------- */
QGraphicsView#canvas { background: $canvas; border: none; }

/* ---------------- status ---------------- */
QWidget#statusBar { background: $bg; border-top: 1px solid $border; }
QLabel#statusText { font-size: 11px; color: $ink2; }
QLabel#statusMeta { font-size: 11px; color: $ink3; }

QToolTip {
    background: $ink; color: $bg; border: none;
    border-radius: 6px; padding: 5px 8px; font-size: 11px;
}
"""
)


_CURRENT = "light"


def theme(name: str | None = None) -> dict:
    """Token table for `name`, or for the currently applied theme when omitted."""
    if name is None:
        name = _CURRENT
    return DARK if name == "dark" else LIGHT


def stylesheet(name: str = "light") -> str:
    t = dict(theme(name))
    t.setdefault("font", FONT_UI)
    t.setdefault("fontDisplay", FONT_DISPLAY)
    return _QSS.substitute(t)


def apply(app: QApplication, name: str = "light") -> None:
    global _CURRENT
    _CURRENT = name
    app.setStyle("Fusion")
    t = theme(name)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(t["bg"]))
    pal.setColor(QPalette.Base, QColor(t["card"]))
    pal.setColor(QPalette.Text, QColor(t["ink"]))
    pal.setColor(QPalette.WindowText, QColor(t["ink"]))
    pal.setColor(QPalette.Highlight, QColor(t["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor(t["accent_ink"]))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(name))


def color(name: str, key: str) -> QColor:
    return QColor(theme(name)[key])
