"""add per-item valuation configuration fields

Revision ID: 0002_item_valuation
Revises: 0001_initial
Create Date: 2026-11-16

为 account_items 增加按资产类型配置估值所需的扩展字段。
SQLite 支持 ADD COLUMN，降级时使用 batch 模式重建表。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_item_valuation"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_COLUMNS = [
    sa.Column(
        "valuation_mode",
        sa.String(length=16),
        nullable=False,
        server_default=sa.text("'manual'"),
    ),
    sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column("unit", sa.String(length=8), nullable=True),
    sa.Column("principal", sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column("face_value", sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column("maturity_date", sa.Date(), nullable=True),
    sa.Column("pay_frequency", sa.String(length=16), nullable=True),
    sa.Column("compounding", sa.String(length=8), nullable=True),
    sa.Column("early_withdraw_rate", sa.Numeric(precision=6, scale=3), nullable=True),
    sa.Column("price_source", sa.String(length=120), nullable=True),
    sa.Column("next_valuation", sa.Date(), nullable=True),
    sa.Column("asset_meta", sa.JSON(), nullable=True),
]


def upgrade() -> None:
    for column in NEW_COLUMNS:
        op.add_column("account_items", column)


def downgrade() -> None:
    with op.batch_alter_table("account_items") as batch_op:
        for column in reversed(NEW_COLUMNS):
            batch_op.drop_column(column.name)
