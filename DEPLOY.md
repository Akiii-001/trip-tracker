# Deploying the Trip Tracker (free)

Goal: the tracker runs **once a day at ~10:00 IST** in the cloud, stores
data in Supabase, and sends Telegram alerts — without your laptop being on.

Architecture (same pattern as the stock-bot):
- **Render** free web service runs `worker.py` (serves `/health` + `/run`).
- **cron-job.org** hits `…/run` once a day at 07:00 IST to trigger the check.
- **Supabase** stores trips + price history (Render's disk is wiped on
  restart, so cloud storage is required for data to persist).
- **Telegram** delivers alerts (works from Render even if blocked on your
  office network).

---

## 1. Supabase (data persistence) — required

1. Create a free project at <https://supabase.com> (or reuse your existing one).
2. Open **SQL Editor** → paste the contents of `supabase_schema.sql` → **Run**.
   This creates `trip_config`, `tracker_state`, and `price_history`.
3. Project **Settings → API**: copy the **Project URL** and the
   **service_role key** (use service_role so the worker can write).

> Reusing the stock-bot's Supabase project is fine — these are new tables and
> won't touch the stock-bot's tables.

## 2. Push this folder to GitHub

```bash
cd trip-tracker
git init
git add .
git commit -m "feat: Andaman trip price tracker"
# create an EMPTY repo on github.com, then:
git remote add origin https://github.com/<you>/trip-tracker.git
git branch -M main
git push -u origin main
```

`.env` is git-ignored, so your secrets are NOT pushed. Good.

## 3. Render web service

1. <https://dashboard.render.com> → **New → Blueprint** → connect the repo.
   Render reads `render.yaml` and creates the `trip-tracker-worker` service.
2. In the service's **Environment**, set these secrets (the rest come from
   `render.yaml`):
   - `SERPAPI_KEY`
   - `TRAVELPAYOUTS_TOKEN` (optional fallback)
   - `SUPABASE_URL`, `SUPABASE_KEY`
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
3. Deploy. When live, note the URL, e.g. `https://trip-tracker-worker.onrender.com`.
4. Test it: open `https://<your-service>.onrender.com/health` (should return
   JSON), then `…/run` once — that triggers a check and should send any alerts
   + populate Supabase. (Uses ~6 SerpApi credits.)

## 4. cron-job.org — the daily 07:00 IST trigger

1. Create a free account at <https://cron-job.org>.
2. New cron job:
   - **URL**: `https://<your-service>.onrender.com/run`
   - **Schedule**: every day at **04:30 UTC** (= 10:00 IST).
   - (Optional) a second job hitting `/health` a minute earlier to pre-wake
     the dyno, so the cold start doesn't delay the run.
3. Save. That's it — it now runs daily on its own.

## 5. Verify

- After the first `/run`, check Supabase `price_history` for new rows and your
  Telegram for the alert/heartbeat.
- The Streamlit UI (run locally or deploy separately) reads the same Supabase
  data, so your charts/roster fill in over time.

## 6. Host the UI (shareable public link) — Streamlit Community Cloud

The dashboard you've been using locally can be hosted free so you get a
`https://….streamlit.app` link to share. It reads the same Supabase data.

1. Go to <https://share.streamlit.io> → sign in with GitHub.
2. **Create app** → pick your `trip-tracker` repo, branch `main`,
   main file `app.py`.
3. **Advanced settings → Secrets**: paste (TOML format):
   ```toml
   SUPABASE_URL = "https://xxxx.supabase.co"
   SUPABASE_KEY = "your_service_role_key"
   SERPAPI_KEY = "your_serpapi_key"
   TELEGRAM_BOT_TOKEN = "your_token"
   TELEGRAM_CHAT_ID = "your_chat_id"
   APP_ADMIN_PASSWORD = "choose-a-password"
   ```
4. Deploy. Share the resulting URL with anyone.

**Important:** set `APP_ADMIN_PASSWORD` so visitors can *view* charts but only
you (with the password, entered in the sidebar) can edit the trip or run
credit-spending checks. Without it, anyone could spend your SerpApi credits.

> The UI and the worker are two separate deploys but share one Supabase, so
> the worker collects data daily and the UI shows it live.

---

## Notes
- **Credits**: 1 daily run = 3 flights + 3 island searches ≈ 6 SerpApi
  searches/day ≈ 180/month (under the free 250). Hotel alerts add 1 detail
  call each, only when they fire.
- **Auto-stop**: once a trip's start date arrives, `run_all()` skips it — no
  wasted credits after the trip begins.
- **Multiple trips**: every active trip is checked each run. Keep an eye on
  total credits if you add several trips.
- The Streamlit **UI** is optional to deploy. To host it too, add a second
  Render service (or Streamlit Community Cloud) running
  `streamlit run app.py`, with the same env vars.
