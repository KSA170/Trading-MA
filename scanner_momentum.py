"""
Real-time momentum scanner — independent of the nightly watchlist.

Runs every ~5 min during US market hours via GitHub Actions. Walks the
full snapshot universe (~5,000 tickers) and fires a Telegram alert the
first time a ticker passes all four configurable filters on the same
trading day:

  1. % price change today  >= pct_change_min       (default 5%)
  2. relative volume       >= rvol_min × N-day avg (default 5×, N=20)
  3. today's intraday high >  max of prior N-day highs  (default N=20)
  4. today's volume / shares outstanding >= vol_mcap_min  (default 0.5%)

Idempotent via momentum_scanner_alerts PK on (alert_date, ticker):
re-running the cron multiple times on the same trading day re-sends
zero alerts.

Data shape:

- Prior-N-day baseline (avg vol, N-day high, prior close) is read from
  the most recent daily_snapshot row's `recent_bars` JSONB. No extra
  API calls — the snapshot already carries up to 60 daily bars.
- Today's in-progress bar (cumulative O/H/L/C/V from 9:30 ET to "now")
  is fetched from Alpaca's daily-bar endpoint with start=today. One
  request per 50-symbol batch, reusing alerts._alpaca_bars_request
  which already handles BRK-B↔BRK.B translation, pagination, and
  recursive splitting on 4xx.

TSX tickers (.TO / .V suffix) are skipped — Alpaca doesn't carry them.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

import snapshots

log = logging.getLogger("scanner_momentum")


# --- defaults --------------------------------------------------------------

DEFAULT_PCT_CHANGE_MIN: float = 5.0    # % gain today
DEFAULT_RVOL_MIN:       float = 5.0    # today's vol / N-day avg
DEFAULT_RVOL_LOOKBACK:  int   = 20     # N (days) for the rvol denominator
DEFAULT_HIGH_LOOKBACK:  int   = 20     # N (days) for the new-high check
DEFAULT_VOL_MCAP_MIN:   float = 0.5    # % of shares outstanding traded today

_FORCE_RUN_ENV = "MOMENTUM_SCANNER_FORCE_RUN"


# --- schema ----------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS momentum_scanner_config (
    id              INT  PRIMARY KEY DEFAULT 1,
    pct_change_min  REAL,
    rvol_min        REAL,
    rvol_lookback   INT,
    high_lookback   INT,
    vol_mcap_min    REAL,
    updated_at      TIMESTAMPTZ DEFAULT now()
);
-- Toggle that lets the UI pause the scanner without touching GitHub
-- Actions. The workflow still fires every 5 min on schedule but exits
-- immediately when this flag is FALSE.
ALTER TABLE momentum_scanner_config
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS momentum_scanner_alerts (
    alert_date    DATE NOT NULL,
    ticker        TEXT NOT NULL,
    fired_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    price         REAL,
    pct_change    REAL,
    rvol          REAL,
    vol_mcap_pct  REAL,
    new_high      REAL,
    details       TEXT,
    PRIMARY KEY (alert_date, ticker)
);
CREATE INDEX IF NOT EXISTS momentum_scanner_alerts_date_idx
    ON momentum_scanner_alerts (alert_date DESC, fired_at DESC);
"""


def init_tables() -> None:
    if not snapshots.enabled():
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(_SCHEMA)
    except Exception as exc:
        log.warning("scanner_momentum.init_tables failed: %s", exc)


# --- config ----------------------------------------------------------------

def get_config() -> dict:
    cfg = {
        "pct_change_min": DEFAULT_PCT_CHANGE_MIN,
        "rvol_min":       DEFAULT_RVOL_MIN,
        "rvol_lookback":  DEFAULT_RVOL_LOOKBACK,
        "high_lookback":  DEFAULT_HIGH_LOOKBACK,
        "vol_mcap_min":   DEFAULT_VOL_MCAP_MIN,
        "enabled":        True,
    }
    if not snapshots.enabled():
        return cfg
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT pct_change_min, rvol_min, rvol_lookback, "
                "high_lookback, vol_mcap_min, enabled "
                "FROM momentum_scanner_config WHERE id = 1"
            )
            row = cur.fetchone()
    except Exception as exc:
        log.warning("scanner_momentum.get_config failed: %s", exc)
        return cfg
    if not row:
        return cfg
    if row[0] is not None: cfg["pct_change_min"] = float(row[0])
    if row[1] is not None: cfg["rvol_min"]       = float(row[1])
    if row[2] is not None: cfg["rvol_lookback"]  = int(row[2])
    if row[3] is not None: cfg["high_lookback"]  = int(row[3])
    if row[4] is not None: cfg["vol_mcap_min"]   = float(row[4])
    if row[5] is not None: cfg["enabled"]        = bool(row[5])
    return cfg


