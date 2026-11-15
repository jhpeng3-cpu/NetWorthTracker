"""估值快照服务。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account, CATEGORY_LABELS, SIDE_LABELS, ValuationSnapshot
from app.utils.money import fmt_money, parse_amount


class SnapshotValidationError(ValueError):
    pass


class SnapshotExistsError(Exception):
    def __init__(self, snapshot_date: date, value: Decimal):
        self.snapshot_date = snapshot_date
        self.value = value
        super().__init__(
            f"{snapshot_date.strftime('%Y-%m-%d')} 已有一条估值 {fmt_money(value)}，"
            "是否覆盖？"
        )


class SnapshotNotFound(LookupError):
    pass


class BatchConflictError(Exception):
    def __init__(self, names: Sequence[str]):
        self.names = list(names)
        preview = "、".join(self.names[:5])
        if len(self.names) > 5:
            preview += f" 等 {len(self.names)} 个账户"
        super().__init__(f"{preview} 在该日期已有快照。")


@dataclass(frozen=True)
class SnapshotRow:
    id: int
    account_id: int
    account_name: str
    side: str
    category: str
    snapshot_date: date
    value: Decimal
    note: str
    created_at: Optional[datetime]

    @property
    def side_label(self) -> str:
        return SIDE_LABELS.get(self.side, self.side)

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)


@dataclass(frozen=True)
class BatchEntry:
    account_id: int
    value: Decimal
    note: str = ""


@dataclass(frozen=True)
class BatchSaveResult:
    created: int
    updated: int

    @property
    def total(self) -> int:
        return self.created + self.updated


@dataclass(frozen=True)
class BatchRow:
    account_id: int
    account_name: str
    side: str
    category: str
    latest_value: Optional[Decimal]
    latest_date: Optional[date]
    existing_value: Optional[Decimal]
    existing_note: str


def _validate_value(value: object) -> Decimal:
    return parse_amount(value, field="估值")


def _validate_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise SnapshotValidationError("请选择估值日期。")


def get_snapshot(session: Session, snapshot_id: int) -> ValuationSnapshot:
    snapshot = session.get(ValuationSnapshot, snapshot_id)
    if snapshot is None:
        raise SnapshotNotFound("快照不存在，可能已被删除。")
    return snapshot


def get_snapshot_for_account(
    session: Session, account_id: int, snapshot_date: date
) -> Optional[ValuationSnapshot]:
    return session.scalar(
        select(ValuationSnapshot).where(
            ValuationSnapshot.account_id == account_id,
            ValuationSnapshot.snapshot_date == snapshot_date,
        )
    )


def save_snapshot(
    session: Session,
    account_id: int,
    snapshot_date: date,
    value: object,
    note: str = "",
    overwrite: bool = False,
) -> tuple[int, bool]:
    """保存单条快照。返回 (快照 id, 是否更新已有记录)。"""
    day = _validate_date(snapshot_date)
    amount = _validate_value(value)
    existing = get_snapshot_for_account(session, account_id, day)
    if existing is not None and not overwrite:
        raise SnapshotExistsError(day, existing.value)
    if existing is not None:
        existing.value = amount
        existing.note = (note or "").strip() or None
        session.commit()
        return int(existing.id), True

    snapshot = ValuationSnapshot(
        account_id=account_id,
        snapshot_date=day,
        value=amount,
        note=(note or "").strip() or None,
    )
    session.add(snapshot)
    session.commit()
    return int(snapshot.id), False


def update_snapshot(
    session: Session,
    snapshot_id: int,
    snapshot_date: date,
    value: object,
    note: str = "",
) -> None:
    snapshot = get_snapshot(session, snapshot_id)
    day = _validate_date(snapshot_date)
    amount = _validate_value(value)
    conflict = session.scalar(
        select(ValuationSnapshot).where(
            ValuationSnapshot.account_id == snapshot.account_id,
            ValuationSnapshot.snapshot_date == day,
            ValuationSnapshot.id != snapshot.id,
        )
    )
    if conflict is not None:
        raise SnapshotExistsError(day, conflict.value)
    snapshot.snapshot_date = day
    snapshot.value = amount
    snapshot.note = (note or "").strip() or None
    session.commit()


def delete_snapshot(session: Session, snapshot_id: int) -> None:
    snapshot = get_snapshot(session, snapshot_id)
    session.delete(snapshot)
    session.commit()


def list_snapshots(
    session: Session,
    account_id: Optional[int] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    limit: Optional[int] = 2000,
) -> List[SnapshotRow]:
    stmt = (
        select(
            ValuationSnapshot.id,
            ValuationSnapshot.account_id,
            Account.name.label("account_name"),
            Account.side,
            Account.category,
            ValuationSnapshot.snapshot_date,
            ValuationSnapshot.value,
            ValuationSnapshot.note,
            ValuationSnapshot.created_at,
        )
        .join(Account, Account.id == ValuationSnapshot.account_id)
        .order_by(ValuationSnapshot.snapshot_date.desc(), Account.name)
    )
    if account_id is not None:
        stmt = stmt.where(ValuationSnapshot.account_id == account_id)
    if start is not None:
        stmt = stmt.where(ValuationSnapshot.snapshot_date >= start)
    if end is not None:
        stmt = stmt.where(ValuationSnapshot.snapshot_date <= end)
    if limit is not None:
        stmt = stmt.limit(limit)

    return [
        SnapshotRow(
            id=row.id,
            account_id=row.account_id,
            account_name=row.account_name,
            side=row.side,
            category=row.category,
            snapshot_date=row.snapshot_date,
            value=row.value,
            note=row.note or "",
            created_at=row.created_at,
        )
        for row in session.execute(stmt).all()
    ]


def batch_context(session: Session, on_date: date) -> List[BatchRow]:
    """批量录入页数据：未归档账户 + 当日已有快照。"""
    from app.services.accounts import list_overviews

    overviews = list_overviews(session, include_archived=False)
    existing = {
        row.account_id: row
        for row in session.execute(
            select(
                ValuationSnapshot.account_id,
                ValuationSnapshot.value,
                ValuationSnapshot.note,
            ).where(ValuationSnapshot.snapshot_date == on_date)
        ).all()
    }
    result = []
    for overview in overviews:
        current = existing.get(overview.id)
        result.append(
            BatchRow(
                account_id=overview.id,
                account_name=overview.name,
                side=overview.side,
                category=overview.category,
                latest_value=overview.latest_value,
                latest_date=overview.latest_date,
                existing_value=current.value if current else None,
                existing_note=(current.note or "") if current else "",
            )
        )
    return result


def save_batch(
    session: Session,
    snapshot_date: date,
    entries: Iterable[BatchEntry],
    overwrite: bool = False,
) -> BatchSaveResult:
    day = _validate_date(snapshot_date)
    cleaned = {}
    for entry in entries:
        cleaned[entry.account_id] = BatchEntry(
            account_id=entry.account_id,
            value=_validate_value(entry.value),
            note=(entry.note or "").strip(),
        )
    if not cleaned:
        return BatchSaveResult(created=0, updated=0)

    account_ids = list(cleaned.keys())
    existing = {
        row.account_id: row
        for row in session.scalars(
            select(ValuationSnapshot).where(
                ValuationSnapshot.account_id.in_(account_ids),
                ValuationSnapshot.snapshot_date == day,
            )
        )
    }
    if existing and not overwrite:
        names = list(
            session.scalars(select(Account.name).where(Account.id.in_(list(existing.keys()))))
        )
        raise BatchConflictError(names)

    created = 0
    updated = 0
    for account_id, entry in cleaned.items():
        snapshot = existing.get(account_id)
        if snapshot is not None:
            snapshot.value = entry.value
            snapshot.note = entry.note or None
            updated += 1
        else:
            session.add(
                ValuationSnapshot(
                    account_id=account_id,
                    snapshot_date=day,
                    value=entry.value,
                    note=entry.note or None,
                )
            )
            created += 1
    session.commit()
    return BatchSaveResult(created=created, updated=updated)
