"""类别子项编辑对话框，可同时维护成本批次。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import CATEGORY_LABELS, CATEGORIES_BY_SIDE, CURRENCY_CODES, CURRENCY_LABELS
from app.services.profit import LotInput
from app.ui.common import make_table, primary_button, set_columns, show_warning
from app.utils.money import fmt_money, parse_amount

LOT_HEADERS = ["买入日期", "数量", "单价", "手续费", "备注"]


def _fmt_number(value: Decimal, digits: int) -> str:
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


class ItemDialog(QDialog):
    def __init__(
        self,
        side: str,
        name: str = "",
        category: Optional[str] = None,
        title: str = "类别子项",
        parent: Optional[QWidget] = None,
        allow_lots: bool = False,
        lots_only: bool = False,
        lots: Optional[List[LotInput]] = None,
        cost_currency: str = "CNY",
        currency: str = "CNY",
        symbol: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(720 if allow_lots else 340)
        self.setModal(True)
        self.allow_lots = allow_lots
        self.lots_only = lots_only

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：现金、股票、债券")
        self.name_edit.setText(name)
        self.currency_combo = QComboBox()
        for code in CURRENCY_CODES:
            self.currency_combo.addItem(f"{CURRENCY_LABELS[code]}（{code}）", code)
        index = self.currency_combo.findData(currency)
        if index >= 0:
            self.currency_combo.setCurrentIndex(index)
        self.category_combo = QComboBox()
        for key in CATEGORIES_BY_SIDE.get(side, []):
            self.category_combo.addItem(CATEGORY_LABELS[key], key)
        if category is not None:
            index = self.category_combo.findData(category)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
        self.symbol_edit = QLineEdit()
        self.symbol_edit.setText(symbol)
        self.symbol_edit.setPlaceholderText("可选，如 600519 / 00700 / AAPL")

        if not lots_only:
            form = QFormLayout()
            form.setLabelAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            form.setSpacing(8)
            form.addRow("子项名称 *", self.name_edit)
            form.addRow("币种 *", self.currency_combo)
            form.addRow("类别 *", self.category_combo)
            if side == "asset":
                form.addRow("股票代码", self.symbol_edit)
            layout.addLayout(form)

        if allow_lots:
            layout.addWidget(self._build_lots_group(cost_currency, lots or []))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = primary_button("保存")
        save.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self._refresh_totals()

    # ---- 成本批次 ----

    def _build_lots_group(
        self, cost_currency: str, lots: List[LotInput]
    ) -> QGroupBox:
        group = QGroupBox("成本批次")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(12, 14, 12, 10)
        group_layout.setSpacing(8)

        currency_row = QHBoxLayout()
        currency_label = QLabel("成本币种")
        currency_label.setObjectName("Hint")
        self.cost_currency_combo = QComboBox()
        self.cost_currency_combo.setFixedWidth(150)
        for code in CURRENCY_CODES:
            self.cost_currency_combo.addItem(f"{CURRENCY_LABELS[code]}（{code}）", code)
        index = self.cost_currency_combo.findData(cost_currency)
        if index >= 0:
            self.cost_currency_combo.setCurrentIndex(index)
        hint = QLabel("同一子项的所有批次必须使用同一种币种")
        hint.setObjectName("Hint")
        currency_row.addWidget(currency_label)
        currency_row.addWidget(self.cost_currency_combo)
        currency_row.addSpacing(8)
        currency_row.addWidget(hint, 1)
        group_layout.addLayout(currency_row)

        self.lots_table = make_table(LOT_HEADERS, stretch_last=True)
        set_columns(self.lots_table, [130, 110, 110, 100, 240])
        self.lots_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.lots_table.itemChanged.connect(lambda _item: self._refresh_totals())
        group_layout.addWidget(self.lots_table, 1)

        toolbar = QHBoxLayout()
        add_button = QPushButton("添加批次")
        add_button.clicked.connect(self._add_lot_row)
        remove_button = QPushButton("删除选中")
        remove_button.clicked.connect(self._remove_lot_row)
        self.totals_label = QLabel("")
        self.totals_label.setObjectName("Hint")
        toolbar.addWidget(add_button)
        toolbar.addWidget(remove_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.totals_label)
        group_layout.addLayout(toolbar)

        for lot in lots:
            self._append_lot_row(lot)
        if not lots:
            self._append_lot_row(None)
        return group

    def _append_lot_row(self, lot: Optional[LotInput]) -> None:
        row = self.lots_table.rowCount()
        self.lots_table.insertRow(row)
        if lot is None:
            values = ["", "", "", "0", ""]
        else:
            values = [
                lot.trade_date.strftime("%Y-%m-%d"),
                _fmt_number(lot.quantity, 4),
                _fmt_number(lot.unit_cost, 6),
                _fmt_number(lot.fee, 2),
                lot.note,
            ]
        for column, text in enumerate(values):
            item = QTableWidgetItem(text)
            if column in (1, 2, 3):
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            self.lots_table.setItem(row, column, item)
        self._refresh_totals()

    def _add_lot_row(self) -> None:
        self._append_lot_row(None)
        self.lots_table.setCurrentCell(self.lots_table.rowCount() - 1, 0)

    def _remove_lot_row(self) -> None:
        row = self.lots_table.currentRow()
        if row >= 0:
            self.lots_table.removeRow(row)
            self._refresh_totals()

    def _read_lot_row(self, row: int) -> Optional[LotInput]:
        def text(column: int) -> str:
            item = self.lots_table.item(row, column)
            return item.text().strip() if item else ""

        if not any(text(column) for column in range(4)):
            return None
        day = QDate.fromString(text(0), "yyyy-MM-dd")
        if not day.isValid():
            raise ValueError(f"第 {row + 1} 行：买入日期格式应为 YYYY-MM-DD。")
        quantity = parse_amount(text(1), field=f"第 {row + 1} 行数量", allow_zero=False)
        unit_cost = parse_amount(text(2), field=f"第 {row + 1} 行单价", allow_zero=True)
        fee = parse_amount(text(3) or "0", field=f"第 {row + 1} 行手续费", allow_zero=True)
        return LotInput(
            trade_date=date(day.year(), day.month(), day.day()),
            quantity=quantity,
            unit_cost=unit_cost,
            fee=fee,
            currency=self.cost_currency_combo.currentData(),
            note=text(4),
        )

    def _refresh_totals(self) -> None:
        if not self.allow_lots or not hasattr(self, "totals_label"):
            return
        quantity = Decimal("0")
        total = Decimal("0.00")
        count = 0
        for row in range(self.lots_table.rowCount()):
            try:
                lot = self._read_lot_row(row)
            except ValueError:
                continue
            if lot is None:
                continue
            count += 1
            quantity += lot.quantity
            total += lot.total_cost
        currency = (
            self.cost_currency_combo.currentData()
            if hasattr(self, "cost_currency_combo")
            else "CNY"
        )
        self.totals_label.setText(
            f"{count} 个批次 · 数量 {_fmt_number(quantity, 4)} · "
            f"成本 {fmt_money(total, symbol='')} {currency}"
        )

    def lot_values(self) -> List[LotInput]:
        lots: List[LotInput] = []
        for row in range(self.lots_table.rowCount()):
            lot = self._read_lot_row(row)
            if lot is not None:
                lots.append(lot)
        return lots

    def cost_currency(self) -> str:
        return self.cost_currency_combo.currentData()

    def currency_value(self) -> str:
        return self.currency_combo.currentData()

    def symbol_value(self) -> str:
        return self.symbol_edit.text().strip().upper()

    # ---- 提交 ----

    def values(self) -> tuple:
        return (
            self.name_edit.text().strip(),
            self.category_combo.currentData(),
            self.symbol_edit.text().strip().upper(),
        )

    def _submit(self) -> None:
        if not self.lots_only:
            name, _category, _symbol = self.values()
            if not name:
                show_warning(self, "请填写名称", "子项名称不能为空。")
                self.name_edit.setFocus()
                return
        if self.allow_lots:
            try:
                self.lot_values()
            except ValueError as exc:
                show_warning(self, "成本批次有误", str(exc))
                return
        self.accept()
