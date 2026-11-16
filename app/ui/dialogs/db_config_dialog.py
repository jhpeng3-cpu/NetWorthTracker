"""SQLite 数据库文件配置对话框。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig, DbSettings, app_dir, default_db_path
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
        self.setMinimumWidth(520)
        self.setModal(True)
        self._build_ui(initial_error)
        self._load_values()

    def _build_ui(self, initial_error: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        title = QLabel("SQLite 数据库文件")
        title.setObjectName("PageTitle")
        title.setStyleSheet("font-size: 18px;")
        layout.addWidget(title)
        subtitle = QLabel(
            "首次使用会自动在用户数据目录创建数据库文件，也可以选择已有的 .db 文件。"
            if self.first_run
            else "修改数据库文件并保存后，应用会自动重连并执行数据库迁移。"
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setSpacing(8)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(str(default_db_path()))

        file_row = QWidget()
        file_layout = QHBoxLayout(file_row)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(8)
        file_layout.addWidget(self.path_edit, 1)
        self.open_button = QPushButton("选择…")
        self.open_button.clicked.connect(self._browse_existing)
        self.new_button = QPushButton("新建…")
        self.new_button.clicked.connect(self._browse_new)
        file_layout.addWidget(self.open_button)
        file_layout.addWidget(self.new_button)

        form.addRow("数据库文件 *", file_row)
        layout.addLayout(form)

        hint = QLabel(
            "数据库文件不存在时会自动创建；切换文件不会移动原文件中的数据。"
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

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
        self.path_edit.setText(self.config.db_settings().path)

    def _browse_existing(self) -> None:
        start = self.path_edit.text().strip() or str(app_dir())
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 SQLite 数据库文件", start, "SQLite 数据库 (*.db *.sqlite);;所有文件 (*)"
        )
        if path:
            self.path_edit.setText(path)

    def _browse_new(self) -> None:
        start = self.path_edit.text().strip() or str(app_dir() / default_db_path())
        path, _ = QFileDialog.getSaveFileName(
            self, "新建 SQLite 数据库文件", start, "SQLite 数据库 (*.db)"
        )
        if path:
            target = Path(path)
            if not target.suffix:
                target = target.with_suffix(".db")
            self.path_edit.setText(str(target))

    def _read_settings(self) -> Optional[DbSettings]:
        raw = self.path_edit.text().strip()
        if not raw:
            show_warning(self, "信息不完整", "请选择 SQLite 数据库文件路径。")
            return None
        path = Path(raw).expanduser()
        if not path.suffix:
            path = path.with_suffix(".db")
        return DbSettings(path=str(path))

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        for widget in (
            self.path_edit,
            self.open_button,
            self.new_button,
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
        self._set_busy(True, "正在测试数据库文件…")
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
        self._set_busy(True, "正在打开数据库文件并执行数据库迁移…")

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
