"""单账户估值录入页面。"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.db.engine import db
from app.services import accounts as account_service
from app.services import snapshots as snapshot_service
from app.services.accounts import AccountOverview
from app.services.snapshots import SnapshotExistsError, SnapshotRow
from app.ui.common import (
    confirm,
    make_table,
    primary_button,
    set_columns,
    show_error,
    show_warning,
    table_item,
)
from app.ui.pages.base import BasePage
from app.ui.styles import palette
from app.utils.money import AmountError, fmt_money, parse_amount


class EntryPage(BasePage):
    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(config, parent)
        self._accounts: List[AccountOverview] = []
        self._theme = config.theme
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.add_header("估值录入", "为单个账户记录某一天的当前估值；同一账户同一天可覆盖。")

        content = QHBoxLayout()
        content.setSpacing(12)

        form_panel = QFrame()
        form_panel.setObjectName("Panel")
        form_panel.setMinimumWidth(400)
        form_panel.setMaximumWidth(460)
        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(18, 16, 18, 16)
        form_layout.setSpacing(10)

        title = QLabel("录入估值")
        title.setObjectName("SectionTitle")
        form_layout.addWidget(title)

        self.account_combo = QComboBox()
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("例如 125000.00")
        self.value_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.value_edit.returnPressed.connect(self._save)
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("可选备注，例如：本月工资到账")
        self.note_edit.setFixedHeight(80)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setSpacing(9)
        form.addRow("账户 *", self.account_combo)
        form.addRow("日期 *", self.date_edit)
        form.addRow("估值 *", self.value_edit)
        form.addRow("备注", self.note_edit)
        form_layout.addLayout(form)

        self.current_label = QLabel("—")
        self.current_label.setObjectName("Hint")
        self.current_label.setWordWrap(True)
        form_layout.addWidget(self.current_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("Hint")
        form_layout.addWidget(self.status_label)

        save_button = primary_button("保存估值")
        save_button.clicked.connect(self._save)
        form_layout.addWidget(save_button)
        form_layout.addStretch(1)
        content.addWidget(form_panel)

        recent_panel = QFrame()
        recent_panel.setObjectName("Panel")
        recent_layout = QVBoxLayout(recent_panel)
        recent_layout.setContentsMargins(16, 14, 16, 14)
        recent_layout.setSpacing(8)
        recent_header = QHBoxLayout()
        recent_title = QLabel("最近估值")
        recent_title.setObjectName("SectionTitle")
        self.recent_hint = QLabel("")
        self.recent_hint.setObjectName("Hint")
        recent_header.addWidget(recent_title)
        recent_header.addStretch(1)
        recent_header.addWidget(self.recent_hint)
        recent_layout.addLayout(recent_header)
        self.recent_table = make_table(["日期", "估值", "备注"])
        set_columns(self.recent_table, [110, 150, 260])
        self.recent_table.horizontalHeader().setStretchLastSection(True)
        recent_layout.addWidget(self.recent_table, 1)
        content.addWidget(recent_panel, 1)
        self.root.addLayout(content, 1)

    def refresh(self) -> None:
        if not db.is_configured:
            return
        try:
            with db.session_scope() as session:
                accounts = account_service.list_overviews(session, include_archived=False)
        except Exception as exc:  # noqa: BLE001
            show_error(self, "加载失败", str(exc))
            return
        current_id = self.account_combo.currentData()
        self._accounts = accounts
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        for account in accounts:
            self.account_combo.addItem(account.display_name, account.id)
        if current_id is not None:
            index = self.account_combo.findData(current_id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
        self.account_combo.blockSignals(False)
        self.account_combo.setEnabled(bool(accounts))
        self._on_account_changed()

    def _selected_account(self) -> Optional[AccountOverview]:
        account_id = self.account_combo.currentData()
        if account_id is None:
            return None
        for account in self._accounts:
            if account.id == int(account_id):
                return account
        return None

    def _on_account_changed(self, *_args) -> None:
        account = self._selected_account()
        if account is None:
            self.current_label.setText("暂无未归档账户，请先到「账户管理」新增。")
            self.recent_table.setRowCount(0)
            self.recent_hint.setText("")
            return
        if account.latest_value is None:
            self.current_label.setText("该账户尚无估值记录。")
        else:
            latest_date = account.latest_date.strftime("%Y-%m-%d") if account.latest_date else "—"
            self.current_label.setText(
                f"最新估值：{fmt_money(account.latest_value, self.symbol)} （{latest_date}）"
            )
        self._load_recent(account.id)

    def _load_recent(self, account_id: int) -> None:
        if not db.is_configured:
            return
        try:
            with db.session_scope() as session:
                rows: List[SnapshotRow] = snapshot_service.list_snapshots(
                    session, account_id=account_id, limit=10
                )
        except Exception as exc:  # noqa: BLE001
            show_error(self, "加载失败", str(exc))
            return
        colors = palette(self._theme)
        self.recent_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.recent_table.setItem(
                row_index, 0, table_item(row.snapshot_date.strftime("%Y-%m-%d"))
            )
            self.recent_table.setItem(
                row_index,
                1,
                table_item(fmt_money(row.value, self.symbol), align_right=True),
            )
            self.recent_table.setItem(row_index, 2, table_item(row.note))
        self.recent_hint.setText(f"最近 {len(rows)} 条" if rows else "暂无记录")
        self.recent_hint.setStyleSheet(f"color: {colors['muted']};")

    def _save(self) -> None:
        account = self._selected_account()
        if account is None:
            show_warning(self, "请选择账户", "当前没有可录入的未归档账户。")
            return
        qdate = self.date_edit.date()
        day = date(qdate.year(), qdate.month(), qdate.day())
        try:
            value = parse_amount(self.value_edit.text(), field="估值")
        except AmountError as exc:
            show_warning(self, "无法保存", str(exc))
            self.value_edit.setFocus()
            return
        note = self.note_edit.toPlainText().strip()

        try:
            with db.session_scope() as session:
                snapshot_service.save_snapshot(
                    session,
                    account_id=account.id,
                    snapshot_date=day,
                    value=value,
                    note=note,
                )
        except SnapshotExistsError as exc:
            if not confirm(
                self,
                "覆盖已有估值",
                f"账户 “{account.name}” 在 {day.strftime('%Y-%m-%d')} 已有估值 "
                f"{fmt_money(exc.value, self.symbol)}。\n是否覆盖？",
            ):
                return
            try:
                with db.session_scope() as session:
                    snapshot_service.save_snapshot(
                        session,
                        account_id=account.id,
                        snapshot_date=day,
                        value=value,
                        note=note,
                        overwrite=True,
                    )
            except Exception as overwrite_error:  # noqa: BLE001
                show_error(self, "保存失败", str(overwrite_error))
                return
        except Exception as exc:  # noqa: BLE001
            show_error(self, "保存失败", str(exc))
            return

        self.status_label.setStyleSheet("color: #059669;")
        self.status_label.setText(
            f"已保存：{account.name} · {day.strftime('%Y-%m-%d')} · "
            f"{fmt_money(value, self.symbol)}"
        )
        self.value_edit.clear()
        self.note_edit.clear()
        self.refresh()
        self.data_changed.emit()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        account_id = self.account_combo.currentData()
        if account_id is not None:
            self._load_recent(int(account_id))
