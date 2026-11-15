"""CSV 导出 / 导入（UTF-8 with BOM，Excel 可直接打开）。"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account, CATEGORY_LABELS, SIDE_LABELS, ValuationSnapshot
from app.services import accounts as account_service
from app.services import snapshots as snapshot_service
from app.utils.exceptions import AppRuntimeError
from app.utils.money import AmountError, parse_amount

IMPORT_REQUIRED_HEADERS = ("account_name", "snapshot_date", "value")
IMPORT_TEMPLATE = "account_name,snapshot_date,value,note\n"

DUPLICATE_SKIP = "skip"
DUPLICATE_OVERWRITE = "overwrite"


class CsvError(AppRuntimeError):
    pass


@dataclass
class ImportRow:
    line_no: int
    account_name: str = ""
    date_text: str = ""
    value_text: str = ""
    note: str = ""
    account_id: Optional[int] = None
    snapshot_date: Optional[date] = None
    value: Optional[Decimal] = None
    exists: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.errors:
            return "错误"
        if self.exists:
            return "已存在"
        return "新增"

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ImportResult:
    created: int
    updated: int
    skipped: int
    invalid: int

    @property
    def total_written(self) -> int:
        return self.created + self.updated


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CsvError("无法识别文件编码，请使用 UTF-8 或 GBK 编码的 CSV。")


def read_snapshot_csv(path: Path) -> List[ImportRow]:
    text = _read_text(path)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise CsvError("CSV 文件为空或缺少表头。")
    headers = [name.strip() for name in reader.fieldnames]
    missing = [name for name in IMPORT_REQUIRED_HEADERS if name not in headers]
    if missing:
        raise CsvError("CSV 缺少必需列：" + "、".join(missing))

    rows: List[ImportRow] = []
    for index, raw in enumerate(reader, start=2):
        normalized = {(key or "").strip(): (value or "").strip() for key, value in raw.items()}
        if not any(normalized.values()):
            continue
        rows.append(
            ImportRow(
                line_no=index,
                account_name=normalized.get("account_name", ""),
                date_text=normalized.get("snapshot_date", ""),
                value_text=normalized.get("value", ""),
                note=normalized.get("note", ""),
            )
        )
    if not rows:
        raise CsvError("CSV 中没有数据行。")
    return rows


def _parse_date(text: str) -> date:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError("日期格式应为 YYYY-MM-DD")


def validate_import_rows(session: Session, rows: Sequence[ImportRow]) -> List[ImportRow]:
    account_rows = session.execute(select(Account.id, Account.name, Account.archived)).all()
    account_map = {row.name: (row.id, bool(row.archived)) for row in account_rows}

    for row in rows:
        row.errors = []
        row.account_id = None
        row.snapshot_date = None
        row.value = None
        row.exists = False

        if not row.account_name:
            row.errors.append("账户名称为空")
        else:
            account = account_map.get(row.account_name)
            if account is None:
                row.errors.append("账户不存在")
            elif account[1]:
                row.errors.append("账户已归档")
            else:
                row.account_id = account[0]

        try:
            row.snapshot_date = _parse_date(row.date_text)
        except ValueError as exc:
            row.errors.append(str(exc))

        try:
            row.value = parse_amount(row.value_text, field="估值")
        except AmountError as exc:
            row.errors.append(str(exc))

    seen: Dict[Tuple[int, date], int] = {}
    for row in rows:
        if row.account_id is None or row.snapshot_date is None:
            continue
        key = (row.account_id, row.snapshot_date)
        if key in seen:
            row.errors.append(f"与第 {seen[key]} 行账户和日期重复")
        else:
            seen[key] = row.line_no

    valid_pairs = {
        (row.account_id, row.snapshot_date)
        for row in rows
        if row.account_id is not None and row.snapshot_date is not None
    }
    if valid_pairs:
        account_ids = {pair[0] for pair in valid_pairs}
        dates = {pair[1] for pair in valid_pairs}
        existing = {
            (row.account_id, row.snapshot_date)
            for row in session.execute(
                select(ValuationSnapshot.account_id, ValuationSnapshot.snapshot_date).where(
                    ValuationSnapshot.account_id.in_(account_ids),
                    ValuationSnapshot.snapshot_date.in_(dates),
                )
            ).all()
        }
        for row in rows:
            if row.account_id is not None and row.snapshot_date is not None:
                row.exists = (row.account_id, row.snapshot_date) in existing
    return list(rows)


def import_rows(
    session: Session,
    rows: Sequence[ImportRow],
    duplicate_policy: str = DUPLICATE_SKIP,
    skip_invalid: bool = True,
) -> ImportResult:
    invalid_rows = [row for row in rows if not row.is_valid]
    if invalid_rows and not skip_invalid:
        preview = "；".join(
            f"第 {row.line_no} 行：{'、'.join(row.errors)}" for row in invalid_rows[:5]
        )
        raise CsvError(f"存在无效数据，未执行导入。{preview}")

    created = 0
    updated = 0
    skipped = 0
    for row in rows:
        if not row.is_valid:
            continue
        if row.account_id is None or row.snapshot_date is None or row.value is None:
            continue
        existing = session.scalar(
            select(ValuationSnapshot).where(
                ValuationSnapshot.account_id == row.account_id,
                ValuationSnapshot.snapshot_date == row.snapshot_date,
            )
        )
        if existing is not None:
            if duplicate_policy == DUPLICATE_OVERWRITE:
                existing.value = row.value
                existing.note = row.note or None
                updated += 1
            else:
                skipped += 1
            continue
        session.add(
            ValuationSnapshot(
                account_id=row.account_id,
                snapshot_date=row.snapshot_date,
                value=row.value,
                note=row.note or None,
            )
        )
        created += 1
    session.commit()
    return ImportResult(
        created=created,
        updated=updated,
        skipped=skipped,
        invalid=len(invalid_rows),
    )


def export_accounts(session: Session, path: Path) -> int:
    overviews = account_service.list_overviews(session, include_archived=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(
            [
                "id",
                "name",
                "side",
                "side_label",
                "category",
                "category_label",
                "currency",
                "note",
                "archived",
                "latest_value",
                "latest_date",
            ]
        )
        for item in overviews:
            writer.writerow(
                [
                    item.id,
                    item.name,
                    item.side,
                    SIDE_LABELS.get(item.side, item.side),
                    item.category,
                    CATEGORY_LABELS.get(item.category, item.category),
                    item.currency,
                    item.note,
                    "true" if item.archived else "false",
                    f"{item.latest_value:.2f}" if item.latest_value is not None else "",
                    item.latest_date.isoformat() if item.latest_date else "",
                ]
            )
    return len(overviews)


def export_snapshots(session: Session, path: Path) -> int:
    rows = snapshot_service.list_snapshots(session, limit=None)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(
            [
                "account_name",
                "side",
                "category",
                "snapshot_date",
                "value",
                "note",
                "created_at",
            ]
        )
        for row in reversed(rows):
            writer.writerow(
                [
                    row.account_name,
                    row.side,
                    row.category,
                    row.snapshot_date.isoformat(),
                    f"{row.value:.2f}",
                    row.note,
                    row.created_at.isoformat() if row.created_at else "",
                ]
            )
    return len(rows)
