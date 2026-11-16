"""编辑快照对话框。"""
from __future__ import annotations

from datetime import date
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

from app.services.snapshots import SnapshotExistsError, SnapshotRow, SnapshotValidationError
from app.ui.common import (
    date_edit,
    dialog_footer,
    from_qdate,
    show_exception,
    show_warning,
)
from app.utils.money import AmountError, fmt_money, parse_amount


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

        self.date_edit = date_edit(row.snapshot_date)
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

        layout.addLayout(dialog_footer(self, self._submit, save_text="保存修改"))

    def _submit(self) -> None:
        day = from_qdate(self.date_edit.date())
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
            show_exception(self, "保存失败", exc)
            return
        self.accept()
