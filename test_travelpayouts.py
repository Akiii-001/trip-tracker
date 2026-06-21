"""Quick sanity check for your Travelpayouts (flights) and SerpApi (hotels) keys.

Run:  python test_travelpayouts.py

It does NOT send Telegram messages or write anything. It just calls the
APIs for your actual trip and prints what comes back, so you can confirm
your token works and see whether the Kolkata->Port Blair cache has data.
"""

from __future__ import annotations

from config import (
    active_flight_provider,
    is_serpapi_configured,
    is_travelpayouts_configured,
)
from flights import search_cheapest_flight
from hotels import search_candidates, select_best_value
from trip import load_trip


def _money(v, cur="INR"):
    sym = "₹" if cur == "INR" else ""
    return f"{sym}{v:,.0f}"


def main() -> None:
    print("=" * 60)
    print("Trip-tracker key check")
    print("=" * 60)

    provider = active_flight_provider()
    print(f"Travelpayouts token:     {'OK' if is_travelpayouts_configured() else 'NOT SET'}")
    print(f"SerpApi key:             {'OK' if is_serpapi_configured() else 'not set'}")
    print(f"Active flight provider:  {provider}")
    print("-" * 60)

    trip = load_trip()
    travelers = int(trip.get("travelers", 1))

    # --- Flights --- #
    print(f"\n✈️  FLIGHTS via {provider}")
    for f in trip.get("flights", []):
        label = f.get("label", f"{f['origin']}→{f['destination']}")
        leg_travelers = int(f.get("travelers", travelers))
        res = search_cheapest_flight(
            origin=f["origin"],
            destination=f["destination"],
            depart_date=f["depart_date"],
            return_date=f.get("return_date"),
            adults=leg_travelers,
            non_stop=bool(f.get("non_stop", False)),
        )
        if not res:
            print(f"  • {label} ({leg_travelers}x): no fares found")
            continue
        stops = res["stops_out"]
        print(
            f"  • {label} ({leg_travelers}x): {_money(res['price'], res['currency'])} total "
            f"({_money(res['price_per_person'], res['currency'])}/pax) · "
            f"{res['airline']} · {'non-stop' if stops == 0 else str(stops) + ' stop(s)'} · "
            f"departs {res['depart_time']}"
        )

    # --- Hotels --- #
    if not is_serpapi_configured():
        print("\n🏨 HOTELS: skipped (no SERPAPI_KEY). Flights-only mode is fine.")
    else:
        print(f"\n🏨 HOTELS (track-all per island, for {travelers} guest(s))")
        for h in trip.get("hotels", []):
            cands = search_candidates(
                query=h["query"],
                checkin=h["checkin"],
                checkout=h["checkout"],
                adults=travelers,
                max_price_per_night=h.get("max_price"),
            )
            label = h.get("label", h["id"])
            if not cands:
                print(f"  • {label}: nothing found")
                continue
            best = select_best_value(
                cands,
                float(h.get("min_rating") or 0),
                int(h.get("min_reviews") or 0),
            )
            print(f"  • {label}: {len(cands)} hotels tracked (≤ ₹{h.get('max_price')}/night)")
            if best:
                site = f" · cheapest on {best['sites'][0]['source']}" if best.get("sites") else ""
                print(
                    f"      best value: {_money(best['price'])}/night "
                    f"— {best['hotel_name']} (★{best['rating']}, {best['reviews']} reviews){site}"
                )

    print("\nDone.")


if __name__ == "__main__":
    main()
