"""Core price-tracking logic.

For each enabled trip item (flight or hotel) this module:
  1. Fetches the current cheapest price (flights via SerpApi/Travelpayouts,
     hotels via SerpApi Google Hotels).
  2. Logs the price to history (Supabase `price_history` or local JSON).
  3. Decides whether to alert, based on:
        - target_hit : price <= user target  (alerts once per breach)
        - new_low    : price is the lowest ever seen for this item
        - big_drop   : price fell >= DROP_PCT vs the previous check
  4. Sends a Telegram alert and updates per-item state to avoid spam.

State (lowest price, last price, whether target already alerted) lives in
the `tracker_state` table when Supabase is configured, else local JSON.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from config import CURRENCY
from db import get_client, is_supabase_configured
from flights import search_cheapest_flight
from hotels import (
    is_hotel_provider_configured,
    search_candidates,
    select_best_value,
    track_hotel,
)
from notifier import is_telegram_configured, send_telegram
from trip import is_trip_active, list_trips, load_trip

# Alert when price drops at least this fraction vs the previous check.
DROP_PCT = 0.08  # 8%

_STATE_PATH = os.path.join(os.path.dirname(__file__), "tracker_state.json")
_HISTORY_PATH = os.path.join(os.path.dirname(__file__), "price_history.json")


# ----------------------------- storage ----------------------------- #


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_state() -> dict[str, Any]:
    if is_supabase_configured():
        try:
            client = get_client()
            res = client.table("tracker_state").select("*").execute()
            return {row["item_id"]: row for row in (res.data or [])}
        except Exception as exc:
            print(f"load state via Supabase failed: {exc}")
    if os.path.exists(_STATE_PATH):
        try:
            with open(_STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state_item(item_id: str, state: dict[str, Any], all_state: dict[str, Any]) -> None:
    all_state[item_id] = state
    if is_supabase_configured():
        try:
            client = get_client()
            client.table("tracker_state").upsert(
                {"item_id": item_id, **state}
            ).execute()
            return
        except Exception as exc:
            print(f"save state via Supabase failed: {exc}")
    try:
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(all_state, f, indent=2)
    except Exception as exc:
        print(f"save state local write failed: {exc}")


def _log_price(
    item_id: str,
    item_type: str,
    label: str,
    price: float,
    currency: str,
    source: str = "",
    meta: dict[str, Any] | None = None,
    trip: str = "",
) -> None:
    row = {
        "item_id": item_id,
        "item_type": item_type,
        "label": label,
        "price": price,
        "currency": currency,
        "source": source,
        "trip": trip,
        "checked_at": _now_iso(),
    }
    if meta:
        row.update(meta)
    if is_supabase_configured():
        try:
            client = get_client()
            client.table("price_history").insert(row).execute()
            return
        except Exception as exc:
            print(f"log price via Supabase failed: {exc}")
    # Local JSON append.
    history = []
    if os.path.exists(_HISTORY_PATH):
        try:
            with open(_HISTORY_PATH, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(row)
    try:
        with open(_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as exc:
        print(f"log price local write failed: {exc}")


# ----------------------------- alerts ----------------------------- #


def _fmt_money(amount: float, currency: str) -> str:
    sym = "₹" if currency == "INR" else ""
    return f"{sym}{amount:,.0f}"


def _evaluate_and_alert(
    item_id: str,
    item_type: str,
    label: str,
    price: float,
    currency: str,
    target: float | None,
    extra: str,
    all_state: dict[str, Any],
    source: str = "",
    trip: str = "",
    enrich=None,
) -> bool:
    """Decide whether to alert for one item and send it. Returns True if sent.

    `enrich` is an optional zero-arg callable returning a string; it is called
    ONLY when an alert actually fires (so a credit-costing detail lookup runs
    just for genuine alerts, not every check).
    """
    prev = all_state.get(item_id, {})
    prev_low = prev.get("lowest_price")
    prev_last = prev.get("last_price")
    target_alerted = bool(prev.get("target_alerted", False))

    _log_price(item_id, item_type, label, price, currency, source, trip=trip)

    reasons: list[str] = []

    # 1. Target hit (only once per breach; reset when price rises above target).
    if target is not None:
        if price <= target and not target_alerted:
            reasons.append(f"🎯 Hit your target of {_fmt_money(target, currency)}")
            target_alerted = True
        elif price > target:
            target_alerted = False  # re-arm for next time it drops

    # 2. New all-time low.
    is_new_low = prev_low is not None and price < prev_low
    if is_new_low:
        reasons.append(
            f"📉 New lowest price (was {_fmt_money(prev_low, currency)})"
        )

    # 3. Big drop since last check.
    if prev_last is not None and prev_last > 0:
        drop = (prev_last - price) / prev_last
        if drop >= DROP_PCT:
            reasons.append(
                f"⬇️ Dropped {drop * 100:.0f}% since last check "
                f"({_fmt_money(prev_last, currency)} → {_fmt_money(price, currency)})"
            )

    new_low = min(price, prev_low) if prev_low is not None else price

    # Persist updated state.
    _save_state_item(
        item_id,
        {
            "lowest_price": new_low,
            "last_price": price,
            "target_alerted": target_alerted,
            "updated_at": _now_iso(),
        },
        all_state,
    )

    if not reasons:
        return False

    # Only now (alert is firing) run the optional enrichment (may cost a credit).
    enrich_txt = ""
    if enrich is not None:
        try:
            enrich_txt = enrich() or ""
        except Exception as exc:
            print(f"  enrich failed for {item_id}: {exc}")

    icon = "✈️" if item_type == "flight" else "🏨"
    body = "\n".join(f"• {r}" for r in reasons)
    msg = (
        f"{icon} *{label}*\n"
        f"Current: *{_fmt_money(price, currency)}*"
        f"{('  ·  ' + extra) if extra else ''}\n"
        f"{body}"
        f"{(chr(10) + enrich_txt) if enrich_txt else ''}"
    )
    if is_telegram_configured():
        return send_telegram(msg)
    print("ALERT (telegram not configured):\n" + msg)
    return False


# ----------------------------- main entry ----------------------------- #


def run_check(trip_key: str | None = None) -> dict[str, Any]:
    """Run one full check for a single trip. Skips trips that have started.

    Returns a small summary dict (counts + any errors) for logging / health.
    """
    from trip import list_trips as _lt

    if trip_key is None:
        trips = _lt()
        trip_key = trips[0]["key"] if trips else "andaman"

    trip = load_trip(trip_key)
    if not is_trip_active(trip):
        summary = {
            "checked": 0, "alerts": 0,
            "errors": [f"trip '{trip_key}' has started/passed; tracking stopped"],
            "ran_at": _now_iso(), "trip": trip_key,
        }
        print(f"Check skipped: {summary}")
        return summary

    travelers = int(trip.get("travelers", 1))
    all_state = _load_state()

    checked = 0
    alerts = 0
    errors: list[str] = []

    # --- Flights --- #
    for f in trip.get("flights", []):
        if not f.get("enabled", True):
            continue
        leg_travelers = int(f.get("travelers", travelers))
        try:
            res = search_cheapest_flight(
                origin=f["origin"],
                destination=f["destination"],
                depart_date=f["depart_date"],
                return_date=f.get("return_date"),
                adults=leg_travelers,
                non_stop=bool(f.get("non_stop", False)),
            )
            checked += 1
            if not res:
                errors.append(f"flight {f['id']}: no offers found")
                continue
            stops = res["stops_out"]
            extra = (
                f"{res['airline']} · "
                f"{'non-stop' if stops == 0 else str(stops) + ' stop(s)'} · "
                f"{leg_travelers}x (₹{res['price_per_person']:,.0f}/pax)"
            )
            if _evaluate_and_alert(
                item_id=f"{trip_key}:flight:{f['id']}",
                item_type="flight",
                label=f.get("label", f"{f['origin']}→{f['destination']}"),
                price=res["price"],
                currency=res["currency"],
                target=f.get("target"),
                extra=extra,
                all_state=all_state,
                trip=trip_key,
                enrich=(lambda link=res.get("link", ""): f"🔗 {link}" if link else ""),
            ):
                alerts += 1
        except Exception as exc:
            errors.append(f"flight {f.get('id')}: {exc}")

    # --- Hotels (only if a provider like SerpApi is configured) --- #
    if not is_hotel_provider_configured():
        if any(h.get("enabled", True) for h in trip.get("hotels", [])):
            errors.append(
                "hotels skipped: no hotel provider configured (set SERPAPI_KEY "
                "to enable hotel tracking)"
            )
    else:
        for h in trip.get("hotels", []):
            if not h.get("enabled", True):
                continue
            try:
                # One search per island returns ~20 hotels for 1 credit.
                cands = search_candidates(
                    query=h["query"],
                    checkin=h["checkin"],
                    checkout=h["checkout"],
                    adults=travelers,
                    max_price_per_night=h.get("max_price"),
                )
                checked += 1
                if not cands:
                    errors.append(f"hotel {h['id']}: no hotels found")
                    continue

                # Track-all: log EVERY hotel returned (builds the roster +
                # per-hotel history) without sending individual alerts.
                island = h.get("label", h["id"])
                for c in cands:
                    cheapest_site = c["sites"][0]["source"] if c.get("sites") else ""
                    _log_price(
                        item_id=f"{trip_key}:hotel:{h['id']}:{c['property_token']}",
                        item_type="hotel",
                        label=c["hotel_name"],
                        price=c["price"],
                        currency=c["currency"],
                        source=cheapest_site,
                        meta={
                            "island": island,
                            "rating": c["rating"],
                            "reviews": c["reviews"],
                            "total_price": c.get("price_total"),
                        },
                        trip=trip_key,
                    )

                # Alert only on the island's BEST-VALUE hotel (one series per
                # island) so we don't ping for all ~20 hotels.
                best = select_best_value(
                    cands,
                    min_rating=float(h.get("min_rating") or 0),
                    min_reviews=int(h.get("min_reviews") or 0),
                )
                if best:
                    extra = (
                        f"{best['hotel_name']} (★{best['rating']}, "
                        f"{best['reviews']} reviews) · {len(cands)} hotels tracked"
                    )

                    def _hotel_enrich(_b=best, _h=h, _tr=travelers):
                        """On alert only: 1 detail call to name the cheapest site."""
                        det = track_hotel(
                            _b.get("property_token", ""), _h["query"],
                            _h["checkin"], _h["checkout"], _tr,
                        )
                        if det and det.get("sites"):
                            s = det["sites"][0]
                            line = f"🏷️ Cheapest on {s['source']} ₹{s['price']:,.0f}/night"
                            if s.get("link"):
                                line += f"\n🔗 {s['link']}"
                            return line
                        return ""

                    if _evaluate_and_alert(
                        item_id=f"{trip_key}:hotel:{h['id']}",
                        item_type="hotel",
                        label=f"{island} (best value)",
                        price=best["price"],
                        currency=best["currency"],
                        target=h.get("target"),
                        extra=extra,
                        all_state=all_state,
                        source=best["sites"][0]["source"] if best.get("sites") else "",
                        trip=trip_key,
                        enrich=_hotel_enrich,
                    ):
                        alerts += 1
            except Exception as exc:
                errors.append(f"hotel {h.get('id')}: {exc}")

    summary = {
        "checked": checked,
        "alerts": alerts,
        "errors": errors,
        "ran_at": _now_iso(),
        "trip": trip_key,
    }
    print(f"Check complete: {summary}")
    return summary


def run_all() -> dict[str, Any]:
    """Run a check for every active (not-yet-started) trip. Used by the worker."""
    totals = {"checked": 0, "alerts": 0, "trips": 0, "errors": []}
    for t in list_trips():
        cfg = load_trip(t["key"])
        if not is_trip_active(cfg):
            continue
        s = run_check(t["key"])
        totals["checked"] += s.get("checked", 0)
        totals["alerts"] += s.get("alerts", 0)
        totals["trips"] += 1
        totals["errors"].extend(s.get("errors", []))
    totals["ran_at"] = _now_iso()
    print(f"run_all complete: {totals}")
    return totals


if __name__ == "__main__":
    run_all()


def load_history(limit: int = 5000, trip: str | None = None) -> list[dict[str, Any]]:
    """Return logged price history rows (newest first), optionally one trip."""
    if is_supabase_configured():
        try:
            client = get_client()
            q = client.table("price_history").select("*")
            if trip:
                q = q.eq("trip", trip)
            res = q.order("checked_at", desc=True).limit(limit).execute()
            return res.data or []
        except Exception as exc:
            print(f"load_history via Supabase failed: {exc}")
    if os.path.exists(_HISTORY_PATH):
        try:
            with open(_HISTORY_PATH, encoding="utf-8") as f:
                rows = json.load(f)
            if trip:
                rows = [r for r in rows if r.get("trip") == trip]
            return sorted(rows, key=lambda r: r.get("checked_at", ""), reverse=True)[:limit]
        except Exception:
            pass
    return []
