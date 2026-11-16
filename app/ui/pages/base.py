"""页面基类。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app.config import AppConfig
from app.ui.common import make_title
from app.ui.styles import palette


class BasePage(QWidget):
    data_changed = Signal()

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self._theme = config.theme
        self.setObjectName("Page")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 16, 24, 16)
        self.root.setSpacing(12)

    def add_header(self, title: str, subtitle: str = "") -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(make_title(title, subtitle), 1)
        self.root.addLayout(row)
        return row

    @property
    def symbol(self) -> str:
        return self.config.currency_symbol

    @property
    def colors(self) -> dict:
        """当前主题的配色表。"""
        return palette(self._theme)

    def refresh(self) -> None:
        """页面可见或数据变化时刷新。"""

    def apply_theme(self, theme: str) -> None:
        """主题切换时更新配色与自定义绘制。"""
        self._theme = theme
