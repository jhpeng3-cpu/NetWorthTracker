"""Qt 样式表与图表配色。"""
from __future__ import annotations

from string import Template

from app.config import bundle_dir

LIGHT = {
    "bg": "#f3f5f9",
    "surface": "#ffffff",
    "surface_alt": "#f7f9fc",
    "border": "#e2e8f0",
    "text": "#1f2937",
    "muted": "#6b7280",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "success": "#059669",
    "danger": "#dc2626",
    "warning": "#d97706",
    "selection": "#dbeafe",
    "sidebar": "#152238",
    "sidebar_text": "#c3cede",
    "sidebar_muted": "#7f8ca1",
    "chart_assets": "#2563eb",
    "chart_liabilities": "#dc2626",
    "chart_net": "#059669",
    "pie": [
        "#2563eb",
        "#0ea5e9",
        "#14b8a6",
        "#22c55e",
        "#eab308",
        "#f97316",
        "#ef4444",
        "#a855f7",
        "#64748b",
    ],
}

DARK = {
    "bg": "#0f172a",
    "surface": "#172033",
    "surface_alt": "#1e293b",
    "border": "#2c3a52",
    "text": "#e5e7eb",
    "muted": "#94a3b8",
    "accent": "#3b82f6",
    "accent_hover": "#60a5fa",
    "success": "#34d399",
    "danger": "#f87171",
    "warning": "#fbbf24",
    "selection": "#1e3a5f",
    "sidebar": "#0b1220",
    "sidebar_text": "#c3cede",
    "sidebar_muted": "#74829a",
    "chart_assets": "#60a5fa",
    "chart_liabilities": "#f87171",
    "chart_net": "#34d399",
    "pie": [
        "#60a5fa",
        "#38bdf8",
        "#2dd4bf",
        "#4ade80",
        "#facc15",
        "#fb923c",
        "#f87171",
        "#c084fc",
        "#94a3b8",
    ],
}


def palette(theme: str) -> dict:
    return DARK if theme == "dark" else LIGHT


_STYLESHEET = Template(
    """
QWidget {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
    color: $text;
}
QMainWindow, QWidget#Content, QWidget#Page, QDialog {
    background: $bg;
}
QFrame#Sidebar {
    background: $sidebar;
    border: none;
}
QLabel#Brand {
    color: #ffffff;
    font-size: 19px;
    font-weight: 700;
}
QLabel#BrandSub {
    color: $sidebar_muted;
    font-size: 11px;
}
QLabel#SidebarFooter {
    color: $sidebar_muted;
    font-size: 11px;
}
QListWidget#Nav {
    background: transparent;
    border: none;
    outline: 0;
    padding-top: 8px;
}
QListWidget#Nav::item {
    color: $sidebar_text;
    padding: 11px 16px;
    border-radius: 8px;
    margin: 2px 10px;
}
QListWidget#Nav::item:hover {
    background: rgba(255, 255, 255, 20);
}
QListWidget#Nav::item:selected {
    background: $accent;
    color: #ffffff;
    font-weight: 600;
}
QLabel#PageTitle {
    font-size: 22px;
    font-weight: 700;
    color: $text;
}
QLabel#PageSubtitle, QLabel#Muted, QLabel#Hint {
    color: $muted;
    font-size: 12px;
}
QLabel#SectionTitle {
    font-size: 14px;
    font-weight: 600;
}
QFrame#Card, QFrame#Panel {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#RateChip {
    background: $surface_alt;
    border: 1px solid $border;
    border-radius: 10px;
}
QLabel#RateCode {
    color: $muted;
    font-size: 11px;
}
QLabel#RateValue {
    font-size: 13px;
    font-weight: 700;
    color: $text;
}
QLabel#CardTitle {
    color: $muted;
    font-size: 12px;
}
QLabel#CardValue {
    font-size: 24px;
    font-weight: 700;
    color: $text;
}
QLabel#CardValue[tone="positive"] {
    color: $success;
}
QLabel#CardValue[tone="negative"] {
    color: $danger;
}
QLabel#CardValue[tone="neutral"] {
    color: $text;
}
QLabel#CardHint {
    color: $muted;
    font-size: 11px;
}
QPushButton {
    background: $surface;
    border: 1px solid $border;
    border-radius: 7px;
    padding: 6px 14px;
    min-height: 18px;
}
QPushButton:hover {
    border-color: $accent;
    color: $accent;
}
QPushButton:pressed {
    background: $surface_alt;
}
QPushButton[primary="true"] {
    background: $accent;
    border: 1px solid $accent;
    color: #ffffff;
    font-weight: 600;
}
QPushButton[primary="true"]:hover {
    background: $accent_hover;
    border-color: $accent_hover;
    color: #ffffff;
}
QPushButton[danger="true"] {
    color: $danger;
    border-color: $danger;
}
QPushButton[danger="true"]:hover {
    background: $danger;
    color: #ffffff;
}
QPushButton:disabled {
    color: $muted;
    background: $surface_alt;
    border-color: $border;
}
QLineEdit, QComboBox, QDateEdit, QTextEdit, QSpinBox, QDoubleSpinBox {
    background: $surface;
    border: 1px solid $border;
    border-radius: 7px;
    padding: 5px 8px;
    min-height: 20px;
    selection-background-color: $accent;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTextEdit:focus {
    border: 1px solid $accent;
}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled {
    background: $surface_alt;
    color: $muted;
}
QComboBox::drop-down, QDateEdit::drop-down {
    border: none;
    width: 24px;
}
QComboBox::down-arrow, QDateEdit::down-arrow {
    image: url("$chevron");
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    background: $surface;
    border: 1px solid $border;
    selection-background-color: $selection;
    selection-color: $text;
    outline: 0;
}
QTableWidget, QTableView {
    background: $surface;
    alternate-background-color: $surface_alt;
    border: 1px solid $border;
    border-radius: 8px;
    gridline-color: $border;
    selection-background-color: $selection;
    selection-color: $text;
    outline: 0;
}
QTableWidget::item, QTableView::item {
    padding: 4px 6px;
}
QHeaderView::section {
    background: $surface_alt;
    color: $muted;
    padding: 7px 6px;
    border: none;
    border-bottom: 1px solid $border;
    font-weight: 600;
}
QTableCornerButton::section {
    background: $surface_alt;
    border: none;
}
QGroupBox {
    background: $surface;
    border: 1px solid $border;
    border-radius: 10px;
    margin-top: 14px;
    padding: 14px 12px 10px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: $text;
    background: $surface;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: $border;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: $muted;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    height: 0;
    background: none;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: $border;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    width: 0;
    background: none;
}
QMenuBar {
    background: $surface;
    border-bottom: 1px solid $border;
}
QMenuBar::item {
    padding: 5px 10px;
    background: transparent;
}
QMenuBar::item:selected {
    background: $selection;
}
QMenu {
    background: $surface;
    border: 1px solid $border;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 5px;
}
QMenu::item:selected {
    background: $selection;
}
QStatusBar {
    background: $surface;
    border-top: 1px solid $border;
    color: $muted;
    font-size: 11px;
}
QToolTip {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    padding: 4px;
}
QSplitter::handle {
    background: transparent;
}
"""
)


def _chevron_path(theme: str) -> str:
    return (
        bundle_dir() / "app" / "ui" / "assets" / f"chevron_{theme}.png"
    ).as_posix()


def build_stylesheet(theme: str) -> str:
    colors = palette(theme)
    colors["chevron"] = _chevron_path(theme)
    return _STYLESHEET.substitute(colors)
