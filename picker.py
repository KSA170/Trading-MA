"""
Nightly stock picker — ranks the universe by a 5-signal composite and
returns the top N candidates for swing-trade watchlist.

Independent of the existing screener / setups / alert engine. This
module is the Stage 1 (EOD ranking) half of a two-stage workflow:

  Stage 1 (this file): rank every snapshot ticker by precursor
    signals — runs nightly via GitHub Actions and on-demand from
    the UI. Output: top 10 tickers with sub-score breakdown.

  Stage 2 (separate, not yet built): intraday real-time monitor
    that watches the top-10 list and fires Telegram alerts when
    specific entry triggers fire (opening range break, VWAP
    reclaim, etc.).

The five signals are deliberately "precursor" signals (things that
appear *before* a breakout), not pattern-detection signals (things
that describe the breakout itself):

  VC — Volatility contraction (20d ATR / 60d ATR). Tight range +
       compressing → coiled spring.
  RS — Relative strength. Ticker's 20-day return percentile-ranked
       across the eligible universe.
  VA — Volume accumulation. 10d avg dollar volume / 60d avg.
       Above-average sustained dollar volume = institutional
       footprint.
  MT — Multi-timeframe trend alignment. Daily EMA stack (close >
       EMA21 > EMA50) + weekly 10w SMA support both pass = 100.
  DP — Distance to 20-day pivot high. Bell curve peaks at 1.5%
       below the pivot (ripe, not yet broken).

Composite = weighted sum (default 25/25/20/15/15, tunable from UI).
Top ranks are written to the nightly_picks Postgres table.
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Iterable

import numpy as np

import snapshots

log = logging.getLogger("picker")


# --- defaults --------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, float] = {
    "vc": 25.0, "rs": 25.0, "va": 20.0, "mt": 15.0, "dp": 15.0,
}
DEFAULT_PRICE_MIN: float = 5.0
DEFAULT_PRICE_MAX: float = 1000.0
DEFAULT_LIMIT: int = 10


# --- schema ----------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nightly_picks (
    pick_date    DATE NOT NULL,
    rank         INT  NOT NULL,
    ticker       TEXT NOT NULL,
    composite    REAL NOT NULL,
    vc_score     REAL,
    rs_score     REAL,
    va_score     REAL,
    mt_score     REAL,
    dp_score     REAL,
    -- Raw metric values, kept so the UI can show *why* a ticker
    -- scored where it did without recomputing.
    close        REAL,
    atr_ratio    REAL,
    ret_20d      REAL,
    dvol_ratio   REAL,
    dist_pivot   REAL,
    PRIMARY KEY (pick_date, rank)
);
CREATE INDEX IF NOT EXISTS nightly_picks_ticker_idx
    ON nightly_picks (ticker, pick_date DESC);

CREATE TABLE IF NOT EXISTS picker_config (
    id          INT  PRIMARY KEY DEFAULT 1,
    weights     JSONB,
    price_min   REAL,
    price_max   REAL,
    updated_at  TIMESTAMPTZ DEFAULT now()
);
"""


def init_tables() -> None:
    if not snapshots.enabled():
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(_SCHEMA)
    except Exception as exc:
        log.warning("picker.init_tables failed: %s", exc)


# --- raw signal extraction -------------------------------------------------

def _bars_from_snapshot_row(row: dict) -> list[dict] | None:
    """Pull the OHLCV bars list out of a snapshot row's recent_bars
    JSONB. Returns None if the row has too few or malformed bars."""
    rb = row.get("recent_bars")
    if rb is None:
        return None
    # psycopg2 returns JSONB as dict; tolerate str (rare).
    if isinstance(rb, str):
        try:
            rb = json.loads(rb)
        except Exception:
            return None
    if not isinstance(rb, dict):
        return None
    bars = rb.get("bars")
    if not isinstance(bars, list) or len(bars) < 21:
        # Need at least 21 bars for the 20-day return shift.
        return None
    return bars


