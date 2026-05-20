"""
Realtime alert engine for Trading-MA.

Runs as a standalone script (see .github/workflows/alerts.yml) on a ~5-minute
cron during US market hours. For each ticker on the alert watchlist it:
  1. fetches ~9 months of daily bars from Alpaca — the last bar is today's
     in-progress bar, so the indicators reflect the current price,
  2. evaluates it against the saved alert criteria using the same
     screener.evaluate_ticker logic the web UI uses,
  3. sends a Telegram message for any ticker that newly passes — deduped
     so you get at most one alert per ticker per trading day.

The web app (app.py) imports this module only for watchlist / config
management; the alerting loop itself is invoked via `python alerts.py`.

Env vars (set as GitHub Actions secrets):
  DATABASE_URL         Postgres (shared with the web app)
  ALPACA_API_KEY       Alpaca API key id
  ALPACA_SECRET_KEY    Alpaca API secret
  TELEGRAM_BOT_TOKEN   from @BotFather
  TELEGRAM_CHAT_ID     your chat id

Data caveat: Alpaca's free tier serves IEX-only data. Prices (and hence
RSI/EMA/MACD) are realtime and accurate. Volume is IEX-only — a fraction
of consolidated volume — so the relative-volume *ratio* is roughly
preserved but the absolute avg-volume floor is not; apply_avg_volume
defaults to False for alerts for that reason.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, time as dt_time

import pandas as pd
import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

import screener
import snapshots

log = logging.getLogger("alerts")

ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "").strip()
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "").strip()
ALPACA_DATA_URL = "https://data.alpaca.markets/v2"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Alert criteria default to the screener's defaults, with two changes:
# avg-volume floor off (IEX volume undercounts — see module docstring),
# and turnover off (no shares-outstanding feed in the alert path).
DEFAULT_ALERT_PARAMS: dict = {
    "high_lookback": 2,
    "streak_mode": "high",
    "rsi_min": 45.0, "rsi_max": 65.0,
    "rsi_dev_min_pct": 0.0, "rsi_dev_max_pct": 10.0,
    "rvol_lookback": 10, "rvol_min": 1.2,
    "avg_volume_min": 50000,
    "price_min": 1.0, "price_max": 1000.0,
    "price_dev_min_pct": -1.0, "price_dev_max_pct": 4.0,
    "ema_dev_min_pct": -3.0, "ema_dev_max_pct": 3.0,
    "macd_hist_min": 0.0, "macd_require_rising": True,
    "turnover_min_pct": 0.5, "turnover_max_pct": 100.0,
    "apply_high": True, "apply_rsi": True, "apply_rsi_dev": True,
    "apply_rvol": True, "apply_avg_volume": False,
    "apply_price": True, "apply_price_dev": True,
    "apply_ema_dev": True, "apply_macd": True,
    "apply_turnover": False,
}

# Only these keys are valid kwargs for screener.evaluate_ticker.
_PARAM_KEYS = frozenset(DEFAULT_ALERT_PARAMS.keys())


# --- alert tables ----------------------------------------------------------

_ALERT_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_watchlist (
    ticker   TEXT PRIMARY KEY,
    added_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS alert_state (
    ticker       TEXT NOT NULL,
    trigger_date DATE NOT NULL,
    detail       TEXT,
    sent_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (ticker, trigger_date)
);
CREATE TABLE IF NOT EXISTS alert_config (
    id         INT PRIMARY KEY,
    params     JSONB,
    updated_at TIMESTAMPTZ DEFAULT now()
);
"""


def enabled() -> bool:
    """The alert layer needs Postgres; everything else degrades to a no-op."""
    return snapshots.enabled()


def init_tables() -> None:
    """Idempotent CREATE TABLE for the alert tables. Safe on every boot."""
    if not enabled():
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(_ALERT_SCHEMA)
    except Exception as exc:
        log.warning("alerts: init_tables failed: %s", exc)


