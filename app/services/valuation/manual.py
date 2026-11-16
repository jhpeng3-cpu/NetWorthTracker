"""手动估值与到期提醒。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, object_session

from app.db.models import (
    VALUATION_MANUAL,
    Account,
    AccountItem,
    ValuationSnapshot,
)
from app.services.valuation.base import ValuationResult, Valuator


@dataclass(frozen=True)
class OverdueValuation:
    account_name: str
    item_name: str
    due_date: date


class ManualValuator(Valuator):
    """直接采用最近一条估值快照。"""

    mode = VALUATION_MANUAL

    def estimate(
        self, item: AccountItem, on_date: date
    ) -> Optional[ValuationResult]:
        latest = self._latest_snapshot(item)
        if latest is None:
            return None
        stale = (
            item.next_valuation is not None and item.next_valuation < on_date
        )
        note = f"最近估值 {latest.snapshot_date:%Y-%m-%d}"
        if stale:
            note += " · 待更新"
        return ValuationResult(
            value=latest.value,
            currency=item.currency or "CNY",
            note=note,
            stale=stale,
            as_of=latest.snapshot_date,
        )

    @staticmethod
    def _latest_snapshot(item: AccountItem):
        """优先查询数据库，避免关系缓存拿到旧数据。"""
        session = object_session(item)
        if session is not None:
            return session.scalar(
                select(ValuationSnapshot)
                .where(ValuationSnapshot.item_id == item.id)
                .order_by(ValuationSnapshot.snapshot_date.desc())
                .limit(1)
            )
        snapshots = list(item.snapshots)
        if not snapshots:
            return None
        return max(snapshots, key=lambda entry: entry.snapshot_date)


def overdue_manual_items(
    session: Session, on_date: Optional[date] = None
) -> List[OverdueValuation]:
    """手动估值且已过提醒日、仍未录入更新快照的子项。"""
    day = on_date or date.today()
    latest = (
        select(
            ValuationSnapshot.item_id.label("item_id"),
            func.max(ValuationSnapshot.snapshot_date).label("latest_date"),
        )
        .group_by(ValuationSnapshot.item_id)
        .subquery()
    )
    rows = session.execute(
        select(Account.name, AccountItem.name, AccountItem.next_valuation)
        .join(Account, Account.id == AccountItem.account_id)
        .outerjoin(latest, latest.c.item_id == AccountItem.id)
        .where(
            Account.side == "asset",
            Account.archived.is_(False),
            AccountItem.valuation_mode == VALUATION_MANUAL,
            AccountItem.next_valuation.is_not(None),
            AccountItem.next_valuation < day,
            or_(
                latest.c.latest_date.is_(None),
                latest.c.latest_date <= AccountItem.next_valuation,
            ),
        )
        .order_by(AccountItem.next_valuation, Account.name)
    ).all()
    return [
        OverdueValuation(
            account_name=row[0], item_name=row[1], due_date=row[2]
        )
        for row in rows
    ]
