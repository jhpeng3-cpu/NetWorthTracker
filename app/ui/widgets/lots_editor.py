"""成本批次编辑控件：日期日历选择、单元格圆角边框与合计。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from PySide6.QtCore import QDate, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCalendarWidget,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyledItemDelegate,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.db.models import CURRENCY_CODES, CURRENCY_LABELS
from app.services.profit import LotInput
from app.ui.common import (
    align_headers,
    make_table,
    parse_optional_decimal,
    set_columns,
)
from app.ui.styles import palette
from app.ui.titlebar import current_theme
from app.utils.money import fmt_number

LOT_HEADERS = ["买入日期", "数量", "单价", "手续费", "备注"]
DATE_FORMAT = "yyyy-MM-dd"


class LotCellDelegate(QStyledItemDelegate):
    """为每个可输入单元格绘制圆角边框，提示此处可编辑。"""

    def paint(self, painter, option, index):  # noqa: N802 - Qt API
        super().paint(painter, option, index)
        colors = palette(current_theme())
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(colors["border"]))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(option.rect.adjusted(3, 4, -3, -4), 7.0, 7.0)
        painter.restore()


class LotsEditor(QGroupBox):
    """成本批次表格：币种、批次行、日期日历、合计与增删操作。"""

    changed = Signal()

    def __init__(
        self,
        lots: Optional[List[LotInput]] = None,
        cost_currency: str = "CNY",
        parent: Optional[QWidget] = None,
    ):
        super().__init__("成本批次", parent)
        self._build_ui(cost_currency)
        for lot in lots or []:
            self._append_row(lot)
        if not lots:
            self._append_row(None)
        self._refresh_totals()

    # ---- 构建 ----
    def _build_ui(self, cost_currency: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 10)
        layout.setSpacing(8)

        currency_row = QHBoxLayout()
        currency_label = QLabel("成本币种")
        currency_label.setObjectName("Hint")
        self.currency_combo = QComboBox()
        self.currency_combo.setFixedWidth(150)
        for code in CURRENCY_CODES:
            self.currency_combo.addItem(f"{CURRENCY_LABELS[code]}（{code}）", code)
        index = self.currency_combo.findData(cost_currency)
        if index >= 0:
            self.currency_combo.setCurrentIndex(index)
        hint = QLabel("同一子项的所有批次必须使用同一种币种")
        hint.setObjectName("Hint")
        currency_row.addWidget(currency_label)
        currency_row.addWidget(self.currency_combo)
        currency_row.addSpacing(8)
        currency_row.addWidget(hint, 1)
        layout.addLayout(currency_row)

        self.table = make_table(LOT_HEADERS, stretch_last=True)
        set_columns(self.table, [130, 110, 110, 100, 240])
        self.table.setMinimumHeight(170)
        align_headers(self.table, (1, 2, 3))
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setItemDelegate(LotCellDelegate(self.table))
        self.table.cellClicked.connect(self._pick_date)
        layout.addWidget(self.table, 1)

        toolbar = QHBoxLayout()
        add_button = QPushButton("添加批次")
        add_button.clicked.connect(self.add_row)
        remove_button = QPushButton("删除选中")
        remove_button.clicked.connect(self._remove_current_row)
        self.totals_label = QLabel("")
        self.totals_label.setObjectName("Hint")
        toolbar.addWidget(add_button)
        toolbar.addWidget(remove_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.totals_label)
        layout.addLayout(toolbar)

    # ---- 对外接口 ----
    def values(self) -> List[LotInput]:
        lots: List[LotInput] = []
        for row in range(self.table.rowCount()):
            lot = self._read_row(row)
            if lot is not None:
                lots.append(lot)
        return lots

    def cost_currency(self) -> str:
        return self.currency_combo.currentData()

    def set_date(self, row: int, day: QDate) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            item.setText(day.toString(DATE_FORMAT))

    def add_row(self, lot: Optional[LotInput] = None) -> None:
        self._append_row(lot)
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)
        self._refresh_totals()

    # ---- 行操作 ----
    def _append_row(self, lot: Optional[LotInput]) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        if lot is None:
            values = ["", "", "", "0", ""]
        else:
            values = [
                lot.trade_date.strftime(DATE_FORMAT),
                fmt_number(lot.quantity, 4),
                fmt_number(lot.unit_cost, 6),
                fmt_number(lot.fee, 2),
                lot.note,
            ]
        for column, text in enumerate(values):
            item = QTableWidgetItem(text)
            if column in (1, 2, 3):
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            if column == 0:
                # 日期不手动输入，点击单元格弹出日历
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip("点击选择买入日期")
            self.table.setItem(row, column, item)

    def _remove_current_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._refresh_totals()

    def _read_row(self, row: int) -> Optional[LotInput]:
        def text(column: int) -> str:
            item = self.table.item(row, column)
            return item.text().strip() if item else ""

        # 只看日期/数量/单价/备注，避免默认手续费 0 让空行被当成有内容
        if not any(text(column) for column in (0, 1, 2, 4)):
            return None
        day = QDate.fromString(text(0), DATE_FORMAT)
        if not day.isValid():
            raise ValueError(f"第 {row + 1} 行：买入日期格式应为 YYYY-MM-DD。")
        quantity = parse_optional_decimal(text(1), f"第 {row + 1} 行数量", "0.0001")
        unit_cost = parse_optional_decimal(text(2), f"第 {row + 1} 行单价", "0.000001")
        fee = parse_optional_decimal(text(3) or "0", f"第 {row + 1} 行手续费", "0.01")
        if quantity is None or quantity <= 0:
            raise ValueError(f"第 {row + 1} 行数量必须大于 0。")
        return LotInput(
            trade_date=date(day.year(), day.month(), day.day()),
            quantity=quantity,
            unit_cost=unit_cost or Decimal("0"),
            fee=fee or Decimal("0.00"),
            currency=self.cost_currency(),
            note=text(4),
        )

    # ---- 日期日历 ----
    def _pick_date(self, row: int, column: int) -> None:
        if column != 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        selected = QDate.fromString(item.text().strip(), DATE_FORMAT)
        calendar = QCalendarWidget(self)
        calendar.setWindowFlags(Qt.WindowType.Popup)
        calendar.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        calendar.setGridVisible(False)
        calendar.setSelectedDate(
            selected if selected.isValid() else QDate.currentDate()
        )

        def choose(day: QDate) -> None:
            self.set_date(row, day)
            calendar.close()

        calendar.clicked.connect(choose)
        calendar.activated.connect(choose)

        rect = self.table.visualItemRect(item)
        position = self.table.viewport().mapToGlobal(rect.bottomLeft())
        screen = self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            size = calendar.sizeHint()
            x = min(position.x(), area.right() - size.width())
            y = position.y()
            if y + size.height() > area.bottom():
                y = position.y() - rect.height() - size.height()
            position = QPoint(max(area.left(), x), max(area.top(), y))
        calendar.move(position)
        calendar.show()

    # ---- 合计 ----
    def _on_item_changed(self, _item) -> None:
        self._refresh_totals()
        self.changed.emit()

    def _refresh_totals(self) -> None:
        quantity = Decimal("0")
        total = Decimal("0.00")
        count = 0
        for row in range(self.table.rowCount()):
            try:
                lot = self._read_row(row)
            except ValueError:
                continue
            if lot is None:
                continue
            count += 1
            quantity += lot.quantity
            total += lot.total_cost
        self.totals_label.setText(
            f"{count} 个批次 · 数量 {fmt_number(quantity, 4)} · "
            f"成本 {total:,.2f} {self.cost_currency()}"
        )
