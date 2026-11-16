"""行情适配器公共类型与 HTTP 工具。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from app.utils.http_client import fetch_bytes

HTTP_TIMEOUT = 4.0


class QuoteError(Exception):
    """单个代码的行情获取失败。"""


@dataclass(frozen=True)
class PricePoint:
    """统一行情点：价格 + 币种 + 时间 + 数据源。"""

    symbol: str
    market: str
    price: Decimal
    currency: str
    quote_time: Optional[datetime]
    source: str
    name: str = ""
    unit: str = ""


def http_get(url: str, referer: Optional[str] = None) -> bytes:
    return fetch_bytes(url, referer=referer, timeout=HTTP_TIMEOUT)


def to_price(value: object) -> Optional[Decimal]:
    try:
        price = Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None
    if price <= 0:
        return None
    return price


_LAST_REQUEST = 0.0
_MIN_INTERVAL = 0.05
_THROTTLE_LOCK = threading.Lock()


def throttle() -> None:
    """简单限频：两次外部请求之间至少间隔 0.05 秒。"""
    global _LAST_REQUEST
    with _THROTTLE_LOCK:
        elapsed = time.monotonic() - _LAST_REQUEST
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        _LAST_REQUEST = time.monotonic()
