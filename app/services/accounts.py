"""账户服务：账户及其类别子项。

一个账户可包含多个类别子项（如证券账户下的现金、股票、债券），
估值快照按子项记录，账户金额为子项之和。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence

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
    AccountItem,
    ValuationSnapshot,
)
from app.services import quotes
from app.utils.exceptions import AppError, AppValidationError


class AccountValidationError(AppValidationError):
    pass


class DuplicateAccountName(AccountValidationError):
    def __init__(self, name: str):
        super().__init__(f"账户名称 “{name}” 已存在（已归档账户也会占用名称），请换一个名称。")


class AccountNotFound(AppError, LookupError):
    pass


@dataclass(frozen=True)
class ItemInput:
    """新增 / 编辑账户时提交的类别子项。id 为空表示新建。"""

    name: str
    category: str
    id: Optional[int] = None
    currency: Optional[str] = None
    symbol: Optional[str] = None
    market: Optional[str] = None
    interest_rate: Optional[Decimal] = None
    interest_start: Optional[date] = None


@dataclass(frozen=True)
class ItemOverview:
    id: int
    account_id: int
    name: str
    category: str
    latest_value: Optional[Decimal]
    latest_date: Optional[date]
    currency: str = "CNY"
    symbol: str = ""
    market: str = ""
    price: Optional[Decimal] = None
    price_currency: str = ""
    price_at: Optional[datetime] = None
    interest_rate: Optional[Decimal] = None
    interest_start: Optional[date] = None

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    @property
    def currency_label(self) -> str:
        return CURRENCY_LABELS.get(self.currency, self.currency)


@dataclass(frozen=True)
class AccountOverview:
    id: int
    name: str
    side: str
    currency: str
    note: str
    archived: bool
    latest_value: Optional[Decimal]
    latest_date: Optional[date]
    items: List[ItemOverview] = field(default_factory=list)

    @property
    def side_label(self) -> str:
        return SIDE_LABELS.get(self.side, self.side)

    @property
    def category_label(self) -> str:
        labels: List[str] = []
        for item in self.items:
            if item.category_label not in labels:
                labels.append(item.category_label)
        return "、".join(labels) if labels else "—"

    @property
    def display_name(self) -> str:
        suffix = "（已归档）" if self.archived else ""
        return f"{self.name}（{self.side_label}·{self.category_label}）{suffix}"

    @property
    def currency_label(self) -> str:
        return CURRENCY_LABELS.get(self.currency, self.currency)

    @property
    def item_currencies(self) -> List[str]:
        codes: List[str] = []
        for item in self.items:
            if item.currency not in codes:
                codes.append(item.currency)
        return codes

    @property
    def display_currency(self) -> str:
        codes = self.item_currencies
        if len(codes) == 1:
            return codes[0]
        return "MIXED"


def _clean_fields(name: str, side: str, currency: str, note: str) -> tuple:
    clean_name = (name or "").strip()
    if not clean_name:
        raise AccountValidationError("账户名称不能为空。")
    if len(clean_name) > 100:
        raise AccountValidationError("账户名称不能超过 100 个字符。")
    if side not in CATEGORIES_BY_SIDE:
        raise AccountValidationError("账户方向必须是资产或负债。")
    clean_currency = (currency or "CNY").strip().upper() or "CNY"
    if clean_currency not in CURRENCY_CODES:
        allowed = "、".join(
            f"{CURRENCY_LABELS[code]}（{code}）" for code in CURRENCY_CODES
        )
        raise AccountValidationError(f"币种仅支持：{allowed}。")
    return clean_name, side, clean_currency, (note or "").strip() or None


def _clean_interest(
    side: str, rate: Optional[Decimal], start: Optional[date]
) -> tuple:
    """负债子项的年利率与计息起始日；资产子项忽略这两个字段。"""
    if side != "liability":
        return None, None
    if rate is None or str(rate).strip() == "":
        if start is not None:
            raise AccountValidationError("填写计息起始日前，请先填写年利率。")
        return None, None
    try:
        value = Decimal(str(rate))
    except (InvalidOperation, ValueError):
        raise AccountValidationError("年利率必须是数字。") from None
    if not value.is_finite():
        raise AccountValidationError("年利率必须是有效数字。")
    if value < 0 or value > 100:
        raise AccountValidationError("年利率应在 0% 至 100% 之间。")
    return (
        value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
        start,
    )


def _clean_items(
    side: str, items: Sequence[ItemInput], default_currency: str
) -> List[ItemInput]:
    cleaned: List[ItemInput] = []
    seen = set()
    for spec in items:
        name = (spec.name or "").strip()
        if not name:
            raise AccountValidationError("类别子项名称不能为空。")
        if len(name) > 100:
            raise AccountValidationError("子项名称不能超过 100 个字符。")
        if name in seen:
            raise AccountValidationError(f"子项名称 “{name}” 重复。")
        seen.add(name)
        if spec.category not in CATEGORIES_BY_SIDE[side]:
            raise AccountValidationError("子项类别与资产/负债方向不匹配。")
        item_currency = (spec.currency or default_currency or "CNY").strip().upper()
        if item_currency not in CURRENCY_CODES:
            allowed = "、".join(
                f"{CURRENCY_LABELS[code]}（{code}）" for code in CURRENCY_CODES
            )
            raise AccountValidationError(f"子项币种仅支持：{allowed}。")
        symbol, market = quotes.normalize_symbol(
            spec.symbol or "", spec.market or ""
        )
        interest_rate, interest_start = _clean_interest(
            side, spec.interest_rate, spec.interest_start
        )
        cleaned.append(
            ItemInput(
                name=name,
                category=spec.category,
                id=spec.id,
                currency=item_currency,
                symbol=symbol or None,
                market=market or None,
                interest_rate=interest_rate,
                interest_start=interest_start,
            )
        )
    if not cleaned:
        raise AccountValidationError("每个账户至少需要一个类别子项。")
    return cleaned


def _is_unique_violation(exc: IntegrityError) -> bool:
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", ())
    errno = args[0] if args and isinstance(args[0], int) else None
    text = str(orig).lower()
    return errno == 1062 or "duplicate entry" in text or "duplicate key" in text


def list_overviews(session: Session, include_archived: bool = False) -> List[AccountOverview]:
    account_stmt = select(Account).order_by(Account.name)
    if not include_archived:
        account_stmt = account_stmt.where(Account.archived.is_(False))
    accounts = list(session.scalars(account_stmt))

    ranked = (
        select(
            ValuationSnapshot.item_id.label("item_id"),
            ValuationSnapshot.value.label("value"),
            ValuationSnapshot.snapshot_date.label("snapshot_date"),
            func.row_number()
            .over(
                partition_by=ValuationSnapshot.item_id,
                order_by=ValuationSnapshot.snapshot_date.desc(),
            )
            .label("rn"),
        )
        .subquery("ranked_item_snapshots")
    )
    item_rows = session.execute(
        select(
            AccountItem.id,
            AccountItem.account_id,
            AccountItem.name,
            AccountItem.category,
            AccountItem.currency,
            AccountItem.symbol,
            AccountItem.market,
            AccountItem.interest_rate,
            AccountItem.interest_start,
            ranked.c.value,
            ranked.c.snapshot_date,
        )
        .outerjoin(ranked, and_(ranked.c.item_id == AccountItem.id, ranked.c.rn == 1))
        .order_by(AccountItem.account_id, AccountItem.sort_order, AccountItem.id)
    ).all()

    quote_map = quotes.latest_quotes(session)
    items_by_account: Dict[int, List[ItemOverview]] = {}
    for row in item_rows:
        symbol = row.symbol or ""
        market = row.market or ""
        quote = quote_map.get((symbol, market)) if symbol else None
        items_by_account.setdefault(row.account_id, []).append(
            ItemOverview(
                id=row.id,
                account_id=row.account_id,
                name=row.name,
                category=row.category,
                latest_value=row.value,
                latest_date=row.snapshot_date,
                currency=row.currency,
                symbol=symbol,
                market=market,
                price=quote.price if quote else None,
                price_currency=quote.currency if quote else "",
                price_at=quote.quote_time if quote else None,
                interest_rate=row.interest_rate,
                interest_start=row.interest_start,
            )
        )

    side_order = {"asset": 0, "liability": 1}
    result: List[AccountOverview] = []
    for account in accounts:
        items = items_by_account.get(account.id, [])
        values = [item.latest_value for item in items if item.latest_value is not None]
        dates = [item.latest_date for item in items if item.latest_date is not None]
        result.append(
            AccountOverview(
                id=account.id,
                name=account.name,
                side=account.side,
                currency=account.currency,
                note=account.note or "",
                archived=bool(account.archived),
                latest_value=sum(values, Decimal("0.00")) if values else None,
                latest_date=max(dates) if dates else None,
                items=items,
            )
        )
    result.sort(key=lambda item: (side_order.get(item.side, 9), item.name))
    return result


def get_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFound("账户不存在，可能已被删除。")
    return account


def get_item(session: Session, item_id: int) -> AccountItem:
    item = session.get(AccountItem, item_id)
    if item is None:
        raise AccountNotFound("类别子项不存在，可能已被删除。")
    return item


def list_items(session: Session, account_id: int) -> List[AccountItem]:
    return list(
        session.scalars(
            select(AccountItem)
            .where(AccountItem.account_id == account_id)
            .order_by(AccountItem.sort_order, AccountItem.id)
        )
    )


def create_account(
    session: Session,
    name: str,
    side: str,
    items: Sequence[ItemInput],
    currency: str = "CNY",
    note: str = "",
) -> int:
    clean_name, side, clean_currency, clean_note = _clean_fields(
        name, side, currency, note
    )
    clean_items = _clean_items(side, items, clean_currency)
    account = Account(
        name=clean_name,
        side=side,
        currency=clean_currency,
        note=clean_note,
        archived=False,
    )
    account.items = [
        AccountItem(
            name=spec.name,
            category=spec.category,
            currency=spec.currency or clean_currency,
            symbol=spec.symbol or None,
            market=spec.market or None,
            interest_rate=spec.interest_rate,
            interest_start=spec.interest_start,
            sort_order=index,
        )
        for index, spec in enumerate(clean_items)
    ]
    session.add(account)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if _is_unique_violation(exc):
            raise DuplicateAccountName(clean_name) from exc
        raise
    return int(account.id)


def update_account(
    session: Session,
    account_id: int,
    name: str,
    side: str,
    items: Sequence[ItemInput],
    currency: str = "CNY",
    note: str = "",
) -> None:
    clean_name, side, clean_currency, clean_note = _clean_fields(
        name, side, currency, note
    )
    clean_items = _clean_items(side, items, clean_currency)
    account = get_account(session, account_id)
    account.name = clean_name
    account.side = side
    account.currency = clean_currency
    account.note = clean_note

    existing = {item.id: item for item in account.items}
    kept = set()
    for index, spec in enumerate(clean_items):
        current = existing.get(spec.id) if spec.id else None
        if current is None:
            account.items.append(
                AccountItem(
                    name=spec.name,
                    category=spec.category,
                    currency=spec.currency or clean_currency,
                    symbol=spec.symbol or None,
                    market=spec.market or None,
                    interest_rate=spec.interest_rate,
                    interest_start=spec.interest_start,
                    sort_order=index,
                )
            )
        else:
            current.name = spec.name
            current.category = spec.category
            current.currency = spec.currency or current.currency
            current.symbol = spec.symbol or None
            current.market = spec.market or None
            current.interest_rate = spec.interest_rate
            current.interest_start = spec.interest_start
            current.sort_order = index
            kept.add(current.id)
    for item_id, item in existing.items():
        if item_id not in kept:
            account.items.remove(item)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if _is_unique_violation(exc):
            raise DuplicateAccountName(clean_name) from exc
        raise
    except ValueError as exc:  # 例如子项已被删除
        session.rollback()
        raise AccountValidationError("保存失败：子项状态已变化，请刷新后重试。") from exc


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
            .join(AccountItem, AccountItem.id == ValuationSnapshot.item_id)
            .where(AccountItem.account_id == account_id)
        )
        or 0
    )
