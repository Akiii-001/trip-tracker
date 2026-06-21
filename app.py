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
    hist["checked_at"] = pd.to_datetime(hist["checked_at"], errors="coerce")
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
    c4.metric("🕒 Last checked", last_dt.strftime("%d %b %H:%M") if pd.notnull(last_dt) else "—")
else:
    c2.metric("✈️ Flights (latest sum)", "—")
    c3.metric("🏨 Est. stay total", "—")
    c4.metric("🕒 Last checked", "—")

# ------------------------- tabs ------------------------- #

tab_plan, tab_prices = st.tabs(["✏️  Plan", "📈  Prices"])


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
                st.line_chart(
                    sub.set_index("checked_at")[["price"]].rename(columns={"price": label}),
                    height=180,
                )

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

                    best = ho[(ho["is_best"]) & (ho["label"].astype(str).str.startswith(island))]
                    if not best.empty:
                        best = best.sort_values("checked_at")
                        st.caption("Best-value trend (₹/night)")
                        st.line_chart(
                            best.set_index("checked_at")[["price"]].rename(columns={"price": "best value"}),
                            height=150,
                        )

                    # On-demand per-site prices (MakeMyTrip / Agoda / Booking...).
                    hcfg = next((x for x in trip.get("hotels", []) if x.get("label") == island), None)
                    if hcfg and is_serpapi_configured():
                        sel = st.selectbox(
                            "Inspect site-wise prices for",
                            list(name_to_token.keys()),
                            key=f"site_sel_{island}",
                        )
                        if admin and st.button("🔍 Show site prices (1 credit)", key=f"site_btn_{island}"):
                            from hotels import track_hotel

                            with st.spinner("Fetching site prices..."):
                                det = track_hotel(
                                    name_to_token.get(sel, ""),
                                    hcfg["query"], hcfg["checkin"], hcfg["checkout"],
                                    int(trip.get("travelers", 1)),
                                )
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
                            else:
                                st.warning("No per-site prices returned for that hotel.")