# --- watchlist -------------------------------------------------------------

def get_watchlist() -> list[str]:
    if not enabled():
        return []
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("SELECT ticker FROM alert_watchlist ORDER BY ticker")
            return [r[0] for r in cur.fetchall()]
    except Exception as exc:
        log.warning("alerts: get_watchlist failed: %s", exc)
        return []


def add_to_watchlist(tickers: list[str]) -> int:
    """Insert tickers (upper-cased, de-duped). Returns count submitted."""
    clean = sorted({t.strip().upper() for t in tickers if t and t.strip()})
    if not enabled() or not clean:
        return 0
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.executemany(
                "INSERT INTO alert_watchlist (ticker) VALUES (%s) "
                "ON CONFLICT (ticker) DO NOTHING",
                [(t,) for t in clean],
            )
        return len(clean)
    except Exception as exc:
        log.warning("alerts: add_to_watchlist failed: %s", exc)
        return 0


def remove_from_watchlist(ticker: str) -> bool:
    if not enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM alert_watchlist WHERE ticker = %s",
                        (ticker.strip().upper(),))
            return (cur.rowcount or 0) > 0
    except Exception as exc:
        log.warning("alerts: remove_from_watchlist failed: %s", exc)
        return False


# --- alert criteria config -------------------------------------------------

def get_alert_params() -> dict:
    """Return the saved alert criteria, falling back to defaults. Only
    keys that are valid evaluate_ticker kwargs are kept."""
    params = dict(DEFAULT_ALERT_PARAMS)
    if not enabled():
        return params
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("SELECT params FROM alert_config WHERE id = 1")
            row = cur.fetchone()
        if row and row[0]:
            stored = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            for k, v in stored.items():
                if k in _PARAM_KEYS:
                    params[k] = v
    except Exception as exc:
        log.warning("alerts: get_alert_params failed: %s", exc)
    return params


def set_alert_params(params: dict) -> bool:
    """Persist alert criteria. Unknown keys are dropped."""
    if not enabled():
        return False
    clean = {k: v for k, v in (params or {}).items() if k in _PARAM_KEYS}
    if not clean:
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO alert_config (id, params, updated_at) "
                "VALUES (1, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET params = EXCLUDED.params, "
                "updated_at = now()",
                (json.dumps(clean),),
            )
        return True
    except Exception as exc:
        log.warning("alerts: set_alert_params failed: %s", exc)
        return False


# --- dedup state -----------------------------------------------------------

def already_alerted(ticker: str, trigger_date: str) -> bool:
    if not enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM alert_state WHERE ticker = %s AND trigger_date = %s",
                (ticker, trigger_date),
            )
            return cur.fetchone() is not None
    except Exception as exc:
        log.warning("alerts: already_alerted failed: %s", exc)
        return False


def record_alert(ticker: str, trigger_date: str, detail: str) -> None:
    if not enabled():
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO alert_state (ticker, trigger_date, detail) "
                "VALUES (%s, %s, %s) ON CONFLICT (ticker, trigger_date) DO NOTHING",
                (ticker, trigger_date, detail),
            )
    except Exception as exc:
        log.warning("alerts: record_alert failed: %s", exc)


# --- Alpaca market data ----------------------------------------------------

