"""行情适配器与行情估值测试（全部离线）。"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    VALUATION_AUTO,
    Account,
    AccountItem,
    Base,
    PriceQuote,
    ValuationSnapshot,
)
from app.services import quotes
from app.services.quotes.commodity import (
    POUNDS_PER_TON,
    copper_cents_to_cny_ton,
    parse_domestic_futures,
    parse_sina_futures,
)
from app.services.quotes.fund import parse_fund_payload
from app.services.quotes.gold import parse_gold_api, parse_sina_spot
from app.services.valuation.orchestrator import refresh_all
from app.services.valuation.quote import QuoteUnavailable, QuoteValuator


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as current:
        yield current
    engine.dispose()


def _stock(session, quantity: Decimal = Decimal("100")) -> AccountItem:
    account = Account(name="证券账户", side="asset", currency="CNY")
    item = AccountItem(
        name="贵州茅台",
        category="stock",
        currency="CNY",
        valuation_mode=VALUATION_AUTO,
        symbol="600519",
        market="CN",
        quantity=quantity,
    )
    account.items.append(item)
    session.add(account)
    session.commit()
    return item


def _cache_quote(
    session, price: Decimal, when: datetime, market: str = "CN", symbol: str = "600519"
) -> None:
    session.add(
        PriceQuote(
            symbol=symbol,
            market=market,
            name=symbol,
            price=price,
            currency="CNY",
            quote_time=when,
            source="测试缓存",
        )
    )
    session.commit()


def test_resolve_market_for_fund_and_gold():
    assert quotes.resolve_market("000001", "", "fund") == ("000001", "FUND")
    assert quotes.resolve_market("AU9999", "", "other_asset") == ("AU9999", "GOLD")
    assert quotes.resolve_market("600519", "", "stock") == ("600519", "CN")


def test_resolve_market_for_new_categories():
    assert quotes.resolve_market("", "", "gold") == ("XAU", "GOLD")
    assert quotes.resolve_market("", "", "silver") == ("XAG", "SILVER")
    assert quotes.resolve_market("wti", "", "commodity") == ("CL", "COMMODITY")
    assert quotes.resolve_market("天然气", "", "commodity") == ("NG", "COMMODITY")


def test_parse_commodity_payloads():
    assert parse_sina_futures(
        'var hq_str_hf_CL="87.763,,87.790";'
    ) == Decimal("87.763")
    assert parse_domestic_futures(
        'var hq_str_nf_SC0="原油,150000,623,626,607,620,620,621,620.800,1";'
    ) == Decimal("620.800")


def test_copper_conversion_to_cny_ton():
    result = copper_cents_to_cny_ton(Decimal("612.682"), Decimal("7.1"))
    expected = (
        Decimal("612.682") / Decimal("100") * Decimal("7.1") * POUNDS_PER_TON
    ).quantize(Decimal("0.01"))
    assert result == expected


def test_parse_fund_payload():
    point = parse_fund_payload(
        {
            "Data": {
                "LSJZList": [
                    {"FSRQ": "2026-11-16", "DWJZ": "1.2345"},
                ]
            }
        },
        "000001",
    )
    assert point.price == Decimal("1.2345")
    assert point.currency == "CNY"
    assert point.market == "FUND"
    assert point.quote_time == datetime(2026, 11, 16, 15, 0)


def test_parse_gold_sources():
    assert parse_sina_spot(
        'var hq_str_hf_XAU="3874.40,3879.920,3874.40";'
    ) == Decimal("3874.40")
    assert parse_gold_api({"price": 3878.85}) == Decimal("3878.85")


def test_quote_valuator_uses_fresh_cache(session, monkeypatch):
    item = _stock(session)
    _cache_quote(session, Decimal("1500.00"), datetime.now())

    def fail(*_args, **_kwargs):
        raise quotes.QuoteError("不应联网")

    monkeypatch.setattr(quotes, "get_price", fail)
    result = QuoteValuator().estimate(item, date.today())
    assert result is not None
    assert result.value == Decimal("150000.00")
    assert result.stale is False


def test_quote_valuator_falls_back_to_stale_cache(session, monkeypatch):
    item = _stock(session)
    _cache_quote(session, Decimal("1400.00"), datetime(2020, 1, 2, 15, 0))

    def fail(*_args, **_kwargs):
        raise quotes.QuoteError("网络不可用")

    monkeypatch.setattr(quotes, "get_price", fail)
    result = QuoteValuator().estimate(item, date.today())
    assert result is not None
    assert result.value == Decimal("140000.00")
    assert result.stale is True
    assert "行情已过期" in result.note


def test_quote_valuator_raises_without_cache(session, monkeypatch):
    item = _stock(session)

    def fail(*_args, **_kwargs):
        raise quotes.QuoteError("网络不可用")

    monkeypatch.setattr(quotes, "get_price", fail)
    with pytest.raises(QuoteUnavailable):
        QuoteValuator().estimate(item, date.today())


def test_refresh_all_writes_quote_snapshot(session, monkeypatch):
    item = _stock(session, Decimal("10"))
    quotes.clear_cache()

    def fake_get_price(symbol, market="", category=""):
        return quotes.PricePoint(
            symbol=symbol,
            market=market or "CN",
            price=Decimal("100"),
            currency="CNY",
            quote_time=datetime.now(),
            source="测试行情",
        )

    monkeypatch.setattr(quotes, "get_price", fake_get_price)
    report = refresh_all(session, date.today(), overwrite=True)
    assert report.updated == 1
    assert report.failed == 0
    rows = session.scalars(
        select(ValuationSnapshot).where(ValuationSnapshot.item_id == item.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].value == Decimal("1000.00")
