"""批量刷新估值并写入快照。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account, AccountItem
from app.services import snapshots
from app.services.valuation.registry import valuator_for

STATUS_UPDATED = "updated"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class ItemOutcome:
    item_id: int
    item_name: str
    account_name: str
    status: str
    message: str = ""
    stale: bool = False


@dataclass
class RefreshReport:
    outcomes: List[ItemOutcome] = field(default_factory=list)

    @property
    def updated(self) -> int:
        return sum(1 for row in self.outcomes if row.status == STATUS_UPDATED)

    @property
    def skipped(self) -> int:
        return sum(1 for row in self.outcomes if row.status == STATUS_SKIPPED)

    @property
    def failed(self) -> int:
        return sum(1 for row in self.outcomes if row.status == STATUS_FAILED)

    @property
    def stale(self) -> int:
        return sum(
            1
            for row in self.outcomes
            if row.status == STATUS_UPDATED and row.stale
        )


def refresh_all(
    session: Session,
    on_date: Optional[date] = None,
    overwrite: bool = True,
) -> RefreshReport:
    """刷新全部资产子项；单项失败不影响其它项。"""
    day = on_date or date.today()
    report = RefreshReport()
    rows = session.execute(
        select(AccountItem, Account)
        .join(Account, Account.id == AccountItem.account_id)
        .where(Account.side == "asset", Account.archived.is_(False))
        .order_by(Account.name, AccountItem.sort_order, AccountItem.id)
    ).all()
    for item, account in rows:
        valuator = valuator_for(item)
        if valuator is None:
            report.outcomes.append(
                ItemOutcome(
                    item.id, item.name, account.name, STATUS_SKIPPED,
                    "暂不支持该估值方式",
                )
            )
            continue
        try:
            result = valuator.estimate(item, day)
        except Exception as exc:  # noqa: BLE001 - 单项失败不中断整体
            report.outcomes.append(
                ItemOutcome(item.id, item.name, account.name, STATUS_FAILED, str(exc))
            )
            continue
        if result is None:
            report.outcomes.append(
                ItemOutcome(
                    item.id, item.name, account.name, STATUS_SKIPPED,
                    "缺少估值参数",
                )
            )
            continue
        try:
            snapshots.save_snapshot(
                session,
                item.id,
                day,
                result.value,
                note=result.note,
                overwrite=overwrite,
            )
        except Exception as exc:  # noqa: BLE001
            report.outcomes.append(
                ItemOutcome(item.id, item.name, account.name, STATUS_FAILED, str(exc))
            )
            continue
        report.outcomes.append(
            ItemOutcome(
                item.id,
                item.name,
                account.name,
                STATUS_UPDATED,
                result.note,
                stale=result.stale,
            )
        )
    return report
