"""现金流服务：记录与查询利息、分红、租金、费用及买卖流水。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import FLOW_TYPES, AccountItem, CashFlow
from app.utils.exceptions import AppRuntimeError


class CashFlowError(AppRuntimeError):
    pass


@dataclass(frozen=True)
class FlowSummary:
    flow_type: str
    total: Decimal
    count: int


def add_flow(
    session: Session,
    item_id: int,
    flow_date: date,
    flow_type: str,
    amount: Decimal,
    currency: str = "CNY",
    quantity: Optional[Decimal] = None,
    unit_price: Optional[Decimal] = None,
    fee: Decimal = Decimal("0"),
    note: str = "",
    commit: bool = True,
) -> CashFlow:
    """写入一条现金流；金额与费用必须为非负数。"""
    if flow_type not in FLOW_TYPES:
        raise CashFlowError(f"未知的现金流类型：{flow_type}")
    if session.get(AccountItem, item_id) is None:
        raise CashFlowError("关联的资产子项不存在。")
    if amount is None or amount < 0:
        raise CashFlowError("金额必须是非负数字。")
    if fee is None or fee < 0:
        raise CashFlowError("费用必须是非负数字。")
    flow = CashFlow(
        item_id=item_id,
        flow_date=flow_date,
        flow_type=flow_type,
        amount=amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        currency=(currency or "CNY").strip().upper(),
        quantity=(
            quantity.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if quantity is not None
            else None
        ),
        unit_price=(
            unit_price.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            if unit_price is not None
            else None
        ),
        fee=fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        note=note.strip() or None,
    )
    session.add(flow)
    if commit:
        session.commit()
    return flow


def list_flows(
    session: Session,
    item_id: int,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> List[CashFlow]:
    query = select(CashFlow).where(CashFlow.item_id == item_id)
    if start is not None:
        query = query.where(CashFlow.flow_date >= start)
    if end is not None:
        query = query.where(CashFlow.flow_date <= end)
    return list(
        session.scalars(query.order_by(CashFlow.flow_date, CashFlow.id))
    )


def delete_flow(session: Session, flow_id: int) -> bool:
    flow = session.get(CashFlow, flow_id)
    if flow is None:
        return False
    session.delete(flow)
    session.commit()
    return True


def summarize(
    session: Session,
    item_id: int,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> Dict[str, FlowSummary]:
    """按类型汇总现金流，供收益报表使用。"""
    totals: Dict[str, FlowSummary] = {}
    for flow in list_flows(session, item_id, start, end):
        current = totals.get(flow.flow_type)
        if current is None:
            totals[flow.flow_type] = FlowSummary(
                flow_type=flow.flow_type, total=flow.amount, count=1
            )
        else:
            totals[flow.flow_type] = FlowSummary(
                flow_type=flow.flow_type,
                total=current.total + flow.amount,
                count=current.count + 1,
            )
    return totals
