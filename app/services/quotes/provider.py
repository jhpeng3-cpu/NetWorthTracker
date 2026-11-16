"""统一行情入口：按类别与市场选择适配器，带本地缓存与限频。"""
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

from app.services.quotes.base import PricePoint, QuoteError, throttle
from app.services.quotes.commodity import fetch_commodity, normalize_commodity
from app.services.quotes.fund import fetch_fund_nav
from app.services.quotes.gold import (
    GOLD_ALIASES,
    SILVER_ALIASES,
    fetch_gold,
    fetch_silver,
)
from app.services.quotes.stock import fetch_quote, normalize_symbol

CACHE_TTL = 60.0
_CACHE: Dict[Tuple[str, str], Tuple[float, PricePoint]] = {}


def resolve_market(
    symbol: str, market: Optional[str] = None, category: str = ""
) -> Tuple[str, str]:
    """结合资产类别归一化代码与市场。"""
    text = (symbol or "").strip().upper().replace(" ", "")
    clean_market = (market or "").strip().upper()

    if category == "gold":
        return text or "XAU", "GOLD"
    if category == "silver":
        return text or "XAG", "SILVER"
    if category == "commodity":
        return normalize_commodity(text), "COMMODITY"
    if clean_market in ("FUND", "GOLD", "SILVER", "COMMODITY"):
        return text, clean_market
    if not text:
        return "", ""
    if category == "fund":
        return text, "FUND"
    if text in GOLD_ALIASES and category not in ("stock", "fund"):
        return text, "GOLD"
    if text in SILVER_ALIASES and category not in ("stock", "fund"):
        return text, "SILVER"
    return normalize_symbol(text, clean_market)


def get_price(
    symbol: str, market: str = "", category: str = ""
) -> PricePoint:
    """获取统一行情点；优先使用 60 秒内存缓存。"""
    clean_symbol, clean_market = resolve_market(symbol, market, category)
    if not clean_symbol:
        raise QuoteError("未填写行情代码")
    key = (clean_symbol, clean_market)
    cached = _CACHE.get(key)
    if cached is not None and time.monotonic() - cached[0] < CACHE_TTL:
        return cached[1]

    throttle()
    if clean_market == "FUND":
        point = fetch_fund_nav(clean_symbol)
    elif clean_market == "GOLD":
        point = fetch_gold(clean_symbol)
    elif clean_market == "SILVER":
        point = fetch_silver(clean_symbol)
    elif clean_market == "COMMODITY":
        point = fetch_commodity(clean_symbol)
    else:
        quote = fetch_quote(clean_symbol, clean_market)
        point = PricePoint(
            symbol=quote.symbol,
            market=quote.market,
            price=quote.price,
            currency=quote.currency,
            quote_time=quote.quote_time,
            source=quote.source,
            name=quote.name,
        )
    _CACHE[key] = (time.monotonic(), point)
    return point


def clear_cache() -> None:
    _CACHE.clear()
