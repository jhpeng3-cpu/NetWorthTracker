"""账户服务：账户及其类别子项。

一个账户可包含多个类别子项（如证券账户下的现金、股票、债券），
估值快照按子项记录，账户金额为子项之和。
"""
from __future__ import annotations

import json
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
    COMPOUNDING_MODES,
    CURRENCY_CODES,
    CURRENCY_LABELS,
    PAY_FREQUENCIES,
    SIDE_LABELS,
    VALUATION_MANUAL,
    VALUATION_MODE_LABELS,
    Account,
    AccountItem,
    ValuationSnapshot,
    allowed_valuation_modes,
    default_valuation_mode,
)
from app.services import exchange_rates, quotes
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
    valuation_mode: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    principal: Optional[Decimal] = None
    face_value: Optional[Decimal] = None
    maturity_date: Optional[date] = None
    pay_frequency: Optional[str] = None
    compounding: Optional[str] = None
    early_withdraw_rate: Optional[Decimal] = None
    price_source: Optional[str] = None
    next_valuation: Optional[date] = None
    asset_meta: Optional[dict] = None

    @classmethod
    def from_overview(cls, item: "ItemOverview", **overrides) -> "ItemInput":
        """由现有的子项概览生成输入项，可覆盖部分字段。"""
        fields = dict(
            id=item.id,
            name=item.name,
            category=item.category,
            currency=item.currency,
            symbol=item.symbol or None,
            market=item.market or None,
            interest_rate=item.interest_rate,
            interest_start=item.interest_start,
            valuation_mode=item.valuation_mode,
            quantity=item.quantity,
            unit=item.unit or None,
            principal=item.principal,
            face_value=item.face_value,
            maturity_date=item.maturity_date,
            pay_frequency=item.pay_frequency,
            compounding=item.compounding,
            early_withdraw_rate=item.early_withdraw_rate,
            price_source=item.price_source or None,
            next_valuation=item.next_valuation,
            asset_meta=item.asset_meta,
        )
        fields.update(overrides)
        return cls(**fields)


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
    valuation_mode: str = VALUATION_MANUAL
    quantity: Optional[Decimal] = None
    unit: str = ""
    principal: Optional[Decimal] = None
    face_value: Optional[Decimal] = None
    maturity_date: Optional[date] = None
    pay_frequency: str = "none"
    compounding: str = "simple"
    early_withdraw_rate: Optional[Decimal] = None
    price_source: str = ""
    next_valuation: Optional[date] = None
    asset_meta: Optional[dict] = None

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
    rate: Optional[Decimal], start: Optional[date]
) -> tuple:
    """年利率与计息起始日（资产计息、负债利息共用）；未填写时均为 None。"""
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