def _compute_raw_metrics(row: dict) -> dict | None:
    """For one snapshot row, compute the raw values of all 5 signals.
    Returns None if the row can't yield a complete metric set."""
    bars = _bars_from_snapshot_row(row)
    if bars is None:
        return None

    # Extract numpy arrays of the OHLCV columns.
    try:
        closes = np.array([b.get("c") for b in bars], dtype=float)
        highs  = np.array([b.get("h") for b in bars], dtype=float)
        lows   = np.array([b.get("l") for b in bars], dtype=float)
        vols   = np.array([b.get("v") for b in bars], dtype=float)
    except Exception:
        return None
    if not np.isfinite(closes).any():
        return None
    last_close = float(closes[-1])
    if not np.isfinite(last_close) or last_close <= 0:
        return None

    # --- VC: Volatility Contraction (20d ATR / 60d ATR) ----------------
    # True range = max(h-l, |h - prev_c|, |l - prev_c|).
    n = len(closes)
    prev_c = np.concatenate(([closes[0]], closes[:-1]))
    tr = np.maximum.reduce([
        highs - lows,
        np.abs(highs - prev_c),
        np.abs(lows - prev_c),
    ])
    # Need at least 60 bars for the denominator; use what's available
    # but require ≥ 30 for a meaningful contraction read.
    if n < 30:
        return None
    atr20 = float(np.nanmean(tr[-20:])) if n >= 20 else float(np.nanmean(tr))
    atr60 = float(np.nanmean(tr[-60:])) if n >= 60 else float(np.nanmean(tr))
    if atr60 <= 0 or not np.isfinite(atr20) or not np.isfinite(atr60):
        return None
    vc_ratio = atr20 / atr60   # < 1 = contracting

    # --- RS: Relative Strength (20d return) ---------------------------
    if n < 21 or closes[-21] <= 0:
        return None
    ret_20d = float(closes[-1] / closes[-21] - 1.0)

    # --- VA: Volume Accumulation (10d dvol / 60d dvol) ----------------
    dvol = closes * vols
    if not np.isfinite(dvol).any():
        return None
    dvol10 = float(np.nanmean(dvol[-10:])) if n >= 10 else float(np.nanmean(dvol))
    dvol60 = float(np.nanmean(dvol[-60:])) if n >= 60 else float(np.nanmean(dvol))
    if dvol60 <= 0 or not np.isfinite(dvol10) or not np.isfinite(dvol60):
        return None
    va_ratio = dvol10 / dvol60   # > 1 = accumulating

    # --- MT: Multi-timeframe alignment ---------------------------------
    # Daily: snapshot row already carries EMA21 / EMA50 columns.
    ema21 = row.get("ema21")
    ema50 = row.get("ema50")
    daily_full = (
        ema21 is not None and ema50 is not None
        and last_close > float(ema21) > float(ema50)
    )
    daily_partial = (
        ema21 is not None and last_close > float(ema21)
    ) or (
        ema50 is not None and last_close > float(ema50)
    )
    # Weekly: resample 60 daily bars → ~12 weekly closes (last close of
    # each ISO week). 10-week SMA needs the last 10 of those.
    weekly_closes: list[float] = []
    last_iso_week = None
    for b in bars:
        d = b.get("d")
        c = b.get("c")
        if d is None or c is None:
            continue
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            iso = (dt.isocalendar().year, dt.isocalendar().week)
        except Exception:
            continue
        if iso == last_iso_week:
            weekly_closes[-1] = float(c)   # overwrite with later close in same week
        else:
            weekly_closes.append(float(c))
            last_iso_week = iso
    weekly_aligned = False
    if len(weekly_closes) >= 10:
        w_sma10 = float(np.mean(weekly_closes[-10:]))
        weekly_aligned = weekly_closes[-1] > w_sma10
    mt_raw = 0.0
    if daily_full:
        mt_raw += 50.0
    elif daily_partial:
        mt_raw += 25.0
    if weekly_aligned:
        mt_raw += 50.0

    # --- DP: Distance to 20-day pivot high -----------------------------
    high20 = float(np.nanmax(highs[-20:])) if n >= 20 else float(np.nanmax(highs))
    if high20 <= 0:
        return None
    dp_pct = float((high20 - last_close) / high20 * 100.0)

    return {
        "close":     last_close,
        "vc_ratio":  vc_ratio,
        "ret_20d":   ret_20d,
        "va_ratio":  va_ratio,
        "mt_raw":    mt_raw,
        "dp_pct":    dp_pct,
    }


# --- scoring ---------------------------------------------------------------

def _percentile_rank(values: list[float], ascending: bool = True) -> np.ndarray:
    """0-100 percentile rank for each value, NaN-tolerant. ``ascending=
    True`` means the smallest value gets rank 0; ``False`` flips it."""
    arr = np.asarray(values, dtype=float)
    finite_mask = np.isfinite(arr)
    n = int(finite_mask.sum())
    out = np.full_like(arr, np.nan)
    if n == 0:
        return out
    finite_idx = np.where(finite_mask)[0]
    finite_vals = arr[finite_idx]
    order = np.argsort(finite_vals, kind="mergesort")
    if not ascending:
        order = order[::-1]
    if n == 1:
        out[finite_idx[0]] = 50.0
        return out
    ranks = np.empty(n, dtype=float)
    ranks[order] = 100.0 * np.arange(n) / (n - 1)
    out[finite_idx] = ranks
    return out


