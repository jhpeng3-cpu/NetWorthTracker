"""类别与估值方式矩阵测试。"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    CATEGORIES_BY_SIDE,
    CATEGORY_LABELS,
    VALUATION_ACCRUAL,
    VALUATION_AUTO,
    VALUATION_MANUAL,
    AccountItem,
    Base,
    allowed_valuation_modes,
    default_valuation_mode,
)
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


def test_new_categories_registered():
    for key in ("gold", "silver", "commodity", "crypto"):
        assert key in CATEGORY_LABELS
        assert key in CATEGORIES_BY_SIDE["asset"]


def test_allowed_valuation_modes_by_category():
    assert allowed_valuation_modes("gold") == (VALUATION_AUTO, VALUATION_MANUAL)
    assert allowed_valuation_modes("silver") == (VALUATION_AUTO, VALUATION_MANUAL)
    assert allowed_valuation_modes("commodity") == (VALUATION_AUTO, VALUATION_MANUAL)
    assert allowed_valuation_modes("crypto") == (VALUATION_MANUAL,)
    assert allowed_valuation_modes("cash") == (VALUATION_ACCRUAL, VALUATION_MANUAL)
    assert allowed_valuation_modes("fixed_asset") == (VALUATION_MANUAL,)
    assert default_valuation_mode("gold") == VALUATION_AUTO
    assert default_valuation_mode("cash") == VALUATION_ACCRUAL


def test_service_normalizes_precious_metal_and_commodity(session):
    account_id = accounts.create_account(
        session,
        name="另类资产",
        side="asset",
        items=[
            accounts.ItemInput(
                name="黄金",
                category="gold",
                valuation_mode="auto_quote",
                quantity=Decimal("10"),
            ),
            accounts.ItemInput(
                name="白银",
                category="silver",
                valuation_mode="auto_quote",
                quantity=Decimal("100"),
            ),
            accounts.ItemInput(
                name="原油",
                category="commodity",
                valuation_mode="auto_quote",
                symbol="wti",
                quantity=Decimal("20"),
            ),
            accounts.ItemInput(
                name="比特币",
                category="crypto",
                valuation_mode="manual",
            ),
        ],
    )
    items = {
        row.name: row
        for row in session.query(AccountItem)
        .filter(AccountItem.account_id == account_id)
        .all()
    }
    assert (items["黄金"].symbol, items["黄金"].market) == ("XAU", "GOLD")
    assert (items["白银"].symbol, items["白银"].market) == ("XAG", "SILVER")
    assert (items["原油"].symbol, items["原油"].market) == ("CL", "COMMODITY")
    assert items["比特币"].valuation_mode == "manual"


@pytest.mark.parametrize(
    "category,mode",
    [
        ("fixed_asset", "accrual"),
        ("cash", "auto_quote"),
        ("crypto", "auto_quote"),
        ("stock", "accrual"),
    ],
)
def test_service_rejects_unsupported_mode(session, category, mode):
    with pytest.raises(accounts.AccountValidationError):
        accounts.create_account(
            session,
            name="非法组合",
            side="asset",
            items=[
                accounts.ItemInput(
                    name="测试",
                    category=category,
                    valuation_mode=mode,
                )
            ],
        )
