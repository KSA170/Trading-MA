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
DEFAULT_MCAP_MIN_M:     float = 250.0       # $M — drop micro-caps below this
DEFAULT_MCAP_MAX_M:     float = 5_000_000.0  # $M (= $5T) — drop mega-caps above this

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
-- Market-cap band, stored in $millions for readable UI inputs.
-- Default 250 (= $250M) → 5,000,000 (= $5T) drops microcaps and
-- caps the very top of mega-cap so the scanner stays focused on
-- the mid-to-large-cap band where reproducible momentum lives.
ALTER TABLE momentum_scanner_config
    ADD COLUMN IF NOT EXISTS mcap_min_m REAL;
ALTER TABLE momentum_scanner_config
    ADD COLUMN IF NOT EXISTS mcap_max_m REAL;

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
-- Soft-delete column for "Clear selected / Clear all" in the panel.
-- Hidden rows still satisfy the dedupe check (fired_tickers_for_date
-- + already_fired_today) so the scanner won't re-fire a ticker the
-- user has explicitly cleared; only the UI hides them from view.
ALTER TABLE momentum_scanner_alerts
    ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT FALSE;
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
        "mcap_min_m":     DEFAULT_MCAP_MIN_M,
        "mcap_max_m":     DEFAULT_MCAP_MAX_M,
        "enabled":        True,
    }
    if not snapshots.enabled():
        return cfg
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT pct_change_min, rvol_min, rvol_lookback, "
                "high_lookback, vol_mcap_min, enabled, "
                "mcap_min_m, mcap_max_m "
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
    if row[6] is not None: cfg["mcap_min_m"]     = float(row[6])
    if row[7] is not None: cfg["mcap_max_m"]     = float(row[7])
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
    mcap_min_m: float, mcap_max_m: float,
) -> bool:
    if not snapshots.enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO momentum_scanner_config "
                "(id, pct_change_min, rvol_min, rvol_lookback, "
                "high_lookback, vol_mcap_min, mcap_min_m, mcap_max_m, "
                "updated_at) "
                "VALUES (1, %s, %s, %s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET "
                "pct_change_min = EXCLUDED.pct_change_min, "
                "rvol_min       = EXCLUDED.rvol_min, "
                "rvol_lookback  = EXCLUDED.rvol_lookback, "
                "high_lookback  = EXCLUDED.high_lookback, "
                "vol_mcap_min   = EXCLUDED.vol_mcap_min, "
                "mcap_min_m     = EXCLUDED.mcap_min_m, "
                "mcap_max_m     = EXCLUDED.mcap_max_m, "
                "updated_at = now()",
                (float(pct_change_min), float(rvol_min),
                 int(rvol_lookback), int(high_lookback),
                 float(vol_mcap_min),
                 float(mcap_min_m), float(mcap_max_m)),
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


# --- today's in-progress daily bar ----------------------------------------
#
# Two implementations, dispatched at the bottom by env var:
#
#   _fetch_today_bars_yahoo  (default) — yfinance / Yahoo's quote feed.
#       FREE. Returns SIP-consolidated cumulative volume, so RVOL math
#       reflects what's actually traded across the consolidated tape.
#       Slower per scan (~2-3 min for 5k tickers) and Yahoo can be
#       flaky, but the volume numbers are right.
#
#   _fetch_today_bars_alpaca_iex — Alpaca with `feed=iex`.
#       Fast (<60s for 5k tickers) but only reports IEX-attributed
#       trades, typically 2-3% of a NYSE/NASDAQ name's total volume.
#       That severely under-counts intraday cumulative volume → RVOL
#       barely moves off zero during the day → almost no alerts fire.
#       Use only when an Algo Trader Plus subscription is in place
#       (then the feed can be switched to "sip" in alerts.py).
#
# Switch via env var MOMENTUM_BARS_FEED=alpaca on the cron runner.

def _fetch_today_bars_alpaca_iex(symbols: list[str], today_str: str) -> dict[str, dict]:
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


