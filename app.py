"""Streamlit UI for the multi-trip price tracker.

- Manage multiple trips (create / select / delete).
- Edit each trip's flights & hotels, run on-demand checks.
- See a snapshot dashboard, an itinerary timeline, and price charts +
  a per-island hotel roster.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from config import (
    APP_ADMIN_PASSWORD,
    CURRENCY,
    is_serpapi_configured,
    is_travelpayouts_configured,
)
from db import is_supabase_configured
from notifier import is_telegram_configured
from trip import (
    create_trip,
    delete_trip,
    is_trip_active,
    list_trips,
    load_trip,
    save_trip,
    trip_start_date,
)

st.set_page_config(page_title="Trip Price Tracker", page_icon="🏝️", layout="wide")

# ------------------------- styling ------------------------- #

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.4rem; max-width: 1200px; }
      .hero {
        background: linear-gradient(135deg, #0EA5A4 0%, #22D3EE 55%, #38BDF8 100%);
        border-radius: 18px; padding: 26px 32px; color: #fff;
        box-shadow: 0 10px 30px rgba(14,165,164,0.25); margin-bottom: 18px;
      }
      .hero-title { font-size: 2.0rem; font-weight: 800; letter-spacing:-0.5px; margin:0; }
      .hero-sub { font-size: 1.0rem; opacity: 0.95; margin-top: 6px; }
      .hero-badges { margin-top: 14px; }
      .hero-badge {
        display:inline-block; background: rgba(255,255,255,0.20);
        border:1px solid rgba(255,255,255,0.35); padding:6px 14px;
        border-radius:999px; font-size:0.9rem; font-weight:600; margin-right:8px;
      }
      [data-testid="stMetric"] {
        background:#fff; border:1px solid #d7ecec; border-radius:14px;
        padding:14px 16px; box-shadow:0 2px 8px rgba(15,46,46,0.05);
      }
      [data-testid="stMetricValue"] { font-size: 1.5rem; }
      [data-testid="stMetricLabel"] { font-size: 0.9rem; }
      .stButton > button { border-radius:12px; font-weight:600; padding:0.5rem 1rem; }
      [data-testid="stExpander"] { border:1px solid #d7ecec; border-radius:14px; overflow:hidden; }
      .timeline { display:flex; gap:12px; flex-wrap:wrap; margin: 6px 0 4px; }
      .stop {
        flex:1; min-width:170px; background:#fff; border:1px solid #d7ecec;
        border-radius:14px; padding:14px 16px; box-shadow:0 2px 8px rgba(15,46,46,0.05);
      }
      .stop-step { font-size:0.78rem; font-weight:700; color:#0EA5A4; letter-spacing:0.5px; }
      .stop-name { font-size:1.05rem; font-weight:700; margin:2px 0; }
      .stop-dates { font-size:0.85rem; color:#5b6b6b; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------- sidebar: status + trips ------------------------- #

trips = list_trips()
trip_names = {t["name"]: t["key"] for t in trips}

with st.sidebar:
    st.header("🧳 Trips")
    names = list(trip_names.keys())
    if "trip_key" not in st.session_state and trips:
        st.session_state["trip_key"] = trips[0]["key"]

    current_key = st.session_state.get("trip_key", trips[0]["key"] if trips else "")
    current_name = next((n for n, k in trip_names.items() if k == current_key), names[0] if names else "")
    chosen_name = st.selectbox("Active trip", names, index=names.index(current_name) if current_name in names else 0)
    st.session_state["trip_key"] = trip_names[chosen_name]
    trip_key = st.session_state["trip_key"]

    # Admin gate: if a password is configured, editing/credit actions require
    # it. Viewing (charts, roster, itinerary) is always open. No password set
    # (e.g. local dev) => full access.
    if APP_ADMIN_PASSWORD:
        pw = st.text_input("🔑 Admin password", type="password", help="Required to edit or run checks")
        admin = pw == APP_ADMIN_PASSWORD
        if pw and not admin:
            st.error("Wrong password — view-only mode.")
        elif not admin:
            st.caption("👀 View-only. Enter password to edit / run checks.")
    else:
        admin = True

    if admin:
        with st.expander("➕ New trip"):
            new_name = st.text_input("Trip name", key="new_trip_name", placeholder="e.g. Goa Dec 2026")
            if st.button("Create trip", use_container_width=True):
                if new_name.strip():
                    k = create_trip(new_name.strip())
                    st.session_state["trip_key"] = k
                    st.rerun()
                else:
                    st.warning("Enter a name first.")

        with st.expander("🗑️ Delete this trip"):
            st.caption(f"Delete '{chosen_name}'? This can't be undone.")
            if st.button("Delete", use_container_width=True):
                delete_trip(trip_key)
                st.session_state.pop("trip_key", None)
                st.rerun()

    st.divider()
    st.header("Status")
    st.write("Flights:", "✅" if is_travelpayouts_configured() or is_serpapi_configured() else "❌")
    st.write("Hotels (SerpApi):", "✅" if is_serpapi_configured() else "⚪ off")
    st.write("Supabase:", "✅" if is_supabase_configured() else "⚠️ local JSON")
    st.write("Telegram:", "✅" if is_telegram_configured() else "❌ not set")
    if admin and st.button("🔔 Send test alert", use_container_width=True):
        from notifier import is_telegram_configured as _tg, send_telegram

        if _tg() and send_telegram("✅ *Trip-tracker* test alert — Telegram is working!"):
            st.success("Sent! Check Telegram.")
        else:
            st.error("Not configured or failed. Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID.")

trip = load_trip(trip_key)

# ------------------------- hero ------------------------- #

_start = trip_start_date(trip)
_days_txt = ""
if _start:
    delta = (_start - date.today()).days
    if delta > 0:
        _days_txt = f"<span class='hero-badge'>⏳ {delta} days to go</span>"
    elif delta == 0:
        _days_txt = "<span class='hero-badge'>🎉 starts today!</span>"
    else:
        _days_txt = "<span class='hero-badge'>✅ trip over — tracking stopped</span>"

_route = " → ".join(
    [h.get("label", "").split(" (")[0] for h in trip.get("hotels", []) if h.get("label")]
)
_flights = trip.get("flights", [])
_air = ""
if _flights:
    _air = f"✈️ {_flights[0].get('origin','')} ↔ {_flights[0].get('destination','')}"

st.markdown(
    f"""
    <div class="hero">
      <div class="hero-title">🏝️ {trip.get('name', 'Trip')}</div>
      <div class="hero-sub">🌴 {_route or 'Add your stops below'} &nbsp; {_air}</div>
      <div class="hero-badges">
        {_days_txt}
        <span class='hero-badge'>👫 {trip.get('travelers', 1)} travelers</span>
        <span class='hero-badge'>🔔 price-drop alerts</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ------------------------- snapshot dashboard ------------------------- #