def _dp_bell_score(dp_pct: float) -> float:
    """Distance-to-pivot bell curve. Peak at 1.5% below the 20-day high
    (ripe), drops off rapidly for "already broken" (negative dp) and
    gradually for "still too far below" (large positive dp)."""
    if not np.isfinite(dp_pct):
        return float("nan")
    return 100.0 * math.exp(-((dp_pct - 1.5) ** 2) / (2.0 * 2.5 ** 2))


def rank_universe(
    as_of: str | None = None,
    weights: dict | None = None,
    price_min: float = DEFAULT_PRICE_MIN,
    price_max: float = DEFAULT_PRICE_MAX,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[dict], str | None]:
    """Read the latest daily snapshot, compute the 5-signal composite
    per ticker, and return the top `limit` rows sorted by composite
    descending. Returns (picks, as_of_date_used)."""
    if not snapshots.enabled():
        log.warning("picker.rank_universe: snapshots disabled — returning empty list")
        return [], None

    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    total_w = sum(weights.values()) or 1.0
    norm = {k: v / total_w for k, v in weights.items()}

    if as_of is None:
        dates = snapshots.available_dates(1)
        if not dates:
            log.warning("picker.rank_universe: no snapshot data available")
            return [], None
        as_of = dates[0]

    t0 = time.time()
    raw_rows: list[dict] = []
    for ticker, row in snapshots.iter_for_date(as_of):
        close = row.get("close")
        if close is None or not (price_min <= float(close) <= price_max):
            continue
        m = _compute_raw_metrics(row)
        if m is None:
            continue
        m["ticker"] = ticker
        raw_rows.append(m)

    if not raw_rows:
        log.warning("picker.rank_universe: 0 eligible tickers for %s "
                    "(price %g-%g)", as_of, price_min, price_max)
        return [], as_of

    # Percentile-rank the universe per signal.
    vc_pct = 100.0 - _percentile_rank(
        [r["vc_ratio"] for r in raw_rows], ascending=True
    )  # low ratio = high score
    rs_pct = _percentile_rank(
        [r["ret_20d"] for r in raw_rows], ascending=True
    )
    va_pct = _percentile_rank(
        [r["va_ratio"] for r in raw_rows], ascending=True
    )
    mt_arr = np.array([r["mt_raw"] for r in raw_rows], dtype=float)
    dp_arr = np.array([_dp_bell_score(r["dp_pct"]) for r in raw_rows], dtype=float)

    composites = (
        norm["vc"] * np.nan_to_num(vc_pct)
        + norm["rs"] * np.nan_to_num(rs_pct)
        + norm["va"] * np.nan_to_num(va_pct)
        + norm["mt"] * np.nan_to_num(mt_arr)
        + norm["dp"] * np.nan_to_num(dp_arr)
    )

    for i, r in enumerate(raw_rows):
        r["vc_score"]  = float(vc_pct[i]) if np.isfinite(vc_pct[i]) else None
        r["rs_score"]  = float(rs_pct[i]) if np.isfinite(rs_pct[i]) else None
        r["va_score"]  = float(va_pct[i]) if np.isfinite(va_pct[i]) else None
        r["mt_score"]  = float(mt_arr[i]) if np.isfinite(mt_arr[i]) else None
        r["dp_score"]  = float(dp_arr[i]) if np.isfinite(dp_arr[i]) else None
        r["composite"] = float(composites[i])

    raw_rows.sort(key=lambda r: -r["composite"])
    log.info(
        "picker.rank_universe: %d eligible, top composite %.1f, "
        "elapsed %.1fs", len(raw_rows), raw_rows[0]["composite"], time.time() - t0,
    )
    return raw_rows[:limit], as_of


# --- persistence -----------------------------------------------------------

