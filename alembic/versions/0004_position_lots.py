"""add position_lots

Revision ID: 0004_position_lots
Revises: 0003_account_items
Create Date: 2026-11-15

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_position_lots"
down_revision: Union[str, None] = "0003_account_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.create_table(
        "position_lots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("fee", sa.Numeric(18, 2), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "currency", sa.String(10), server_default=sa.text("'CNY'"), nullable=False
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
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_position_lots_item_date", "position_lots", ["item_id", "trade_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_position_lots_item_date", table_name="position_lots")
    op.drop_table("position_lots")
