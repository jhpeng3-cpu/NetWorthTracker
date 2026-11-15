"""新增估值录入对话框（账户管理内使用）。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.common import primary_button, show_warning
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
    ):
        super().__init__(parent)
        self._symbol = symbol
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

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
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

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = primary_button("保存")
        save.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def values(self) -> tuple:
        qdate = self.date_edit.date()
        return (
            date(qdate.year(), qdate.month(), qdate.day()),
            parse_amount(self.value_edit.text(), field="估值"),
            self.note_edit.toPlainText().strip(),
        )

    def _submit(self) -> None:
        try:
            self.values()
        except AmountError as exc:
            show_warning(self, "无法保存", str(exc))
            self.value_edit.setFocus()
            return
        self.accept()
