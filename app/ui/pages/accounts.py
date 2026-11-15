"""账户管理页面。"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.db.engine import db
from app.db.models import SIDE_ASSET, SIDE_LIABILITY
from app.services import accounts as account_service
from app.services.accounts import AccountOverview
from app.ui.common import (
    confirm,
    danger_button,
    make_table,
    primary_button,
    selected_row,
    set_columns,
    show_error,
    table_item,
)
from app.ui.dialogs.account_dialog import AccountDialog
from app.ui.pages.base import BasePage
from app.ui.styles import palette
from app.utils.money import fmt_money


class AccountsPage(BasePage):
    HEADERS = ["名称", "类别", "币种", "最新估值", "估值日期", "备注", "状态"]

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(config, parent)
        self._rows: Dict[int, AccountOverview] = {}
        self._clearing = False
        self._theme = config.theme
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.add_header("账户管理", "维护资产与负债账户；归档后保留历史，但不计入净资产。")

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.new_button = primary_button("新增账户")
        self.new_button.clicked.connect(self._new_account)
        self.edit_button = QPushButton("编辑")
        self.edit_button.clicked.connect(self._edit_account)
        self.archive_button = QPushButton("归档")
        self.archive_button.clicked.connect(self._toggle_archive)
        self.delete_button = danger_button("删除")
        self.delete_button.clicked.connect(self._delete_account)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh)
        self.show_archived = QCheckBox("显示已归档")
        self.show_archived.toggled.connect(self.refresh)
        actions.addWidget(self.new_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.archive_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        actions.addWidget(self.show_archived)
        actions.addWidget(self.refresh_button)
        self.root.addLayout(actions)

        self.asset_group = QGroupBox("资产账户")
        asset_layout = QVBoxLayout(self.asset_group)
        asset_layout.setContentsMargins(8, 8, 8, 8)
        self.asset_table = self._make_account_table()
        asset_layout.addWidget(self.asset_table)
        self.root.addWidget(self.asset_group, 1)

        self.liability_group = QGroupBox("负债账户")
        liability_layout = QVBoxLayout(self.liability_group)
        liability_layout.setContentsMargins(8, 8, 8, 8)
        self.liability_table = self._make_account_table()
        liability_layout.addWidget(self.liability_table)
        self.root.addWidget(self.liability_group, 1)

        self.asset_table.itemSelectionChanged.connect(
            lambda: self._on_selection(self.asset_table, self.liability_table)
        )
        self.liability_table.itemSelectionChanged.connect(
            lambda: self._on_selection(self.liability_table, self.asset_table)
        )
        self._update_buttons()

    def _make_account_table(self) -> QTableWidget:
        table = make_table(self.HEADERS, stretch_last=False)
        set_columns(table, [190, 100, 64, 140, 104, 240, 76])
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        table.doubleClicked.connect(lambda _index: self._edit_account())
        return table

    def refresh(self) -> None:
        if not db.is_configured:
            return
        try:
            with db.session_scope() as session:
                rows = account_service.list_overviews(
                    session, include_archived=self.show_archived.isChecked()
                )
        except Exception as exc:  # noqa: BLE001
            show_error(self, "加载失败", str(exc))
            return
        self._rows = {row.id: row for row in rows}
        assets = [row for row in rows if row.side == SIDE_ASSET]
        liabilities = [row for row in rows if row.side == SIDE_LIABILITY]
        self._fill_table(self.asset_table, assets)
        self._fill_table(self.liability_table, liabilities)
        self._set_group_title(self.asset_group, "资产账户", assets)
        self._set_group_title(self.liability_group, "负债账户", liabilities)
        self._update_buttons()

    def _set_group_title(
        self, group: QGroupBox, label: str, rows: List[AccountOverview]
    ) -> None:
        total = sum(
            (row.latest_value for row in rows if row.latest_value is not None),
            Decimal("0.00"),
        )
        group.setTitle(
            f"{label} · {len(rows)} 个 · 最新合计 {fmt_money(total, self.symbol)}"
        )

    def _fill_table(self, table: QTableWidget, rows: List[AccountOverview]) -> None:
        colors = palette(self._theme)
        table.setRowCount(len(rows))
        for row_index, overview in enumerate(rows):
            muted_color = colors["muted"] if overview.archived else None
            values = [
                overview.name,
                overview.category_label,
                overview.currency_label,
                fmt_money(overview.latest_value, self.symbol),
                overview.latest_date.strftime("%Y-%m-%d") if overview.latest_date else "—",
                overview.note,
                "已归档" if overview.archived else "在用",
            ]
            for column, text in enumerate(values):
                item = table_item(
                    text,
                    align_right=column in (3, 4),
                    color=muted_color,
                    user_data=overview.id if column == 0 else None,
                )
                table.setItem(row_index, column, item)

    def _on_selection(self, source: QTableWidget, other: QTableWidget) -> None:
        if self._clearing:
            return
        if selected_row(source) >= 0 and other.selectionModel().hasSelection():
            self._clearing = True
            other.clearSelection()
            self._clearing = False
        self._update_buttons()

    def _selected(self) -> Optional[AccountOverview]:
        for table in (self.asset_table, self.liability_table):
            row_index = selected_row(table)
            if row_index >= 0:
                item = table.item(row_index, 0)
                account_id = item.data(Qt.ItemDataRole.UserRole) if item else None
                if account_id is not None:
                    return self._rows.get(int(account_id))
        return None

    def _update_buttons(self) -> None:
        selected = self._selected()
        has_selection = selected is not None
        self.edit_button.setEnabled(has_selection)
        self.archive_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
        if selected is not None:
            self.archive_button.setText("恢复" if selected.archived else "归档")
        else:
            self.archive_button.setText("归档")

    def _after_change(self) -> None:
        self.refresh()
        self.data_changed.emit()

    def _new_account(self) -> None:
        def save(payload: Dict[str, str]) -> None:
            with db.session_scope() as session:
                account_service.create_account(session, **payload)

        dialog = AccountDialog(save, parent=self)
        if dialog.exec():
            self._after_change()

    def _edit_account(self) -> None:
        overview = self._selected()
        if overview is None:
            return

        def save(payload: Dict[str, str]) -> None:
            with db.session_scope() as session:
                account_service.update_account(
                    session,
                    overview.id,
                    name=payload["name"],
                    side=payload["side"],
                    category=payload["category"],
                    currency=payload["currency"],
                    note=payload["note"],
                )

        dialog = AccountDialog(save, account=overview, parent=self)
        if dialog.exec():
            self._after_change()

    def _toggle_archive(self) -> None:
        overview = self._selected()
        if overview is None:
            return
        target = not overview.archived
        if target and not confirm(
            self,
            "归档账户",
            f"归档 “{overview.name}” 后将不再计入净资产，历史快照仍会保留。是否继续？",
        ):
            return
        try:
            with db.session_scope() as session:
                account_service.set_archived(session, overview.id, target)
        except Exception as exc:  # noqa: BLE001
            show_error(self, "操作失败", str(exc))
            return
        self._after_change()

    def _delete_account(self) -> None:
        overview = self._selected()
        if overview is None:
            return
        try:
            with db.session_scope() as session:
                count = account_service.snapshot_count(session, overview.id)
        except Exception as exc:  # noqa: BLE001
            show_error(self, "读取失败", str(exc))
            return
        if not confirm(
            self,
            "删除账户",
            f"确定删除账户 “{overview.name}” 吗？\n"
            f"其 {count} 条估值快照也会被一并删除，且无法恢复。",
        ):
            return
        try:
            with db.session_scope() as session:
                account_service.delete_account(session, overview.id)
        except Exception as exc:  # noqa: BLE001
            show_error(self, "删除失败", str(exc))
            return
        self._after_change()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self.refresh()
