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

import snapshots
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
    momentum_score: float
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


# --- heuristic "momentum continuation" score ------------------------------
# Weighted blend of the indicator stack squashed into 0-100. Each sub-score
# is a bell or sigmoid in [0, 1] designed to peak at a "healthy momentum"
# value and fall off at exhaustion extremes (overbought / parabolic /
# stretched / volume-mania). Sub-scores are weighted (sums to 100); missing
# indicators are skipped and the remaining weights re-normalized.
#
# IMPORTANT: this is a RANKING heuristic, NOT a calibrated probability.
# A true probability would require backtesting forward returns over the
# snapshot table — which only starts to be meaningful once we've
# accumulated weeks of daily snapshots.

def _bell(x: float, center: float, width: float) -> float:
    """Gaussian-shaped 0-1 bell centered at `center` with sigma `width`."""
    return math.exp(-((x - center) / width) ** 2)


def _sigmoid(x: float, midpoint: float, slope: float = 1.0) -> float:
    """Logistic 0-1 curve crossing 0.5 at `midpoint`; `slope` is steepness."""
    z = (x - midpoint) * slope
    if z > 40:
        return 1.0
    if z < -40:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def compute_momentum_score(
    *,
    close: float | None = None,
    rsi: float | None = None,
    rsi_dev_pct: float | None = None,
    price_ema21_dev_pct: float | None = None,
    ema21_ema50_dev_pct: float | None = None,
    macd_hist: float | None = None,
    macd_hist_prev: float | None = None,
    rel_volume: float | None = None,
    breakout_pct: float | None = None,
    turnover_pct: float | None = None,
) -> float:
    """Heuristic 0-100 score; higher = more of the indicator stack is
    aligned for continuation. See module-level note: ranking signal, not
    a calibrated probability."""
    parts: list[tuple[float, float]] = []  # (weight, value in [0, 1])

    # RSI position — strong but not overbought. Peak at 60.
    if rsi is not None:
        parts.append((12.0, _bell(rsi, 60.0, 18.0)))

    # RSI dev vs 9d SMA — accelerating, not parabolic. Peak at +3%.
    if rsi_dev_pct is not None:
        parts.append((8.0, _bell(rsi_dev_pct, 3.0, 5.0)))

    # Price vs EMA(21) — slightly above the moving average. Peak at +1%.
    if price_ema21_dev_pct is not None:
        parts.append((8.0, _bell(price_ema21_dev_pct, 1.0, 3.5)))

    # EMA(21) vs EMA(50) — trend confirmation, not stretched. Peak at +2%.
    if ema21_ema50_dev_pct is not None:
        parts.append((13.0, _bell(ema21_ema50_dev_pct, 2.0, 4.0)))

    # MACD histogram — positive = bullish. Normalize by price so the
    # scale is comparable across $5 vs $500 names.
    if macd_hist is not None and close and close > 0:
        macd_pct = macd_hist / close * 100.0
        parts.append((12.0, _sigmoid(macd_pct, 0.1, 5.0)))
    elif macd_hist is not None:
        parts.append((12.0, _sigmoid(macd_hist, 0.0, 1.0)))

    # MACD rising — binary acceleration bonus.
    if macd_hist is not None and macd_hist_prev is not None:
        parts.append((10.0, 1.0 if macd_hist > macd_hist_prev else 0.2))

    # Relative volume — confirmation. Ramps around 2x.
    if rel_volume is not None:
        parts.append((17.0, _sigmoid(rel_volume, 2.0, 2.0)))

    # Streak run-up % — modest breakout. Around +2% ideal.
    if breakout_pct is not None:
        parts.append((10.0, _sigmoid(breakout_pct, 2.0, 0.8)))

    # Turnover (volume / market cap) — engaged but not retail mania.
    if turnover_pct is not None:
        parts.append((10.0, _bell(turnover_pct, 1.5, 3.0)))

    if not parts:
        return 0.0
    total_w = sum(w for w, _ in parts)
    score = sum(w * v for w, v in parts)
    return round(100.0 * score / total_w, 1)


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


# --- failed-ticker prune ---------------------------------------------------
# A ticker that consistently has no Yahoo data (delisted, unrecognised
# suffix, etc.) wastes warm-cache time on every run and produces nothing
# downstream. Track per-ticker failure streaks across runs; after
# PRUNE_THRESHOLD consecutive days of failing, drop the ticker from the
# universe. tickers.py reads the same JSON file at universe-build time.
#
# Safety layers:
#   * Bucketed by exchange — a high-failure run for one exchange (e.g. a
#     bad Yahoo day for US tickers during a holiday) doesn't bump
#     counters for other exchanges.
#   * Day-bucketed — a ticker failing N times in one run still counts as
#     one failure-day. Counter only ticks once per calendar day.
#   * Suspicious-rate guard — if >SUSPICIOUS_FAIL_RATE of a bucket
#     fails in one run, that bucket's counters are not touched (Yahoo
#     outage / rate-limit, not per-ticker rot).
#
# Restore via /api/admin/pruned-tickers/restore.

_PRUNE_STATE_PATH = _CACHE_DIR / "ticker_failures.json"
PRUNE_THRESHOLD = 3  # consecutive failure days before pruning
SUSPICIOUS_FAIL_RATE = 0.85
_prune_lock = threading.Lock()


def _exchange_bucket(ticker: str) -> str:
    """Coarse bucket for the suspicious-rate guard. yfinance hiccups
    tend to be exchange-wide, not universal."""
    if ticker.endswith(".TO"):
        return "tsx"
    if ticker.endswith(".V"):
        return "tsxv"
    return "us"


