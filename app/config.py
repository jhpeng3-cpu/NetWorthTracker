"""应用配置：数据库连接与界面偏好，保存在应用目录 config.ini。"""
from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.utils.secret import deobfuscate, obfuscate

APP_DIR_NAME = "NetWorthTracker"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3306
DEFAULT_DATABASE = "networth"
DEFAULT_USER = "root"


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


@dataclass
class DbSettings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    database: str = DEFAULT_DATABASE
    user: str = DEFAULT_USER
    password: str = ""

    def is_complete(self) -> bool:
        return bool(self.host and self.database and self.user and 1 <= self.port <= 65535)

    def display(self) -> str:
        return f"{self.host}:{self.port}/{self.database} · {self.user}"

    def masked(self) -> str:
        return f"{self.host}:{self.port}/{self.database} · {self.user} · 密码 ******"


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
        try:
            port = int(self._get("database", "port", str(DEFAULT_PORT)) or DEFAULT_PORT)
        except ValueError:
            port = DEFAULT_PORT
        return DbSettings(
            host=self._get("database", "host", DEFAULT_HOST) or DEFAULT_HOST,
            port=port,
            database=self._get("database", "database", DEFAULT_DATABASE) or DEFAULT_DATABASE,
            user=self._get("database", "user", DEFAULT_USER) or DEFAULT_USER,
            password=deobfuscate(self._get("database", "password", "")),
        )

    def has_database_config(self) -> bool:
        return self._parser.has_section("database") and bool(self._get("database", "host"))

    def save_db_settings(self, settings: DbSettings) -> None:
        self._set("database", "host", settings.host.strip())
        self._set("database", "port", str(settings.port))
        self._set("database", "database", settings.database.strip())
        self._set("database", "user", settings.user.strip())
        self._set("database", "password", obfuscate(settings.password))
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
