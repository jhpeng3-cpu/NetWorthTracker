"""净资产、资产分布、历史曲线与变化拆解。

金额口径：所有对外统计均折算为人民币；各持仓按「统计当日」的有效汇率换算
（当日无汇率时前向填充最近一次，早于最早汇率日沿用最早汇率，见 exchange_rates）。

前向填充核心：
- holdings_as_of() 使用窗口函数 row_number() OVER (PARTITION BY account_id
  ORDER BY snapshot_date DESC) 取每个账户在目标日期及之前最近的一条估值。
- 历史曲线一次性读取快照并按日期指针推进，时间复杂度 O(快照数 + 时间点数)。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    CATEGORY_LABELS,
    SIDE_ASSET,
    SIDE_LABELS,
    SIDE_LIABILITY,
    Account,
    AccountItem,
    ValuationSnapshot,
)
from app.services import exchange_rates
from app.utils.dates import build_period_points
from app.utils.money import ratio


@dataclass(frozen=True)
class Holding:
    account_id: int
    account_name: str
    side: str
    category: str
    value: Optional[Decimal]
    snapshot_date: Optional[date]
    currency: str = "CNY"
    item_id: int = 0
    item_name: str = ""


@dataclass(frozen=True)
class NetWorthPoint:
    on_date: date
    assets: Decimal
    liabilities: Decimal
    net: Decimal


@dataclass(frozen=True)
class PieSlice:
    label: str
    value: Decimal
    percent: Decimal


@dataclass(frozen=True)
class CurrentSummary:
    assets: Decimal
    liabilities: Decimal
    net: Decimal
    previous_net: Optional[Decimal]
    change: Optional[Decimal]
    change_rate: Optional[Decimal]
    latest_date: Optional[date]
    previous_date: Optional[date]
    account_count: int
    snapshot_count: int


@dataclass(frozen=True)
class DecompositionRow:
    account_id: int
    account_name: str
    side: str
    category: str
    start_value: Decimal
    end_value: Decimal
    change: Decimal
    item_name: str = ""

    @property
    def side_label(self) -> str:
        return SIDE_LABELS.get(self.side, self.side)

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)


@dataclass(frozen=True)
class Decomposition:
    start_point: NetWorthPoint
    end_point: NetWorthPoint
    rows: List[DecompositionRow]


def holdings_as_of(session: Session, on_date: date) -> List[Holding]:
    """某个日期各未归档账户子项的最新估值（前向填充，窗口函数实现）。"""
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
        .where(ValuationSnapshot.snapshot_date <= on_date)
        .subquery("ranked_holdings")
    )
    stmt = (
        select(
            ranked.c.item_id.label("item_id"),
            AccountItem.name.label("item_name"),
            AccountItem.category,
            AccountItem.currency,
            Account.id.label("account_id"),
            Account.name.label("account_name"),
            Account.side,
            ranked.c.value,
            ranked.c.snapshot_date,
        )
        .select_from(AccountItem)
        .join(Account, Account.id == AccountItem.account_id)
        .join(
            ranked,
            (ranked.c.item_id == AccountItem.id) & (ranked.c.rn == 1),
        )
        .where(Account.archived.is_(False))
        .order_by(Account.side, Account.name, AccountItem.sort_order, AccountItem.id)
    )
    return [
        Holding(
            account_id=row.account_id,
            account_name=row.account_name,
            side=row.side,
            category=row.category,
            currency=row.currency,
            value=row.value,
            snapshot_date=row.snapshot_date,
            item_id=row.item_id,
            item_name=row.item_name,
        )
        for row in session.execute(stmt).all()
    ]


def _sum_side(
    holdings: List[Holding],
    side: str,
    lookup: Callable[[str, date], Decimal],
    on_date: date,
) -> Decimal:
    total = Decimal("0.00")
    for item in holdings:
        if item.side == side:
            total += exchange_rates.to_cny(item.value, item.currency, on_date, lookup)
    return total


def net_worth_on(session: Session, on_date: date) -> NetWorthPoint:
    holdings = holdings_as_of(session, on_date)
    lookup = exchange_rates.build_rate_lookup(session)
    assets = _sum_side(holdings, SIDE_ASSET, lookup, on_date)
    liabilities = _sum_side(holdings, SIDE_LIABILITY, lookup, on_date)
    return NetWorthPoint(
        on_date=on_date,
        assets=assets,
        liabilities=liabilities,
        net=assets - liabilities,
    )


def first_snapshot_date(session: Session) -> Optional[date]:
    return session.scalar(
        select(func.min(ValuationSnapshot.snapshot_date))
        .select_from(ValuationSnapshot)
        .join(Account, Account.id == ValuationSnapshot.account_id)
        .where(Account.archived.is_(False))
    )


def current_summary(session: Session, today: Optional[date] = None) -> CurrentSummary:
    today = today or date.today()
    account_count = int(
        session.scalar(
            select(func.count()).select_from(Account).where(Account.archived.is_(False))
        )
        or 0
    )
    snapshot_count = int(
        session.scalar(
            select(func.count())
            .select_from(ValuationSnapshot)
            .join(Account, Account.id == ValuationSnapshot.account_id)
            .where(Account.archived.is_(False))
        )
        or 0
    )
    dates = list(
        session.scalars(
            select(ValuationSnapshot.snapshot_date)
            .join(Account, Account.id == ValuationSnapshot.account_id)
            .where(
                Account.archived.is_(False),
                ValuationSnapshot.snapshot_date <= today,
            )
            .distinct()
            .order_by(ValuationSnapshot.snapshot_date.desc())
            .limit(2)
        )
    )
    latest_date = dates[0] if dates else None
    previous_date = dates[1] if len(dates) > 1 else None

    current = net_worth_on(session, today)
    if previous_date is None:
        previous_net = None
        change = None
        change_rate = None
    else:
        previous = net_worth_on(session, previous_date)
        previous_net = previous.net
        change = current.net - previous.net
        if previous_net == 0:
            change_rate = None
        else:
            change_rate = (change / abs(previous_net) * Decimal("100")).quantize(
                Decimal("0.01")
            )

    return CurrentSummary(
        assets=current.assets,
        liabilities=current.liabilities,
        net=current.net,
        previous_net=previous_net,
        change=change,
        change_rate=change_rate,
        latest_date=latest_date,
        previous_date=previous_date,
        account_count=account_count,
        snapshot_count=snapshot_count,
    )


def distribution(
    session: Session,
    side: str,
    group_by: str = "category",
    on_date: Optional[date] = None,
) -> List[PieSlice]:
    day = on_date or date.today()
    holdings = holdings_as_of(session, day)
    lookup = exchange_rates.build_rate_lookup(session)
    buckets: Dict[str, Decimal] = {}
    for item in holdings:
        if item.side != side or item.value is None or item.value <= 0:
            continue
        if group_by == "account":
            key = item.account_name
        else:
            key = CATEGORY_LABELS.get(item.category, item.category)
        buckets[key] = buckets.get(key, Decimal("0.00")) + exchange_rates.to_cny(
            item.value, item.currency, day, lookup
        )
    total = sum(buckets.values(), Decimal("0.00"))
    if total <= 0:
        return []
    slices = [
        PieSlice(label=label, value=value, percent=ratio(value, total))
        for label, value in buckets.items()
    ]
    slices.sort(key=lambda item: item.value, reverse=True)
    return slices


def history_points(
    session: Session,
    start: date,
    end: date,
    granularity: str = "day",
) -> List[NetWorthPoint]:
    """返回区间内的净资产序列。

    日粒度：区间内逐日计算，无快照的日期沿用最近一次估值；
    月/年粒度：取每个周期末，当前周期取今天。
    """
    if start > end:
        return []

    rows: List[Tuple[date, int, str, str, Decimal]] = [
        (row.snapshot_date, row.item_id, row.side, row.currency, row.value)
        for row in session.execute(
            select(
                ValuationSnapshot.snapshot_date,
                ValuationSnapshot.item_id,
                Account.side,
                AccountItem.currency,
                ValuationSnapshot.value,
            )
            .join(AccountItem, AccountItem.id == ValuationSnapshot.item_id)
            .join(Account, Account.id == AccountItem.account_id)
            .where(
                Account.archived.is_(False),
                ValuationSnapshot.snapshot_date <= end,
            )
            .order_by(ValuationSnapshot.snapshot_date, ValuationSnapshot.id)
        ).all()
    ]
    if not rows:
        return []

    if granularity == "day":
        total_days = (end - start).days
        target_dates = [start + timedelta(days=offset) for offset in range(total_days + 1)]
    else:
        target_dates = build_period_points(start, end, granularity)

    lookup = exchange_rates.build_rate_lookup(session)
    current: Dict[int, Tuple[str, str, Decimal]] = {}
    cursor = 0
    result: List[NetWorthPoint] = []
    for target in target_dates:
        while cursor < len(rows) and rows[cursor][0] <= target:
            _, account_id, side, currency, value = rows[cursor]
            current[account_id] = (side, currency, value)
            cursor += 1
        assets = Decimal("0.00")
        liabilities = Decimal("0.00")
        for side, currency, value in current.values():
            converted = exchange_rates.to_cny(value, currency, target, lookup)
            if side == SIDE_ASSET:
                assets += converted
            else:
                liabilities += converted
        result.append(
            NetWorthPoint(
                on_date=target,
                assets=assets,
                liabilities=liabilities,
                net=assets - liabilities,
            )
        )
    return result


def decompose(session: Session, start: date, end: date) -> Decomposition:
    start_point = net_worth_on(session, start)
    end_point = net_worth_on(session, end)
    start_holdings = {item.account_id: item for item in holdings_as_of(session, start)}
    end_holdings = {item.account_id: item for item in holdings_as_of(session, end)}
    lookup = exchange_rates.build_rate_lookup(session)

    rows: List[DecompositionRow] = []
    for item_id in set(start_holdings) | set(end_holdings):
        first = start_holdings.get(item_id)
        last = end_holdings.get(item_id)
        meta = last or first
        if meta is None:
            continue
        start_value = exchange_rates.to_cny(
            first.value if first else None, meta.currency, start, lookup
        )
        end_value = exchange_rates.to_cny(
            last.value if last else None, meta.currency, end, lookup
        )
        rows.append(
            DecompositionRow(
                account_id=meta.account_id,
                account_name=meta.account_name,
                side=meta.side,
                category=meta.category,
                start_value=start_value,
                end_value=end_value,
                change=end_value - start_value,
                item_name=meta.item_name,
            )
        )
    rows.sort(key=lambda item: item.change, reverse=True)
    return Decomposition(start_point=start_point, end_point=end_point, rows=rows)
