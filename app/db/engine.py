"""数据库引擎、会话与连接测试（MySQL 8.0+ / PyMySQL）。"""
from __future__ import annotations

import contextlib
import re
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import DbSettings
from app.utils.exceptions import AppRuntimeError

DRIVER_NAME = "mysql+pymysql"
CHARSET = "utf8mb4"
COLLATION = "utf8mb4_unicode_ci"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_$]+$")


class DatabaseConnectionError(AppRuntimeError):
    """连接数据库失败，message 为面向用户的中文提示。"""


def build_url(settings: DbSettings, connect_timeout: int = 10, include_database: bool = True) -> URL:
    return URL.create(
        drivername=DRIVER_NAME,
        username=settings.user,
        password=settings.password,
        host=settings.host,
        port=settings.port,
        database=settings.database if include_database else None,
        query={"charset": CHARSET, "connect_timeout": str(connect_timeout)},
    )


def _mysql_errno(exc: Exception) -> Optional[int]:
    orig = getattr(exc, "orig", None) or exc
    args = getattr(orig, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


def _friendly_error(exc: Exception, settings: DbSettings) -> str:
    raw = str(exc)
    lower = raw.lower()
    errno = _mysql_errno(exc)
    if errno == 1045 or "access denied for user" in lower:
        return "用户名或密码错误，请检查数据库账号信息。"
    if errno == 1044:
        return f"当前账号没有访问数据库 “{settings.database}” 的权限。"
    if errno == 1049:
        return (
            f"数据库 “{settings.database}” 不存在，且当前账号没有创建权限；"
            "请先用 MySQL 账号手动创建该数据库。"
        )
    if errno == 1130 or "is not allowed to connect" in lower:
        return f"MySQL 不允许从当前主机连接到 {settings.host}，请检查账号授权。"
    if errno in (2002, 2003, 2005) or "can't connect" in lower or "timed out" in lower:
        return (
            f"无法连接到 {settings.host}:{settings.port}，请确认 MySQL 已启动、"
            "端口正确且允许远程连接。"
        )
    if errno == 1698 or "auth_socket" in lower:
        return "该 MySQL 账号使用 auth_socket 认证，请改用密码认证的账号。"
    if "cryptography" in lower:
        return "缺少 cryptography 依赖，无法完成 MySQL 8 密码认证，请重新安装依赖。"
    return f"数据库连接失败：{raw.splitlines()[0] if raw else '未知错误'}"


def ensure_database(settings: DbSettings) -> bool:
    """确保目标数据库存在，不存在时按 utf8mb4 创建。返回是否新建。"""
    if not _IDENTIFIER_RE.match(settings.database):
        raise DatabaseConnectionError("数据库名只能包含字母、数字、下划线和 $。")
    engine = create_engine(
        build_url(settings, include_database=False),
        connect_args={"connect_timeout": 8},
    )
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA "
                    "WHERE SCHEMA_NAME = :name"
                ),
                {"name": settings.database},
            ).scalar()
            if exists:
                return False
            conn.execute(
                text(
                    f"CREATE DATABASE `{settings.database}` "
                    f"CHARACTER SET {CHARSET} COLLATE {COLLATION}"
                )
            )
            return True
    except (OperationalError, SQLAlchemyError, OSError) as exc:
        raise DatabaseConnectionError(_friendly_error(exc, settings)) from exc
    finally:
        engine.dispose()


def test_connection(settings: DbSettings) -> str:
    """测试连接，返回 “数据库名 · MySQL 版本” 摘要；数据库不存在时自动创建。"""
    if not settings.is_complete():
        raise DatabaseConnectionError("请填写完整的主机、端口、数据库名和用户名。")
    created = ensure_database(settings)
    engine: Optional[Engine] = None
    try:
        engine = create_engine(
            build_url(settings, connect_timeout=8),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 8},
        )
        with engine.connect() as conn:
            db_name = conn.execute(text("SELECT DATABASE()")).scalar()
            version = conn.execute(text("SELECT VERSION()")).scalar() or ""
        short_version = version.split("-")[0].strip()
        summary = f"{db_name} · MySQL {short_version}"
        return summary + "（已新建数据库）" if created else summary
    except (OperationalError, SQLAlchemyError, OSError) as exc:
        raise DatabaseConnectionError(_friendly_error(exc, settings)) from exc
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
        url = build_url(settings)
        self.url = url
        self.engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=5,
            max_overflow=5,
            connect_args={"connect_timeout": 10},
        )
        self._session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    def session(self) -> Session:
        if self._session_factory is None:
            raise DatabaseConnectionError("数据库尚未配置，请先在“数据库设置”中连接。")
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
