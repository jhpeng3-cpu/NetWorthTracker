"""设置页面：显示偏好、自动备份与数据库信息。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.db.engine import db
from app.ui.common import primary_button, show_info, show_warning
from app.ui.pages.base import BasePage
from app.ui.styles import palette


class SettingsPage(BasePage):
    settings_changed = Signal()
    database_settings_requested = Signal()

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(config, parent)
        self._build_ui()
        self.reload_from_config()
        self.refresh_db_info()

    def _build_ui(self) -> None:
        self.add_header("设置", "显示偏好保存在 config.ini；数据库连接可随时修改。")

        appearance = QGroupBox("显示")
        appearance_form = QFormLayout(appearance)
        appearance_form.setContentsMargins(12, 14, 12, 10)
        appearance_form.setSpacing(9)
        self.currency_edit = QLineEdit()
        self.currency_edit.setMaxLength(4)
        self.currency_edit.setFixedWidth(100)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.setFixedWidth(140)
        appearance_form.addRow("货币符号", self.currency_edit)
        appearance_form.addRow("主题", self.theme_combo)
        self.root.addWidget(appearance)

        backup_group = QGroupBox("自动备份")
        backup_form = QFormLayout(backup_group)
        backup_form.setContentsMargins(12, 14, 12, 10)
        backup_form.setSpacing(9)
        self.auto_backup_check = QCheckBox("启动应用时自动备份数据库")
        backup_form.addRow("", self.auto_backup_check)
        dir_row = QWidget()
        dir_layout = QHBoxLayout(dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(8)
        self.backup_dir_edit = QLineEdit()
        self.backup_dir_edit.setPlaceholderText("选择备份保存目录")
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse_backup_dir)
        dir_layout.addWidget(self.backup_dir_edit, 1)
        dir_layout.addWidget(browse)
        backup_form.addRow("备份目录", dir_row)
        backup_hint = QLabel("自动备份依赖 PATH 中的 mysqldump；失败不会影响应用启动。")
        backup_hint.setObjectName("Hint")
        backup_form.addRow("", backup_hint)
        self.root.addWidget(backup_group)

        database_group = QGroupBox("数据库连接")
        database_layout = QVBoxLayout(database_group)
        database_layout.setContentsMargins(12, 14, 12, 10)
        database_layout.setSpacing(8)
        self.db_form = QFormLayout()
        self.db_form.setSpacing(7)
        self.db_host_label = QLabel("—")
        self.db_port_label = QLabel("—")
        self.db_name_label = QLabel("—")
        self.db_user_label = QLabel("—")
        self.db_password_label = QLabel("—")
        self.db_status_label = QLabel("—")
        self.db_form.addRow("主机", self.db_host_label)
        self.db_form.addRow("端口", self.db_port_label)
        self.db_form.addRow("数据库", self.db_name_label)
        self.db_form.addRow("用户名", self.db_user_label)
        self.db_form.addRow("密码", self.db_password_label)
        self.db_form.addRow("状态", self.db_status_label)
        database_layout.addLayout(self.db_form)
        db_buttons = QHBoxLayout()
        db_button = QPushButton("数据库设置…")
        db_button.clicked.connect(self.database_settings_requested.emit)
        db_buttons.addWidget(db_button)
        db_buttons.addStretch(1)
        database_layout.addLayout(db_buttons)
        self.root.addWidget(database_group)

        save_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setObjectName("Hint")
        save_row.addWidget(self.status_label)
        save_row.addStretch(1)
        save_button = primary_button("保存设置")
        save_button.clicked.connect(self._save)
        save_row.addWidget(save_button)
        self.root.addLayout(save_row)
        self.root.addStretch(1)

    def reload_from_config(self) -> None:
        self.currency_edit.setText(self.config.currency_symbol)
        theme_index = self.theme_combo.findData(self.config.theme)
        if theme_index >= 0:
            self.theme_combo.setCurrentIndex(theme_index)
        self.auto_backup_check.setChecked(self.config.auto_backup)
        self.backup_dir_edit.setText(self.config.backup_dir)

    def refresh(self) -> None:
        self.refresh_db_info()

    def refresh_db_info(self) -> None:
        settings = self.config.db_settings()
        self.db_host_label.setText(settings.host or "—")
        self.db_port_label.setText(str(settings.port))
        self.db_name_label.setText(settings.database or "—")
        self.db_user_label.setText(settings.user or "—")
        self.db_password_label.setText("******（已设置）" if settings.password else "（未设置）")
        if db.is_configured:
            self.db_status_label.setText("已连接")
            self.db_status_label.setStyleSheet(
                f"color: {palette(self.config.theme)['success']};"
            )
        else:
            self.db_status_label.setText("未连接")
            self.db_status_label.setStyleSheet(
                f"color: {palette(self.config.theme)['danger']};"
            )

    def _browse_backup_dir(self) -> None:
        start = self.backup_dir_edit.text().strip() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "选择备份目录", start)
        if directory:
            self.backup_dir_edit.setText(directory)

    def _save(self) -> None:
        symbol = self.currency_edit.text().strip() or "¥"
        auto_backup = self.auto_backup_check.isChecked()
        backup_dir = self.backup_dir_edit.text().strip()
        if auto_backup and not backup_dir:
            show_warning(self, "缺少备份目录", "开启自动备份前，请选择一个备份目录。")
            return
        self.config.save_ui_settings(
            currency_symbol=symbol,
            theme=self.theme_combo.currentData() or "light",
            auto_backup=auto_backup,
            backup_dir=backup_dir,
        )
        self.status_label.setStyleSheet("color: #059669;")
        self.status_label.setText("设置已保存。")
        self.refresh_db_info()
        self.settings_changed.emit()
        show_info(self, "设置已保存", "显示与备份设置已生效。")
