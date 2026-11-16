"""HTTP GET 工具：优先直连，直连失败时回退系统代理。

Windows 上 urllib 默认会读取系统代理。若本机代理较慢，每次行情请求都会被
额外拖慢数秒；行情与汇率源均为公开接口，因此默认绕过代理直连。
只有直连失败（超时、DNS、连接被拒）时才尝试系统代理，并记住该主机，
避免后续请求重复等待。
"""
from __future__ import annotations

import threading
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import urlsplit

DEFAULT_TIMEOUT = 5.0
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NetWorthTracker"

_PROXY_HOSTS: set[str] = set()
_LOCK = threading.Lock()


def _request(url: str, referer: Optional[str]) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer
    return urllib.request.Request(url, headers=headers)


def _open(request: urllib.request.Request, timeout: float, use_proxy: bool) -> bytes:
    handlers = [] if use_proxy else [urllib.request.ProxyHandler({})]
    opener = urllib.request.build_opener(*handlers)
    with opener.open(request, timeout=timeout) as response:
        return response.read()


def fetch_bytes(
    url: str,
    referer: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> bytes:
    """获取 URL 内容；默认直连，直连不可用时回退系统代理。"""
    host = (urlsplit(url).hostname or "").lower()
    with _LOCK:
        prefer_proxy = host in _PROXY_HOSTS

    if prefer_proxy:
        return _open(_request(url, referer), timeout, use_proxy=True)

    try:
        return _open(_request(url, referer), timeout, use_proxy=False)
    except urllib.error.HTTPError:
        # 能拿到 HTTP 响应说明网络可达，不因业务状态码切换代理。
        raise
    except Exception as direct_error:  # noqa: BLE001 - 直连失败后回退代理
        with _LOCK:
            _PROXY_HOSTS.add(host)
        try:
            return _open(_request(url, referer), timeout, use_proxy=True)
        except Exception:  # noqa: BLE001
            raise direct_error
