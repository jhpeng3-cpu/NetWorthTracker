"""汇率服务：拉取各币种兑人民币汇率、按日落库与有效汇率查询。

- 数据源为免费、无需 API Key 的公开接口，按顺序尝试直到成功。
- 汇率统一表示为「1 单位外币兑人民币」，入库保留 6 位小数（展示 4 位）。
- 同一币种同一日期重复拉取时覆盖更新；CNY 为基准货币，恒为 1，不入库。
"""
from __future__ import annotations

import json
import urllib.request
from bisect import bisect_right
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BASE_CURRENCY, CURRENCY_CODES, ExchangeRate
from app.utils.exceptions import AppRuntimeError

getcontext().prec = 28

RATE_QUANT = Decimal("0.000001")
CENT = Decimal("0.01")
HTTP_TIMEOUT = 15


class ExchangeRateError(AppRuntimeError):
    """所有汇率源都失败时抛出。"""


def _convert_from_per_cny(per_cny: dict) -> Dict[str, Decimal]:
    """接口按「1 CNY 兑多少外币」返回，这里换算成「1 外币兑多少 CNY」。"""
    result: Dict[str, Decimal] = {}
    for code in CURRENCY_CODES:
        if code == BASE_CURRENCY:
            continue
        raw = per_cny.get(code) or per_cny.get(code.lower())
        if raw in (None, 0, "0"):
            continue
        result[code] = (Decimal(1) / Decimal(str(raw))).quantize(
            RATE_QUANT, rounding=ROUND_HALF_UP
        )
    return result


def _parse_erapi(payload: dict) -> Dict[str, Decimal]:
    if payload.get("result") != "success":
        raise ValueError(payload.get("error-type") or "接口返回异常")
    return _convert_from_per_cny(payload.get("rates") or {})


def _parse_currency_api(payload: dict) -> Dict[str, Decimal]:
    return _convert_from_per_cny(payload.get("cny") or {})


_SOURCES: List[Tuple[str, Callable[[dict], Dict[str, Decimal]]]] = [
    ("https://open.er-api.com/v6/latest/CNY", _parse_erapi),
    ("https://latest.currency-api.pages.dev/v1/currencies/cny.json", _parse_currency_api),
    (
        "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/cny.json",
        _parse_currency_api,
    ),
]


def fetch_latest_rates() -> Tuple[Dict[str, Decimal], str]:
    """依次尝试各数据源，返回（汇率字典, 生效的数据源地址）。"""
    errors: List[str] = []
    for url, parser in _SOURCES:
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "NetWorthTracker"}
            )
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
            rates = parser(payload)
            if rates:
                return rates, url
            errors.append(f"{url}：未返回所需币种")
        except Exception as exc:  # noqa: BLE001 - 逐源尝试，最后汇总
            errors.append(f"{url}：{exc}")
    raise ExchangeRateError("所有汇率源均请求失败。" + "；".join(errors))


def save_rates(
    session: Session,
    rates: Dict[str, Decimal],
    on_date: Optional[date] = None,
    source: str = "",
) -> Tuple[date, int]:
    """按日写入汇率，同一天同一币种覆盖更新。"""
    day = on_date or date.today()
    for code, rate in rates.items():
        existing = session.scalar(
            select(ExchangeRate).where(
                ExchangeRate.currency_code == code,
                ExchangeRate.rate_date == day,
            )
        )
        if existing is None:
            session.add(
                ExchangeRate(currency_code=code, rate_date=day, rate=rate, source=source)
            )
        else:
            existing.rate = rate
            existing.source = source
            existing.updated_at = datetime.now()
    session.commit()
    return day, len(rates)


def refresh_rates(session: Session) -> Tuple[date, int]:
    """拉取并保存最新汇率，返回（日期, 币种数量）。"""
    rates, source = fetch_latest_rates()
    return save_rates(session, rates, source=source)


def build_rate_lookup(session: Session) -> Callable[[str, date], Decimal]:
    """构建「币种 + 日期 → 有效汇率」查询函数（按日前向填充）。

    某币种完全缺失汇率时按 1 处理（即不折算）；早于最早汇率日的日期沿用最早汇率。
    """
    rows = session.execute(
        select(
            ExchangeRate.currency_code,
            ExchangeRate.rate_date,
            ExchangeRate.rate,
        ).order_by(ExchangeRate.currency_code, ExchangeRate.rate_date)
    ).all()
    series: Dict[str, Tuple[List[date], List[Decimal]]] = {}
    for code, day, rate in rows:
        dates, values = series.setdefault(code, ([], []))
        dates.append(day)
        values.append(rate)

    def lookup(code: str, day: date) -> Decimal:
        if code == BASE_CURRENCY:
            return Decimal("1")
        entry = series.get(code)
        if entry is None:
            return Decimal("1")
        index = bisect_right(entry[0], day) - 1
        if index < 0:
            return entry[1][0]
        return entry[1][index]

    return lookup


def to_cny(
    value: Optional[Decimal],
    currency: str,
    day: date,
    lookup: Callable[[str, date], Decimal],
) -> Decimal:
    """把原币种金额按指定日期的有效汇率折算为人民币。"""
    if value is None:
        return Decimal("0.00")
    return (value * lookup(currency, day)).quantize(CENT, rounding=ROUND_HALF_UP)


def latest_rates(session: Session) -> Dict[str, Tuple[date, Decimal]]:
    """每个币种最近一次汇率，供设置页展示。"""
    result: Dict[str, Tuple[date, Decimal]] = {}
    for code, day, rate in session.execute(
        select(
            ExchangeRate.currency_code,
            ExchangeRate.rate_date,
            ExchangeRate.rate,
        ).order_by(ExchangeRate.currency_code, ExchangeRate.rate_date.desc())
    ).all():
        if code not in result:
            result[code] = (day, rate)
    return result


def latest_lookup(session: Session) -> Callable[[str, date], Decimal]:
    """以各币种最新一次汇率折算（忽略日期），接口与 build_rate_lookup 一致。

    用于需要「统一按最新汇率」展示的实时金额；缺少汇率的币种按 1 处理。
    """
    rates = {code: rate for code, (_day, rate) in latest_rates(session).items()}

    def lookup(code: str, _day: Optional[date] = None) -> Decimal:
        if code == BASE_CURRENCY:
            return Decimal("1")
        return rates.get(code, Decimal("1"))

    return lookup
