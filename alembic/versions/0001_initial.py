"""initial schema (SQLite)

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-15

SQLite 不支持多数 ALTER TABLE 操作，因此此处直接定义最终表结构。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORY_CHECK = (
    "category IN ('fixed_asset','cash','stock','bond','fund','other_asset',"
    "'short_term_debt','long_term_debt','other_liability')"
)


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column(
            "currency", sa.String(length=10), server_default=sa.text("'CNY'"), nullable=False
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("side IN ('asset', 'liability')", name="ck_accounts_side"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_accounts_name"),
    )

    op.create_table(
        "account_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column(
            "currency", sa.String(length=10), server_default=sa.text("'CNY'"), nullable=False
        ),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("market", sa.String(length=8), nullable=True),
        sa.Column("interest_rate", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("interest_start", sa.Date(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(CATEGORY_CHECK, name="ck_item_category"),
        sa.CheckConstraint(
            "interest_rate IS NULL OR (interest_rate >= 0 AND interest_rate <= 100)",
            name="ck_item_interest_rate",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "name", name="uq_item_account_name"),
    )

    op.create_table(
        "valuation_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("value >= 0", name="ck_snapshot_value_nonnegative"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["account_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "snapshot_date", name="uq_snapshot_item_date"),
    )
    op.create_index(
        "ix_valuation_snapshots_snapshot_date",
        "valuation_snapshots",
        ["snapshot_date"],
        unique=False,
    )

    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("currency_code", sa.String(length=10), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("rate > 0", name="ck_rate_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("currency_code", "rate_date", name="uq_rate_code_date"),
    )
    op.create_index("ix_exchange_rates_rate_date", "exchange_rates", ["rate_date"], unique=False)

    op.create_table(
        "price_quotes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column(
            "currency", sa.String(length=10), server_default=sa.text("'CNY'"), nullable=False
        ),
        sa.Column("quote_time", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("price >= 0", name="ck_quote_price_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "market", name="uq_quote_symbol_market"),
    )

    op.create_table(
        "position_lots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("fee", sa.Numeric(precision=18, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "currency", sa.String(length=10), server_default=sa.text("'CNY'"), nullable=False
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="ck_lot_quantity_positive"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_lot_unit_cost_nonnegative"),
        sa.CheckConstraint("fee >= 0", name="ck_lot_fee_nonnegative"),
        sa.ForeignKeyConstraint(["item_id"], ["account_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_position_lots_item_date", "position_lots", ["item_id", "trade_date"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_position_lots_item_date", table_name="position_lots")
    op.drop_table("position_lots")
    op.drop_table("price_quotes")
    op.drop_index("ix_exchange_rates_rate_date", table_name="exchange_rates")
    op.drop_table("exchange_rates")
    op.drop_index("ix_valuation_snapshots_snapshot_date", table_name="valuation_snapshots")
    op.drop_table("valuation_snapshots")
    op.drop_table("account_items")
    op.drop_table("accounts")
