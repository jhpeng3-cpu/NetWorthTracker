"""以编程方式执行 Alembic 迁移（源码运行与 PyInstaller 打包均适用）。"""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

from app.config import bundle_dir
from app.utils.exceptions import AppRuntimeError


class MigrationError(AppRuntimeError):
    pass


def run_migrations(url: URL) -> None:
    root = bundle_dir()
    ini_path = root / "alembic.ini"
    scripts = root / "alembic"
    if not ini_path.exists() or not scripts.exists():
        raise MigrationError("未找到 Alembic 配置文件或迁移脚本，请检查安装是否完整。")

    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(scripts))
    cfg.attributes["sqlalchemy_url"] = url.render_as_string(hide_password=False)
    try:
        command.upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001 - 统一转成可展示的错误
        raise MigrationError(f"数据库迁移失败：{exc}") from exc
