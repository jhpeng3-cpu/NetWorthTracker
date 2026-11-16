"""黄金 / 白银现货适配：新浪现货、gold-api，统一换算为人民币/克。"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from app.services.quotes.base import QuoteError, PricePoint, http_get, to_price
from app.services.quotes.fx import usd_cny

GRAMS_PER_OUNCE = Decimal("31.1034768")
GOLD_ALIASES = {"XAU", "GOLD", "AU9999", "AU100G", "AU"}
SILVER_ALIASES = {"XAG", "SILVER", "AG9999", "AG1000G", "AG"}


def parse_sina_spot(payload: str) -> Decimal:
    """解析 hq.sinajs.cn 的 hf_XAU / hf_SI 返回，单位为美元/盎司。"""
    if '"' not in payload:
        raise QuoteError("新浪现货返回为空")
    body = payload.split('"')[1]
    parts = body.split(",")
    if not parts or not parts[0].strip():
        raise QuoteError("新浪现货格式异常")
    price = to_price(parts[0])
    if price is None:
        raise QuoteError("新浪现货价格无效")
    return price


def parse_gold_api(payload: dict) -> Decimal:
    price = to_price(payload.get("price"))
    if price is None:
        raise QuoteError("gold-api 价格无效")
    return price


def _usd_per_ounce(sina_code: str, api_code: str) -> tuple:
    """返回（美元/盎司, 数据源），新浪失败时回退 gold-api。"""
    errors = []
    try:
        return (
            parse_sina_spot(
                http_get(
                    f"https://hq.sinajs.cn/list={sina_code}",
                    referer="https://finance.sina.com.cn",
                ).decode("gbk", errors="ignore")
            ),
            "hq.sinajs.cn",
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"新浪：{exc}")
    try:
        return (
            parse_gold_api(
                json.loads(
                    http_get(f"https://api.gold-api.com/price/{api_code}").decode(
                        "utf-8", errors="ignore"
                    )
                )
            ),
            "api.gold-api.com",
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"gold-api：{exc}")
    raise QuoteError("；".join(errors) or "贵金属行情获取失败")


def _metal_point(
    symbol: str,
    market: str,
    name: str,
    sina_code: str,
    api_code: str,
) -> PricePoint:
    usd_per_ounce, source = _usd_per_ounce(sina_code, api_code)
    price = (usd_per_ounce * usd_cny() / GRAMS_PER_OUNCE).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return PricePoint(
        symbol=symbol,
        market=market,
        price=price,
        currency="CNY",
        quote_time=datetime.now(),
        source=source,
        name=name,
        unit="元/克",
    )


def fetch_gold(symbol: str = "XAU") -> PricePoint:
    """现货黄金，人民币/克。"""
    return _metal_point(symbol or "XAU", "GOLD", "现货黄金", "hf_XAU", "XAU")


def fetch_silver(symbol: str = "XAG") -> PricePoint:
    """现货白银，人民币/克（与黄金一致）。"""
    return _metal_point(symbol or "XAG", "SILVER", "现货白银", "hf_SI", "XAG")