hist_rows = []
try:
    from tracker import load_history

    hist_rows = load_history(trip=trip_key)
except Exception:
    hist_rows = []

hist = pd.DataFrame(hist_rows)
if not hist.empty:
    # Stored timestamps are UTC; convert to IST for all display/charts.
    hist["checked_at"] = (
        pd.to_datetime(hist["checked_at"], errors="coerce", utc=True)
        .dt.tz_convert("Asia/Kolkata")
        .dt.tz_localize(None)
    )
    if "item_type" not in hist.columns:
        hist["item_type"] = "flight"


def _latest_per_item(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values("checked_at").groupby("item_id").tail(1)


c1, c2, c3, c4 = st.columns(4)
days_val = f"{(_start - date.today()).days}" if _start and (_start - date.today()).days >= 0 else "—"
c1.metric("⏳ Days to go", days_val)

if not hist.empty:
    fl = hist[hist["item_type"] == "flight"]
    flights_total = _latest_per_item(fl)["price"].sum() if not fl.empty else None
    c2.metric("✈️ Flights (latest sum)", f"₹{flights_total:,.0f}" if flights_total else "—")

    # Est. stay total = sum over islands of (best-value ₹/night × nights).
    ho = hist[hist["item_type"] == "hotel"].copy()
    best = ho[ho["label"].astype(str).str.endswith("(best value)")] if not ho.empty else ho
    est_total = 0.0
    have_stay = False
    if not best.empty:
        best_latest = _latest_per_item(best)
        for h in trip.get("hotels", []):
            island = h.get("label", "")
            try:
                nights = max(1, (date.fromisoformat(str(h["checkout"])) - date.fromisoformat(str(h["checkin"]))).days)
            except Exception:
                nights = 1
            match = best_latest[best_latest["label"].astype(str).str.startswith(island)]
            if not match.empty:
                est_total += float(match.iloc[0]["price"]) * nights
                have_stay = True
    c3.metric("🏨 Est. stay total", f"₹{est_total:,.0f}" if have_stay else "—")

    last_dt = hist["checked_at"].max()
    c4.metric("🕒 Last checked (IST)", last_dt.strftime("%d %b %H:%M") if pd.notnull(last_dt) else "—")
else:
    c2.metric("✈️ Flights (latest sum)", "—")
    c3.metric("🏨 Est. stay total", "—")
    c4.metric("🕒 Last checked", "—")

# ------------------------- tabs ------------------------- #

tab_plan, tab_prices, tab_expenses = st.tabs(["✏️  Plan", "📈  Prices", "💰  Expenses"])


def _clean_records(df: pd.DataFrame) -> list[dict]:
    records = df.where(pd.notnull(df), None).to_dict("records")
    return [r for r in records if any(v not in (None, "") for v in r.values())]


# ============================== PLAN TAB ============================== #
with tab_plan:
    if not is_trip_active(trip):
        st.warning("This trip has started or passed — automatic tracking is stopped.")

    # Itinerary timeline (from hotels).
    if trip.get("hotels"):
        st.markdown("#### 🗺️ Itinerary")
        cards = ""
        for i, h in enumerate(trip["hotels"], 1):
            cards += (
                f"<div class='stop'><div class='stop-step'>STOP {i}</div>"
                f"<div class='stop-name'>{h.get('label','')}</div>"
                f"<div class='stop-dates'>🛏️ {h.get('checkin','?')} → {h.get('checkout','?')}</div></div>"
            )
        st.markdown(f"<div class='timeline'>{cards}</div>", unsafe_allow_html=True)

    st.markdown("#### ⚙️ Trip basics")
    col1, col2 = st.columns(2)
    with col1:
        travelers = st.number_input(
            "Default travelers", min_value=1, max_value=9,
            value=int(trip.get("travelers", 2)), key=f"trav_{trip_key}",
        )
    with col2:
        currency = st.text_input("Currency", value=trip.get("currency", CURRENCY), key=f"cur_{trip_key}")

    st.markdown("#### ✈️ Flights")
    st.caption("One row per one-way search. Travelers is per leg.")
    flights_df = pd.DataFrame(trip.get("flights", []))
    if flights_df.empty:
        flights_df = pd.DataFrame(columns=[
            "id", "label", "origin", "destination", "depart_date",
            "return_date", "non_stop", "travelers", "target", "enabled",
        ])
    flights_edited = st.data_editor(
        flights_df, num_rows="dynamic", use_container_width=True, key=f"flights_{trip_key}",
        column_config={
            "id": st.column_config.TextColumn("ID"),
            "label": st.column_config.TextColumn("Label"),
            "origin": st.column_config.TextColumn("From"),
            "destination": st.column_config.TextColumn("To"),
            "depart_date": st.column_config.TextColumn("Depart"),
            "return_date": st.column_config.TextColumn("Return (opt)"),
            "non_stop": st.column_config.CheckboxColumn("Non-stop"),
            "travelers": st.column_config.NumberColumn("Pax", min_value=1, max_value=9),
            "target": st.column_config.NumberColumn("Target ₹"),
            "enabled": st.column_config.CheckboxColumn("Track"),
        },
    )

    st.markdown("#### 🏨 Hotels")
    st.caption(
        "One search per island per run tracks **all** returned hotels (≤ Max ₹/night). "
        "Alerts fire on the best-value hotel (cheapest meeting Min rating + Min reviews)."
    )
    hotels_df = pd.DataFrame(trip.get("hotels", []))
    if hotels_df.empty:
        hotels_df = pd.DataFrame(columns=[
            "id", "label", "query", "checkin", "checkout",
            "min_rating", "min_reviews", "max_price", "target", "enabled",
        ])
    hotels_edited = st.data_editor(
        hotels_df, num_rows="dynamic", use_container_width=True, key=f"hotels_{trip_key}",
        column_config={
            "id": st.column_config.TextColumn("ID"),
            "label": st.column_config.TextColumn("Island / area"),
            "query": st.column_config.TextColumn("Google Hotels query", width="medium"),
            "checkin": st.column_config.TextColumn("Check-in"),
            "checkout": st.column_config.TextColumn("Check-out"),
            "min_rating": st.column_config.NumberColumn("Min ★", min_value=0.0, max_value=5.0, step=0.1),
            "min_reviews": st.column_config.NumberColumn("Min reviews", min_value=0),
            "max_price": st.column_config.NumberColumn("Max ₹/night", min_value=0),
            "target": st.column_config.NumberColumn("Target ₹/night", min_value=0),
            "enabled": st.column_config.CheckboxColumn("Track"),
        },
    )

    if not admin:
        st.info("👀 View-only — enter the admin password in the sidebar to edit or run checks.")
    col_save, col_check = st.columns(2)
    with col_save:
        if admin and st.button("💾 Save trip", use_container_width=True, type="primary"):
            new_cfg = {
                "name": trip.get("name", chosen_name),
                "travelers": int(travelers),
                "currency": currency.strip() or CURRENCY,
                "flights": _clean_records(flights_edited),
                "hotels": _clean_records(hotels_edited),
                "expenses": trip.get("expenses"),  # preserve expenses
                "watchlist": trip.get("watchlist"),  # preserve watchlist
            }
            save_trip(trip_key, new_cfg)
            st.success("Saved.")
            st.rerun()

    with col_check:
        if admin and st.button("🔍 Check prices now", use_container_width=True):
            if not (is_travelpayouts_configured() or is_serpapi_configured()):
                st.error("No provider configured. Set SERPAPI_KEY (recommended) or TRAVELPAYOUTS_TOKEN.")
            else:
                with st.spinner("Querying prices..."):
                    from tracker import run_check

                    summary = run_check(trip_key)
                st.success(f"Checked {summary['checked']} item(s), {summary['alerts']} alert(s).")
                if summary.get("errors"):
                    with st.expander("Warnings / items with no results"):
                        for e in summary["errors"]:
                            st.write("•", e)
                st.rerun()


# ============================== PRICES TAB ============================== #
with tab_prices:
    if hist.empty:
        st.info("No price history yet for this trip. Go to **Plan → Check prices now** to start collecting data.")
    else:
        # ---- Flights ---- #
        fl = hist[hist["item_type"] == "flight"]
        if not fl.empty:
            st.markdown("### ✈️ Flights")
            for label in sorted(fl["label"].dropna().unique().tolist()):
                sub = fl[fl["label"] == label].sort_values("checked_at")
                if sub.empty:
                    continue
                latest = sub.iloc[-1]
                a, b, c = st.columns([2, 1, 1])
                a.markdown(f"**{label}**")
                b.metric("Latest", f"₹{latest['price']:,.0f}")
                c.metric("Lowest seen", f"₹{sub['price'].min():,.0f}")
                if len(sub) >= 2:
                    st.line_chart(
                        sub.set_index("checked_at")[["price"]].rename(columns={"price": label}),
                        height=180,
                    )
                else:
                    st.caption("📊 Collecting data — trend chart appears after the next daily check.")

        # ---- Hotels grouped by island ---- #
        ho = hist[hist["item_type"] == "hotel"].copy()
        if not ho.empty:
            ho["is_best"] = ho["label"].astype(str).str.endswith("(best value)")
            roster_all = ho[~ho["is_best"]]
            islands = sorted(roster_all["island"].dropna().unique().tolist()) if "island" in roster_all.columns else []
            st.markdown("### 🏨 Hotels")
            for island in islands:
                roster = roster_all[roster_all["island"] == island]
                if roster.empty:
                    continue
                with st.expander(f"🏝️ {island} · {roster['item_id'].nunique()} hotels tracked", expanded=True):
                    summary = []
                    name_to_token: dict[str, str] = {}
                    for item_id, g in roster.groupby("item_id"):
                        g = g.sort_values("checked_at")
                        last = g.iloc[-1]
                        name_to_token[str(last["label"])] = str(item_id).rsplit(":", 1)[-1]
                        summary.append({
                            "Hotel": last["label"],
                            "★": last.get("rating"),
                            "Reviews": int(last["reviews"]) if pd.notnull(last.get("reviews")) else None,
                            "Latest ₹/night": round(float(last["price"])),
                            "Lowest seen": round(float(g["price"].min())),
                            "Cheapest site": last.get("source") or "",
                        })
                    sdf = pd.DataFrame(summary).sort_values("Latest ₹/night")
                    st.dataframe(sdf, use_container_width=True, hide_index=True)

                    # Island-level overall trend (best-value = cheapest quality hotel).
                    best = ho[(ho["is_best"]) & (ho["label"].astype(str).str.startswith(island))]
                    if len(best) >= 2:
                        best = best.sort_values("checked_at")
                        st.caption("🏝️ Island best-value trend (cheapest quality hotel, ₹/night)")
                        st.line_chart(
                            best.set_index("checked_at")[["price"]].rename(columns={"price": "best value"}),
                            height=160,
                        )

                    # Choose a specific hotel to chart its own price history.
                    hcfg = next((x for x in trip.get("hotels", []) if x.get("label") == island), None)
                    sel = st.selectbox(
                        "Select a hotel to see its price history",
                        list(name_to_token.keys()),
                        key=f"hsel_{island}",
                    )
                    sel_token = name_to_token.get(sel, "")
                    sel_item_id = f"{trip_key}:hotel:{hcfg['id']}:{sel_token}" if hcfg else ""
                    sel_rows = roster[roster["item_id"].astype(str) == sel_item_id].sort_values("checked_at")
                    if len(sel_rows) >= 2:
                        st.caption(f"📈 {sel} — price history (₹/night, times in IST)")
                        st.line_chart(
                            sel_rows.set_index("checked_at")[["price"]].rename(columns={"price": sel}),
                            height=180,
                        )
                    elif len(sel_rows) == 1:
                        st.caption(
                            f"{sel}: ₹{int(sel_rows.iloc[0]['price'])}/night — only one data point so far; "
                            f"the trend line appears after the next daily check."
                        )

                    # On-demand per-site prices (MakeMyTrip / Agoda / Booking...).
                    if hcfg and is_serpapi_configured():
                        if admin:
                            if st.button("🔍 Show site prices for selected (1 credit)", key=f"site_btn_{island}"):
                                from hotels import track_hotel

                                with st.spinner("Fetching site prices..."):
                                    det = track_hotel(
                                        name_to_token.get(sel, ""),
                                        hcfg["query"], hcfg["checkin"], hcfg["checkout"],
                                        int(trip.get("travelers", 1)),
                                    )
                                if det:
                                    try:
                                        from tracker import log_manual_hotel

                                        log_manual_hotel(trip_key, hcfg["id"], island, det)
                                    except Exception as exc:
                                        print(f"log_manual_hotel failed: {exc}")
                                st.session_state[f"sites_{island}"] = (sel, det)
                            saved = st.session_state.get(f"sites_{island}")
                            if saved:
                                sname, det = saved
                                if det and det.get("sites"):
                                    st.markdown(f"**{sname}** — price by site (₹/night):")
                                    st.dataframe(
                                        pd.DataFrame(det["sites"]).rename(
                                            columns={"source": "Site", "price": "₹/night"}
                                        ),
                                        use_container_width=True, hide_index=True,
                                    )
                                    st.caption("✅ Saved to price history — future checks will compare against this.")
                                else:
                                    st.warning("No per-site prices returned for that hotel.")

                            # Add the selected hotel to the daily watchlist (+1 credit/day).
                            if st.button("📌 Track this hotel daily (watchlist, +1 credit/day)", key=f"watch_btn_{island}"):
                                wl = list(trip.get("watchlist") or [])
                                wid = f"{hcfg['id']}-{sel_token[:8]}"
                                if any(x.get("id") == wid for x in wl):
                                    st.info("Already in your watchlist.")
                                else:
                                    wl.append({
                                        "id": wid, "label": sel, "property_token": sel_token,
                                        "query": hcfg["query"], "checkin": hcfg["checkin"],
                                        "checkout": hcfg["checkout"], "target": None, "enabled": True,
                                    })
                                    save_trip(trip_key, {**trip, "watchlist": wl})
                                    st.success(f"Added '{sel}' to daily watchlist (+1 credit/day).")
                                    st.rerun()
                        else:
                            st.caption("🔑 Enter the admin password (sidebar) to fetch live site-wise prices for the selected hotel.")

        # ---- Watchlist (specific hotels tracked daily, 1 credit each) ---- #
        watch = trip.get("watchlist") or []
        if watch:
            st.markdown("### ⭐ Watchlist (tracked daily)")
            st.caption("Specific hotels you pinned — each uses 1 extra credit/day and shows per-site prices in alerts.")
            for w in watch:
                wid_full = f"{trip_key}:watch:{w['id']}"
                wrows = ho[ho["item_id"].astype(str) == wid_full].sort_values("checked_at") if "item_id" in ho.columns else ho.iloc[0:0]
                cols = st.columns([3, 1, 1, 1])
                cols[0].markdown(f"**{w.get('label','')}**")
                if not wrows.empty:
                    last = wrows.iloc[-1]
                    cols[1].metric("Latest", f"₹{last['price']:,.0f}")
                    cols[2].metric("Lowest", f"₹{wrows['price'].min():,.0f}")
                    src = last.get("source") or ""
                    cols[3].caption(f"cheapest: {src}" if src else "")
                else:
                    cols[1].caption("no data yet")
                if len(wrows) >= 2:
                    st.line_chart(
                        wrows.set_index("checked_at")[["price"]].rename(columns={"price": w.get("label", "hotel")}),
                        height=150,
                    )
                if admin and st.button("🗑️ Remove from watchlist", key=f"unwatch_{w['id']}"):
                    newwl = [x for x in watch if x.get("id") != w.get("id")]
                    save_trip(trip_key, {**trip, "watchlist": newwl})
                    st.rerun()


# ============================== EXPENSES TAB ============================== #

# Justified planned defaults for a ~5-day Andaman trip for 2 people (INR).
# These are starting points (editable) based on typical 2026 costs:
#   - Inter-island ferries: private ferries (Makruzz/Nautika/Green Ocean)
#     ~₹1,200/person/leg × ~3 legs × 2 people.
#   - Food: ~₹1,350/person/day × 5 days × 2 (mid-range cafes/seafood).
#   - Local transport: autos/taxis + a scooter rental over 5 days.
#   - Activities: scuba (~₹3.5k/pax) + snorkeling/sea-walk for two.
#   - Tickets/permits: Cellular Jail + light & sound, beach/Ross entries.
#   - Shopping & buffer: souvenirs + contingency.
DEFAULT_EXPENSES_OTHERS = [
    {"category": "Inter-island ferries", "planned": 7500, "actual": 0},
    {"category": "Food & drinks", "planned": 13500, "actual": 0},
    {"category": "Local transport (auto/taxi/scooter)", "planned": 4000, "actual": 0},
    {"category": "Activities (scuba/snorkel/sea-walk)", "planned": 10000, "actual": 0},
    {"category": "Tickets & permits", "planned": 1500, "actual": 0},
    {"category": "Shopping & souvenirs", "planned": 3000, "actual": 0},
    {"category": "Buffer / misc", "planned": 3000, "actual": 0},
]


def _flights_latest_sum(h: pd.DataFrame) -> float:
    if h.empty:
        return 0.0
    fl = h[h["item_type"] == "flight"]
    if fl.empty:
        return 0.0
    return float(_latest_per_item(fl)["price"].sum())


def _hotel_est_total(h: pd.DataFrame, cfg: dict) -> float:
    if h.empty:
        return 0.0
    ho = h[h["item_type"] == "hotel"].copy()
    best = ho[ho["label"].astype(str).str.endswith("(best value)")]
    if best.empty:
        return 0.0
    best_latest = _latest_per_item(best)
    total = 0.0
    for hotel in cfg.get("hotels", []):
        island = hotel.get("label", "")
        try:
            nights = max(1, (date.fromisoformat(str(hotel["checkout"])) - date.fromisoformat(str(hotel["checkin"]))).days)
        except Exception:
            nights = 1
        match = best_latest[best_latest["label"].astype(str).str.startswith(island)]
        if not match.empty:
            total += float(match.iloc[0]["price"]) * nights
    return total


with tab_expenses:
    st.markdown("#### 💰 Planned vs actual expenses")
    st.caption(
        "Flights & hotels pull from the live tracker (they change as deals "
        "appear). Other categories are justified estimates for a 5-day "
        "Andaman trip for 2 — edit freely and fill in 'actual' as you book."
    )

    exp = trip.get("expenses") or {}
    others = exp.get("others") or [dict(x) for x in DEFAULT_EXPENSES_OTHERS]

    flights_planned = _flights_latest_sum(hist)
    hotels_planned = _hotel_est_total(hist, trip)

    # Auto rows (planned from live data, actual editable).
    st.markdown("**Auto-tracked (from live prices)**")
    ca, cb = st.columns(2)
    with ca:
        st.metric("✈️ Flights — planned", f"₹{flights_planned:,.0f}" if flights_planned else "— (run a check)")
        flights_actual = st.number_input(
            "Flights — actual paid", min_value=0, value=int(exp.get("flights_actual") or 0),
            key=f"fa_{trip_key}", disabled=not admin,
        )
    with cb:
        st.metric("🏨 Hotels — planned", f"₹{hotels_planned:,.0f}" if hotels_planned else "— (run a check)")
        hotels_actual = st.number_input(
            "Hotels — actual paid", min_value=0, value=int(exp.get("hotels_actual") or 0),
            key=f"ha_{trip_key}", disabled=not admin,
        )

    st.markdown("**Other expenses**")
    others_df = pd.DataFrame(others)
    others_edited = st.data_editor(
        others_df, num_rows="dynamic", use_container_width=True, key=f"exp_{trip_key}",
        disabled=not admin,
        column_config={
            "category": st.column_config.TextColumn("Category"),
            "planned": st.column_config.NumberColumn("Planned ₹", min_value=0),
            "actual": st.column_config.NumberColumn("Actual ₹", min_value=0),
        },
    )

    # Totals.
    others_planned = float(pd.to_numeric(others_edited.get("planned"), errors="coerce").fillna(0).sum()) if not others_edited.empty else 0.0
    others_actual = float(pd.to_numeric(others_edited.get("actual"), errors="coerce").fillna(0).sum()) if not others_edited.empty else 0.0
    total_planned = flights_planned + hotels_planned + others_planned
    total_actual = float(flights_actual) + float(hotels_actual) + others_actual
    diff = total_actual - total_planned

    st.divider()
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Planned total", f"₹{total_planned:,.0f}")
    t2.metric("Actual so far", f"₹{total_actual:,.0f}")
    t3.metric("Difference", f"₹{diff:,.0f}", delta=f"{diff:,.0f}", delta_color="inverse")
    travelers_n = int(trip.get("travelers", 2)) or 1
    t4.metric("Planned / person", f"₹{total_planned / travelers_n:,.0f}")

    if admin:
        if st.button("💾 Save expenses", use_container_width=True, type="primary"):
            new_exp = {
                "others": others_edited.where(pd.notnull(others_edited), None).to_dict("records"),
                "flights_actual": int(flights_actual),
                "hotels_actual": int(hotels_actual),
            }
            save_trip(trip_key, {**trip, "expenses": new_exp})
            st.success("Expenses saved.")
            st.rerun()
    else:
        st.info("👀 View-only — enter the admin password in the sidebar to edit expenses.")
