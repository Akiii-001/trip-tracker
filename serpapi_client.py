"""Thin SerpApi client (shared by flights + hotels).

SerpApi returns live Google Flights / Google Hotels results as structured
JSON. One API key + one quota (free plan = 250 searches/month) covers both
engines. Each call to search() counts as one search against the quota.

Docs: https://serpapi.com/google-flights-api , https://serpapi.com/google-hotels-api
"""

from __future__ import annotations

from typing import Any

import requests

from config import SERPAPI_KEY, is_serpapi_configured

_URL = "https://serpapi.com/search.json"


class SerpApiError(RuntimeError):
    """Raised when a SerpApi call fails."""


def serpapi_search(params: dict[str, Any]) -> dict[str, Any]:
    """Run one SerpApi search. Adds the api_key automatically.

    Raises SerpApiError on transport/HTTP failure or an API-level error
    field in the JSON body.
    """
    if not is_serpapi_configured():
        raise SerpApiError("SerpApi not configured. Set SERPAPI_KEY.")
    q = {**params, "api_key": SERPAPI_KEY}
    try:
        resp = requests.get(_URL, params=q, timeout=45)
    except Exception as exc:
        raise SerpApiError(f"request failed: {exc}") from exc
    if resp.status_code != 200:
        raise SerpApiError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if data.get("error"):
        raise SerpApiError(str(data["error"]))
    return data
