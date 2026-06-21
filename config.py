"""Configuration helper.

Reads settings from environment variables (.env locally) with a fallback
to Streamlit secrets when running inside the Streamlit app process. This
mirrors the stock-bot pattern so load order never matters.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Safe to call repeatedly; only the first call has effect.
load_dotenv()


def _get(key: str, default: str = "") -> str:
    """Return a config value from env, falling back to Streamlit secrets."""
    val = os.getenv(key, "")
    if val:
        return val
    try:
        import streamlit as st  # type: ignore

        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return default


# --- Travelpayouts / Aviasales (flights, free) ---
TRAVELPAYOUTS_TOKEN = _get("TRAVELPAYOUTS_TOKEN", "")
# Optional affiliate marker (id). Harmless to leave blank.
TRAVELPAYOUTS_MARKER = _get("TRAVELPAYOUTS_MARKER", "")
# Data-source market for the price cache. Leave blank to use the API
# default. Set to a market code (e.g. "in") to bias toward India searches.
TRAVELPAYOUTS_MARKET = _get("TRAVELPAYOUTS_MARKET", "").strip().lower()

# --- SerpApi (hotels + optionally flights, paid; free 250/mo) ---
SERPAPI_KEY = _get("SERPAPI_KEY", "")

# Flight data source: "auto" (SerpApi if key present, else Travelpayouts),
# "serpapi", or "travelpayouts".
FLIGHT_PROVIDER = _get("FLIGHT_PROVIDER", "auto").strip().lower()

# --- Supabase ---
SUPABASE_URL = _get("SUPABASE_URL", "")
SUPABASE_KEY = _get("SUPABASE_KEY", "")

# --- Telegram ---
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID", "")

# --- Currency for all price queries/alerts ---
CURRENCY = _get("CURRENCY", "INR")

# --- Optional admin password (protects edit/credit actions on a public UI) ---
APP_ADMIN_PASSWORD = _get("APP_ADMIN_PASSWORD", "")


def is_travelpayouts_configured() -> bool:
    return bool(TRAVELPAYOUTS_TOKEN)


def is_serpapi_configured() -> bool:
    return bool(SERPAPI_KEY)


def active_flight_provider() -> str:
    """Resolve which flight data source to use given config + keys."""
    if FLIGHT_PROVIDER == "serpapi":
        return "serpapi"
    if FLIGHT_PROVIDER == "travelpayouts":
        return "travelpayouts"
    # auto: prefer SerpApi (reliable, date-specific) when a key exists.
    return "serpapi" if SERPAPI_KEY else "travelpayouts"