def _load_prune_state() -> dict:
    try:
        if not _PRUNE_STATE_PATH.exists():
            return {"failures": {}, "pruned": []}
        import json as _json
        data = _json.loads(_PRUNE_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"failures": {}, "pruned": []}
        data.setdefault("failures", {})
        data.setdefault("pruned", [])
        return data
    except Exception as exc:
        log.warning("prune state read failed: %s", exc)
        return {"failures": {}, "pruned": []}


def _save_prune_state(state: dict) -> None:
    try:
        import json as _json
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _PRUNE_STATE_PATH.write_text(
            _json.dumps(state, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        log.warning("prune state write failed: %s", exc)


def pruned_tickers() -> set[str]:
    """Set of tickers currently pruned out of the universe."""
    with _prune_lock:
        return set(_load_prune_state().get("pruned") or [])


def prune_status() -> dict:
    """Snapshot of the prune state — total pruned + a sample of failing
    tickers nearing the threshold. Used by the admin UI."""
    with _prune_lock:
        state = _load_prune_state()
        failures = state.get("failures") or {}
        # Tickers within one strike of pruning — useful warning.
        watch = sorted(
            (
                (t, e.get("count", 0), e.get("last_fail_date"))
                for t, e in failures.items()
                if (e.get("count", 0) or 0) >= max(1, PRUNE_THRESHOLD - 1)
                and t not in (state.get("pruned") or [])
            ),
            key=lambda r: -(r[1] or 0),
        )[:25]
        return {
            "threshold": PRUNE_THRESHOLD,
            "pruned": list(state.get("pruned") or []),
            "near_prune": [
                {"ticker": t, "fail_count": c, "last_fail_date": d}
                for t, c, d in watch
            ],
        }


def restore_pruned(tickers: list[str] | None) -> int:
    """Restore one or more tickers to the universe. `tickers=None`
    restores everything and resets all failure counters."""
    with _prune_lock:
        state = _load_prune_state()
        if tickers is None:
            n = len(state.get("pruned") or [])
            state["pruned"] = []
            state["failures"] = {}
        else:
            wanted = {t.strip().upper() for t in tickers if t}
            before = len(state.get("pruned") or [])
            state["pruned"] = [t for t in (state.get("pruned") or []) if t.upper() not in wanted]
            n = before - len(state["pruned"])
            for t in list(state.get("failures", {}).keys()):
                if t.upper() in wanted:
                    state["failures"].pop(t, None)
        _save_prune_state(state)
        return n


def record_warm_results(succeeded: set[str], failed: set[str]) -> list[str]:
    """Update per-ticker failure counters from the latest warm-cache run.
    Returns the list of tickers freshly pruned by this run."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Group by exchange so the suspicious-rate guard fires per-exchange.
    buckets: dict[str, tuple[list[str], list[str]]] = {}
    for t in succeeded:
        buckets.setdefault(_exchange_bucket(t), ([], []))[0].append(t)
    for t in failed:
        buckets.setdefault(_exchange_bucket(t), ([], []))[1].append(t)

    newly_pruned: list[str] = []
    with _prune_lock:
        state = _load_prune_state()
        failures = state.setdefault("failures", {})
        pruned = state.setdefault("pruned", [])
        pruned_set = set(pruned)

        for exch, (succ, fail) in buckets.items():
            total = len(succ) + len(fail)
            if total == 0:
                continue
            rate = len(fail) / total
            if rate > SUSPICIOUS_FAIL_RATE:
                log.warning(
                    "prune: skipping %s counter updates this run — %d/%d "
                    "(%d%%) failed; treating as a Yahoo-side anomaly",
                    exch, len(fail), total, int(rate * 100),
                )
                continue
            # Successes clear the streak.
            for t in succ:
                failures.pop(t, None)
            # Failures bump the streak — at most once per calendar day.
            for t in fail:
                entry = failures.get(t) or {"count": 0, "last_fail_date": None}
                if entry.get("last_fail_date") == today:
                    continue
                entry["count"] = (entry.get("count") or 0) + 1
                entry["last_fail_date"] = today
                failures[t] = entry
                if entry["count"] >= PRUNE_THRESHOLD and t not in pruned_set:
                    pruned.append(t)
                    pruned_set.add(t)
                    newly_pruned.append(t)

        _save_prune_state(state)

    if newly_pruned:
        sample = ", ".join(newly_pruned[:10])
        log.info(
            "prune: dropping %d ticker(s) from universe after %d consecutive "
            "failed warm-cache days: %s%s",
            len(newly_pruned), PRUNE_THRESHOLD, sample,
            "…" if len(newly_pruned) > 10 else "",
        )
    return newly_pruned


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
    # A small bounded sample of tickers that failed in the most recent
    # warm-cache run — surfaced via /api/admin/warm-status so the user
    # can see *which* names are problematic (delisted, missing on
    # Yahoo, malformed suffix, etc.) instead of just a raw error count.
    "failed_samples": [],
}
_warm_lock = threading.Lock()
# Separate ref so cancel can clear the UI-facing "running" flag without
# losing track of a zombie thread still draining (e.g. wedged in a
# network call inside all_tickers()). warm_cache refuses to start a new
# job while this thread is alive.
_warm_thread: threading.Thread | None = None


def warm_status() -> dict:
    with _warm_lock:
        return dict(_warm_state)


def cancel_warm_cache() -> bool:
    """Ask the running warm thread to stop and immediately mark the job
    as finished from the UI's perspective. The background thread keeps
    draining (each per-ticker worker noops once it sees `cancelled`),
    but the UI doesn't have to wait for it to wake up from whatever
    blocking call it's currently in."""
    global _warm_thread
    alive = _warm_thread is not None and _warm_thread.is_alive()
    with _warm_lock:
        was_running = _warm_state["running"]
        if not was_running and not alive:
            return False
        _warm_state["cancelled"] = True
        _warm_state["running"] = False
        _warm_state["finished_at"] = time.time()
        return True


def warm_cache(tickers: list[str] | None = None, max_workers: int = 12) -> bool:
    """Start a background fetch of `tickers` (or the full universe) into the
    disk price cache. Returns False if a warm job is already running."""
    global _warm_thread
    # The previous job's thread may still be draining post-cancel — refuse
    # to start a second concurrent warm in that case (both would fight for
    # the same per-ticker pickle files).
    if _warm_thread is not None and _warm_thread.is_alive():
        return False
    with _warm_lock:
        if _warm_state["running"]:
            return False
        _warm_state.update(
            running=True, done=0, total=0, errors=0, cancelled=False,
            started_at=time.time(), finished_at=None,
            failed_samples=[],
        )

    def _run() -> None:
        try:
            tk = tickers if tickers is not None else all_tickers()
            with _warm_lock:
                _warm_state["total"] = len(tk)

            _FAIL_SAMPLE_CAP = 20
            # Local sets — collected without the warm lock since they're
            # only touched inside the pool threads, then handed to the
            # prune logic atomically after the pool drains.
            succeeded: set[str] = set()
            failed: set[str] = set()
            _result_lock = threading.Lock()

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
                # Truth-on-disk success check: _cached_history returns
                # None silently when Yahoo gives no data (delisted ticker,
                # unrecognized symbol, transient empty response), so the
                # try/except alone catches almost nothing. Verify the
                # pickle was actually written and is fresh.
                ok = False
                try:
                    df = _cached_history(t)
                    if df is not None:
                        try:
                            mtime = _price_file(t).stat().st_mtime
                            ok = (time.time() - mtime) < _PRICE_FILE_TTL_SEC
                        except FileNotFoundError:
                            ok = False
                except Exception:
                    ok = False
                with _result_lock:
                    (succeeded if ok else failed).add(t)
                with _warm_lock:
                    _warm_state["done"] += 1
                    if not ok:
                        _warm_state["errors"] += 1
                        samples = _warm_state["failed_samples"]
                        if len(samples) < _FAIL_SAMPLE_CAP:
                            samples.append(t)

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for _ in pool.map(_one, tk):
                    pass

            # Update the per-ticker failure streak counters and prune
            # any ticker that has now failed PRUNE_THRESHOLD calendar
            # days in a row. Skipped (no-op) if the run was cancelled —
            # partial data shouldn't be used to penalise tickers.
            with _warm_lock:
                was_cancelled = _warm_state["cancelled"]
            if not was_cancelled:
                try:
                    record_warm_results(succeeded, failed)
                except Exception as exc:
                    log.warning("prune: record_warm_results failed: %s", exc)
        except Exception as exc:
            log.warning("warm-cache job failed: %s", exc)
        finally:
            with _warm_lock:
                _warm_state["running"] = False
                _warm_state["finished_at"] = time.time()
                # Concise summary line for server logs — the warm endpoint's
                # poll-based UI doesn't show server logs, so this is the
                # only record of the failure breakdown the operator can grep.
                dur = (_warm_state["finished_at"] - _warm_state["started_at"]) \
                    if _warm_state["started_at"] else 0
                succeeded = _warm_state["done"] - _warm_state["errors"]
                sample = ", ".join(_warm_state["failed_samples"][:10])
                log.info(
                    "warm-cache complete: %d/%d succeeded (%d failed) in %.0fs%s",
                    succeeded, _warm_state["total"], _warm_state["errors"],
                    dur,
                    f" — sample failed: {sample}" if sample else "",
                )
            # Always snapshot what made it onto disk, even if the warm
            # was cancelled — partial data is still useful and the user
            # may have cancelled by accident (e.g. auto-warm racing with
            # a manual click on boot). Cancel the snapshot separately
            # via /api/admin/snapshot/cancel if you really don't want it.
            if snapshots.enabled():
                global _snapshot_thread
                _snapshot_thread = threading.Thread(
                    target=take_snapshot, daemon=True, name="post-warm-snapshot",
                )
                _snapshot_thread.start()

    _warm_thread = threading.Thread(target=_run, daemon=True, name="warm-cache")
    _warm_thread.start()
    return True


# --- daily snapshot writer -------------------------------------------------
# After a warm-cache run finishes, we extract the latest-bar indicators
# plus the trailing 60 OHLCV bars from each ticker's pickle and write a
# row to the Postgres `daily_snapshot` table. Subsequent screens for that
# date serve from one bulk SELECT instead of 8k disk reads.

_snapshot_state: dict = {
    "running": False,
    "done": 0,
    "total": 0,
    "errors": 0,
    "cancelled": False,
    "started_at": None,
    "finished_at": None,
    "last_as_of": None,
    "last_written": 0,
    "last_trimmed": 0,
    # Per-category counters from the last completed run — populated so
    # the UI can explain why a snapshot produced 0 rows.
    "skipped_missing": 0,     # pickle file does not exist on disk
    "skipped_stale": 0,       # mtime older than _PRICE_FILE_TTL_SEC
    "skipped_unenriched": 0,  # rsi14 column absent (old-format pickle)
    "skipped_corrupt": 0,     # pd.read_pickle raised
    "skipped_short": 0,       # df had < 2 bars
    "skipped_row_none": 0,    # last bar's Close/Volume was NaN -> row None
    "last_error": None,       # most recent upsert error, if any
}
_snapshot_lock = threading.Lock()
_snapshot_thread: threading.Thread | None = None


def snapshot_status() -> dict:
    with _snapshot_lock:
        return dict(_snapshot_state)


def cancel_snapshot() -> bool:
    """Ask the running snapshot job to stop. Mirrors cancel_warm_cache:
    flips running=False for the UI immediately, and sets cancelled=True
    so the worker thread's per-ticker check noops the remaining work."""
    global _snapshot_thread
    alive = _snapshot_thread is not None and _snapshot_thread.is_alive()
    with _snapshot_lock:
        if not _snapshot_state["running"] and not alive:
            return False
        _snapshot_state["cancelled"] = True
        _snapshot_state["running"] = False
        _snapshot_state["finished_at"] = time.time()
        return True


def _row_from_df(ticker: str, df: pd.DataFrame) -> dict | None:
    """Build a snapshot-row dict from an already-enriched price DataFrame.
    Returns None if the frame is too short or missing indicator columns."""
    if df is None or len(df) < 2 or "rsi14" not in df.columns:
        return None
    last_idx = -1
    as_of_date = df.index[last_idx].strftime("%Y-%m-%d")

    def _scalar(col: str, idx: int = last_idx):
        try:
            v = float(df[col].iloc[idx])
        except (KeyError, IndexError, ValueError, TypeError):
            return None
        return v if np.isfinite(v) else None

    close = _scalar("Close")
    prior_close = _scalar("Close", -2)
    volume = _scalar("Volume")
    if close is None or volume is None:
        return None

    # Default avg_volume window matches the screener's rvol_lookback default
    # (10 days). The screener recomputes avg_volume from recent_bars when
    # rvol_lookback differs, so this is just a convenience field.
    vol_window = df["Volume"].iloc[max(-11, -len(df)):-1]
    avg_volume = float(vol_window.mean()) if len(vol_window) else None
    if avg_volume is not None and not np.isfinite(avg_volume):
        avg_volume = None

    keep = df.iloc[max(-snapshots.RECENT_BARS_KEEP, -len(df)):]
    bars = []
    for idx, r in keep.iterrows():
        bars.append({
            "d": idx.strftime("%Y-%m-%d"),
            "o": _safe_float(r.get("Open")),
            "h": _safe_float(r.get("High")),
            "l": _safe_float(r.get("Low")),
            "c": _safe_float(r.get("Close")),
            "v": _safe_float(r.get("Volume")),
        })

    shares_val = df.attrs.get("shares")
    try:
        shares_val = float(shares_val) if shares_val else None
    except (TypeError, ValueError):
        shares_val = None

    return {
        "ticker": ticker,
        "as_of": as_of_date,
        "close": close,
        "prior_close": prior_close,
        "volume": volume,
        "avg_volume": avg_volume,
        "ema21": _scalar("ema21"),
        "ema50": _scalar("ema50"),
        "rsi14": _scalar("rsi14"),
        "rsi_sma9": _scalar("rsi_sma9"),
        "macd": _scalar("macd"),
        "macd_signal": _scalar("macd_signal"),
        "macd_hist": _scalar("macd_hist"),
        "macd_hist_prev": _scalar("macd_hist", -2),
        "shares": shares_val,
        "recent_bars": {"bars": bars},
    }


def _safe_float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _read_pickle_for_snapshot(ticker: str) -> tuple[pd.DataFrame | None, str]:
    """Read a ticker's pickle directly from disk. Returns (df, reason).
    reason is "" on success, or one of: missing / stale / corrupt /
    unenriched / empty / short — so the snapshot loop can tally why
    tickers were rejected and surface it in the UI.

    If the pickle is on disk but lacks indicator columns (rsi14 etc.),
    enrich it in memory before returning. This is pure pandas — no
    network — and rescues snapshots when an older warm wrote pickles
    that didn't get enriched, or when a fresh warm's enrichment
    rewrite to disk failed silently (free-tier disk full / permission)."""
    pf = _price_file(ticker)
    if not pf.exists():
        return None, "missing"
    try:
        if (time.time() - pf.stat().st_mtime) > _PRICE_FILE_TTL_SEC:
            return None, "stale"
    except Exception:
        return None, "missing"
    try:
        df = pd.read_pickle(pf)
    except Exception:
        return None, "corrupt"
    if df is None or df.empty:
        return None, "empty"
    # Older pickles (and the occasional yfinance edge case) can carry rows
    # with NaN Close/Volume at the tail. _row_from_df would then silently
    # reject the ticker because its last bar has no usable close — strip
    # those rows here so a usable last bar is used.
    try:
        if "Close" in df.columns and "Volume" in df.columns:
            df = df.dropna(subset=["Close", "Volume"])
    except Exception:
        return None, "corrupt"
    if df is None or df.empty:
        return None, "empty"
    if len(df) < 2:
        return None, "short"
    if "rsi14" not in df.columns:
        try:
            df = _enrich(df)
        except Exception:
            return None, "unenriched"
        if "rsi14" not in df.columns:
            return None, "unenriched"
    return df, ""


_SNAPSHOT_BATCH = 500       # rows per upsert — bounds memory + makes
                            # progress durable if the worker dies.
_SNAPSHOT_WORKERS = 6       # disk reads + JSON encode; mostly I/O.


def take_snapshot(tickers: list[str] | None = None) -> dict:
    """Write a snapshot row to Postgres for every ticker whose pickle is
    fresh on disk. Reads pickles directly (no Yahoo fallback) in a
    bounded thread pool and upserts in 500-row batches so progress
    survives a worker restart. Honors cancel_snapshot()."""
    if not snapshots.enabled():
        return {"enabled": False}
    # Re-entry guard. Only check the state flag — NOT _snapshot_thread.
    # When called from inside _snapshot_thread (post-warm hook or
    # api_take_snapshot), is_alive() on that ref would be True and the
    # function would falsely bail thinking another run is in progress.
    with _snapshot_lock:
        if _snapshot_state["running"]:
            return {"running": True, **_snapshot_state}
        _snapshot_state.update(
            running=True, done=0, total=0, errors=0, cancelled=False,
            started_at=time.time(), finished_at=None,
            last_written=0, last_trimmed=0, last_as_of=None,
        )

    tk = list(tickers) if tickers is not None else all_tickers()
    written_total = 0
    errors = 0
    last_as_of: str | None = None
    batch: list[dict] = []
    # Per-category counters — surfaced via /api/admin/snapshot/status so
    # we can answer "why is snapshot empty?" without server access.
    skip_counts = {
        "missing": 0, "stale": 0, "unenriched": 0,
        "corrupt": 0, "empty": 0, "short": 0,
        # _row_from_df returns None when the last bar's Close/Volume is
        # unusable — track it so the gap between warm-cache count and
        # snapshot rows is fully accounted for.
        "row_none": 0,
    }
    skip_lock = threading.Lock()

    def _flush() -> None:
        nonlocal written_total
        if not batch:
            return
        try:
            n = snapshots.upsert_many(batch)
            written_total += n
            with _snapshot_lock:
                _snapshot_state["last_written"] = written_total
                _snapshot_state["last_error"] = snapshots.last_write_error()
        finally:
            batch.clear()

    def _one(t: str) -> dict | None:
        with _snapshot_lock:
            if _snapshot_state["cancelled"]:
                return None
        df, reason = _read_pickle_for_snapshot(t)
        if df is None:
            with skip_lock:
                skip_counts[reason] = skip_counts.get(reason, 0) + 1
            return None
        try:
            row = _row_from_df(t, df)
        except Exception as exc:
            log.warning("snapshot row build failed for %s: %s", t, exc)
            raise
        if row is None:
            with skip_lock:
                skip_counts["row_none"] = skip_counts.get("row_none", 0) + 1
        return row

    try:
        with _snapshot_lock:
            _snapshot_state["total"] = len(tk)
        log.info("snapshot: starting (%d tickers)", len(tk))

        with ThreadPoolExecutor(max_workers=_SNAPSHOT_WORKERS) as pool:
            # imap-style iteration so we can flush in batches as rows
            # become available, instead of holding all 8k in memory.
            for i, fut_row in enumerate(pool.map(_one, tk), start=1):
                with _snapshot_lock:
                    if _snapshot_state["cancelled"]:
                        break
                if fut_row is not None:
                    batch.append(fut_row)
                    last_as_of = fut_row.get("as_of") or last_as_of
                    if len(batch) >= _SNAPSHOT_BATCH:
                        _flush()
                with _snapshot_lock:
                    _snapshot_state["done"] += 1
                if i % 1000 == 0:
                    log.info("snapshot: %d/%d processed, %d written so far",
                             i, len(tk), written_total)

        _flush()
        trimmed = snapshots.trim_to_last(snapshots.RETENTION_DAYS) if written_total else 0
        with _snapshot_lock:
            _snapshot_state.update(
                errors=errors,
                last_as_of=last_as_of,
                last_written=written_total,
                last_trimmed=trimmed,
                last_error=snapshots.last_write_error(),
                skipped_missing=skip_counts["missing"],
                skipped_stale=skip_counts["stale"],
                skipped_unenriched=skip_counts["unenriched"],
                skipped_corrupt=skip_counts["corrupt"],
                skipped_short=skip_counts["empty"] + skip_counts["short"],
                skipped_row_none=skip_counts.get("row_none", 0),
            )
        log.info(
            "snapshot complete: as_of=%s written=%d trimmed=%d skipped=%s last_error=%s",
            last_as_of, written_total, trimmed, skip_counts,
            snapshots.last_write_error(),
        )
        return {
            "enabled": True,
            "as_of": last_as_of,
            "written": written_total,
            "trimmed": trimmed,
            "errors": errors,
            "skipped": skip_counts,
            "last_error": snapshots.last_write_error(),
        }
    except Exception as exc:
        log.warning("snapshot job failed: %s", exc)
        return {"enabled": True, "error": str(exc), "written": written_total}
    finally:
        with _snapshot_lock:
            _snapshot_state["running"] = False
            _snapshot_state["finished_at"] = time.time()


def _resolve_as_of_date(as_of_offset: int) -> str | None:
    """Map an offset (0 = latest) to a YYYY-MM-DD using SPY's calendar.
    Mirrors the resolution evaluate_ticker does per-ticker; needed up
    front so the snapshot path can pick the right row in bulk."""
    try:
        offset = max(0, min(int(as_of_offset), MAX_AS_OF_OFFSET))
    except (TypeError, ValueError):
        return None
    for ref in ("SPY", "QQQ", "DIA", "AAPL", "MSFT"):
        df = _cached_history(ref, period="6mo")
        if df is None or df.empty:
            continue
        idx = -(1 + offset)
        if idx < -len(df):
            continue
        return df.index[idx].strftime("%Y-%m-%d")
    # Last-ditch: any cached ticker
    for _, (_, cached_df) in list(_PRICE_CACHE.items()):
        if cached_df is None or cached_df.empty:
            continue
        idx = -(1 + offset)
        if idx < -len(cached_df):
            continue
        return cached_df.index[idx].strftime("%Y-%m-%d")
    return None


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
    macd_line_min: float = 0.0,
    macd_line_max: float = 10.0,
    turnover_min_pct: float = 0.0,
    turnover_max_pct: float = 100.0,
    pct_change_min: float = 5.0,
    apply_high: bool = True,
    apply_rsi: bool = True,
    apply_rsi_dev: bool = True,
    apply_rvol: bool = True,
    apply_avg_volume: bool = True,
    apply_price: bool = True,
    apply_price_dev: bool = True,
    apply_ema_dev: bool = True,
    apply_macd: bool = True,
    apply_macd_line: bool = False,
    apply_turnover: bool = False,
    apply_pct_change: bool = False,
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

    # Latest-bar % change vs prior close. Equivalent to the "% chg" column
    # the UI shows; gating here lets us early-exit before the expensive
    # streak / RSI / MACD work for tickers that didn't move enough today.
    if apply_pct_change:
        if prior_close <= 0:
            return None
        if ((prev_close - prior_close) / prior_close * 100.0) < pct_change_min:
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
    # MACD line (EMA12 - EMA26) gated by a min/max band — different from
    # the histogram filter above: this looks at the raw line value,
    # which is positive when EMA12 > EMA26 (bullish trend) and stays
    # near zero in ranging tape. macd_line_min = 0 keeps only stocks
    # in an established uptrend; raising the floor selects stronger
    # ones, raising the max excludes runaway extensions.
    if apply_macd_line and not (macd_line_min <= macd_val <= macd_line_max):
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
    momentum = compute_momentum_score(
        close=prev_close,
        rsi=rsi_val,
        rsi_dev_pct=rsi_dev_pct,
        price_ema21_dev_pct=price_ema21_dev_pct,
        ema21_ema50_dev_pct=ema21_ema50_dev_pct,
        macd_hist=macd_hist_val,
        macd_hist_prev=macd_hist_prev,
        rel_volume=rel_vol,
        breakout_pct=breakout * 100.0,
        turnover_pct=turnover_pct,
    )

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
        momentum_score=momentum,
        score=round(score, 4),
    )


def _evaluate_from_snapshot(
    ticker: str,
    as_of_date: str,
    row: dict,
    *,
    high_lookback: int,
    streak_mode: str,
    rsi_min: float,
    rsi_max: float,
    rsi_dev_min_pct: float,
    rsi_dev_max_pct: float,
    rvol_lookback: int,
    rvol_min: float,
    avg_volume_min: int,
    price_min: float,
    price_max: float,
    price_dev_min_pct: float,
    price_dev_max_pct: float,
    ema_dev_min_pct: float,
    ema_dev_max_pct: float,
    macd_hist_min: float,
    macd_require_rising: bool,
    macd_line_min: float,
    macd_line_max: float,
    turnover_min_pct: float,
    turnover_max_pct: float,
    pct_change_min: float,
    apply_high: bool,
    apply_rsi: bool,
    apply_rsi_dev: bool,
    apply_rvol: bool,
    apply_avg_volume: bool,
    apply_price: bool,
    apply_price_dev: bool,
    apply_ema_dev: bool,
    apply_macd: bool,
    apply_macd_line: bool,
    apply_turnover: bool,
    apply_pct_change: bool,
) -> ScreenHit | None:
    """Apply every filter against a single snapshot row + its trailing bars.
    Mirrors evaluate_ticker's gates but reads from a dict instead of a
    DataFrame so the snapshot-fast path doesn't materialise per-ticker
    indicator series."""
    close = row.get("close")
    prior_close = row.get("prior_close")
    volume = row.get("volume")
    if close is None or volume is None or prior_close is None:
        return None

    if apply_price and not (price_min <= close <= price_max):
        return None

    # Latest-bar % change vs prior close. Cheap early-exit before the
    # streak / RSI / MACD work for tickers that didn't move enough today.
    if apply_pct_change:
        if prior_close <= 0:
            return None
        if ((close - prior_close) / prior_close * 100.0) < pct_change_min:
            return None

    # recent_bars is JSONB; psycopg2 returns it as a dict. Tolerate str too
    # in case the column type ever changes to plain JSON.
    bars_payload = row.get("recent_bars")
    if isinstance(bars_payload, str):
        try:
            import json as _json
            bars_payload = _json.loads(bars_payload)
        except Exception:
            bars_payload = None
    bars = (bars_payload or {}).get("bars") or []
    if len(bars) < 2:
        return None

    # --- streak check (mirrors evaluate_ticker logic) ---------------------
    eval_streak_val = None
    streak_start_val = None
    streak_ok = False
    if streak_mode == "green":
        window = bars[-high_lookback:]
        if len(window) < high_lookback:
            return None
        try:
            streak_ok = all(b["c"] is not None and b["o"] is not None and b["c"] > b["o"]
                            for b in window)
        except (KeyError, TypeError):
            return None
        eval_streak_val = float(window[-1]["c"])
        streak_start_val = float(window[0]["c"])
    elif streak_mode == "close_green":
        window = bars[-(high_lookback + 1):]
        if len(window) < high_lookback + 1:
            return None
        try:
            closes = [float(b["c"]) for b in window]
            opens = [float(b["o"]) for b in window[1:]]
        except (KeyError, TypeError, ValueError):
            return None
        rising = all(closes[i] > closes[i - 1] for i in range(1, len(closes)))
        green = all(c > o for c, o in zip(closes[1:], opens))
        streak_ok = rising and green
        eval_streak_val = closes[-1]
        streak_start_val = closes[0]
    else:
        key = "h" if streak_mode == "high" else "c"
        window = bars[-(high_lookback + 1):]
        if len(window) < high_lookback + 1:
            return None
        try:
            vals = [float(b[key]) for b in window]
        except (KeyError, TypeError, ValueError):
            return None
        streak_ok = all(vals[i] > vals[i - 1] for i in range(1, len(vals)))
        eval_streak_val = vals[-1]
        streak_start_val = vals[0]
    if apply_high and not streak_ok:
        return None

    rsi_val = row.get("rsi14")
    if rsi_val is None:
        return None
    if apply_rsi and not (rsi_min <= rsi_val <= rsi_max):
        return None

    rsi_sma_val = row.get("rsi_sma9")
    if rsi_sma_val is None or rsi_sma_val == 0:
        return None
    rsi_dev_pct = (rsi_val - rsi_sma_val) / rsi_sma_val * 100.0
    if apply_rsi_dev and not (rsi_dev_min_pct <= rsi_dev_pct <= rsi_dev_max_pct):
        return None

    ema_val = row.get("ema21")
    if ema_val is None or ema_val == 0:
        return None
    price_ema21_dev_pct = (close - ema_val) / ema_val * 100.0
    if apply_price_dev and not (price_dev_min_pct <= price_ema21_dev_pct <= price_dev_max_pct):
        return None

    ema_long_val = row.get("ema50")
    if ema_long_val is None or ema_long_val == 0:
        return None
    ema21_ema50_dev_pct = (ema_val - ema_long_val) / ema_long_val * 100.0
    if apply_ema_dev and not (ema_dev_min_pct <= ema21_ema50_dev_pct <= ema_dev_max_pct):
        return None

    macd_hist_val = row.get("macd_hist")
    macd_hist_prev = row.get("macd_hist_prev")
    macd_val = row.get("macd")
    macd_signal_val = row.get("macd_signal")
    if macd_hist_val is None or macd_hist_prev is None:
        return None
    if apply_macd:
        if macd_hist_val < macd_hist_min:
            return None
        if macd_require_rising and not (macd_hist_val > macd_hist_prev):
            return None
    # MACD line (EMA12 - EMA26) gated by a min/max band — different from
    # the histogram filter above: this looks at the raw line value,
    # which is positive when EMA12 > EMA26 (bullish trend) and stays
    # near zero in ranging tape. macd_line_min = 0 keeps only stocks
    # in an established uptrend; raising the floor selects stronger
    # ones, raising the max excludes runaway extensions.
    if apply_macd_line and not (macd_line_min <= macd_val <= macd_line_max):
        return None

    # Relative volume — recompute against the user-specified lookback (the
    # `avg_volume` column in the snapshot is fixed to 10d; we need the
    # last `rvol_lookback` bars *before* the as_of bar).
    prior_window = bars[-(rvol_lookback + 1):-1]
    if len(prior_window) < rvol_lookback:
        return None
    prior_vols = [b.get("v") for b in prior_window if b.get("v") is not None]
    if not prior_vols:
        return None
    avg_volume = sum(prior_vols) / len(prior_vols)
    if not avg_volume:
        return None
    rel_vol = volume / avg_volume
    if apply_rvol and rel_vol <= rvol_min:
        return None
    if apply_avg_volume and avg_volume < avg_volume_min:
        return None

    shares_val = row.get("shares")
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
    market_cap = (shares_val * close) if shares_val else None

    pct_change = (close - prior_close) / prior_close * 100.0 if prior_close else 0.0
    exchange = "TSX" if ticker.endswith(".TO") else "US"
    breakout = (eval_streak_val - streak_start_val) / streak_start_val if streak_start_val else 0.0
    score = max(rel_vol, 0.01) * (1 + max(0.0, breakout))
    momentum = compute_momentum_score(
        close=close,
        rsi=rsi_val,
        rsi_dev_pct=rsi_dev_pct,
        price_ema21_dev_pct=price_ema21_dev_pct,
        ema21_ema50_dev_pct=ema21_ema50_dev_pct,
        macd_hist=macd_hist_val,
        macd_hist_prev=macd_hist_prev,
        rel_volume=rel_vol,
        breakout_pct=breakout * 100.0,
        turnover_pct=turnover_pct,
    )

    membership = lists_for(ticker)
    return ScreenHit(
        ticker=display_symbol(ticker),
        name=_company_name(ticker),
        exchange=exchange,
        lists=membership,
        list_labels=list_labels(membership),
        as_of_date=as_of_date,
        close=round(close, 4),
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
        macd=round(float(macd_val), 4) if macd_val is not None else 0.0,
        macd_signal=round(float(macd_signal_val), 4) if macd_signal_val is not None else 0.0,
        macd_hist=round(float(macd_hist_val), 4),
        macd_hist_prev=round(float(macd_hist_prev), 4),
        rel_volume=round(rel_vol, 2),
        avg_volume=round(avg_volume, 0),
        volume=round(volume, 0),
        shares=round(shares_val, 0) if shares_val else None,
        market_cap=round(market_cap, 0) if market_cap else None,
        turnover_pct=round(turnover_pct, 4) if turnover_pct is not None else None,
        momentum_score=momentum,
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
    macd_line_min: float = 0.0,
    macd_line_max: float = 10.0,
    turnover_min_pct: float = 0.0,
    turnover_max_pct: float = 100.0,
    pct_change_min: float = 5.0,
    apply_high: bool = True,
    apply_rsi: bool = True,
    apply_rsi_dev: bool = True,
    apply_rvol: bool = True,
    apply_avg_volume: bool = True,
    apply_price: bool = True,
    apply_price_dev: bool = True,
    apply_ema_dev: bool = True,
    apply_macd: bool = True,
    apply_macd_line: bool = False,
    apply_turnover: bool = False,
    apply_pct_change: bool = False,
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

    # --- snapshot-fast path -----------------------------------------------
    # If Postgres is configured and the chosen as_of_date has a snapshot,
    # serve the screen by streaming rows from the DB and evaluating each
    # in place. The streaming cursor caps memory at ~`chunk` rows —
    # crucial on the 512MB Render free tier where a single fetchall() of
    # the 7,800-row result set OOMs the worker (each row carries a ~5KB
    # JSONB recent_bars blob → ~100MB+ in Python dicts).
    if snapshots.enabled():
        target_date = _resolve_as_of_date(as_of_offset)
        if target_date and snapshots.has_date(target_date):
            ticker_set = set(tickers)
            snap_hits: list[ScreenHit] = []
            for tk_name, row in snapshots.iter_for_date(target_date, tickers):
                if tk_name not in ticker_set:
                    continue
                try:
                    hit = _evaluate_from_snapshot(
                        tk_name, target_date, row,
                        high_lookback=high_lookback,
                        streak_mode=streak_mode,
                        rsi_min=rsi_min, rsi_max=rsi_max,
                        rsi_dev_min_pct=rsi_dev_min_pct,
                        rsi_dev_max_pct=rsi_dev_max_pct,
                        rvol_lookback=rvol_lookback,
                        rvol_min=rvol_min,
                        avg_volume_min=avg_volume_min,
                        price_min=price_min, price_max=price_max,
                        price_dev_min_pct=price_dev_min_pct,
                        price_dev_max_pct=price_dev_max_pct,
                        ema_dev_min_pct=ema_dev_min_pct,
                        ema_dev_max_pct=ema_dev_max_pct,
                        macd_hist_min=macd_hist_min,
                        macd_require_rising=macd_require_rising,
                        macd_line_min=macd_line_min,
                        macd_line_max=macd_line_max,
                        turnover_min_pct=turnover_min_pct,
                        turnover_max_pct=turnover_max_pct,
                        pct_change_min=pct_change_min,
                        apply_high=apply_high, apply_rsi=apply_rsi,
                        apply_rsi_dev=apply_rsi_dev,
                        apply_rvol=apply_rvol,
                        apply_avg_volume=apply_avg_volume,
                        apply_price=apply_price,
                        apply_price_dev=apply_price_dev,
                        apply_ema_dev=apply_ema_dev,
                        apply_macd=apply_macd,
                        apply_macd_line=apply_macd_line,
                        apply_turnover=apply_turnover,
                        apply_pct_change=apply_pct_change,
                    )
                except Exception as exc:
                    log.warning("snapshot evaluate failed for %s: %s", tk_name, exc)
                    continue
                if hit is not None:
                    snap_hits.append(hit)
            snap_hits.sort(key=lambda h: h.score, reverse=True)
            log.info("screen served from snapshot: %d matches for %s",
                     len(snap_hits), target_date)
            return snap_hits

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
                macd_line_min=macd_line_min,
                macd_line_max=macd_line_max,
                turnover_min_pct=turnover_min_pct,
                turnover_max_pct=turnover_max_pct,
                pct_change_min=pct_change_min,
                apply_high=apply_high,
                apply_rsi=apply_rsi,
                apply_rsi_dev=apply_rsi_dev,
                apply_rvol=apply_rvol,
                apply_avg_volume=apply_avg_volume,
                apply_price=apply_price,
                apply_price_dev=apply_price_dev,
                apply_ema_dev=apply_ema_dev,
                apply_macd=apply_macd,
                apply_macd_line=apply_macd_line,
                apply_turnover=apply_turnover,
                apply_pct_change=apply_pct_change,
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
    macd_line_min: float = 0.0,
    macd_line_max: float = 10.0,
    turnover_min_pct: float = 0.0,
    turnover_max_pct: float = 100.0,
    pct_change_min: float = 5.0,
    apply_high: bool = True,
    apply_rsi: bool = True,
    apply_rsi_dev: bool = True,
    apply_rvol: bool = True,
    apply_avg_volume: bool = True,
    apply_price: bool = True,
    apply_price_dev: bool = True,
    apply_ema_dev: bool = True,
    apply_macd: bool = True,
    apply_macd_line: bool = False,
    apply_turnover: bool = False,
    apply_pct_change: bool = False,
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

    # 1b. Latest-bar % change vs prior close (must be ≥ threshold — a "green
    # day" filter when the threshold is ≥ 0).
    pct_change_val = None
    if prior_close and prior_close > 0 and prev_close == prev_close:  # NaN-safe
        pct_change_val = (prev_close - prior_close) / prior_close * 100.0
    pct_change_ok = pct_change_val is not None and pct_change_val >= pct_change_min
    add("pct_change", f"Latest bar % change ≥ {pct_change_min}%",
        round(pct_change_val, 2) if pct_change_val is not None else None,
        apply_pct_change, pct_change_ok, [pct_change_min, None],
        {"prior_close": round(prior_close, 4) if prior_close == prior_close else None})

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

    # 7b. MACD line (EMA12 - EMA26) range
    macd_line_val = _scalar("macd")
    macd_line_ok = (macd_line_val is not None
                    and macd_line_min <= macd_line_val <= macd_line_max)
    add("macd_line",
        f"MACD(12, 26) line ∈ [{macd_line_min}, {macd_line_max}]",
        round(macd_line_val, 4) if macd_line_val is not None else None,
        apply_macd_line, macd_line_ok, [macd_line_min, macd_line_max], None)

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