def _fetch_today_bars_yahoo(symbols: list[str], today_str: str) -> dict[str, dict]:
    """Free Yahoo Finance source for the in-progress daily bar.
    Replaces Alpaca's IEX-only intraday feed which only reports trades
    routed through IEX (~2-3% of a NYSE/NASDAQ large-cap's volume) and
    therefore under-counts today's cumulative volume by 30-50x.

    yfinance.download() handles Yahoo's auth/crumb dance internally and
    parallelises symbol requests across a thread pool, so a 5k-ticker
    universe completes in 2-3 min. Tickers Yahoo doesn't recognise, or
    that have no trades on `today_str`, are silently dropped — same
    contract as the Alpaca variant.

    Returns {ticker: {c, h, v}} keyed by the caller's original symbols.
    Our universe already uses hyphens for share classes (BRK-B) which
    matches Yahoo's convention, so no symbol translation is needed."""
    if not symbols:
        return {}
    import yfinance as yf
    import pandas as pd

    out: dict[str, dict] = {}
    chunk = 200
    for i in range(0, len(symbols), chunk):
        batch = symbols[i:i + chunk]
        try:
            df = yf.download(
                tickers=" ".join(batch),
                period="2d",          # in-progress today + yesterday
                interval="1d",
                progress=False,
                auto_adjust=False,
                threads=True,
                group_by="ticker",
            )
        except Exception as exc:
            log.warning(
                "yahoo batch %d-%d (%d symbols) failed: %s",
                i, i + len(batch), len(batch), exc,
            )
            continue
        if df is None or df.empty:
            continue

        # Single-ticker call returns a flat OHLCV frame (no MultiIndex);
        # multi-ticker returns columns indexed by (ticker, field).
        is_multi = isinstance(df.columns, pd.MultiIndex)
        for sym in batch:
            try:
                sub = df[sym] if is_multi else df
            except (KeyError, ValueError):
                continue
            if sub is None or sub.empty:
                continue
            try:
                last_idx = sub.index[-1]
                last_date = (last_idx.strftime("%Y-%m-%d")
                             if hasattr(last_idx, "strftime")
                             else str(last_idx)[:10])
            except Exception:
                continue
            if last_date != today_str:
                # Either Yahoo's most-recent bar is yesterday's (no
                # trades today yet) or the symbol is stale — skip.
                continue
            try:
                row = sub.iloc[-1]
                close = float(row["Close"])
                high  = float(row["High"])
                vol   = float(row["Volume"])
            except (KeyError, ValueError, TypeError):
                continue
            if not (close > 0 and vol > 0):
                continue
            out[sym] = {"c": close, "h": high, "v": vol}
    return out


def _fetch_today_bars(symbols: list[str], today_str: str) -> dict[str, dict]:
    """Dispatch to the configured intraday data source. Defaults to
    Yahoo (free, SIP-consolidated volume). Set MOMENTUM_BARS_FEED=alpaca
    on the cron runner once an Algo Trader Plus subscription is active
    and `feed=iex` has been changed to `feed=sip` in alerts.py."""
    src = os.environ.get("MOMENTUM_BARS_FEED", "yahoo").strip().lower()
    if src == "alpaca":
        return _fetch_today_bars_alpaca_iex(symbols, today_str)
    return _fetch_today_bars_yahoo(symbols, today_str)


# --- per-ticker evaluation -------------------------------------------------

def _evaluate_one(baseline: dict, today_bar: dict, cfg: dict) -> dict | None:
    """Compute all metrics for one ticker. Returns the metrics dict if
    every filter passes, else None."""
    try:
        last_price  = float(today_bar.get("c") or 0)
        today_high  = float(today_bar.get("h") or 0)
        today_vol   = float(today_bar.get("v") or 0)
    except (TypeError, ValueError):
        return None
    if last_price <= 0 or today_vol <= 0:
        return None

    prior_close = baseline["prior_close"]
    shares      = baseline["shares"]
    pct_change  = (last_price / prior_close - 1.0) * 100.0
    rvol        = today_vol / baseline["avg_vol"]
    vol_mcap    = (today_vol / shares) * 100.0
    mcap_m      = (shares * last_price) / 1e6   # $M, matches UI unit
    new_high_ok = today_high > baseline["high_n"]

    if pct_change < cfg["pct_change_min"]:   return None
    if rvol       < cfg["rvol_min"]:         return None
    if not new_high_ok:                      return None
    if vol_mcap   < cfg["vol_mcap_min"]:     return None
    if mcap_m < cfg.get("mcap_min_m", DEFAULT_MCAP_MIN_M): return None
    if mcap_m > cfg.get("mcap_max_m", DEFAULT_MCAP_MAX_M): return None

    return {
        "price":        last_price,
        "today_high":   today_high,
        "today_vol":    today_vol,
        "avg_vol":      baseline["avg_vol"],   # denominator used for rvol
        "prior_close":  prior_close,
        "prior_high_n": baseline["high_n"],
        "pct_change":   pct_change,
        "rvol":         rvol,
        "vol_mcap_pct": vol_mcap,
        "mcap_m":       mcap_m,
    }


