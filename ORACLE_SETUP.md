# Run the trip-tracker on your Oracle VM (daily cron)

The tracker runs **once a day** (not a 24/7 loop), so on Oracle it's just a
single `cron` entry that runs the price check — no web server, no systemd,
no cold starts, no GitHub-minute limits. Reuse the **same Always-Free VM**
that runs your stock-bot.

All commands run **on the VM** (the `ubuntu@...` prompt). Get there from
Oracle Cloud Shell: `ssh ubuntu@YOUR_VM_PUBLIC_IP`.

## 1. Clone the repo (public — no deploy key needed)
```bash
git clone https://github.com/Akiii-001/trip-tracker.git ~/trip-tracker
cd ~/trip-tracker
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-worker.txt
```

## 2. Add your secrets
```bash
cat > ~/trip-tracker/.env <<'EOF'
SERPAPI_KEY=...
SUPABASE_URL=...
SUPABASE_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TRAVELPAYOUTS_TOKEN=
EOF
chmod 600 ~/trip-tracker/.env
```
(Use the same values from your local `.env`.)

## 3. Smoke test (writes to Supabase + sends Telegram; uses ~6 SerpApi credits)
```bash
cd ~/trip-tracker && .venv/bin/python -c "from tracker import run_all; run_all()"
```
You should see `run_all complete: {...}` and a Telegram heartbeat.

## 4. Schedule it daily at 10:00 IST
The VM clock is UTC, and 10:00 IST = **04:30 UTC**. Add a cron entry:
```bash
( crontab -l 2>/dev/null; echo '30 4 * * * cd /home/ubuntu/trip-tracker && /home/ubuntu/trip-tracker/.venv/bin/python -c "from tracker import run_all; run_all()" >> /home/ubuntu/trip-tracker/cron.log 2>&1' ) | crontab -
```
Verify it's installed:
```bash
crontab -l
```

## 5. Retire the old triggers
- **cron-job.org**: delete/disable the `Daily Tracker` and `Tracker wake up` jobs.
- **GitHub Actions**: optional — disable the `Daily trip price check` workflow
  (repo → Actions → the workflow → ⋯ → Disable). Keep it as a manual fallback
  if you like; it won't run on a schedule if disabled.
- **Render**: the `trip-tracker-worker` service is no longer needed; you can
  delete it.

## Useful commands
| Task | Command |
|---|---|
| See the schedule | `crontab -l` |
| Run now (manual) | `cd ~/trip-tracker && .venv/bin/python -c "from tracker import run_all; run_all()"` |
| View last run log | `tail -n 50 ~/trip-tracker/cron.log` |
| Update code later | `cd ~/trip-tracker && git pull && .venv/bin/pip install -r requirements-worker.txt` |
| Change time | `crontab -e` then edit the `30 4 * * *` (UTC) part |

## Notes
- The Streamlit **UI stays on Streamlit Community Cloud** (unchanged) — it reads
  the same Supabase data the VM writes. Oracle only handles the daily run.
- ~6 SerpApi searches/day ≈ 180/month, under the free 250.
- Tracking auto-stops once a trip's start date passes (`run_all` skips it).
