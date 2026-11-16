"""汇率适配器：复用汇率服务，并给出行情侧统一入口。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Tuple

from sqlalchemy.orm import Session

from app.services import exchange_rates
from app.services.quotes.base import QuoteError


def usd_cny() -> Decimal:
    """美元兑人民币汇率，复用汇率服务的 60 秒缓存。"""
    rates, _source = exchange_rates.fetch_latest_rates()
    usd = rates.get("USD")
    if usd is None:
        raise QuoteError("缺少 USD/CNY 汇率，无法折算美元报价")
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