def save_picks(picks: list[dict], as_of: str) -> int:
    if not snapshots.enabled() or not picks or not as_of:
        return 0
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM nightly_picks WHERE pick_date = %s", (as_of,))
            for rank, p in enumerate(picks, start=1):
                cur.execute(
                    "INSERT INTO nightly_picks ("
                    "  pick_date, rank, ticker, composite, "
                    "  vc_score, rs_score, va_score, mt_score, dp_score, "
                    "  close, atr_ratio, ret_20d, dvol_ratio, dist_pivot"
                    ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (as_of, rank, p["ticker"], p["composite"],
                     p.get("vc_score"), p.get("rs_score"), p.get("va_score"),
                     p.get("mt_score"), p.get("dp_score"),
                     p.get("close"), p.get("vc_ratio"),
                     p.get("ret_20d"), p.get("va_ratio"), p.get("dp_pct")),
                )
        return len(picks)
    except Exception as exc:
        log.warning("picker.save_picks failed: %s", exc)
        return 0


def load_picks(as_of: str | None = None) -> list[dict]:
    """Read picks. If `as_of` is None, returns the most recent
    pick_date in the table."""
    if not snapshots.enabled():
        return []
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            if as_of:
                cur.execute(
                    "SELECT pick_date, rank, ticker, composite, "
                    "vc_score, rs_score, va_score, mt_score, dp_score, "
                    "close, atr_ratio, ret_20d, dvol_ratio, dist_pivot "
                    "FROM nightly_picks WHERE pick_date = %s ORDER BY rank",
                    (as_of,),
                )
            else:
                cur.execute(
                    "SELECT pick_date, rank, ticker, composite, "
                    "vc_score, rs_score, va_score, mt_score, dp_score, "
                    "close, atr_ratio, ret_20d, dvol_ratio, dist_pivot "
                    "FROM nightly_picks WHERE pick_date = "
                    "(SELECT MAX(pick_date) FROM nightly_picks) ORDER BY rank"
                )
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append({
                "pick_date":  r[0].isoformat() if r[0] else None,
                "rank":       int(r[1]),
                "ticker":     r[2],
                "composite":  float(r[3]),
                "vc_score":   float(r[4]) if r[4] is not None else None,
                "rs_score":   float(r[5]) if r[5] is not None else None,
                "va_score":   float(r[6]) if r[6] is not None else None,
                "mt_score":   float(r[7]) if r[7] is not None else None,
                "dp_score":   float(r[8]) if r[8] is not None else None,
                "close":      float(r[9])  if r[9]  is not None else None,
                "atr_ratio":  float(r[10]) if r[10] is not None else None,
                "ret_20d":    float(r[11]) if r[11] is not None else None,
                "dvol_ratio": float(r[12]) if r[12] is not None else None,
                "dist_pivot": float(r[13]) if r[13] is not None else None,
            })
        return out
    except Exception as exc:
        log.warning("picker.load_picks failed: %s", exc)
        return []


def get_config() -> dict:
    """Read picker config from DB. Falls back to module defaults if the
    table is empty or unreachable."""
    cfg = {
        "weights":   dict(DEFAULT_WEIGHTS),
        "price_min": DEFAULT_PRICE_MIN,
        "price_max": DEFAULT_PRICE_MAX,
    }
    if not snapshots.enabled():
        return cfg
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT weights, price_min, price_max FROM picker_config "
                "WHERE id = 1"
            )
            row = cur.fetchone()
    except Exception as exc:
        log.warning("picker.get_config failed: %s", exc)
        return cfg
    if not row:
        return cfg
    try:
        w = row[0]
        if isinstance(w, str):
            w = json.loads(w)
        if isinstance(w, dict):
            cfg["weights"] = {**DEFAULT_WEIGHTS, **{
                k: float(v) for k, v in w.items() if k in DEFAULT_WEIGHTS
            }}
    except Exception:
        pass
    if row[1] is not None:
        cfg["price_min"] = float(row[1])
    if row[2] is not None:
        cfg["price_max"] = float(row[2])
    return cfg


def save_config(weights: dict, price_min: float, price_max: float) -> bool:
    if not snapshots.enabled():
        return False
    # Filter the weights dict down to the known keys to keep the schema
    # honest if the caller throws extra keys at us.
    clean = {k: float(weights.get(k, DEFAULT_WEIGHTS[k])) for k in DEFAULT_WEIGHTS}
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO picker_config (id, weights, price_min, price_max, updated_at) "
                "VALUES (1, %s, %s, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET "
                "weights = EXCLUDED.weights, "
                "price_min = EXCLUDED.price_min, "
                "price_max = EXCLUDED.price_max, "
                "updated_at = now()",
                (json.dumps(clean), float(price_min), float(price_max)),
            )
        return True
    except Exception as exc:
        log.warning("picker.save_config failed: %s", exc)
        return False
