"""
Screener for US/Canadian stocks. Each filter is independently toggleable;
when disabled the criterion is skipped but the value is still reported.

Default filters (all enabled):
  - Previous close set a new N-day high (default 30)
  - Daily RSI(14) inside [rsi_min, rsi_max] (default 45-50)
  - RSI(14) deviation vs its own 9-day SMA within [-5%, +5%]
  - Relative volume over the trailing N days greater than threshold
    (default 10-day, > 0.5)
  - Price range (default $1 - $1000)

Universe is selected via list keys: 'sp500', 'dow', 'nasdaq100', 'tsx'.

Data source: yfinance (Yahoo Finance public endpoints).
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Iterable

try:
    from zoneinfo import ZoneInfo  # py3.9+
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

import numpy as np
import pandas as pd
import yfinance as yf

from tickers import all_tickers, display_symbol, lists_for, list_labels, universe as build_universe

log = logging.getLogger("screener")


@dataclass
class ScreenHit:
    ticker: str
    name: str
    exchange: str
    lists: list[str]
    list_labels: list[str]
    as_of_date: str
    close: float
    prev_close: float
    pct_change: float
    high_lookback: float
    rsi: float
    rsi_sma9: float
    rsi_dev_pct: float
    ema21: float
    price_ema21_dev_pct: float
    ema50: float
    ema21_ema50_dev_pct: float
    macd: float
    macd_signal: float
    macd_hist: float
    macd_hist_prev: float
    rel_volume: float
    avg_volume: float
    volume: float
    shares: float | None
    market_cap: float | None
    turnover_pct: float | None
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


# --- indicator helpers -----------------------------------------------------

def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    """Classic Wilder RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder's smoothing == EMA with alpha = 1/period
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


# --- data fetching ---------------------------------------------------------
#
# Two-layer cache:
#  1. Disk: one small pickled DataFrame per ticker in .cache/prices/. Lives
#     ~20h (one trading day), so a "warm cache" run done after market close
#     covers the rest of the day's screens without re-fetching from Yahoo.
#     This is what makes the screen reusable and keeps peak RAM bounded
#     (the screen worker reads one ticker's frame at a time off disk).
#  2. In-memory: a small LRU (~2k entries) for hot tickers — covers the
#     ticker hover-chart workflow right after a screen.
#
# Together, the disk cache makes a fresh screen run cost only the cumulative
# disk-read time (a few seconds for the full universe), and a warm-cache
# button does the slow Yahoo fetch up front so it doesn't happen inside the
# /api/screen request.

_CACHE_DIR = Path(__file__).resolve().parent / ".cache"
_PRICE_DIR = _CACHE_DIR / "prices"
_PRICE_FILE_TTL_SEC = 20 * 3600   # ~one trading day
_PRICE_TTL_SEC = 60 * 30          # in-memory TTL (intra-session)
_PRICE_CACHE_MAX = 2000           # tight cap; disk is the persistence layer

_PRICE_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_PRICE_CACHE_LOCK = threading.Lock()

# Only these columns are ever read by the screener / chart payload.
_KEEP_COLS = ("Open", "High", "Low", "Close", "Volume")


def _price_file(ticker: str) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_")
    return _PRICE_DIR / f"{safe}.pkl"


def cache_status(tickers: list[str]) -> dict:
    """Summarise the on-disk price cache for `tickers`. A ticker is "warm"
    if its pickle exists and is younger than _PRICE_FILE_TTL_SEC; "stale"
    if the file exists but is older; "missing" if no file at all."""
    now = time.time()
    warm = stale = missing = 0
    for t in tickers:
        pf = _price_file(t)
        try:
            mtime = pf.stat().st_mtime
        except FileNotFoundError:
            missing += 1
            continue
        except Exception:
            missing += 1
            continue
        if now - mtime < _PRICE_FILE_TTL_SEC:
            warm += 1
        else:
            stale += 1
    return {
        "total": len(tickers),
        "warm": warm,
        "stale": stale,
        "missing": missing,
    }


def _remember(ticker: str, ts: float, df: pd.DataFrame) -> None:
    """Put a ticker's frame into the in-memory LRU and evict overflow."""
    with _PRICE_CACHE_LOCK:
        _PRICE_CACHE[ticker] = (ts, df)
        if len(_PRICE_CACHE) > _PRICE_CACHE_MAX:
            # Drop the oldest 20% by insertion order — keeps the working set
            # warm without scanning on every insert.
            drop_n = _PRICE_CACHE_MAX // 5
            for old_key in list(_PRICE_CACHE.keys())[:drop_n]:
                _PRICE_CACHE.pop(old_key, None)


