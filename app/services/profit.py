"""持仓成本与盈亏计算。

成本以「批次」形式挂在类别子项上（一次买入一条），
市值沿用已有估值快照；盈亏在查询时实时计算，不落库。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    CATEGORY_LABELS,
    CURRENCY_CODES,
    SIDE_ASSET,
    SIDE_LABELS,
    SIDE_LIABILITY,
    AccountItem,
    PositionLot,
)
from app.services import accounts as account_service
from app.services import analytics
from app.services import exchange_rates
from app.services import interest as interest_service
from app.utils.exceptions import AppValidationError
from app.utils.money import ratio, to_money

CENT = Decimal("0.01")


class ProfitError(AppValidationError):
    pass


@dataclass(frozen=True)
class LotInput:
    trade_date: date
    quantity: Decimal
    unit_cost: Decimal
    fee: Decimal = Decimal("0")
    currency: str = "CNY"
    note: str = ""

    @property
    def total_cost(self) -> Decimal:
        return to_money(self.quantity * self.unit_cost + self.fee)


@dataclass(frozen=True)
class CostSummary:
    currency: str
    quantity: Decimal
    total_cost: Decimal
    lot_count: int

    @property
    def avg_unit_cost(self) -> Optional[Decimal]:
        if self.quantity <= 0:
            return None
        return (self.total_cost / self.quantity).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )


@dataclass(frozen=True)
class ProfitRow:
    account_id: int
    account_name: str
    item_id: int
    item_name: str
    category: str
    side: str
    account_currency: str
    cost_currency: str
    quantity: Decimal
    cost_total: Decimal
    avg_unit_cost: Optional[Decimal]
    value: Optional[Decimal]
    value_date: Optional[date]
    value_in_cost: Optional[Decimal]
    pnl: Optional[Decimal]
    pnl_rate: Optional[Decimal]
    pnl_cny: Optional[Decimal]
    cost_cny: Optional[Decimal]
    value_cny: Optional[Decimal]

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    @property
    def side_label(self) -> str:
        return SIDE_LABELS.get(self.side, self.side)


@dataclass(frozen=True)
class PortfolioSummary:
    value_cny: Decimal
    cost_cny: Decimal
    pnl_cny: Decimal
    pnl_rate: Optional[Decimal]
    item_count: int
    missing_rate: int


@dataclass(frozen=True)
class AccountProfitRow:
    """账户级盈亏：资产为投资收益，负债为利息支出。"""

    account_id: int
    account_name: str
    side: str
    currency: str
    value_cny: Optional[Decimal]
    cost_cny: Optional[Decimal]
    pnl_cny: Optional[Decimal]
    pnl_rate: Optional[Decimal]
    interest_cny: Optional[Decimal]
    item_count: int
    note: str = ""

    @property
    def side_label(self) -> str:
        return SIDE_LABELS.get(self.side, self.side)


@dataclass(frozen=True)
class AccountProfitSummary:
    investment_cny: Decimal
    interest_cny: Decimal
    net_cny: Decimal
    value_cny: Decimal
    cost_cny: Decimal
    account_count: int
    missing: int


def _check_currency(currency: str) -> str:
    code = (currency or "").strip().upper()
    if code not in CURRENCY_CODES:
        raise ProfitError("成本币种仅支持：" + "、".join(CURRENCY_CODES) + "。")
    return code


def _clean_lot(lot: LotInput, today: date) -> LotInput:
    if lot.trade_date > today:
        raise ProfitError("买入日期不能晚于今天。")
    quantity = Decimal(str(lot.quantity))
    if quantity <= 0:
        raise ProfitError("买入数量必须大于 0。")
    unit_cost = Decimal(str(lot.unit_cost))
    if unit_cost < 0:
        raise ProfitError("买入单价不能为负数。")
    fee = Decimal(str(lot.fee or 0))
    if fee < 0:
        raise ProfitError("手续费不能为负数。")
    return LotInput(
        trade_date=lot.trade_date,
        quantity=quantity.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        unit_cost=unit_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
        fee=to_money(fee),
        currency=_check_currency(lot.currency),
        note=(lot.note or "").strip(),
    )


def save_lots(
    session: Session, item_id: int, lots: Sequence[LotInput], today: Optional[date] = None
) -> int:
    """整体替换某个子项的成本批次，返回保存条数。"""
    item = session.get(AccountItem, item_id)
    if item is None:
        raise ProfitError("类别子项不存在，可能已被删除。")
    day = today or date.today()
    cleaned = [_clean_lot(lot, day) for lot in lots]
    currencies = {lot.currency for lot in cleaned}
    if len(currencies) > 1:
        raise ProfitError("同一子项的成本批次必须使用同一种币种。")

    session.execute(delete(PositionLot).where(PositionLot.item_id == item_id))
    for lot in cleaned:
        session.add(
            PositionLot(
                item_id=item_id,
                trade_date=lot.trade_date,
                quantity=lot.quantity,
                unit_cost=lot.unit_cost,
                fee=lot.fee,
                currency=lot.currency,
                note=lot.note or None,
            )
        )
    session.flush()
    session.commit()
    return len(cleaned)


def list_lots(session: Session, item_id: int) -> List[PositionLot]:
    return list(
        session.execute(
            select(PositionLot)
            .where(PositionLot.item_id == item_id)
            .order_by(PositionLot.trade_date, PositionLot.id)
        ).scalars()
    )


def cost_summaries(
    session: Session, item_ids: Iterable[int]
) -> Dict[int, CostSummary]:
    """批量计算各子项的成本汇总，避免逐个查询。"""
    ids = [item_id for item_id in item_ids]
    if not ids:
        return {}
    sums: Dict[int, tuple] = {}
    for item_id, currency, quantity, total in session.execute(
        select(
            PositionLot.item_id,
            PositionLot.currency,
            PositionLot.quantity,
            PositionLot.quantity * PositionLot.unit_cost + PositionLot.fee,
        ).where(PositionLot.item_id.in_(ids))
    ).all():
        current = sums.get(item_id)
        if current is None:
            sums[item_id] = (currency, quantity, to_money(total), 1)
        else:
            sums[item_id] = (
                current[0],
                current[1] + quantity,
                to_money(current[2] + total),
                current[3] + 1,
            )
    return {
        item_id: CostSummary(
            currency=value[0],
            quantity=value[1],
            total_cost=value[2],
            lot_count=value[3],
        )
        for item_id, value in sums.items()
    }


def _convert(
    value: Optional[Decimal],
    from_currency: str,
    to_currency: str,
    day: date,
    lookup,
    known: Iterable[str],
) -> Optional[Decimal]:
    """按当日汇率把金额从一种币种折算到另一种；缺少汇率时返回 None。"""
    if value is None:
        return None
    known_set = set(known)
    for code in (from_currency, to_currency):
        if code != "CNY" and code not in known_set:
            return None
    if from_currency == to_currency:
        return to_money(value)
    rate_from = lookup(from_currency, day)
    rate_to = lookup(to_currency, day)
    if rate_to == 0:
        return None
    return (value * rate_from / rate_to).quantize(CENT, rounding=ROUND_HALF_UP)


def profit_rows(
    session: Session,
    include_archived: bool = False,
    today: Optional[date] = None,
) -> List[ProfitRow]:
    """所有已录成本子项的盈亏，按盈亏额降序；市值不足时对应字段为 None。"""
    day = today or date.today()
    lookup = exchange_rates.build_rate_lookup(session)
    known = set(exchange_rates.latest_rates(session))
    overviews = account_service.list_overviews(
        session, include_archived=include_archived
    )
    summaries = cost_summaries(
        session, [item.id for account in overviews for item in account.items]
    )

    rows: List[ProfitRow] = []
    for account in overviews:
        for item in account.items:
            summary = summaries.get(item.id)
            if summary is None:
                continue
            if account.side != SIDE_ASSET:
                continue
            value = item.latest_value
            value_in_cost = _convert(
                value, item.currency, summary.currency, day, lookup, known
            )
            pnl = (
                to_money(value_in_cost - summary.total_cost)
                if value_in_cost is not None
                else None
            )
            pnl_cny = (
                _convert(pnl, summary.currency, "CNY", day, lookup, known)
                if pnl is not None
                else None
            )
            cost_cny = _convert(
                summary.total_cost, summary.currency, "CNY", day, lookup, known
            )
            if cost_cny is None and summary.currency == "CNY":
                cost_cny = summary.total_cost
            value_cny = (
                _convert(value, item.currency, "CNY", day, lookup, known)
                if value is not None
                else None
            )
            rows.append(
                ProfitRow(
                    account_id=account.id,
                    account_name=account.name,
                    item_id=item.id,
                    item_name=item.name,
                    category=item.category,
                    side=account.side,
                    account_currency=item.currency,
                    cost_currency=summary.currency,
                    quantity=summary.quantity,
                    cost_total=summary.total_cost,
                    avg_unit_cost=summary.avg_unit_cost,
                    value=value,
                    value_date=item.latest_date,
                    value_in_cost=value_in_cost,
                    pnl=pnl,
                    pnl_rate=ratio(pnl, summary.total_cost) if pnl is not None else None,
                    pnl_cny=pnl_cny,
                    cost_cny=cost_cny,
                    value_cny=value_cny,
                )
            )
    rows.sort(
        key=lambda row: (row.pnl_cny is None, -row.pnl_cny if row.pnl_cny else Decimal("0"))
    )
    return rows


def portfolio_summary(rows: Sequence[ProfitRow], today: Optional[date] = None) -> PortfolioSummary:
    """组合层面的盈亏汇总（人民币口径），仅统计可折算的行。"""
    value_cny = Decimal("0.00")
    cost_cny = Decimal("0.00")
    pnl_cny = Decimal("0.00")
    missing = 0
    for row in rows:
        if row.value_cny is None or row.pnl_cny is None or row.cost_cny is None:
            missing += 1
            continue
        value_cny += row.value_cny
        cost_cny += row.cost_cny
        pnl_cny += row.pnl_cny
    return PortfolioSummary(
        value_cny=to_money(value_cny),
        cost_cny=to_money(cost_cny),
        pnl_cny=to_money(pnl_cny),
        pnl_rate=ratio(pnl_cny, cost_cny) if cost_cny > 0 else None,
        item_count=len(rows),
        missing_rate=missing,
    )


@dataclass(frozen=True)
class PeriodProfitRow:
    """区间盈亏：期初/期末的市值、成本与区间内盈亏变化。

    市值取区间起点前一日与区间末日的有效估值快照（缺少时按 0 计），
    成本取买入日期不晚于对应日期的成本批次之和；盈亏与盈亏率按成本币种计算。
    """

    account_id: int
    account_name: str
    item_id: int
    item_name: str
    category: str
    side: str
    currency: str
    cost_currency: str
    quantity: Decimal
    start_value: Optional[Decimal]
    end_value: Optional[Decimal]
    start_cost: Decimal
    end_cost: Decimal
    pnl: Optional[Decimal]
    pnl_rate: Optional[Decimal]
    pnl_cny: Optional[Decimal]
    start_cost_cny: Optional[Decimal]
    end_value_cny: Optional[Decimal]
    start_value_date: Optional[date]
    end_value_date: Optional[date]

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    @property
    def side_label(self) -> str:
        return SIDE_LABELS.get(self.side, self.side)


@dataclass(frozen=True)
class PeriodSummary:
    start: date
    end: date
    pnl_cny: Decimal
    end_value_cny: Decimal
    start_cost_cny: Decimal
    pnl_rate: Optional[Decimal]
    item_count: int
    missing_rate: int


def _costs_as_of(
    session: Session, day: date
) -> Dict[int, Tuple[str, Decimal, Decimal]]:
    """截至某日各子项的（成本币种, 数量, 累计成本）。"""
    result: Dict[int, Tuple[str, Decimal, Decimal]] = {}
    rows = session.execute(
        select(
            PositionLot.item_id,
            PositionLot.currency,
            func.sum(PositionLot.quantity),
            func.sum(PositionLot.quantity * PositionLot.unit_cost + PositionLot.fee),
        )
        .where(PositionLot.trade_date <= day)
        .group_by(PositionLot.item_id, PositionLot.currency)
    ).all()
    for item_id, currency, quantity, total in rows:
        current = result.get(item_id)
        if current is None:
            result[item_id] = (
                currency,
                Decimal(str(quantity or 0)),
                to_money(total),
            )
        else:
            result[item_id] = (
                current[0],
                current[1] + Decimal(str(quantity or 0)),
                to_money(current[2] + (total or 0)),
            )
    return result


def period_profit_rows(
    session: Session,
    start: date,
    end: date,
    include_archived: bool = False,
    today: Optional[date] = None,
) -> List[PeriodProfitRow]:
    """统计 [start, end] 区间的盈亏变化，按子项返回明细。"""
    day = today or date.today()
    end_day = min(end, day)
    if start > end_day:
        return []
    start_ref = start - timedelta(days=1)
    lookup = exchange_rates.build_rate_lookup(session)
    known = set(exchange_rates.latest_rates(session))
    start_holdings = {
        holding.item_id: holding
        for holding in analytics.holdings_as_of(session, start_ref)
    }
    end_holdings = {
        holding.item_id: holding
        for holding in analytics.holdings_as_of(session, end_day)
    }
    start_costs = _costs_as_of(session, start_ref)
    end_costs = _costs_as_of(session, end_day)
    overviews = account_service.list_overviews(
        session, include_archived=include_archived
    )

    result: List[PeriodProfitRow] = []
    for account in overviews:
        if account.side != SIDE_ASSET:
            continue
        for item in account.items:
            end_info = end_costs.get(item.id)
            if end_info is None:
                continue
            cost_currency, quantity, end_cost = end_info
            start_info = start_costs.get(item.id)
            start_cost = start_info[2] if start_info is not None else Decimal("0.00")
            start_holding = start_holdings.get(item.id)
            end_holding = end_holdings.get(item.id)
            start_value = start_holding.value if start_holding else None
            end_value = end_holding.value if end_holding else None

            start_in_cost = _convert(
                start_value if start_value is not None else Decimal("0.00"),
                item.currency,
                cost_currency,
                start_ref,
                lookup,
                known,
            )
            end_in_cost = _convert(
                end_value, item.currency, cost_currency, end_day, lookup, known
            )
            pnl: Optional[Decimal] = None
            if start_in_cost is not None and end_in_cost is not None:
                pnl = to_money(
                    (end_in_cost - end_cost) - (start_in_cost - start_cost)
                )
            pnl_rate = (
                ratio(pnl, start_cost)
                if pnl is not None and start_cost > 0
                else None
            )
            pnl_cny = (
                _convert(pnl, cost_currency, "CNY", end_day, lookup, known)
                if pnl is not None
                else None
            )
            start_cost_cny = _convert(
                start_cost, cost_currency, "CNY", start_ref, lookup, known
            )
            end_value_cny = (
                _convert(end_value, item.currency, "CNY", end_day, lookup, known)
                if end_value is not None
                else None
            )
            result.append(
                PeriodProfitRow(
                    account_id=account.id,
                    account_name=account.name,
                    item_id=item.id,
                    item_name=item.name,
                    category=item.category,
                    side=account.side,
                    currency=item.currency,
                    cost_currency=cost_currency,
                    quantity=quantity,
                    start_value=start_value,
                    end_value=end_value,
                    start_cost=start_cost,
                    end_cost=end_cost,
                    pnl=pnl,
                    pnl_rate=pnl_rate,
                    pnl_cny=pnl_cny,
                    start_cost_cny=start_cost_cny,
                    end_value_cny=end_value_cny,
                    start_value_date=start_holding.snapshot_date if start_holding else None,
                    end_value_date=end_holding.snapshot_date if end_holding else None,
                )
            )
    result.sort(
        key=lambda row: (
            row.pnl_cny is None,
            -row.pnl_cny if row.pnl_cny else Decimal("0"),
        )
    )
    return result


def period_summary(
    rows: Sequence[PeriodProfitRow], start: date, end: date
) -> PeriodSummary:
    """区间汇总（人民币口径），仅统计可折算的行。"""
    pnl = Decimal("0.00")
    value = Decimal("0.00")
    cost = Decimal("0.00")
    missing = 0
    for row in rows:
        if (
            row.pnl_cny is None
            or row.end_value_cny is None
            or row.start_cost_cny is None
        ):
            missing += 1
            continue
        pnl += row.pnl_cny
        value += row.end_value_cny
        cost += row.start_cost_cny
    return PeriodSummary(
        start=start,
        end=min(end, date.today()),
        pnl_cny=to_money(pnl),
        end_value_cny=to_money(value),
        start_cost_cny=to_money(cost),
        pnl_rate=ratio(pnl, cost) if cost > 0 else None,
        item_count=len(rows),
        missing_rate=missing,
    )


def account_profit_rows(
    session: Session,
    start: Optional[date] = None,
    end: Optional[date] = None,
    include_archived: bool = False,
    today: Optional[date] = None,
) -> List[AccountProfitRow]:
    """按账户汇总：资产账户为投资收益，负债账户为计息支出。

    start 为空表示累计口径；否则统计 [start, end] 区间。
    """
    day = today or date.today()
    overviews = account_service.list_overviews(
        session, include_archived=include_archived
    )
    meta = {account.id: account for account in overviews}
    buckets: Dict[int, Dict[str, Decimal]] = {
        account.id: {
            "value": Decimal("0.00"),
            "cost": Decimal("0.00"),
            "pnl": Decimal("0.00"),
            "interest": Decimal("0.00"),
            "items": Decimal("0"),
            "missing": Decimal("0"),
        }
        for account in overviews
    }

    if start is None:
        asset_rows = profit_rows(session, include_archived=include_archived, today=day)
        interest_rows = interest_service.interest_rows(
            session, None, day, include_archived=include_archived, today=day
        )
    else:
        asset_rows = period_profit_rows(
            session, start, end or day, include_archived=include_archived, today=day
        )
        interest_rows = interest_service.interest_rows(
            session, start, end or day, include_archived=include_archived, today=day
        )

    for row in asset_rows:
        bucket = buckets.get(row.account_id)
        if bucket is None:
            continue
        bucket["items"] += 1
        if start is None:
            value, cost, pnl = row.value_cny, row.cost_cny, row.pnl_cny
        else:
            value, cost, pnl = row.end_value_cny, row.start_cost_cny, row.pnl_cny
        if value is None or cost is None or pnl is None:
            bucket["missing"] += 1
            continue
        bucket["value"] += value
        bucket["cost"] += cost
        bucket["pnl"] += pnl

    interest_by_account: Dict[int, List[interest_service.InterestRow]] = {}
    for row in interest_rows:
        bucket = buckets.get(row.account_id)
        if bucket is None:
            continue
        if row.interest_cny is None:
            bucket["missing"] += 1
            continue
        bucket["interest"] += row.interest_cny
        bucket["items"] += 1
        interest_by_account.setdefault(row.account_id, []).append(row)

    result: List[AccountProfitRow] = []
    for account_id, bucket in buckets.items():
        account = meta[account_id]
        if bucket["items"] == 0:
            continue
        if account.side == SIDE_LIABILITY:
            interest = to_money(bucket["interest"])
            details = interest_by_account.get(account_id, [])
            if len(details) == 1:
                detail = details[0]
                note = f"年利率 {detail.rate}%"
                if detail.start:
                    note += f" · 自 {detail.start:%Y-%m-%d}"
                if detail.missing_snapshot:
                    note += " · 缺期初快照"
            else:
                note = f"{len(details)} 项计息"
            result.append(
                AccountProfitRow(
                    account_id=account_id,
                    account_name=account.name,
                    side=account.side,
                    currency=account.display_currency,
                    value_cny=None,
                    cost_cny=None,
                    pnl_cny=-interest,
                    pnl_rate=None,
                    interest_cny=interest,
                    item_count=int(bucket["items"]),
                    note=note,
                )
            )
            continue
        value = to_money(bucket["value"])
        cost = to_money(bucket["cost"])
        pnl = to_money(bucket["pnl"])
        note = f"{int(bucket['missing'])} 项缺估值或汇率" if bucket["missing"] else ""
        result.append(
            AccountProfitRow(
                account_id=account_id,
                account_name=account.name,
                side=account.side,
                currency=account.display_currency,
                value_cny=value,
                cost_cny=cost,
                pnl_cny=pnl,
                pnl_rate=ratio(pnl, cost) if cost > 0 else None,
                interest_cny=None,
                item_count=int(bucket["items"]),
                note=note,
            )
        )
    result.sort(
        key=lambda row: (
            row.side == SIDE_LIABILITY,
            -(row.interest_cny if row.side == SIDE_LIABILITY else (row.pnl_cny or Decimal("0"))),
        )
    )
    return result


def account_profit_summary(
    rows: Sequence[AccountProfitRow],
) -> AccountProfitSummary:
    """账户级汇总：净收益 = 投资收益 − 利息支出。"""
    investment = Decimal("0.00")
    interest = Decimal("0.00")
    value = Decimal("0.00")
    cost = Decimal("0.00")
    missing = 0
    for row in rows:
        if row.side == SIDE_LIABILITY:
            if row.interest_cny is not None:
                interest += row.interest_cny
            continue
        if row.pnl_cny is None or row.cost_cny is None or row.value_cny is None:
            missing += 1
            continue
        investment += row.pnl_cny
        value += row.value_cny
        cost += row.cost_cny
    return AccountProfitSummary(
        investment_cny=to_money(investment),
        interest_cny=to_money(interest),
        net_cny=to_money(investment - interest),
        value_cny=to_money(value),
        cost_cny=to_money(cost),
        account_count=len(rows),
        missing=missing,
    )
