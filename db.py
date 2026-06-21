"""Supabase client and connection management.

If SUPABASE_URL and SUPABASE_KEY are set (.env locally or Streamlit Cloud
secrets), the app uses Supabase for persistence (trip config, price
history, alert dedupe).

If they're not set, the app falls back to local JSON files so development
works without any cloud account. See trip.py and tracker.py for the
fallbacks.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from config import SUPABASE_KEY, SUPABASE_URL


def is_supabase_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


@lru_cache(maxsize=1)
def get_client() -> Any:
    """Return a cached Supabase client. Raises if not configured."""
    if not is_supabase_configured():
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY "
            "in your .env or Streamlit secrets."
        )
    from supabase import create_client

    return create_client(SUPABASE_URL, SUPABASE_KEY)
