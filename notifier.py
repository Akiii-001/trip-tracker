"""Telegram notification helper.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID lazily (via config) so load
order doesn't matter. Adapted from the stock-bot notifier.
"""

from __future__ import annotations

from typing import Any

import requests

from config import _get


def _token() -> str:
    return _get("TELEGRAM_BOT_TOKEN")


def _chat_id() -> str:
    return _get("TELEGRAM_CHAT_ID")


def is_telegram_configured() -> bool:
    return bool(_token() and _chat_id())


def send_telegram(message: str, parse_mode: str = "Markdown") -> bool:
    """Send a message to the configured Telegram chat. Returns True on success."""
    token = _token()
    chat_id = _chat_id()
    if not (token and chat_id):
        print("Telegram not configured (missing token or chat id).")
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200 and r.json().get("ok"):
            return True
        print(f"Telegram error: {r.status_code} {r.text}")
        return False
    except Exception as exc:
        print(f"Telegram send failed: {exc}")
        return False
