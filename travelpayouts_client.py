"""Thin Travelpayouts / Aviasales Data API client.

Much simpler than OAuth-based APIs: every request just carries your API
token (via the X-Access-Token header). The Data API serves cached prices
collected from real Aviasales user searches (refreshed continuously, kept
~7 days), so it's ideal for trend/drop tracking rather than live booking.

Docs: https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
"""

from __future__ import annotations

import time
from typing import Any

import requests

from config import TRAVELPAYOUTS_TOKEN, is_travelpayouts_configured

_BASE_URL = "https://api.travelpayouts.com"


class TravelpayoutsError(RuntimeError):
    """Raised when a Travelpayouts API call fails after retries."""


def tp_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET a Travelpayouts endpoint, returning parsed JSON.

    Adds the token automatically, retries with backoff on 429 rate limits.
    Raises TravelpayoutsError on persistent failure.
    """
    if not is_travelpayouts_configured():
        raise TravelpayoutsError(
            "Travelpayouts not configured. Set TRAVELPAYOUTS_TOKEN."
        )
    url = f"{_BASE_URL}{path}"
    headers = {
        "X-Access-Token": TRAVELPAYOUTS_TOKEN,
        "Accept-Encoding": "gzip, deflate",
    }
    for attempt in range(3):
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            time.sleep(1.5 * (attempt + 1))
            continue
        raise TravelpayoutsError(f"GET {path} failed: {resp.status_code} {resp.text}")
    raise TravelpayoutsError(f"GET {path} failed after retries (rate limited).")
