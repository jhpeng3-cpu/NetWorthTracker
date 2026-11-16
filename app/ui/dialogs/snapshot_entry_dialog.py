"""新增估值录入对话框（账户管理内使用）。"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.common import (
    date_edit,
    dialog_footer,
    from_qdate,
    run_save,
    show_warning,
)
from app.utils.money import AmountError, parse_amount


class SnapshotEntryDialog(QDialog):
    """为单个子项录入某一天的估值。"""

    def __init__(
        self,
        account_name: str,
        item_name: str,
        side_label: str,
        category_label: str,
        symbol: str,
        default_value: Optional[Decimal] = None,
        parent: Optional[QWidget] = None,
        on_save: Optional[Callable[[object, Decimal, str], None]] = None,
    ):
        super().__init__(parent)
        self._symbol = symbol
        self._on_save = on_save
        self.setWindowTitle("录入估值")
        self.setMinimumWidth(430)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        title = QLabel(f"{account_name} · {item_name}")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        subtitle = QLabel(f"{side_label} · {category_label}")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        self.date_edit = date_edit()
        self.value_edit = QLineEdit()
        self.value_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.value_edit.setPlaceholderText(f"{self._symbol}0.00")
        if default_value is not None:
            self.value_edit.setText(f"{default_value:.2f}")
        self.note_edit = QTextEdit()
        self.note_edit.setFixedHeight(66)
        self.note_edit.setPlaceholderText("可选备注")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setSpacing(8)
        form.addRow("日期 *", self.date_edit)
        form.addRow("估值 *", self.value_edit)
        form.addRow("备注", self.note_edit)
        layout.addLayout(form)

        hint = QLabel("同一子项同一天已有估值时，会先询问是否覆盖。")
        hint.setObjectName("Hint")
        layout.addWidget(hint)

        layout.addLayout(dialog_footer(self, self._submit))

    def values(self) -> tuple:
        return (
            from_qdate(self.date_edit.date()),
            parse_amount(self.value_edit.text(), field="估值"),
            self.note_edit.toPlainText().strip(),
        )

    def _submit(self) -> None:
        try:
            day, value, note = self.values()
        except AmountError as exc:
            show_warning(self, "无法保存", str(exc))
            self.value_edit.setFocus()
            return
        if self._on_save is not None and not run_save(
            self, lambda: self._on_save(day, value, note)
        ):
            return
        self.accept()
