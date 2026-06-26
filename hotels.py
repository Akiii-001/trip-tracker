"""Hotel price lookups via SerpApi Google Hotels.

Strategy ("track-all"): one area search per island returns ~20 hotels in a
single response (one SerpApi credit). We log EVERY returned hotel's price,
keyed by its stable Google `property_token`, so over time we accumulate a
growing roster of every hotel we've seen — with full price history for
each — without spending extra credits.

Prices are tracked PER NIGHT (matches how Google shows them and how the
max-price ceiling is expressed). The full-stay total is also captured.

Selection for alerting: among hotels meeting rating/review floors, the
cheapest is the island's "best value" — that's what drives Telegram
alerts (so we don't ping for all 20 hotels). Floors relax gracefully so
thinly-reviewed island hotels still qualify.

Ratings are Google's overall rating (the Google Maps stars).

Docs: https://serpapi.com/google-hotels-api
"""

from __future__ import annotations

from typing import Any

from config import CURRENCY, is_serpapi_configured

_SORT_HIGHEST_RATING = 8  # Google Hotels sort_by code
DEFAULT_MIN_RATING = 4.2
DEFAULT_MIN_REVIEWS = 50


def is_hotel_provider_configured() -> bool:
    return is_serpapi_configured()


# --------------------------- price helpers --------------------------- #


def _rate(node_holder: dict, key: str) -> float | None:
    node = node_holder.get(key) or {}
    val = node.get("extracted_lowest")
    return float(val) if isinstance(val, (int, float)) else None


def _extract_sites(prop: dict) -> list[dict[str, Any]]:
    """Per-site prices [{source, price, link}] (per-night preferred), cheapest first."""
    by_source: dict[str, dict[str, Any]] = {}
    for arr_key in ("featured_prices", "prices"):
        for item in prop.get(arr_key) or []:
            source = item.get("source") or item.get("name") or "Unknown"
            price = _rate(item, "rate_per_night") or _rate(item, "total_rate")
            if price is None:
                continue
            link = item.get("link") or item.get("url") or ""
            if source not in by_source or price < by_source[source]["price"]:
                by_source[source] = {"price": price, "link": link}
    sites = [
        {"source": s, "price": round(v["price"], 2), "link": v["link"]}
        for s, v in by_source.items()
    ]
    sites.sort(key=lambda x: x["price"])
    return sites


# --------------------------- area search --------------------------- #


def search_candidates(
    query: str,
    checkin: str,
    checkout: str,
    adults: int = 1,
    max_price_per_night: float | None = None,
    limit: int = 40,
    sort_by_rating: bool = True,
) -> list[dict[str, Any]]:
    """Return ALL hotels from one area search (one credit), filtered by the
    per-night price ceiling. Each item:

        {
          "property_token": str,
          "hotel_name": str,
          "rating": float,
          "reviews": int,
          "price": float,        # per night (headline)
          "price_total": float,  # full stay
          "currency": str,
          "sites": [{source, price}],   # may be partial in list view
        }

    sort_by_rating=True biases results to the highest-rated hotels (good for
    the daily best-value scan). Set False for a name search so Google's
    relevance ranking surfaces the specific hotel you typed.
    """
    if not is_hotel_provider_configured():
        return []

    from serpapi_client import SerpApiError, serpapi_search

    params: dict[str, Any] = {
        "engine": "google_hotels",
        "q": query,
        "check_in_date": checkin,
        "check_out_date": checkout,
        "adults": adults,
        "currency": CURRENCY,
        "gl": "in",
        "hl": "en",
    }
    if sort_by_rating:
        params["sort_by"] = _SORT_HIGHEST_RATING

    try:
        data = serpapi_search(params)
    except SerpApiError as exc:
        print(f"  hotel search '{query}': {exc}")
        return []

    out: list[dict[str, Any]] = []
    for prop in data.get("properties") or []:
        per_night = _rate(prop, "rate_per_night")
        total = _rate(prop, "total_rate")
        headline = per_night if per_night is not None else total
        if headline is None:
            continue
        # Exact client-side filter on the nightly rate.
        if max_price_per_night and per_night is not None and per_night > max_price_per_night:
            continue
        token = prop.get("property_token") or prop.get("name", "")
        out.append(
            {
                "property_token": token,
                "hotel_name": prop.get("name", "Unknown"),
                "rating": float(prop.get("overall_rating") or 0),
                "reviews": int(prop.get("reviews") or 0),
                "price": round(headline, 2),
                "price_total": round(total, 2) if total is not None else None,
                "currency": CURRENCY,
                "sites": _extract_sites(prop),
            }
        )
        if len(out) >= limit:
            break
    return out


def select_best_value(
    candidates: list[dict[str, Any]],
    min_rating: float = DEFAULT_MIN_RATING,
    min_reviews: int = DEFAULT_MIN_REVIEWS,
) -> dict[str, Any] | None:
    """Cheapest hotel meeting the quality floors, relaxing if needed."""
    if not candidates:
        return None
    tiers = [
        [c for c in candidates if c["rating"] >= min_rating and c["reviews"] >= min_reviews],
        [c for c in candidates if c["rating"] >= min_rating],
        candidates,
    ]
    for pool in tiers:
        if pool:
            return min(pool, key=lambda c: c["price"])
    return None


# --------------------------- locked hotel (optional detail) --------------------------- #


def track_hotel(
    property_token: str,
    query: str,
    checkin: str,
    checkout: str,
    adults: int = 1,
) -> dict[str, Any] | None:
    """Price a SPECIFIC hotel by property_token, with full per-site breakdown.

    Used on demand (e.g. a UI "details" button) to get the complete
    MakeMyTrip/Agoda/Booking price list for one hotel. Costs one credit.
    """
    if not is_hotel_provider_configured():
        return None

    from serpapi_client import SerpApiError, serpapi_search

    params: dict[str, Any] = {
        "engine": "google_hotels",
        "q": query,
        "check_in_date": checkin,
        "check_out_date": checkout,
        "adults": adults,
        "currency": CURRENCY,
        "gl": "in",
        "hl": "en",
        "property_token": property_token,
    }
    try:
        data = serpapi_search(params)
    except SerpApiError as exc:
        print(f"  hotel detail ({property_token[:8]}...): {exc}")
        return None

    sites = _extract_sites(data)
    per_night = _rate(data, "rate_per_night")
    total = _rate(data, "total_rate")
    headline = per_night if per_night is not None else (sites[0]["price"] if sites else total)
    if headline is None:
        return None
    cheapest = sites[0] if sites else None
    return {
        "price": round(headline, 2),
        "price_total": round(total, 2) if total is not None else None,
        "currency": CURRENCY,
        "hotel_name": data.get("name", "Unknown"),
        "rating": float(data.get("overall_rating") or 0),
        "reviews": int(data.get("reviews") or 0),
        "sites": sites,
        "cheapest_site": cheapest["source"] if cheapest else "",
        "property_token": property_token,
    }
