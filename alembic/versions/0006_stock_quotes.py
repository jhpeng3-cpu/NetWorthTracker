"""add stock symbol and price quotes

Revision ID: 0006_stock_quotes
Revises: 0005_item_currency
Create Date: 2026-11-15

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_stock_quotes"
down_revision: Union[str, None] = "0005_item_currency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.add_column("account_items", sa.Column("symbol", sa.String(32), nullable=True))
    op.add_column("account_items", sa.Column("market", sa.String(8), nullable=True))
    op.create_table(
        "price_quotes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("name", sa.String(64), nullable=True),
        sa.Column("price", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "currency",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'CNY'"),
        ),
        sa.Column("quote_time", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(120), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("symbol", "market", name="uq_quote_symbol_market"),
        sa.CheckConstraint("price >= 0", name="ck_quote_price_nonnegative"),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("price_quotes")
    op.drop_column("account_items", "market")
    op.drop_column("account_items", "symbol")
