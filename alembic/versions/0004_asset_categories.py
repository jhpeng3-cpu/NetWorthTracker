"""add precious metal, commodity and crypto categories

Revision ID: 0004_asset_categories
Revises: 0003_cash_flows
Create Date: 2026-11-16

扩展资产类别约束：黄金、白银、大宗商品、加密资产。
SQLite 需重建表以替换 CHECK 约束；降级时把新类别映射为其他资产，保证成功。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0004_asset_categories"
down_revision: Union[str, None] = "0003_cash_flows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_CATEGORIES = (
    "fixed_asset",
    "cash",
    "stock",
    "bond",
    "fund",
    "gold",
    "silver",
    "commodity",
    "crypto",
    "other_asset",
    "short_term_debt",
    "long_term_debt",
    "other_liability",
)
OLD_CATEGORIES = (
    "fixed_asset",
    "cash",
    "stock",
    "bond",
    "fund",
    "other_asset",
    "short_term_debt",
    "long_term_debt",
    "other_liability",
)
NEW_ASSET_CATEGORIES = ("gold", "silver", "commodity", "crypto")


def _check_sql(categories: Sequence[str]) -> str:
    return "category IN (" + ",".join(f"'{name}'" for name in categories) + ")"


def upgrade() -> None:
    with op.batch_alter_table("account_items", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_item_category", type_="check")
        batch_op.create_check_constraint(
            "ck_item_category", _check_sql(NEW_CATEGORIES)
        )


def downgrade() -> None:
    names = ",".join(f"'{name}'" for name in NEW_ASSET_CATEGORIES)
    op.execute(
        f"UPDATE account_items SET category = 'other_asset' "
        f"WHERE category IN ({names})"
    )
    with op.batch_alter_table("account_items", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_item_category", type_="check")
        batch_op.create_check_constraint(
            "ck_item_category", _check_sql(OLD_CATEGORIES)
        )
