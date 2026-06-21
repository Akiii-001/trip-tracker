"""Flight price lookups, with a selectable data source.

Two providers:

  - "serpapi"       : live Google Flights via SerpApi. Reliable and
                      date-specific (works for thin routes like CCU->IXZ).
                      Counts against the SerpApi quota.
  - "travelpayouts" : free Aviasales Data API (cached fares). Great for
                      busy routes, but the cache often has NO data for
                      thin routes / specific future dates (proven for
                      Kolkata->Port Blair), so it's the fallback.

config.active_flight_provider() decides which is used.

Both return the same result shape so the rest of the app is agnostic:
    {
      "price": float,            # total for all travelers, in CURRENCY
      "price_per_person": float,
      "currency": str,
      "airline": str,
      "stops_out": int,
      "depart_time": str,
      "link": str,
      "provider": str,
      "raw": {...}
    }
"""

from __future__ import annotations

from typing import Any

from config import CURRENCY, TRAVELPAYOUTS_MARKET, active_flight_provider


def search_cheapest_flight(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str | None = None,
    adults: int = 1,
    non_stop: bool = False,
    max_offers: int = 30,
) -> dict[str, Any] | None:
    """Return the cheapest flight via the active provider, or None."""
    provider = active_flight_provider()
    if provider == "serpapi":
        return _serpapi_flight(
            origin, destination, depart_date, return_date, adults, non_stop
        )
    return _travelpayouts_flight(
        origin, destination, depart_date, return_date, adults, non_stop, max_offers
    )


# ----------------------------- SerpApi ----------------------------- #


def _serpapi_flight(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str | None,
    adults: int,
    non_stop: bool,
) -> dict[str, Any] | None:
    from serpapi_client import SerpApiError, serpapi_search

    params: dict[str, Any] = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": depart_date,
        "currency": CURRENCY,
        "hl": "en",
        "gl": "in",
        "adults": adults,
        # 1 = round trip, 2 = one way.
        "type": 1 if return_date else 2,
    }
    if return_date:
        params["return_date"] = return_date
    if non_stop:
        params["stops"] = 1  # SerpApi: 1 = nonstop only

    try:
        data = serpapi_search(params)
    except SerpApiError as exc:
        print(f"  flight (serpapi) {origin}->{destination} {depart_date}: {exc}")
        return None

    offers = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    if not offers:
        return None

    def _price(o: dict) -> float:
        try:
            return float(o.get("price", float("inf")))
        except (ValueError, TypeError):
            return float("inf")

    cheapest = min(offers, key=_price)
    total = _price(cheapest)
    if total == float("inf"):
        return None

    segments = cheapest.get("flights") or []
    stops_out = max(0, len(segments) - 1)
    airline = segments[0].get("airline", "") if segments else ""
    depart_time = (
        segments[0].get("departure_airport", {}).get("time", "") if segments else ""
    )

    # SerpApi/Google price reflects the searched passenger count (total).
    per_person = round(total / max(1, adults), 2)

    return {
        "price": round(total, 2),
        "price_per_person": per_person,
        "currency": CURRENCY,
        "airline": airline,
        "stops_out": stops_out,
        "depart_time": depart_time,
        "link": data.get("search_metadata", {}).get("google_flights_url", ""),
        "provider": "serpapi",
        "raw": cheapest,
    }


# -------------------------- Travelpayouts -------------------------- #


def _travelpayouts_flight(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str | None,
    adults: int,
    non_stop: bool,
    max_offers: int,
) -> dict[str, Any] | None:
    from travelpayouts_client import TravelpayoutsError, tp_get

    params: dict[str, Any] = {
        "origin": origin,
        "destination": destination,
        "departure_at": depart_date,
        "currency": CURRENCY.lower(),
        "sorting": "price",
        "direct": "true" if non_stop else "false",
        "limit": max_offers,
        "page": 1,
    }
    if return_date:
        params["return_at"] = return_date
        params["one_way"] = "false"
    else:
        params["one_way"] = "true"
    if TRAVELPAYOUTS_MARKET:
        params["market"] = TRAVELPAYOUTS_MARKET

    try:
        data = tp_get("/aviasales/v3/prices_for_dates", params)
    except TravelpayoutsError as exc:
        print(f"  flight (tp) {origin}->{destination} {depart_date}: {exc}")
        return None

    if not data.get("success", False):
        print(f"  flight (tp) {origin}->{destination}: API error {data.get('error')}")
        return None

    offers = data.get("data") or []
    if not offers:
        return None

    def _price(o: dict) -> float:
        try:
            return float(o.get("price", float("inf")))
        except (ValueError, TypeError):
            return float("inf")

    cheapest = min(offers, key=_price)
    per_person = _price(cheapest)
    if per_person == float("inf"):
        return None

    total = round(per_person * max(1, adults), 2)
    link = cheapest.get("link", "")
    full_link = f"https://www.aviasales.com{link}" if link else ""

    return {
        "price": total,
        "price_per_person": round(per_person, 2),
        "currency": (cheapest.get("currency") or CURRENCY).upper(),
        "airline": cheapest.get("airline", ""),
        "stops_out": int(cheapest.get("transfers", 0) or 0),
        "depart_time": cheapest.get("departure_at", ""),
        "link": full_link,
        "provider": "travelpayouts",
        "raw": cheapest,
    }
