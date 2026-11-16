"""估值器抽象与结果对象。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from app.db.models import AccountItem


@dataclass(frozen=True)
class ValuationResult:
    """一次估值的结果；value 为原币金额。"""

    value: Decimal
    currency: str
    note: str = ""
    stale: bool = False
    as_of: Optional[date] = None


class Valuator(ABC):
    """按资产类型计算时点市值。"""

    mode: str = ""

    @abstractmethod
    def estimate(
        self, item: AccountItem, on_date: date
    ) -> Optional[ValuationResult]:
        """返回估值结果；参数不足时返回 None。"""
