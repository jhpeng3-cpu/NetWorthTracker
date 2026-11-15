"""新增 / 编辑账户对话框。"""
from __future__ import annotations

from typing import Callable, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.db.models import (
    CATEGORY_LABELS,
    CATEGORIES_BY_SIDE,
    CURRENCY_CODES,
    CURRENCY_LABELS,
    SIDE_ASSET,
    SIDE_LIABILITY,
    SIDE_LABELS,
)
from app.services.accounts import AccountOverview, AccountValidationError
from app.ui.common import primary_button, show_error, show_warning


class AccountDialog(QDialog):
    def __init__(
        self,
        on_submit: Callable[[Dict[str, str]], None],
        account: Optional[AccountOverview] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._on_submit = on_submit
        self._account = account
        self.setWindowTitle("编辑账户" if account else "新增账户")
        self.setMinimumWidth(440)
        self.setModal(True)
        self._build_ui()
        if account is not None:
            self._fill(account)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：招商银行活期、住房按揭")
        self.side_combo = QComboBox()
        self.side_combo.addItem("资产", SIDE_ASSET)
        self.side_combo.addItem("负债", SIDE_LIABILITY)
        self.category_combo = QComboBox()
        self.side_combo.currentIndexChanged.connect(self._populate_categories)
        self.currency_combo = QComboBox()
        for code in CURRENCY_CODES:
            self.currency_combo.addItem(f"{CURRENCY_LABELS[code]}（{code}）", code)
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("可选备注")
        self.note_edit.setFixedHeight(72)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setSpacing(8)
        form.addRow("账户名称 *", self.name_edit)
        form.addRow("方向 *", self.side_combo)
        form.addRow("类别 *", self.category_combo)
        form.addRow("币种", self.currency_combo)
        form.addRow("备注", self.note_edit)
        layout.addLayout(form)

        hint = QLabel("账户名称不可重复；归档后名称仍会占用。")
        hint.setObjectName("Hint")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = primary_button("保存")
        save.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self._populate_categories()

    def _populate_categories(self, *_args) -> None:
        side = self.side_combo.currentData() or SIDE_ASSET
        current = self.category_combo.currentData()
        self.category_combo.clear()
        for category in CATEGORIES_BY_SIDE[side]:
            self.category_combo.addItem(CATEGORY_LABELS[category], category)
        if current:
            index = self.category_combo.findData(current)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)

    def _fill(self, account: AccountOverview) -> None:
        self.name_edit.setText(account.name)
        index = self.side_combo.findData(account.side)
        if index >= 0:
            self.side_combo.setCurrentIndex(index)
        self._populate_categories()
        category_index = self.category_combo.findData(account.category)
        if category_index >= 0:
            self.category_combo.setCurrentIndex(category_index)
        currency_index = self.currency_combo.findData(account.currency)
        self.currency_combo.setCurrentIndex(currency_index if currency_index >= 0 else 0)
        self.note_edit.setPlainText(account.note)

    def _submit(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            show_warning(self, "请填写名称", "账户名称不能为空。")
            self.name_edit.setFocus()
            return
        payload = {
            "name": name,
            "side": self.side_combo.currentData(),
            "category": self.category_combo.currentData(),
            "currency": self.currency_combo.currentData() or "CNY",
            "note": self.note_edit.toPlainText().strip(),
        }
        try:
            self._on_submit(payload)
        except AccountValidationError as exc:
            show_warning(self, "无法保存", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            show_error(self, "保存失败", str(exc))
            return
        self.accept()