def set_enabled(enabled: bool) -> bool:
    """Toggle the scanner kill-switch. Read by run() at startup;
    when FALSE the workflow exits immediately."""
    if not snapshots.enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO momentum_scanner_config (id, enabled, updated_at) "
                "VALUES (1, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET "
                "enabled = EXCLUDED.enabled, "
                "updated_at = now()",
                (bool(enabled),),
            )
        return True
    except Exception as exc:
        log.warning("scanner_momentum.set_enabled failed: %s", exc)
        return False


def save_config(
    pct_change_min: float, rvol_min: float,
    rvol_lookback: int, high_lookback: int,
    vol_mcap_min: float,
) -> bool:
    if not snapshots.enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO momentum_scanner_config "
                "(id, pct_change_min, rvol_min, rvol_lookback, "
                "high_lookback, vol_mcap_min, updated_at) "
                "VALUES (1, %s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET "
                "pct_change_min = EXCLUDED.pct_change_min, "
                "rvol_min       = EXCLUDED.rvol_min, "
                "rvol_lookback  = EXCLUDED.rvol_lookback, "
                "high_lookback  = EXCLUDED.high_lookback, "
                "vol_mcap_min   = EXCLUDED.vol_mcap_min, "
                "updated_at = now()",
                (float(pct_change_min), float(rvol_min),
                 int(rvol_lookback), int(high_lookback),
                 float(vol_mcap_min)),
            )
        return True
    except Exception as exc:
        log.warning("scanner_momentum.save_config failed: %s", exc)
        return False


# --- market-hours gate (shared shape with picker_intraday) -----------------

def _et_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return datetime.now(timezone.utc) + timedelta(hours=-5)


def _market_is_open(now_et: datetime) -> bool:
    if now_et.weekday() >= 5:
        return False
    hm = now_et.hour * 100 + now_et.minute
    return 930 <= hm <= 1600


def _is_us_ticker(t: str) -> bool:
    if not t:
        return False
    return not (t.endswith(".TO") or t.endswith(".V"))


# --- baseline (prior-N-day stats) from snapshot ----------------------------

def _bars_from_row(row: dict) -> list[dict] | None:
    """Parse the recent_bars JSONB into a list of bar dicts."""
    rb = row.get("recent_bars")
    if rb is None:
        return None
    if isinstance(rb, str):
        try:
            rb = json.loads(rb)
        except Exception:
            return None
    if not isinstance(rb, dict):
        return None
    bars = rb.get("bars")
    if not isinstance(bars, list):
        return None
    return bars


