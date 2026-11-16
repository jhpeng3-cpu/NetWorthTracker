"""估值与计息单元测试。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    VALUATION_ACCRUAL,
    VALUATION_AUTO,
    VALUATION_MANUAL,
    Account,
    AccountItem,
    Base,
    ValuationSnapshot,
)
from app.services import quotes
from app.services.valuation.accrual import (
    AccrualValuator,
    bond_accrued_interest,
    bond_full_price,
    compound_value,
    deposit_value,
    early_withdraw_value,
    simple_interest,
)
from app.services.valuation.manual import ManualValuator, overdue_manual_items
from app.services.valuation.orchestrator import refresh_all


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


def test_simple_interest_rounds_half_up():
    # 10000 × 4.25% × 60 / 365 = 69.8630...
    assert simple_interest(
        Decimal("10000"), Decimal("4.25"), date(2026, 1, 1), date(2026, 3, 2)
    ) == Decimal("69.86")


def test_deposit_value_stops_at_maturity():
    value = deposit_value(
        Decimal("100000"),
        Decimal("3"),
        date(2026, 1, 1),
        date(2027, 6, 1),
        maturity_date=date(2027, 1, 1),
    )
    assert value == Decimal("103000.00")


def test_compound_quarterly_rolls_periods():
    value = compound_value(
        Decimal("10000"),
        Decimal("4"),
        date(2026, 1, 1),
        date(2026, 10, 1),
        "quarterly",
    )
    assert value == Decimal("10303.01")


def test_early_withdraw_uses_early_rate():
    value = early_withdraw_value(
        Decimal("100000"), Decimal("0.35"), date(2026, 1, 1), date(2026, 4, 11)
    )
    assert value == Decimal("100095.89")


def test_bond_accrued_interest_and_full_price():
    interest = bond_accrued_interest(
        Decimal("10000"), Decimal("3.65"), date(2026, 1, 1), date(2026, 4, 1)
    )
    assert interest == Decimal("90.00")
    assert bond_full_price(
        Decimal("10000"), Decimal("3.65"), date(2026, 1, 1), date(2026, 4, 1)
    ) == Decimal("10090.00")


def test_accrual_valuator_uses_date_principle():
    item = AccountItem(
        name="定期存款",
        category="cash",
        currency="CNY",
        valuation_mode=VALUATION_ACCRUAL,
        principal=Decimal("100000"),
        interest_rate=Decimal("3"),
        interest_start=date(2026, 1, 1),
        maturity_date=date(2027, 1, 1),
    )
    result = AccrualValuator().estimate(item, date(2026, 7, 1))
    assert result is not None
    # 100000 + 100000 × 3% × 181 / 365
    assert result.value == Decimal("101487.67")


def test_manual_valuator_marks_stale(session):
    account = Account(name="自住房产", side="asset", currency="CNY")
    item = AccountItem(
        name="房产",
        category="fixed_asset",
        currency="CNY",
        valuation_mode=VALUATION_MANUAL,
        next_valuation=date(2026, 5, 1),
    )
    account.items.append(item)
    session.add(account)
    session.commit()
    session.add(
        ValuationSnapshot(
            account_id=account.id,
            item_id=item.id,
            snapshot_date=date(2026, 4, 1),
            value=Decimal("1000000.00"),
        )
    )
    session.commit()

    result = ManualValuator().estimate(item, date(2026, 6, 1))
    assert result is not None
    assert result.value == Decimal("1000000.00")
    assert result.stale is True
    assert "待更新" in result.note


def test_overdue_manual_items_skips_updated_items(session):
    account = Account(name="房产账户", side="asset", currency="CNY")
    due = AccountItem(
        name="未更新房产",
        category="fixed_asset",
        valuation_mode=VALUATION_MANUAL,
        next_valuation=date(2026, 5, 1),
    )
    updated = AccountItem(
        name="已更新房产",
        category="fixed_asset",
        valuation_mode=VALUATION_MANUAL,
        next_valuation=date(2026, 5, 1),
    )
    account.items.extend([due, updated])
    session.add(account)
    session.commit()
    session.add_all(
        [
            ValuationSnapshot(
                account_id=account.id,
                item_id=due.id,
                snapshot_date=date(2026, 4, 1),
                value=Decimal("100"),
            ),
            ValuationSnapshot(
                account_id=account.id,
                item_id=updated.id,
                snapshot_date=date(2026, 5, 15),
                value=Decimal("200"),
            ),
        ]
    )
    session.commit()

    rows = overdue_manual_items(session, date(2026, 6, 1))
    assert [row.item_name for row in rows] == ["未更新房产"]


def test_asset_meta_json_roundtrip(session):
    account = Account(name="保单账户", side="asset", currency="CNY")
    item = AccountItem(
        name="保单",
        category="other_asset",
        valuation_mode=VALUATION_MANUAL,
        asset_meta={"plan": "10 年", "premium": "5000.00"},
    )
    account.items.append(item)
    session.add(account)
    session.commit()
    session.expire_all()
    stored = session.get(AccountItem, item.id)
    assert stored is not None
    assert stored.asset_meta == {"plan": "10 年", "premium": "5000.00"}


def test_orchestrator_updates_accrual_and_reports_quote_failure(session, monkeypatch):
    account = Account(name="测试账户", side="asset", currency="CNY")
    deposit = AccountItem(
        name="定期存款",
        category="cash",
        valuation_mode=VALUATION_ACCRUAL,
        principal=Decimal("10000"),
        interest_rate=Decimal("3.65"),
        interest_start=date(2026, 1, 1),
    )
    stock = AccountItem(
        name="股票",
        category="stock",
        valuation_mode=VALUATION_AUTO,
        symbol="600519",
        market="CN",
        quantity=Decimal("100"),
    )
    account.items.extend([deposit, stock])
    session.add(account)
    session.commit()

    def fail(*_args, **_kwargs):
        raise quotes.QuoteError("测试环境离线")

    monkeypatch.setattr(quotes, "get_price", fail)
    report = refresh_all(session, date(2026, 4, 1), overwrite=True)
    assert report.updated == 1
    assert report.failed == 1
    saved = session.scalars(
        select(ValuationSnapshot).where(ValuationSnapshot.item_id == deposit.id)
    ).all()
    assert len(saved) == 1
    assert saved[0].value == Decimal("10090.00")
