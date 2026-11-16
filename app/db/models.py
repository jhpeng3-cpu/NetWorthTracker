"""SQLAlchemy 模型定义。"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

SIDE_ASSET = "asset"
SIDE_LIABILITY = "liability"

SIDE_LABELS = {SIDE_ASSET: "资产", SIDE_LIABILITY: "负债"}

CATEGORY_LABELS = {
    "fixed_asset": "固定资产",
    "cash": "现金",
    "stock": "股票",
    "bond": "债券",
    "fund": "基金",
    "gold": "黄金",
    "silver": "白银",
    "commodity": "大宗商品",
    "crypto": "加密资产",
    "other_asset": "其他资产",
    "short_term_debt": "短期负债",
    "long_term_debt": "长期负债",
    "other_liability": "其他负债",
}

CATEGORIES_BY_SIDE = {
    SIDE_ASSET: [
        "fixed_asset",
        "cash",
        "stock",
        "bond",
        "fund",
        "gold",
        "silver",
        "commodity",
        "crypto",
        "other_asset",
    ],
    SIDE_LIABILITY: ["short_term_debt", "long_term_debt", "other_liability"],
}

ALL_CATEGORIES = set(CATEGORY_LABELS)

# 估值方式：行情自动 / 计息增值 / 手动估值
VALUATION_AUTO = "auto_quote"
VALUATION_ACCRUAL = "accrual"
VALUATION_MANUAL = "manual"
VALUATION_MODES = (VALUATION_AUTO, VALUATION_ACCRUAL, VALUATION_MANUAL)
VALUATION_MODE_LABELS = {
    VALUATION_AUTO: "行情自动",
    VALUATION_ACCRUAL: "计息增值",
    VALUATION_MANUAL: "手动估值",
}

PAY_FREQUENCIES = ("none", "monthly", "quarterly", "semiannual", "annual", "at_maturity")
PAY_FREQUENCY_LABELS = {
    "none": "不计付",
    "monthly": "每月",
    "quarterly": "每季",
    "semiannual": "每半年",
    "annual": "每年",
    "at_maturity": "到期一次",
}
COMPOUNDING_MODES = ("simple", "compound")
COMPOUNDING_LABELS = {"simple": "单利", "compound": "复利"}

FLOW_TYPES = (
    "deposit",
    "withdraw",
    "buy",
    "sell",
    "interest",
    "dividend",
    "rent",
    "fee",
    "tax",
    "transfer_in",
    "transfer_out",
)
FLOW_TYPE_LABELS = {
    "deposit": "存入",
    "withdraw": "取出",
    "buy": "买入",
    "sell": "卖出",
    "interest": "利息",
    "dividend": "分红",
    "rent": "租金",
    "fee": "费用",
    "tax": "税费",
    "transfer_in": "转入",
    "transfer_out": "转出",
}


def default_valuation_mode(category: str) -> str:
    """按类别给出默认估值方式；用户仍可在表单中修改。"""
    return allowed_valuation_modes(category)[0]


# 各类资产允许的估值方式，首项为默认值；负债单独在服务层强制手动估值。
ALLOWED_VALUATION_MODES = {
    "cash": (VALUATION_ACCRUAL, VALUATION_MANUAL),
    "bond": (VALUATION_ACCRUAL, VALUATION_MANUAL),
    "stock": (VALUATION_AUTO, VALUATION_MANUAL),
    "fund": (VALUATION_AUTO, VALUATION_MANUAL),
    "gold": (VALUATION_AUTO, VALUATION_MANUAL),
    "silver": (VALUATION_AUTO, VALUATION_MANUAL),
    "commodity": (VALUATION_AUTO, VALUATION_MANUAL),
    "crypto": (VALUATION_MANUAL,),
    "fixed_asset": (VALUATION_MANUAL,),
    "other_asset": (VALUATION_MANUAL,),
    "short_term_debt": (VALUATION_MANUAL,),
    "long_term_debt": (VALUATION_MANUAL,),
    "other_liability": (VALUATION_MANUAL,),
}


def allowed_valuation_modes(category: str) -> tuple:
    """类别允许的估值方式，未知类别只允许手动估值。"""
    return ALLOWED_VALUATION_MODES.get(category, (VALUATION_MANUAL,))

BASE_CURRENCY = "CNY"
CURRENCY_LABELS = {
    "CNY": "人民币",
    "USD": "美元",
    "JPY": "日元",
    "MOP": "澳门元",
    "HKD": "港币",
}

CURRENCY_CODES = list(CURRENCY_LABELS)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'CNY'"))
    note: Mapped[Optional[str]] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=func.now()
    )

    items: Mapped[List["AccountItem"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        order_by="AccountItem.sort_order",
    )
    snapshots: Mapped[List["ValuationSnapshot"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_accounts_name"),
        CheckConstraint("side IN ('asset', 'liability')", name="ck_accounts_side"),
    )


class AccountItem(Base):
    """账户下的类别子项，例如「证券账户」下的现金、股票、债券。"""

    __tablename__ = "account_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'CNY'")
    )
    symbol: Mapped[Optional[str]] = mapped_column(String(32))
    market: Mapped[Optional[str]] = mapped_column(String(8))
    interest_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3))
    interest_start: Mapped[Optional[date]] = mapped_column(Date)
    valuation_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'manual'")
    )
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    unit: Mapped[Optional[str]] = mapped_column(String(8))
    principal: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    face_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    maturity_date: Mapped[Optional[date]] = mapped_column(Date)
    pay_frequency: Mapped[Optional[str]] = mapped_column(String(16))
    compounding: Mapped[Optional[str]] = mapped_column(String(8))
    early_withdraw_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3))
    price_source: Mapped[Optional[str]] = mapped_column(String(120))
    next_valuation: Mapped[Optional[date]] = mapped_column(Date)
    asset_meta: Mapped[Optional[dict]] = mapped_column(JSON)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=func.now()
    )

    account: Mapped[Account] = relationship(back_populates="items")
    snapshots: Mapped[List["ValuationSnapshot"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    lots: Mapped[List["PositionLot"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    cash_flows: Mapped[List["CashFlow"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_item_account_name"),
        CheckConstraint(
            "category IN ('fixed_asset','cash','stock','bond','fund','gold','silver',"
            "'commodity','crypto','other_asset',"
            "'short_term_debt','long_term_debt','other_liability')",
            name="ck_item_category",
        ),
        CheckConstraint(
            "interest_rate IS NULL OR (interest_rate >= 0 AND interest_rate <= 100)",
            name="ck_item_interest_rate",
        ),
    )


class ValuationSnapshot(Base):
    __tablename__ = "valuation_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("account_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_date: Mapped[date] = mapped_column(nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=func.now()
    )

    account: Mapped[Account] = relationship(back_populates="snapshots")
    item: Mapped[AccountItem] = relationship(back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint("item_id", "snapshot_date", name="uq_snapshot_item_date"),
        CheckConstraint("value >= 0", name="ck_snapshot_value_nonnegative"),
        Index("ix_valuation_snapshots_snapshot_date", "snapshot_date"),
    )


class ExchangeRate(Base):
    """每日汇率：1 单位外币兑人民币金额；CNY 为基准不入库。"""

    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False)
    rate_date: Mapped[date] = mapped_column(nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("currency_code", "rate_date", name="uq_rate_code_date"),
        CheckConstraint("rate > 0", name="ck_rate_positive"),
        Index("ix_exchange_rates_rate_date", "rate_date"),
    )


class PriceQuote(Base):
    """股票/基金最新行情缓存：每个代码只保留最近一次成功报价。"""

    __tablename__ = "price_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(64))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'CNY'")
    )
    quote_time: Mapped[Optional[datetime]] = mapped_column(DateTime())
    source: Mapped[Optional[str]] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("symbol", "market", name="uq_quote_symbol_market"),
        CheckConstraint("price >= 0", name="ck_quote_price_nonnegative"),
    )


class PositionLot(Base):
    """成本批次：记录某个子项的一次买入，用于计算持仓盈亏。"""

    __tablename__ = "position_lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("account_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'CNY'")
    )
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=func.now()
    )

    item: Mapped[AccountItem] = relationship(back_populates="lots")

    @property
    def total_cost(self) -> Decimal:
        return (self.quantity * self.unit_cost + self.fee).quantize(Decimal("0.01"))

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_lot_quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="ck_lot_unit_cost_nonnegative"),
        CheckConstraint("fee >= 0", name="ck_lot_fee_nonnegative"),
        Index("ix_position_lots_item_date", "item_id", "trade_date"),
    )


class CashFlow(Base):
    """子项现金流：利息、分红、租金、费用、买卖与转入转出。

    金额始终以正数保存，方向由 flow_type 表达；市值与收益因此可以分离。
    """

    __tablename__ = "cash_flows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("account_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    flow_date: Mapped[date] = mapped_column(Date, nullable=False)
    flow_type: Mapped[str] = mapped_column(String(24), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'CNY'")
    )
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default=text("0")
    )
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=func.now()
    )

    item: Mapped[AccountItem] = relationship(back_populates="cash_flows")

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_flow_amount_nonnegative"),
        CheckConstraint("fee >= 0", name="ck_flow_fee_nonnegative"),
        CheckConstraint(
            "flow_type IN (" + ",".join(f"'{name}'" for name in FLOW_TYPES) + ")",
            name="ck_flow_type",
        ),
        Index("ix_cash_flows_item_date", "item_id", "flow_date"),
    )
