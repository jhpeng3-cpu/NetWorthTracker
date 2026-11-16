"""SQLite 数据库文件备份。"""
from __future__ import annotations

import contextlib
import sqlite3
from datetime import datetime
from pathlib import Path

from app.config import DbSettings
from app.utils.exceptions import AppRuntimeError


class BackupError(AppRuntimeError):
    pass


def default_backup_name() -> str:
    return f"networth_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"


def create_backup(settings: DbSettings, target: Path) -> Path:
    """通过 SQLite 在线备份接口把当前数据库复制为独立 .db 文件。"""
    source = settings.resolved_path()
    if not source.exists():
        raise BackupError(f"数据库文件不存在：{source}")

    target = Path(target)
    if target.resolve() == source.resolve():
        raise BackupError("备份文件不能与当前数据库文件相同。")
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        with contextlib.closing(sqlite3.connect(str(source))) as src, contextlib.closing(
            sqlite3.connect(str(target))
        ) as dst:
            src.backup(dst)
    except (sqlite3.Error, OSError) as exc:
        raise BackupError(f"备份数据库失败：{exc}") from exc

    if not target.exists() or target.stat().st_size == 0:
        raise BackupError("备份文件未生成或为空，请检查磁盘空间与文件权限。")
    return target
