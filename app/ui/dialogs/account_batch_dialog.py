"""账户内批量估值录入对话框：一次填写该账户所有子项的当日估值。"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.db.engine import db
from app.db.models import CATEGORY_LABELS
from app.services import snapshots as snapshot_service
from app.services.snapshots import BatchConflictError, BatchEntry, BatchRow
from app.ui.common import (
    align_headers,
    date_edit,
    dialog_footer,
    confirm,
    from_qdate,
    make_table,
    set_columns,
    show_exception,
    show_warning,
    table_item,
)
from app.utils.money import AmountError, fmt_money, parse_amount, symbol_for

HEADERS = ["子项", "类别", "最新估值", "当日已有", "估值输入", "备注"]


class AccountBatchDialog(QDialog):
    """按账户批量录入：留空的子项不更新。"""

    def __init__(
        self,
        account_id: int,
        account_name: str,
        currency: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.account_id = account_id
        self.account_name = account_name
        self.symbol = symbol_for(currency)
        self._rows: List[BatchRow] = []
        self.saved_total = 0
        self.saved_created = 0
        self.saved_updated = 0

        self.setWindowTitle(f"批量录入 · {account_name}")
        self.setMinimumSize(760, 420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        controls = QHBoxLayout()
        date_label = QLabel("估值日期")
        date_label.setObjectName("Muted")
        self.date_edit = date_edit()
        self.date_edit.setFixedWidth(130)
        self.date_edit.dateChanged.connect(lambda _value: self._load())
        controls.addWidget(date_label)
        controls.addWidget(self.date_edit)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.table = make_table(HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        set_columns(self.table, [150, 96, 130, 120, 130, 200])
        align_headers(self.table, (2, 3, 4))
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Hint")
        layout.addWidget(self.status_label)

        layout.addLayout(dialog_footer(self, self._save, save_text="保存全部"))

        self._load()

    def _selected_date(self) -> date:
        return from_qdate(self.date_edit.date())

    def _load(self) -> None:
        day = self._selected_date()
        try:
            with db.session_scope() as session:
                self._rows = snapshot_service.batch_context(
                    session, day, account_id=self.account_id
                )
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "加载失败", exc)
            return
        self._fill_table(day)

    def _fill_table(self, day: date) -> None:
        self.table.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            row_symbol = symbol_for(row.currency, self.symbol)
            values = [
                row.item_name,
                CATEGORY_LABELS.get(row.category, row.category),
                fmt_money(row.latest_value, row_symbol),
                fmt_money(row.existing_value, row_symbol, placeholder="—"),
            ]
            for column, text in enumerate(values):
                self.table.setItem(
                    row_index,
                    column,
                    table_item(text, align_right=column in (2, 3)),
                )
            value_edit = QLineEdit()
            value_edit.setPlaceholderText("输入估值")
            value_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.table.setCellWidget(row_index, 4, value_edit)
            note_edit = QLineEdit()
            note_edit.setPlaceholderText("可选备注")
            note_edit.setText(row.existing_note)
            self.table.setCellWidget(row_index, 5, note_edit)
        existing = sum(1 for row in self._rows if row.existing_value is not None)
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            f"{self.account_name} 共 {len(self._rows)} 个子项，"
            f"{existing} 个在 {day.strftime('%Y-%m-%d')} 已有估值；留空表示不更新。"
        )

    def _collect(self) -> tuple:
        entries: List[BatchEntry] = []
        errors: List[str] = []
        for row_index, row in enumerate(self._rows):
            value_widget = self.table.cellWidget(row_index, 4)
            note_widget = self.table.cellWidget(row_index, 5)
            if not isinstance(value_widget, QLineEdit):
                continue
            text = value_widget.text().strip()
            if not text:
                continue
            try:
                value = parse_amount(text, field="估值")
            except AmountError as exc:
                errors.append(f"{row.item_name}：{exc}")
                continue
            note = note_widget.text().strip() if isinstance(note_widget, QLineEdit) else ""
            entries.append(BatchEntry(item_id=row.item_id, value=value, note=note))
        return entries, errors

    def _save(self) -> None:
        if not self._rows:
            show_warning(self, "没有可保存的数据", "该账户还没有类别子项。")
            return
        entries, errors = self._collect()
        if errors:
            show_warning(self, "请修正输入", "以下子项的估值无效：\n" + "\n".join(errors[:8]))
            return
        if not entries:
            show_warning(self, "没有可保存的数据", "请至少为一个子项填写估值。")
            return

        day = self._selected_date()
        try:
            with db.session_scope() as session:
                result = snapshot_service.save_batch(session, day, entries)
        except BatchConflictError as exc:
            if not confirm(
                self,
                "覆盖已有估值",
                f"{exc}\n是否覆盖这些子项在 {day.strftime('%Y-%m-%d')} 的估值？",
            ):
                return
            try:
                with db.session_scope() as session:
                    result = snapshot_service.save_batch(
                        session, day, entries, overwrite=True
                    )
            except Exception as overwrite_error:  # noqa: BLE001
                show_exception(self, "保存失败", overwrite_error)
                return
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "保存失败", exc)
            return

        self.saved_total = result.total
        self.saved_created = result.created
        self.saved_updated = result.updated
        self.accept()
