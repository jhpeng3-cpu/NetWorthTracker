"""账户管理页面：左侧账户列表 + 右侧类别子项明细。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.db.engine import db
from app.db.models import (
    CURRENCY_CODES,
    CURRENCY_LABELS,
    SIDE_ASSET,
    SIDE_LABELS,
    SIDE_LIABILITY,
)
from app.services import accounts as account_service
from app.services import exchange_rates
from app.services import profit
from app.services import quotes
from app.services import snapshots as snapshot_service
from app.services.accounts import AccountOverview, ItemInput, ItemOverview
from app.services.profit import CostSummary
from app.services.snapshots import SnapshotExistsError
from app.utils.exceptions import AppValidationError
from app.ui.common import (
    confirm,
    danger_button,
    align_headers,
    make_table,
    primary_button,
    set_columns,
    show_exception,
    show_warning,
    table_item,
)
from app.ui.dialogs.account_batch_dialog import AccountBatchDialog
from app.ui.dialogs.account_dialog import AccountDialog
from app.ui.dialogs.item_dialog import ItemDialog
from app.ui.dialogs.snapshot_entry_dialog import SnapshotEntryDialog
from app.ui.pages.base import BasePage
from app.ui.styles import palette
from app.utils.async_task import run_async
from app.utils.money import fmt_money, fmt_percent, symbol_for


class AccountsPage(BasePage):
    ACCOUNT_HEADERS = ["名称", "估值(CNY)", "状态"]
    ITEM_HEADERS = ["子项", "类别", "现价", "最新估值", "折合人民币", "盈亏额", "盈亏率", "估值日期"]

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(config, parent)
        self._rows: Dict[int, AccountOverview] = {}
        self._theme = config.theme
        self._today = date.today()
        self._lookup = lambda _code, _day: 1
        self._rate_dates: Dict[str, date] = {}
        self._costs: Dict[int, CostSummary] = {}
        self._display_code = "CNY"
        self._build_ui()
        self.refresh()

    # ---- 构建 ----
    def _build_ui(self) -> None:
        self.add_header(
            "账户管理",
            "一个账户可包含多个类别子项；估值按子项记录，账户金额为子项之和。",
        )

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.new_button = primary_button("新增账户")
        self.new_button.clicked.connect(self._new_account)
        self.edit_button = QPushButton("编辑账户")
        self.edit_button.clicked.connect(self._edit_account)
        self.archive_button = QPushButton("归档")
        self.archive_button.clicked.connect(self._toggle_archive)
        self.delete_button = danger_button("删除")
        self.delete_button.clicked.connect(self._delete_account)
        self.show_archived = QCheckBox("显示已归档")
        self.show_archived.stateChanged.connect(self.refresh)
        self.quote_button = QPushButton("刷新行情")
        self.quote_button.setToolTip("拉取已配置代码的子项最新价，并写入当日估值")
        self.quote_button.clicked.connect(self._refresh_quotes)
        toolbar.addWidget(self.new_button)
        toolbar.addWidget(self.edit_button)
        toolbar.addWidget(self.archive_button)
        toolbar.addWidget(self.delete_button)
        toolbar.addWidget(self.show_archived)
        toolbar.addWidget(self.quote_button)
        toolbar.addStretch(1)
        self.rate_strip = QWidget()
        self.rate_strip_layout = QHBoxLayout(self.rate_strip)
        self.rate_strip_layout.setContentsMargins(0, 0, 0, 0)
        self.rate_strip_layout.setSpacing(6)
        toolbar.addWidget(self.rate_strip)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Hint")
        toolbar.addWidget(self.count_label)
        self.root.addLayout(toolbar)

        content = QHBoxLayout()
        content.setSpacing(12)

        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        left_title = QLabel("账户")
        left_title.setObjectName("SectionTitle")
        self.display_currency_combo = QComboBox()
        self.display_currency_combo.setFixedWidth(150)
        self.display_currency_combo.setToolTip("左侧账户估值统一折算为所选币种")
        for code in CURRENCY_CODES:
            self.display_currency_combo.addItem(f"{CURRENCY_LABELS[code]}（{code}）", code)
        self.display_currency_combo.currentIndexChanged.connect(
            self._on_display_currency_changed
        )
        title_row.addWidget(left_title)
        title_row.addStretch(1)
        title_row.addWidget(self.display_currency_combo)
        left_layout.addLayout(title_row)

        self.account_splitter = QSplitter(Qt.Orientation.Vertical)
        self.account_splitter.setChildrenCollapsible(False)
        self.account_splitter.setHandleWidth(6)
        asset_pane, self.asset_title, self.asset_table = self._make_account_pane(
            "资产账户"
        )
        liability_pane, self.liability_title, self.liability_table = (
            self._make_account_pane("负债账户")
        )
        self.account_splitter.addWidget(asset_pane)
        self.account_splitter.addWidget(liability_pane)
        left_layout.addWidget(self.account_splitter, 1)
        content.addWidget(left_panel, 4)

        right_panel = QFrame()
        right_panel.setObjectName("Panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 14, 16, 14)
        right_layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.detail_title = QLabel("选择一个账户查看类别子项")
        self.detail_title.setObjectName("SectionTitle")
        self.detail_meta = QLabel("—")
        self.detail_meta.setObjectName("Hint")
        self.detail_meta.setWordWrap(True)
        title_box.addWidget(self.detail_title)
        title_box.addWidget(self.detail_meta)
        header.addLayout(title_box, 1)
        right_layout.addLayout(header)

        items_toolbar = QHBoxLayout()
        items_toolbar.setSpacing(8)
        items_title = QLabel("类别子项")
        items_title.setStyleSheet("font-weight: 600;")
        self.item_hint = QLabel("")
        self.item_hint.setObjectName("Hint")
        self.add_item_button = QPushButton("新增子项")
        self.add_item_button.clicked.connect(self._add_item)
        self.edit_item_button = QPushButton("编辑子项")
        self.edit_item_button.clicked.connect(self._edit_item)
        self.delete_item_button = QPushButton("删除子项")
        self.delete_item_button.clicked.connect(self._delete_item)
        self.cost_button = QPushButton("成本批次…")
        self.cost_button.clicked.connect(self._edit_costs)
        items_toolbar.addWidget(items_title)
        items_toolbar.addWidget(self.item_hint, 1)
        items_toolbar.addWidget(self.add_item_button)
        items_toolbar.addWidget(self.edit_item_button)
        items_toolbar.addWidget(self.delete_item_button)
        items_toolbar.addWidget(self.cost_button)
        right_layout.addLayout(items_toolbar)

        entry_row = QHBoxLayout()
        entry_row.setSpacing(8)
        entry_hint = QLabel("选中子项后录入；也可双击「最新估值」列")
        entry_hint.setObjectName("Hint")
        self.entry_button = primary_button("录入估值…")
        self.entry_button.clicked.connect(self._entry_value)
        self.batch_entry_button = QPushButton("批量录入…")
        self.batch_entry_button.clicked.connect(self._batch_entry)
        entry_row.addWidget(entry_hint, 1)
        entry_row.addWidget(self.entry_button)
        entry_row.addWidget(self.batch_entry_button)
        right_layout.addLayout(entry_row)

        self.items_table = make_table(self.ITEM_HEADERS)
        set_columns(self.items_table, [110, 62, 82, 98, 100, 92, 62, 84])
        align_headers(self.items_table, (2, 3, 4, 5, 6, 7))
        self.items_table.doubleClicked.connect(self._on_item_double_clicked)
        self.items_table.horizontalHeader().setStretchLastSection(True)
        self.items_table.itemSelectionChanged.connect(self._update_buttons)
        right_layout.addWidget(self.items_table, 1)
        content.addWidget(right_panel, 6)

        self.root.addLayout(content, 1)

    def _account_headers(self) -> List[str]:
        return ["名称", f"估值({self._display_code})", "状态"]

    def _make_account_table(self) -> QTableWidget:
        table = make_table(self._account_headers(), stretch_last=False)
        set_columns(table, [150, 130, 64])
        align_headers(table, (1,))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.itemSelectionChanged.connect(self._on_account_selected)
        table.doubleClicked.connect(lambda _index: self._edit_account())
        return table

    def _make_account_pane(self, title_text: str):
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title = QLabel(title_text)
        title.setObjectName("Hint")
        title.setFixedHeight(18)
        table = self._make_account_table()
        layout.addWidget(title)
        layout.addWidget(table, 1)
        return pane, title, table

    # ---- 数据 ----
    def refresh(self) -> None:
        if not db.is_configured:
            return
        try:
            with db.session_scope() as session:
                rows = account_service.list_overviews(
                    session, include_archived=self.show_archived.isChecked()
                )
                # 实时金额统一按各币种最新汇率折算，手动刷新汇率后立即生效。
                self._lookup = exchange_rates.latest_lookup(session)
                self._rate_dates = {
                    code: day
                    for code, (day, _rate) in exchange_rates.latest_rates(session).items()
                }
                self._costs = profit.cost_summaries(
                    session,
                    [item.id for overview in rows for item in overview.items],
                )
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "加载失败", exc)
            return
        self._today = date.today()
        current_id = self._selected_account_id()
        self._rows = {row.id: row for row in rows}
        self._fill_tables(rows)
        self._render_rate_strip(rows)
        self.count_label.setText(f"共 {len(rows)} 个账户")
        if current_id is not None:
            self._select_account(current_id)
        if self._selected_account_id() is None:
            if self.asset_table.rowCount():
                self.asset_table.selectRow(0)
            elif self.liability_table.rowCount():
                self.liability_table.selectRow(0)
        self._render_detail()

    def _render_rate_strip(self, rows: List[AccountOverview]) -> None:
        """顶部汇率条：圆角卡片展示当前账户实际使用的非人民币币种。"""
        while self.rate_strip_layout.count():
            item = self.rate_strip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        used: List[str] = []
        for overview in rows:
            for code in overview.item_currencies:
                if code != "CNY" and code not in used:
                    used.append(code)
        if not used:
            hint = QLabel("当前无外币账户")
            hint.setObjectName("Hint")
            self.rate_strip_layout.addWidget(hint)
            self._append_rate_button()
            return

        caption = QLabel("当日汇率")
        caption.setObjectName("Hint")
        self.rate_strip_layout.addWidget(caption)

        dates: List[date] = []
        for code in CURRENCY_CODES:
            if code not in used:
                continue
            known = code in self._rate_dates
            chip = QFrame()
            chip.setObjectName("RateChip")
            chip_layout = QHBoxLayout(chip)
            chip_layout.setContentsMargins(10, 4, 10, 4)
            chip_layout.setSpacing(6)
            code_label = QLabel(CURRENCY_LABELS.get(code, code))
            code_label.setObjectName("RateCode")
            value_label = QLabel(f"{self._lookup(code, self._today):.4f}" if known else "—")
            value_label.setObjectName("RateValue")
            chip_layout.addWidget(code_label)
            chip_layout.addWidget(value_label)
            if known:
                dates.append(self._rate_dates[code])
                chip.setToolTip(
                    f"1 {CURRENCY_LABELS.get(code, code)} = "
                    f"{self._lookup(code, self._today):.4f} 人民币\n"
                    f"汇率日期：{self._rate_dates[code]:%Y-%m-%d}"
                )
            else:
                chip.setToolTip("暂无该币种汇率，应用联网后会自动补全。")
            self.rate_strip_layout.addWidget(chip)

        note = QLabel(f"截至 {max(dates):%m-%d}" if dates else "暂无汇率")
        note.setObjectName("Hint")
        self.rate_strip_layout.addWidget(note)
        self._append_rate_button()

    def _append_rate_button(self) -> None:
        self.refresh_rates_button = QPushButton("刷新汇率")
        self.refresh_rates_button.setToolTip("立即拉取账户所用币种兑人民币的最新汇率")
        self.refresh_rates_button.clicked.connect(self._refresh_rates)
        self.rate_strip_layout.addWidget(self.refresh_rates_button)

    def _refresh_rates(self) -> None:
        if not db.is_configured:
            return
        self.refresh_rates_button.setEnabled(False)
        self.refresh_rates_button.setText("刷新中…")

        def task():
            with db.session_scope() as session:
                return exchange_rates.refresh_rates(session)

        def success(_result):
            self.refresh()
            self.data_changed.emit()

        def failure(message: str):
            self.refresh_rates_button.setEnabled(True)
            self.refresh_rates_button.setText("刷新汇率")
            show_warning(self, "汇率刷新失败", message)

        run_async(task, success, failure)

    def _refresh_quotes(self) -> None:
        if not db.is_configured:
            return
        self.quote_button.setEnabled(False)
        self.quote_button.setText("刷新中…")

        def task():
            with db.session_scope() as session:
                return quotes.refresh_stock_quotes(session)

        def success(result):
            self.quote_button.setEnabled(True)
            self.quote_button.setText("刷新行情")
            self._after_change()
            if result.failed:
                show_warning(
                    self,
                    "部分行情获取失败",
                    "\n".join(result.errors[:6]),
                )

        def failure(message: str):
            self.quote_button.setEnabled(True)
            self.quote_button.setText("刷新行情")
            show_warning(self, "行情刷新失败", message)

        run_async(task, success, failure)

    def _fill_tables(self, rows: List[AccountOverview]) -> None:
        assets = [row for row in rows if row.side == SIDE_ASSET]
        liabilities = [row for row in rows if row.side == SIDE_LIABILITY]
        asset_height = self._fill_one_table(self.asset_table, assets)
        liability_height = self._fill_one_table(self.liability_table, liabilities)
        self.asset_title.setText(f"资产账户 · {len(assets)}")
        self.liability_title.setText(f"负债账户 · {len(liabilities)}")
        self.account_splitter.setSizes([asset_height + 26, liability_height + 26])

    def _fill_one_table(
        self, table: QTableWidget, rows: List[AccountOverview]
    ) -> int:
        """填充账户表，返回内容所需高度（供分栏按比例分配）。"""
        colors = palette(self._theme)
        symbol = symbol_for(self._display_code, self.symbol)
        table.blockSignals(True)
        table.setRowCount(len(rows))
        for row_index, overview in enumerate(rows):
            muted_color = colors["muted"] if overview.archived else None
            total = self._account_total(overview)
            values = [
                overview.name,
                fmt_money(total, symbol, placeholder="—"),
                "已归档" if overview.archived else "在用",
            ]
            for column, text in enumerate(values):
                item = table_item(
                    text,
                    align_right=column == 1,
                    color=muted_color,
                    user_data=overview.id if column == 0 else None,
                )
                if column == 0:
                    item.setToolTip(
                        f"类别：{overview.category_label} · 子项 {len(overview.items)} 个"
                    )
                elif column == 1 and total is None:
                    item.setToolTip("暂无估值，或缺少折算所需汇率")
                table.setItem(row_index, column, item)
        table.blockSignals(False)
        header_height = table.horizontalHeader().sizeHint().height()
        row_height = table.verticalHeader().defaultSectionSize()
        return header_height + len(rows) * row_height + 12

    def _account_total(self, overview: AccountOverview) -> Optional[Decimal]:
        """账户估值折算为左侧选定币种；缺少必要汇率时返回 None。"""
        valued = [item for item in overview.items if item.latest_value is not None]
        if not valued:
            return None
        code = self._display_code
        if code != "CNY" and code not in self._rate_dates:
            return None
        total_cny = Decimal("0.00")
        for item in valued:
            if item.currency != "CNY" and item.currency not in self._rate_dates:
                return None
            total_cny += exchange_rates.to_cny(
                item.latest_value, item.currency, self._today, self._lookup
            )
        if code == "CNY":
            return total_cny
        rate = self._lookup(code, self._today)
        if rate == 0:
            return None
        return (total_cny / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _on_display_currency_changed(self, _index: int) -> None:
        self._display_code = self.display_currency_combo.currentData() or "CNY"
        headers = self._account_headers()
        for table in (self.asset_table, self.liability_table):
            table.setHorizontalHeaderLabels(headers)
            align_headers(table, (1,))
        self.refresh()

    def _selected_account_id(self) -> Optional[int]:
        for table in (self.asset_table, self.liability_table):
            items = table.selectedItems()
            if not items:
                continue
            item = table.item(items[0].row(), 0)
            data = item.data(Qt.ItemDataRole.UserRole) if item else None
            if data is not None:
                return int(data)
        return None

    def _select_account(self, account_id: int) -> None:
        for table in (self.asset_table, self.liability_table):
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == account_id:
                    table.selectRow(row)
                    return

    def _selected_account(self) -> Optional[AccountOverview]:
        account_id = self._selected_account_id()
        return self._rows.get(account_id) if account_id is not None else None

    def _selected_item(self) -> Optional[ItemOverview]:
        account = self._selected_account()
        row = self.items_table.currentRow()
        if account is None or row < 0 or row >= len(account.items):
            return None
        return account.items[row]

    # ---- 明细 ----
    def _on_account_selected(self) -> None:
        source = self.sender()
        other = (
            self.liability_table if source is self.asset_table else self.asset_table
        )
        if source is not None and other.selectionModel() is not None:
            other.blockSignals(True)
            other.clearSelection()
            other.blockSignals(False)
        self._render_detail()

    def _render_detail(self) -> None:
        account = self._selected_account()
        self.items_table.blockSignals(True)
        self.items_table.setRowCount(0)
        self.items_table.blockSignals(False)
        if account is None:
            self.detail_title.setText("选择一个账户查看类别子项")
            self.detail_meta.setText("—")
            self.item_hint.setText("")
            self._update_buttons()
            return

        title = account.name + ("（已归档）" if account.archived else "")
        self.detail_title.setText(title)
        currency_text = (
            "多币种（" + "、".join(CURRENCY_LABELS.get(c, c) for c in account.item_currencies) + "）"
            if account.display_currency == "MIXED"
            else account.currency_label
        )
        parts = [account.side_label, currency_text]
        if account.note:
            parts.append(account.note)
        self.detail_meta.setText(" · ".join(parts))

        foreign = any(item.currency != "CNY" for item in account.items)
        self.items_table.setColumnHidden(4, not foreign)

        colors = palette(self._theme)
        self.items_table.setRowCount(len(account.items))
        for row_index, item in enumerate(account.items):
            symbol = symbol_for(item.currency, self.symbol)
            rate_known = item.currency == "CNY" or item.currency in self._rate_dates
            cny_text = ""
            if item.currency != "CNY":
                if rate_known and item.latest_value is not None:
                    cny_text = fmt_money(
                        exchange_rates.to_cny(
                            item.latest_value, item.currency, self._today, self._lookup
                        ),
                        self.symbol,
                    )
                else:
                    cny_text = "—"
            summary = self._costs.get(item.id)
            pnl_text = "—"
            rate_text = "—"
            tooltip = ""
            if summary is not None:
                avg = summary.avg_unit_cost
                tooltip = (
                    f"成本 {summary.currency} {summary.total_cost:,.2f}"
                    f" · {summary.lot_count} 个批次"
                    + (f" · 平均成本 {avg:,.4f}" if avg is not None else "")
                )
                value_in_cost = self._convert_value(
                    item.latest_value, item.currency, summary.currency
                )
                if value_in_cost is not None:
                    pnl = value_in_cost - summary.total_cost
                    pnl_text = fmt_money(pnl, summary.currency, show_sign=True)
                    if summary.total_cost > 0:
                        rate_text = fmt_percent(
                            pnl / summary.total_cost * Decimal("100"), show_sign=True
                        )
            values = [
                item.name,
                item.category_label,
                fmt_money(
                    item.price,
                    symbol_for(item.price_currency or item.currency, self.symbol),
                ),
                fmt_money(item.latest_value, symbol),
                cny_text,
                pnl_text,
                rate_text,
                item.latest_date.strftime("%Y-%m-%d") if item.latest_date else "—",
            ]
            for column, text in enumerate(values):
                cell = table_item(
                    text,
                    align_right=column in (2, 3, 4, 5, 6, 7),
                    user_data=item.id if column == 0 else None,
                )
                if column == 2 and item.symbol:
                    if item.price is None:
                        cell.setToolTip(f"{item.symbol} · 暂无行情，点击「刷新行情」")
                    else:
                        tail = (
                            item.price_at.strftime("%m-%d %H:%M")
                            if item.price_at
                            else "—"
                        )
                        cell.setToolTip(
                            f"{item.symbol}（{item.market}）{item.price_currency}"
                            f" · 报价时间 {tail}"
                        )
                elif column == 5 and tooltip:
                    cell.setToolTip(tooltip)
                if account.archived:
                    cell.setForeground(colors["muted"])
                self.items_table.setItem(row_index, column, cell)

        codes = account.item_currencies
        if len(codes) > 1:
            total_cny = sum(
                (
                    exchange_rates.to_cny(
                        entry.latest_value, entry.currency, self._today, self._lookup
                    )
                    or Decimal("0.00")
                )
                for entry in account.items
                if entry.latest_value is not None
            )
            total_text = f"{fmt_money(total_cny, self.symbol)}（折算人民币）"
        else:
            code = codes[0] if codes else "CNY"
            total_text = fmt_money(account.latest_value, symbol_for(code, self.symbol))
            if (
                code != "CNY"
                and code in self._rate_dates
                and account.latest_value is not None
            ):
                total_cny = exchange_rates.to_cny(
                    account.latest_value, code, self._today, self._lookup
                )
                total_text += f"（折合 {fmt_money(total_cny, self.symbol)}）"
        self.item_hint.setText(f"{len(account.items)} 个类别子项 · 合计 {total_text}")
        self._update_buttons()

    def _convert_value(
        self, value: Optional[Decimal], from_currency: str, to_currency: str
    ) -> Optional[Decimal]:
        """按当日汇率折算；任一币种缺少汇率时返回 None。"""
        if value is None:
            return None
        for code in (from_currency, to_currency):
            if code != "CNY" and code not in self._rate_dates:
                return None
        if from_currency == to_currency:
            return value
        rate_to = self._lookup(to_currency, self._today)
        if rate_to == 0:
            return None
        return (
            value * self._lookup(from_currency, self._today) / rate_to
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _on_item_double_clicked(self, index) -> None:
        if index.column() == 3:
            self._entry_value()
        else:
            self._edit_item()

    def _entry_value(self) -> None:
        overview = self._selected_account()
        current = self._selected_item()
        if overview is None or current is None:
            return
        dialog = SnapshotEntryDialog(
            overview.name,
            current.name,
            SIDE_LABELS.get(overview.side, overview.side),
            current.category_label,
            symbol_for(current.currency, self.symbol),
            parent=self,
        )
        if not dialog.exec():
            return
        try:
            day, value, note = dialog.values()
        except AppValidationError as exc:
            show_warning(self, "无法保存", str(exc))
            return
        self._save_snapshot(current.id, day, value, note)

    def _save_snapshot(
        self,
        item_id: int,
        day: date,
        value: Decimal,
        note: str,
        overwrite: bool = False,
    ) -> None:
        try:
            with db.session_scope() as session:
                snapshot_service.save_snapshot(
                    session,
                    item_id=item_id,
                    snapshot_date=day,
                    value=value,
                    note=note,
                    overwrite=overwrite,
                )
        except SnapshotExistsError as exc:
            if confirm(self, "覆盖已有估值", str(exc)):
                self._save_snapshot(item_id, day, value, note, overwrite=True)
            return
        except AppValidationError as exc:
            show_warning(self, "无法保存", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "保存失败", exc)
            return
        self._after_change()

    def _batch_entry(self) -> None:
        overview = self._selected_account()
        if overview is None:
            return
        dialog = AccountBatchDialog(
            overview.id, overview.name, overview.currency, self
        )
        if dialog.exec():
            self._after_change()

    def _update_buttons(self) -> None:
        account = self._selected_account()
        has_account = account is not None
        self.edit_button.setEnabled(has_account)
        self.archive_button.setEnabled(has_account)
        self.delete_button.setEnabled(has_account)
        self.add_item_button.setEnabled(has_account and not account.archived)
        has_item = self._selected_item() is not None
        self.edit_item_button.setEnabled(has_item and not account.archived)
        self.delete_item_button.setEnabled(has_item and not account.archived)
        self.cost_button.setEnabled(
            has_item and not account.archived and account.side == "asset"
        )
        self.entry_button.setEnabled(has_item and not account.archived)
        self.batch_entry_button.setEnabled(has_account and not account.archived)
        if has_account:
            self.archive_button.setText("恢复" if account.archived else "归档")
        else:
            self.archive_button.setText("归档")

    # ---- 账户操作 ----
    @staticmethod
    def _to_item_inputs(payload: Dict[str, object]) -> List[ItemInput]:
        result: List[ItemInput] = []
        for spec in payload.get("items") or []:
            result.append(
                ItemInput(
                    id=spec.get("id"),
                    name=str(spec.get("name") or ""),
                    category=str(spec.get("category") or ""),
                    currency=str(spec.get("currency") or "") or None,
                    symbol=str(spec.get("symbol") or "") or None,
                )
            )
        return result

    def _after_change(self) -> None:
        self.refresh()
        self.data_changed.emit()

    def _new_account(self) -> None:
        def save(payload: Dict[str, object]) -> None:
            with db.session_scope() as session:
                account_service.create_account(
                    session,
                    name=str(payload["name"]),
                    side=str(payload["side"]),
                    items=self._to_item_inputs(payload),
                    currency=str(payload["currency"]),
                    note=str(payload["note"]),
                )

        dialog = AccountDialog(save, parent=self)
        if dialog.exec():
            self._after_change()

    def _edit_account(self) -> None:
        overview = self._selected_account()
        if overview is None:
            return

        def save(payload: Dict[str, object]) -> None:
            with db.session_scope() as session:
                account_service.update_account(
                    session,
                    overview.id,
                    name=str(payload["name"]),
                    side=str(payload["side"]),
                    items=self._to_item_inputs(payload),
                    currency=str(payload["currency"]),
                    note=str(payload["note"]),
                )

        dialog = AccountDialog(save, account=overview, parent=self)
        if dialog.exec():
            self._after_change()

    def _toggle_archive(self) -> None:
        overview = self._selected_account()
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
            show_exception(self, "操作失败", exc)
            return
        self._after_change()

    def _delete_account(self) -> None:
        overview = self._selected_account()
        if overview is None:
            return
        try:
            with db.session_scope() as session:
                count = account_service.snapshot_count(session, overview.id)
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "读取失败", exc)
            return
        if not confirm(
            self,
            "删除账户",
            f"确定删除账户 “{overview.name}” 吗？\n"
            f"其 {count} 条估值记录也会被一并删除，且无法恢复。",
        ):
            return
        try:
            with db.session_scope() as session:
                account_service.delete_account(session, overview.id)
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "删除失败", exc)
            return
        self._after_change()

    # ---- 子项操作 ----
    def _save_items(self, overview: AccountOverview, items: List[ItemInput]) -> None:
        try:
            with db.session_scope() as session:
                account_service.update_account(
                    session,
                    overview.id,
                    name=overview.name,
                    side=overview.side,
                    items=items,
                    currency=overview.currency,
                    note=overview.note,
                )
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "保存失败", exc)
            return
        self._after_change()

    @staticmethod
    def _base_items(overview: AccountOverview) -> List[ItemInput]:
        return [
            ItemInput(
                id=item.id,
                name=item.name,
                category=item.category,
                currency=item.currency,
                symbol=item.symbol or None,
            )
            for item in overview.items
        ]

    def _add_item(self) -> None:
        overview = self._selected_account()
        if overview is None:
            return
        dialog = ItemDialog(
            overview.side,
            title="新增类别子项",
            parent=self,
            currency=overview.currency,
        )
        if not dialog.exec():
            return
        name, category, symbol = dialog.values()
        items = self._base_items(overview)
        items.append(
            ItemInput(
                name=name,
                category=category,
                currency=dialog.currency_value(),
                symbol=symbol or None,
            )
        )
        self._save_items(overview, items)

    def _edit_item(self) -> None:
        overview = self._selected_account()
        current = self._selected_item()
        if overview is None or current is None:
            return
        allow_lots = overview.side == "asset"
        lots: List[profit.LotInput] = []
        cost_currency = current.currency
        if allow_lots:
            try:
                with db.session_scope() as session:
                    stored = profit.list_lots(session, current.id)
                    lots = [
                        profit.LotInput(
                            trade_date=lot.trade_date,
                            quantity=lot.quantity,
                            unit_cost=lot.unit_cost,
                            fee=lot.fee,
                            currency=lot.currency,
                            note=lot.note or "",
                        )
                        for lot in stored
                    ]
                    if stored:
                        cost_currency = stored[0].currency
            except Exception as exc:  # noqa: BLE001
                show_exception(self, "读取成本失败", exc)
                return
        dialog = ItemDialog(
            overview.side,
            name=current.name,
            category=current.category,
            title="编辑类别子项",
            parent=self,
            allow_lots=allow_lots,
            lots=lots,
            cost_currency=cost_currency,
            currency=current.currency,
            symbol=current.symbol,
        )
        if not dialog.exec():
            return
        name, category, symbol = dialog.values()
        items = [
            ItemInput(
                id=item.id,
                name=name if item.id == current.id else item.name,
                category=category if item.id == current.id else item.category,
                currency=(
                    dialog.currency_value()
                    if item.id == current.id
                    else item.currency
                ),
                symbol=(
                    symbol or None
                    if item.id == current.id
                    else (item.symbol or None)
                ),
            )
            for item in overview.items
        ]
        try:
            with db.session_scope() as session:
                account_service.update_account(
                    session,
                    overview.id,
                    name=overview.name,
                    side=overview.side,
                    items=items,
                    currency=overview.currency,
                    note=overview.note,
                )
                if allow_lots:
                    profit.save_lots(session, current.id, dialog.lot_values())
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "保存失败", exc)
            return
        self._after_change()

    def _edit_costs(self) -> None:
        overview = self._selected_account()
        current = self._selected_item()
        if overview is None or current is None:
            return
        try:
            with db.session_scope() as session:
                stored = profit.list_lots(session, current.id)
                cost_currency = stored[0].currency if stored else current.currency
                lots = [
                    profit.LotInput(
                        trade_date=lot.trade_date,
                        quantity=lot.quantity,
                        unit_cost=lot.unit_cost,
                        fee=lot.fee,
                        currency=lot.currency,
                        note=lot.note or "",
                    )
                    for lot in stored
                ]
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "读取成本失败", exc)
            return
        dialog = ItemDialog(
            overview.side,
            title=f"成本批次 · {current.name}",
            parent=self,
            allow_lots=True,
            lots_only=True,
            lots=lots,
            cost_currency=cost_currency,
        )
        if not dialog.exec():
            return
        try:
            with db.session_scope() as session:
                profit.save_lots(session, current.id, dialog.lot_values())
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "保存失败", exc)
            return
        self._after_change()

    def _delete_item(self) -> None:
        overview = self._selected_account()
        current = self._selected_item()
        if overview is None or current is None:
            return
        if len(overview.items) <= 1:
            show_warning(self, "无法删除", "每个账户至少需要保留一个类别子项。")
            return
        if not confirm(
            self,
            "删除子项",
            f"确定删除子项 “{current.name}”（{current.category_label}）吗？\n"
            "该子项的全部估值记录也会被一并删除，且无法恢复。",
        ):
            return
        items = [item for item in self._base_items(overview) if item.id != current.id]
        self._save_items(overview, items)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self.refresh()
