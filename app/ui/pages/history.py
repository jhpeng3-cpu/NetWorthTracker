"""历史快照明细与净资产变化拆解。"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.db.engine import db
from app.services import accounts as account_service
from app.services import analytics, snapshots as snapshot_service
from app.services.analytics import Decomposition
from app.services.snapshots import SnapshotRow
from app.ui.common import (
    confirm,
    danger_button,
    make_table,
    primary_button,
    selected_row,
    set_columns,
    show_error,
    show_warning,
    table_item,
)
from app.ui.dialogs.snapshot_dialog import SnapshotEditDialog, to_qdate
from app.ui.pages.base import BasePage
from app.ui.styles import palette
from app.utils.async_task import run_async
from app.utils.dates import add_months
from app.utils.money import fmt_money, fmt_signed_money


class HistoryPage(BasePage):
    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(config, parent)
        self._rows: Dict[int, SnapshotRow] = {}
        self._list_request = 0
        self._compare_request = 0
        self._theme = config.theme
        self._build_ui()
        self._load_filter_accounts()
        self._query()

    def _build_ui(self) -> None:
        self.add_header("历史与明细", "筛选、修改估值快照，并对比任意两个日期的净资产变化。")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        self.root.addWidget(splitter, 1)

        # ---- 快照明细 ----
        list_group = QGroupBox("快照明细")
        list_layout = QVBoxLayout(list_group)
        list_layout.setContentsMargins(10, 12, 10, 10)
        list_layout.setSpacing(8)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        account_label = QLabel("账户")
        account_label.setObjectName("Muted")
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(220)
        start_label = QLabel("从")
        start_label.setObjectName("Muted")
        self.start_edit = QDateEdit()
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_edit.setDate(to_qdate(add_months(date.today(), -12)))
        end_label = QLabel("到")
        end_label.setObjectName("Muted")
        self.end_edit = QDateEdit()
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_edit.setDate(QDate.currentDate())
        query_button = primary_button("查询")
        query_button.clicked.connect(self._query)
        reset_button = QPushButton("重置筛选")
        reset_button.clicked.connect(self._reset_filters)
        filters.addWidget(account_label)
        filters.addWidget(self.account_combo)
        filters.addWidget(start_label)
        filters.addWidget(self.start_edit)
        filters.addWidget(end_label)
        filters.addWidget(self.end_edit)
        filters.addWidget(query_button)
        filters.addWidget(reset_button)
        filters.addStretch(1)
        list_layout.addLayout(filters)

        self.list_table = make_table(["日期", "账户", "方向", "类别", "估值", "备注"])
        set_columns(self.list_table, [110, 190, 60, 100, 140, 250])
        self.list_table.itemDoubleClicked.connect(lambda _item: self._edit_snapshot())
        list_layout.addWidget(self.list_table, 1)

        list_actions = QHBoxLayout()
        self.list_hint = QLabel("")
        self.list_hint.setObjectName("Hint")
        self.edit_button = QPushButton("编辑选中")
        self.edit_button.clicked.connect(self._edit_snapshot)
        self.delete_button = danger_button("删除选中")
        self.delete_button.clicked.connect(self._delete_snapshot)
        list_actions.addWidget(self.list_hint)
        list_actions.addStretch(1)
        list_actions.addWidget(self.edit_button)
        list_actions.addWidget(self.delete_button)
        list_layout.addLayout(list_actions)
        splitter.addWidget(list_group)

        # ---- 变化拆解 ----
        compare_group = QGroupBox("净资产变化拆解")
        compare_layout = QVBoxLayout(compare_group)
        compare_layout.setContentsMargins(10, 12, 10, 10)
        compare_layout.setSpacing(8)

        compare_controls = QHBoxLayout()
        compare_controls.setSpacing(8)
        start_label2 = QLabel("期初")
        start_label2.setObjectName("Muted")
        self.compare_start = QDateEdit()
        self.compare_start.setCalendarPopup(True)
        self.compare_start.setDisplayFormat("yyyy-MM-dd")
        self.compare_start.setDate(to_qdate(add_months(date.today(), -1)))
        end_label2 = QLabel("期末")
        end_label2.setObjectName("Muted")
        self.compare_end = QDateEdit()
        self.compare_end.setCalendarPopup(True)
        self.compare_end.setDisplayFormat("yyyy-MM-dd")
        self.compare_end.setDate(QDate.currentDate())
        compare_button = primary_button("对比")
        compare_button.clicked.connect(self._compare)
        compare_controls.addWidget(start_label2)
        compare_controls.addWidget(self.compare_start)
        compare_controls.addWidget(end_label2)
        compare_controls.addWidget(self.compare_end)
        compare_controls.addWidget(compare_button)
        self.compare_hint = QLabel("选择两个日期后点击「对比」。")
        self.compare_hint.setObjectName("Hint")
        compare_controls.addSpacing(8)
        compare_controls.addWidget(self.compare_hint)
        compare_controls.addStretch(1)
        compare_layout.addLayout(compare_controls)

        summary_frame = QFrame()
        summary_frame.setObjectName("Panel")
        summary_layout = QGridLayout(summary_frame)
        summary_layout.setContentsMargins(12, 8, 12, 8)
        summary_layout.setSpacing(6)
        headers = ["", "总资产", "总负债", "净资产"]
        for column, text in enumerate(headers):
            label = QLabel(text)
            label.setObjectName("Muted")
            summary_layout.addWidget(label, 0, column)
        self.summary_labels: Dict[tuple, QLabel] = {}
        row_titles = ["期初", "期末", "变化"]
        for row_index, title in enumerate(row_titles, start=1):
            title_label = QLabel(title)
            title_label.setObjectName("SectionTitle")
            summary_layout.addWidget(title_label, row_index, 0)
            for column in range(1, 4):
                value_label = QLabel("—")
                value_label.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                summary_layout.addWidget(value_label, row_index, column)
                self.summary_labels[(row_index, column)] = value_label
        for column in range(4):
            summary_layout.setColumnStretch(column, 1)
        compare_layout.addWidget(summary_frame)

        self.compare_table = make_table(
            ["账户", "方向", "类别", "期初估值", "期末估值", "变化额"]
        )
        set_columns(self.compare_table, [210, 70, 110, 150, 150, 150])
        self.compare_table.horizontalHeader().setStretchLastSection(True)
        compare_layout.addWidget(self.compare_table, 1)
        splitter.addWidget(compare_group)
        splitter.setSizes([430, 330])

    def _load_filter_accounts(self) -> None:
        if not db.is_configured:
            return
        try:
            with db.session_scope() as session:
                accounts = account_service.list_overviews(session, include_archived=True)
        except Exception as exc:  # noqa: BLE001
            show_error(self, "加载失败", str(exc))
            return
        current = self.account_combo.currentData()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItem("全部账户", None)
        for account in accounts:
            self.account_combo.addItem(account.display_name, account.id)
        if current is not None:
            index = self.account_combo.findData(current)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
        self.account_combo.blockSignals(False)

    def refresh(self) -> None:
        self._load_filter_accounts()
        self._query()

    def _reset_filters(self) -> None:
        self.account_combo.setCurrentIndex(0)
        self.start_edit.setDate(to_qdate(add_months(date.today(), -12)))
        self.end_edit.setDate(QDate.currentDate())
        self._query()

    def _selected_date(self, edit: QDateEdit) -> date:
        value = edit.date()
        return date(value.year(), value.month(), value.day())

    def _query(self) -> None:
        if not db.is_configured:
            return
        start = self._selected_date(self.start_edit)
        end = self._selected_date(self.end_edit)
        if start > end:
            show_warning(self, "日期范围无效", "开始日期不能晚于结束日期。")
            return
        account_id = self.account_combo.currentData()
        self._list_request += 1
        request_id = self._list_request
        self.list_hint.setText("查询中…")

        def task() -> List[SnapshotRow]:
            with db.session_scope() as session:
                return snapshot_service.list_snapshots(
                    session,
                    account_id=int(account_id) if account_id is not None else None,
                    start=start,
                    end=end,
                    limit=1000,
                )

        run_async(
            task,
            lambda rows: self._apply_rows(rows, request_id),
            lambda message: self._on_list_error(message, request_id),
        )

    def _on_list_error(self, message: str, request_id: int) -> None:
        if request_id != self._list_request:
            return
        self.list_hint.setText("查询失败")
        show_error(self, "查询失败", message)

    def _apply_rows(self, rows: object, request_id: int) -> None:
        if request_id != self._list_request or not isinstance(rows, list):
            return
        self._rows = {row.id: row for row in rows}
        self.list_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.snapshot_date.strftime("%Y-%m-%d"),
                row.account_name,
                row.side_label,
                row.category_label,
                fmt_money(row.value, self.symbol),
                row.note,
            ]
            for column, text in enumerate(values):
                self.list_table.setItem(
                    row_index,
                    column,
                    table_item(
                        text,
                        align_right=column == 4,
                        user_data=row.id if column == 0 else None,
                    ),
                )
        if not rows:
            self.list_hint.setText("没有符合条件的快照。")
        elif len(rows) >= 1000:
            self.list_hint.setText("仅显示前 1000 条，请缩小日期范围。")
        else:
            self.list_hint.setText(f"共 {len(rows)} 条记录。")

    def _selected_snapshot(self) -> Optional[SnapshotRow]:
        row_index = selected_row(self.list_table)
        if row_index < 0:
            return None
        item = self.list_table.item(row_index, 0)
        snapshot_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return self._rows.get(int(snapshot_id)) if snapshot_id is not None else None

    def _edit_snapshot(self) -> None:
        row = self._selected_snapshot()
        if row is None:
            show_warning(self, "请选择记录", "请先在表格中选择一条快照。")
            return

        def save(day: date, value: object, note: str) -> None:
            with db.session_scope() as session:
                snapshot_service.update_snapshot(session, row.id, day, value, note)

        dialog = SnapshotEditDialog(row, self.symbol, save, parent=self)
        if dialog.exec():
            self._query()
            self.data_changed.emit()

    def _delete_snapshot(self) -> None:
        row = self._selected_snapshot()
        if row is None:
            show_warning(self, "请选择记录", "请先在表格中选择一条快照。")
            return
        if not confirm(
            self,
            "删除快照",
            f"确定删除 {row.account_name} 在 {row.snapshot_date.strftime('%Y-%m-%d')} "
            f"的估值 {fmt_money(row.value, self.symbol)} 吗？",
        ):
            return
        try:
            with db.session_scope() as session:
                snapshot_service.delete_snapshot(session, row.id)
        except Exception as exc:  # noqa: BLE001
            show_error(self, "删除失败", str(exc))
            return
        self._query()
        self.data_changed.emit()

    def _compare(self) -> None:
        if not db.is_configured:
            return
        start = self._selected_date(self.compare_start)
        end = self._selected_date(self.compare_end)
        if start > end:
            show_warning(self, "日期范围无效", "期初日期不能晚于期末日期。")
            return
        self._compare_request += 1
        request_id = self._compare_request
        self.compare_hint.setText("计算中…")

        def task() -> Decomposition:
            with db.session_scope() as session:
                return analytics.decompose(session, start, end)

        run_async(
            task,
            lambda result: self._apply_compare(result, request_id),
            lambda message: self._on_compare_error(message, request_id),
        )

    def _on_compare_error(self, message: str, request_id: int) -> None:
        if request_id != self._compare_request:
            return
        self.compare_hint.setText("计算失败")
        show_error(self, "对比失败", message)

    def _apply_compare(self, result: object, request_id: int) -> None:
        if request_id != self._compare_request or not isinstance(result, Decomposition):
            return
        start = result.start_point
        end = result.end_point
        colors = palette(self._theme)
        symbol = self.symbol
        values = [
            (
                start.on_date.strftime("%Y-%m-%d"),
                [start.assets, start.liabilities, start.net],
            ),
            (
                end.on_date.strftime("%Y-%m-%d"),
                [end.assets, end.liabilities, end.net],
            ),
            (
                "变化",
                [end.assets - start.assets, end.liabilities - start.liabilities, end.net - start.net],
            ),
        ]
        for row_index, (label, amounts) in enumerate(values, start=1):
            formatter = fmt_signed_money if row_index == 3 else fmt_money
            self.summary_labels[(row_index, 1)].setText(formatter(amounts[0], symbol))
            self.summary_labels[(row_index, 2)].setText(formatter(amounts[1], symbol))
            net_label = self.summary_labels[(row_index, 3)]
            net_label.setText(formatter(amounts[2], symbol))
            if row_index == 3:
                tone = colors["success"] if amounts[2] > 0 else (
                    colors["danger"] if amounts[2] < 0 else colors["text"]
                )
                net_label.setStyleSheet(f"color: {tone}; font-weight: 600;")
                self.summary_labels[(row_index, 1)].setStyleSheet(
                    "font-weight: 600;"
                )
                self.summary_labels[(row_index, 2)].setStyleSheet(
                    "font-weight: 600;"
                )

        self.compare_table.setRowCount(len(result.rows))
        for row_index, row in enumerate(result.rows):
            values_row = [
                row.account_name,
                row.side_label,
                row.category_label,
                fmt_money(row.start_value, symbol),
                fmt_money(row.end_value, symbol),
                fmt_signed_money(row.change, symbol),
            ]
            for column, text in enumerate(values_row):
                self.compare_table.setItem(
                    row_index,
                    column,
                    table_item(text, align_right=column in (3, 4, 5)),
                )
        self.compare_hint.setText(
            f"共 {len(result.rows)} 个账户；按估值变化额降序排列。"
        )
