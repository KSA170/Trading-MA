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
  RS — Relative strength. Ticker's **60-day** return percentile-
       ranked across the eligible universe. The longer window catches
       sustained leaders instead of recent gappers — a name up 40%
       three weeks ago dominates a 20-day ranking but is exhausted,
       not coiling.
  VA — Volume accumulation. 10d avg **share** volume / 60d avg.
       (Was $-volume; that conflated price moves with accumulation —
       a stock that ran up 30% on average share volume scored high
       VA even though nothing was being accumulated.)
  MT — Multi-timeframe trend alignment. Daily EMA stack (close >
       EMA21 > EMA50) + weekly 10w SMA support both pass = 100.
  DP — Distance to **30-day** pivot high. Bell curve peaks at 1.5%
       below the pivot, widened (σ=5) so stocks 5–10% off the pivot
       (textbook cup-and-handle bases) still score meaningfully.

Composite = weighted sum (default 25/25/20/15/15, tunable from UI).

Universe gates (applied BEFORE scoring — keep the pool to genuine
basing setups):

  Price band: $5–$1000 (tunable from UI).
  Liquidity:  ≥ $1M average daily $-volume over the last 60 sessions.
  Prior trend: close ≥ 1.20 × 60d low AND 50d SMA rising. Real bases
              form after an advance, not in dead-money names.
  Not extended: 60d return ≤ 80%. Above that the move is the move —
                no edge in calling a base on a parabolic.

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
    "vc": 20.0, "rs": 15.0, "va": 15.0, "mt": 10.0, "dp": 15.0, "sr": 25.0,
}
DEFAULT_PRICE_MIN: float = 5.0
DEFAULT_PRICE_MAX: float = 1000.0
# Stage 1 saves the top N; Stage 2 (intraday monitor) watches all of
# them and the UI displays all of them. Default 25, but tunable from
# the picks "Tune…" panel and persisted in picker_config.pick_limit.
DEFAULT_LIMIT: int = 25
MIN_LIMIT: int = 5
MAX_LIMIT: int = 100
INTRADAY_TRIGGER_TYPES: tuple[str, ...] = ("vwap_reclaim",)


