"""类别子项编辑对话框，可同时维护估值参数与成本批次。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.db.models import (
    CATEGORY_LABELS,
    CATEGORIES_BY_SIDE,
    COMPOUNDING_LABELS,
    CURRENCY_CODES,
    CURRENCY_LABELS,
    PAY_FREQUENCIES,
    PAY_FREQUENCY_LABELS,
    VALUATION_ACCRUAL,
    VALUATION_AUTO,
    VALUATION_MANUAL,
    VALUATION_MODE_LABELS,
    VALUATION_MODES,
    allowed_valuation_modes,
    default_valuation_mode,
)
from app.services import quotes
from app.services.profit import LotInput
from app.ui.common import (
    date_edit,
    dialog_footer,
    parse_optional_decimal,
    run_save,
    show_warning,
)
from app.ui.widgets.lots_editor import LotsEditor
from app.utils.money import fmt_number

MARKETS = [
    ("自动识别", ""),
    ("A 股 / 场内", "CN"),
    ("港股", "HK"),
    ("美股", "US"),
    ("公募基金", "FUND"),
    ("黄金现货", "GOLD"),
    ("白银现货", "SILVER"),
    ("大宗商品", "COMMODITY"),
]
AUTO_UNITS = {"", "股", "份", "克", "千克", "桶", "吨", "百万英热"}


def _date_row(
    parent: QWidget, default_day: date, enabled: bool
) -> tuple:
    """返回（容器, 复选框, 日期编辑框）。"""
    check = QCheckBox("自")
    edit = date_edit(default_day)
    check.setChecked(enabled)
    edit.setEnabled(enabled)
    check.toggled.connect(edit.setEnabled)
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(check)
    layout.addWidget(edit, 1)
    return row, check, edit


def _read_date(check: QCheckBox, edit: QDateEdit) -> Optional[date]:
    if not check.isChecked():
        return None
    value = edit.date()
    return date(value.year(), value.month(), value.day())


class ItemDialog(QDialog):
    def __init__(
        self,
        side: str,
        name: str = "",
        category: Optional[str] = None,
        title: str = "类别子项",
        parent: Optional[QWidget] = None,
        allow_lots: bool = False,
        lots_only: bool = False,
        lots: Optional[List[LotInput]] = None,
        cost_currency: str = "CNY",
        currency: str = "CNY",
        symbol: str = "",
        interest_rate: Optional[Decimal] = None,
        interest_start: Optional[date] = None,
        valuation_mode: Optional[str] = None,
        quantity: Optional[Decimal] = None,
        unit: str = "",
        principal: Optional[Decimal] = None,
        face_value: Optional[Decimal] = None,
        maturity_date: Optional[date] = None,
        pay_frequency: str = "none",
        compounding: str = "simple",
        early_withdraw_rate: Optional[Decimal] = None,
        price_source: str = "",
        next_valuation: Optional[date] = None,
        asset_meta: Optional[dict] = None,
        on_save: Optional[Callable[["ItemDialog"], None]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(720 if allow_lots else 420)
        self.setModal(True)
        self.side = side
        self.allow_lots = allow_lots
        self.lots_only = lots_only
        self._on_save = on_save
        self._asset_meta = asset_meta or {}
        self._original_valuation = {
            "valuation_mode": valuation_mode or VALUATION_MANUAL,
            "quantity": quantity,
            "unit": unit,
            "principal": principal,
            "face_value": face_value,
            "maturity_date": maturity_date,
            "pay_frequency": pay_frequency or "none",
            "compounding": compounding or "simple",
            "early_withdraw_rate": early_withdraw_rate,
            "price_source": price_source,
            "next_valuation": next_valuation,
        }

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
        self.name_edit.setPlaceholderText("例如：现金、股票、债券")
        self.name_edit.setText(name)
        self.currency_combo = QComboBox()
        for code in CURRENCY_CODES:
            self.currency_combo.addItem(f"{CURRENCY_LABELS[code]}（{code}）", code)
        index = self.currency_combo.findData(currency)
        if index >= 0:
            self.currency_combo.setCurrentIndex(index)
        self.category_combo = QComboBox()
        for key in CATEGORIES_BY_SIDE.get(side, []):
            self.category_combo.addItem(CATEGORY_LABELS[key], key)
        if category is not None:
            index = self.category_combo.findData(category)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
        self._stored_category = self.category_combo.currentData()
        self._stored_mode = valuation_mode

        if not lots_only:
            form = QFormLayout()
            form.setLabelAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            form.setSpacing(8)
            form.addRow("子项名称 *", self.name_edit)
            form.addRow("币种 *", self.currency_combo)
            form.addRow("类别 *", self.category_combo)
            if side == "asset":
                self.mode_combo = QComboBox()
                form.addRow("估值方式 *", self.mode_combo)
            else:
                self.rate_edit = QLineEdit()
                self.rate_edit.setPlaceholderText("如 4.25；留空表示不计息")
                if interest_rate is not None:
                    self.rate_edit.setText(fmt_number(interest_rate, 3))
                start_row, self.start_check, self.start_edit = _date_row(
                    self, interest_start or date.today(), interest_start is not None
                )
                start_hint = QLabel("留空则从首次估值起算")
                start_hint.setObjectName("Hint")
                start_row.layout().addWidget(start_hint)
                form.addRow("年利率(%)", self.rate_edit)
                form.addRow("计息起始日", start_row)
            layout.addLayout(form)

            if side == "asset":
                self.auto_group = self._build_auto_group(symbol, quantity, unit)
                self.accrual_group = self._build_accrual_group(
                    interest_rate,
                    interest_start,
                    principal,
                    face_value,
                    maturity_date,
                    pay_frequency,
                    compounding,
                    early_withdraw_rate,
                )
                self.manual_group = self._build_manual_group(next_valuation)
                layout.addWidget(self.auto_group)
                layout.addWidget(self.accrual_group)
                layout.addWidget(self.manual_group)
                self.mode_combo.currentIndexChanged.connect(
                    self._update_mode_visibility
                )
                self.category_combo.currentIndexChanged.connect(
                    self._on_category_changed
                )
                self._refresh_mode_options(valuation_mode)
                self._apply_category_defaults()

        if allow_lots:
            layout.addWidget(self._build_lots_group(cost_currency, lots or []))

        footer = QWidget(self)
        footer_layout = dialog_footer(self, self._submit)
        footer_layout.setContentsMargins(22, 10, 22, 16)
        footer_layout.setSpacing(8)
        footer.setLayout(footer_layout)
        outer.addWidget(footer)

        self._resize_for_screen(content)

    def _resize_for_screen(self, content: QWidget) -> None:
        """按内容与屏幕可用高度调整窗口，超出时由滚动区承载。"""
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            self.resize(760 if self.allow_lots else 460, 620)
            return
        available = screen.availableGeometry()
        width = 760 if self.allow_lots else 460
        width = min(width, int(available.width() * 0.92))
        height = min(
            content.sizeHint().height() + 90,
            int(available.height() * 0.85),
        )
        self.resize(max(width, 400), max(height, 360))

    # ---- 估值参数 ----

    def _build_auto_group(
        self, symbol: str, quantity: Optional[Decimal], unit: str
    ) -> QGroupBox:
        group = QGroupBox("行情估值参数")
        form = QFormLayout(group)
        form.setSpacing(8)
        self.symbol_edit = QLineEdit()
        self.symbol_edit.setText(symbol)
        self.symbol_edit.setPlaceholderText("如 600519 / 00700 / AAPL")
        self.market_combo = QComboBox()
        for label, code in MARKETS:
            self.market_combo.addItem(label, code)
        self.quantity_edit = QLineEdit()
        self.quantity_edit.setPlaceholderText("数量 / 份额 / 克数")
        if quantity is not None:
            self.quantity_edit.setText(fmt_number(quantity, 4))
        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText("股 / 份 / 克")
        self.unit_edit.setText(unit)
        self.symbol_label = QLabel("代码")
        form.addRow(self.symbol_label, self.symbol_edit)
        self.commodity_combo = QComboBox()
        for code, label in quotes.COMMODITY_LABELS.items():
            self.commodity_combo.addItem(f"{label}（{code}）", code)
        self.commodity_label = QLabel("品种")
        form.addRow(self.commodity_label, self.commodity_combo)
        code = quotes.normalize_commodity(symbol)
        combo_index = self.commodity_combo.findData(code)
        self.commodity_combo.setCurrentIndex(combo_index if combo_index >= 0 else 0)
        self.commodity_label.setVisible(False)
        self.commodity_combo.setVisible(False)
        form.addRow("市场", self.market_combo)
        form.addRow("数量", self.quantity_edit)
        form.addRow("单位", self.unit_edit)
        self.auto_hint = QLabel("")
        self.auto_hint.setObjectName("Hint")
        self.auto_hint.setWordWrap(True)
        form.addRow("", self.auto_hint)
        self.symbol_edit.textChanged.connect(self._on_symbol_changed)
        self.commodity_combo.currentIndexChanged.connect(self._on_symbol_changed)
        return group

    def _build_accrual_group(
        self,
        interest_rate: Optional[Decimal],
        interest_start: Optional[date],
        principal: Optional[Decimal],
        face_value: Optional[Decimal],
        maturity_date: Optional[date],
        pay_frequency: str,
        compounding: str,
        early_withdraw_rate: Optional[Decimal],
    ) -> QGroupBox:
        group = QGroupBox("计息估值参数")
        form = QFormLayout(group)
        form.setSpacing(8)
        self.principal_edit = QLineEdit()
        self.principal_edit.setPlaceholderText("存款本金")
        if principal is not None:
            self.principal_edit.setText(f"{principal:.2f}")
        self.face_edit = QLineEdit()
        self.face_edit.setPlaceholderText("债券面值")
        if face_value is not None:
            self.face_edit.setText(f"{face_value:.2f}")
        self.rate_edit = QLineEdit()
        self.rate_edit.setPlaceholderText("如 4.25；留空表示不计息")
        if interest_rate is not None:
            self.rate_edit.setText(fmt_number(interest_rate, 3))
        rate_row = QHBoxLayout()
        rate_row.addWidget(self.rate_edit, 1)
        rate_hint = QLabel("%/年")
        rate_hint.setObjectName("Hint")
        rate_row.addWidget(rate_hint)
        rate_widget = QWidget(group)
        rate_widget.setLayout(rate_row)
        start_row, self.start_check, self.start_edit = _date_row(
            group, interest_start or date.today(), interest_start is not None
        )
        maturity_row, self.maturity_check, self.maturity_edit = _date_row(
            group, maturity_date or date.today(), maturity_date is not None
        )
        self.pay_combo = QComboBox()
        for key in PAY_FREQUENCIES:
            self.pay_combo.addItem(PAY_FREQUENCY_LABELS[key], key)
        pay_index = self.pay_combo.findData(pay_frequency or "none")
        self.pay_combo.setCurrentIndex(pay_index if pay_index >= 0 else 0)
        self.compounding_combo = QComboBox()
        for key, label in COMPOUNDING_LABELS.items():
            self.compounding_combo.addItem(label, key)
        comp_index = self.compounding_combo.findData(compounding or "simple")
        self.compounding_combo.setCurrentIndex(comp_index if comp_index >= 0 else 0)
        self.early_edit = QLineEdit()
        self.early_edit.setPlaceholderText("提前支取时适用的年利率（%）")
        if early_withdraw_rate is not None:
            self.early_edit.setText(fmt_number(early_withdraw_rate, 3))
        form.addRow("本金", self.principal_edit)
        form.addRow("面值", self.face_edit)
        form.addRow("年利率", rate_widget)
        form.addRow("起息日", start_row)
        form.addRow("到期日", maturity_row)
        form.addRow("付息方式", self.pay_combo)
        form.addRow("计息方式", self.compounding_combo)
        form.addRow("提前支取利率", self.early_edit)
        return group

    def _build_manual_group(self, next_valuation: Optional[date]) -> QGroupBox:
        group = QGroupBox("手动估值提醒")
        form = QFormLayout(group)
        form.setSpacing(8)
        row, self.next_check, self.next_edit = _date_row(
            group, next_valuation or date.today(), next_valuation is not None
        )
        hint = QLabel("市值取最近一条估值快照；到期未更新会在启动时提醒。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        form.addRow("下次估值日", row)
        form.addRow("", hint)
        return group

    def _refresh_mode_options(self, preferred: Optional[str] = None) -> None:
        """按类别重建估值方式下拉，只保留该类别支持的方式。"""
        if not hasattr(self, "mode_combo"):
            return
        category = self.category_combo.currentData()
        allowed = allowed_valuation_modes(category)
        current = self.mode_combo.currentData()
        target = preferred if preferred in allowed else None
        if target is None and current in allowed:
            target = current

        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        for mode in allowed:
            self.mode_combo.addItem(VALUATION_MODE_LABELS[mode], mode)
        legacy = (
            target is None
            and category == self._stored_category
            and self._stored_mode in VALUATION_MODES
            and self._stored_mode not in allowed
        )
        if legacy:
            self.mode_combo.addItem(
                f"{VALUATION_MODE_LABELS.get(self._stored_mode, self._stored_mode)}"
                "（当前值，不推荐）",
                self._stored_mode,
            )
            target = self._stored_mode
        if target is None:
            target = allowed[0]
        index = self.mode_combo.findData(target)
        self.mode_combo.setCurrentIndex(index if index >= 0 else 0)
        self.mode_combo.blockSignals(False)
        self._update_mode_visibility()

    def _apply_category_defaults(self) -> None:
        """按类别调整代码、市场、单位提示。"""
        if not hasattr(self, "auto_group"):
            return
        category = self.category_combo.currentData()
        self.market_combo.setEnabled(True)
        if category == "gold":
            self.symbol_edit.setPlaceholderText("XAU（可留空，自动使用现货黄金）")
            self._select_market("GOLD", enabled=False)
            self._set_default_unit("克")
        elif category == "silver":
            self.symbol_edit.setPlaceholderText("XAG（可留空，自动使用现货白银）")
            self._select_market("SILVER", enabled=False)
            self._set_default_unit("克")
        elif category == "commodity":
            self._show_commodity_selector(True)
            self._select_market("COMMODITY", enabled=False)
            self._update_auto_hint()
        elif category == "fund":
            self.symbol_edit.setPlaceholderText("6 位基金代码")
            self._select_market("FUND", enabled=False)
            self._set_default_unit("份")
        elif category == "stock":
            self.symbol_edit.setPlaceholderText("600519 / 00700 / AAPL")
            if self.market_combo.currentData() not in ("CN", "HK", "US"):
                self._select_market("", enabled=True)
            else:
                self.market_combo.setEnabled(True)
            self._set_default_unit("股")
        else:
            self.symbol_edit.setPlaceholderText("如 600519 / 00700 / AAPL")
            self._select_market("", enabled=True)
        if category != "commodity":
            self._show_commodity_selector(False)
        self._update_auto_hint()

    def _show_commodity_selector(self, visible: bool) -> None:
        self.symbol_label.setVisible(not visible)
        self.symbol_edit.setVisible(not visible)
        self.commodity_label.setVisible(visible)
        self.commodity_combo.setVisible(visible)

    def _select_market(self, code: str, enabled: bool) -> None:
        index = self.market_combo.findData(code)
        if index >= 0:
            self.market_combo.setCurrentIndex(index)
        self.market_combo.setEnabled(enabled)

    def _set_default_unit(self, default: str) -> None:
        if self.unit_edit.text().strip() in AUTO_UNITS:
            self.unit_edit.setText(default)

    def _on_symbol_changed(self) -> None:
        if self.category_combo.currentData() == "commodity":
            self._update_auto_hint()

    def _update_auto_hint(self) -> None:
        if not hasattr(self, "auto_hint"):
            return
        category = self.category_combo.currentData()
        if category == "commodity":
            code = self.commodity_combo.currentData() or ""
            unit = quotes.COMMODITY_UNITS.get(code, "")
            label = quotes.COMMODITY_LABELS.get(code, "")
            if unit:
                self.auto_hint.setText(f"行情：{code} {label} · {unit}，数量按该单位填写")
                self._set_default_unit(unit.replace("元/", ""))
            else:
                self.auto_hint.setText("请选择大宗商品品种")
                self._set_default_unit("")
        elif category == "gold":
            self.auto_hint.setText("行情：现货黄金折算人民币/克，数量填克数")
        elif category == "silver":
            self.auto_hint.setText("行情：现货白银折算人民币/克，数量填克数")
        elif category == "fund":
            self.auto_hint.setText("行情：基金最近确认净值，单位「份」")
        elif category == "stock":
            self.auto_hint.setText("行情：股票 / ETF 实时价，数量单位默认「股」")
        else:
            self.auto_hint.setText("")

    def _on_category_changed(self) -> None:
        if not hasattr(self, "mode_combo"):
            return
        category = self.category_combo.currentData()
        self._refresh_mode_options(default_valuation_mode(category))
        self._apply_category_defaults()

    def _update_mode_visibility(self) -> None:
        if not hasattr(self, "auto_group"):
            return
        mode = self.mode_combo.currentData()
        self.auto_group.setVisible(mode == VALUATION_AUTO)
        self.accrual_group.setVisible(mode == VALUATION_ACCRUAL)
        self.manual_group.setVisible(mode == VALUATION_MANUAL)

    # ---- 成本批次 ----

    def _build_lots_group(
        self, cost_currency: str, lots: List[LotInput]
    ) -> LotsEditor:
        self.lots_editor = LotsEditor(lots, cost_currency, self)
        return self.lots_editor

    def lot_values(self) -> List[LotInput]:
        return self.lots_editor.values()

    def cost_currency(self) -> str:
        return self.lots_editor.cost_currency()

    def currency_value(self) -> str:
        return self.currency_combo.currentData()

    def symbol_value(self) -> str:
        if not hasattr(self, "symbol_edit"):
            return ""
        category = self.category_combo.currentData()
        if category == "commodity":
            return self.commodity_combo.currentData() or ""
        text = self.symbol_edit.text().strip().upper()
        if not text and category == "gold":
            return "XAU"
        if not text and category == "silver":
            return "XAG"
        return text

    # ---- 提交 ----

    def interest_values(self) -> tuple:
        """年利率与计息起始日；未填写时均为 None。"""
        if not hasattr(self, "rate_edit"):
            return None, None
        text = self.rate_edit.text().strip().replace("%", "").replace("％", "")
        day = _read_date(self.start_check, self.start_edit)
        if not text:
            if day is not None:
                raise ValueError("填写计息起始日前，请先填写年利率。")
            return None, None
        try:
            rate = Decimal(text)
        except (ArithmeticError, ValueError):
            raise ValueError("年利率必须是数字。") from None
        if rate < 0 or rate > 100:
            raise ValueError("年利率应在 0% 至 100% 之间。")
        return rate.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP), day

    def valuation_values(self) -> dict:
        """估值方式与扩展参数；负债与仅成本批次场景返回原值。"""
        if self.side != "asset" or not hasattr(self, "mode_combo"):
            values = dict(self._original_valuation)
            values["valuation_mode"] = VALUATION_MANUAL
            return values

        mode = self.mode_combo.currentData() or VALUATION_MANUAL
        unit = self.unit_edit.text().strip()
        if len(unit) > 8:
            raise ValueError("单位不能超过 8 个字符。")
        quantity = parse_optional_decimal(self.quantity_edit.text(), "数量", "0.0001")
        principal = parse_optional_decimal(self.principal_edit.text(), "本金", "0.01")
        face_value = parse_optional_decimal(self.face_edit.text(), "面值", "0.01")
        early_rate = parse_optional_decimal(
            self.early_edit.text(), "提前支取利率", "0.001", Decimal("100")
        )
        return {
            "valuation_mode": mode,
            "quantity": quantity,
            "unit": unit,
            "principal": principal,
            "face_value": face_value,
            "maturity_date": _read_date(self.maturity_check, self.maturity_edit),
            "pay_frequency": self.pay_combo.currentData() or "none",
            "compounding": self.compounding_combo.currentData() or "simple",
            "early_withdraw_rate": early_rate,
            "price_source": self._original_valuation.get("price_source") or "",
            "next_valuation": _read_date(self.next_check, self.next_edit),
            "asset_meta": self._asset_meta or None,
        }

    def values(self) -> tuple:
        rate, start = self.interest_values()
        return (
            self.name_edit.text().strip(),
            self.category_combo.currentData(),
            self.symbol_value(),
            rate,
            start,
        )

    def _current_mode(self) -> str:
        if not hasattr(self, "mode_combo"):
            return self._original_valuation.get("valuation_mode") or VALUATION_MANUAL
        return self.mode_combo.currentData() or VALUATION_MANUAL

    def _submit(self) -> None:
        if not self.lots_only:
            name = self.name_edit.text().strip()
            if not name:
                show_warning(self, "请填写名称", "子项名称不能为空。")
                self.name_edit.setFocus()
                return
            try:
                _name, _category, _symbol, rate, _start = self.values()
                self.valuation_values()
                if self.allow_lots:
                    self.lot_values()
                if (
                    self.side == "asset"
                    and self._current_mode() == VALUATION_ACCRUAL
                    and rate is None
                ):
                    raise ValueError("计息增值需要填写年利率。")
            except ValueError as exc:
                show_warning(self, "无法保存", str(exc))
                return
        elif self.allow_lots:
            try:
                self.lot_values()
            except ValueError as exc:
                show_warning(self, "成本批次有误", str(exc))
                return

        if self._on_save is not None and not run_save(
            self, lambda: self._on_save(self)
        ):
            return
        self.accept()
