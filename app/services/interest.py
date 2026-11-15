"""负债子项利息：按日单利计算。

口径：当日利息 = 当日余额 × 年利率 ÷ 100 ÷ 365；
余额取估值快照并按日前向填充，早于首次快照的日期不计息。
区间利息由各余额分段累加，累计利息即从计息起始日到今天的区间利息。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SIDE_LIABILITY, Account, AccountItem, ValuationSnapshot
from app.services import exchange_rates
from app.utils.money import to_money

CENT = Decimal("0.01")
DAYS_PER_YEAR = Decimal("365")


@dataclass(frozen=True)
class InterestRow:
    account_id: int
    account_name: str
    item_id: int
    item_name: str
    category: str
    currency: str
    rate: Decimal
    start: date
    end: date
    days: int
    balance: Optional[Decimal]
    interest: Decimal
    interest_cny: Optional[Decimal]
    missing_snapshot: bool


def _load_snapshots(
    session: Session, item_ids: Sequence[int]
) -> Dict[int, List[Tuple[date, Decimal]]]:
    if not item_ids:
        return {}
    result: Dict[int, List[Tuple[date, Decimal]]] = {}
    for item_id, day, value in session.execute(
        select(
            ValuationSnapshot.item_id,
            ValuationSnapshot.snapshot_date,
            ValuationSnapshot.value,
        )
        .where(ValuationSnapshot.item_id.in_(list(item_ids)))
        .order_by(ValuationSnapshot.item_id, ValuationSnapshot.snapshot_date)
    ).all():
        result.setdefault(item_id, []).append((day, Decimal(str(value))))
    return result


def _balance_on(snapshots: Sequence[Tuple[date, Decimal]], day: date) -> Optional[Decimal]:
    """某日有效余额（前向填充），早于首次快照返回 None。"""
    balance: Optional[Decimal] = None
    for snapshot_date, value in snapshots:
        if snapshot_date > day:
            break
        balance = value
    return balance


def _segment_interest(
    snapshots: Sequence[Tuple[date, Decimal]],
    start: date,
    end: date,
    rate: Decimal,
) -> Decimal:
    """[start, end] 内按余额分段累加的利息（原币，未四舍五入）。"""
    if start > end or not snapshots:
        return Decimal("0")
    total = Decimal("0")
    for index, (snapshot_date, value) in enumerate(snapshots):
        segment_start = max(snapshot_date, start)
        if index + 1 < len(snapshots):
            segment_end = min(snapshots[index + 1][0] - timedelta(days=1), end)
        else:
            segment_end = end
        if segment_start > segment_end:
            continue
        days = (segment_end - segment_start).days + 1
        total += value * rate / Decimal("100") / DAYS_PER_YEAR * days
    return total


def _to_cny(
    value: Decimal,
    currency: str,
    day: date,
    lookup,
    known: Sequence[str],
) -> Optional[Decimal]:
    if currency != "CNY" and currency not in set(known):
        return None
    rate = lookup(currency, day)
    return (value * rate).quantize(CENT, rounding=ROUND_HALF_UP)


def interest_rows(
    session: Session,
    start: Optional[date] = None,
    end: Optional[date] = None,
    include_archived: bool = False,
    today: Optional[date] = None,
) -> List[InterestRow]:
    """已配置年利率的负债子项利息；start 为空表示从计息起始日累计。"""
    day = today or date.today()
    finish = min(end or day, day)
    stmt = (
        select(AccountItem, Account)
        .join(Account, Account.id == AccountItem.account_id)
        .where(
            Account.side == SIDE_LIABILITY,
            AccountItem.interest_rate.is_not(None),
            AccountItem.interest_rate > 0,
        )
        .order_by(Account.name, AccountItem.sort_order, AccountItem.id)
    )
    if not include_archived:
        stmt = stmt.where(Account.archived.is_(False))
    records = session.execute(stmt).all()
    snapshots_by_item = _load_snapshots(session, [item.id for item, _ in records])
    lookup = exchange_rates.build_rate_lookup(session)
    known = list(exchange_rates.latest_rates(session))

    rows: List[InterestRow] = []
    for item, account in records:
        rate = Decimal(str(item.interest_rate))
        snapshots = snapshots_by_item.get(item.id, [])
        base = item.interest_start or (snapshots[0][0] if snapshots else None)
        if base is None:
            base = finish
        begin = max(start, base) if start is not None else base
        accrual = max(begin, snapshots[0][0]) if snapshots else begin
        balance = _balance_on(snapshots, finish)
        if accrual > finish or balance is None:
            interest = Decimal("0.00")
            days = 0
        else:
            interest = to_money(
                _segment_interest(snapshots, begin, finish, rate)
            )
            days = (finish - accrual).days + 1
        missing = bool(
            item.interest_start
            and (not snapshots or snapshots[0][0] > item.interest_start)
        )
        rows.append(
            InterestRow(
                account_id=account.id,
                account_name=account.name,
                item_id=item.id,
                item_name=item.name,
                category=item.category,
                currency=item.currency,
                rate=rate,
                start=begin,
                end=finish,
                days=days,
                balance=balance,
                interest=interest,
                interest_cny=_to_cny(interest, item.currency, finish, lookup, known),
                missing_snapshot=missing,
            )
        )
    rows.sort(key=lambda row: row.interest_cny or Decimal("0"), reverse=True)
    return rows


def totals_by_item(rows: Sequence[InterestRow]) -> Dict[int, InterestRow]:
    return {row.item_id: row for row in rows}


def total_interest_cny(rows: Sequence[InterestRow]) -> Decimal:
    return sum(
        (row.interest_cny for row in rows if row.interest_cny is not None),
        Decimal("0.00"),
    )
