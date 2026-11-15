"""编辑快照对话框。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Callable, Optional

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

from app.services.snapshots import SnapshotExistsError, SnapshotRow, SnapshotValidationError
from app.ui.common import primary_button, show_error, show_warning
from app.utils.money import AmountError, fmt_money, parse_amount


def to_qdate(day: date) -> QDate:
    return QDate(day.year, day.month, day.day)


class SnapshotEditDialog(QDialog):
    def __init__(
        self,
        row: SnapshotRow,
        symbol: str,
        on_submit: Callable[[date, Decimal, str], None],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._row = row
        self._symbol = symbol
        self._on_submit = on_submit
        self.setWindowTitle("编辑估值快照")
        self.setMinimumWidth(420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        account_label = QLabel(row.account_name)
        account_label.setObjectName("SectionTitle")
        layout.addWidget(account_label)
        side_label = QLabel(f"{row.side_label} · {row.category_label}")
        side_label.setObjectName("Muted")
        layout.addWidget(side_label)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(to_qdate(row.snapshot_date))
        self.value_edit = QLineEdit(f"{row.value:.2f}")
        self.value_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.note_edit = QTextEdit()
        self.note_edit.setPlainText(row.note)
        self.note_edit.setFixedHeight(70)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setSpacing(8)
        form.addRow("日期 *", self.date_edit)
        form.addRow("估值 *", self.value_edit)
        form.addRow("备注", self.note_edit)
        layout.addLayout(form)

        hint = QLabel(f"当前记录：{fmt_money(row.value, self._symbol)}")
        hint.setObjectName("Hint")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = primary_button("保存修改")
        save.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _submit(self) -> None:
        qdate = self.date_edit.date()
        day = date(qdate.year(), qdate.month(), qdate.day())
        try:
            value = parse_amount(self.value_edit.text(), field="估值")
        except AmountError as exc:
            show_warning(self, "无法保存", str(exc))
            return
        try:
            self._on_submit(day, value, self.note_edit.toPlainText().strip())
        except SnapshotExistsError as exc:
            show_warning(self, "日期重复", str(exc))
            return
        except SnapshotValidationError as exc:
            show_warning(self, "无法保存", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            show_error(self, "保存失败", str(exc))
            return
        self.accept()
