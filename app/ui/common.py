"""通用 UI 组件与辅助函数。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Callable, Iterable, List, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


def make_title(title: str, subtitle: str = "") -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    label = QLabel(title)
    label.setObjectName("PageTitle")
    layout.addWidget(label)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("PageSubtitle")
        layout.addWidget(sub)
    return container


def primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("primary", True)
    return button


def to_qdate(day: date) -> QDate:
    return QDate(day.year, day.month, day.day)


def from_qdate(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def date_edit(day: Optional[date] = None) -> QDateEdit:
    """带日历弹窗的标准日期输入框。"""
    edit = QDateEdit(to_qdate(day or date.today()))
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy-MM-dd")
    return edit


def dialog_footer(
    dialog: QDialog,
    on_save: Callable[[], None],
    save_text: str = "保存",
    cancel_text: str = "取消",
) -> QHBoxLayout:
    """对话框底部的「取消 / 保存」按钮行。"""
    row = QHBoxLayout()
    row.addStretch(1)
    cancel = QPushButton(cancel_text)
    cancel.clicked.connect(dialog.reject)
    save = primary_button(save_text)
    save.clicked.connect(on_save)
    row.addWidget(cancel)
    row.addWidget(save)
    return row


def danger_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("danger", True)
    return button


def hbox(*widgets: QWidget, spacing: int = 8) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        if isinstance(widget, str):
            label = QLabel(widget)
            label.setObjectName("Muted")
            layout.addWidget(label)
        else:
            layout.addWidget(widget)
    layout.addStretch(1)
    return layout


class StatCard(QFrame):
    def __init__(self, title: str, hint: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("CardValue")
        self.value_label.setProperty("tone", "neutral")
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("CardHint")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.hint_label)
        self.setMinimumHeight(104)

    def set_value(self, text: str, hint: Optional[str] = None, tone: str = "neutral") -> None:
        self.value_label.setText(text)
        self.value_label.setProperty("tone", tone)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)
        if hint is not None:
            self.hint_label.setText(hint)


def make_table(headers: Iterable[str], stretch_last: bool = True) -> QTableWidget:
    header_list = list(headers)
    table = QTableWidget(0, len(header_list))
    table.setHorizontalHeaderLabels(header_list)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.horizontalHeader().setStretchLastSection(stretch_last)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setHighlightSections(False)
    table.verticalHeader().setDefaultSectionSize(34)
    return table


def table_item(
    text: str,
    align_right: bool = False,
    color: Optional[str] = None,
    bold: bool = False,
    user_data: object = None,
) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if align_right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    else:
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    if color:
        item.setForeground(QColor(color))
    if bold:
        font = QFont()
        font.setBold(True)
        item.setFont(font)
    if user_data is not None:
        item.setData(Qt.ItemDataRole.UserRole, user_data)
    return item


def set_columns(table: QTableWidget, widths: List[int]) -> None:
    for index, width in enumerate(widths):
        if index >= table.columnCount():
            break
        table.setColumnWidth(index, width)


def align_headers(table: QTableWidget, right_columns: Iterable[int] = ()) -> None:
    """让表头与列内容对齐：数字列右对齐，其余左对齐。"""
    right = set(right_columns)
    for column in range(table.columnCount()):
        item = table.horizontalHeaderItem(column)
        if item is None:
            continue
        horizontal = (
            Qt.AlignmentFlag.AlignRight
            if column in right
            else Qt.AlignmentFlag.AlignLeft
        )
        item.setTextAlignment(horizontal | Qt.AlignmentFlag.AlignVCenter)


def selected_row(table: QTableWidget) -> int:
    rows = table.selectionModel().selectedRows() if table.selectionModel() else []
    return rows[0].row() if rows else -1


def row_user_data(table: QTableWidget, row: int) -> object:
    item = table.item(row, 0)
    return item.data(Qt.ItemDataRole.UserRole) if item else None


def confirm(parent: QWidget, title: str, text: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.button(QMessageBox.StandardButton.Yes).setText("确定")
    box.button(QMessageBox.StandardButton.No).setText("取消")
    return box.exec() == QMessageBox.StandardButton.Yes


def show_info(parent: QWidget, title: str, text: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.button(QMessageBox.StandardButton.Ok).setText("知道了")
    box.exec()


def show_warning(parent: QWidget, title: str, text: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.button(QMessageBox.StandardButton.Ok).setText("知道了")
    box.exec()


def show_error(parent: QWidget, title: str, text: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.button(QMessageBox.StandardButton.Ok).setText("知道了")
    box.exec()


def show_exception(parent: QWidget, title: str, exc: BaseException) -> None:
    """统一异常出口：日志记录完整堆栈，界面只展示友好文案。"""
    from app.utils.exceptions import report_exception

    show_error(parent, title, report_exception(exc, title))


def run_save(parent: QWidget, action: Callable[[], None], title: str = "保存失败") -> bool:
    """执行保存动作：校验错误提示警告，其它异常走统一出口并打印。

    返回 True 表示保存成功；False 表示失败（调用方应保持弹窗打开）。
    """
    try:
        action()
    except ValueError as exc:
        show_warning(parent, "无法保存", str(exc))
        return False
    except Exception as exc:  # noqa: BLE001
        show_exception(parent, title, exc)
        return False
    return True


def money_text(value: Optional[Decimal], symbol: str, placeholder: str = "—") -> str:
    from app.utils.money import fmt_money

    return fmt_money(value, symbol=symbol, placeholder=placeholder)


def parse_optional_decimal(
    text: str,
    field: str,
    digits: str,
    maximum: Optional[Decimal] = None,
) -> Optional[Decimal]:
    """解析表单里的可选数字；空文本返回 None，非法值抛 ValueError。"""
    raw = (text or "").strip().replace(",", "").replace("％", "").replace("%", "")
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field}必须是数字。") from None
    if not value.is_finite() or value < 0:
        raise ValueError(f"{field}必须是非负数字。")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field}不能大于 {maximum}。")
    return value.quantize(Decimal(digits), rounding=ROUND_HALF_UP)
