"""主窗口：侧边导航 + 页面栈。"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QDateTime, QTime, QSize, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.config import AppConfig
from app.db.engine import db
from app.services import backup, exchange_rates
from app.ui.common import show_error, show_info
from app.ui.dialogs.db_config_dialog import DbConfigDialog
from app.ui.pages.accounts import AccountsPage
from app.ui.pages.batch import BatchPage
from app.ui.pages.base import BasePage
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.data import DataPage
from app.ui.pages.entry import EntryPage
from app.ui.pages.history import HistoryPage
from app.ui.pages.settings import SettingsPage
from app.ui.styles import build_stylesheet
from app.utils.async_task import run_async


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.setWindowTitle("净资产管理 · 个人资产负债表")
        self.setMinimumSize(1280, 800)
        self.resize(1380, 880)
        self._build_menu()
        self._build_central()
        self._build_statusbar()
        self._apply_theme(self.config.theme)
        QTimer.singleShot(1500, self._auto_backup_if_needed)
        QTimer.singleShot(2500, self._startup_rate_refresh)
        self._schedule_midnight_rate_fetch()

    # ---- 构建 ----
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        db_action = file_menu.addAction("数据库设置…")
        db_action.triggered.connect(self._open_db_settings)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("退出")
        exit_action.triggered.connect(self.close)

        help_menu = self.menuBar().addMenu("帮助")
        about_action = help_menu.addAction("关于")
        about_action.triggered.connect(self._show_about)

    def _build_central(self) -> None:
        central = QWidget()
        central.setObjectName("Content")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 20, 0, 16)
        sidebar_layout.setSpacing(0)

        brand = QLabel("净资产管理")
        brand.setObjectName("Brand")
        brand.setContentsMargins(22, 0, 0, 0)
        brand_sub = QLabel("个人资产负债表 · 净资产追踪")
        brand_sub.setObjectName("BrandSub")
        brand_sub.setContentsMargins(22, 2, 10, 0)
        brand_sub.setWordWrap(True)
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(brand_sub)
        sidebar_layout.addSpacing(18)

        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_layout.addWidget(self.nav, 1)

        footer = QLabel(f"v{__version__}\nMySQL · 本地存储")
        footer.setObjectName("SidebarFooter")
        footer.setContentsMargins(22, 0, 10, 0)
        sidebar_layout.addWidget(footer)
        layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Content")
        layout.addWidget(self.stack, 1)

        self.dashboard_page = DashboardPage(self.config)
        self.accounts_page = AccountsPage(self.config)
        self.entry_page = EntryPage(self.config)
        self.batch_page = BatchPage(self.config)
        self.history_page = HistoryPage(self.config)
        self.data_page = DataPage(self.config)
        self.settings_page = SettingsPage(self.config)

        self._pages: List[BasePage] = [
            self.dashboard_page,
            self.accounts_page,
            self.entry_page,
            self.batch_page,
            self.history_page,
            self.data_page,
            self.settings_page,
        ]
        nav_labels = ["仪表盘", "账户管理", "估值录入", "批量录入", "历史与明细", "数据管理", "设置"]

        for page, label in zip(self._pages, nav_labels):
            self.stack.addWidget(page)
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(200, 42))
            self.nav.addItem(item)

        for page in self._pages:
            page.data_changed.connect(self._on_data_changed)
        self.settings_page.settings_changed.connect(self._on_settings_changed)
        self.settings_page.database_settings_requested.connect(self._open_db_settings)
        self.nav.currentRowChanged.connect(self._switch_page)
        self.nav.setCurrentRow(0)

        self.setCentralWidget(central)

    def _build_statusbar(self) -> None:
        self.db_status = QLabel()
        self.statusBar().addPermanentWidget(self.db_status)
        self.statusBar().showMessage("就绪", 4000)
        self._update_db_status()

    def _update_db_status(self) -> None:
        if db.is_configured:
            self.db_status.setText("数据库：" + self.config.db_settings().display())
        else:
            self.db_status.setText("数据库：未连接")

    # ---- 导航与刷新 ----
    def _switch_page(self, index: int) -> None:
        if index < 0 or index >= len(self._pages):
            return
        self.stack.setCurrentIndex(index)
        page = self._pages[index]
        # 批量录入页保留用户尚未保存的输入，不自动刷新。
        if page is not self.batch_page:
            page.refresh()

    def _on_data_changed(self) -> None:
        self.dashboard_page.refresh()
        self.accounts_page.refresh()
        self.entry_page.refresh()
        self.history_page.refresh()
        self.data_page.refresh()
        self.statusBar().showMessage("数据已更新", 3000)

    def refresh_all(self) -> None:
        for page in self._pages:
            page.refresh()
        self._update_db_status()

    def _on_settings_changed(self) -> None:
        self._apply_theme(self.config.theme)
        self.dashboard_page.refresh()
        self.accounts_page.refresh()
        self.entry_page.refresh()
        self.history_page.refresh()
        self.data_page.refresh()
        self.batch_page.refresh()
        self.settings_page.refresh_db_info()
        self.statusBar().showMessage("设置已应用", 3000)

    def _apply_theme(self, theme: str) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(theme))
        for page in getattr(self, "_pages", []):
            page.apply_theme(theme)

    # ---- 数据库 ----
    def _open_db_settings(self) -> None:
        dialog = DbConfigDialog(self.config, self)
        if dialog.exec():
            self.refresh_all()
            self.settings_page.reload_from_config()
            self._update_db_status()
            self._refresh_rates()
            self.statusBar().showMessage("数据库连接已更新", 4000)

    def _show_about(self) -> None:
        show_info(
            self,
            "关于净资产管理",
            f"净资产管理 v{__version__}\n\n"
            "个人资产负债记录与净资产追踪工具。\n"
            "PySide6 · SQLAlchemy 2 · MySQL · Alembic · matplotlib\n\n"
            f"配置文件：{self.config.path}",
        )

    # ---- 自动备份 ----
    def _auto_backup_if_needed(self) -> None:
        if not self.config.auto_backup:
            return
        directory = self.config.backup_dir.strip()
        if not directory:
            self.statusBar().showMessage("自动备份已开启，但未配置备份目录", 6000)
            return
        if not backup.find_mysqldump():
            self.statusBar().showMessage("自动备份跳过：未找到 mysqldump", 6000)
            return
        target = Path(directory) / backup.default_backup_name()
        settings = self.config.db_settings()
        self.statusBar().showMessage("正在执行启动自动备份…")

        def task() -> Path:
            return backup.create_backup(settings, target)

        def success(result: object) -> None:
            self.statusBar().showMessage(f"自动备份完成：{result}", 8000)

        def failure(message: str) -> None:
            self.statusBar().showMessage("自动备份失败，请到「数据管理」手动备份", 8000)

        try:
            run_async(task, success, failure)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"自动备份失败：{exc}", 8000)

    # ---- 汇率 ----
    def _startup_rate_refresh(self) -> None:
        if db.is_configured:
            self._refresh_rates()

    def _schedule_midnight_rate_fetch(self) -> None:
        now = QDateTime.currentDateTime()
        next_midnight = QDateTime(now.date().addDays(1), QTime(0, 0))
        delay = max(60000, now.msecsTo(next_midnight) + 5000)
        QTimer.singleShot(delay, self._on_midnight_rate_fetch)

    def _on_midnight_rate_fetch(self) -> None:
        if db.is_configured:
            self._refresh_rates()
        self._schedule_midnight_rate_fetch()

    def _refresh_rates(self) -> None:
        self.statusBar().showMessage("正在获取最新汇率…")

        def task():
            with db.session_scope() as session:
                return exchange_rates.refresh_rates(session)

        def success(result):
            day, count = result
            self.statusBar().showMessage(
                f"汇率已更新：{count} 个币种（{day:%Y-%m-%d}）", 8000
            )
            self._on_data_changed()

        def failure(_message: str):
            self.statusBar().showMessage(
                "汇率获取失败，沿用最近一次成功汇率；可在「设置」页手动重试", 8000
            )

        try:
            run_async(task, success, failure)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"汇率获取失败：{exc}", 8000)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        db.dispose()
        super().closeEvent(event)
