"""create cash_flows table

Revision ID: 0003_cash_flows
Revises: 0002_item_valuation
Create Date: 2026-11-16

现金流与市值分离：利息、分红、租金、费用、买卖与转入转出。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_cash_flows"
down_revision: Union[str, None] = "0002_item_valuation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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


def upgrade() -> None:
    op.create_table(
        "cash_flows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("flow_date", sa.Date(), nullable=False),
        sa.Column("flow_type", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "currency", sa.String(length=10), server_default=sa.text("'CNY'"), nullable=False
        ),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column(
            "fee", sa.Numeric(precision=18, scale=2), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("amount >= 0", name="ck_flow_amount_nonnegative"),
        sa.CheckConstraint("fee >= 0", name="ck_flow_fee_nonnegative"),
        sa.CheckConstraint(
            "flow_type IN (" + ",".join(f"'{name}'" for name in FLOW_TYPES) + ")",
            name="ck_flow_type",
        ),
        sa.ForeignKeyConstraint(["item_id"], ["account_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cash_flows_item_date", "cash_flows", ["item_id", "flow_date"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_cash_flows_item_date", table_name="cash_flows")
    op.drop_table("cash_flows")