def _optional_decimal(
    value: object,
    field: str,
    digits: str,
    minimum: Optional[Decimal] = None,
    maximum: Optional[Decimal] = None,
) -> Optional[Decimal]:
    """把可选数值规范为指定小数位，空值返回 None。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise AccountValidationError(f"{field}必须是数字。") from None
    if not number.is_finite():
        raise AccountValidationError(f"{field}必须是有效数字。")
    if minimum is not None and number < minimum:
        raise AccountValidationError(f"{field}不能小于 {minimum}。")
    if maximum is not None and number > maximum:
        raise AccountValidationError(f"{field}不能大于 {maximum}。")
    return number.quantize(Decimal(digits), rounding=ROUND_HALF_UP)


def _clean_valuation(side: str, spec: "ItemInput") -> dict:
    """校验并规范化估值模式及其扩展参数。"""
    mode = (spec.valuation_mode or default_valuation_mode(spec.category)).strip()
    allowed = allowed_valuation_modes(spec.category)
    if side != "asset":
        mode = VALUATION_MANUAL
        allowed = (VALUATION_MANUAL,)
    if mode not in allowed:
        labels = "、".join(VALUATION_MODE_LABELS[item] for item in allowed)
        raise AccountValidationError(
            f"{CATEGORY_LABELS.get(spec.category, spec.category)}仅支持：{labels}。"
        )

    unit = (spec.unit or "").strip()
    if len(unit) > 8:
        raise AccountValidationError("单位不能超过 8 个字符。")

    pay_frequency = (spec.pay_frequency or "none").strip()
    if pay_frequency not in PAY_FREQUENCIES:
        raise AccountValidationError("付息方式不合法。")

    compounding = (spec.compounding or "simple").strip()
    if compounding not in COMPOUNDING_MODES:
        raise AccountValidationError("计息方式必须是单利或复利。")

    price_source = (spec.price_source or "").strip()
    if len(price_source) > 120:
        raise AccountValidationError("行情源标识不能超过 120 个字符。")

    asset_meta = spec.asset_meta
    if asset_meta is not None:
        if not isinstance(asset_meta, dict):
            raise AccountValidationError("扩展参数必须是键值对象。")
        try:
            json.dumps(asset_meta, ensure_ascii=False)
        except (TypeError, ValueError):
            raise AccountValidationError("扩展参数包含无法保存的内容。") from None

    return {
        "valuation_mode": mode,
        "quantity": _optional_decimal(
            spec.quantity, "数量", "0.0001", Decimal("0")
        ),
        "unit": unit or None,
        "principal": _optional_decimal(
            spec.principal, "本金", "0.01", Decimal("0")
        ),
        "face_value": _optional_decimal(
            spec.face_value, "面值", "0.01", Decimal("0")
        ),
        "maturity_date": spec.maturity_date,
        "pay_frequency": None if pay_frequency == "none" else pay_frequency,
        "compounding": None if compounding == "simple" else compounding,
        "early_withdraw_rate": _optional_decimal(
            spec.early_withdraw_rate,
            "提前支取利率",
            "0.001",
            Decimal("0"),
            Decimal("100"),
        ),
        "price_source": price_source or None,
        "next_valuation": spec.next_valuation,
        "asset_meta": asset_meta or None,
    }


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
        symbol, market = quotes.resolve_market(
            spec.symbol or "", spec.market or "", spec.category
        )
        interest_rate, interest_start = _clean_interest(
            spec.interest_rate, spec.interest_start
        )
        valuation = _clean_valuation(side, spec)
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
                **valuation,
            )
        )
    if not cleaned:
        raise AccountValidationError("每个账户至少需要一个类别子项。")
    return cleaned


def _item_columns(spec: ItemInput) -> dict:
    """把清理后的 ItemInput 转成 AccountItem 字段。"""
    return {
        "name": spec.name,
        "category": spec.category,
        "currency": spec.currency,
        "symbol": spec.symbol or None,
        "market": spec.market or None,
        "interest_rate": spec.interest_rate,
        "interest_start": spec.interest_start,
        "valuation_mode": spec.valuation_mode or VALUATION_MANUAL,
        "quantity": spec.quantity,
        "unit": spec.unit,
        "principal": spec.principal,
        "face_value": spec.face_value,
        "maturity_date": spec.maturity_date,
        "pay_frequency": spec.pay_frequency,
        "compounding": spec.compounding,
        "early_withdraw_rate": spec.early_withdraw_rate,
        "price_source": spec.price_source,
        "next_valuation": spec.next_valuation,
        "asset_meta": spec.asset_meta,
    }


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
            AccountItem.valuation_mode,
            AccountItem.quantity,
            AccountItem.unit,
            AccountItem.principal,
            AccountItem.face_value,
            AccountItem.maturity_date,
            AccountItem.pay_frequency,
            AccountItem.compounding,
            AccountItem.early_withdraw_rate,
            AccountItem.price_source,
            AccountItem.next_valuation,
            AccountItem.asset_meta,
            ranked.c.value,
            ranked.c.snapshot_date,
        )
        .outerjoin(ranked, and_(ranked.c.item_id == AccountItem.id, ranked.c.rn == 1))
        .order_by(AccountItem.account_id, AccountItem.sort_order, AccountItem.id)
    ).all()

    quote_map = quotes.latest_quotes(session)
    rate_map = exchange_rates.latest_rates(session)
    items_by_account: Dict[int, List[ItemOverview]] = {}
    for row in item_rows:
        symbol = row.symbol or ""
        market = row.market or ""
        lookup_market = market or (
            quotes.resolve_market(symbol, market, row.category)[1] if symbol else ""
        )
        quote = quote_map.get((symbol, lookup_market)) if symbol else None
        price = quote.price if quote else None
        price_currency = quote.currency if quote else ""
        price_at = quote.quote_time if quote else None
        if quote is None and not symbol and row.currency != "CNY":
            rate_entry = rate_map.get(row.currency)
            if rate_entry is not None:
                rate_day, rate_value = rate_entry
                price = rate_value
                price_currency = "CNY"
                price_at = datetime.combine(rate_day, datetime.min.time())
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
                price=price,
                price_currency=price_currency,
                price_at=price_at,
                interest_rate=row.interest_rate,
                interest_start=row.interest_start,
                valuation_mode=row.valuation_mode or VALUATION_MANUAL,
                quantity=row.quantity,
                unit=row.unit or "",
                principal=row.principal,
                face_value=row.face_value,
                maturity_date=row.maturity_date,
                pay_frequency=row.pay_frequency or "none",
                compounding=row.compounding or "simple",
                early_withdraw_rate=row.early_withdraw_rate,
                price_source=row.price_source or "",
                next_valuation=row.next_valuation,
                asset_meta=row.asset_meta,
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
        AccountItem(sort_order=index, **_item_columns(spec))
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
                AccountItem(sort_order=index, **_item_columns(spec))
            )
        else:
            for key, value in _item_columns(spec).items():
                setattr(current, key, value)
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