def _load_universe_baseline(today_str: str, rvol_lookback: int,
                            high_lookback: int) -> dict[str, dict]:
    """For every US ticker in the most recent daily_snapshot, derive:

      prior_close   — last close strictly before today
      avg_vol       — mean volume over the most recent `rvol_lookback`
                      bars that are strictly before today
      high_n        — max high over the most recent `high_lookback`
                      bars that are strictly before today
      shares        — shares outstanding (for vol/mcap)

    Filtering `d < today` keeps the baseline window honest even if the
    snapshot was unusually refreshed mid-session (rare — the nightly job
    runs at close+1hr)."""
    if not snapshots.enabled():
        return {}
    dates = snapshots.available_dates(1)
    if not dates:
        return {}
    as_of = dates[0]

    need = max(rvol_lookback, high_lookback, 1)
    out: dict[str, dict] = {}
    skipped_non_us = 0
    skipped_no_shares = 0
    skipped_no_bars = 0
    skipped_short_history = 0
    for ticker, row in snapshots.iter_for_date(as_of):
        if not _is_us_ticker(ticker):
            skipped_non_us += 1
            continue
        shares = row.get("shares")
        if shares is None or float(shares) <= 0:
            skipped_no_shares += 1
            continue
        bars = _bars_from_row(row)
        if not bars:
            skipped_no_bars += 1
            continue
        prior_bars = [
            b for b in bars
            if isinstance(b, dict) and (b.get("d") or "9999-12-31") < today_str
        ]
        if len(prior_bars) < need:
            skipped_short_history += 1
            continue
        try:
            prior_close = float(prior_bars[-1].get("c") or 0)
        except (TypeError, ValueError):
            continue
        if prior_close <= 0:
            continue
        try:
            vol_window = prior_bars[-rvol_lookback:]
            vols = [float(b.get("v") or 0) for b in vol_window]
            avg_vol = float(np.mean(vols)) if vols else 0.0
        except (TypeError, ValueError):
            continue
        if avg_vol <= 0:
            continue
        try:
            high_window = prior_bars[-high_lookback:]
            high_n = max(float(b.get("h") or 0) for b in high_window)
        except (TypeError, ValueError):
            continue
        if high_n <= 0:
            continue
        out[ticker] = {
            "prior_close": prior_close,
            "avg_vol":     avg_vol,
            "high_n":      high_n,
            "shares":      float(shares),
        }
    log.info(
        "baseline: as_of=%s eligible=%d (skipped: non-us=%d, "
        "no-shares=%d, no-bars=%d, short-history=%d)",
        as_of, len(out), skipped_non_us, skipped_no_shares,
        skipped_no_bars, skipped_short_history,
    )
    return out


# --- today's live bar from Alpaca ------------------------------------------

def _fetch_today_bars(symbols: list[str], today_str: str) -> dict[str, dict]:
    """Daily bar with start=today for each symbol — Alpaca returns the
    in-progress today bar (cumulative since open). Reuses the splitting
    helper alerts.py uses for nightly bars so a single rejected symbol
    doesn't sink the whole batch.

    Returns {ticker: bar_dict} only for tickers that have traded today.
    Tickers with no today-bar (illiquid, halted, recently delisted) are
    silently dropped."""
    import alerts
    if not (alerts.ALPACA_API_KEY and alerts.ALPACA_SECRET_KEY) or not symbols:
        return {}
    headers = {
        "APCA-API-KEY-ID":     alerts.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": alerts.ALPACA_SECRET_KEY,
    }
    collected: dict[str, list] = {}
    chunk = 50
    for i in range(0, len(symbols), chunk):
        batch = symbols[i:i + chunk]
        collected.update(alerts._alpaca_bars_request(batch, today_str, headers))
    out: dict[str, dict] = {}
    for sym, bars in collected.items():
        if not bars:
            continue
        last = bars[-1]
        # Belt-and-braces: only accept bars whose t starts with today's
        # date. Alpaca occasionally returns a yesterday-flagged bar on
        # the first request after market open.
        ts = (last.get("t") or "")[:10]
        if ts and ts != today_str:
            continue
        out[sym] = last
    return out


# --- per-ticker evaluation -------------------------------------------------

def _evaluate_one(baseline: dict, today_bar: dict, cfg: dict) -> dict | None:
    """Compute all four metrics for one ticker. Returns the metrics dict
    if every filter passes, else None."""
    try:
        last_price  = float(today_bar.get("c") or 0)
        today_high  = float(today_bar.get("h") or 0)
        today_vol   = float(today_bar.get("v") or 0)
    except (TypeError, ValueError):
        return None
    if last_price <= 0 or today_vol <= 0:
        return None

    prior_close = baseline["prior_close"]
    pct_change  = (last_price / prior_close - 1.0) * 100.0
    rvol        = today_vol / baseline["avg_vol"]
    vol_mcap    = (today_vol / baseline["shares"]) * 100.0
    new_high_ok = today_high > baseline["high_n"]

    if pct_change < cfg["pct_change_min"]:   return None
    if rvol       < cfg["rvol_min"]:         return None
    if not new_high_ok:                      return None
    if vol_mcap   < cfg["vol_mcap_min"]:     return None

    return {
        "price":        last_price,
        "today_high":   today_high,
        "today_vol":    today_vol,
        "prior_close":  prior_close,
        "prior_high_n": baseline["high_n"],
        "pct_change":   pct_change,
        "rvol":         rvol,
        "vol_mcap_pct": vol_mcap,
    }


