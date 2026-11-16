"""子项成本批次空行处理。"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QDate, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.profit import LotInput  # noqa: E402
from app.ui.dialogs.item_dialog import ItemDialog  # noqa: E402

_APP = QApplication.instance() or QApplication([])


def _make_dialog() -> ItemDialog:
    return ItemDialog(
        "asset",
        name="人民币现金",
        category="cash",
        valuation_mode="manual",
        allow_lots=True,
        lots=[],
    )


def test_blank_lot_row_is_ignored():
    dialog = _make_dialog()
    try:
        table = dialog.lots_editor.table
        assert table.rowCount() == 1
        assert dialog.lot_values() == []
    finally:
        dialog.close()


def test_filled_lot_row_is_returned():
    dialog = _make_dialog()
    try:
        table = dialog.lots_editor.table
        table.item(0, 0).setText("2026-01-05")
        table.item(0, 1).setText("100")
        table.item(0, 2).setText("1.25")
        lots = dialog.lot_values()
        assert len(lots) == 1
        assert lots[0].quantity == Decimal("100")
    finally:
        dialog.close()


def test_quantity_without_date_still_raises():
    dialog = _make_dialog()
    try:
        dialog.lots_editor.table.item(0, 1).setText("100")
        with pytest.raises(ValueError, match="买入日期"):
            dialog.lot_values()
    finally:
        dialog.close()


def test_lot_date_cell_is_not_text_editable():
    dialog = _make_dialog()
    try:
        editor = dialog.lots_editor
        date_item = editor.table.item(0, 0)
        assert not date_item.flags() & Qt.ItemFlag.ItemIsEditable
        editor.set_date(0, QDate(2026, 3, 8))
        assert date_item.text() == "2026-03-08"
        assert editor.table.item(0, 1).flags() & Qt.ItemFlag.ItemIsEditable
    finally:
        dialog.close()


def test_existing_lots_are_loaded_with_date():
    lots = [
        LotInput(
            trade_date=date(2026, 1, 5),
            quantity=Decimal("100"),
            unit_cost=Decimal("1.25"),
            fee=Decimal("0"),
            currency="CNY",
        )
    ]
    dialog = ItemDialog(
        "asset",
        name="人民币现金",
        category="cash",
        valuation_mode="manual",
        allow_lots=True,
        lots=lots,
        cost_currency="CNY",
    )
    try:
        table = dialog.lots_editor.table
        assert table.item(0, 0).text() == "2026-01-05"
        values = dialog.lot_values()
        assert len(values) == 1
        assert values[0].trade_date == date(2026, 1, 5)
        assert values[0].quantity == Decimal("100")
    finally:
        dialog.close()
