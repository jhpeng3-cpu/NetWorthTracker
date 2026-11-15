"""matplotlib 图表组件（环形图 + 折线图）。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional, Sequence

import matplotlib

matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "Microsoft YaHei UI",
    "SimHei",
    "Arial Unicode MS",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False

import matplotlib.dates as mdates  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget  # noqa: E402

from app.services.analytics import NetWorthPoint, PieSlice  # noqa: E402
from app.ui.styles import palette  # noqa: E402

MAX_PIE_SLICES = 8


def _compact_slices(slices: Sequence[PieSlice]) -> List[PieSlice]:
    if len(slices) <= MAX_PIE_SLICES:
        return list(slices)
    top = list(slices[: MAX_PIE_SLICES - 1])
    rest = slices[MAX_PIE_SLICES - 1 :]
    other_value = sum((item.value for item in rest), Decimal("0.00"))
    other_percent = sum((item.percent for item in rest), Decimal("0.00"))
    top.append(PieSlice(label="其他", value=other_value, percent=other_percent))
    return top


class DonutChart(QWidget):
    def __init__(self, theme: str = "light", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._theme = theme
        self._slices: List[PieSlice] = []
        self._symbol = "¥"
        self._center_text = "合计"
        self._empty_text = "暂无数据"
        self._figure = Figure(figsize=(5, 3), dpi=100)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._canvas.setMinimumHeight(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)
        self._render()

    def set_data(
        self,
        slices: List[PieSlice],
        symbol: str,
        center_text: str = "合计",
        empty_text: str = "暂无数据",
    ) -> None:
        self._slices = _compact_slices(slices)
        self._symbol = symbol
        self._center_text = center_text
        self._empty_text = empty_text
        self._render()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self._render()

    def _render(self) -> None:
        colors = palette(self._theme)
        figure = self._figure
        figure.clear()
        figure.patch.set_facecolor(colors["surface"])

        if not self._slices:
            axes = figure.add_axes([0.05, 0.05, 0.9, 0.9])
            axes.set_facecolor(colors["surface"])
            axes.axis("off")
            axes.text(
                0.5,
                0.5,
                self._empty_text,
                ha="center",
                va="center",
                color=colors["muted"],
                fontsize=11,
            )
            self._canvas.draw_idle()
            return

        pie_axes = figure.add_axes([0.0, 0.06, 0.5, 0.88])
        legend_axes = figure.add_axes([0.5, 0.03, 0.49, 0.94])
        pie_axes.set_facecolor(colors["surface"])
        legend_axes.set_facecolor(colors["surface"])
        legend_axes.axis("off")

        values = [float(item.value) for item in self._slices]  # 仅用于绘图，计算仍为 Decimal
        pie_colors = colors["pie"][: len(values)]
        wedges, _ = pie_axes.pie(
            values,
            colors=pie_colors,
            startangle=90,
            counterclock=False,
            wedgeprops={
                "width": 0.40,
                "edgecolor": colors["surface"],
                "linewidth": 2,
            },
        )
        total = sum(values)
        pie_axes.text(
            0,
            0,
            f"{self._center_text}\n{self._symbol}{total:,.0f}",
            ha="center",
            va="center",
            color=colors["text"],
            fontsize=10,
            fontweight="bold",
        )
        labels = [
            f"{item.label}   {item.percent:.1f}%"
            for item in self._slices
        ]
        legend_axes.legend(
            wedges,
            labels,
            loc="center left",
            frameon=False,
            fontsize=8.5,
            labelcolor=colors["text"],
            handlelength=1.2,
            borderaxespad=0.2,
        )
        self._canvas.draw_idle()


class LineChart(QWidget):
    def __init__(self, theme: str = "light", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._theme = theme
        self._points: List[NetWorthPoint] = []
        self._symbol = "¥"
        self._granularity = "day"
        self._figure = Figure(figsize=(7, 3.4), dpi=100)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._canvas.setMinimumHeight(260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)
        self._render()

    def set_data(
        self, points: List[NetWorthPoint], symbol: str, granularity: str = "day"
    ) -> None:
        self._points = list(points)
        self._symbol = symbol
        self._granularity = granularity
        self._render()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self._render()

    def _render(self) -> None:
        colors = palette(self._theme)
        figure = self._figure
        figure.clear()
        figure.patch.set_facecolor(colors["surface"])
        axes = figure.add_subplot(111)
        axes.set_facecolor(colors["surface"])

        if not self._points:
            axes.axis("off")
            axes.text(
                0.5,
                0.5,
                "暂无估值数据，录入快照后即可查看趋势",
                ha="center",
                va="center",
                color=colors["muted"],
                fontsize=11,
                transform=axes.transAxes,
            )
            self._canvas.draw_idle()
            return

        dates = [point.on_date for point in self._points]
        series = [
            ("总资产", [float(point.assets) for point in self._points], colors["chart_assets"]),
            ("总负债", [float(point.liabilities) for point in self._points], colors["chart_liabilities"]),
            ("净资产", [float(point.net) for point in self._points], colors["chart_net"]),
        ]
        for label, values, color in series:
            axes.plot(
                dates,
                values,
                label=label,
                color=color,
                linewidth=1.9,
                marker="o" if len(dates) <= 80 else None,
                markersize=3.2,
            )

        axes.axhline(0, color=colors["border"], linewidth=1)
        axes.grid(axis="y", color=colors["border"], linestyle="--", linewidth=0.7, alpha=0.8)
        axes.set_axisbelow(True)
        for spine in ("top", "right"):
            axes.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            axes.spines[spine].set_color(colors["border"])
        axes.tick_params(colors=colors["muted"], labelsize=8.5)
        axes.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: self._axis_money(value)))
        axes.legend(
            loc="lower left",
            bbox_to_anchor=(0.0, 1.01),
            frameon=False,
            fontsize=9,
            labelcolor=colors["text"],
            ncol=3,
        )

        locator = mdates.AutoDateLocator(minticks=3, maxticks=8)
        axes.xaxis.set_major_locator(locator)
        fmt = {"day": "%m-%d", "month": "%Y-%m", "year": "%Y"}.get(self._granularity, "%Y-%m-%d")
        axes.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
        if len(dates) == 1:
            axes.scatter([dates[0]], [series[2][1][0]], color=colors["chart_net"], s=24, zorder=5)
        figure.subplots_adjust(left=0.11, right=0.98, top=0.86, bottom=0.19)
        self._canvas.draw_idle()

    def _axis_money(self, value: float) -> str:
        symbol = self._symbol
        sign = "-" if value < 0 else ""
        absolute = abs(value)
        if absolute >= 100_000_000:
            return f"{sign}{symbol}{absolute / 100_000_000:,.2f}亿"
        if absolute >= 10_000:
            return f"{sign}{symbol}{absolute / 10_000:,.1f}万"
        return f"{sign}{symbol}{absolute:,.0f}"
