"""add currency to account_items

Revision ID: 0005_item_currency
Revises: 0004_position_lots
Create Date: 2026-11-15

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_item_currency"
down_revision: Union[str, None] = "0004_position_lots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "account_items",
        sa.Column(
            "currency",
            sa.String(10),
            server_default=sa.text("'CNY'"),
            nullable=False,
        ),
    )
    # 既有子项继承所属账户的币种，保持历史数据含义不变。
    op.execute(
        "UPDATE account_items ai JOIN accounts a ON a.id = ai.account_id "
        "SET ai.currency = a.currency"
    )


def downgrade() -> None:
    op.drop_column("account_items", "currency")
