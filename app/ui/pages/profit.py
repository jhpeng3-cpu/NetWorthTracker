"""盈亏分析页面：按子项展示成本、市值、盈亏额与盈亏率，并支持区间统计。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional, Tuple

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from app.config import AppConfig
from app.db.engine import db
from app.db.models import CATEGORY_LABELS
from app.services import profit
from app.services.profit import AccountProfitRow, PeriodProfitRow, ProfitRow
from app.ui.common import (
    align_headers,
    make_table,
    set_columns,
    show_exception,
    show_warning,
    table_item,
)
from app.ui.dialogs.item_dialog import ItemDialog
from app.ui.pages.base import BasePage
from app.utils.dates import add_months, month_end
from app.utils.money import fmt_money, fmt_percent, symbol_for

HEADERS = [
    "账户",
    "子项",
    "方向",
    "类别",
    "数量",
    "平均成本",
    "市值(原币)",
    "成本(原币)",
    "盈亏额",
    "盈亏率",
    "折合人民币",
]

PERIOD_HEADERS = [
    "账户",
    "子项",
    "方向",
    "类别",
    "期初市值",
    "期末市值",
    "期初成本",
    "期末成本",
    "期间盈亏",
    "期间收益率",
    "折合人民币",
]

PERIOD_WIDTHS = [120, 100, 50, 76, 110, 110, 110, 110, 110, 90, 120]

ACCOUNT_HEADERS = [
    "账户",
    "方向",
    "估值(CNY)",
    "成本(CNY)",
    "盈亏/利息",
    "收益率",
    "说明",
]

ACCOUNT_WIDTHS = [160, 50, 130, 130, 130, 80, 190]


def _fmt_quantity(value: Decimal) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


class ProfitPage(BasePage):
    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(config, parent)
        self._rows: List[ProfitRow] = []
        self._period_rows: List[PeriodProfitRow] = []
        self._account_rows: List[AccountProfitRow] = []
        self._sort_column = 10
        self._sort_desc = True
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        header = self.add_header(
            "盈亏分析",
            "按买入币种计算盈亏；仅统计已录成本批次的资产子项。可切换累计或区间统计。",
        )
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.refresh)
        header.addWidget(refresh_button)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        dimension_label = QLabel("维度")
        dimension_label.setObjectName("Hint")
        self.dimension_combo = QComboBox()
        self.dimension_combo.addItem("按子项", "item")
        self.dimension_combo.addItem("按账户", "account")
        self.dimension_combo.currentIndexChanged.connect(self._on_dimension_changed)
        side_label = QLabel("方向")
        side_label.setObjectName("Hint")
        self.side_combo = QComboBox()
        self.side_combo.addItem("全部", "")
        self.side_combo.addItem("资产", "asset")
        self.side_combo.addItem("负债", "liability")
        self.side_combo.currentIndexChanged.connect(self.refresh)
        category_label = QLabel("类别")
        category_label.setObjectName("Hint")
        self.category_combo = QComboBox()
        self.category_combo.addItem("全部", "")
        for key, label in CATEGORY_LABELS.items():
            self.category_combo.addItem(label, key)
        self.category_combo.currentIndexChanged.connect(self.refresh)
        period_label = QLabel("区间")
        period_label.setObjectName("Hint")
        self.period_combo = QComboBox()
        self.period_combo.addItem("当前累计", "cumulative")
        self.period_combo.addItem("近一个月", "last_month")
        self.period_combo.addItem("近一年", "last_year")
        self.period_combo.addItem("按年度", "year")
        self.period_combo.addItem("按月份", "month")
        self.period_combo.currentIndexChanged.connect(self._on_period_changed)
        self.detail_combo = QComboBox()
        self.detail_combo.setMinimumWidth(104)
        self.detail_combo.setVisible(False)
        self.detail_combo.currentIndexChanged.connect(self.refresh)
        self.show_archived = QCheckBox("显示已归档账户")
        self.show_archived.toggled.connect(self.refresh)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("Hint")
        filters.addWidget(dimension_label)
        filters.addWidget(self.dimension_combo)
        filters.addWidget(side_label)
        filters.addWidget(self.side_combo)
        filters.addWidget(category_label)
        filters.addWidget(self.category_combo)
        filters.addWidget(period_label)
        filters.addWidget(self.period_combo)
        filters.addWidget(self.detail_combo)
        filters.addWidget(self.show_archived)
        filters.addStretch(1)
        filters.addWidget(self.summary_label)
        self.root.addLayout(filters)

        self.table = make_table(HEADERS)
        set_columns(self.table, [130, 110, 50, 80, 90, 110, 120, 110, 110, 76, 130])
        align_headers(self.table, (4, 5, 6, 7, 8, 9, 10))
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.doubleClicked.connect(lambda _index: self._edit_costs())
        self.root.addWidget(self.table, 1)

        self.empty_label = QLabel("")
        self.empty_label.setObjectName("Hint")
        self.empty_label.hide()
        self.root.addWidget(self.empty_label)

    # ---- 数据 ----

    def _dimension(self) -> str:
        return self.dimension_combo.currentData() or "item"

    def _on_dimension_changed(self, _index: int) -> None:
        is_account = self._dimension() == "account"
        self.category_combo.setEnabled(not is_account)
        if is_account and self.category_combo.currentIndex() != 0:
            self.category_combo.blockSignals(True)
            self.category_combo.setCurrentIndex(0)
            self.category_combo.blockSignals(False)
        self._sort_column = 4 if is_account else 10
        self._sort_desc = True
        self.refresh()

    def _on_period_changed(self, _index: int) -> None:
        mode = self.period_combo.currentData()
        today = date.today()
        self.detail_combo.blockSignals(True)
        self.detail_combo.clear()
        if mode == "year":
            for year in range(today.year, today.year - 10, -1):
                self.detail_combo.addItem(f"{year} 年", year)
        elif mode == "month":
            cursor = date(today.year, today.month, 1)
            for _ in range(24):
                self.detail_combo.addItem(
                    f"{cursor.year}-{cursor.month:02d}",
                    f"{cursor.year}-{cursor.month:02d}",
                )
                cursor = add_months(cursor, -1)
        self.detail_combo.setVisible(mode in ("year", "month"))
        self.detail_combo.blockSignals(False)
        self.refresh()

    def _period_range(self) -> Optional[Tuple[date, date]]:
        mode = self.period_combo.currentData()
        today = date.today()
        if mode == "last_month":
            return add_months(today, -1), today
        if mode == "last_year":
            return add_months(today, -12), today
        if mode == "year":
            year = int(self.detail_combo.currentData() or today.year)
            return date(year, 1, 1), min(date(year, 12, 31), today)
        if mode == "month":
            text = str(
                self.detail_combo.currentData() or f"{today.year}-{today.month:02d}"
            )
            year, month = (int(part) for part in text.split("-"))
            start = date(year, month, 1)
            return start, min(month_end(start), today)
        return None

    def _apply_columns(self, period: bool) -> None:
        if self._dimension() == "account":
            self.table.setColumnCount(len(ACCOUNT_HEADERS))
            self.table.setHorizontalHeaderLabels(ACCOUNT_HEADERS)
            set_columns(self.table, ACCOUNT_WIDTHS)
            align_headers(self.table, (2, 3, 4, 5))
            return
        self.table.setColumnCount(len(HEADERS))
        if period:
            self.table.setHorizontalHeaderLabels(PERIOD_HEADERS)
            set_columns(self.table, PERIOD_WIDTHS)
            align_headers(self.table, (4, 5, 6, 7, 8, 9, 10))
        else:
            self.table.setHorizontalHeaderLabels(HEADERS)
            set_columns(self.table, [130, 110, 50, 80, 90, 110, 120, 110, 110, 76, 130])
            align_headers(self.table, (4, 5, 6, 7, 8, 9, 10))

    def refresh(self) -> None:
        if not db.is_configured:
            return
        period = self._period_range()
        dimension = self._dimension()
        account_summary = None
        try:
            with db.session_scope() as session:
                if dimension == "account":
                    rows: List[ProfitRow] = []
                    period_rows: List[PeriodProfitRow] = []
                    account_rows = profit.account_profit_rows(
                        session,
                        None if period is None else period[0],
                        None if period is None else period[1],
                        include_archived=self.show_archived.isChecked(),
                    )
                    account_summary = profit.account_profit_summary(account_rows)
                elif period is None:
                    rows = profit.profit_rows(
                        session, include_archived=self.show_archived.isChecked()
                    )
                    period_rows = []
                    account_rows = []
                    summary = profit.portfolio_summary(rows)
                else:
                    start, end = period
                    rows = []
                    period_rows = profit.period_profit_rows(
                        session,
                        start,
                        end,
                        include_archived=self.show_archived.isChecked(),
                    )
                    account_rows = []
                    summary = profit.period_summary(period_rows, start, end)
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "加载失败", exc)
            return
        side = self.side_combo.currentData() or ""
        category = self.category_combo.currentData() or ""
        self._rows = [
            row
            for row in rows
            if (not side or row.side == side) and (not category or row.category == category)
        ]
        self._period_rows = [
            row
            for row in period_rows
            if (not side or row.side == side) and (not category or row.category == category)
        ]
        self._account_rows = [
            row for row in account_rows if not side or row.side == side
        ]
        self._apply_columns(period is not None)
        self._render()
        if dimension == "account" and account_summary is not None:
            self._set_account_summary(account_summary)
        elif period is None:
            self._set_cumulative_summary(summary)
        else:
            self._set_period_summary(summary)

    def _set_account_summary(self, summary: profit.AccountProfitSummary) -> None:
        if not summary.account_count:
            self.summary_label.setText("暂无账户盈亏")
            return
        text = (
            f"{self._period_label()} · 投资收益 {fmt_money(summary.investment_cny, self.symbol, show_sign=True)}"
            f" · 利息支出 {fmt_money(summary.interest_cny, self.symbol)}"
            f" · 净收益 {fmt_money(summary.net_cny, self.symbol, show_sign=True)}"
        )
        if summary.missing:
            text += f" · {summary.missing} 项缺估值或汇率"
        self.summary_label.setText(text)

    def _set_cumulative_summary(self, summary: profit.PortfolioSummary) -> None:
        if not summary.item_count:
            self.summary_label.setText("暂无成本记录")
            return
        self.summary_label.setText(
            f"共 {summary.item_count} 项 · 市值 {fmt_money(summary.value_cny, self.symbol)}"
            f" · 成本 {fmt_money(summary.cost_cny, self.symbol)}"
            f" · 盈亏 {fmt_money(summary.pnl_cny, self.symbol, show_sign=True)}"
            + (f"（{fmt_percent(summary.pnl_rate)}）" if summary.pnl_rate is not None else "")
        )

    def _period_label(self) -> str:
        mode = self.period_combo.currentData()
        if mode == "year":
            return f"{self.detail_combo.currentData()} 年"
        if mode == "month":
            return str(self.detail_combo.currentData())
        return self.period_combo.currentText()

    def _set_period_summary(self, summary: profit.PeriodSummary) -> None:
        if not summary.item_count:
            self.summary_label.setText(
                f"{self._period_label()}：区间内没有可统计的持仓盈亏"
            )
            return
        rate_text = (
            f"（{fmt_percent(summary.pnl_rate)}）"
            if summary.pnl_rate is not None
            else "（期初无持仓）"
        )
        text = (
            f"{self._period_label()}"
            f" · {summary.start:%Y-%m-%d} ~ {summary.end:%Y-%m-%d}"
            f" · 共 {summary.item_count} 项"
            f" · 期末市值 {fmt_money(summary.end_value_cny, self.symbol)}"
            f" · 期间盈亏 {fmt_money(summary.pnl_cny, self.symbol, show_sign=True)}{rate_text}"
        )
        if summary.missing_rate:
            text += f" · {summary.missing_rate} 项缺少汇率"
        self.summary_label.setText(text)

    def _sorted_rows(self) -> List[ProfitRow]:
        keys = {
            0: lambda row: row.account_name,
            1: lambda row: row.item_name,
            2: lambda row: row.side,
            3: lambda row: row.category_label,
            4: lambda row: row.quantity,
            5: lambda row: row.avg_unit_cost or Decimal("0"),
            6: lambda row: row.value or Decimal("0"),
            7: lambda row: row.cost_total,
            8: lambda row: row.pnl if row.pnl is not None else Decimal("-1e18"),
            9: lambda row: row.pnl_rate if row.pnl_rate is not None else Decimal("-1e18"),
            10: lambda row: row.pnl_cny if row.pnl_cny is not None else Decimal("-1e18"),
        }
        key = keys.get(self._sort_column, keys[10])
        return sorted(self._rows, key=key, reverse=self._sort_desc)

    def _sorted_period_rows(self) -> List[PeriodProfitRow]:
        keys = {
            0: lambda row: row.account_name,
            1: lambda row: row.item_name,
            2: lambda row: row.side,
            3: lambda row: row.category_label,
            4: lambda row: row.start_value or Decimal("0"),
            5: lambda row: row.end_value or Decimal("0"),
            6: lambda row: row.start_cost,
            7: lambda row: row.end_cost,
            8: lambda row: row.pnl if row.pnl is not None else Decimal("-1e18"),
            9: lambda row: row.pnl_rate if row.pnl_rate is not None else Decimal("-1e18"),
            10: lambda row: row.pnl_cny if row.pnl_cny is not None else Decimal("-1e18"),
        }
        key = keys.get(self._sort_column, keys[10])
        return sorted(self._period_rows, key=key, reverse=self._sort_desc)

    def _render(self) -> None:
        if self._dimension() == "account":
            self._render_accounts()
            return
        if self._period_rows or self._period_range() is not None:
            self._render_period()
            return
        rows = self._sorted_rows()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            symbol = symbol_for(row.cost_currency, self.symbol)
            values = [
                row.account_name,
                row.item_name,
                row.side_label,
                row.category_label,
                _fmt_quantity(row.quantity),
                fmt_money(row.avg_unit_cost, symbol),
                fmt_money(row.value, symbol_for(row.account_currency, self.symbol)),
                fmt_money(row.cost_total, symbol),
                fmt_money(row.pnl, symbol, show_sign=True),
                fmt_percent(row.pnl_rate),
                fmt_money(row.pnl_cny, self.symbol, show_sign=True),
            ]
            for column, text in enumerate(values):
                item = table_item(
                    text,
                    align_right=column in (4, 5, 6, 7, 8, 9, 10),
                    user_data=row.item_id if column == 0 else None,
                )
                if column == 5:
                    item.setToolTip(
                        f"成本合计 {symbol}{row.cost_total:,.2f}"
                    )
                self.table.setItem(row_index, column, item)

        empty = len(rows) == 0
        self.empty_label.setVisible(empty)
        if empty:
            self.empty_label.setText(
                "还没有任何成本记录。可在「账户管理」中选中资产子项，点击「成本批次…」录入买入记录。"
            )

    def _render_period(self) -> None:
        rows = self._sorted_period_rows()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            cost_symbol = symbol_for(row.cost_currency, self.symbol)
            value_symbol = symbol_for(row.currency, self.symbol)
            values = [
                row.account_name,
                row.item_name,
                row.side_label,
                row.category_label,
                fmt_money(row.start_value, value_symbol),
                fmt_money(row.end_value, value_symbol),
                fmt_money(row.start_cost, cost_symbol),
                fmt_money(row.end_cost, cost_symbol),
                fmt_money(row.pnl, cost_symbol, show_sign=True),
                fmt_percent(row.pnl_rate),
                fmt_money(row.pnl_cny, self.symbol, show_sign=True),
            ]
            for column, text in enumerate(values):
                item = table_item(
                    text,
                    align_right=column in (4, 5, 6, 7, 8, 9, 10),
                    user_data=row.item_id if column == 0 else None,
                )
                if column == 4:
                    item.setToolTip(
                        f"期初市值 {value_symbol}{row.start_value:,.2f}"
                        if row.start_value is not None
                        else "区间起点前没有估值快照，期初按 0 计算"
                    )
                elif column == 5:
                    item.setToolTip(
                        f"估值日期：{row.end_value_date:%Y-%m-%d}"
                        if row.end_value_date
                        else "截至区间末没有估值快照"
                    )
                elif column == 8:
                    item.setToolTip(
                        f"期初成本 {cost_symbol}{row.start_cost:,.2f}"
                        f" · 期末成本 {cost_symbol}{row.end_cost:,.2f}"
                    )
                self.table.setItem(row_index, column, item)

        empty = len(rows) == 0
        self.empty_label.setVisible(empty)
        if empty:
            self.empty_label.setText(
                "所选区间内没有可统计的持仓盈亏。区间需包含已录成本批次的资产子项及估值快照。"
            )

    def _on_header_clicked(self, column: int) -> None:
        if column == self._sort_column:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_column = column
            self._sort_desc = column >= 2
        self._render()

    def _sorted_account_rows(self) -> List[AccountProfitRow]:
        keys = {
            0: lambda row: row.account_name,
            1: lambda row: row.side,
            2: lambda row: row.value_cny or Decimal("-1e18"),
            3: lambda row: row.cost_cny or Decimal("-1e18"),
            4: lambda row: (
                row.pnl_cny
                if row.pnl_cny is not None
                else Decimal("-1e18")
            ),
            5: lambda row: row.pnl_rate or Decimal("-1e18"),
            6: lambda row: row.note,
        }
        key = keys.get(self._sort_column, keys[4])
        return sorted(self._account_rows, key=key, reverse=self._sort_desc)

    def _render_accounts(self) -> None:
        rows = self._sorted_account_rows()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            is_liability = row.side == "liability"
            if is_liability:
                pnl_text = fmt_money(
                    -(row.interest_cny or Decimal("0.00")),
                    self.symbol,
                    show_sign=True,
                )
            else:
                pnl_text = fmt_money(row.pnl_cny, self.symbol, show_sign=True)
            values = [
                row.account_name,
                row.side_label,
                fmt_money(row.value_cny, self.symbol),
                fmt_money(row.cost_cny, self.symbol),
                pnl_text,
                fmt_percent(row.pnl_rate),
                row.note,
            ]
            for column, text in enumerate(values):
                item = table_item(
                    text,
                    align_right=column in (2, 3, 4, 5),
                    user_data=row.account_id if column == 0 else None,
                )
                if column == 4:
                    if is_liability:
                        item.setToolTip(f"利息支出 {fmt_money(row.interest_cny, self.symbol)}")
                    elif row.note:
                        item.setToolTip(row.note)
                self.table.setItem(row_index, column, item)

        empty = len(rows) == 0
        self.empty_label.setVisible(empty)
        if empty:
            self.empty_label.setText(
                "暂无账户盈亏。资产账户需录入成本批次；负债账户需在子项中配置年利率。"
            )

    # ---- 成本编辑 ----

    def _selected_row(self) -> Optional[ProfitRow]:
        indexes = self.table.selectedItems()
        if not indexes:
            return None
        row = indexes[0].row()
        rows = self._sorted_rows()
        if 0 <= row < len(rows):
            return rows[row]
        return None

    def _selected_period_row(self) -> Optional[PeriodProfitRow]:
        indexes = self.table.selectedItems()
        if not indexes:
            return None
        row = indexes[0].row()
        rows = self._sorted_period_rows()
        if 0 <= row < len(rows):
            return rows[row]
        return None

    def _edit_costs(self) -> None:
        if self._dimension() == "account":
            return
        row = self._selected_row()
        if row is not None:
            self._open_cost_dialog(
                row.item_id,
                row.side,
                f"{row.account_name} / {row.item_name}",
                row.account_currency,
            )
            return
        period_row = self._selected_period_row()
        if period_row is None:
            return
        self._open_cost_dialog(
            period_row.item_id,
            period_row.side,
            f"{period_row.account_name} / {period_row.item_name}",
            period_row.currency,
        )

    def _open_cost_dialog(
        self,
        item_id: int,
        side: str,
        title_name: str,
        fallback_currency: str,
    ) -> None:
        if side != "asset":
            show_warning(self, "无法录入成本", "只有资产子项可以录入成本批次。")
            return
        try:
            with db.session_scope() as session:
                stored = profit.list_lots(session, item_id)
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
                cost_currency = (
                    stored[0].currency if stored else fallback_currency
                )
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "读取成本失败", exc)
            return
        dialog = ItemDialog(
            side,
            title=f"成本批次 · {title_name}",
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
                profit.save_lots(session, item_id, dialog.lot_values())
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "保存失败", exc)
            return
        self.refresh()
        self.data_changed.emit()
