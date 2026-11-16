"""外币子项现价显示最新汇率。"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, ExchangeRate, PriceQuote
from app.services import accounts


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


def test_foreign_cash_uses_latest_rate(session):
    accounts.create_account(
        session,
        name="外币现金",
        side="asset",
        items=[
            accounts.ItemInput(
                name="美元现金",
                category="cash",
                valuation_mode="manual",
                currency="USD",
            ),
            accounts.ItemInput(
                name="人民币现金",
                category="cash",
                valuation_mode="manual",
                currency="CNY",
            ),
        ],
    )
    session.add(
        ExchangeRate(
            currency_code="USD",
            rate_date=date(2026, 11, 15),
            rate=Decimal("7.1000"),
            source="测试",
        )
    )
    session.add(
        ExchangeRate(
            currency_code="USD",
            rate_date=date(2026, 11, 16),
            rate=Decimal("7.1234"),
            source="测试",
        )
    )
    session.commit()

    overview = accounts.list_overviews(session)[0]
    items = {row.name: row for row in overview.items}
    usd = items["美元现金"]
    cny = items["人民币现金"]
    assert usd.price == Decimal("7.123400")
    assert usd.price_currency == "CNY"
    assert usd.price_at == datetime(2026, 11, 16, 0, 0)
    assert cny.price is None


def test_foreign_market_item_without_quote_has_no_rate_fallback(session):
    accounts.create_account(
        session,
        name="美股账户",
        side="asset",
        currency="USD",
        items=[
            accounts.ItemInput(
                name="苹果",
                category="stock",
                valuation_mode="auto_quote",
                symbol="AAPL",
                market="US",
                quantity=Decimal("10"),
            )
        ],
    )
    session.add(
        ExchangeRate(
            currency_code="USD",
            rate_date=date(2026, 11, 16),
            rate=Decimal("7.1234"),
            source="测试",
        )
    )
    session.commit()
    item = accounts.list_overviews(session)[0].items[0]
    assert item.price is None


def test_foreign_quote_takes_priority_over_rate(session):
    accounts.create_account(
        session,
        name="美股账户",
        side="asset",
        currency="USD",
        items=[
            accounts.ItemInput(
                name="苹果",
                category="stock",
                valuation_mode="auto_quote",
                symbol="AAPL",
                market="US",
                quantity=Decimal("10"),
            )
        ],
    )
    session.add(
        ExchangeRate(
            currency_code="USD",
            rate_date=date(2026, 11, 16),
            rate=Decimal("7.1234"),
            source="测试",
        )
    )
    session.add(
        PriceQuote(
            symbol="AAPL",
            market="US",
            name="Apple",
            price=Decimal("200.00"),
            currency="USD",
            quote_time=datetime(2026, 11, 16, 9, 30),
            source="测试",
        )
    )
    session.commit()

    item = accounts.list_overviews(session)[0].items[0]
    assert item.price == Decimal("200.00")
    assert item.price_currency == "USD"
    assert item.price_at == datetime(2026, 11, 16, 9, 30)
