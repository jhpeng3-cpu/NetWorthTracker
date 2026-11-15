"""add account_items and per-item snapshots

Revision ID: 0003_account_items
Revises: 0002_exchange_rates
Create Date: 2026-11-15

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_account_items"
down_revision: Union[str, None] = "0002_exchange_rates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}

# 迁移内固化中文名，避免依赖应用常量的后续变化
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


def upgrade() -> None:
    op.create_table(
        "account_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('fixed_asset','cash','stock','bond','fund','other_asset',"
            "'short_term_debt','long_term_debt','other_liability')",
            name="ck_item_category",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "name", name="uq_item_account_name"),
        **TABLE_OPTIONS,
    )

    # 每个既有账户转换出一个同名类别子项，保留原类别
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, category FROM accounts")).fetchall()
    for account_id, category in rows:
        bind.execute(
            sa.text(
                "INSERT INTO account_items (account_id, name, category, sort_order) "
                "VALUES (:account_id, :name, :category, 0)"
            ),
            {
                "account_id": account_id,
                "name": CATEGORY_LABELS.get(category, category),
                "category": category,
            },
        )

    # 快照挂到子项上
    op.add_column(
        "valuation_snapshots", sa.Column("item_id", sa.BigInteger(), nullable=True)
    )
    op.execute(
        "UPDATE valuation_snapshots AS s "
        "JOIN account_items AS i ON i.account_id = s.account_id "
        "SET s.item_id = i.id"
    )
    op.alter_column(
        "valuation_snapshots", "item_id", existing_type=sa.BigInteger(), nullable=False
    )
    # 原唯一索引被 account_id 外键复用，先补独立索引才能删除
    op.create_index(
        "ix_valuation_snapshots_account_id", "valuation_snapshots", ["account_id"]
    )
    op.drop_constraint("uq_snapshot_account_date", "valuation_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_snapshot_item_date", "valuation_snapshots", ["item_id", "snapshot_date"]
    )
    op.create_foreign_key(
        "fk_snapshots_item",
        "valuation_snapshots",
        "account_items",
        ["item_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 类别改由子项承载
    op.drop_column("accounts", "category")


def downgrade() -> None:
    op.add_column(
        "accounts", sa.Column("category", sa.String(length=30), nullable=True)
    )
    op.execute(
        "UPDATE accounts AS a JOIN account_items AS i ON i.account_id = a.id "
        "SET a.category = i.category"
    )
    op.alter_column(
        "accounts", "category", existing_type=sa.String(length=30), nullable=False
    )

    op.drop_constraint("fk_snapshots_item", "valuation_snapshots", type_="foreignkey")
    op.drop_constraint("uq_snapshot_item_date", "valuation_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_snapshot_account_date", "valuation_snapshots", ["account_id", "snapshot_date"]
    )
    op.drop_index("ix_valuation_snapshots_account_id", table_name="valuation_snapshots")
    op.drop_column("valuation_snapshots", "item_id")
    op.drop_table("account_items")
