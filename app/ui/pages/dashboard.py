"""仪表盘：总览卡片、资产/负债分布、净资产历史曲线。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.db.engine import db
from app.services import analytics
from app.services import profit as profit_service
from app.services.analytics import CurrentSummary, NetWorthPoint, PieSlice
from app.services.profit import PortfolioSummary
from app.ui.common import StatCard, show_error
from app.ui.pages.base import BasePage
from app.ui.widgets.charts import DonutChart, LineChart
from app.utils.async_task import run_async
from app.utils.dates import (
    GRANULARITY_OPTIONS,
    RANGE_OPTIONS,
    resolve_range_start,
)
from app.utils.money import fmt_money, fmt_percent, fmt_signed_money


@dataclass
class DashboardBundle:
    summary: CurrentSummary
    assets: List[PieSlice]
    liabilities: List[PieSlice]
    points: List[NetWorthPoint]
    start: date
    end: date
    profit: PortfolioSummary


def _pack_chart_panel(
    title: str,
    group_combo: QComboBox,
    chart: QWidget,
    subtitle: str = "",
) -> QFrame:
    panel = QFrame()
    panel.setObjectName("Panel")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(14, 12, 14, 8)
    layout.setSpacing(4)
    header = QHBoxLayout()
    title_label = QLabel(title)
    title_label.setObjectName("SectionTitle")
    header.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("Hint")
        header.addSpacing(6)
        header.addWidget(subtitle_label)
    header.addStretch(1)
    group_combo.setFixedWidth(110)
    header.addWidget(group_combo)
    layout.addLayout(header)
    layout.addWidget(chart, 1)
    return panel


class DashboardPage(BasePage):
    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(config, parent)
        self._request_id = 0
        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        header = self.add_header(
            "仪表盘",
            "按各账户最新估值实时计算，归档账户不计入。",
        )
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.refresh)
        header.addWidget(refresh_button)

        self.empty_label = QLabel("")
        self.empty_label.setObjectName("Muted")
        self.empty_label.setWordWrap(True)
        self.empty_label.hide()
        self.root.addWidget(self.empty_label)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.asset_card = StatCard("总资产", "尚无数据")
        self.liability_card = StatCard("总负债", "尚无数据")
        self.net_card = StatCard("净资产", "资产 − 负债")
        self.change_card = StatCard("较上次快照", "暂无上一期快照")
        self.profit_card = StatCard("持仓盈亏", "尚无成本记录")
        for card in (
            self.net_card,
            self.asset_card,
            self.liability_card,
            self.change_card,
            self.profit_card,
        ):
            cards.addWidget(card, 1)
        self.root.addLayout(cards)

        self.asset_group = QComboBox()
        self.asset_group.addItem("按类别", "category")
        self.asset_group.addItem("按账户", "account")
        self.asset_group.currentIndexChanged.connect(self._reload)
        self.liability_group = QComboBox()
        self.liability_group.addItem("按类别", "category")
        self.liability_group.addItem("按账户", "account")
        self.liability_group.currentIndexChanged.connect(self._reload)

        self.asset_chart = DonutChart(self._theme)
        self.liability_chart = DonutChart(self._theme)

        distribution = QHBoxLayout()
        distribution.setSpacing(12)
        distribution.addWidget(
            _pack_chart_panel("资产分布", self.asset_group, self.asset_chart), 1
        )
        distribution.addWidget(
            _pack_chart_panel("负债分布", self.liability_group, self.liability_chart), 1
        )
        self.root.addLayout(distribution, 1)

        self.range_combo = QComboBox()
        for key, label in RANGE_OPTIONS:
            self.range_combo.addItem(label, key)
        self.range_combo.setCurrentIndex(self.range_combo.findData("1y"))
        self.range_combo.currentIndexChanged.connect(self._reload)
        self.granularity_combo = QComboBox()
        for key, label in GRANULARITY_OPTIONS:
            self.granularity_combo.addItem(label, key)
        self.granularity_combo.setCurrentIndex(self.granularity_combo.findData("month"))
        self.granularity_combo.currentIndexChanged.connect(self._reload)

        history_panel = QFrame()
        history_panel.setObjectName("Panel")
        history_layout = QVBoxLayout(history_panel)
        history_layout.setContentsMargins(14, 12, 14, 8)
        history_layout.setSpacing(4)
        history_header = QHBoxLayout()
        history_title = QLabel("净资产历史")
        history_title.setObjectName("SectionTitle")
        history_header.addWidget(history_title)
        range_label = QLabel("范围")
        range_label.setObjectName("Hint")
        history_header.addSpacing(8)
        history_header.addWidget(range_label)
        history_header.addWidget(self.range_combo)
        granularity_label = QLabel("粒度")
        granularity_label.setObjectName("Hint")
        history_header.addWidget(granularity_label)
        history_header.addWidget(self.granularity_combo)
        history_header.addStretch(1)
        history_layout.addLayout(history_header)
        self.line_chart = LineChart(self._theme)
        history_layout.addWidget(self.line_chart, 1)
        self.root.addWidget(history_panel, 1)

    def _apply_styles(self) -> None:
        colors = self.colors
        self.empty_label.setStyleSheet(
            f"background: {colors['surface_alt']}; border: 1px solid {colors['border']};"
            f" border-radius: 8px; padding: 8px 12px; color: {colors['muted']};"
        )

    def refresh(self) -> None:
        self._reload()

    def apply_theme(self, theme: str) -> None:
        super().apply_theme(theme)
        self._apply_styles()
        self.asset_chart.apply_theme(theme)
        self.liability_chart.apply_theme(theme)
        self.line_chart.apply_theme(theme)

    def _reload(self, *_args) -> None:
        if not db.is_configured:
            return
        range_key = self.range_combo.currentData() or "1y"
        granularity = self.granularity_combo.currentData() or "month"
        asset_group = self.asset_group.currentData() or "category"
        liability_group = self.liability_group.currentData() or "category"
        self._request_id += 1
        request_id = self._request_id
        self.empty_label.setText("正在加载…")
        self.empty_label.show()

        def task() -> DashboardBundle:
            today = date.today()
            with db.session_scope() as session:
                summary = analytics.current_summary(session, today)
                assets = analytics.distribution(session, "asset", asset_group, today)
                liabilities = analytics.distribution(
                    session, "liability", liability_group, today
                )
                first = analytics.first_snapshot_date(session)
                start = resolve_range_start(range_key, today, first)
                if first is not None and start < first:
                    start = first
                points = analytics.history_points(session, start, today, granularity)
                profit_rows = profit_service.profit_rows(session, today=today)
                return DashboardBundle(
                    summary=summary,
                    assets=assets,
                    liabilities=liabilities,
                    points=points,
                    start=start,
                    end=today,
                    profit=profit_service.portfolio_summary(profit_rows),
                )

        run_async(
            task,
            lambda bundle: self._apply_bundle(bundle, request_id),
            lambda message: self._on_error(message, request_id),
        )

    def _on_error(self, message: str, request_id: int) -> None:
        if request_id != self._request_id:
            return
        self.empty_label.setText("加载失败，请检查数据库连接后重试。")
        self.empty_label.show()
        show_error(self, "加载失败", message)

    def _apply_bundle(self, bundle: object, request_id: int) -> None:
        if request_id != self._request_id or not isinstance(bundle, DashboardBundle):
            return
        summary = bundle.summary
        symbol = self.symbol
        as_of = summary.latest_date.strftime("%Y-%m-%d") if summary.latest_date else "暂无快照"

        self.asset_card.set_value(
            fmt_money(summary.assets, symbol),
            f"截至 {as_of}",
            tone="neutral",
        )
        self.liability_card.set_value(
            fmt_money(summary.liabilities, symbol),
            f"截至 {as_of}",
            tone="neutral",
        )
        net_tone = "negative" if summary.net < 0 else "neutral"
        self.net_card.set_value(
            fmt_money(summary.net, symbol),
            "资产 − 负债",
            tone=net_tone,
        )

        if summary.change is None:
            self.change_card.set_value("—", "暂无上一期快照", tone="neutral")
        else:
            tone = "positive" if summary.change > 0 else ("negative" if summary.change < 0 else "neutral")
            hint = f"较 {summary.previous_date.strftime('%Y-%m-%d') if summary.previous_date else '上次'}"
            if summary.change_rate is not None:
                hint += f" · {fmt_percent(summary.change_rate)}"
            self.change_card.set_value(
                fmt_signed_money(summary.change, symbol),
                hint,
                tone=tone,
            )

        portfolio = bundle.profit
        if portfolio.item_count == 0:
            self.profit_card.set_value("—", "尚无成本记录", tone="neutral")
        else:
            tone = (
                "positive"
                if portfolio.pnl_cny > 0
                else ("negative" if portfolio.pnl_cny < 0 else "neutral")
            )
            hint = f"市值 {fmt_money(portfolio.value_cny, symbol)} · 成本 {fmt_money(portfolio.cost_cny, symbol)}"
            if portfolio.pnl_rate is not None:
                hint += f" · {fmt_percent(portfolio.pnl_rate)}"
            if portfolio.missing_rate:
                hint += f" · {portfolio.missing_rate} 项缺汇率"
            self.profit_card.set_value(
                fmt_signed_money(portfolio.pnl_cny, symbol),
                hint,
                tone=tone,
            )

        self.asset_chart.set_data(
            bundle.assets,
            symbol,
            center_text="资产",
            empty_text="暂无资产估值",
        )
        self.liability_chart.set_data(
            bundle.liabilities,
            symbol,
            center_text="负债",
            empty_text="暂无负债估值",
        )
        self.line_chart.set_data(
            bundle.points,
            symbol,
            self.granularity_combo.currentData() or "month",
        )

        if summary.account_count == 0:
            self.empty_label.setText(
                "还没有账户。请先到左侧「账户管理」新增资产或负债账户，再录入估值。"
            )
            self.empty_label.show()
        elif summary.snapshot_count == 0:
            self.empty_label.setText(
                "账户已创建，但还没有估值快照。请到「账户管理」录入第一笔估值。"
            )
            self.empty_label.show()
        else:
            self.empty_label.hide()
