"""应用配置：SQLite 数据库文件与界面偏好，保存在应用目录 config.ini。"""
from __future__ import annotations

import configparser
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

APP_DIR_NAME = "NetWorthTracker"
DEFAULT_DB_FILENAME = "networth.db"


def app_dir() -> Path:
    """源码运行时为项目根目录；PyInstaller 打包后为 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """只读资源目录（打包后为 _MEIPASS）。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    override = os.environ.get("NETWORTH_CONFIG")
    if override:
        return Path(override).expanduser()
    return app_dir() / "config.ini"


def user_data_dir() -> Path:
    """旧版本默认数据目录；仅用于迁移历史数据库。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME.lower()}"


def default_db_path() -> Path:
    """默认数据库文件，相对于应用目录。"""
    return Path(DEFAULT_DB_FILENAME)


def resolve_db_path(path: str | Path) -> Path:
    """相对路径按应用目录解析，绝对路径原样返回。"""
    target = Path(path).expanduser()
    if target.is_absolute():
        return target
    return (app_dir() / target).resolve()


def stored_db_path(path: str | Path) -> str:
    """尽量以相对路径保存；只有位于应用目录之外时才保留绝对路径。"""
    target = Path(path).expanduser()
    if not target.is_absolute():
        return target.as_posix()
    try:
        relative = target.resolve().relative_to(app_dir().resolve())
    except ValueError:
        return target.as_posix()
    return relative.as_posix()


@dataclass
class DbSettings:
    path: str = field(default_factory=lambda: str(default_db_path()))

    def resolved_path(self) -> Path:
        return resolve_db_path(self.path)

    def is_complete(self) -> bool:
        return bool(self.path.strip())

    def display(self) -> str:
        return str(self.resolved_path())


class AppConfig:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else config_path()
        self._parser = configparser.ConfigParser(interpolation=None)
        self.reload()
        self._adopt_legacy_database()

    def reload(self) -> None:
        self._parser = configparser.ConfigParser(interpolation=None)
        if self.path.exists():
            self._parser.read(self.path, encoding="utf-8")

    def _adopt_legacy_database(self) -> None:
        """旧版本数据库在用户数据目录，迁移到应用目录并改写为相对路径。"""
        if self.path != config_path():
            return  # 测试或自定义配置，不做迁移
        legacy = user_data_dir() / DEFAULT_DB_FILENAME
        raw = self._get("database", "path", "").strip()
        if raw and Path(raw).expanduser() != legacy:
            return  # 用户已指定其它位置
        target = resolve_db_path(DEFAULT_DB_FILENAME)
        if not target.exists() and legacy.exists():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy, target)
            except OSError:
                return
        if raw:
            self._set("database", "path", DEFAULT_DB_FILENAME)
            try:
                self.save()
            except OSError:
                pass

    def _get(self, section: str, option: str, fallback: str = "") -> str:
        if not self._parser.has_section(section):
            return fallback
        value = self._parser.get(section, option, fallback=fallback)
        return value if value is not None else fallback

    def _set(self, section: str, option: str, value: str) -> None:
        if not self._parser.has_section(section):
            self._parser.add_section(section)
        self._parser.set(section, option, value)

    # ---- 数据库 ----
    def db_settings(self) -> DbSettings:
        path = self._get("database", "path", "").strip()
        return DbSettings(path=path or str(default_db_path()))

    def has_database_config(self) -> bool:
        return bool(self._get("database", "path", "").strip())

    def save_db_settings(self, settings: DbSettings) -> None:
        self._set("database", "path", stored_db_path(settings.path))
        # 清理旧版本遗留的连接项（host/port/database/user/password）
        for legacy in ("host", "port", "database", "user", "password"):
            if self._parser.has_option("database", legacy):
                self._parser.remove_option("database", legacy)
        self.save()

    # ---- 界面 ----
    @property
    def currency_symbol(self) -> str:
        return self._get("ui", "currency_symbol", "¥") or "¥"

    @property
    def theme(self) -> str:
        theme = self._get("ui", "theme", "light")
        return theme if theme in ("light", "dark") else "light"

    @property
    def auto_backup(self) -> bool:
        return self._get("ui", "auto_backup", "false").strip().lower() in ("1", "true", "yes", "on")

    @property
    def backup_dir(self) -> str:
        return self._get("ui", "backup_dir", "")

    def save_ui_settings(
        self,
        currency_symbol: str,
        theme: str,
        auto_backup: bool,
        backup_dir: str,
    ) -> None:
        self._set("ui", "currency_symbol", currency_symbol or "¥")
        self._set("ui", "theme", theme if theme in ("light", "dark") else "light")
        self._set("ui", "auto_backup", "true" if auto_backup else "false")
        self._set("ui", "backup_dir", backup_dir or "")
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fp:
            self._parser.write(fp)