def _clamp_limit(value) -> int:
    """Coerce a user-supplied pick limit into [MIN_LIMIT, MAX_LIMIT],
    falling back to DEFAULT_LIMIT on garbage input."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(MIN_LIMIT, min(MAX_LIMIT, n))


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
-- SR (SMA Reset) sub-score added later; backfill via ALTER ADD so the
-- column appears on existing deployments without manual migration.
-- Pattern: 4 SMAs converged after a downtrend and are now fanning out
-- bullish with SMA10 leading. Captures Stage 1 → Stage 2 transitions
-- that the original 5 IBD-style signals didn't reward.
ALTER TABLE nightly_picks ADD COLUMN IF NOT EXISTS sr_score REAL;
CREATE INDEX IF NOT EXISTS nightly_picks_ticker_idx
    ON nightly_picks (ticker, pick_date DESC);

CREATE TABLE IF NOT EXISTS picker_config (
    id          INT  PRIMARY KEY DEFAULT 1,
    weights     JSONB,
    price_min   REAL,
    price_max   REAL,
    updated_at  TIMESTAMPTZ DEFAULT now()
);
-- Toggle that lets the UI pause the picker-intraday workflow without
-- touching GitHub Actions. The workflow still fires every 5 min on
-- schedule, but exits immediately when this flag is FALSE.
ALTER TABLE picker_config
    ADD COLUMN IF NOT EXISTS intraday_alerts_enabled BOOLEAN NOT NULL DEFAULT TRUE;
-- How many top-ranked picks Stage 1 saves (and Stage 2 watches / the UI
-- shows). Tunable from the picks "Tune…" panel. Backfilled via ALTER ADD
-- so existing deployments pick up the column without manual migration.
ALTER TABLE picker_config
    ADD COLUMN IF NOT EXISTS pick_limit INT NOT NULL DEFAULT 25;

-- Stage 2: intraday triggers that fire on the nightly top-25 watchlist.
-- One row per (date, ticker, trigger_type) — dedupes so the cron can
-- run every 5 min idempotently and only emit a Telegram alert once.
CREATE TABLE IF NOT EXISTS picker_intraday_alerts (
    pick_date    DATE NOT NULL,
    ticker       TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    fired_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    price        REAL,
    vwap         REAL,
    details      TEXT,
    PRIMARY KEY (pick_date, ticker, trigger_type)
);
CREATE INDEX IF NOT EXISTS picker_intraday_alerts_date_idx
    ON picker_intraday_alerts (pick_date DESC, fired_at DESC);
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

def _is_warrant_unit_or_right(ticker: str) -> bool:
    """Per Nasdaq's 5-character ticker convention, the 5th letter
    encodes the security type. We exclude these from the watchlist:

      *W = warrant      (e.g. MOBBW, NUAIW)
      *U = unit         (SPAC pre-split)
      *R = rights

    These instruments derive their price from the underlying, have
    sparse trading history (often only a few months), and the 20-day
    return signal goes haywire when they climb off a near-zero base.

    The check is intentionally narrow — only triggers on 5-char,
    pure-letter, uppercase symbols (e.g. NYSE share-class symbols like
    'BRK-B' or TSX symbols like 'RY.TO' contain non-letters and pass
    through)."""
    if not ticker or len(ticker) != 5 or not ticker.isalpha():
        return False
    return ticker[-1] in ("W", "U", "R")


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
    # Hard floor: 60 bars. The VC and VA signals both denominate with
    # a 60-day average. Anything shorter triggers the "use fewer bars"
    # fallback that lets newly-listed warrants and SPACs through with
    # scoring artifacts (atr60 ≈ atr20 → neutral VC; 10d dvol >> all-
    # time dvol → score-100 VA on a price spike that's actually their
    # entire history).
    if not isinstance(bars, list) or len(bars) < 60:
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
    # Bar-count floor is enforced upstream in _bars_from_snapshot_row
    # (n >= 60). Both VC and VA need a full 60-bar denominator.
    atr20 = float(np.nanmean(tr[-20:]))
    atr60 = float(np.nanmean(tr[-60:]))
    if atr60 <= 0 or not np.isfinite(atr20) or not np.isfinite(atr60):
        return None
    vc_ratio = atr20 / atr60   # < 1 = contracting

    # --- RS: Relative Strength (60d return) ---------------------------
    # Use the full 60-bar window for a "3-month return" measure. The
    # previous 20-day version surfaced one-off gappers; 60d catches
    # sustained leaders, which is what we want for a base setup.
    # Reject tickers climbing off a near-zero base — that's the
    # warrant / penny-spike artifact (closes[-60] = $0.05, closes[-1] =
    # $2 → 3,900%, which clamps RS to 100). Require the start of the
    # window to be at least $1 to even count.
    if closes[-60] < 1.0:
        return None
    ret_60d = float(closes[-1] / closes[-60] - 1.0)

    # --- VA: Volume Accumulation (10d / 60d share volume) -------------
    # Use SHARE volume (not $-volume) so a price runup doesn't fake an
    # accumulation read. Liquidity floor is enforced separately on
    # dollar volume below.
    if not np.isfinite(vols).any():
        return None
    vol10 = float(np.nanmean(vols[-10:]))
    vol60 = float(np.nanmean(vols[-60:]))
    if vol60 <= 0 or not np.isfinite(vol10) or not np.isfinite(vol60):
        return None
    va_ratio = vol10 / vol60   # > 1 = accumulating

    # Absolute liquidity floor: at least $1M average daily dollar
    # volume over the last 60 sessions. Kills illiquid warrants and
    # micro-caps that the relative ratio alone lets slip through.
    dvol60 = float(np.nanmean(closes[-60:] * vols[-60:]))
    if not np.isfinite(dvol60) or dvol60 < 1_000_000:
        return None

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

    # --- DP: Distance to 30-day pivot high -----------------------------
    # Widened from 20d to 30d so the pivot represents a real base high,
    # not a recent 4-week swing. The DP bell-score itself (in
    # _dp_bell_score) also widens its tail so 5–10% bases score
    # meaningfully instead of getting trashed.
    high30 = float(np.nanmax(highs[-30:])) if n >= 30 else float(np.nanmax(highs))
    if high30 <= 0:
        return None
    dp_pct = float((high30 - last_close) / high30 * 100.0)

    # --- SR: SMA Reset score ------------------------------------------
    # Compute BEFORE the trend gates so SR-pattern names (which sit near
    # their lows by definition) can bypass the prior-uptrend gate. See
    # _sr_score for the pattern semantics.
    sr_raw = _sr_score(closes)

    # --- Universe gates ------------------------------------------------
    # Applied AFTER metric extraction so individual gate failures show up
    # in logs (return None drops the ticker silently from ranking).
    #
    # Gate 1 — Prior uptrend OR SR pattern. Real continuation bases form
    # after an advance, so we require close ≥ 1.20 × 60-bar low. But
    # SR-pattern tickers sit near their lows BY DEFINITION (the whole
    # point is they were in a downtrend that just ended); we let them
    # through when SR ≥ 30 (a meaningful reset signal, not just a noisy
    # detector ping).
    lo60 = float(np.nanmin(closes[-60:]))
    if not np.isfinite(lo60) or lo60 <= 0:
        return None
    if last_close < lo60 * 1.20 and sr_raw < 30.0:
        return None

    # Gate 2 — 50-day SMA rising OR SR pattern. Same exception: an SR
    # cluster forms while SMA50 is still flat-to-down, with the turn-up
    # happening simultaneously with or AFTER the cluster.
    sma50_now  = float(np.nanmean(closes[-50:]))
    sma50_then = float(np.nanmean(closes[-60:-10]))
    if not (np.isfinite(sma50_now) and np.isfinite(sma50_then)):
        return None
    if sma50_now <= sma50_then and sr_raw < 30.0:
        return None

    # Gate 3 — Not extended. A stock up 80% in 60 days is mid-move, not
    # mid-base; calling a base on it is wishful. Hard cap at +80%
    # (applies to SR pattern too — extension cap doesn't depend on the
    # signal type).
    if ret_60d > 0.80:
        return None

    return {
        "close":     last_close,
        "vc_ratio":  vc_ratio,
        # Field name is kept as ret_20d because the nightly_picks table
        # already has a `ret_20d` column; we store the new 60d return
        # value there. Migration would invalidate historical rows.
        "ret_20d":   ret_60d,
        "va_ratio":  va_ratio,
        "mt_raw":    mt_raw,
        "dp_pct":    dp_pct,
        "sr_raw":    sr_raw,
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
    """Distance-to-pivot bell curve. Peak at 1.5% below the 30-day high
    (ripe). σ widened from 2.5 to 5.0 so 5–10% bases still score
    meaningfully — textbook cup-and-handle bases end in that band, and
    the previous narrow bell (σ=2.5) trashed them (10% off → score ~0).
    The new curve:
      1.5% below pivot →  100   (ripe sweet spot, unchanged)
        5% below pivot →   77
       10% below pivot →   23
       15% below pivot →    3
    """
    if not np.isfinite(dp_pct):
        return float("nan")
    return 100.0 * math.exp(-((dp_pct - 1.5) ** 2) / (2.0 * 5.0 ** 2))


def _sr_score(closes_arr: np.ndarray) -> float:
    """SMA Reset score [0, 100]. Detects the pattern where the four
    SMAs (10/20/30/40) converged after a downtrend and are now fanning
    out bullish with SMA10 leading — i.e. the Stage 1 → Stage 2
    transition visible at the right edge of a "cluster then break"
    base.

    Five necessary conditions; any failure → 0.0:

      (1) Came from a bearish stack ~30 bars ago — SMA40 was above
          SMA10 then (long > short = was declining).
      (2) Convergence in the last 20 bars — the SMA spread reached
          a low of ≤ 3.5% of the cluster midpoint.
      (3) SMA10 has turned up — current SMA10 > SMA10 five bars ago.
      (4) Today's close is above all four SMAs (the break is
          starting).
      (5) Not yet exhausted — SMA10/SMA40 ≤ 1.10 (above that the
          move is already in progress and the SR window has closed).

    Score combines three factors when all conditions hold:
      tightness   — exp(-min_spread / 1.5%), favours tighter clusters
      freshness   — exp(-days_since_min_spread / 10), favours recent
                    convergence
      fan_out     — Gaussian centred at +3% (SMA10 over SMA40), so
                    "just starting to fan out" scores best and
                    "barely fanned out" / "already fanned out a lot"
                    both fall off.
    """
    n = len(closes_arr)
    if n < 60:
        return 0.0

    # Rolling SMAs over the input array. min_periods enforced by the
    # nan-padding so we never compare against a partial window.
    def _sma(arr: np.ndarray, w: int) -> np.ndarray:
        out = np.full(len(arr), np.nan, dtype=float)
        if len(arr) < w:
            return out
        kernel = np.full(w, 1.0 / w)
        out[w - 1:] = np.convolve(arr, kernel, mode="valid")
        return out

    s10 = _sma(closes_arr, 10)
    s20 = _sma(closes_arr, 20)
    s30 = _sma(closes_arr, 30)
    s40 = _sma(closes_arr, 40)

    s10_t, s20_t, s30_t, s40_t = s10[-1], s20[-1], s30[-1], s40[-1]
    if not (np.isfinite(s10_t) and np.isfinite(s20_t)
            and np.isfinite(s30_t) and np.isfinite(s40_t)):
        return 0.0
    last_close = float(closes_arr[-1])

    # (1) Came from downtrend. SMA40 isn't valid 30 bars back when the
    # input is exactly 60 bars (s40[-30] = NaN), so the "bearish stack"
    # version of this check would always fail at the boundary. Use raw
    # closes instead: the early portion of the window must have a peak
    # at least 5% above the lowest point in the cluster window. That
    # establishes "declining into the cluster" without an SMA dependency.
    early_high   = float(np.nanmax(closes_arr[-60:-30]))
    cluster_low  = float(np.nanmin(closes_arr[-30:-10]))
    if not (np.isfinite(early_high) and np.isfinite(cluster_low) and cluster_low > 0):
        return 0.0
    if not (early_high > cluster_low * 1.05):
        return 0.0

    # (2) Convergence in last 20 bars: find tightest SMA spread.
    smas = np.stack([s10, s20, s30, s40], axis=0)
    sma_max = np.nanmax(smas, axis=0)
    sma_min = np.nanmin(smas, axis=0)
    mid = (sma_max + sma_min) / 2.0
    spread = np.where(mid > 0, (sma_max - sma_min) / mid, np.nan)
    recent = spread[-20:]
    if not np.isfinite(recent).any():
        return 0.0
    min_spread = float(np.nanmin(recent))
    days_since_min = (len(recent) - 1) - int(np.nanargmin(recent))
    if min_spread > 0.035:
        return 0.0

    # (3) SMA10 has turned up.
    if not np.isfinite(s10[-6]):
        return 0.0
    if not (s10_t > s10[-6]):
        return 0.0

    # (4) Close above all four SMAs.
    if last_close < max(s10_t, s20_t, s30_t, s40_t):
        return 0.0

    # (5) Not yet exhausted: SMA10/SMA40 ≤ 1.10.
    if s40_t <= 0:
        return 0.0
    fan_ratio = s10_t / s40_t
    if fan_ratio > 1.10:
        return 0.0

    # Scoring factors, σ values tuned to realistic price-action ranges:
    #   tightness  σ = 2.5%   (typical real-stock cluster widths are 1-4%)
    #   freshness  σ = 15 bars (3 weeks)
    #   fan_out    σ = 6%     centred at +3% (sweet spot is "just starting
    #                          to fan out" — too little = pattern unconfirmed,
    #                          too much = move already done)
    tightness = math.exp(-min_spread / 0.025)
    freshness = math.exp(-days_since_min / 15.0)
    fan_x = max(0.0, fan_ratio - 1.0)
    fan_out = math.exp(-((fan_x - 0.03) / 0.06) ** 2)

    # Weighted sum (not product). The previous multiplicative form needed
    # every factor near 1.0 to score meaningfully — a 0.4 in any one
    # zeroed the result, which made the signal vanish on realistic data.
    # Sum is more forgiving: tightness leads (40%), freshness and fan-out
    # split the remainder (30% each).
    return float(100.0 * (0.40 * tightness + 0.30 * freshness + 0.30 * fan_out))


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
    skipped_warrants = 0
    for ticker, row in snapshots.iter_for_date(as_of):
        if _is_warrant_unit_or_right(ticker):
            skipped_warrants += 1
            continue
        close = row.get("close")
        if close is None or not (price_min <= float(close) <= price_max):
            continue
        m = _compute_raw_metrics(row)
        if m is None:
            continue
        m["ticker"] = ticker
        raw_rows.append(m)
    if skipped_warrants:
        log.info("picker: filtered out %d warrant/unit/right ticker(s)",
                 skipped_warrants)

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
    # SR is already absolute [0, 100] (not percentile-ranked) — using
    # the raw bell score directly so the magnitude of the SR signal
    # matters, not just its rank in the surviving pool. A pool of weak
    # SR scores shouldn't get artificially promoted.
    sr_arr = np.array([r.get("sr_raw", 0.0) for r in raw_rows], dtype=float)

    composites = (
        norm["vc"] * np.nan_to_num(vc_pct)
        + norm["rs"] * np.nan_to_num(rs_pct)
        + norm["va"] * np.nan_to_num(va_pct)
        + norm["mt"] * np.nan_to_num(mt_arr)
        + norm["dp"] * np.nan_to_num(dp_arr)
        + norm.get("sr", 0.0) * np.nan_to_num(sr_arr)
    )

    for i, r in enumerate(raw_rows):
        r["vc_score"]  = float(vc_pct[i]) if np.isfinite(vc_pct[i]) else None
        r["rs_score"]  = float(rs_pct[i]) if np.isfinite(rs_pct[i]) else None
        r["va_score"]  = float(va_pct[i]) if np.isfinite(va_pct[i]) else None
        r["mt_score"]  = float(mt_arr[i]) if np.isfinite(mt_arr[i]) else None
        r["dp_score"]  = float(dp_arr[i]) if np.isfinite(dp_arr[i]) else None
        r["sr_score"]  = float(sr_arr[i]) if np.isfinite(sr_arr[i]) else None
        r["composite"] = float(composites[i])

    raw_rows.sort(key=lambda r: -r["composite"])
    top = raw_rows[:limit]
    # Stamp rank + pick_date + persistence-name aliases so the live
    # response from /api/picks/run has the same shape as a load_picks()
    # response. The UI reads atr_ratio / dvol_ratio / dist_pivot — the
    # internal scoring uses vc_ratio / va_ratio / dp_pct — so we keep
    # both for compatibility.
    for idx, r in enumerate(top, start=1):
        r["rank"] = idx
        r["pick_date"] = as_of
        r["atr_ratio"]  = r.get("vc_ratio")
        r["dvol_ratio"] = r.get("va_ratio")
        r["dist_pivot"] = r.get("dp_pct")
    log.info(
        "picker.rank_universe: %d eligible, top composite %.1f, "
        "elapsed %.1fs", len(raw_rows), top[0]["composite"] if top else 0.0,
        time.time() - t0,
    )
    return top, as_of


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
                    "  vc_score, rs_score, va_score, mt_score, dp_score, sr_score, "
                    "  close, atr_ratio, ret_20d, dvol_ratio, dist_pivot"
                    ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (as_of, rank, p["ticker"], p["composite"],
                     p.get("vc_score"), p.get("rs_score"), p.get("va_score"),
                     p.get("mt_score"), p.get("dp_score"), p.get("sr_score"),
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
                    "vc_score, rs_score, va_score, mt_score, dp_score, sr_score, "
                    "close, atr_ratio, ret_20d, dvol_ratio, dist_pivot "
                    "FROM nightly_picks WHERE pick_date = %s ORDER BY rank",
                    (as_of,),
                )
            else:
                cur.execute(
                    "SELECT pick_date, rank, ticker, composite, "
                    "vc_score, rs_score, va_score, mt_score, dp_score, sr_score, "
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
                "sr_score":   float(r[9]) if r[9] is not None else None,
                "close":      float(r[10]) if r[10] is not None else None,
                "atr_ratio":  float(r[11]) if r[11] is not None else None,
                "ret_20d":    float(r[12]) if r[12] is not None else None,
                "dvol_ratio": float(r[13]) if r[13] is not None else None,
                "dist_pivot": float(r[14]) if r[14] is not None else None,
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
        "intraday_alerts_enabled": True,
        "pick_limit": DEFAULT_LIMIT,
    }
    if not snapshots.enabled():
        return cfg
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT weights, price_min, price_max, intraday_alerts_enabled, "
                "pick_limit "
                "FROM picker_config WHERE id = 1"
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
    if row[3] is not None:
        cfg["intraday_alerts_enabled"] = bool(row[3])
    if row[4] is not None:
        cfg["pick_limit"] = _clamp_limit(row[4])
    return cfg


def set_intraday_alerts_enabled(enabled: bool) -> bool:
    """Toggle the intraday-alerts kill-switch. Read by picker_intraday.py
    at startup; when FALSE the workflow exits immediately."""
    if not snapshots.enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            # UPSERT the singleton row — if the row doesn't exist yet
            # (fresh install), the other config fields stay NULL and
            # get_config falls back to module defaults.
            cur.execute(
                "INSERT INTO picker_config (id, intraday_alerts_enabled, updated_at) "
                "VALUES (1, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET "
                "intraday_alerts_enabled = EXCLUDED.intraday_alerts_enabled, "
                "updated_at = now()",
                (bool(enabled),),
            )
        return True
    except Exception as exc:
        log.warning("picker.set_intraday_alerts_enabled failed: %s", exc)
        return False


def save_config(weights: dict, price_min: float, price_max: float,
                pick_limit: int | None = None) -> bool:
    if not snapshots.enabled():
        return False
    # Filter the weights dict down to the known keys to keep the schema
    # honest if the caller throws extra keys at us.
    clean = {k: float(weights.get(k, DEFAULT_WEIGHTS[k])) for k in DEFAULT_WEIGHTS}
    # When pick_limit isn't supplied, preserve whatever is stored (or the
    # default) rather than clobbering it.
    limit = _clamp_limit(pick_limit) if pick_limit is not None else get_config()["pick_limit"]
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO picker_config "
                "(id, weights, price_min, price_max, pick_limit, updated_at) "
                "VALUES (1, %s, %s, %s, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET "
                "weights = EXCLUDED.weights, "
                "price_min = EXCLUDED.price_min, "
                "price_max = EXCLUDED.price_max, "
                "pick_limit = EXCLUDED.pick_limit, "
                "updated_at = now()",
                (json.dumps(clean), float(price_min), float(price_max), int(limit)),
            )
        return True
    except Exception as exc:
        log.warning("picker.save_config failed: %s", exc)
        return False


# --- intraday triggers (Stage 2) ------------------------------------------

def intraday_alerts_for_date(as_of: str | None = None) -> list[dict]:
    """Return all intraday trigger alerts that have fired on `as_of`
    (default: today's date in UTC). Newest first within each ticker."""
    if not snapshots.enabled():
        return []
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            if as_of:
                cur.execute(
                    "SELECT pick_date, ticker, trigger_type, fired_at, "
                    "price, vwap, details FROM picker_intraday_alerts "
                    "WHERE pick_date = %s ORDER BY fired_at DESC",
                    (as_of,),
                )
            else:
                cur.execute(
                    "SELECT pick_date, ticker, trigger_type, fired_at, "
                    "price, vwap, details FROM picker_intraday_alerts "
                    "WHERE pick_date = ("
                    "  SELECT MAX(pick_date) FROM picker_intraday_alerts"
                    ") ORDER BY fired_at DESC"
                )
            rows = cur.fetchall()
        return [
            {
                "pick_date":   r[0].isoformat() if r[0] else None,
                "ticker":      r[1],
                "trigger_type": r[2],
                "fired_at":    r[3].isoformat() if r[3] else None,
                "price":       float(r[4]) if r[4] is not None else None,
                "vwap":        float(r[5]) if r[5] is not None else None,
                "details":     r[6],
            }
            for r in rows
        ]
    except Exception as exc:
        log.warning("picker.intraday_alerts_for_date failed: %s", exc)
        return []


def already_fired(pick_date: str, ticker: str, trigger_type: str) -> bool:
    """Has this (date, ticker, trigger) already fired? Used by the
    intraday cron to dedupe across 5-min-cadence reruns."""
    if not snapshots.enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM picker_intraday_alerts WHERE pick_date = %s "
                "AND ticker = %s AND trigger_type = %s",
                (pick_date, ticker, trigger_type),
            )
            return cur.fetchone() is not None
    except Exception as exc:
        log.warning("picker.already_fired failed: %s", exc)
        return False


def record_intraday(
    pick_date: str, ticker: str, trigger_type: str,
    price: float | None, vwap: float | None, details: str,
) -> bool:
    """Idempotent insert. Returns True if this is a fresh trigger
    (caller should send Telegram). False if it was already recorded —
    dedupes across multiple cron runs."""
    if not snapshots.enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO picker_intraday_alerts "
                "(pick_date, ticker, trigger_type, price, vwap, details) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (pick_date, ticker, trigger_type) DO NOTHING",
                (pick_date, ticker, trigger_type, price, vwap, details),
            )
            # rowcount == 1 means a fresh insert; 0 means the conflict
            # path fired (already exists).
            return (cur.rowcount or 0) > 0
    except Exception as exc:
        log.warning("picker.record_intraday failed: %s", exc)
        return False
