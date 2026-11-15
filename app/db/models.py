"""SQLAlchemy 模型定义。"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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
    "other_asset": "其他资产",
    "short_term_debt": "短期负债",
    "long_term_debt": "长期负债",
    "other_liability": "其他负债",
}

CATEGORIES_BY_SIDE = {
    SIDE_ASSET: ["fixed_asset", "cash", "stock", "bond", "fund", "other_asset"],
    SIDE_LIABILITY: ["short_term_debt", "long_term_debt", "other_liability"],
}

ALL_CATEGORIES = set(CATEGORY_LABELS)

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

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )


class AccountItem(Base):
    """账户下的类别子项，例如「证券账户」下的现金、股票、债券。"""

    __tablename__ = "account_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger,
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

    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_item_account_name"),
        CheckConstraint(
            "category IN ('fixed_asset','cash','stock','bond','fund','other_asset',"
            "'short_term_debt','long_term_debt','other_liability')",
            name="ck_item_category",
        ),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )


class ValuationSnapshot(Base):
    __tablename__ = "valuation_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[int] = mapped_column(
        BigInteger,
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
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )


class ExchangeRate(Base):
    """每日汇率：1 单位外币兑人民币金额；CNY 为基准不入库。"""

    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )


class PriceQuote(Base):
    """股票/基金最新行情缓存：每个代码只保留最近一次成功报价。"""

    __tablename__ = "price_quotes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )


class PositionLot(Base):
    """成本批次：记录某个子项的一次买入，用于计算持仓盈亏。"""

    __tablename__ = "position_lots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        BigInteger,
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
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )
