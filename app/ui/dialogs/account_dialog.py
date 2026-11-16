"""新增 / 编辑账户对话框（账户基本信息 + 类别子项）。"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
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
)
from app.services.accounts import AccountOverview, AccountValidationError
from app.ui.common import primary_button, show_exception, show_warning


class AccountDialog(QDialog):
    def __init__(
        self,
        on_submit: Callable[[Dict[str, object]], None],
        account: Optional[AccountOverview] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._on_submit = on_submit
        self._account = account
        self._item_rows: List[Tuple[QLineEdit, QComboBox, Optional[int]]] = []
        self.setWindowTitle("编辑账户" if account else "新增账户")
        self.setMinimumWidth(520)
        self.setModal(True)
        self._build_ui()
        if account is not None:
            self._fill(account)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 18, 22, 12)
        layout.setSpacing(12)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：招商银行活期、证券账户、住房按揭")
        self.side_combo = QComboBox()
        self.side_combo.addItem("资产", SIDE_ASSET)
        self.side_combo.addItem("负债", SIDE_LIABILITY)
        self.side_combo.currentIndexChanged.connect(self._on_side_changed)
        self.currency_combo = QComboBox()
        for code in CURRENCY_CODES:
            self.currency_combo.addItem(f"{CURRENCY_LABELS[code]}（{code}）", code)
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("可选备注")
        self.note_edit.setFixedHeight(64)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setSpacing(8)
        form.addRow("账户名称 *", self.name_edit)
        form.addRow("方向 *", self.side_combo)
        form.addRow("默认币种", self.currency_combo)
        form.addRow("备注", self.note_edit)
        layout.addLayout(form)

        items_header = QHBoxLayout()
        items_title = QLabel("类别子项 *")
        items_title.setStyleSheet("font-weight: 600;")
        items_header.addWidget(items_title)
        items_header.addStretch(1)
        add_button = QPushButton("添加子项")
        add_button.clicked.connect(lambda: self._add_item_row())
        remove_button = QPushButton("删除选中")
        remove_button.clicked.connect(self._remove_item_row)
        items_header.addWidget(add_button)
        items_header.addWidget(remove_button)
        layout.addLayout(items_header)

        self.items_table = QTableWidget(0, 4)
        self.items_table.setHorizontalHeaderLabels(["子项名称", "币种", "类别", "代码"])
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.items_table.setColumnWidth(1, 110)
        self.items_table.setColumnWidth(2, 130)
        self.items_table.setColumnWidth(3, 110)
        self.items_table.setMinimumHeight(170)
        self.items_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        layout.addWidget(self.items_table)

        hint = QLabel(
            "一个账户可包含多个类别子项（如证券账户下的现金、股票、债券），"
            "估值按子项分别记录。账户名称不可重复；归档后名称仍会占用。"
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        footer = QWidget(self)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(22, 10, 22, 16)
        footer_layout.setSpacing(8)
        footer_layout.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = primary_button("保存")
        save.clicked.connect(self._submit)
        footer_layout.addWidget(cancel)
        footer_layout.addWidget(save)
        outer.addWidget(footer)

        if self._account is None:
            self._add_item_row()
        self._resize_for_screen(content)

    def _resize_for_screen(self, content: QWidget) -> None:
        """限制窗口高度，内容超出时使用滚动区。"""
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            self.resize(620, 560)
            return
        available = screen.availableGeometry()
        width = min(620, int(available.width() * 0.92))
        height = min(
            content.sizeHint().height() + 90,
            int(available.height() * 0.85),
        )
        self.setMaximumHeight(int(available.height() * 0.9))
        self.resize(max(width, 480), max(height, 360))

    def _current_side(self) -> str:
        return self.side_combo.currentData() or SIDE_ASSET

    def _add_item_row(
        self,
        name: str = "",
        category: Optional[str] = None,
        item_id: Optional[int] = None,
        currency: Optional[str] = None,
        symbol: Optional[str] = None,
        interest_rate: Optional[object] = None,
        interest_start: Optional[object] = None,
    ) -> None:
        row = self.items_table.rowCount()
        self.items_table.insertRow(row)

        name_edit = QLineEdit()
        name_edit.setText(name)
        name_edit.setPlaceholderText("如：现金 / 股票 / 债券")
        currency_combo = QComboBox()
        for code in CURRENCY_CODES:
            currency_combo.addItem(f"{CURRENCY_LABELS[code]}（{code}）", code)
        target_currency = currency or self.currency_combo.currentData() or "CNY"
        index = currency_combo.findData(target_currency)
        currency_combo.setCurrentIndex(index if index >= 0 else 0)
        category_combo = QComboBox()
        for key in CATEGORIES_BY_SIDE[self._current_side()]:
            category_combo.addItem(CATEGORY_LABELS[key], key)
        if category is not None:
            index = category_combo.findData(category)
            if index >= 0:
                category_combo.setCurrentIndex(index)

        self.items_table.setCellWidget(row, 0, name_edit)
        self.items_table.setCellWidget(row, 1, currency_combo)
        self.items_table.setCellWidget(row, 2, category_combo)
        symbol_edit = QLineEdit()
        symbol_edit.setText(symbol or "")
        symbol_edit.setPlaceholderText("可选")
        self.items_table.setCellWidget(row, 3, symbol_edit)
        self._item_rows.append(
            (
                name_edit,
                currency_combo,
                category_combo,
                symbol_edit,
                item_id,
                interest_rate,
                interest_start,
            )
        )

    def _remove_item_row(self) -> None:
        row = self.items_table.currentRow()
        if row < 0:
            show_warning(self, "请选择子项", "请先在表格中选择要删除的子项。")
            return
        self.items_table.removeRow(row)
        del self._item_rows[row]

    def _on_side_changed(self, *_args) -> None:
        categories = CATEGORIES_BY_SIDE[self._current_side()]
        for row in self._item_rows:
            category_combo = row[2]
            current = category_combo.currentData()
            category_combo.blockSignals(True)
            category_combo.clear()
            for key in categories:
                category_combo.addItem(CATEGORY_LABELS[key], key)
            index = category_combo.findData(current)
            category_combo.setCurrentIndex(index if index >= 0 else 0)
            category_combo.blockSignals(False)

    def _fill(self, account: AccountOverview) -> None:
        self.name_edit.setText(account.name)
        index = self.side_combo.findData(account.side)
        if index >= 0:
            self.side_combo.setCurrentIndex(index)
        currency_index = self.currency_combo.findData(account.currency)
        self.currency_combo.setCurrentIndex(currency_index if currency_index >= 0 else 0)
        self.note_edit.setPlainText(account.note)
        for item in account.items:
            self._add_item_row(
                item.name,
                item.category,
                item.id,
                item.currency,
                item.symbol,
                item.interest_rate,
                item.interest_start,
            )
        if not account.items:
            self._add_item_row()

    def _submit(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            show_warning(self, "请填写名称", "账户名称不能为空。")
            self.name_edit.setFocus()
            return

        items = []
        for (
            name_edit,
            currency_combo,
            category_combo,
            symbol_edit,
            item_id,
            interest_rate,
            interest_start,
        ) in self._item_rows:
            items.append(
                {
                    "id": item_id,
                    "name": name_edit.text().strip(),
                    "currency": currency_combo.currentData(),
                    "category": category_combo.currentData(),
                    "symbol": symbol_edit.text().strip().upper(),
                    "interest_rate": interest_rate,
                    "interest_start": interest_start,
                }
            )
        if not items:
            show_warning(self, "缺少子项", "每个账户至少需要一个类别子项。")
            return

        payload = {
            "name": name,
            "side": self.side_combo.currentData(),
            "currency": self.currency_combo.currentData() or "CNY",
            "note": self.note_edit.toPlainText().strip(),
            "items": items,
        }
        try:
            self._on_submit(payload)
        except AccountValidationError as exc:
            show_warning(self, "无法保存", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            show_exception(self, "保存失败", exc)
            return
        self.accept()
