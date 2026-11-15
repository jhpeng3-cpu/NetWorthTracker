"""数据库连接配置对话框。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig, DbSettings
from app.db import engine as db_engine
from app.db.migrate import run_migrations
from app.ui.common import primary_button, show_warning
from app.utils.async_task import run_async


class DbConfigDialog(QDialog):
    def __init__(
        self,
        config: AppConfig,
        parent: Optional[QWidget] = None,
        first_run: bool = False,
        initial_error: str = "",
    ):
        super().__init__(parent)
        self.config = config
        self.first_run = first_run
        self.saved_settings: Optional[DbSettings] = None
        self._saved_candidate: Optional[DbSettings] = None
        self._busy = False
        self.setWindowTitle("数据库设置")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._build_ui(initial_error)
        self._load_values()

    def _build_ui(self, initial_error: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        title = QLabel("连接到 MySQL")
        title.setObjectName("PageTitle")
        title.setStyleSheet("font-size: 18px;")
        layout.addWidget(title)
        subtitle = QLabel(
            "首次使用需要填写数据库连接信息，保存后会自动建表；数据库不存在时会自动创建。"
            if self.first_run
            else "修改连接信息并保存后，应用会自动重连并执行数据库迁移。"
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setSpacing(8)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("127.0.0.1")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(3306)
        self.database_edit = QLineEdit()
        self.database_edit.setPlaceholderText("networth")
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("root")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_password = QCheckBox("显示密码")
        self.show_password.toggled.connect(self._toggle_password)

        password_row = QWidget()
        password_layout = QHBoxLayout(password_row)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(8)
        password_layout.addWidget(self.password_edit, 1)
        password_layout.addWidget(self.show_password)

        form.addRow("主机 *", self.host_edit)
        form.addRow("端口 *", self.port_spin)
        form.addRow("数据库 *", self.database_edit)
        form.addRow("用户名 *", self.user_edit)
        form.addRow("密码", password_row)
        layout.addLayout(form)

        risk = QLabel(
            "提示：密码以可逆混淆方式保存在应用目录的 config.ini 中，并非强加密，"
            "请确保该文件仅本人可读。"
        )
        risk.setObjectName("Hint")
        risk.setWordWrap(True)
        layout.addWidget(risk)

        if initial_error:
            error_label = QLabel(initial_error)
            error_label.setWordWrap(True)
            error_label.setStyleSheet("color: #dc2626;")
            layout.addWidget(error_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(self._on_test)
        self.cancel_button = QPushButton("退出" if self.first_run else "取消")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = primary_button("保存并连接")
        self.save_button.clicked.connect(self._on_save)
        buttons.addWidget(self.test_button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

    def _load_values(self) -> None:
        settings = self.config.db_settings()
        self.host_edit.setText(settings.host)
        self.port_spin.setValue(settings.port)
        self.database_edit.setText(settings.database)
        self.user_edit.setText(settings.user)
        self.password_edit.setText(settings.password)

    def _toggle_password(self, checked: bool) -> None:
        self.password_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def _read_settings(self) -> Optional[DbSettings]:
        settings = DbSettings(
            host=self.host_edit.text().strip(),
            port=self.port_spin.value(),
            database=self.database_edit.text().strip(),
            user=self.user_edit.text().strip(),
            password=self.password_edit.text(),
        )
        if not settings.host or not settings.database or not settings.user:
            show_warning(self, "信息不完整", "请填写主机、数据库名和用户名。")
            return None
        return settings

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        for widget in (
            self.host_edit,
            self.port_spin,
            self.database_edit,
            self.user_edit,
            self.password_edit,
            self.show_password,
            self.test_button,
            self.cancel_button,
            self.save_button,
        ):
            widget.setEnabled(not busy)
        if message:
            self.status_label.setStyleSheet("")
            self.status_label.setText(message)

    def _set_status(self, text: str, success: bool) -> None:
        color = "#059669" if success else "#dc2626"
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(text)

    def _on_test(self) -> None:
        settings = self._read_settings()
        if settings is None:
            return
        self._set_busy(True, "正在测试连接…")
        run_async(
            lambda: db_engine.test_connection(settings),
            self._on_test_success,
            self._on_test_failure,
        )

    def _on_test_success(self, message: object) -> None:
        self._set_busy(False)
        self._set_status(f"连接成功：{message}", True)

    def _on_test_failure(self, message: str) -> None:
        self._set_busy(False)
        self._set_status(message, False)

    def _on_save(self) -> None:
        settings = self._read_settings()
        if settings is None:
            return
        self._saved_candidate = settings
        self._set_busy(True, "正在连接并执行数据库迁移…")

        def task() -> str:
            summary = db_engine.test_connection(settings)
            db_engine.db.configure(settings)
            try:
                assert db_engine.db.url is not None
                run_migrations(db_engine.db.url)
            except Exception:
                db_engine.db.dispose()
                raise
            return summary

        run_async(task, self._on_save_success, self._on_save_failure)

    def _on_save_success(self, summary: object) -> None:
        settings = self._saved_candidate
        if settings is None:
            return
        self.config.save_db_settings(settings)
        self.saved_settings = settings
        self._set_busy(False)
        self._set_status(f"连接成功，数据库已就绪：{summary}", True)
        self.accept()

    def _on_save_failure(self, message: str) -> None:
        self._set_busy(False)
        self._set_status(message, False)
