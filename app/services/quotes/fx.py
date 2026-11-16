"""汇率适配器：复用汇率服务，并给出行情侧统一入口。"""
from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.services import exchange_rates
from app.services.quotes.base import QuoteError

_USD_RATE: Optional[Tuple[float, Decimal]] = None
_RATE_TTL = 300.0


def usd_cny() -> Decimal:
    """美元兑人民币汇率，缓存 5 分钟。"""
    global _USD_RATE
    now = time.monotonic()
    if _USD_RATE is not None and now - _USD_RATE[0] < _RATE_TTL:
        return _USD_RATE[1]
    rates, _source = exchange_rates.fetch_latest_rates()
    usd = rates.get("USD")
    if usd is None:
        raise QuoteError("缺少 USD/CNY 汇率，无法折算美元报价")
    _USD_RATE = (now, usd)
    return usd


def fetch_rate(code: str) -> Decimal:
    """获取 1 单位外币兑人民币汇率。"""
    clean = (code or "").strip().upper()
    if clean == "CNY":
        return Decimal("1")
    rates, _source = exchange_rates.fetch_latest_rates()
    rate = rates.get(clean)
    if rate is None:
        raise QuoteError(f"未获取到 {clean} 兑人民币汇率")
    return rate


def refresh_rates(session: Session) -> Tuple[date, int]:
    """拉取并保存最新汇率，与汇率服务保持同一数据源。"""
    return exchange_rates.refresh_rates(session)
