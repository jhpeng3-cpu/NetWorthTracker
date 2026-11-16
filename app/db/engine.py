"""数据库引擎、会话与连接测试（SQLite）。"""
from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import DbSettings
from app.utils.exceptions import AppRuntimeError

DRIVER_NAME = "sqlite"


class DatabaseConnectionError(AppRuntimeError):
    """连接数据库失败，message 为面向用户的中文提示。"""


def build_url(settings: DbSettings) -> URL:
    """SQLite 文件 URL；同时确保文件所在目录存在。"""
    path = settings.resolved_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return URL.create(DRIVER_NAME, database=path.as_posix())


def _friendly_error(exc: Exception, path: Path) -> str:
    raw = str(exc)
    lower = raw.lower()
    if "unable to open database file" in lower:
        return f"无法打开数据库文件：{path}；请确认目录存在且当前用户有写入权限。"
    if "database is locked" in lower:
        return "数据库文件正被其他程序占用，请关闭后重试。"
    if "file is not a database" in lower or "malformed" in lower:
        return f"所选文件不是有效的 SQLite 数据库：{path}"
    if "disk i/o error" in lower or "readonly" in lower:
        return f"无法读写数据库文件：{path}，请检查磁盘状态与文件权限。"
    return f"数据库连接失败：{raw.splitlines()[0] if raw else '未知错误'}"


def _attach_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=15000")
        finally:
            cursor.close()


def _create_engine(settings: DbSettings) -> Engine:
    engine = create_engine(
        build_url(settings),
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    _attach_pragmas(engine)
    return engine


def test_connection(settings: DbSettings) -> str:
    """打开（必要时新建）SQLite 文件，返回 “文件名 · SQLite 版本” 摘要。"""
    if not settings.is_complete():
        raise DatabaseConnectionError("请选择 SQLite 数据库文件路径。")
    path = settings.resolved_path()
    created = not path.exists()
    engine: Optional[Engine] = None
    try:
        engine = _create_engine(settings)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT sqlite_version()")).scalar() or ""
        summary = f"{path.name} · SQLite {version}"
        return summary + "（已新建数据库文件）" if created else summary
    except (SQLAlchemyError, OSError, sqlite3.Error) as exc:
        raise DatabaseConnectionError(_friendly_error(exc, path)) from exc
    finally:
        if engine is not None:
            engine.dispose()


class Database:
    def __init__(self) -> None:
        self.engine: Optional[Engine] = None
        self.url: Optional[URL] = None
        self._session_factory: Optional[sessionmaker[Session]] = None

    @property
    def is_configured(self) -> bool:
        return self.engine is not None and self._session_factory is not None

    def configure(self, settings: DbSettings) -> None:
        self.dispose()
        self.url = build_url(settings)
        self.engine = _create_engine(settings)
        self._session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    def session(self) -> Session:
        if self._session_factory is None:
            raise DatabaseConnectionError("数据库尚未配置，请先在“数据库设置”中选择数据库文件。")
        return self._session_factory()

    @contextlib.contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self.session()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
        self.engine = None
        self._session_factory = None
        self.url = None


db = Database()
