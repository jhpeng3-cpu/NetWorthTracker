"""add exchange_rates table

Revision ID: 0002_exchange_rates
Revises: 0001_initial
Create Date: 2026-11-15

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_exchange_rates"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
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
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_exchange_rates_rate_date", "exchange_rates", ["rate_date"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_exchange_rates_rate_date", table_name="exchange_rates")
    op.drop_table("exchange_rates")
