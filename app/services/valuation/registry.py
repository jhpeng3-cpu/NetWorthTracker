"""按估值方式选择估值器。"""
from __future__ import annotations

from typing import Dict, Optional

from app.db.models import (
    VALUATION_ACCRUAL,
    VALUATION_AUTO,
    VALUATION_MANUAL,
    AccountItem,
    default_valuation_mode,
)
from app.services.valuation.accrual import AccrualValuator
from app.services.valuation.base import Valuator
from app.services.valuation.manual import ManualValuator
from app.services.valuation.quote import QuoteValuator

_VALUATORS: Dict[str, Valuator] = {
    VALUATION_AUTO: QuoteValuator(),
    VALUATION_ACCRUAL: AccrualValuator(),
    VALUATION_MANUAL: ManualValuator(),
}


def get_valuator(mode: str) -> Optional[Valuator]:
    return _VALUATORS.get(mode)


def valuator_for(item: AccountItem) -> Optional[Valuator]:
    mode = item.valuation_mode or default_valuation_mode(item.category)
    return get_valuator(mode)
