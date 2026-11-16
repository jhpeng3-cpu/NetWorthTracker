"""计息类资产估值：活期、定期存款与债券。

利率按百分比（如 4.25 表示 4.25%），天数按实际天数 / 365 计算。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from app.db.models import VALUATION_ACCRUAL, AccountItem
from app.services.valuation.base import ValuationResult, Valuator
from app.utils.dates import add_months

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
DAYS_IN_YEAR = Decimal("365")
# 复利滚存周期（月）；at_maturity 不逐期滚存
PERIOD_MONTHS = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}


def _rate_fraction(annual_rate_percent: Decimal) -> Decimal:
    return Decimal(str(annual_rate_percent)) / HUNDRED


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def interest_days(start: date, end: date) -> int:
    """实际计息天数，负数按 0 处理。"""
    return max((end - start).days, 0)


def simple_interest(
    principal: Decimal,
    annual_rate_percent: Decimal,
    start: date,
    end: date,
) -> Decimal:
    """单利：本金 × 年利率 × 实际天数 / 365。"""
    days = interest_days(start, end)
    return _money(principal * _rate_fraction(annual_rate_percent) * Decimal(days) / DAYS_IN_YEAR)


def compound_value(
    principal: Decimal,
    annual_rate_percent: Decimal,
    start: date,
    end: date,
    pay_frequency: str,
) -> Decimal:
    """按付息周期逐期滚存，末期不足一个周期时按天单利。"""
    months = PERIOD_MONTHS.get(pay_frequency)
    if not months or end <= start:
        return _money(principal)
    balance = principal
    periods = 0
    rate = _rate_fraction(annual_rate_percent)
    while True:
        period_end = add_months(start, months * (periods + 1))
        if period_end > end:
            break
        balance += balance * rate * Decimal(months) / Decimal("12")
        periods += 1
        if periods > 10000:  # 防御异常参数导致死循环
            break
    cursor = add_months(start, months * periods) if periods else start
    days = interest_days(cursor, end)
    if days:
        balance += balance * rate * Decimal(days) / DAYS_IN_YEAR
    return _money(balance)


def deposit_value(
    principal: Decimal,
    annual_rate_percent: Optional[Decimal],
    start: date,
    on_date: date,
    compounding: str = "simple",
    pay_frequency: str = "none",
    maturity_date: Optional[date] = None,
) -> Decimal:
    """存款在指定日期的本息合计；到期后停止计息。"""
    if annual_rate_percent is None:
        return _money(principal)
    end = min(on_date, maturity_date) if maturity_date else on_date
    if end <= start:
        return _money(principal)
    if compounding == "compound" and pay_frequency in PERIOD_MONTHS:
        return compound_value(principal, annual_rate_percent, start, end, pay_frequency)
    return _money(principal + simple_interest(principal, annual_rate_percent, start, end))


def early_withdraw_value(
    principal: Decimal,
    early_rate_percent: Optional[Decimal],
    start: date,
    on_date: date,
) -> Decimal:
    """定期提前支取：按提前支取利率对已过天数重算利息。"""
    if early_rate_percent is None:
        return _money(principal)
    return _money(principal + simple_interest(principal, early_rate_percent, start, on_date))


def bond_accrued_interest(
    face_value: Decimal,
    coupon_rate_percent: Optional[Decimal],
    start: date,
    on_date: date,
    maturity_date: Optional[date] = None,
) -> Decimal:
    """债券应计利息：面值 × 票面利率 × 已过天数 / 365。"""
    if coupon_rate_percent is None:
        return Decimal("0.00")
    end = min(on_date, maturity_date) if maturity_date else on_date
    return simple_interest(face_value, coupon_rate_percent, start, end)


def bond_full_price(
    face_value: Decimal,
    coupon_rate_percent: Optional[Decimal],
    start: date,
    on_date: date,
    maturity_date: Optional[date] = None,
) -> Decimal:
    """全价 = 面值（净价） + 应计利息。"""
    return _money(face_value + bond_accrued_interest(
        face_value, coupon_rate_percent, start, on_date, maturity_date
    ))


class AccrualValuator(Valuator):
    """存款与债券的计息估值器。"""

    mode = VALUATION_ACCRUAL

    def estimate(
        self, item: AccountItem, on_date: date
    ) -> Optional[ValuationResult]:
        rate = item.interest_rate
        start = item.interest_start
        if start is None and item.created_at is not None:
            start = item.created_at.date()
        if start is None or rate is None:
            return None

        if item.category == "bond":
            base = item.face_value if item.face_value is not None else item.principal
            if not base:
                return None
            value = bond_full_price(
                base, rate, start, on_date, item.maturity_date
            )
            note = "面值 + 应计利息"
        else:
            base = item.principal if item.principal is not None else item.face_value
            if not base:
                return None
            value = deposit_value(
                base,
                rate,
                start,
                on_date,
                item.compounding or "simple",
                item.pay_frequency or "none",
                item.maturity_date,
            )
            note = "本金 + 应计利息"

        return ValuationResult(
            value=value,
            currency=item.currency or "CNY",
            note=note,
            stale=False,
            as_of=on_date,
        )
