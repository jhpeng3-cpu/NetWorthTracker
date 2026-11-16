"""汇率请求缓存与主动刷新。"""
from __future__ import annotations

import json
from decimal import Decimal

from app.services import exchange_rates


def test_rate_cache_and_force_refresh(monkeypatch):
    exchange_rates.clear_cache()
    calls: list[str] = []

    def fake_fetch(url: str, timeout: float = 0) -> bytes:
        calls.append(url)
        return json.dumps({"cny": {"usd": 0.15}}).encode("utf-8")

    monkeypatch.setattr(exchange_rates, "fetch_bytes", fake_fetch)
    monkeypatch.setattr(
        exchange_rates,
        "_SOURCES",
        [("https://rate.test/cny.json", exchange_rates._parse_currency_api)],
    )

    rates, source = exchange_rates.fetch_latest_rates(force=True)
    assert source == "https://rate.test/cny.json"
    assert rates["USD"] == Decimal("6.666667")
    assert len(calls) == 1

    cached_rates, _ = exchange_rates.fetch_latest_rates()
    assert cached_rates == rates
    assert len(calls) == 1

    exchange_rates.fetch_latest_rates(force=True)
    assert len(calls) == 2
    exchange_rates.clear_cache()
