# 🏝️ Andaman Trip Price Tracker

Tracks **Kolkata ↔ Port Blair flights** (free) and, optionally, **Andaman
hotels** (Havelock, Neil, Port Blair), logs price history, and sends a
**Telegram alert** when prices drop to your target, hit a new low, or fall
sharply since the last check.

Reuses the same proven stack as the stock-bot: Streamlit UI + Supabase
persistence + a Render free-tier worker kept awake by a cron-job.org ping.
It is a completely separate project — the stock-bot is untouched.

## Data sources (and why)

The free travel-API landscape changed in 2026, so this uses the options
that are actually alive:

- **Flights → Travelpayouts / Aviasales Data API (FREE).** Returns the
  cheapest *cached* fares Aviasales users found for a route/date. Perfect
  for trend/drop alerts. (Amadeus Self-Service is being decommissioned in
  July 2026, so it was dropped.)
- **Hotels → SerpApi Google Hotels (OPTIONAL, paid).** The free hotel
  APIs shut down (Hotellook discontinued, Amadeus going away), so the only
  reliable option that surfaces Agoda/MakeMyTrip/Booking-style prices is
  SerpApi. **Hotels are optional** — without a `SERPAPI_KEY` the tracker
  runs flights-only, for free.

## How it works

```
worker.py  ──every 6h──▶ tracker.run_check()
                              │
            ┌─────────────────┼──────────────────┐
            ▼                 ▼                  ▼
      flights.py         hotels.py         price logged to
   (Travelpayouts /   (SerpApi Google      Supabase / JSON
    Aviasales Data)    Hotels, optional)        │
            └─────────────────┴──────────────────┘
                              ▼
                  alert? (target / new low / big drop)
                              ▼
                       notifier.send_telegram()

app.py (Streamlit) ── edit trip, run checks on demand, view charts
```

## Notes on accuracy

- **Flight prices are cached**, not live booking quotes. For a busy route
  they're very representative; for a thinner route like Kolkata→Port Blair
  the cache can occasionally be empty (the app handles that gracefully).
  Prices are per-person × travelers, shown as the total trip cost.
- **Hotel prices** come from Google Hotels via SerpApi and reflect what
  you'd see comparing sites on Google.

## Setup

1. **Install deps**

   ```bash
   pip install -r requirements.txt
   ```

2. **Get your free Travelpayouts token**: sign up at
   <https://www.travelpayouts.com/>, then copy the token from
   **Profile → API token** (<https://app.travelpayouts.com/profile/api-token>).

3. **Create a Telegram bot** with @BotFather, get your chat id from
   @userinfobot.

4. **Copy `.env.example` to `.env`** and fill in the values.

5. *(Optional)* **SerpApi key** for hotel tracking — add `SERPAPI_KEY`.

6. *(Optional)* **Supabase**: create a project, run `supabase_schema.sql`
   in the SQL editor, and add `SUPABASE_URL` / `SUPABASE_KEY`. Without
   Supabase the app stores everything in local JSON files.

## Run

- **Confirm your keys work** (no Telegram, no writes):
  ```bash
  python test_travelpayouts.py
  ```
- **UI (edit trip + view charts):**
  ```bash
  streamlit run app.py
  ```
- **One-off price check:**
  ```bash
  python tracker.py
  ```
- **Background worker (checks every 6h):**
  ```bash
  python worker.py
  ```

## Deploy (Render free tier)

1. Push this folder to a Git repo.
2. In Render, create a service from `render.yaml` (Blueprint).
3. Add the secret env vars (Travelpayouts, Telegram, optional SerpApi /
   Supabase) in the dashboard.
4. Add a cron-job.org job pinging `https://<your-service>.onrender.com/health`
   every ~10 min during the hours you want it awake.

## Your trip (default config)

| Item | Detail |
|------|--------|
| Travelers | 2 |
| Outbound | Kolkata (CCU) → Port Blair (IXZ), 28 Sep 2026 |
| Return | Port Blair (IXZ) → Kolkata (CCU), 3 Oct 2026 |
| Hotels | Havelock 28 Sep–1 Oct → Neil 1–2 Oct → Port Blair 2–3 Oct |

Everything above is editable in the Streamlit UI (or `trip.json` locally).

## Quota notes

- **Travelpayouts** Data API is generous for personal use; checking ~2
  flights every 6h is trivial.
- **SerpApi** free trial is small (~100 searches/month). With 3 hotels,
  check roughly once a day (≈90/month) to stay within it, or raise
  `CHECK_INTERVAL_HOURS`.
