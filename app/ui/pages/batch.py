"""批量估值录入页面。"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.db.engine import db
from app.db.models import CATEGORY_LABELS, SIDE_LABELS
from app.services import snapshots as snapshot_service
from app.services.snapshots import BatchConflictError, BatchEntry, BatchRow
from app.ui.common import (
    confirm,
    make_table,
    primary_button,
    set_columns,
    show_error,
    show_warning,
    table_item,
)
from app.ui.pages.base import BasePage
from app.utils.money import AmountError, fmt_money, parse_amount


class BatchPage(BasePage):
    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(config, parent)
        self._rows: List[BatchRow] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.add_header(
            "批量录入",
            "适合月末集中更新：为多个账户填写同一日期的估值，留空表示不更新。",
        )

        controls = QHBoxLayout()
        controls.setSpacing(8)
        date_label = QLabel("估值日期")
        date_label.setObjectName("Muted")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setFixedWidth(130)
        self.date_edit.dateChanged.connect(self._on_date_changed)
        self.load_button = QPushButton("载入账户")
        self.load_button.clicked.connect(self.refresh)
        self.save_button = primary_button("保存全部")
        self.save_button.clicked.connect(self._save)
        controls.addWidget(date_label)
        controls.addWidget(self.date_edit)
        controls.addWidget(self.load_button)
        controls.addStretch(1)
        controls.addWidget(self.save_button)
        self.root.addLayout(controls)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Hint")
        self.status_label.setWordWrap(True)
        self.root.addWidget(self.status_label)

        panel = QFrame()
        panel.setObjectName("Panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        self.table = make_table(
            ["账户", "方向", "类别", "最新估值", "当日已有", "估值输入", "备注"]
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        set_columns(self.table, [190, 60, 100, 130, 120, 140, 240])
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        panel_layout.addWidget(self.table)
        self.root.addWidget(panel, 1)

    def refresh(self) -> None:
        if not db.is_configured:
            return
        day = self._selected_date()
        try:
            with db.session_scope() as session:
                rows = snapshot_service.batch_context(session, day)
        except Exception as exc:  # noqa: BLE001
            show_error(self, "加载失败", str(exc))
            return
        self._rows = rows
        self._fill_table()
        existing = sum(1 for row in rows if row.existing_value is not None)
        if rows:
            self.status_label.setStyleSheet("")
            self.status_label.setText(
                f"已载入 {len(rows)} 个未归档账户，其中 {existing} 个在 "
                f"{day.strftime('%Y-%m-%d')} 已有快照。"
            )
        else:
            self.status_label.setText("暂无未归档账户，请先到「账户管理」新增账户。")

    def _fill_table(self) -> None:
        self.table.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            side = SIDE_LABELS.get(row.side, row.side)
            category = CATEGORY_LABELS.get(row.category, row.category)
            values = [
                row.account_name,
                side,
                category,
                fmt_money(row.latest_value, self.symbol),
                fmt_money(row.existing_value, self.symbol, placeholder="—"),
            ]
            for column, text in enumerate(values):
                item = table_item(
                    text,
                    align_right=column in (3, 4),
                    user_data=row.account_id if column == 0 else None,
                )
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, column, item)

            value_edit = QLineEdit()
            value_edit.setPlaceholderText("输入估值")
            value_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
            value_edit.setToolTip("留空表示不更新该账户")
            self.table.setCellWidget(row_index, 5, value_edit)

            note_edit = QLineEdit()
            note_edit.setPlaceholderText("可选备注")
            note_edit.setText(row.existing_note)
            self.table.setCellWidget(row_index, 6, note_edit)

    def _selected_date(self) -> date:
        qdate = self.date_edit.date()
        return date(qdate.year(), qdate.month(), qdate.day())

    def _on_date_changed(self, *_args) -> None:
        self.status_label.setStyleSheet("")
        self.status_label.setText("日期已改变，点击「载入账户」查看当日已有快照。")

    def _save(self) -> None:
        if not self._rows:
            show_warning(self, "没有可保存的数据", "请先点击「载入账户」。")
            return
        entries: List[BatchEntry] = []
        errors: List[str] = []
        for row_index, row in enumerate(self._rows):
            value_widget = self.table.cellWidget(row_index, 5)
            note_widget = self.table.cellWidget(row_index, 6)
            if not isinstance(value_widget, QLineEdit):
                continue
            text = value_widget.text().strip()
            if not text:
                continue
            try:
                value = parse_amount(text, field="估值")
            except AmountError as exc:
                errors.append(f"{row.account_name}：{exc}")
                continue
            note = note_widget.text().strip() if isinstance(note_widget, QLineEdit) else ""
            entries.append(
                BatchEntry(
                    account_id=row.account_id,
                    value=value,
                    note=note,
                )
            )
        if errors:
            show_warning(
                self,
                "请修正输入",
                "以下账户的估值无效：\n" + "\n".join(errors[:8]),
            )
            return
        if not entries:
            show_warning(self, "没有可保存的数据", "请至少为一个账户填写估值。")
            return

        day = self._selected_date()
        try:
            with db.session_scope() as session:
                result = snapshot_service.save_batch(session, day, entries)
        except BatchConflictError as exc:
            if not confirm(
                self,
                "覆盖已有快照",
                f"{exc}\n是否覆盖这些账户在 {day.strftime('%Y-%m-%d')} 的估值？",
            ):
                return
            try:
                with db.session_scope() as session:
                    result = snapshot_service.save_batch(
                        session, day, entries, overwrite=True
                    )
            except Exception as overwrite_error:  # noqa: BLE001
                show_error(self, "保存失败", str(overwrite_error))
                return
        except Exception as exc:  # noqa: BLE001
            show_error(self, "保存失败", str(exc))
            return

        self.refresh()
        self.status_label.setStyleSheet("color: #059669;")
        self.status_label.setText(
            f"已保存 {result.total} 个账户的估值（新建 {result.created}，更新 {result.updated}）。"
        )
        self.data_changed.emit()
