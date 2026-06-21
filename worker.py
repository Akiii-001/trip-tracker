"""Background worker for the trip price tracker (Render free web service).

Trigger model: a single daily HTTP hit to **/run** (from cron-job.org at
07:00 IST) runs a price check across all active trips. This gives a precise
daily schedule and avoids duplicate credit spend. The process also serves
**/health** so Render's port-bind check passes and the dyno can be woken.

Endpoints:
  GET /health  -> JSON status (also wakes a sleeping Render dyno)
  GET /run     -> starts a price check in the background, returns immediately

Why not an internal timer? Render free dynos sleep after ~15 min idle, so a
precise time needs an external ping anyway. Driving the check from /run keeps
exactly one trigger (no double runs / wasted SerpApi credits). Set
AUTO_CHECK=1 to also run on a CHECK_INTERVAL_HOURS timer as a fallback.

Env knobs:
  AUTO_CHECK           - "1" to also run on an internal timer. Default off.
  CHECK_INTERVAL_HOURS - timer hours when AUTO_CHECK is on. Default 24.
  HEARTBEAT_ENABLED    - "1"/"true" daily Telegram heartbeat. Default on.
  MAX_RUNTIME_HOURS    - hours before clean self-exit (host restarts). Default 12.
  PORT                 - HTTP port (Render injects this). Default 10000.
"""

from __future__ import annotations

import os
import signal
import threading
import time
import traceback
from datetime import datetime, time as dtime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
HEARTBEAT_TIME = dtime(10, 5)  # daily heartbeat ~10:05 IST (just after the 10:00 run)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


AUTO_CHECK = _bool_env("AUTO_CHECK", False)
CHECK_INTERVAL_HOURS = float(os.getenv("CHECK_INTERVAL_HOURS", "24"))
HEARTBEAT_ENABLED = _bool_env("HEARTBEAT_ENABLED", True)
MAX_RUNTIME_HOURS = int(os.getenv("MAX_RUNTIME_HOURS", "12"))

_status: dict = {"started_at": None, "last_check": None, "last_summary": None, "running": False}
_stop = False
_run_lock = threading.Lock()


def _now_ist() -> datetime:
    return datetime.now(IST)


def _log(msg: str) -> None:
    print(f"[{_now_ist():%Y-%m-%d %H:%M:%S IST}] {msg}", flush=True)


def _safe_send_telegram(msg: str) -> None:
    try:
        from notifier import is_telegram_configured, send_telegram

        if is_telegram_configured():
            send_telegram(msg)
    except Exception as exc:
        _log(f"telegram send failed: {exc}")


def _do_check() -> None:
    """Run a price check across all active trips. Guarded against overlap."""
    if not _run_lock.acquire(blocking=False):
        _log("check already running; skipping duplicate trigger")
        return
    try:
        _status["running"] = True
        from tracker import run_all

        _log("running price check (all active trips)...")
        summary = run_all()
        _status["last_check"] = _now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
        _status["last_summary"] = summary
        _log(f"check ok: {summary}")
    except Exception:
        _log("price check crashed:")
        traceback.print_exc()
        _safe_send_telegram("⚠️ Trip-tracker: price check crashed. See host logs.")
    finally:
        _status["running"] = False
        _run_lock.release()


def _trigger_check_async() -> bool:
    """Start a check in a background thread. Returns False if one is running."""
    if _status.get("running"):
        return False
    threading.Thread(target=_do_check, daemon=True).start()
    return True


# ---------- main loop (keep-alive + heartbeat + self-restart) ---------- #


def _handle_stop(signum, _frame):
    global _stop
    _log(f"received signal {signum}; stopping after current cycle")
    _stop = True


def _interruptible_sleep(seconds: float) -> None:
    end = time.time() + seconds
    while not _stop and time.time() < end:
        time.sleep(min(5.0, max(0.0, end - time.time())))


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    threading.Thread(target=_start_http_server, daemon=True).start()

    started_at = _now_ist()
    _status["started_at"] = started_at.strftime("%Y-%m-%d %H:%M:%S IST")
    deadline = started_at + timedelta(hours=MAX_RUNTIME_HOURS)
    _log(
        f"trip-tracker worker started (auto_check={AUTO_CHECK}, "
        f"interval={CHECK_INTERVAL_HOURS}h, max_runtime_h={MAX_RUNTIME_HOURS}). "
        f"Trigger checks via GET /run."
    )

    last_check = 0.0
    last_heartbeat_date = None

    while not _stop:
        now = _now_ist()
        if now >= deadline:
            _log("max runtime reached; exiting cleanly so host restarts us")
            return

        if (
            HEARTBEAT_ENABLED
            and last_heartbeat_date != now.date()
            and now.time() >= HEARTBEAT_TIME
        ):
            summary = _status.get("last_summary") or {}
            _safe_send_telegram(
                f"💓 Trip-tracker alive ({now:%a %d %b %H:%M IST}). "
                f"Last check: {summary.get('checked', '?')} items, "
                f"{summary.get('alerts', 0)} alert(s)."
            )
            last_heartbeat_date = now.date()

        if AUTO_CHECK and (time.time() - last_check) >= CHECK_INTERVAL_HOURS * 3600:
            _trigger_check_async()
            last_check = time.time()

        _interruptible_sleep(30)


# ---------- HTTP server ---------- #


class _Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, body: str) -> None:
        raw = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/health", "/healthz"):
            summary = _status.get("last_summary") or {}
            self._json(200, (
                '{"status":"ok",'
                f'"now_ist":"{_now_ist():%Y-%m-%d %H:%M:%S}",'
                f'"started_at":"{_status["started_at"] or ""}",'
                f'"last_check":"{_status["last_check"] or ""}",'
                f'"running":{str(_status.get("running", False)).lower()},'
                f'"checked":{summary.get("checked", 0)},'
                f'"alerts":{summary.get("alerts", 0)}}}'
            ))
        elif self.path in ("/run", "/run/"):
            started = _trigger_check_async()
            if started:
                self._json(202, '{"status":"run started"}')
            else:
                self._json(200, '{"status":"already running"}')
        else:
            self._json(404, '{"status":"not found"}')

    def log_message(self, fmt, *args):  # noqa: N802
        return


def _start_http_server() -> None:
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    _log(f"http server listening on :{port} (/health, /run)")
    try:
        server.serve_forever()
    except Exception:
        _log("http server crashed:")
        traceback.print_exc()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        _safe_send_telegram("🚨 Trip-tracker worker crashed at top level.")
        raise