# --- dedup / persistence ---------------------------------------------------

def already_fired_today(alert_date: str, ticker: str) -> bool:
    if not snapshots.enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM momentum_scanner_alerts "
                "WHERE alert_date = %s AND ticker = %s",
                (alert_date, ticker),
            )
            return cur.fetchone() is not None
    except Exception as exc:
        log.warning("scanner_momentum.already_fired_today failed: %s", exc)
        return False


def fired_tickers_for_date(alert_date: str) -> set[str]:
    """Bulk version — avoids N round-trips when filtering 5,000 tickers."""
    if not snapshots.enabled():
        return set()
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT ticker FROM momentum_scanner_alerts "
                "WHERE alert_date = %s", (alert_date,),
            )
            return {r[0] for r in cur.fetchall()}
    except Exception as exc:
        log.warning("scanner_momentum.fired_tickers_for_date failed: %s", exc)
        return set()


def record_alert(alert_date: str, ticker: str, metrics: dict,
                 details: str) -> bool:
    """Idempotent insert. Returns True when the row was freshly inserted
    (caller should send Telegram). False when a parallel run beat us."""
    if not snapshots.enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO momentum_scanner_alerts "
                "(alert_date, ticker, price, pct_change, rvol, "
                "vol_mcap_pct, new_high, details) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (alert_date, ticker) DO NOTHING",
                (alert_date, ticker, metrics["price"], metrics["pct_change"],
                 metrics["rvol"], metrics["vol_mcap_pct"],
                 metrics["prior_high_n"], details),
            )
            return (cur.rowcount or 0) > 0
    except Exception as exc:
        log.warning("scanner_momentum.record_alert failed: %s", exc)
        return False


def alerts_for_date(alert_date: str | None = None) -> list[dict]:
    """Read alerts for `alert_date` (default: most recent date in the
    table), newest first. Used by the UI panel."""
    if not snapshots.enabled():
        return []
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            if alert_date:
                cur.execute(
                    "SELECT alert_date, ticker, fired_at, price, pct_change, "
                    "rvol, vol_mcap_pct, new_high, details "
                    "FROM momentum_scanner_alerts WHERE alert_date = %s "
                    "ORDER BY fired_at DESC", (alert_date,),
                )
            else:
                cur.execute(
                    "SELECT alert_date, ticker, fired_at, price, pct_change, "
                    "rvol, vol_mcap_pct, new_high, details "
                    "FROM momentum_scanner_alerts WHERE alert_date = ("
                    "  SELECT MAX(alert_date) FROM momentum_scanner_alerts"
                    ") ORDER BY fired_at DESC"
                )
            rows = cur.fetchall()
        return [
            {
                "alert_date":   r[0].isoformat() if r[0] else None,
                "ticker":       r[1],
                "fired_at":     r[2].isoformat() if r[2] else None,
                "price":        float(r[3]) if r[3] is not None else None,
                "pct_change":   float(r[4]) if r[4] is not None else None,
                "rvol":         float(r[5]) if r[5] is not None else None,
                "vol_mcap_pct": float(r[6]) if r[6] is not None else None,
                "new_high":     float(r[7]) if r[7] is not None else None,
                "details":      r[8],
            }
            for r in rows
        ]
    except Exception as exc:
        log.warning("scanner_momentum.alerts_for_date failed: %s", exc)
        return []


# --- Telegram --------------------------------------------------------------

def _format_telegram(ticker: str, m: dict, cfg: dict,
                     insider: dict | None = None,
                     fund: dict | None = None) -> str:
    import enrich
    lines = [
        f"🚀 <b>{ticker}</b> · momentum scan · ${m['price']:.2f}",
        f"<i>+{m['pct_change']:.1f}% today · RVOL {m['rvol']:.1f}× · "
        f"new {cfg['high_lookback']}-day high (prior ${m['prior_high_n']:.2f}) · "
        f"{m['vol_mcap_pct']:.2f}% of float</i>",
    ]
    insider_line = enrich.format_insider_line(insider)
    if insider_line:
        lines.append(insider_line)
    fund_line = enrich.format_fundamentals_line(fund)
    if fund_line:
        lines.append(fund_line)
    return "\n".join(lines)


