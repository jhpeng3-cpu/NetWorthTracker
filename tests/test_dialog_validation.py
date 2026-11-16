"""弹窗保存校验：失败时保持打开，不丢失已填内容。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.db.models import VALUATION_ACCRUAL, VALUATION_MANUAL  # noqa: E402
from app.ui import common  # noqa: E402
from app.ui.dialogs import item_dialog as item_dialog_module  # noqa: E402
from app.ui.dialogs.item_dialog import ItemDialog  # noqa: E402

_APP = QApplication.instance() or QApplication([])


@pytest.fixture()
def warnings(monkeypatch):
    messages = []
    monkeypatch.setattr(
        item_dialog_module,
        "show_warning",
        lambda _parent, _title, text: messages.append(text),
    )
    monkeypatch.setattr(
        common, "show_warning", lambda _parent, _title, text: messages.append(text)
    )
    return messages


def test_accrual_without_rate_keeps_dialog_open(warnings):
    dialog = ItemDialog(
        "asset",
        name="货币基金",
        category="cash",
        valuation_mode=VALUATION_ACCRUAL,
    )
    try:
        dialog._submit()
        assert dialog.result() == 0
        assert warnings and "年利率" in warnings[0]
        assert dialog.name_edit.text() == "货币基金"
    finally:
        dialog.close()


def test_save_callback_error_keeps_dialog_open(warnings):
    def save(_dialog: ItemDialog) -> None:
        raise ValueError("后端拒绝保存")

    dialog = ItemDialog(
        "asset",
        name="现金",
        category="cash",
        valuation_mode=VALUATION_MANUAL,
        on_save=save,
    )
    try:
        dialog._submit()
        assert dialog.result() == 0
        assert warnings == ["后端拒绝保存"]
    finally:
        dialog.close()


def test_save_callback_success_accepts(warnings):
    saved = []

    dialog = ItemDialog(
        "asset",
        name="现金",
        category="cash",
        valuation_mode=VALUATION_MANUAL,
        on_save=lambda dlg: saved.append(dlg.name_edit.text()),
    )
    try:
        dialog._submit()
        assert saved == ["现金"]
        assert dialog.result() == 1
    finally:
        dialog.close()