# --- single-ticker diagnose (mirrors run() per-ticker exactly) ------------

def diagnose(ticker: str, as_of: str | None = None,
             cfg: dict | None = None) -> dict:
    """Dry-run the same pipeline a real scan would for one ticker:
    look up the latest snapshot row, derive the baseline, fetch the
    live Alpaca bar, and compute all four metrics. Returns a
    pass/fail breakdown per filter plus the reason no alert would
    fire (eligibility miss, missing data, or already-fired-today).

    `as_of` (YYYY-MM-DD) flips into historical mode — the "today"
    bar is sourced from the snapshot's recent_bars instead of
    Alpaca, so you can ask "would BTU have fired 3 days ago?".
    Historical mode only sees EOD closes; a real intraday scan
    could have fired on a peak that the close didn't preserve.

    Designed so the UI can answer "why didn't I see BTU?" without
    waiting for the next cron tick."""
    if cfg is None:
        cfg = get_config()
    ticker = (ticker or "").strip().upper()
    is_historical = bool((as_of or "").strip())
    out: dict = {
        "ticker": ticker,
        "mode": "historical" if is_historical else "live",
        "source": None,
        "config": {
            "pct_change_min": float(cfg["pct_change_min"]),
            "rvol_min":       float(cfg["rvol_min"]),
            "rvol_lookback":  int(cfg["rvol_lookback"]),
            "high_lookback":  int(cfg["high_lookback"]),
            "vol_mcap_min":   float(cfg["vol_mcap_min"]),
            "mcap_min_m":     float(cfg.get("mcap_min_m", DEFAULT_MCAP_MIN_M)),
            "mcap_max_m":     float(cfg.get("mcap_max_m", DEFAULT_MCAP_MAX_M)),
            "enabled":        bool(cfg.get("enabled", True)),
        },
        "is_us": _is_us_ticker(ticker) if ticker else False,
        "in_snapshot": False,
        "as_of_baseline": None,
        "today": None,
        "available_dates": [],
        "already_fired": False,
        "baseline": None,
        "today_bar": None,
        "filters": [],
        "passes_all": False,
        "reason": None,
    }
    if not ticker:
        out["reason"] = "ticker required"
        return out
    if not snapshots.enabled():
        out["reason"] = "DATABASE_URL not set — snapshot required"
        return out
    if not out["is_us"]:
        out["reason"] = "not a US ticker (scanner is US-only — TSX/TSXV filtered upstream)"
        return out

    dates = snapshots.available_dates(1)
    if not dates:
        out["reason"] = "no snapshot data available — nightly job hasn't run"
        return out
    snap_as_of = dates[0]
    out["as_of_baseline"] = snap_as_of

    snap_row = None
    for _t, row in snapshots.iter_for_date(snap_as_of, tickers=[ticker]):
        snap_row = row
        break
    if snap_row is None:
        out["reason"] = (
            f"ticker not in {snap_as_of} snapshot — outside the screened "
            f"universe, or the nightly job skipped it"
        )
        return out
    out["in_snapshot"] = True

    bars = _bars_from_row(snap_row)
    if not bars:
        out["reason"] = "snapshot row has no recent_bars — can't derive prior baseline"
        return out

    # Populate the UI dropdown — last 5 completed-session bar dates,
    # strictly before today's ET date so every option is a finished day.
    today_et = _et_now().strftime("%Y-%m-%d")
    bar_dates_sorted = sorted(
        {b.get("d") for b in bars if isinstance(b, dict) and b.get("d")},
        reverse=True,
    )
    out["available_dates"] = [d for d in bar_dates_sorted if d < today_et][:5]

    target_date = (as_of or "").strip() if is_historical else today_et
    out["today"] = target_date
    if is_historical and target_date not in bar_dates_sorted:
        out["reason"] = (
            f"no snapshot bar for {target_date} — not a trading day, "
            f"or outside the snapshot's {len(bars)}-bar history window"
        )
        return out

    shares = snap_row.get("shares")
    if shares is None or float(shares) <= 0:
        out["reason"] = "snapshot row has no shares-outstanding — can't compute vol/float"
        return out
    prior_bars = [
        b for b in bars
        if isinstance(b, dict) and (b.get("d") or "9999-12-31") < target_date
    ]
    need = max(int(cfg["rvol_lookback"]), int(cfg["high_lookback"]), 1)
    if len(prior_bars) < need:
        out["reason"] = (
            f"only {len(prior_bars)} prior bars before {target_date} — "
            f"need {need} for the configured lookbacks "
            f"(rvol={int(cfg['rvol_lookback'])}, high={int(cfg['high_lookback'])})"
        )
        return out
    try:
        prior_close = float(prior_bars[-1].get("c") or 0)
        vol_window  = prior_bars[-int(cfg["rvol_lookback"]):]
        avg_vol     = float(np.mean([float(b.get("v") or 0) for b in vol_window]))
        high_window = prior_bars[-int(cfg["high_lookback"]):]
        high_n      = max(float(b.get("h") or 0) for b in high_window)
    except (TypeError, ValueError) as exc:
        out["reason"] = f"baseline numeric parse failed: {exc}"
        return out
    if prior_close <= 0 or avg_vol <= 0 or high_n <= 0:
        out["reason"] = (
            f"baseline non-positive (prior_close={prior_close}, "
            f"avg_vol={avg_vol:.0f}, high_n={high_n})"
        )
        return out
    out["baseline"] = {
        "prior_close": prior_close,
        "avg_vol":     avg_vol,
        "high_n":      high_n,
        "shares":      float(shares),
    }
    out["already_fired"] = already_fired_today(target_date, ticker)

    # Decide where the "today" bar comes from.
    #   - historical: always from the snapshot (the only source we have)
    #   - live + snapshot has today's bar: from the snapshot (the
    #     nightly job at close+1hr has already written it, so an
    #     Alpaca call here would be redundant — and probably fail
    #     after-hours anyway)
    #   - live + snapshot doesn't yet have today: from Alpaca (we're
    #     mid-session; live in-progress bar is the right source)
    today_in_snapshot = any(
        isinstance(b, dict) and b.get("d") == target_date for b in bars
    )
    if is_historical or today_in_snapshot:
        source = "snapshot"
    else:
        # Live mode → which intraday feed the scanner is currently
        # configured to use. Surface it so the user can tell whether
        # they're looking at IEX-only or SIP-consolidated volume.
        feed = os.environ.get("MOMENTUM_BARS_FEED", "yahoo").strip().lower()
        source = "alpaca-iex" if feed == "alpaca" else "yahoo"
    out["source"] = source

    if source == "snapshot":
        today_bar = None
        for b in bars:
            if isinstance(b, dict) and b.get("d") == target_date:
                today_bar = {"c": b.get("c"), "h": b.get("h"), "v": b.get("v")}
                break
        if not today_bar:
            out["reason"] = f"snapshot has no bar for {target_date}"
            return out
    else:
        today_bars = _fetch_today_bars([ticker], target_date)
        today_bar = today_bars.get(ticker)
        if not today_bar:
            out["reason"] = (
                "no live bar from Alpaca for today — market may not have "
                "opened yet, ticker is halted, or it isn't on Alpaca's feed"
            )
            return out
    try:
        last_price = float(today_bar.get("c") or 0)
        today_high = float(today_bar.get("h") or 0)
        today_vol  = float(today_bar.get("v") or 0)
    except (TypeError, ValueError) as exc:
        out["reason"] = f"bar numeric parse failed: {exc}"
        return out
    if last_price <= 0 or today_vol <= 0:
        out["reason"] = (
            f"bar has zero price or volume "
            f"(price={last_price}, vol={today_vol:.0f})"
        )
        return out
    out["today_bar"] = {
        "price":      last_price,
        "today_high": today_high,
        "today_vol":  today_vol,
    }

    pct_change = (last_price / prior_close - 1.0) * 100.0
    rvol       = today_vol / avg_vol
    vol_mcap   = (today_vol / float(shares)) * 100.0
    mcap_m     = (float(shares) * last_price) / 1e6
    mcap_min_m = float(cfg.get("mcap_min_m", DEFAULT_MCAP_MIN_M))
    mcap_max_m = float(cfg.get("mcap_max_m", DEFAULT_MCAP_MAX_M))

    out["filters"] = [
        {"name": "pct_change",
         "label": "% change vs prior close",
         "threshold": float(cfg["pct_change_min"]),
         "measured":  pct_change,
         "unit": "%",
         "passes": pct_change >= float(cfg["pct_change_min"])},
        {"name": "rvol",
         "label": f"Relative volume ({int(cfg['rvol_lookback'])}-day avg)",
         "threshold": float(cfg["rvol_min"]),
         "measured":  rvol,
         "unit": "x",
         "passes": rvol >= float(cfg["rvol_min"])},
        {"name": "new_high",
         "label": f"New {int(cfg['high_lookback'])}-day high",
         "threshold": high_n,
         "measured":  today_high,
         "unit": "$",
         "passes": today_high > high_n},
        {"name": "vol_mcap",
         "label": "Today's vol / shares outstanding",
         "threshold": float(cfg["vol_mcap_min"]),
         "measured":  vol_mcap,
         "unit": "%",
         "passes": vol_mcap >= float(cfg["vol_mcap_min"])},
        {"name": "mcap_band",
         "label": "Market cap (shares × price)",
         "threshold":     mcap_min_m,
         "threshold_max": mcap_max_m,
         "measured":      mcap_m,
         "unit": "M$",
         "passes": mcap_min_m <= mcap_m <= mcap_max_m},
    ]
    out["passes_all"] = all(f["passes"] for f in out["filters"])
    if out["passes_all"] and out["already_fired"]:
        out["reason"] = (
            f"would have fired — but an alert already fired for this "
            f"ticker on {target_date}"
            if source == "snapshot"
            else "would fire — but an alert for this ticker already fired "
                 "earlier today (one alert per ticker per day)"
        )
    elif out["passes_all"]:
        out["reason"] = (
            f"EOD close on {target_date} passed all filters — a live scan "
            f"that day would have fired (or earlier on an intraday peak)"
            if source == "snapshot"
            else "passes all filters — would fire on next scan"
        )
    else:
        failed = [f["label"] for f in out["filters"] if not f["passes"]]
        out["reason"] = "fails: " + "; ".join(failed)
    return out


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
    table), newest first. Hidden rows (soft-deleted via the UI's
    Clear button) are filtered out — the underlying row stays in the
    table so dedupe still works, but it doesn't show up here."""
    if not snapshots.enabled():
        return []
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            if alert_date:
                cur.execute(
                    "SELECT alert_date, ticker, fired_at, price, pct_change, "
                    "rvol, vol_mcap_pct, new_high, details "
                    "FROM momentum_scanner_alerts "
                    "WHERE alert_date = %s AND hidden = FALSE "
                    "ORDER BY fired_at DESC", (alert_date,),
                )
            else:
                # MAX() over the unhidden subset — if every row for
                # today is hidden, fall back to the most recent date
                # that still has visible rows.
                cur.execute(
                    "SELECT alert_date, ticker, fired_at, price, pct_change, "
                    "rvol, vol_mcap_pct, new_high, details "
                    "FROM momentum_scanner_alerts "
                    "WHERE hidden = FALSE AND alert_date = ("
                    "  SELECT MAX(alert_date) FROM momentum_scanner_alerts "
                    "  WHERE hidden = FALSE"
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


def hide_alerts(alert_date: str | None = None,
                tickers: list[str] | None = None) -> int:
    """Soft-delete rows the user has cleared from the panel. The row
    stays in momentum_scanner_alerts so dedupe still works — only
    the visibility flag flips. Returns the number of rows hidden.

    - `tickers` empty / None  → hide every row for `alert_date`.
    - `alert_date` empty / None → use the most recent date with any
      visible rows (matches alerts_for_date's default)."""
    if not snapshots.enabled():
        return 0
    norm_tickers = [t.strip().upper() for t in (tickers or []) if t and t.strip()]
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            if alert_date:
                date_clause = "alert_date = %s"
                date_args: tuple = (alert_date,)
            else:
                # Resolve the latest date that still has visible rows
                # at SQL time so the UI and the hide call agree.
                date_clause = (
                    "alert_date = (SELECT MAX(alert_date) "
                    "FROM momentum_scanner_alerts WHERE hidden = FALSE)"
                )
                date_args = ()
            if norm_tickers:
                cur.execute(
                    "UPDATE momentum_scanner_alerts SET hidden = TRUE "
                    f"WHERE {date_clause} AND ticker = ANY(%s) "
                    "AND hidden = FALSE",
                    (*date_args, norm_tickers),
                )
            else:
                cur.execute(
                    "UPDATE momentum_scanner_alerts SET hidden = TRUE "
                    f"WHERE {date_clause} AND hidden = FALSE",
                    date_args,
                )
            return cur.rowcount or 0
    except Exception as exc:
        log.warning("scanner_momentum.hide_alerts failed: %s", exc)
        return 0


# --- Telegram --------------------------------------------------------------

_VERDICT_MAX_SCORE = 14
# Tuned so a "barely passes thresholds" alert lands in PASS, a typical
# good setup with one supportive enrichment lands in WATCH, and a strong
# setup with multiple supportive signals lands in BUY.
_VERDICT_BUY_MIN   = 9
_VERDICT_WATCH_MIN = 5
_VERDICT_INSIDER_RECENT_DAYS = 60   # only count Form 4s newer than this


def _fmt_compact_vol(v: float) -> str:
    """Compact share-count formatter — '12.0M', '350K', '8.4B'."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    a = abs(n)
    if a >= 1e9: return f"{n/1e9:.1f}B"
    if a >= 1e6: return f"{n/1e6:.1f}M"
    if a >= 1e3: return f"{n/1e3:.0f}K"
    return f"{int(n):,}"


def _insider_is_recent(insider: dict | None,
                       max_age_days: int = _VERDICT_INSIDER_RECENT_DAYS) -> bool:
    """True only when the insider transaction is within max_age_days.
    Older Form 4s still display on the alert (still useful context) but
    don't count toward the verdict — a 6-month-old buy says nothing
    about the current move."""
    if not insider:
        return False
    raw = insider.get("transaction_date") or insider.get("filing_date")
    if not raw:
        return False
    try:
        d = datetime.strptime(raw, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    age_days = (datetime.utcnow() - d).days
    return 0 <= age_days <= max_age_days


def compute_verdict(m: dict,
                    insider: dict | None,
                    news: list[dict] | None,
                    intel: dict | None = None) -> dict:
    """Score the alert across pct_change, RVOL, vol-of-float, insider
    activity, and catalyst news. Output: {label, glyph, score, max}
    where label is BUY / WATCH / PASS.

    Every alert that reaches this function has already cleared the four
    filters; the verdict measures how far ABOVE the thresholds the
    setup actually sits and whether enrichment supports a high-
    conviction call."""
    score = 0

    pct = float(m.get("pct_change") or 0)
    if   pct >= 15: score += 3
    elif pct >= 8:  score += 2
    elif pct >= 5:  score += 1

    rvol = float(m.get("rvol") or 0)
    if   rvol >= 10: score += 3
    elif rvol >= 5:  score += 2
    elif rvol >= 2.5: score += 1

    vmp = float(m.get("vol_mcap_pct") or 0)
    if   vmp >= 3:   score += 3
    elif vmp >= 1:   score += 2
    elif vmp >= 0.5: score += 1

    # New high is one of the four filter gates, so it's always true
    # by the time we get here — still counts as positive evidence
    # rather than a constant offset, to keep the score interpretable.
    score += 1

    if _insider_is_recent(insider):
        code = (insider.get("code") or "").upper()
        if code == "P":   score += 2     # open-market BUY
        elif code == "S": score -= 1     # SELL drags the verdict

    n_news = len(news or [])
    if   n_news >= 2: score += 2
    elif n_news >= 1: score += 1

    # Optional market-intel band (analyst/target/fundamentals/news
    # sentiment). No-op unless intel is present, so the default path and
    # the displayed /max are unchanged; a broadly bullish backdrop nudges
    # a borderline setup up, a weak one nudges it down.
    max_score = _VERDICT_MAX_SCORE
    if intel and intel.get("score") is not None:
        import market_intel
        max_score += 2
        score += market_intel.band(intel, 2, 1, -1)

    if score >= _VERDICT_BUY_MIN:
        label, glyph = "BUY", "🟢"
    elif score >= _VERDICT_WATCH_MIN:
        label, glyph = "WATCH", "🟡"
    else:
        label, glyph = "PASS", "🔴"
    return {"label": label, "glyph": glyph,
            "score": score, "max": max_score}


def _format_telegram(ticker: str, m: dict, cfg: dict,
                     insider: dict | None = None,
                     fund: dict | None = None,
                     news: list[dict] | None = None,
                     when: "datetime | None" = None,
                     intel: dict | None = None) -> str:
    """Build the HTML Telegram body in the shared tg_format style:
    header (category — ticker / company / time) → a vertical block of
    label:value metric rows with severity callouts → enrichment rows
    (insider / fundamentals / catalysts) → verdict footer."""
    import enrich
    import tickers as _tickers
    import tg_format as T
    # Prefer the SEC-sourced local name over yfinance's .info["longName"]
    # (yfinance returns wrong/stale names for delisted/recycled tickers).
    local_name = _tickers.company_name(ticker)
    name = (local_name
            if local_name and local_name.upper() != ticker.upper()
            else (fund or {}).get("name"))
    today_vol = _fmt_compact_vol(m.get("today_vol") or 0)
    avg_vol   = _fmt_compact_vol(m.get("avg_vol") or 0)
    rvol_lb   = int(cfg.get("rvol_lookback", 20))

    pct = m.get("pct_change")
    rvol = m.get("rvol")
    vmp = m.get("vol_mcap_pct")

    lines = T.header("LIVE ALERT", ticker, name=name, when=T.time_et(when))
    lines += [
        T.row("💰", "Price", T.b(T.money(m.get("price")))),
        T.severity_row("📊", "Change",
                       T.b(T.signed_pct(pct)) + " today",
                       T.pct_change_level(pct)),
        T.severity_row("🔥", f"RVOL({rvol_lb})",
                       T.b(T.multiple(rvol)) + f" <i>({today_vol} ÷ {avg_vol} {rvol_lb}d avg)</i>",
                       T.rvol_level(rvol)),
        T.severity_row("🌊", "Vol/Float",
                       T.b(T.signed_pct(vmp, 2).lstrip("+")),
                       T.vol_float_level(vmp)),
        T.row("🎯", f"New {cfg['high_lookback']}-day high",
              f"prior {T.money(m.get('prior_high_n'))}"),
    ]
    lines += T.fundamentals_rows(fund)
    lines.append(T.insider_row(insider))
    import market_intel
    intel_row = market_intel.summary_row(intel)
    if intel_row:
        lines.append(T.row("🧠", "Intel", intel_row))
    news_block = enrich.format_news_block(news)
    if news_block:
        lines.append("")
        lines.append(news_block)
    # Verdict footer.
    v = compute_verdict(m, insider, news, intel=intel)
    lines.append("")
    lines.append(
        f"🧭 <b>Verdict:</b> {v['glyph']} <b>{v['label']}</b> "
        f"<i>({v['score']}/{v['max']})</i>"
    )
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
        "new %d-day high, vol/mcap>=%.3f%%, mcap=$%.0fM-$%.0fM",
        cfg["pct_change_min"], cfg["rvol_min"], cfg["rvol_lookback"],
        cfg["high_lookback"], cfg["vol_mcap_min"],
        cfg["mcap_min_m"], cfg["mcap_max_m"],
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
        import outcomes as _outcomes
        _outcomes.record_stock_outcome(
            ticker, today, m.get("price"),
            {"kind": "momentum_scan", "id": None,
             "label": "Momentum scanner"},
        )
        # Enrichment is best-effort. Every function swallows exceptions
        # and returns None / {} / [] on failure so a flaky upstream
        # can't block the Telegram send.
        import enrich
        import market_intel
        insider = enrich.last_insider_transaction(ticker)
        fund = enrich.fundamentals(ticker)
        news = enrich.recent_news(ticker)
        # Optional intel (Alpha Vantage) — None unless INTEL_ENABLED + key.
        intel = market_intel.conviction_for(
            ticker, price=m.get("price"), insider=insider)
        msg = _format_telegram(ticker, m, cfg, insider=insider, fund=fund,
                               news=news, when=now_et, intel=intel)
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