def fetch_daily_bars(symbols: list[str], lookback_days: int = 270) -> dict[str, pd.DataFrame]:
    """Fetch daily OHLCV bars for `symbols` from Alpaca. The most recent
    bar is the current (in-progress) trading day, so downstream
    indicators reflect the live price. Returns {symbol: DataFrame}."""
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY) or not symbols:
        return {}
    start = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    collected: dict[str, list] = {}
    page_token = None
    while True:
        params = {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "start": start,
            "limit": 10000,
            "feed": "iex",
            "adjustment": "raw",
        }
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(f"{ALPACA_DATA_URL}/stocks/bars",
                            headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for sym, bars in (data.get("bars") or {}).items():
            collected.setdefault(sym, []).extend(bars)
        page_token = data.get("next_page_token")
        if not page_token:
            break
    frames: dict[str, pd.DataFrame] = {}
    for sym, bars in collected.items():
        if not bars:
            continue
        df = pd.DataFrame(bars)
        if df.empty or "c" not in df.columns:
            continue
        df["t"] = pd.to_datetime(df["t"])
        df = df.set_index("t").sort_index()
        df = df.rename(columns={"o": "Open", "h": "High", "l": "Low",
                                "c": "Close", "v": "Volume"})
        keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
        frames[sym] = df[keep].astype("float32")
    return frames


# --- Telegram --------------------------------------------------------------

def send_telegram(text: str) -> bool:
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        log.warning("alerts: Telegram not configured — skipping send")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        log.warning("alerts: Telegram send failed: %s", exc)
        return False


def _format_alert(hit) -> str:
    return (
        f"<b>{hit.ticker}</b> — {hit.name}\n"
        f"Price ${hit.close:.2f} ({hit.pct_change:+.2f}%)\n"
        f"Momentum {hit.momentum_score:.0f}/100\n"
        f"RSI {hit.rsi:.1f} | MACD hist {hit.macd_hist:+.3f} | "
        f"RVol {hit.rel_volume:.2f}x\n"
        f"Matched alert criteria — as of {hit.as_of_date}"
    )


# --- market clock ----------------------------------------------------------

def _now_et() -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            pass
    return datetime.utcnow() - timedelta(hours=4)


def market_is_open(now: datetime | None = None) -> bool:
    """US regular session, weekdays 9:30am-4:00pm ET. Does not account
    for market holidays — a holiday just yields zero fresh bars, so the
    worst case is a wasted run, not a wrong alert."""
    now = now or _now_et()
    if now.weekday() >= 5:
        return False
    return dt_time(9, 30) <= now.time() <= dt_time(16, 0)


# --- main loop -------------------------------------------------------------

def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not enabled():
        log.error("DATABASE_URL not set — cannot run alerts")
        return 1
    init_tables()

    now = _now_et()
    if not market_is_open(now):
        log.info("market closed (%s ET) — skipping", now.strftime("%a %H:%M"))
        return 0

    watchlist = get_watchlist()
    if not watchlist:
        log.info("alert watchlist empty — nothing to evaluate")
        return 0
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
        log.error("ALPACA_API_KEY / ALPACA_SECRET_KEY not set")
        return 1

    params = get_alert_params()
    today = now.strftime("%Y-%m-%d")
    log.info("evaluating %d watchlist tickers", len(watchlist))

    try:
        frames = fetch_daily_bars(watchlist)
    except Exception as exc:
        log.error("Alpaca fetch failed: %s", exc)
        return 1

    triggered = []
    for ticker in watchlist:
        if already_alerted(ticker, today):
            continue
        df = frames.get(ticker)
        if df is None or len(df) < 40:
            continue
        try:
            # Reuse the screener's evaluation by injecting the live frame
            # into its in-memory cache, then calling evaluate_ticker — the
            # same code path the web UI uses, so alert logic can't drift
            # from screen logic.
            enriched = screener._enrich(df.copy())
            screener._PRICE_CACHE[ticker] = (time.time(), enriched)
            hit = screener.evaluate_ticker(ticker, **params)
        except Exception as exc:
            log.warning("evaluate failed for %s: %s", ticker, exc)
            continue
        if hit is None:
            continue
        triggered.append(hit)
        record_alert(ticker, today, f"momentum={hit.momentum_score}")

    if not triggered:
        log.info("no new alerts this run")
        return 0

    sent = 0
    for hit in triggered:
        if send_telegram(_format_alert(hit)):
            sent += 1
    log.info("alerts: %d triggered, %d sent to Telegram", len(triggered), sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
