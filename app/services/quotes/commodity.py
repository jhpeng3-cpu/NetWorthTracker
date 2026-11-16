"""大宗商品行情：原油、铜、天然气。

优先使用国内期货主连（人民币报价），缺失时回退国际报价并按汇率折算。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from app.services.quotes.base import QuoteError, PricePoint, http_get, to_price
from app.services.quotes.fx import usd_cny

POUNDS_PER_TON = Decimal("2204.62262185")
COMMODITY_LABELS = {"CL": "原油", "HG": "铜", "NG": "天然气"}
COMMODITY_UNITS = {"CL": "元/桶", "HG": "元/吨", "NG": "元/百万英热"}
COMMODITY_ALIASES = {
    "CL": "CL",
    "WTI": "CL",
    "原油": "CL",
    "SC": "CL",
    "HG": "HG",
    "COPPER": "HG",
    "铜": "HG",
    "CU": "HG",
    "NG": "NG",
    "GAS": "NG",
    "天然气": "NG",
}


def normalize_commodity(raw: str) -> str:
    text = (raw or "").strip().upper().replace(" ", "")
    return COMMODITY_ALIASES.get(text, text)


def parse_sina_futures(payload: str) -> Decimal:
    """解析 hq.sinajs.cn 的 hf_ 国际期货返回，首字段为最新价。"""
    if '"' not in payload:
        raise QuoteError("新浪期货返回为空")
    body = payload.split('"')[1]
    parts = body.split(",")
    if not parts or not parts[0].strip():
        raise QuoteError("新浪期货格式异常")
    price = to_price(parts[0])
    if price is None:
        raise QuoteError("新浪期货价格无效")
    return price


def parse_domestic_futures(payload: str, index: int = 8) -> Decimal:
    """解析 nf_ 国内期货主连，默认取第 9 个字段（最新价）。"""
    if '"' not in payload:
        raise QuoteError("国内期货返回为空")
    body = payload.split('"')[1]
    parts = body.split(",")
    if len(parts) <= index:
        raise QuoteError("国内期货格式异常")
    price = to_price(parts[index])
    if price is None:
        raise QuoteError("国内期货价格无效")
    return price


def copper_cents_to_cny_ton(cents_per_pound: Decimal, rate: Decimal) -> Decimal:
    """美铜报价（美分/磅）换算为人民币/吨。"""
    return (
        cents_per_pound / Decimal("100") * rate * POUNDS_PER_TON
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _sina(code: str) -> str:
    return http_get(
        f"https://hq.sinajs.cn/list={code}",
        referer="https://finance.sina.com.cn",
    ).decode("gbk", errors="ignore")


def _domestic(code: str) -> Decimal:
    return parse_domestic_futures(_sina(code))


def _international(code: str) -> Decimal:
    return parse_sina_futures(_sina(code))


def _point(symbol: str, price: Decimal, source: str) -> PricePoint:
    return PricePoint(
        symbol=symbol,
        market="COMMODITY",
        price=price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        currency="CNY",
        quote_time=datetime.now(),
        source=source,
        name=COMMODITY_LABELS.get(symbol, symbol),
        unit=COMMODITY_UNITS.get(symbol, ""),
    )


def fetch_commodity(symbol: str) -> PricePoint:
    """按品种获取人民币报价；国内主连不可用时回退国际盘。"""
    code = normalize_commodity(symbol)
    if code not in COMMODITY_LABELS:
        raise QuoteError("大宗商品代码仅支持 CL（原油）、HG（铜）、NG（天然气）")

    errors = []
    if code == "CL":
        try:
            return _point(code, _domestic("nf_SC0"), "hq.sinajs.cn · 上海原油连续")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"国内原油：{exc}")
        try:
            return _point(
                code, _international("hf_CL") * usd_cny(), "hq.sinajs.cn · WTI 原油"
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"WTI 原油：{exc}")
    elif code == "HG":
        try:
            return _point(code, _domestic("nf_CU0"), "hq.sinajs.cn · 沪铜连续")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"国内铜：{exc}")
        try:
            return _point(
                code,
                copper_cents_to_cny_ton(_international("hf_HG"), usd_cny()),
                "hq.sinajs.cn · COMEX 铜",
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"COMEX 铜：{exc}")
    else:
        try:
            return _point(
                code,
                _international("hf_NG") * usd_cny(),
                "hq.sinajs.cn · Henry Hub 天然气",
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"天然气：{exc}")

    raise QuoteError("；".join(errors) or "大宗商品行情获取失败")
