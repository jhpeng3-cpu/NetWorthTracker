"""配置中的数据库路径使用相对路径。"""
from __future__ import annotations

from pathlib import Path

from app.config import (
    AppConfig,
    DbSettings,
    app_dir,
    resolve_db_path,
    stored_db_path,
)


def test_default_db_path_is_relative(tmp_path):
    config = AppConfig(path=tmp_path / "config.ini")
    settings = config.db_settings()
    assert settings.path == "networth.db"
    assert settings.resolved_path() == (app_dir() / "networth.db").resolve()


def test_relative_path_resolves_against_app_dir():
    assert resolve_db_path("data/ledger.db") == (app_dir() / "data" / "ledger.db").resolve()


def test_path_inside_app_dir_is_stored_relative(tmp_path):
    config = AppConfig(path=tmp_path / "config.ini")
    config.save_db_settings(DbSettings(path=str(app_dir() / "data" / "ledger.db")))
    assert config.db_settings().path == "data/ledger.db"


def test_path_outside_app_dir_is_stored_absolute(tmp_path):
    outside = (tmp_path / "other.db").resolve()
    assert Path(stored_db_path(outside)) == outside
