"""子项成本批次空行处理。"""
from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

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
        assert dialog.lots_table.rowCount() == 1
        assert dialog.lot_values() == []
    finally:
        dialog.close()


def test_filled_lot_row_is_returned():
    dialog = _make_dialog()
    try:
        dialog.lots_table.item(0, 0).setText("2026-01-05")
        dialog.lots_table.item(0, 1).setText("100")
        dialog.lots_table.item(0, 2).setText("1.25")
        lots = dialog.lot_values()
        assert len(lots) == 1
        assert lots[0].quantity == Decimal("100")
    finally:
        dialog.close()


def test_quantity_without_date_still_raises():
    dialog = _make_dialog()
    try:
        dialog.lots_table.item(0, 1).setText("100")
        with pytest.raises(ValueError, match="买入日期"):
            dialog.lot_values()
    finally:
        dialog.close()
