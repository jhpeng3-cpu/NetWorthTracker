"""initial schema: accounts and valuation_snapshots

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-15

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("currency", sa.String(length=10), server_default=sa.text("'CNY'"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("side IN ('asset', 'liability')", name="ck_accounts_side"),
        sa.CheckConstraint(
            "category IN ('fixed_asset','cash','stock','bond','fund','other_asset',"
            "'short_term_debt','long_term_debt','other_liability')",
            name="ck_accounts_category",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_accounts_name"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "valuation_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "snapshot_date", name="uq_snapshot_account_date"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_valuation_snapshots_snapshot_date",
        "valuation_snapshots",
        ["snapshot_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_valuation_snapshots_snapshot_date", table_name="valuation_snapshots")
    op.drop_table("valuation_snapshots")
    op.drop_table("accounts")
