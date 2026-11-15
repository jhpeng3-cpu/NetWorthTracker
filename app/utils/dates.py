"""日期与区间工具。"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import List

RANGE_OPTIONS = [
    ("1m", "近 1 月"),
    ("3m", "近 3 月"),
    ("6m", "近 6 月"),
    ("1y", "近 1 年"),
    ("3y", "近 3 年"),
    ("all", "全部"),
]
RANGE_MONTHS = {"1m": 1, "3m": 3, "6m": 6, "1y": 12, "3y": 36}

GRANULARITY_OPTIONS = [("day", "日"), ("month", "月"), ("year", "年")]


def add_months(day: date, months: int) -> date:
    """按月加减，并自动裁剪到目标月份的最后一天。"""
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def month_end(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def year_end(day: date) -> date:
    return date(day.year, 12, 31)


def resolve_range_start(key: str, today: date, first_snapshot: date | None) -> date:
    if key == "all":
        return first_snapshot or today
    months = RANGE_MONTHS.get(key, 12)
    return add_months(today, -months)


def build_period_points(start: date, end: date, granularity: str) -> List[date]:
    """生成月/年粒度的时间点（每个周期最后一天，当前周期裁剪到今天）。"""
    if start > end:
        return []
    if granularity == "month":
        step_end = month_end
    elif granularity == "year":
        step_end = year_end
    else:
        raise ValueError(f"不支持的粒度: {granularity}")

    points: List[date] = []
    cursor = step_end(start)
    while cursor < end:
        if not points or points[-1] != cursor:
            points.append(cursor)
        cursor = step_end(cursor + timedelta(days=1))
    if not points or points[-1] != end:
        points.append(end)
    return points


def format_date_cn(day: date | None) -> str:
    if day is None:
        return "—"
    return day.strftime("%Y-%m-%d")
