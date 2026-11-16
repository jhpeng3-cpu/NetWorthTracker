"""行情自动估值：数量 × 最新价 × 汇率。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from app.db.models import VALUATION_AUTO, AccountItem, PositionLot, PriceQuote
from app.services import exchange_rates, quotes
from app.services.valuation.base import ValuationResult, Valuator

CENT = Decimal("0.01")


class QuoteUnavailable(Exception):
    """行情与缓存均不可用。"""


class QuoteValuator(Valuator):
    mode = VALUATION_AUTO

    def estimate(
        self, item: AccountItem, on_date: date
    ) -> Optional[ValuationResult]:
        session = object_session(item)
        quantity = self._quantity(session, item)
        if quantity is None or quantity <= 0:
            raise QuoteUnavailable("未填写数量，也未录入成本批次")

        symbol, market = quotes.resolve_market(
            item.symbol or "", item.market or "", item.category
        )
        if not symbol:
            raise QuoteUnavailable("未填写行情代码")

        cached = self._cached(session, symbol, market)
        stale = False
        if (
            cached is not None
            and cached.quote_time is not None
            and cached.quote_time.date() >= on_date
        ):
            point = cached
        else:
            try:
                point = quotes.get_price(symbol, market, item.category)
                self._save(session, point)
            except quotes.QuoteError as exc:
                if cached is None:
                    raise QuoteUnavailable(f"行情获取失败：{exc}") from exc
                stale = True
                point = cached

        price = Decimal(str(point.price))
        currency = (point.currency or "CNY").upper()
        value = price * quantity
        if currency != (item.currency or "CNY").upper():
            if session is None:
                raise QuoteUnavailable("缺少汇率信息，无法折算币种")
            lookup = exchange_rates.latest_lookup(session)
            value = value * lookup(currency, on_date) / lookup(item.currency, on_date)
        value = value.quantize(CENT, rounding=ROUND_HALF_UP)

        source = getattr(point, "source", "") or ""
        quote_time = getattr(point, "quote_time", None)
        note = source
        if quote_time is not None:
            note = f"{source} · {quote_time:%Y-%m-%d %H:%M}"
        unit = getattr(point, "unit", "") or ""
        if unit:
            note += f" · {unit}"
        if stale:
            note = "行情已过期 · " + note
        return ValuationResult(
            value=value,
            currency=item.currency or "CNY",
            note=note,
            stale=stale,
            as_of=on_date,
        )

    @staticmethod
    def _quantity(session: Optional[Session], item: AccountItem) -> Optional[Decimal]:
        if item.quantity is not None:
            return Decimal(str(item.quantity))
        if session is None:
            return None
        total = session.scalar(
            select(func.sum(PositionLot.quantity)).where(
                PositionLot.item_id == item.id
            )
        )
        return Decimal(str(total)) if total is not None else None

    @staticmethod
    def _cached(
        session: Optional[Session], symbol: str, market: str
    ) -> Optional[PriceQuote]:
        if session is None:
            return None
        return session.scalar(
            select(PriceQuote).where(
                PriceQuote.symbol == symbol,
                PriceQuote.market == market,
            )
        )

    @staticmethod
    def _save(session: Optional[Session], point) -> None:  # noqa: ANN001
        if session is None:
            return
        quotes.save_quote(
            session,
            quotes.Quote(
                symbol=point.symbol,
                market=point.market,
                name=getattr(point, "name", "") or point.symbol,
                price=point.price,
                currency=point.currency,
                quote_time=point.quote_time,
                source=point.source,
            ),
        )
