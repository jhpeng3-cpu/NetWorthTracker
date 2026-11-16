"""汇率条：展示当日非人民币币种汇率，并提供刷新行情入口。"""
from __future__ import annotations

from datetime import date
from typing import Callable, Dict, Iterable, List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from app.db.models import CURRENCY_CODES, CURRENCY_LABELS

RateLookup = Callable[[str, date], float]


class RateStrip(QWidget):
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._refresh_button: QPushButton | None = None
        self._status = QLabel("")

    def set_rates(
        self,
        currencies: Iterable[str],
        rate_dates: Dict[str, date],
        lookup: RateLookup,
        day: date,
    ) -> None:
        """按当前账户实际使用的币种重绘汇率卡片。"""
        self._clear()
        used: List[str] = []
        for code in currencies:
            if code != "CNY" and code not in used:
                used.append(code)
        if not used:
            self._add_hint("当前无外币账户")
            return

        self._add_hint("当日汇率")
        dates: List[date] = []
        for code in CURRENCY_CODES:
            if code not in used:
                continue
            known = code in rate_dates
            rate = lookup(code, day) if known else 0.0
            label = CURRENCY_LABELS.get(code, code)
            chip = QFrame()
            chip.setObjectName("RateChip")
            chip_layout = QHBoxLayout(chip)
            chip_layout.setContentsMargins(10, 4, 10, 4)
            chip_layout.setSpacing(6)
            code_label = QLabel(label)
            code_label.setObjectName("RateCode")
            value_label = QLabel(f"{rate:.4f}" if known else "—")
            value_label.setObjectName("RateValue")
            chip_layout.addWidget(code_label)
            chip_layout.addWidget(value_label)
            if known:
                dates.append(rate_dates[code])
                chip.setToolTip(
                    f"1 {label} = {rate:.4f} 人民币\n"
                    f"汇率日期：{rate_dates[code]:%Y-%m-%d}"
                )
            else:
                chip.setToolTip("暂无该币种汇率，应用联网后会自动补全。")
            self._layout.addWidget(chip)

        self._add_hint(f"截至 {max(dates):%m-%d}" if dates else "暂无汇率")

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_busy(self, busy: bool) -> None:
        if self._refresh_button is None:
            return
        self._refresh_button.setEnabled(not busy)
        self._refresh_button.setText("刷新中…" if busy else "刷新行情")

    # ---- 内部 ----
    def _add_hint(self, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("Hint")
        self._layout.addWidget(label)

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._add_refresh_button()

    def _add_refresh_button(self) -> None:
        button = QPushButton("刷新行情")
        button.setToolTip(
            "刷新汇率并按估值方式生成当日快照：行情自动、计息增值、手动估值"
        )
        button.clicked.connect(self.refresh_requested)
        self._layout.addWidget(button)
        self._refresh_button = button
        self._status = QLabel("")
        self._status.setObjectName("Hint")
        self._layout.addWidget(self._status)
