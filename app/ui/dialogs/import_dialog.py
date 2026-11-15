"""CSV 导入预览对话框。"""
from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.csv_io import (
    DUPLICATE_OVERWRITE,
    DUPLICATE_SKIP,
    ImportResult,
    ImportRow,
)
from app.ui.common import (
    align_headers,
    make_table,
    primary_button,
    set_columns,
    show_exception,
    show_warning,
)
from app.ui.styles import palette
from app.utils.money import fmt_money, symbol_for


class ImportPreviewDialog(QDialog):
    def __init__(
        self,
        rows: List[ImportRow],
        theme: str,
        on_import: Callable[[str, bool], ImportResult],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._rows = rows
        self._colors = palette(theme)
        self._on_import = on_import
        self.import_result: Optional[ImportResult] = None
        self.setWindowTitle("导入预览")
        self.setMinimumSize(820, 560)
        self.setModal(True)
        self._build_ui()
        self._fill_table()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        title = QLabel("CSV 导入预览")
        title.setObjectName("PageTitle")
        title.setStyleSheet("font-size: 18px;")
        layout.addWidget(title)

        valid = sum(1 for row in self._rows if row.is_valid)
        existing = sum(1 for row in self._rows if row.is_valid and row.exists)
        invalid = len(self._rows) - valid
        self.summary_label = QLabel(
            f"共 {len(self._rows)} 行：可导入 {valid - existing} 行，"
            f"已存在 {existing} 行，错误 {invalid} 行。"
        )
        self.summary_label.setObjectName("Muted")
        layout.addWidget(self.summary_label)

        self.table = make_table(["行号", "账户", "日期", "估值", "备注", "状态"])
        set_columns(self.table, [60, 180, 110, 130, 220, 200])
        align_headers(self.table, (3,))
        layout.addWidget(self.table, 1)

        options = QHBoxLayout()
        options.setSpacing(8)
        label = QLabel("重复数据：")
        label.setObjectName("Muted")
        self.policy_combo = QComboBox()
        self.policy_combo.addItem("跳过已存在", DUPLICATE_SKIP)
        self.policy_combo.addItem("覆盖已存在", DUPLICATE_OVERWRITE)
        self.skip_invalid = QCheckBox("跳过无效行")
        self.skip_invalid.setChecked(True)
        options.addWidget(label)
        options.addWidget(self.policy_combo)
        options.addSpacing(12)
        options.addWidget(self.skip_invalid)
        options.addStretch(1)
        layout.addLayout(options)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.import_button = primary_button("开始导入")
        self.import_button.setEnabled(valid - existing > 0 or (existing > 0 and valid > 0))
        self.import_button.clicked.connect(self._do_import)
        buttons.addWidget(cancel)
        buttons.addWidget(self.import_button)
        layout.addLayout(buttons)

    def _fill_table(self) -> None:
        status_colors = {
            "错误": self._colors["danger"],
            "已存在": self._colors["warning"],
            "新增": self._colors["success"],
        }
        self.table.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            status = row.status
            values = [
                str(row.line_no),
                row.account_name,
                row.date_text,
                row.value_text,
                row.note,
                status if not row.errors else f"错误：{'；'.join(row.errors)}",
            ]
            color = status_colors.get(status)
            for column, text in enumerate(values):
                item = self.table.item(row_index, column)
                if item is None:
                    from PySide6.QtWidgets import QTableWidgetItem

                    item = QTableWidgetItem()
                    self.table.setItem(row_index, column, item)
                item.setText(text)
                if column == 3:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if color is not None:
                    item.setForeground(QColor(color))
                if row.value is not None and column == 3:
                    item.setText(fmt_money(row.value, symbol_for(row.currency)))

    def _do_import(self) -> None:
        valid = [row for row in self._rows if row.is_valid]
        if not valid:
            show_warning(self, "无法导入", "没有可导入的有效数据。")
            return
        skip_invalid = self.skip_invalid.isChecked()
        if not skip_invalid and any(not row.is_valid for row in self._rows):
            show_warning(
                self,
                "存在无效数据",
                "请勾选“跳过无效行”，或先取消并修正 CSV 文件。",
            )
            return
        policy = self.policy_combo.currentData() or DUPLICATE_SKIP
        try:
            self.import_result = self._on_import(policy, skip_invalid)
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "导入失败", exc)
            return
        self.accept()
