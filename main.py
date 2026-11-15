"""应用入口。"""
from __future__ import annotations

import ctypes
import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _report_startup_failure() -> None:
    """启动失败兜底：写入 startup_error.log 并弹出系统提示框。"""
    detail = traceback.format_exc()
    try:
        target = Path(__file__).resolve().parent / "startup_error.log"
        target.write_text(detail, encoding="utf-8")
        note = f"详细堆栈已写入：\n{target}"
    except OSError:
        note = ""
    lines = [line for line in detail.strip().splitlines() if line.strip()]
    summary = lines[-1] if lines else "未知错误"
    try:
        ctypes.windll.user32.MessageBoxW(
            0, f"程序启动失败：\n\n{summary}\n\n{note}", "净资产管理", 0x10
        )
    except Exception:  # noqa: BLE001
        print(detail, file=sys.stderr)


def setup_logging() -> None:
    from app.config import app_dir

    handlers = [logging.StreamHandler()]
    try:
        log_path = app_dir() / "networth.log"
        handlers.append(
            RotatingFileHandler(
                log_path,
                maxBytes=2 * 1024 * 1024,
                backupCount=2,
                encoding="utf-8",
            )
        )
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
    )


def main() -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from app import __version__
    from app.config import AppConfig, bundle_dir
    from app.db.engine import db
    from app.db.migrate import run_migrations
    from app.ui.dialogs.db_config_dialog import DbConfigDialog
    from app.ui.main_window import MainWindow
    from app.ui.styles import build_stylesheet
    from app.utils.exceptions import install_global_exception_handler

    setup_logging()
    install_global_exception_handler()
    app = QApplication(sys.argv)
    app.setApplicationName("净资产管理")
    app.setOrganizationName("NetWorthTracker")
    app.setApplicationVersion(__version__)

    icon_path = bundle_dir() / "app" / "ui" / "assets" / "app.ico"
    if not getattr(sys, "frozen", False):
        # 源码运行时优先使用项目根目录的图标，替换后无需重新转换
        root_icon = Path(__file__).resolve().parent / "图标.png"
        if root_icon.exists():
            icon_path = root_icon
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "NetWorthTracker.App"
            )
        except (AttributeError, OSError):
            pass

    config = AppConfig()
    app.setStyleSheet(build_stylesheet(config.theme))

    if not config.has_database_config():
        dialog = DbConfigDialog(config, first_run=True)
        if not dialog.exec():
            return 0
    else:
        try:
            db.configure(config.db_settings())
            assert db.url is not None
            run_migrations(db.url)
        except Exception as exc:  # noqa: BLE001
            db.dispose()
            logging.getLogger(__name__).exception("启动连接数据库失败")
            dialog = DbConfigDialog(
                config,
                first_run=False,
                initial_error=f"无法使用已保存的连接：{exc}",
            )
            if not dialog.exec():
                return 1

    window = MainWindow(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        _report_startup_failure()
        sys.exit(1)
