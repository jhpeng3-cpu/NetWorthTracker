"""股票/基金行情：代码归一化、免费接口拉取、缓存与自动写入估值快照。

数据源均为免费、无需 API Key 的公开接口，按市场依次回退：
- A 股：腾讯 → 东方财富 → 新浪
- 港股：腾讯 → 东方财富 → 新浪
- 美股：腾讯 → 新浪

行情只保留每个代码最新一条；开盘期间由界面定时刷新。
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    AccountItem,
    PositionLot,
    PriceQuote,
    ValuationSnapshot,
)
from app.services import exchange_rates

HTTP_TIMEOUT = 8
UA = "Mozilla/5.0 NetWorthTracker"
CENT = Decimal("0.01")

MARKET_CURRENCY = {"CN": "CNY", "HK": "HKD", "US": "USD"}

TENCENT_PREFIX = {"CN": None, "HK": "hk", "US": "us"}
EASTMONEY_SECID = {"CN": None, "HK": "116", "US": None}


class QuoteError(Exception):
    """单个代码所有行情源都失败。"""


@dataclass(frozen=True)
class Quote:
    symbol: str
    market: str
    name: str
    price: Decimal
    currency: str
    quote_time: Optional[datetime]
    source: str


@dataclass(frozen=True)
class QuoteRefreshResult:
    requested: int
    fetched: int
    failed: int
    snapshots: int
    errors: List[str] = field(default_factory=list)


def normalize_symbol(
    raw: str, market: Optional[str] = None
) -> Tuple[str, str]:
    """把用户输入归一化为（纯代码, 市场）。市场取 CN / HK / US。"""
    text = (raw or "").strip().upper().replace(" ", "")
    if not text:
        return "", ""
    if "." in text:
        text = text.split(".", 1)[0]
    prefix_map = {"SH": "CN", "SZ": "CN", "HK": "HK", "US": "US"}
    if len(text) > 2 and text[:2] in prefix_map:
        market = prefix_map[text[:2]]
        text = text[2:]
    clean_market = (market or "").strip().upper()
    if clean_market not in MARKET_CURRENCY:
        clean_market = ""
    if text.isdigit():
        if len(text) >= 6:
            return text, clean_market or "CN"
        return text.zfill(5), clean_market or "HK"
    if text.isalnum():
        return text, clean_market or "US"
    return text, clean_market or "CN"


def _http_get(url: str, referer: Optional[str] = None) -> bytes:
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return response.read()


def _to_price(value: object) -> Optional[Decimal]:
    try:
        price = Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None
    if price <= 0:
        return None
    return price


def _fetch_tencent(symbol: str, market: str) -> Quote:
    if market == "CN":
        code = ("sh" if symbol.startswith(("6", "9")) else "sz") + symbol
    else:
        code = TENCENT_PREFIX[market] + symbol
    payload = _http_get(f"https://qt.gtimg.cn/q={code}").decode(
        "gbk", errors="ignore"
    )
    if '"' not in payload:
        raise QuoteError("腾讯行情返回为空")
    body = payload.split('"')[1]
    parts = body.split("~")
    if len(parts) < 4:
        raise QuoteError("腾讯行情格式异常")
    price = _to_price(parts[3])
    if price is None:
        raise QuoteError("腾讯行情价格无效")
    return Quote(
        symbol=symbol,
        market=market,
        name=parts[1] or symbol,
        price=price,
        currency=MARKET_CURRENCY[market],
        quote_time=datetime.now(),
        source="qt.gtimg.cn",
    )


def _fetch_eastmoney(symbol: str, market: str) -> Quote:
    if market == "CN":
        if symbol.startswith(("6", "9")):
            secid = f"1.{symbol}"
        else:
            secid = f"0.{symbol}"
    elif market == "HK":
        secid = f"{EASTMONEY_SECID['HK']}.{symbol}"
    else:
        raise QuoteError("东方财富不支持该市场")
    url = (
        "https://push2.eastmoney.com/api/qt/stock/get"
        f"?secid={secid}&fields=f43,f57,f58,f59"
    )
    payload = json.loads(_http_get(url).decode("utf-8", errors="ignore"))
    data = payload.get("data") or {}
    raw_price = data.get("f43")
    decimals = data.get("f59")
    if raw_price in (None, "-", 0) or decimals in (None, "-"):
        raise QuoteError("东方财富行情为空")
    price = _to_price(Decimal(str(raw_price)) / (Decimal(10) ** int(decimals)))
    if price is None:
        raise QuoteError("东方财富行情价格无效")
    return Quote(
        symbol=symbol,
        market=market,
        name=str(data.get("f58") or symbol),
        price=price,
        currency=MARKET_CURRENCY[market],
        quote_time=datetime.now(),
        source="push2.eastmoney.com",
    )


def _fetch_sina(symbol: str, market: str) -> Quote:
    if market == "CN":
        code = ("sh" if symbol.startswith(("6", "9")) else "sz") + symbol
    elif market == "HK":
        code = "hk" + symbol
    else:
        code = "gb_" + symbol.lower()
    payload = _http_get(
        f"https://hq.sinajs.cn/list={code}", referer="https://finance.sina.com.cn"
    ).decode("gbk", errors="ignore")
    if '"' not in payload:
        raise QuoteError("新浪行情返回为空")
    body = payload.split('"')[1]
    parts = body.split(",")
    try:
        if market == "CN":
            name, raw_price = parts[0], parts[3]
        elif market == "HK":
            name, raw_price = parts[1], parts[6]
        else:
            name, raw_price = parts[0], parts[1]
    except IndexError as exc:
        raise QuoteError("新浪行情格式异常") from exc
    price = _to_price(raw_price)
    if price is None:
        raise QuoteError("新浪行情价格无效")
    return Quote(
        symbol=symbol,
        market=market,
        name=name or symbol,
        price=price,
        currency=MARKET_CURRENCY[market],
        quote_time=datetime.now(),
        source="hq.sinajs.cn",
    )


_SOURCES = {
    "CN": (_fetch_tencent, _fetch_eastmoney, _fetch_sina),
    "HK": (_fetch_tencent, _fetch_eastmoney, _fetch_sina),
    "US": (_fetch_tencent, _fetch_sina),
}


def fetch_quote(symbol: str, market: str) -> Quote:
    """依次尝试该市场的行情源，全部失败时抛出 QuoteError。"""
    errors: List[str] = []
    for source in _SOURCES.get(market, ()):
        try:
            return source(symbol, market)
        except Exception as exc:  # noqa: BLE001 - 逐源回退
            errors.append(f"{source.__name__}: {exc}")
    raise QuoteError("；".join(errors) or "未知行情错误")


def save_quote(session: Session, quote: Quote) -> None:
    existing = session.scalar(
        select(PriceQuote).where(
            PriceQuote.symbol == quote.symbol,
            PriceQuote.market == quote.market,
        )
    )
    if existing is None:
        session.add(
            PriceQuote(
                symbol=quote.symbol,
                market=quote.market,
                name=quote.name,
                price=quote.price,
                currency=quote.currency,
                quote_time=quote.quote_time,
                source=quote.source,
            )
        )
        return
    existing.name = quote.name
    existing.price = quote.price
    existing.currency = quote.currency
    existing.quote_time = quote.quote_time
    existing.source = quote.source


def latest_quotes(session: Session) -> Dict[Tuple[str, str], Quote]:
    result: Dict[Tuple[str, str], Quote] = {}
    for row in session.scalars(select(PriceQuote)):
        result[(row.symbol, row.market)] = Quote(
            symbol=row.symbol,
            market=row.market,
            name=row.name or row.symbol,
            price=row.price,
            currency=row.currency,
            quote_time=row.quote_time,
            source=row.source or "",
        )
    return result


def _quantities(session: Session, item_ids: List[int]) -> Dict[int, Decimal]:
    if not item_ids:
        return {}
    rows = session.execute(
        select(PositionLot.item_id, func.sum(PositionLot.quantity))
        .where(PositionLot.item_id.in_(item_ids))
        .group_by(PositionLot.item_id)
    ).all()
    return {
        item_id: Decimal(str(quantity or 0))
        for item_id, quantity in rows
    }


def refresh_stock_quotes(
    session: Session,
    on_date: Optional[date] = None,
    write_snapshots: bool = True,
) -> QuoteRefreshResult:
    """刷新所有配置了代码的资产子项行情，并按需写入当日估值快照。"""
    day = on_date or date.today()
    items = list(
        session.scalars(
            select(AccountItem)
            .join(Account, Account.id == AccountItem.account_id)
            .where(
                Account.archived.is_(False),
                AccountItem.symbol.is_not(None),
                AccountItem.symbol != "",
            )
        )
    )
    if not items:
        return QuoteRefreshResult(0, 0, 0, 0)

    quotes: Dict[Tuple[str, str], Quote] = {}
    errors: List[str] = []
    failed = 0
    for symbol, market in sorted({(item.symbol or "", item.market or "CN") for item in items}):
        try:
            quote = fetch_quote(symbol, market)
        except QuoteError as exc:
            failed += 1
            errors.append(f"{symbol}：{exc}")
            continue
        quotes[(symbol, market)] = quote
        save_quote(session, quote)
    session.commit()

    snapshots = 0
    if write_snapshots and quotes:
        lookup = exchange_rates.latest_lookup(session)
        known = set(exchange_rates.latest_rates(session))
        quantities = _quantities(session, [item.id for item in items])
        existing = {
            item_id
            for item_id in session.scalars(
                select(ValuationSnapshot.item_id).where(
                    ValuationSnapshot.item_id.in_([item.id for item in items]),
                    ValuationSnapshot.snapshot_date == day,
                )
            )
        }
        for item in items:
            quote = quotes.get((item.symbol or "", item.market or "CN"))
            quantity = quantities.get(item.id)
            if quote is None or not quantity:
                continue
            if item.id in existing:
                continue
            if item.currency != "CNY" and item.currency not in known:
                continue
            value = quote.price * quantity
            if quote.currency != item.currency:
                rate_from = lookup(quote.currency, day)
                rate_to = lookup(item.currency, day)
                if rate_to == 0:
                    continue
                value = value * rate_from / rate_to
            session.add(
                ValuationSnapshot(
                    account_id=item.account_id,
                    item_id=item.id,
                    snapshot_date=day,
                    value=value.quantize(CENT, rounding=ROUND_HALF_UP),
                    note="实时行情自动写入",
                )
            )
            snapshots += 1
        session.commit()

    return QuoteRefreshResult(
        requested=len(items),
        fetched=len(quotes),
        failed=failed,
        snapshots=snapshots,
        errors=errors,
    )