def _fetch_shares(ticker: str) -> float | None:
    """Best-effort fetch of shares outstanding via yfinance.fast_info.
    Returns None on any failure (missing data, network error, private
    company, etc). One Yahoo call per ticker — cheap, but only worth
    doing when the value isn't already cached in df.attrs."""
    try:
        fi = yf.Ticker(ticker).fast_info
    except Exception:
        return None
    for key in ("shares", "shares_outstanding", "sharesOutstanding"):
        try:
            val = fi[key] if hasattr(fi, "__getitem__") else getattr(fi, key, None)
        except Exception:
            val = None
        try:
            f = float(val) if val is not None else None
        except (TypeError, ValueError):
            f = None
        if f and f > 0 and np.isfinite(f):
            return f
    return None


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Precompute every indicator the screener filters on — EMA(21), EMA(50),
    RSI(14) + its 9d SMA, and MACD(12, 26, 9) — and store each as a
    float32 column. Moves all the expensive pandas ewm/rolling work to
    cache-build time so a screen run becomes a slice + filter pass."""
    closes = df["Close"]
    df["ema21"] = ema(closes, 21).astype("float32")
    df["ema50"] = ema(closes, 50).astype("float32")
    df["rsi14"] = rsi_wilder(closes, 14).astype("float32")
    df["rsi_sma9"] = df["rsi14"].rolling(window=9, min_periods=9).mean().astype("float32")
    macd_line = ema(closes, 12) - ema(closes, 26)
    macd_signal = ema(macd_line, 9)
    df["macd"] = macd_line.astype("float32")
    df["macd_signal"] = macd_signal.astype("float32")
    df["macd_hist"] = (macd_line - macd_signal).astype("float32")
    return df


def _cached_history(ticker: str, period: str = "6mo", need_shares: bool = False) -> pd.DataFrame | None:
    now = time.time()
    # 1. In-memory hot cache.
    cached = _PRICE_CACHE.get(ticker)
    if cached and now - cached[0] < _PRICE_TTL_SEC:
        df = cached[1]
        if need_shares and df.attrs.get("shares") is None:
            shares = _fetch_shares(ticker)
            if shares:
                df.attrs["shares"] = shares
                pf = _price_file(ticker)
                try:
                    df.to_pickle(pf)
                except Exception:
                    pass
        return df
    # 2. Disk cache — the once-per-day store.
    pf = _price_file(ticker)
    try:
        if pf.exists() and (now - pf.stat().st_mtime) < _PRICE_FILE_TTL_SEC:
            df = pd.read_pickle(pf)
            rewrite = False
            # Old cache files (pre-enrichment) lack the indicator columns.
            # Enrich in place and rewrite so we don't have to refetch.
            if "rsi14" not in df.columns:
                df = _enrich(df)
                rewrite = True
            # Shares attr was added later; backfill once on demand so the
            # turnover filter has data without waiting for the next warm.
            if need_shares and df.attrs.get("shares") is None:
                shares = _fetch_shares(ticker)
                if shares:
                    df.attrs["shares"] = shares
                    rewrite = True
            if rewrite:
                try:
                    df.to_pickle(pf)
                except Exception:
                    pass
            _remember(ticker, now, df)
            return df
    except Exception as exc:
        log.warning("price cache read failed for %s: %s", ticker, exc)
    # 3. Fresh fetch.
    try:
        yt = yf.Ticker(ticker)
        df = yt.history(period=period, interval="1d", auto_adjust=False)
    except Exception as exc:
        log.warning("history fetch failed for %s: %s", ticker, exc)
        return None
    if df is None or df.empty:
        return None
    df = df.dropna(subset=["Close", "Volume"])
    keep = [c for c in _KEEP_COLS if c in df.columns]
    df = df[keep].astype("float32")
    df = _enrich(df)
    # Fetch shares once per fresh fetch so the turnover filter has data
    # without an extra screen-time call. fast_info is a cheap Yahoo quote
    # call (~50ms); we tolerate failures (returns None).
    try:
        shares = _fetch_shares(ticker)
        if shares:
            df.attrs["shares"] = shares
    except Exception:
        pass
    try:
        _PRICE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_pickle(pf)
    except Exception as exc:
        log.warning("price cache write failed for %s: %s", ticker, exc)
    _remember(ticker, now, df)
    return df


# --- background "warm cache" job -------------------------------------------
# The user can kick off a warm of the whole universe to disk via the
# /api/admin/warm-cache endpoint; subsequent screen runs then read from
# disk instead of hammering Yahoo inside the request.

_warm_state: dict = {
    "running": False,
    "done": 0,
    "total": 0,
    "errors": 0,
    "cancelled": False,
    "started_at": None,
    "finished_at": None,
}
_warm_lock = threading.Lock()


def warm_status() -> dict:
    with _warm_lock:
        return dict(_warm_state)


def cancel_warm_cache() -> bool:
    """Ask the running warm thread to stop after the in-flight fetch.
    Returns True if a warm was running, False otherwise."""
    with _warm_lock:
        if not _warm_state["running"]:
            return False
        _warm_state["cancelled"] = True
        return True


def warm_cache(tickers: list[str] | None = None, max_workers: int = 12) -> bool:
    """Start a background fetch of `tickers` (or the full universe) into the
    disk price cache. Returns False if a warm job is already running."""
    with _warm_lock:
        if _warm_state["running"]:
            return False
        _warm_state.update(
            running=True, done=0, total=0, errors=0, cancelled=False,
            started_at=time.time(), finished_at=None,
        )

    def _run() -> None:
        try:
            tk = tickers if tickers is not None else all_tickers()
            with _warm_lock:
                _warm_state["total"] = len(tk)

            def _one(t: str) -> None:
                # Cancellation check — newly-started workers see the flag
                # and skip immediately. In-flight Yahoo fetches are allowed
                # to finish (they're already a few hundred ms each).
                with _warm_lock:
                    cancelled = _warm_state["cancelled"]
                if cancelled:
                    with _warm_lock:
                        _warm_state["done"] += 1
                    return
                try:
                    _cached_history(t)
                except Exception:
                    with _warm_lock:
                        _warm_state["errors"] += 1
                finally:
                    with _warm_lock:
                        _warm_state["done"] += 1

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for _ in pool.map(_one, tk):
                    pass
        except Exception as exc:
            log.warning("warm-cache job failed: %s", exc)
        finally:
            with _warm_lock:
                _warm_state["running"] = False
                _warm_state["finished_at"] = time.time()

    threading.Thread(target=_run, daemon=True, name="warm-cache").start()
    return True


# --- daily auto-warm scheduler ---------------------------------------------
# A daemon thread wakes every 30 minutes and triggers a warm if it's after
# the configured trigger time (default 4:30pm ET, US weekdays only) and we
# haven't already warmed today. Trigger time is overridable via the
# AUTO_WARM_AFTER_ET env var, e.g. "16:30" or "17:00". Set DISABLE_AUTO_WARM
# to "1" to turn the scheduler off.
#
# Caveat for free-tier hosts that idle the service after no traffic: the
# thread can only fire while the worker process is alive. An external ping
# near the trigger time (e.g. UptimeRobot hitting "/" at 4:25pm ET) keeps
# the service awake long enough for the auto-warm to kick in.

_AUTO_WARM_STATE: dict = {
    "last_run_date": None,   # YYYY-MM-DD of the last successful auto-trigger
    "next_check_at": None,   # unix ts of the next periodic check
    "trigger_time": "16:30",
    "started": False,
}
_auto_warm_lock = threading.Lock()


def _now_et() -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            pass
    # Fallback: treat server time as UTC and subtract 4h (closer to EDT than
    # EST). Not perfect across DST, but the warm only needs to fire roughly
    # after market close — minor offset is harmless.
    import datetime as _dt
    return datetime.utcnow() - _dt.timedelta(hours=4)


def _parse_trigger_time() -> dt_time:
    raw = os.environ.get("AUTO_WARM_AFTER_ET", "16:30").strip()
    try:
        hh, mm = raw.split(":")
        return dt_time(int(hh), int(mm))
    except Exception:
        return dt_time(16, 30)


def auto_warm_status() -> dict:
    with _auto_warm_lock:
        return dict(_AUTO_WARM_STATE)


def _auto_warm_loop() -> None:
    trigger = _parse_trigger_time()
    interval_sec = 30 * 60  # check every 30 minutes
    with _auto_warm_lock:
        _AUTO_WARM_STATE["trigger_time"] = trigger.strftime("%H:%M")
    log.info("auto-warm scheduler started (trigger %s ET, weekdays)", trigger.strftime("%H:%M"))
    while True:
        try:
            now = _now_et()
            today = now.strftime("%Y-%m-%d")
            already = False
            with _auto_warm_lock:
                already = _AUTO_WARM_STATE["last_run_date"] == today
                _AUTO_WARM_STATE["next_check_at"] = time.time() + interval_sec
            is_weekday = now.weekday() < 5
            is_after_trigger = now.time() >= trigger
            if is_weekday and is_after_trigger and not already and not warm_status()["running"]:
                log.info("auto-warm: triggering cache warm for %s", today)
                if warm_cache():
                    with _auto_warm_lock:
                        _AUTO_WARM_STATE["last_run_date"] = today
        except Exception as exc:
            log.warning("auto-warm loop error: %s", exc)
        time.sleep(interval_sec)


def start_auto_warm() -> None:
    """Start the daily auto-warm scheduler (idempotent). Honors
    DISABLE_AUTO_WARM env var."""
    if os.environ.get("DISABLE_AUTO_WARM"):
        log.info("auto-warm scheduler disabled by DISABLE_AUTO_WARM env var")
        return
    with _auto_warm_lock:
        if _AUTO_WARM_STATE["started"]:
            return
        _AUTO_WARM_STATE["started"] = True
    threading.Thread(target=_auto_warm_loop, daemon=True, name="auto-warm").start()


# Company names come from the SEC dataset (already loaded for the universe) —
# avoids a heavy per-match yfinance get_info() call. Falls back to the symbol.
_NAME_CACHE: dict[str, str] = {}


def _company_name(ticker: str) -> str:
    if ticker in _NAME_CACHE:
        return _NAME_CACHE[ticker]
    try:
        from tickers import company_name as _list_company_name
        name = _list_company_name(ticker) or ticker
    except Exception:
        name = ticker
    _NAME_CACHE[ticker] = name
    return name


# --- core screening --------------------------------------------------------

MAX_AS_OF_OFFSET = 20


def evaluate_ticker(
    ticker: str,
    high_lookback: int = 2,
    streak_mode: str = "high",
    rsi_period: int = 14,
    rsi_min: float = 45.0,
    rsi_max: float = 65.0,
    rsi_sma_period: int = 9,
    rsi_dev_min_pct: float = 0.0,
    rsi_dev_max_pct: float = 10.0,
    rvol_lookback: int = 10,
    rvol_min: float = 1.2,
    avg_volume_min: int = 50000,
    price_min: float = 1.0,
    price_max: float = 1000.0,
    ema_period: int = 21,
    ema_long_period: int = 50,
    price_dev_min_pct: float = -1.0,
    price_dev_max_pct: float = 4.0,
    ema_dev_min_pct: float = -3.0,
    ema_dev_max_pct: float = 3.0,
    macd_hist_min: float = 0.0,
    macd_require_rising: bool = True,
    turnover_min_pct: float = 0.0,
    turnover_max_pct: float = 100.0,
    apply_high: bool = True,
    apply_rsi: bool = True,
    apply_rsi_dev: bool = True,
    apply_rvol: bool = True,
    apply_avg_volume: bool = True,
    apply_price: bool = True,
    apply_price_dev: bool = True,
    apply_ema_dev: bool = True,
    apply_macd: bool = True,
    apply_turnover: bool = False,
    as_of_offset: int = 0,
) -> ScreenHit | None:
    if as_of_offset < 0:
        as_of_offset = 0
    if as_of_offset > MAX_AS_OF_OFFSET:
        as_of_offset = MAX_AS_OF_OFFSET

    df = _cached_history(ticker, period="6mo", need_shares=apply_turnover)
    needed = max(
        high_lookback + 2, rsi_period + 5, rvol_lookback + 2,
        ema_period + 2, ema_long_period + 2,
        # MACD(12,26,9) needs 26 + 9 = 35 bars for the signal line, plus 1
        # extra so we can compare today's hist vs yesterday's.
        26 + 9 + 2,
    ) + as_of_offset
    if df is None or len(df) < needed:
        return None

    closes = df["Close"]
    volumes = df["Volume"]

    # The "evaluation bar" is the close used for the prev_close gate. With
    # as_of_offset=0 it's the latest bar; offset=k pushes back k trading days.
    eval_idx = -(1 + as_of_offset)
    prior_idx = eval_idx - 1
    eval_date = df.index[eval_idx].strftime("%Y-%m-%d")

    prev_close = float(closes.iloc[eval_idx])
    prior_close = float(closes.iloc[prior_idx])
    volume = float(volumes.iloc[eval_idx])

    # Price-range filter (applied first - cheapest gate)
    if apply_price and not (price_min <= prev_close <= price_max):
        return None

    # Streak check. `streak_mode` decides what makes a streak:
    #   "high"        — each bar's high  strictly above the prior bar's high
    #   "close"       — each bar's close strictly above the prior bar's close
    #   "green"       — each bar closes above its own open (green candle)
    #   "close_green" — both of the above: each bar closes above the prior
    #                   bar's close AND above its own open.
    # high / close / close_green all compare N+1 bars (N day-over-day diffs);
    # green / close_green also use the N bars' opens.
    if streak_mode == "green":
        g_start = eval_idx - high_lookback + 1
        if eval_idx + 1 < 0:
            open_win = df["Open"].iloc[g_start:eval_idx + 1]
            close_win = closes.iloc[g_start:eval_idx + 1]
        else:
            open_win = df["Open"].iloc[g_start:]
            close_win = closes.iloc[g_start:]
        if len(close_win) < high_lookback:
            return None
        streak_ok = bool((close_win.values > open_win.values).all())
        eval_streak_val = float(close_win.iloc[-1])
        streak_start_val = float(close_win.iloc[0])
    elif streak_mode == "close_green":
        # N+1 closes for the higher-close check, plus the matching N opens
        # for the body-green check.
        s_start = eval_idx - high_lookback
        if eval_idx + 1 < 0:
            close_win = closes.iloc[s_start:eval_idx + 1]
            open_win = df["Open"].iloc[s_start + 1:eval_idx + 1]
        else:
            close_win = closes.iloc[s_start:]
            open_win = df["Open"].iloc[s_start + 1:]
        if len(close_win) < high_lookback + 1 or len(open_win) < high_lookback:
            return None
        rising = bool(close_win.diff().iloc[1:].gt(0).all())
        green = bool((close_win.iloc[1:].values > open_win.values).all())
        streak_ok = rising and green
        eval_streak_val = float(close_win.iloc[-1])
        streak_start_val = float(close_win.iloc[0])
    else:
        series = df["High"] if streak_mode == "high" else closes
        s_start = eval_idx - high_lookback
        if eval_idx + 1 < 0:
            streak_win = series.iloc[s_start:eval_idx + 1]
        else:
            streak_win = series.iloc[s_start:]
        if len(streak_win) < high_lookback + 1:
            return None
        eval_streak_val = float(streak_win.iloc[-1])
        streak_start_val = float(streak_win.iloc[0])
        streak_ok = bool(streak_win.diff().iloc[1:].gt(0).all())
    if apply_high and not streak_ok:
        return None

    # Indicators were precomputed when the price frame was built/cached
    # (see _enrich). Reading scalars off existing columns is far cheaper
    # than the ewm/rolling work this used to do per-screen-per-ticker.
    def _scalar(col: str, idx: int = eval_idx):
        try:
            v = df[col].iloc[idx]
        except (KeyError, IndexError):
            return None
        v = float(v)
        return v if np.isfinite(v) else None

    # RSI(14)
    rsi_val = _scalar("rsi14")
    if rsi_val is None:
        return None
    if apply_rsi and not (rsi_min <= rsi_val <= rsi_max):
        return None

    # 9-day SMA of RSI(14) and RSI's deviation from it.
    rsi_sma_val = _scalar("rsi_sma9")
    if rsi_sma_val is None or rsi_sma_val == 0:
        return None
    rsi_dev_pct = (rsi_val - rsi_sma_val) / rsi_sma_val * 100.0
    if apply_rsi_dev and not (rsi_dev_min_pct <= rsi_dev_pct <= rsi_dev_max_pct):
        return None

    # EMA(21) + price deviation.
    ema_val = _scalar("ema21")
    if ema_val is None or ema_val == 0:
        return None
    price_ema21_dev_pct = (prev_close - ema_val) / ema_val * 100.0
    if apply_price_dev and not (price_dev_min_pct <= price_ema21_dev_pct <= price_dev_max_pct):
        return None

    # EMA(50) + EMA21-vs-EMA50 deviation.
    ema_long_val = _scalar("ema50")
    if ema_long_val is None or ema_long_val == 0:
        return None
    ema21_ema50_dev_pct = (ema_val - ema_long_val) / ema_long_val * 100.0
    if apply_ema_dev and not (ema_dev_min_pct <= ema21_ema50_dev_pct <= ema_dev_max_pct):
        return None

    # MACD(12, 26, 9) — histogram threshold and optional "rising" gate.
    macd_val = _scalar("macd")
    macd_signal_val = _scalar("macd_signal")
    macd_hist_val = _scalar("macd_hist")
    macd_hist_prev = _scalar("macd_hist", eval_idx - 1)
    if (macd_val is None or macd_signal_val is None
            or macd_hist_val is None or macd_hist_prev is None):
        return None
    if apply_macd:
        if macd_hist_val < macd_hist_min:
            return None
        if macd_require_rising and not (macd_hist_val > macd_hist_prev):
            return None

    # Relative volume: eval-bar volume / mean of the prior rvol_lookback bars
    vol_window_start = eval_idx - rvol_lookback
    vol_window = volumes.iloc[vol_window_start:eval_idx]
    if vol_window.empty or vol_window.mean() == 0:
        return None
    avg_volume = float(vol_window.mean())
    rel_vol = volume / avg_volume
    if apply_rvol and rel_vol <= rvol_min:
        return None
    if apply_avg_volume and avg_volume < avg_volume_min:
        return None

    # Turnover %: daily volume / shares outstanding. Algebraically this is
    # equal to (volume * price) / (shares * price) = dollar volume / market
    # cap, so the price drops out — we only need shares outstanding.
    shares_val = df.attrs.get("shares")
    try:
        shares_val = float(shares_val) if shares_val else None
    except (TypeError, ValueError):
        shares_val = None
    turnover_pct = None
    if shares_val and shares_val > 0:
        turnover_pct = volume / shares_val * 100.0
    if apply_turnover:
        if turnover_pct is None:
            return None
        if not (turnover_min_pct <= turnover_pct <= turnover_max_pct):
            return None
    market_cap = (shares_val * prev_close) if shares_val else None

    pct_change = (prev_close - prior_close) / prior_close * 100.0 if prior_close else 0.0
    exchange = "TSX" if ticker.endswith(".TO") else "US"
    breakout = (eval_streak_val - streak_start_val) / streak_start_val if streak_start_val else 0.0
    score = max(rel_vol, 0.01) * (1 + max(0.0, breakout))

    membership = lists_for(ticker)
    return ScreenHit(
        ticker=display_symbol(ticker),
        name=_company_name(ticker),
        exchange=exchange,
        lists=membership,
        list_labels=list_labels(membership),
        as_of_date=eval_date,
        close=round(prev_close, 4),
        prev_close=round(prior_close, 4),
        pct_change=round(pct_change, 2),
        high_lookback=round(eval_streak_val, 4),
        rsi=round(float(rsi_val), 2),
        rsi_sma9=round(float(rsi_sma_val), 2),
        rsi_dev_pct=round(rsi_dev_pct, 2),
        ema21=round(ema_val, 4),
        price_ema21_dev_pct=round(price_ema21_dev_pct, 2),
        ema50=round(ema_long_val, 4),
        ema21_ema50_dev_pct=round(ema21_ema50_dev_pct, 2),
        macd=round(float(macd_val), 4),
        macd_signal=round(float(macd_signal_val), 4),
        macd_hist=round(float(macd_hist_val), 4),
        macd_hist_prev=round(float(macd_hist_prev), 4),
        rel_volume=round(rel_vol, 2),
        avg_volume=round(avg_volume, 0),
        volume=round(volume, 0),
        shares=round(shares_val, 0) if shares_val else None,
        market_cap=round(market_cap, 0) if market_cap else None,
        turnover_pct=round(turnover_pct, 4) if turnover_pct is not None else None,
        score=round(score, 4),
    )


def run_screen(
    high_lookback: int = 2,
    streak_mode: str = "high",
    rsi_min: float = 45.0,
    rsi_max: float = 65.0,
    rsi_dev_min_pct: float = 0.0,
    rsi_dev_max_pct: float = 10.0,
    rvol_lookback: int = 10,
    rvol_min: float = 1.2,
    avg_volume_min: int = 50000,
    price_min: float = 1.0,
    price_max: float = 1000.0,
    price_dev_min_pct: float = -1.0,
    price_dev_max_pct: float = 4.0,
    ema_dev_min_pct: float = -3.0,
    ema_dev_max_pct: float = 3.0,
    macd_hist_min: float = 0.0,
    macd_require_rising: bool = True,
    turnover_min_pct: float = 0.0,
    turnover_max_pct: float = 100.0,
    apply_high: bool = True,
    apply_rsi: bool = True,
    apply_rsi_dev: bool = True,
    apply_rvol: bool = True,
    apply_avg_volume: bool = True,
    apply_price: bool = True,
    apply_price_dev: bool = True,
    apply_ema_dev: bool = True,
    apply_macd: bool = True,
    apply_turnover: bool = False,
    as_of_offset: int = 0,
    lists: list[str] | None = None,
    extras: list[str] | None = None,
    universe: Iterable[str] | None = None,
    max_workers: int = 16,
) -> list[ScreenHit]:
    if universe is not None:
        tickers = list(universe)
    elif lists:
        tickers = build_universe(lists)
    else:
        tickers = all_tickers()
    # Append manually-specified tickers (de-duped, preserving order).
    if extras:
        seen = set(tickers)
        for t in extras:
            t = t.strip().upper()
            if t and t not in seen:
                seen.add(t)
                tickers.append(t)
    hits: list[ScreenHit] = []

    def _eval(t: str) -> ScreenHit | None:
        try:
            return evaluate_ticker(
                t,
                high_lookback=high_lookback,
                streak_mode=streak_mode,
                rsi_min=rsi_min,
                rsi_max=rsi_max,
                rsi_dev_min_pct=rsi_dev_min_pct,
                rsi_dev_max_pct=rsi_dev_max_pct,
                rvol_lookback=rvol_lookback,
                rvol_min=rvol_min,
                avg_volume_min=avg_volume_min,
                price_min=price_min,
                price_max=price_max,
                price_dev_min_pct=price_dev_min_pct,
                price_dev_max_pct=price_dev_max_pct,
                ema_dev_min_pct=ema_dev_min_pct,
                ema_dev_max_pct=ema_dev_max_pct,
                macd_hist_min=macd_hist_min,
                macd_require_rising=macd_require_rising,
                turnover_min_pct=turnover_min_pct,
                turnover_max_pct=turnover_max_pct,
                apply_high=apply_high,
                apply_rsi=apply_rsi,
                apply_rsi_dev=apply_rsi_dev,
                apply_rvol=apply_rvol,
                apply_avg_volume=apply_avg_volume,
                apply_price=apply_price,
                apply_price_dev=apply_price_dev,
                apply_ema_dev=apply_ema_dev,
                apply_macd=apply_macd,
                apply_turnover=apply_turnover,
                as_of_offset=as_of_offset,
            )
        except Exception as exc:
            log.warning("evaluate failed for %s: %s", t, exc)
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for fut in as_completed(pool.submit(_eval, t) for t in tickers):
            hit = fut.result()
            if hit is not None:
                hits.append(hit)

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits


def reference_dates(n: int = 21) -> list[dict]:
    """Last `n` US trading-day dates for the as-of date picker.

    Returns a list of {"offset": k, "date": "YYYY-MM-DD"} most recent first.
    Tries several liquid reference tickers, then falls back to any ticker
    already in the price cache (warm after a screen run) so the picker still
    populates even if the reference fetches fail. Per-ticker actual dates may
    differ on Canadian holidays (each row's `as_of_date` reports the real one).
    """
    df = None
    for ref in ("SPY", "QQQ", "DIA", "AAPL", "MSFT"):
        df = _cached_history(ref, period="6mo")
        if df is not None and not df.empty:
            break
    if df is None or df.empty:
        # Fall back to any cached ticker — US trading calendars match.
        for _, (_, cached_df) in list(_PRICE_CACHE.items()):
            if cached_df is not None and not cached_df.empty:
                df = cached_df
                break
    if df is None or df.empty:
        return []
    dates = [idx.strftime("%Y-%m-%d") for idx in df.index][-n:]
    # most recent first, with offset 0 = latest
    return [{"offset": i, "date": d} for i, d in enumerate(reversed(dates))]


# --- chart payload ---------------------------------------------------------

def chart_payload(ticker: str, period: str = "6mo") -> dict | None:
    """Daily OHLCV + EMA(21)/EMA(50) + RSI(14)/9d-SMA-of-RSI for the hover
    chart. No MACD — that pane was dropped from the UI."""
    df = _cached_history(ticker, period=period)
    if df is None or df.empty:
        return None

    df = df.copy()
    df["EMA21"] = ema(df["Close"], 21)
    df["EMA50"] = ema(df["Close"], 50)
    df["RSI"] = rsi_wilder(df["Close"], 14)
    df["RSI_SMA9"] = df["RSI"].rolling(window=9, min_periods=9).mean()

    rows = []
    for idx, r in df.iterrows():
        rows.append({
            "time": idx.strftime("%Y-%m-%d"),
            "open": _safe(r["Open"]),
            "high": _safe(r["High"]),
            "low": _safe(r["Low"]),
            "close": _safe(r["Close"]),
            "volume": _safe(r["Volume"]),
            "ema21": _safe(r["EMA21"]),
            "ema50": _safe(r["EMA50"]),
            "rsi": _safe(r["RSI"]),
            "rsi_sma9": _safe(r["RSI_SMA9"]),
        })
    return {
        "ticker": display_symbol(ticker),
        "name": _company_name(ticker),
        "rows": rows,
    }


def _safe(v):
    """Make a numpy/pandas scalar JSON-safe (NaN/Inf → None)."""
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


# --- diagnostic: per-filter pass/fail for a single ticker ------------------

def diagnose_ticker(
    ticker: str,
    high_lookback: int = 2,
    streak_mode: str = "high",
    rsi_period: int = 14,
    rsi_min: float = 45.0,
    rsi_max: float = 65.0,
    rsi_sma_period: int = 9,
    rsi_dev_min_pct: float = 0.0,
    rsi_dev_max_pct: float = 10.0,
    rvol_lookback: int = 10,
    rvol_min: float = 1.2,
    avg_volume_min: int = 50000,
    price_min: float = 1.0,
    price_max: float = 1000.0,
    ema_period: int = 21,
    ema_long_period: int = 50,
    price_dev_min_pct: float = -1.0,
    price_dev_max_pct: float = 4.0,
    ema_dev_min_pct: float = -3.0,
    ema_dev_max_pct: float = 3.0,
    macd_hist_min: float = 0.0,
    macd_require_rising: bool = True,
    turnover_min_pct: float = 0.0,
    turnover_max_pct: float = 100.0,
    apply_high: bool = True,
    apply_rsi: bool = True,
    apply_rsi_dev: bool = True,
    apply_rvol: bool = True,
    apply_avg_volume: bool = True,
    apply_price: bool = True,
    apply_price_dev: bool = True,
    apply_ema_dev: bool = True,
    apply_macd: bool = True,
    apply_turnover: bool = False,
    as_of_offset: int = 0,
) -> dict:
    """Run each filter independently and return a per-filter pass/fail
    breakdown. Mirrors evaluate_ticker but without short-circuiting so the
    user can see exactly which check rejected a ticker.
    """
    out: dict = {
        "ticker": display_symbol(ticker),
        "in_universe": bool(lists_for(ticker)),
        "lists": lists_for(ticker),
        "as_of_offset": int(as_of_offset),
        "as_of_date": None,
        "data_bars": 0,
        "data_sufficient": False,
        "all_pass": False,
        "checks": [],
        "error": None,
    }

    df = _cached_history(ticker, period="6mo", need_shares=True)
    if df is None or df.empty:
        out["error"] = "yfinance returned no data for this ticker"
        return out
    out["data_bars"] = int(len(df))

    needed = max(
        high_lookback + 2, rsi_period + 5, rvol_lookback + 2,
        ema_period + 2, ema_long_period + 2, 26 + 9 + 2,
    ) + as_of_offset
    if len(df) < needed:
        out["error"] = f"only {len(df)} bars available, screener needs >= {needed}"
        return out
    out["data_sufficient"] = True

    closes = df["Close"]
    volumes = df["Volume"]
    eval_idx = -(1 + int(as_of_offset))
    if eval_idx < -len(df):
        out["error"] = f"as_of_offset {as_of_offset} exceeds available history"
        return out
    out["as_of_date"] = df.index[eval_idx].strftime("%Y-%m-%d")

    prev_close = float(closes.iloc[eval_idx])
    prior_close = float(closes.iloc[eval_idx - 1]) if eval_idx - 1 >= -len(df) else float("nan")
    volume = float(volumes.iloc[eval_idx])

    def add(name, label, value, applied, ok, band=None, extra=None):
        out["checks"].append({
            "name": name,
            "label": label,
            "value": value,
            "applied": bool(applied),
            "pass": bool(ok) if applied else True,  # ignored filters don't fail
            "band": band,
            "extra": extra,
        })

    # 1. Price range
    price_ok = price_min <= prev_close <= price_max
    add("price", f"Price ∈ [${price_min}, ${price_max}]", round(prev_close, 4),
        apply_price, price_ok, [price_min, price_max])

    # 2. Streak (mode: high / close / green / close_green)
    if streak_mode == "green":
        g_start = eval_idx - high_lookback + 1
        if eval_idx + 1 < 0:
            open_win = df["Open"].iloc[g_start:eval_idx + 1]
            close_win = closes.iloc[g_start:eval_idx + 1]
        else:
            open_win = df["Open"].iloc[g_start:]
            close_win = closes.iloc[g_start:]
        green_flags = [bool(c > o) for c, o in zip(close_win.tolist(), open_win.tolist())]
        streak_ok = len(close_win) >= high_lookback and all(green_flags)
        add("streak",
            f"Green-candle streak ({high_lookback} days)",
            round(float(close_win.iloc[-1]), 4) if len(close_win) else None,
            apply_high, streak_ok, None,
            {"opens": [round(float(o), 4) for o in open_win.tolist()],
             "closes": [round(float(c), 4) for c in close_win.tolist()],
             "green": green_flags})
    elif streak_mode == "close_green":
        s_start = eval_idx - high_lookback
        if eval_idx + 1 < 0:
            close_win = closes.iloc[s_start:eval_idx + 1]
            open_win = df["Open"].iloc[s_start + 1:eval_idx + 1]
        else:
            close_win = closes.iloc[s_start:]
            open_win = df["Open"].iloc[s_start + 1:]
        diffs = close_win.diff().iloc[1:].tolist() if len(close_win) >= 2 else []
        clean_diffs = [d for d in diffs if d is not None and not (isinstance(d, float) and (d != d))]
        streak_closes = close_win.iloc[1:]  # the N "streak" bars
        green_flags = [bool(c > o) for c, o in zip(streak_closes.tolist(), open_win.tolist())]
        ok_close = len(close_win) >= high_lookback + 1 and all(d > 0 for d in clean_diffs)
        ok_green = len(open_win) >= high_lookback and all(green_flags)
        streak_ok = ok_close and ok_green
        add("streak",
            f"Higher-close + green-body streak ({high_lookback} days)",
            round(float(close_win.iloc[-1]), 4) if len(close_win) else None,
            apply_high, streak_ok, None,
            {"closes": [round(float(c), 4) for c in close_win.tolist()],
             "diffs": [round(float(d), 4) for d in clean_diffs],
             "opens": [round(float(o), 4) for o in open_win.tolist()],
             "green": green_flags})
    else:
        series = df["High"] if streak_mode == "high" else closes
        s_start = eval_idx - high_lookback
        if eval_idx + 1 < 0:
            streak_win = series.iloc[s_start:eval_idx + 1]
        else:
            streak_win = series.iloc[s_start:]
        diffs = streak_win.diff().iloc[1:].tolist() if len(streak_win) >= 2 else []
        clean_diffs = [d for d in diffs if d is not None and not (isinstance(d, float) and (d != d))]
        streak_ok = len(streak_win) >= high_lookback + 1 and all(d > 0 for d in clean_diffs)
        label = "Higher-high" if streak_mode == "high" else "Higher-close"
        add("streak",
            f"{label} streak ({high_lookback} days)",
            round(float(streak_win.iloc[-1]), 4) if len(streak_win) else None,
            apply_high, streak_ok, None,
            {"values": [round(float(v), 4) for v in streak_win.tolist()],
             "diffs": [round(float(d), 4) for d in clean_diffs]})

    # Indicators come straight off the precomputed columns (same as
    # evaluate_ticker), so no recomputation per call.
    def _scalar(col: str, idx: int = eval_idx):
        try:
            v = df[col].iloc[idx]
        except (KeyError, IndexError):
            return None
        v = float(v)
        return v if np.isfinite(v) else None

    # 3. RSI(14) band
    rsi_val = _scalar("rsi14")
    rsi_ok = rsi_val is not None and rsi_min <= rsi_val <= rsi_max
    add("rsi", f"RSI({rsi_period}) ∈ [{rsi_min}, {rsi_max}]",
        round(rsi_val, 2) if rsi_val is not None else None,
        apply_rsi, rsi_ok, [rsi_min, rsi_max])

    # 4. RSI dev vs 9d SMA
    rsi_sma_val = _scalar("rsi_sma9")
    rsi_dev_pct = None
    if rsi_val is not None and rsi_sma_val and rsi_sma_val != 0:
        rsi_dev_pct = (rsi_val - rsi_sma_val) / rsi_sma_val * 100.0
    rsi_dev_ok = rsi_dev_pct is not None and rsi_dev_min_pct <= rsi_dev_pct <= rsi_dev_max_pct
    add("rsi_dev", f"RSI dev vs 9d SMA ∈ [{rsi_dev_min_pct}%, {rsi_dev_max_pct}%]",
        round(rsi_dev_pct, 2) if rsi_dev_pct is not None else None,
        apply_rsi_dev, rsi_dev_ok, [rsi_dev_min_pct, rsi_dev_max_pct],
        {"rsi_sma9": round(rsi_sma_val, 2) if rsi_sma_val is not None else None})

    # 5. Price dev vs EMA(21)
    ema_val = _scalar("ema21")
    price_dev_pct = None
    if ema_val and ema_val != 0:
        price_dev_pct = (prev_close - ema_val) / ema_val * 100.0
    pd_ok = price_dev_pct is not None and price_dev_min_pct <= price_dev_pct <= price_dev_max_pct
    add("price_dev", f"Price vs EMA({ema_period}) ∈ [{price_dev_min_pct}%, {price_dev_max_pct}%]",
        round(price_dev_pct, 2) if price_dev_pct is not None else None,
        apply_price_dev, pd_ok, [price_dev_min_pct, price_dev_max_pct],
        {"ema21": round(ema_val, 4) if ema_val is not None else None})

    # 6. EMA(21) vs EMA(50)
    ema_long_val = _scalar("ema50")
    ema_dev_pct = None
    if ema_val is not None and ema_long_val and ema_long_val != 0:
        ema_dev_pct = (ema_val - ema_long_val) / ema_long_val * 100.0
    ed_ok = ema_dev_pct is not None and ema_dev_min_pct <= ema_dev_pct <= ema_dev_max_pct
    add("ema_dev", f"EMA({ema_period}) vs EMA({ema_long_period}) ∈ [{ema_dev_min_pct}%, {ema_dev_max_pct}%]",
        round(ema_dev_pct, 2) if ema_dev_pct is not None else None,
        apply_ema_dev, ed_ok, [ema_dev_min_pct, ema_dev_max_pct],
        {"ema50": round(ema_long_val, 4) if ema_long_val is not None else None})

    # 7. MACD histogram
    macd_hist_val = _scalar("macd_hist")
    macd_hist_prev = _scalar("macd_hist", eval_idx - 1)
    macd_ok = True
    if macd_hist_val is None:
        macd_ok = False
    else:
        if macd_hist_val < macd_hist_min:
            macd_ok = False
        if macd_require_rising and macd_hist_prev is not None and not (macd_hist_val > macd_hist_prev):
            macd_ok = False
    add("macd", f"MACD hist ≥ {macd_hist_min}" + (" and rising" if macd_require_rising else ""),
        round(macd_hist_val, 4) if macd_hist_val is not None else None,
        apply_macd, macd_ok, None,
        {"prev_hist": round(macd_hist_prev, 4) if macd_hist_prev is not None else None,
         "rising": macd_hist_val is not None and macd_hist_prev is not None and macd_hist_val > macd_hist_prev})

    # 8. Relative volume
    vol_window_start = eval_idx - rvol_lookback
    vol_window = volumes.iloc[vol_window_start:eval_idx]
    rvol = None
    if len(vol_window) and vol_window.mean() > 0:
        rvol = volume / float(vol_window.mean())
    rvol_ok = rvol is not None and rvol > rvol_min
    avg_vol = float(vol_window.mean()) if len(vol_window) else None
    add("rvol", f"RVol({rvol_lookback}d) > {rvol_min}",
        round(rvol, 2) if rvol is not None else None,
        apply_rvol, rvol_ok, [rvol_min, None],
        {"avg_volume": round(avg_vol, 0) if avg_vol is not None else None,
         "volume": round(volume, 0)})

    # 9. Average volume floor
    avg_vol_ok = avg_vol is not None and avg_vol >= avg_volume_min
    add("avg_volume", f"Avg volume ({rvol_lookback}d) ≥ {avg_volume_min:,}",
        round(avg_vol, 0) if avg_vol is not None else None,
        apply_avg_volume, avg_vol_ok, [avg_volume_min, None])

    # 10. Turnover % = volume / shares outstanding × 100 (= $vol / market cap)
    shares_val = df.attrs.get("shares")
    try:
        shares_val = float(shares_val) if shares_val else None
    except (TypeError, ValueError):
        shares_val = None
    turnover_pct = (volume / shares_val * 100.0) if (shares_val and shares_val > 0) else None
    market_cap = (shares_val * prev_close) if shares_val else None
    turnover_ok = turnover_pct is not None and turnover_min_pct <= turnover_pct <= turnover_max_pct
    add("turnover",
        f"Volume / market cap ∈ [{turnover_min_pct}%, {turnover_max_pct}%]",
        round(turnover_pct, 4) if turnover_pct is not None else None,
        apply_turnover, turnover_ok, [turnover_min_pct, turnover_max_pct],
        {"shares": round(shares_val, 0) if shares_val else None,
         "market_cap": round(market_cap, 0) if market_cap else None})

    out["all_pass"] = all(c["pass"] for c in out["checks"])
    return out
