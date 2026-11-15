"""金额解析与格式化。

应用内所有金额均以 Decimal 表示，数据库为 NUMERIC(18,2)。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("9999999999999999.99")  # NUMERIC(18,2) 上限


class AmountError(ValueError):
    """金额格式或范围不合法。"""


def parse_amount(text: object, field: str = "金额", allow_zero: bool = True) -> Decimal:
    """把用户输入解析为两位小数的非负 Decimal。"""
    raw = "" if text is None else str(text)
    normalized = (
        raw.strip()
        .replace(",", "")
        .replace("，", "")
        .replace(" ", "")
        .replace("￥", "")
        .replace("¥", "")
    )
    if not normalized:
        raise AmountError(f"{field}不能为空")
    try:
        value = Decimal(normalized)
    except (InvalidOperation, ValueError):
        raise AmountError(f"{field}必须是数字") from None
    if not value.is_finite():
        raise AmountError(f"{field}必须是有效数字")
    if value < 0:
        raise AmountError(f"{field}不能为负数")
    if value == 0 and not allow_zero:
        raise AmountError(f"{field}必须大于 0")
    if value > MAX_AMOUNT:
        raise AmountError(f"{field}超出可存储范围")
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def to_money(value: object) -> Decimal:
    """把数据库返回值统一成两位小数 Decimal。"""
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt_money(
    value: object,
    symbol: str = "¥",
    show_sign: bool = False,
    placeholder: str = "—",
) -> str:
    """格式化金额，例如 ¥1,234.00 / +¥1,234.00。"""
    if value is None:
        return placeholder
    amount = to_money(value)
    if amount < 0:
        sign = "-"
    elif show_sign and amount > 0:
        sign = "+"
    else:
        sign = ""
    return f"{sign}{symbol}{abs(amount):,.2f}"


def fmt_signed_money(value: object, symbol: str = "¥", placeholder: str = "—") -> str:
    if value is None:
        return placeholder
    return fmt_money(value, symbol=symbol, show_sign=True)


def fmt_percent(value: object, show_sign: bool = True, digits: int = 2) -> str:
    if value is None:
        return "—"
    d = Decimal(str(value))
    sign = "+" if show_sign and d > 0 else ""
    return f"{sign}{d:.{digits}f}%"


def ratio(part: Decimal, total: Decimal) -> Decimal:
    """安全计算百分比数值（0-100），total 为 0 时返回 0。"""
    if total is None or total == 0:
        return Decimal("0")
    return (part / total * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
