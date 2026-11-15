"""密码的简单可逆混淆（仅防止 shoulder-surfing，并非安全加密）。"""
from __future__ import annotations

import base64

_PREFIX = "obf:"
_KEY = b"NetWorthTracker#2024"


def obfuscate(text: str) -> str:
    if not text:
        return ""
    data = text.encode("utf-8")
    mixed = bytes(byte ^ _KEY[i % len(_KEY)] for i, byte in enumerate(data))
    return _PREFIX + base64.urlsafe_b64encode(mixed).decode("ascii")


def deobfuscate(text: str) -> str:
    if not text:
        return ""
    if not text.startswith(_PREFIX):
        return text
    try:
        raw = base64.urlsafe_b64decode(text[len(_PREFIX):].encode("ascii"))
        data = bytes(byte ^ _KEY[i % len(_KEY)] for i, byte in enumerate(raw))
        return data.decode("utf-8")
    except Exception:
        return ""
