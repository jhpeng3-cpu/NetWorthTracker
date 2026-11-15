"""数据管理：CSV 导出/导入、mysqldump 备份。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.db.engine import db
from app.services import backup, csv_io
from app.ui.common import primary_button, show_error, show_info, show_warning
from app.ui.dialogs.import_dialog import ImportPreviewDialog
from app.ui.pages.base import BasePage
from app.ui.styles import palette
from app.utils.async_task import run_async
from datetime import date


class DataPage(BasePage):
    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(config, parent)
        self._theme = config.theme
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.add_header("数据管理", "导出 CSV、按模板导入快照，或使用 mysqldump 备份数据库。")

        export_group = QGroupBox("导出 CSV")
        export_layout = QVBoxLayout(export_group)
        export_layout.setContentsMargins(12, 12, 12, 10)
        export_layout.setSpacing(8)
        export_hint = QLabel("导出文件为 UTF-8 with BOM 编码，可直接用 Excel 打开。")
        export_hint.setObjectName("Muted")
        export_layout.addWidget(export_hint)
        export_buttons = QHBoxLayout()
        accounts_button = QPushButton("导出账户列表")
        accounts_button.clicked.connect(self._export_accounts)
        snapshots_button = primary_button("导出全部快照")
        snapshots_button.clicked.connect(self._export_snapshots)
        export_buttons.addWidget(accounts_button)
        export_buttons.addWidget(snapshots_button)
        export_buttons.addStretch(1)
        export_layout.addLayout(export_buttons)
        self.root.addWidget(export_group)

        import_group = QGroupBox("导入快照")
        import_layout = QVBoxLayout(import_group)
        import_layout.setContentsMargins(12, 12, 12, 10)
        import_layout.setSpacing(8)
        template = QLabel(
            "模板列：account_name, snapshot_date, value, note\n"
            "日期格式 YYYY-MM-DD；支持 UTF-8 / GBK 编码；导入前会预览并校验账户、日期与重复数据。"
        )
        template.setObjectName("Muted")
        template.setWordWrap(True)
        import_layout.addWidget(template)
        import_buttons = QHBoxLayout()
        import_button = QPushButton("选择 CSV 并预览…")
        import_button.clicked.connect(self._import_csv)
        import_buttons.addWidget(import_button)
        import_buttons.addStretch(1)
        import_layout.addLayout(import_buttons)
        self.root.addWidget(import_group)

        backup_group = QGroupBox("数据库备份")
        backup_layout = QVBoxLayout(backup_group)
        backup_layout.setContentsMargins(12, 12, 12, 10)
        backup_layout.setSpacing(8)
        self.dump_label = QLabel("")
        self.dump_label.setObjectName("Muted")
        self.dump_label.setWordWrap(True)
        backup_layout.addWidget(self.dump_label)
        auto_hint = QLabel("自动备份可在「设置」中开启；备份依赖本机 PATH 中的 mysqldump。")
        auto_hint.setObjectName("Hint")
        backup_layout.addWidget(auto_hint)
        backup_buttons = QHBoxLayout()
        self.backup_button = primary_button("立即备份…")
        self.backup_button.clicked.connect(self._backup)
        backup_buttons.addWidget(self.backup_button)
        self.backup_status = QLabel("")
        self.backup_status.setObjectName("Hint")
        self.backup_status.setWordWrap(True)
        backup_buttons.addWidget(self.backup_status)
        backup_buttons.addStretch(1)
        backup_layout.addLayout(backup_buttons)
        self.root.addWidget(backup_group)
        self.root.addStretch(1)

    def refresh(self) -> None:
        executable = backup.find_mysqldump()
        if executable:
            self.dump_label.setText(f"已检测到 mysqldump：{executable}")
            self.dump_label.setStyleSheet(f"color: {palette(self._theme)['success']};")
            self.backup_button.setEnabled(True)
        else:
            self.dump_label.setText(
                "未在 PATH 中找到 mysqldump。请安装 MySQL 客户端并把 bin 目录加入 PATH。"
            )
            self.dump_label.setStyleSheet(f"color: {palette(self._theme)['danger']};")
            self.backup_button.setEnabled(False)

    def _export_accounts(self) -> None:
        default = Path.home() / f"账户列表_{date.today().strftime('%Y%m%d')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "导出账户列表", str(default), "CSV 文件 (*.csv)")
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".csv":
            target = target.with_suffix(".csv")
        try:
            with db.session_scope() as session:
                count = csv_io.export_accounts(session, target)
        except Exception as exc:  # noqa: BLE001
            show_error(self, "导出失败", str(exc))
            return
        show_info(self, "导出完成", f"已导出 {count} 个账户到：\n{target}")

    def _export_snapshots(self) -> None:
        default = Path.home() / f"估值快照_{date.today().strftime('%Y%m%d')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "导出全部快照", str(default), "CSV 文件 (*.csv)")
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".csv":
            target = target.with_suffix(".csv")
        try:
            with db.session_scope() as session:
                count = csv_io.export_snapshots(session, target)
        except Exception as exc:  # noqa: BLE001
            show_error(self, "导出失败", str(exc))
            return
        show_info(self, "导出完成", f"已导出 {count} 条快照到：\n{target}")

    def _import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择快照 CSV", str(Path.home()), "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            rows = csv_io.read_snapshot_csv(Path(path))
            with db.session_scope() as session:
                csv_io.validate_import_rows(session, rows)
        except Exception as exc:  # noqa: BLE001
            show_error(self, "无法读取 CSV", str(exc))
            return

        def do_import(policy: str, skip_invalid: bool):
            with db.session_scope() as session:
                return csv_io.import_rows(session, rows, policy, skip_invalid)

        dialog = ImportPreviewDialog(rows, self._theme, do_import, parent=self)
        if not dialog.exec():
            return
        result = dialog.import_result
        if result is None:
            return
        show_info(
            self,
            "导入完成",
            f"新建 {result.created} 条，覆盖 {result.updated} 条，"
            f"跳过 {result.skipped} 条，无效 {result.invalid} 条。",
        )
        self.data_changed.emit()

    def _backup(self) -> None:
        executable = backup.find_mysqldump()
        if not executable:
            show_warning(
                self,
                "找不到 mysqldump",
                "请安装 MySQL 客户端，并把其 bin 目录加入系统 PATH 后重启应用。",
            )
            return
        directory = QFileDialog.getExistingDirectory(
            self, "选择备份保存目录", str(Path.home())
        )
        if not directory:
            return
        target = Path(directory) / backup.default_backup_name()
        settings = self.config.db_settings()
        self.backup_button.setEnabled(False)
        self.backup_status.setStyleSheet("")
        self.backup_status.setText("正在备份，请稍候…")

        def task() -> Path:
            return backup.create_backup(settings, target)

        run_async(task, self._backup_success, self._backup_failure)

    def _backup_success(self, result: object) -> None:
        self.backup_button.setEnabled(True)
        self.backup_status.setStyleSheet(f"color: {palette(self._theme)['success']};")
        self.backup_status.setText(f"备份完成：{result}")
        show_info(self, "备份完成", f"数据库已备份到：\n{result}")

    def _backup_failure(self, message: str) -> None:
        self.backup_button.setEnabled(True)
        self.backup_status.setStyleSheet(f"color: {palette(self._theme)['danger']};")
        self.backup_status.setText("备份失败")
        show_error(self, "备份失败", message)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self.refresh()
