"""mysqldump 备份。"""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import DbSettings


class BackupError(RuntimeError):
    pass


class MysqldumpNotFound(BackupError):
    def __init__(self) -> None:
        super().__init__(
            "未在 PATH 中找到 mysqldump。请安装 MySQL 客户端，"
            "并将其 bin 目录（例如 C:\\Program Files\\MySQL\\MySQL Server 8.0\\bin）加入系统 PATH。"
        )


def find_mysqldump() -> Optional[str]:
    return shutil.which("mysqldump")


def default_backup_name() -> str:
    return f"networth_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"


def create_backup(settings: DbSettings, target: Path) -> Path:
    executable = find_mysqldump()
    if not executable:
        raise MysqldumpNotFound()

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["MYSQL_PWD"] = settings.password
    command = [
        executable,
        f"--host={settings.host}",
        f"--port={settings.port}",
        f"--user={settings.user}",
        "--default-character-set=utf8mb4",
        "--single-transaction",
        "--quick",
        "--skip-comments",
        "--no-tablespaces",
        "--set-gtid-purged=OFF",
        f"--result-file={target}",
        settings.database,
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=600,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackupError(f"执行 mysqldump 失败：{exc}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise BackupError(f"mysqldump 返回错误（{result.returncode}）：{message}")
    if not target.exists() or target.stat().st_size == 0:
        raise BackupError("备份文件未生成或为空，请检查数据库权限。")
    return target
