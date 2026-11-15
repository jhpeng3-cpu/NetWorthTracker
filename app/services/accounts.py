"""账户服务。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    CATEGORY_LABELS,
    CATEGORIES_BY_SIDE,
    CURRENCY_CODES,
    CURRENCY_LABELS,
    SIDE_LABELS,
    Account,
    ValuationSnapshot,
)
from app.utils.exceptions import AppValidationError


class AccountValidationError(AppValidationError):
    pass


class DuplicateAccountName(AccountValidationError):
    def __init__(self, name: str):
        super().__init__(f"账户名称 “{name}” 已存在（已归档账户也会占用名称），请换一个名称。")


class AccountNotFound(LookupError):
    pass


@dataclass(frozen=True)
class AccountOverview:
    id: int
    name: str
    side: str
    category: str
    currency: str
    note: str
    archived: bool
    latest_value: Optional[Decimal]
    latest_date: Optional[date]

    @property
    def side_label(self) -> str:
        return SIDE_LABELS.get(self.side, self.side)

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    @property
    def display_name(self) -> str:
        suffix = "（已归档）" if self.archived else ""
        return f"{self.name}（{self.side_label}·{self.category_label}）{suffix}"

    @property
    def currency_label(self) -> str:
        return CURRENCY_LABELS.get(self.currency, self.currency)


def _clean_fields(
    name: str,
    side: str,
    category: str,
    currency: str,
    note: str,
) -> tuple:
    clean_name = (name or "").strip()
    if not clean_name:
        raise AccountValidationError("账户名称不能为空。")
    if len(clean_name) > 100:
        raise AccountValidationError("账户名称不能超过 100 个字符。")
    if side not in CATEGORIES_BY_SIDE:
        raise AccountValidationError("账户方向必须是资产或负债。")
    if category not in CATEGORIES_BY_SIDE[side]:
        raise AccountValidationError("账户类别与资产/负债方向不匹配。")
    clean_currency = (currency or "CNY").strip().upper() or "CNY"
    if clean_currency not in CURRENCY_CODES:
        allowed = "、".join(
            f"{CURRENCY_LABELS[code]}（{code}）" for code in CURRENCY_CODES
        )
        raise AccountValidationError(f"币种仅支持：{allowed}。")
    return clean_name, side, category, clean_currency, (note or "").strip() or None


def _is_unique_violation(exc: IntegrityError) -> bool:
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", ())
    errno = args[0] if args and isinstance(args[0], int) else None
    text = str(orig).lower()
    return errno == 1062 or "duplicate entry" in text or "duplicate key" in text


def list_overviews(session: Session, include_archived: bool = False) -> List[AccountOverview]:
    ranked = (
        select(
            ValuationSnapshot.account_id.label("account_id"),
            ValuationSnapshot.value.label("value"),
            ValuationSnapshot.snapshot_date.label("snapshot_date"),
            func.row_number()
            .over(
                partition_by=ValuationSnapshot.account_id,
                order_by=ValuationSnapshot.snapshot_date.desc(),
            )
            .label("rn"),
        )
        .subquery("ranked_snapshots")
    )
    stmt = (
        select(
            Account.id,
            Account.name,
            Account.side,
            Account.category,
            Account.currency,
            Account.note,
            Account.archived,
            ranked.c.value,
            ranked.c.snapshot_date,
        )
        .outerjoin(ranked, and_(ranked.c.account_id == Account.id, ranked.c.rn == 1))
        .order_by(Account.name)
    )
    if not include_archived:
        stmt = stmt.where(Account.archived.is_(False))

    rows = session.execute(stmt).all()
    result = [
        AccountOverview(
            id=row.id,
            name=row.name,
            side=row.side,
            category=row.category,
            currency=row.currency,
            note=row.note or "",
            archived=bool(row.archived),
            latest_value=row.value,
            latest_date=row.snapshot_date,
        )
        for row in rows
    ]
    side_order = {"asset": 0, "liability": 1}
    category_order = {key: index for index, key in enumerate(CATEGORY_LABELS)}
    result.sort(
        key=lambda item: (
            side_order.get(item.side, 9),
            category_order.get(item.category, 99),
            item.name,
        )
    )
    return result


def get_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFound("账户不存在，可能已被删除。")
    return account


def create_account(
    session: Session,
    name: str,
    side: str,
    category: str,
    currency: str = "CNY",
    note: str = "",
) -> int:
    clean = _clean_fields(name, side, category, currency, note)
    account = Account(
        name=clean[0],
        side=clean[1],
        category=clean[2],
        currency=clean[3],
        note=clean[4],
        archived=False,
    )
    session.add(account)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if _is_unique_violation(exc):
            raise DuplicateAccountName(clean[0]) from exc
        raise
    return int(account.id)


def update_account(
    session: Session,
    account_id: int,
    name: str,
    side: str,
    category: str,
    currency: str = "CNY",
    note: str = "",
) -> None:
    clean = _clean_fields(name, side, category, currency, note)
    account = get_account(session, account_id)
    account.name = clean[0]
    account.side = clean[1]
    account.category = clean[2]
    account.currency = clean[3]
    account.note = clean[4]
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if _is_unique_violation(exc):
            raise DuplicateAccountName(clean[0]) from exc
        raise


def set_archived(session: Session, account_id: int, archived: bool) -> None:
    account = get_account(session, account_id)
    account.archived = archived
    session.commit()


def delete_account(session: Session, account_id: int) -> None:
    account = get_account(session, account_id)
    session.delete(account)
    session.commit()


def snapshot_count(session: Session, account_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ValuationSnapshot)
            .where(ValuationSnapshot.account_id == account_id)
        )
        or 0
    )
