"""公募基金净值适配（天天基金 / 东方财富）。"""
from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

from app.services.quotes.base import QuoteError, PricePoint, http_get, to_price


def parse_fund_payload(payload: dict, code: str) -> PricePoint:
    """解析历史净值接口返回的第一条记录。"""
    data = payload.get("Data") or {}
    rows = data.get("LSJZList") or []
    if not rows:
        raise QuoteError("基金净值接口未返回数据")
    row = rows[0]
    price = to_price(row.get("DWJZ"))
    if price is None:
        raise QuoteError("基金净值无效")
    day: Optional[date] = None
    raw_day = str(row.get("FSRQ") or "").strip()
    if raw_day:
        try:
            day = date.fromisoformat(raw_day)
        except ValueError:
            day = None
    quote_time = datetime.combine(day, time(15, 0)) if day else datetime.now()
    return PricePoint(
        symbol=code,
        market="FUND",
        price=price,
        currency="CNY",
        quote_time=quote_time,
        source="fund.eastmoney.com",
        name=code,
    )


def fetch_fund_nav(code: str) -> PricePoint:
    url = (
        "https://api.fund.eastmoney.com/f10/lsjz"
        f"?fundCode={code}&pageIndex=1&pageSize=1"
    )
    payload = json.loads(
        http_get(url, referer="https://fundf10.eastmoney.com/").decode(
            "utf-8", errors="ignore"
        )
    )
    return parse_fund_payload(payload, code)