def _format_details(m: dict, cfg: dict) -> str:
    return (
        f"+{m['pct_change']:.2f}% vs prior close ${m['prior_close']:.2f}; "
        f"RVOL {m['rvol']:.2f}× ({cfg['rvol_lookback']}-day avg); "
        f"new {cfg['high_lookback']}-day high "
        f"(today {m['today_high']:.2f} > prior {m['prior_high_n']:.2f}); "
        f"vol/float {m['vol_mcap_pct']:.3f}%"
    )


# --- main entry ------------------------------------------------------------

def run() -> int:
    import alerts as alerts_mod

    if not snapshots.enabled():
        log.error("DATABASE_URL not set — cannot run momentum scanner")
        return 1
    init_tables()

    # UI kill-switch — when the user has toggled the scanner OFF in
    # the panel, exit before any Alpaca calls / DB writes / Telegram.
    if not get_config().get("enabled", True):
        log.info("scanner disabled in UI — skipping")
        return 0

    now_et = _et_now()
    force = os.environ.get(_FORCE_RUN_ENV, "").lower() in ("1", "true", "yes")
    if not _market_is_open(now_et) and not force:
        log.info("market closed (%s ET) — skipping",
                 now_et.strftime("%a %H:%M"))
        return 0

    today = now_et.strftime("%Y-%m-%d")
    cfg = get_config()
    log.info(
        "config: pct_change>=%.2f, rvol>=%.2fx (lookback=%d), "
        "new %d-day high, vol/mcap>=%.3f%%",
        cfg["pct_change_min"], cfg["rvol_min"], cfg["rvol_lookback"],
        cfg["high_lookback"], cfg["vol_mcap_min"],
    )

    t0 = time.time()
    baseline = _load_universe_baseline(
        today, cfg["rvol_lookback"], cfg["high_lookback"],
    )
    if not baseline:
        log.warning("no eligible tickers in baseline — nothing to scan")
        return 0

    # Skip tickers that have already fired today — cheap pre-filter that
    # also avoids re-sending Telegram if the cron retries.
    fired_today = fired_tickers_for_date(today)
    to_fetch = [t for t in baseline.keys() if t not in fired_today]
    if not to_fetch:
        log.info("all eligible tickers already fired today (%d) — done",
                 len(fired_today))
        return 0
    log.info("baseline=%d, already-fired=%d, to-fetch=%d (took %.1fs)",
             len(baseline), len(fired_today), len(to_fetch), time.time() - t0)

    t1 = time.time()
    today_bars = _fetch_today_bars(to_fetch, today)
    log.info("fetched today-bars for %d/%d tickers in %.1fs",
             len(today_bars), len(to_fetch), time.time() - t1)
    if not today_bars:
        log.info("no live bars returned — market may have just opened")
        return 0

    fired = 0
    failed_telegrams = 0
    for ticker, today_bar in today_bars.items():
        b = baseline.get(ticker)
        if not b:
            continue
        m = _evaluate_one(b, today_bar, cfg)
        if not m:
            continue
        details = _format_details(m, cfg)
        if not record_alert(today, ticker, m, details):
            continue   # someone else inserted it first
        # Enrichment is best-effort. Both functions swallow exceptions
        # and return None / {} on failure so a flaky upstream can't
        # block the Telegram send.
        import enrich
        insider = enrich.last_insider_transaction(ticker)
        fund = enrich.fundamentals(ticker)
        msg = _format_telegram(ticker, m, cfg, insider=insider, fund=fund)
        try:
            ok = alerts_mod.send_telegram(msg)
            if not ok:
                failed_telegrams += 1
        except Exception as exc:
            failed_telegrams += 1
            log.warning("telegram send failed for %s: %s", ticker, exc)
        fired += 1
        log.info(
            "FIRED %s @ $%.2f (+%.2f%% RVOL %.1fx vol/float %.3f%%)",
            ticker, m["price"], m["pct_change"], m["rvol"], m["vol_mcap_pct"],
        )

    log.info(
        "scan complete — %d new alert(s), %d telegram failure(s), total %.1fs",
        fired, failed_telegrams, time.time() - t0,
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    sys.exit(run())
