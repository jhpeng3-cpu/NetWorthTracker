"""add liability interest rate and start date

Revision ID: 0007_liability_interest
Revises: 0006_stock_quotes
Create Date: 2026-11-15

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_liability_interest"
down_revision: Union[str, None] = "0006_stock_quotes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "account_items",
        sa.Column("interest_rate", sa.Numeric(6, 3), nullable=True),
    )
    op.add_column(
        "account_items",
        sa.Column("interest_start", sa.Date(), nullable=True),
    )
    op.create_check_constraint(
        "ck_item_interest_rate",
        "account_items",
        "interest_rate IS NULL OR (interest_rate >= 0 AND interest_rate <= 100)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_item_interest_rate", "account_items", type_="check")
    op.drop_column("account_items", "interest_start")
    op.drop_column("account_items", "interest_rate")
