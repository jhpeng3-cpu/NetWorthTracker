"""应用入口。"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app import __version__
from app.config import AppConfig, app_dir
from app.db.engine import db
from app.db.migrate import run_migrations
from app.utils.exceptions import install_global_exception_handler
from app.ui.dialogs.db_config_dialog import DbConfigDialog
from app.ui.main_window import MainWindow
from app.ui.styles import build_stylesheet





def setup_logging() -> None:
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
    setup_logging()
    install_global_exception_handler()
    app = QApplication(sys.argv)
    app.setApplicationName("净资产管理")
    app.setOrganizationName("NetWorthTracker")
    app.setApplicationVersion(__version__)

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
    sys.exit(main())
