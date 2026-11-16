"""轻量图表组件：Qt 原生绘制的环形图与折线图（不依赖 matplotlib）。"""
from __future__ import annotations

from decimal import Decimal
from math import ceil
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.services.analytics import NetWorthPoint, PieSlice
from app.ui.styles import palette

MAX_PIE_SLICES = 8
FONT_FAMILY = "Microsoft YaHei"


def _compact_slices(slices: Sequence[PieSlice]) -> List[PieSlice]:
    if len(slices) <= MAX_PIE_SLICES:
        return list(slices)
    top = list(slices[: MAX_PIE_SLICES - 1])
    rest = slices[MAX_PIE_SLICES - 1 :]
    other_value = sum((item.value for item in rest), Decimal("0.00"))
    other_percent = sum((item.percent for item in rest), Decimal("0.00"))
    top.append(PieSlice(label="其他", value=other_value, percent=other_percent))
    return top


def _money_axis(value: float, symbol: str) -> str:
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    if absolute >= 100_000_000:
        return f"{sign}{symbol}{absolute / 100_000_000:,.2f}亿"
    if absolute >= 10_000:
        return f"{sign}{symbol}{absolute / 10_000:,.1f}万"
    return f"{sign}{symbol}{absolute:,.0f}"


class _ChartBase(QWidget):
    def __init__(
        self,
        theme: str = "light",
        minimum_height: int = 220,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._theme = theme
        self.setMinimumHeight(minimum_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        colors = palette(self._theme)
        painter.fillRect(self.rect(), QColor(colors["surface"]))
        self._paint(painter, colors)
        painter.end()

    def _paint(self, painter: QPainter, colors: Dict[str, Any]) -> None:
        raise NotImplementedError


class DonutChart(_ChartBase):
    def __init__(self, theme: str = "light", parent: Optional[QWidget] = None):
        super().__init__(theme, 220, parent)
        self._slices: List[PieSlice] = []
        self._symbol = "¥"
        self._center_text = "合计"
        self._empty_text = "暂无数据"

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
        self.update()

    def _paint(self, painter: QPainter, colors: Dict[str, Any]) -> None:
        area = QRectF(self.rect()).adjusted(10, 8, -10, -8)
        if not self._slices:
            self._draw_empty(painter, area, colors)
            return

        total = sum((float(item.value) for item in self._slices), 0.0)
        if total <= 0:
            self._draw_empty(painter, area, colors)
            return

        legend_width = min(max(area.width() * 0.46, 130.0), 230.0)
        pie_area = QRectF(
            area.left(), area.top(), area.width() - legend_width, area.height()
        )
        side = max(min(pie_area.width(), pie_area.height()) - 16, 40.0)
        pie_rect = QRectF(
            pie_area.center().x() - side / 2,
            pie_area.center().y() - side / 2,
            side,
            side,
        )

        pie_colors = list(colors["pie"])  # type: ignore[arg-type]
        start = 90 * 16
        for index, item in enumerate(self._slices):
            span = -int(round(float(item.value) / total * 360 * 16))
            if span == 0:
                continue
            painter.setBrush(QColor(pie_colors[index % len(pie_colors)]))
            painter.setPen(QPen(QColor(colors["surface"]), 2))  # type: ignore[arg-type]
            painter.drawPie(pie_rect, start, span)
            start += span

        inner_offset = side * 0.20
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["surface"]))  # type: ignore[arg-type]
        painter.drawEllipse(pie_rect.adjusted(inner_offset, inner_offset, -inner_offset, -inner_offset))

        painter.setPen(QColor(colors["text"]))  # type: ignore[arg-type]
        font = QFont(FONT_FAMILY, 10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            pie_rect,
            Qt.AlignmentFlag.AlignCenter,
            f"{self._center_text}\n{self._symbol}{total:,.0f}",
        )

        self._draw_legend(painter, colors, area, pie_area.right() + 16)

    def _draw_legend(
        self,
        painter: QPainter,
        colors: Dict[str, Any],
        area: QRectF,
        left: float,
    ) -> None:
        pie_colors = list(colors["pie"])  # type: ignore[arg-type]
        count = max(len(self._slices), 1)
        row_height = min(max(area.height() / count, 20.0), 30.0)
        top = area.center().y() - row_height * count / 2
        font = QFont(FONT_FAMILY, 9)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        available = max(area.right() - left - 4, 40.0)

        for index, item in enumerate(self._slices):
            y = top + index * row_height
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pie_colors[index % len(pie_colors)]))
            painter.drawRoundedRect(QRectF(left, y + row_height / 2 - 5, 10, 10), 2, 2)

            text = f"{item.label}   {item.percent:.1f}%"
            text = metrics.elidedText(
                text, Qt.TextElideMode.ElideRight, int(available - 16)
            )
            painter.setPen(QColor(colors["text"]))  # type: ignore[arg-type]
            painter.drawText(
                QRectF(left + 16, y, available - 16, row_height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                text,
            )

    def _draw_empty(
        self, painter: QPainter, area: QRectF, colors: Dict[str, Any]
    ) -> None:
        painter.setPen(QColor(colors["muted"]))  # type: ignore[arg-type]
        painter.setFont(QFont(FONT_FAMILY, 11))
        painter.drawText(area, Qt.AlignmentFlag.AlignCenter, self._empty_text)


class LineChart(_ChartBase):
    def __init__(self, theme: str = "light", parent: Optional[QWidget] = None):
        super().__init__(theme, 260, parent)
        self._points: List[NetWorthPoint] = []
        self._symbol = "¥"
        self._granularity = "day"

    def set_data(
        self, points: List[NetWorthPoint], symbol: str, granularity: str = "day"
    ) -> None:
        self._points = list(points)
        self._symbol = symbol
        self._granularity = granularity
        self.update()

    def _paint(self, painter: QPainter, colors: Dict[str, Any]) -> None:
        area = QRectF(self.rect()).adjusted(0, 0, 0, 0)
        if not self._points:
            painter.setPen(QColor(colors["muted"]))  # type: ignore[arg-type]
            painter.setFont(QFont(FONT_FAMILY, 11))
            painter.drawText(
                area,
                Qt.AlignmentFlag.AlignCenter,
                "暂无估值数据，录入快照后即可查看趋势",
            )
            return

        plot = QRectF(
            area.left() + 66,
            area.top() + 34,
            max(area.width() - 82, 20),
            max(area.height() - 62, 20),
        )
        series = [
            ("总资产", [float(point.assets) for point in self._points], colors["chart_assets"]),
            ("总负债", [float(point.liabilities) for point in self._points], colors["chart_liabilities"]),
            ("净资产", [float(point.net) for point in self._points], colors["chart_net"]),
        ]
        all_values = [value for _, values, _ in series for value in values]
        low = min(all_values)
        high = max(all_values)
        if low == high:
            padding = max(abs(low) * 0.10, 1.0)
        else:
            padding = (high - low) * 0.08
        low -= padding
        high += padding
        span = high - low or 1.0

        self._draw_grid(painter, colors, plot, low, high, span)
        self._draw_x_axis(painter, colors, plot)
        self._draw_legend(painter, colors, area, series)

        for _, values, color in series:
            self._draw_series(painter, plot, values, low, span, color)

    def _y_for(self, value: float, plot: QRectF, low: float, span: float) -> float:
        return plot.bottom() - (value - low) / span * plot.height()

    def _draw_grid(
        self,
        painter: QPainter,
        colors: Dict[str, Any],
        plot: QRectF,
        low: float,
        high: float,
        span: float,
    ) -> None:
        painter.setFont(QFont(FONT_FAMILY, 8))
        ticks = 4
        for index in range(ticks + 1):
            value = low + span * index / ticks
            y = self._y_for(value, plot, low, span)
            pen = QPen(QColor(colors["border"]), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(colors["muted"]))  # type: ignore[arg-type]
            painter.drawText(
                QRectF(0, y - 8, plot.left() - 8, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _money_axis(value, self._symbol),
            )

        if low < 0 < high:
            y = self._y_for(0, plot, low, span)
            painter.setPen(QPen(QColor(colors["border"]), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

    def _draw_x_axis(
        self, painter: QPainter, colors: Dict[str, Any], plot: QRectF
    ) -> None:
        points = self._points
        count = len(points)
        format_string = {
            "day": "%m-%d",
            "month": "%Y-%m",
            "year": "%Y",
        }.get(self._granularity, "%Y-%m-%d")
        max_ticks = max(2, int(plot.width() // 72))
        if count <= max_ticks:
            indices = list(range(count))
        else:
            step = ceil((count - 1) / (max_ticks - 1))
            indices = list(range(0, count, step))
            if indices[-1] != count - 1:
                indices.append(count - 1)

        painter.setFont(QFont(FONT_FAMILY, 8))
        painter.setPen(QColor(colors["muted"]))  # type: ignore[arg-type]
        for index in indices:
            x = self._x_for(index, count, plot)
            label = points[index].on_date.strftime(format_string)
            painter.drawText(
                QRectF(x - 34, plot.bottom() + 6, 68, 18),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                label,
            )

    def _x_for(self, index: int, count: int, plot: QRectF) -> float:
        if count <= 1:
            return plot.center().x()
        return plot.left() + plot.width() * index / (count - 1)

    def _draw_legend(
        self,
        painter: QPainter,
        colors: Dict[str, Any],
        area: QRectF,
        series: Sequence[tuple],
    ) -> None:
        font = QFont(FONT_FAMILY, 9)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        x = area.left() + 8
        y = area.top() + 8
        for label, _, color in series:
            painter.setPen(QPen(QColor(color), 2))
            painter.drawLine(QPointF(x, y + 8), QPointF(x + 16, y + 8))
            painter.setPen(QColor(colors["text"]))  # type: ignore[arg-type]
            painter.drawText(
                QRectF(x + 21, y, metrics.horizontalAdvance(label) + 4, 16),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )
            x += 21 + metrics.horizontalAdvance(label) + 18

    def _draw_series(
        self,
        painter: QPainter,
        plot: QRectF,
        values: Sequence[float],
        low: float,
        span: float,
        color: object,
    ) -> None:
        count = len(values)
        points = [
            QPointF(
                self._x_for(index, count, plot),
                self._y_for(value, plot, low, span),
            )
            for index, value in enumerate(values)
        ]
        painter.setPen(QPen(QColor(color), 1.9))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if len(points) >= 2:
            painter.drawPolyline(QPolygonF(points))
        if len(points) <= 80:
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            for point in points:
                painter.drawEllipse(point, 2.4, 2.4)
