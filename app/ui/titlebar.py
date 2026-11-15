"""Windows 原生标题栏主题。

主窗口与所有弹窗（QDialog / QMessageBox）共用同一套标题栏配色，
使窗口边框、标题文字与当前应用主题保持一致。
"""
from __future__ import annotations

import ctypes
import sys
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget

from app.ui.styles import palette

# Windows 原生标题栏相关属性
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

THEME_PROPERTY = "appTheme"
_THEMED_WINDOW_TYPES = (Qt.WindowType.Window, Qt.WindowType.Dialog)


def _colorref(hex_color: str) -> int:
    """把 #RRGGBB 转成 Windows COLORREF（0x00BBGGRR）。"""
    value = hex_color.lstrip("#")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return red | (green << 8) | (blue << 16)


def apply_titlebar_theme(hwnd: int, theme: str) -> None:
    """让 Windows 原生标题栏配色跟随应用主题。

    Win10 1809+ 支持深色标题栏；Win11 起可自定义标题栏、文字与边框颜色，
    不支持的属性会被系统忽略，因此无需区分版本。
    """
    if sys.platform != "win32" or not hwnd:
        return
    try:
        dwmapi = ctypes.windll.dwmapi
    except AttributeError:
        return
    colors = palette(theme)
    dark = ctypes.c_int(1 if theme == "dark" else 0)
    for attribute in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD):
        if (
            dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(dark), ctypes.sizeof(dark)
            )
            == 0
        ):
            break
    for attribute, color in (
        (DWMWA_CAPTION_COLOR, colors["bg"]),
        (DWMWA_TEXT_COLOR, colors["text"]),
        (DWMWA_BORDER_COLOR, colors["border"]),
    ):
        value = ctypes.c_int(_colorref(color))
        dwmapi.DwmSetWindowAttribute(
            hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
        )


def current_theme() -> str:
    app = QApplication.instance()
    theme = app.property(THEME_PROPERTY) if app is not None else None
    return str(theme) if theme else "light"


def _apply_widget(widget: QWidget, theme: str) -> None:
    try:
        if widget.isVisible():
            apply_titlebar_theme(int(widget.winId()), theme)
    except RuntimeError:  # 窗口已销毁
        pass


def _is_themed_window(widget: QWidget) -> bool:
    return (
        widget.isWindow()
        and widget.windowType() in _THEMED_WINDOW_TYPES
        and not (widget.windowFlags() & Qt.WindowType.FramelessWindowHint)
    )


def apply_titlebar_to_open_windows(theme: Optional[str] = None) -> None:
    """主题切换时同步已打开的窗口（含弹窗）。"""
    app = QApplication.instance()
    if app is None:
        return
    target = theme or current_theme()
    for widget in app.topLevelWidgets():
        if _is_themed_window(widget):
            _apply_widget(widget, target)


class TitleBarThemeFilter(QObject):
    """在任意窗口首次显示时应用当前主题的标题栏配色。"""

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and _is_themed_window(watched)
        ):
            theme = current_theme()
            _apply_widget(watched, theme)
            # 部分对话框在显示后才会创建原生句柄，补一次确保生效
            QTimer.singleShot(0, lambda: _apply_widget(watched, current_theme()))
        return False


def install_titlebar_theme_filter(app: QApplication) -> TitleBarThemeFilter:
    """安装全局过滤器；对象挂到应用上，随应用生命周期存活。"""
    theme_filter = TitleBarThemeFilter(app)
    app.installEventFilter(theme_filter)
    return theme_filter
