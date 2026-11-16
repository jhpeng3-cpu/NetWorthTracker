"""主窗口：侧边导航 + 页面栈。"""
from __future__ import annotations

from pathlib import Path
from typing import List

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
from app.services import backup, exchange_rates, valuation
from app.services.valuation import manual as valuation_manual
from app.ui.common import show_info
from app.ui.dialogs.db_config_dialog import DbConfigDialog
from app.ui.pages.accounts import AccountsPage
from app.ui.pages.base import BasePage
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.data import DataPage
from app.ui.pages.history import HistoryPage
from app.ui.pages.profit import ProfitPage
from app.ui.pages.settings import SettingsPage
from app.ui.styles import build_stylesheet
from app.ui.titlebar import (
    THEME_PROPERTY,
    apply_titlebar_theme,
    apply_titlebar_to_open_windows,
)
from app.utils.async_task import run_async


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.setWindowTitle("财序 · 个人资产负债表")
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is not None:
            available = screen.availableGeometry()
            width = min(1380, max(800, available.width() - 40))
            height = min(880, max(560, available.height() - 40))
        else:
            width, height = 1380, 880
        self.setMinimumSize(min(1120, width), min(680, height))
        self.resize(width, height)
        self._build_menu()
        self._build_central()
        self._build_statusbar()
        self._apply_theme(self.config.theme)
        QTimer.singleShot(1500, self._auto_backup_if_needed)
        QTimer.singleShot(1200, self._check_valuation_reminders)
        QTimer.singleShot(2500, self._startup_rate_refresh)
        QTimer.singleShot(3500, self._startup_quote_refresh)
        self._schedule_midnight_rate_fetch()
        self._quote_timer = QTimer(self)
        self._quote_timer.setInterval(5 * 60 * 1000)
        self._quote_timer.timeout.connect(self._refresh_quotes)
        self._quote_timer.start()

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

        brand = QLabel("财序")
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

        footer = QLabel(f"v{__version__}\nSQLite · 本地存储")
        footer.setObjectName("SidebarFooter")
        footer.setContentsMargins(22, 0, 10, 0)
        sidebar_layout.addWidget(footer)
        layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Content")
        layout.addWidget(self.stack, 1)

        self.dashboard_page = DashboardPage(self.config)
        self.accounts_page = AccountsPage(self.config)
        self.history_page = HistoryPage(self.config)
        self.profit_page = ProfitPage(self.config)
        self.data_page = DataPage(self.config)
        self.settings_page = SettingsPage(self.config)

        self._pages: List[BasePage] = [
            self.dashboard_page,
            self.accounts_page,
            self.history_page,
            self.profit_page,
            self.data_page,
            self.settings_page,
        ]
        nav_labels = [
            "仪表盘",
            "账户管理",
            "历史与明细",
            "盈亏分析",
            "数据管理",
            "设置",
        ]

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
        page.refresh()

    def _on_data_changed(self) -> None:
        self.dashboard_page.refresh()
        self.accounts_page.refresh()
        self.history_page.refresh()
        self.profit_page.refresh()
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
        self.history_page.refresh()
        self.profit_page.refresh()
        self.data_page.refresh()
        self.settings_page.refresh_db_info()
        self.statusBar().showMessage("设置已应用", 3000)

    def _apply_theme(self, theme: str) -> None:
        self._theme = theme
        app = QApplication.instance()
        if app is not None:
            app.setProperty(THEME_PROPERTY, theme)
            app.setStyleSheet(build_stylesheet(theme))
        for page in getattr(self, "_pages", []):
            page.apply_theme(theme)
        apply_titlebar_to_open_windows(theme)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        apply_titlebar_theme(
            int(self.winId()), getattr(self, "_theme", self.config.theme)
        )

    # ---- 数据库 ----
    def _open_db_settings(self) -> None:
        dialog = DbConfigDialog(self.config, self)
        if dialog.exec():
            self.refresh_all()
            self.settings_page.reload_from_config()
            self._update_db_status()
            self._refresh_rates()
            self.statusBar().showMessage("数据库文件已更新", 4000)

    def _show_about(self) -> None:
        show_info(
            self,
            "关于财序",
            f"财序 v{__version__}\n\n"
            "个人资产负债记录与净资产追踪工具。\n"
            "PySide6 · SQLAlchemy 2 · SQLite · Alembic · Qt 原生图表\n\n"
            f"配置文件：{self.config.path}",
        )

    # ---- 估值提醒 ----
    def _check_valuation_reminders(self) -> None:
        if not db.is_configured:
            return

        def task():
            with db.session_scope() as session:
                return valuation_manual.overdue_manual_items(session)

        def success(result: object) -> None:
            rows = list(result) if isinstance(result, list) else []
            if not rows:
                return
            lines = [
                f"· {row.account_name} / {row.item_name}"
                f"（应于 {row.due_date:%Y-%m-%d} 更新）"
                for row in rows[:10]
            ]
            more = "" if len(rows) <= 10 else f"\n……另有 {len(rows) - 10} 项"
            show_info(
                self,
                "估值提醒",
                "以下手动估值已到期未更新：\n\n"
                + "\n".join(lines)
                + more
                + "\n\n可到「账户管理」录入最新估值。",
            )

        run_async(task, success, lambda _message: None)

    # ---- 自动备份 ----
    def _auto_backup_if_needed(self) -> None:
        if not self.config.auto_backup:
            return
        directory = self.config.backup_dir.strip()
        if not directory:
            self.statusBar().showMessage("自动备份已开启，但未配置备份目录", 6000)
            return
        if not db.is_configured:
            self.statusBar().showMessage("自动备份跳过：数据库尚未就绪", 6000)
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

    # ---- 行情 ----
    def _startup_quote_refresh(self) -> None:
        if db.is_configured:
            self._refresh_quotes()

    def _refresh_quotes(self) -> None:
        if not db.is_configured:
            return

        def task():
            with db.session_scope() as session:
                return valuation.refresh_all(session)

        def success(result) -> None:
            if result.updated or result.failed:
                self._on_data_changed()
                note = (
                    f"估值刷新：成功 {result.updated}，跳过 {result.skipped}，"
                    f"失败 {result.failed}"
                )
                if result.stale:
                    note += f"，行情过期 {result.stale}"
                self.statusBar().showMessage(note, 6000)
            elif result.skipped:
                self.statusBar().showMessage(
                    f"暂无可自动估值的资产（跳过 {result.skipped} 项）", 6000
                )

        def failure(_message: str) -> None:
            self.statusBar().showMessage("行情刷新失败，稍后自动重试", 6000)

        run_async(task, success, failure)

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
        self._quote_timer.stop()
        db.dispose()
        super().closeEvent(event)
