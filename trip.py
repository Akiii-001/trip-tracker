"""Trip configuration: multi-trip storage, load / save / defaults.

Supports MANY trips (Andaman now, anything later). Each trip has a short
key (slug) and a human name, plus its flights and hotels.

Persistence:
  - Supabase: one row per trip in `trip_config` (key + config jsonb).
  - Local fallback: a single trips.json file: {key: config, ...}.

A trip "config" looks like:
    {
      "name": "Andaman Trip",
      "travelers": 2,
      "currency": "INR",
      "flights": [...],
      "hotels": [...],
    }
"""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import date
from typing import Any

from db import get_client, is_supabase_configured

_LOCAL_PATH = os.path.join(os.path.dirname(__file__), "trips.json")

# Suggested Google Hotels search queries per Andaman island.
ISLAND_QUERIES = {
    "Havelock (Swaraj Dweep)": "Hotels in Havelock Island Andaman",
    "Neil (Shaheed Dweep)": "Hotels in Neil Island Andaman",
    "Port Blair": "Hotels in Port Blair Andaman",
}

# The starter Andaman trip (seeded on first run).
DEFAULT_KEY = "andaman"
DEFAULT_TRIP: dict[str, Any] = {
    "name": "Andaman Trip",
    "travelers": 2,
    "currency": "INR",
    "flights": [
        {"id": "out", "label": "Kolkata → Port Blair", "origin": "CCU",
         "destination": "IXZ", "depart_date": "2026-09-28", "return_date": None,
         "non_stop": False, "travelers": 2, "target": None, "enabled": True},
        {"id": "ret", "label": "Port Blair → Kolkata", "origin": "IXZ",
         "destination": "CCU", "depart_date": "2026-10-03", "return_date": None,
         "non_stop": False, "travelers": 1, "target": None, "enabled": True},
        {"id": "ret_hyd", "label": "Port Blair → Hyderabad", "origin": "IXZ",
         "destination": "HYD", "depart_date": "2026-10-03", "return_date": None,
         "non_stop": False, "travelers": 1, "target": None, "enabled": True},
    ],
    "hotels": [
        {"id": "havelock", "label": "Havelock (Swaraj Dweep)",
         "query": "Hotels in Havelock Island Andaman", "checkin": "2026-09-28",
         "checkout": "2026-10-01", "min_rating": 4.0, "min_reviews": 50,
         "max_price": 9000, "target": None, "enabled": True},
        {"id": "neil", "label": "Neil (Shaheed Dweep)",
         "query": "Hotels in Neil Island Andaman", "checkin": "2026-10-01",
         "checkout": "2026-10-02", "min_rating": 4.0, "min_reviews": 50,
         "max_price": 9000, "target": None, "enabled": True},
        {"id": "portblair", "label": "Port Blair",
         "query": "Hotels in Port Blair Andaman", "checkin": "2026-10-02",
         "checkout": "2026-10-03", "min_rating": 4.0, "min_reviews": 100,
         "max_price": 9000, "target": None, "enabled": True},
    ],
}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "trip"


# --------------------------- storage --------------------------- #


def _load_all() -> dict[str, dict[str, Any]]:
    """Return all trips {key: config}, seeding the default on first run."""
    if is_supabase_configured():
        try:
            client = get_client()
            res = client.table("trip_config").select("key, config").execute()
            trips = {r["key"]: r["config"] for r in (res.data or [])}
            if not trips:
                save_trip(DEFAULT_KEY, copy.deepcopy(DEFAULT_TRIP))
                trips = {DEFAULT_KEY: copy.deepcopy(DEFAULT_TRIP)}
            return trips
        except Exception as exc:
            print(f"_load_all via Supabase failed ({exc}); using local.")

    if os.path.exists(_LOCAL_PATH):
        try:
            with open(_LOCAL_PATH, encoding="utf-8") as f:
                trips = json.load(f)
            if trips:
                return trips
        except Exception as exc:
            print(f"_load_all local read failed ({exc}); using default.")
    trips = {DEFAULT_KEY: copy.deepcopy(DEFAULT_TRIP)}
    _save_all_local(trips)
    return trips


def _save_all_local(trips: dict[str, dict[str, Any]]) -> None:
    try:
        with open(_LOCAL_PATH, "w", encoding="utf-8") as f:
            json.dump(trips, f, indent=2)
    except Exception as exc:
        print(f"trips local write failed: {exc}")


# --------------------------- public API --------------------------- #


def list_trips() -> list[dict[str, str]]:
    """Return [{"key", "name"}] for all trips."""
    trips = _load_all()
    return [{"key": k, "name": v.get("name", k)} for k, v in trips.items()]


def load_trip(key: str | None = None) -> dict[str, Any]:
    """Load one trip. If key is None, returns the first available trip."""
    trips = _load_all()
    if key and key in trips:
        return trips[key]
    # Fall back to the first trip.
    first_key = next(iter(trips))
    return trips[first_key]


def save_trip(key: str, config: dict[str, Any]) -> None:
    """Persist one trip to Supabase (if configured) and local mirror."""
    if is_supabase_configured():
        try:
            client = get_client()
            client.table("trip_config").upsert(
                {"key": key, "config": config}
            ).execute()
        except Exception as exc:
            print(f"save_trip via Supabase failed: {exc}")
    trips = _load_all()
    trips[key] = config
    _save_all_local(trips)


def create_trip(name: str) -> str:
    """Create a new empty trip; returns its key."""
    trips = _load_all()
    base = _slug(name)
    key = base
    i = 2
    while key in trips:
        key = f"{base}-{i}"
        i += 1
    config = {
        "name": name.strip() or "New Trip",
        "travelers": 2,
        "currency": "INR",
        "flights": [],
        "hotels": [],
    }
    save_trip(key, config)
    return key


def delete_trip(key: str) -> None:
    """Delete a trip (keeps at least one — recreates default if last)."""
    if is_supabase_configured():
        try:
            client = get_client()
            client.table("trip_config").delete().eq("key", key).execute()
        except Exception as exc:
            print(f"delete_trip via Supabase failed: {exc}")
    trips = _load_all()
    trips.pop(key, None)
    if not trips:
        trips[DEFAULT_KEY] = copy.deepcopy(DEFAULT_TRIP)
    _save_all_local(trips)


# --------------------------- dates / activity --------------------------- #


def trip_start_date(config: dict[str, Any]) -> date | None:
    """Earliest flight departure (or hotel check-in) date for the trip."""
    dates: list[date] = []
    for f in config.get("flights", []):
        d = f.get("depart_date")
        if d:
            try:
                dates.append(date.fromisoformat(str(d)))
            except ValueError:
                pass
    for h in config.get("hotels", []):
        d = h.get("checkin")
        if d:
            try:
                dates.append(date.fromisoformat(str(d)))
            except ValueError:
                pass
    return min(dates) if dates else None


def is_trip_active(config: dict[str, Any]) -> bool:
    """True if the trip hasn't started yet (so tracking still makes sense).

    Tracking stops ON the start date — once today >= start, there's no point
    checking prices for a trip that has begun.
    """
    start = trip_start_date(config)
    if start is None:
        return True  # no dates set yet; allow tracking
    return date.today() < start
