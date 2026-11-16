"""应用配置：SQLite 数据库文件与界面偏好，保存在应用目录 config.ini。"""
from __future__ import annotations

import configparser
import os
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
    """用户数据目录；Windows 下优先使用 LOCALAPPDATA。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME.lower()}"


def default_db_path() -> Path:
    return user_data_dir() / DEFAULT_DB_FILENAME


@dataclass
class DbSettings:
    path: str = field(default_factory=lambda: str(default_db_path()))

    def resolved_path(self) -> Path:
        return Path(self.path).expanduser()

    def is_complete(self) -> bool:
        return bool(self.path.strip())

    def display(self) -> str:
        return str(self.resolved_path())


class AppConfig:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else config_path()
        self._parser = configparser.ConfigParser(interpolation=None)
        self.reload()

    def reload(self) -> None:
        self._parser = configparser.ConfigParser(interpolation=None)
        if self.path.exists():
            self._parser.read(self.path, encoding="utf-8")

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
        self._set("database", "path", str(settings.resolved_path()))
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
