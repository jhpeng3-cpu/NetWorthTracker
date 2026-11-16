"""现金流服务单元测试。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Account, AccountItem, Base
from app.services import cash_flows


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


@pytest.fixture()
def item(session):
    account = Account(name="现金账户", side="asset", currency="CNY")
    child = AccountItem(name="活期", category="cash")
    account.items.append(child)
    session.add(account)
    session.commit()
    return child


def test_add_and_list_flows(session, item):
    cash_flows.add_flow(
        session, item.id, date(2026, 3, 1), "interest", Decimal("12.34")
    )
    cash_flows.add_flow(
        session, item.id, date(2026, 4, 1), "interest", Decimal("10.00")
    )
    cash_flows.add_flow(
        session, item.id, date(2026, 4, 2), "fee", Decimal("1.50"), note="账户管理费"
    )
    rows = cash_flows.list_flows(session, item.id)
    assert [row.flow_type for row in rows] == ["interest", "interest", "fee"]
    assert rows[0].amount == Decimal("12.34")


def test_summarize_by_type(session, item):
    cash_flows.add_flow(
        session, item.id, date(2026, 3, 1), "interest", Decimal("12.34")
    )
    cash_flows.add_flow(
        session, item.id, date(2026, 4, 1), "interest", Decimal("10.00")
    )
    totals = cash_flows.summarize(session, item.id)
    assert totals["interest"].total == Decimal("22.34")
    assert totals["interest"].count == 2


def test_invalid_flow_type_rejected(session, item):
    with pytest.raises(cash_flows.CashFlowError):
        cash_flows.add_flow(
            session, item.id, date(2026, 3, 1), "unknown", Decimal("1")
        )


def test_delete_flow(session, item):
    flow = cash_flows.add_flow(
        session, item.id, date(2026, 3, 1), "interest", Decimal("1")
    )
    assert cash_flows.delete_flow(session, flow.id) is True
    assert cash_flows.list_flows(session, item.id) == []
