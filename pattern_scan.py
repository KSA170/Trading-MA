"""
Base-breakout / momentum-ignition setup scanner.

Scores each stock 0-100 for the "HYLN-style" setup: a long quiet base,
then price curls up through both EMAs (with the EMA21/EMA50 cross
recently or in progress), volume explodes, MACD flips positive and
rising, and RSI surges out of the lows — caught early, before the
price is already extended.

The score is a transparent weighted blend of three sub-scores:

    Base quality    — was there a long quiet base before the move?
                      tightness  (low stddev/mean over the base)
                      MA convergence (EMA21 ~= EMA50 over the base)
                      quiet volume   (base volume below recent avg)
    Ignition        — is the move firing now?
                      price above both EMAs
                      EMA21/EMA50 cross recency
                      volume burst vs the base
                      MACD positive + rising + recently negative
                      RSI surge from base lows into healthy strength
    Earliness       — caught early, not already extended?
                      price not far above EMA21
                      EMA21/EMA50 gap not yet wide
                      RSI not yet overbought

Weights: base 0.35, ignition 0.45, earliness 0.20.

Operates on the daily_snapshot table's recent_bars JSONB (last 60
OHLCV bars per ticker) plus the row's last-bar indicator scalars
(ema21, ema50, rsi14, macd_hist, macd_hist_prev — computed on the
full 6-month history, so more accurate than recomputing on 60 bars).
"""

from __future__ import annotations

import logging
import math
from typing import Iterable

import numpy as np
import pandas as pd

import snapshots

log = logging.getLogger("pattern_scan")


# Score weights — sum to 1.0. Tune by inspecting the top-N output
# against known-good setups (HYLN-style) and known-bad ones.
W_BASE = 0.35
W_IGNITION = 0.45
W_EARLINESS = 0.20

# Window sizing on the 60-bar recent_bars frame.
IGNITION_BARS = 7       # last ~week — the breakout period
BASE_LOOKBACK_BARS = 35  # ~6-7 weeks of base before the ignition


def _bell(x: float, center: float, width: float) -> float:
    """Gaussian-shaped 0-1 bell centred at `center` with sigma `width`."""
    try:
        return math.exp(-((x - center) / width) ** 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _safe_float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def score_base_breakout(bars: list[dict],
                        last_scalars: dict | None = None) -> dict | None:
    """Score a single stock 0-100 for the base-breakout / momentum-
    ignition setup. Returns a dict with `score`, the three sub-scores,
    and a `breakdown` of every component metric — or None if the bar
    series is too short / unusable."""
    if not bars or len(bars) < 35:
        return None
    df = pd.DataFrame(bars)
    for col in ("o", "h", "l", "c", "v"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["c", "v"])
    n = len(df)
    if n < 35:
        return None

    closes = df["c"]
    volumes = df["v"]

    # Recompute indicators on the available window — fine because the
    # scoring uses trajectories, not absolute values. The last-bar
    # scalars from the snapshot override these where present (more
    # accurate, computed on the full 6-month history).
    ema21 = closes.ewm(span=21, adjust=False, min_periods=21).mean()
    ema50 = closes.ewm(span=50, adjust=False, min_periods=min(50, n - 1)).mean()
    ema12 = closes.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = closes.ewm(span=26, adjust=False, min_periods=26).mean()
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
    macd_hist = macd_line - macd_signal
    delta = closes.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    last_close = float(closes.iloc[-1])
    last_ema21 = float(ema21.iloc[-1]) if not pd.isna(ema21.iloc[-1]) else None
    last_ema50 = float(ema50.iloc[-1]) if not pd.isna(ema50.iloc[-1]) else None
    last_rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else None
    last_macd = float(macd_hist.iloc[-1]) if not pd.isna(macd_hist.iloc[-1]) else None

    # Prefer the snapshot's stored scalars (computed on the full 6-mo
    # history) over our 60-bar recomputation.
    if last_scalars:
        last_ema21 = _safe_float(last_scalars.get("ema21")) or last_ema21
        last_ema50 = _safe_float(last_scalars.get("ema50")) or last_ema50
        last_rsi = _safe_float(last_scalars.get("rsi14")) or last_rsi
        last_macd = _safe_float(last_scalars.get("macd_hist")) or last_macd

    if last_ema21 is None or last_ema50 is None or last_rsi is None or last_macd is None:
        return None

    # Define the base and ignition windows.
    ign_n = min(IGNITION_BARS, max(3, n // 6))
    base_end = n - ign_n
    base_start = max(0, base_end - BASE_LOOKBACK_BARS)
    base_closes = closes.iloc[base_start:base_end]
    base_vols = volumes.iloc[base_start:base_end]
    base_ema21 = ema21.iloc[base_start:base_end]
    base_ema50 = ema50.iloc[base_start:base_end]
    base_rsi = rsi.iloc[base_start:base_end]
    ign_vols = volumes.iloc[base_end:]
    if len(base_closes) < 15:
        return None

    # --- Base quality ---------------------------------------------------
    base_mean = float(base_closes.mean()) or 1.0
    base_std = float(base_closes.std()) if len(base_closes) > 1 else 0.0
    tightness_ratio = base_std / base_mean if base_mean else 1.0
    # Bell: tight base (stddev/mean ~0.03) = 1.0; ~0.12 = ~0.1.
    tightness_score = _bell(tightness_ratio, 0.0, 0.06)

    ma_diff = (base_ema21 - base_ema50).abs() / base_ema50.replace(0, np.nan)
    ma_conv = float(ma_diff.mean()) if ma_diff.notna().any() else 1.0
    # Bell: convergence ~0.01 = 1.0; ~0.10 = ~0.02.
    ma_score = _bell(ma_conv, 0.0, 0.05)

    overall_vol = float(volumes.mean()) or 1.0
    base_avg_vol = float(base_vols.mean()) if len(base_vols) else 1.0
    # Lower base volume relative to overall (which includes the ignition
    # spike) = the base really was quiet. Sigmoid: 0.5 at ratio 0.75.
    vol_ratio = base_avg_vol / overall_vol if overall_vol else 1.0
    vol_quiet_score = 1.0 / (1.0 + math.exp((vol_ratio - 0.75) * 6))

    # Flatness — was the base actually flat (not trending)? R² of a
    # linear fit through the base closes: near 0 = noisy/flat (good),
    # near 1 = smoothly trending (bad — could be a late-stage uptrend
    # or a downtrend feeding a V-bounce). This is the signal that
    # separates real base-breakouts from continuation-of-trend and
    # bounce-off-drop patterns that satisfy the surface filters.
    flatness_score = 0.5
    r_squared = None
    if len(base_closes) >= 8:
        try:
            x_arr = np.arange(len(base_closes), dtype=float)
            y_arr = base_closes.values.astype(float)
            slope, intercept = np.polyfit(x_arr, y_arr, 1)
            y_pred = slope * x_arr + intercept
            ss_res = float(np.sum((y_arr - y_pred) ** 2))
            ss_tot = float(np.sum((y_arr - y_arr.mean()) ** 2))
            if ss_tot > 0:
                r_squared = 1.0 - ss_res / ss_tot
                flatness_score = max(0.0, min(1.0, 1.0 - r_squared))
        except Exception:
            pass

    base_quality = (tightness_score + ma_score + vol_quiet_score
                    + flatness_score) / 4.0

    # --- Ignition strength ---------------------------------------------
    above_ema21 = last_close > last_ema21
    above_ema50 = last_close > last_ema50
    ema_pos_score = (1.0 if above_ema21 and above_ema50
                     else 0.5 if above_ema21 or above_ema50 else 0.0)

    # When did EMA21 most recently cross above EMA50? "Crossed below"
    # requires a *meaningful* gap (>0.5%) so noise-crossings on a flat
    # series don't masquerade as a real fresh ignition cross.
    cross_score = 0.15
    last_below_pos = -1
    for i in range(n - 1, -1, -1):
        e21 = ema21.iloc[i]; e50 = ema50.iloc[i]
        if pd.notna(e21) and pd.notna(e50) and e50 > 0:
            if (e21 - e50) / e50 < -0.005:
                last_below_pos = i
                break
    if last_below_pos >= 0:
        bars_since = n - 1 - last_below_pos
        if bars_since <= 5:
            cross_score = 1.0
        elif bars_since <= 10:
            cross_score = 0.7
        elif bars_since <= 20:
            cross_score = 0.4
        else:
            cross_score = 0.2

    ign_vol = float(ign_vols.mean()) if len(ign_vols) else 0.0
    vol_mult = ign_vol / base_avg_vol if base_avg_vol else 0.0
    if vol_mult >= 3.0:
        vol_burst_score = 1.0
    elif vol_mult >= 1.5:
        vol_burst_score = 0.5 + (vol_mult - 1.5) / 3.0
    elif vol_mult >= 1.0:
        vol_burst_score = (vol_mult - 1.0)
    else:
        vol_burst_score = 0.0

    # MACD ignition: positive, rising, recently flipped from negative.
    macd_neg_recent = False
    look_back = min(15, n)
    for i in range(n - look_back, n - 1):
        v = macd_hist.iloc[i]
        if pd.notna(v) and v < 0:
            macd_neg_recent = True
            break
    macd_score = 0.0
    if last_macd > 0:
        macd_score += 0.4
        prev = (_safe_float(last_scalars.get("macd_hist_prev")) if last_scalars else None)
        if prev is None and n >= 2 and pd.notna(macd_hist.iloc[-2]):
            prev = float(macd_hist.iloc[-2])
        if prev is not None and last_macd > prev:
            macd_score += 0.3
        if macd_neg_recent:
            macd_score += 0.3
    macd_score = min(1.0, macd_score)

    base_rsi_mean = float(base_rsi.mean()) if base_rsi.notna().any() else 50.0
    rsi_delta = last_rsi - base_rsi_mean
    if 55 <= last_rsi <= 75:
        rsi_pos_score = 1.0
    elif 45 <= last_rsi < 55:
        rsi_pos_score = 0.4 + (last_rsi - 45) * 0.06
    elif 75 < last_rsi <= 85:
        rsi_pos_score = 1.0 - (last_rsi - 75) * 0.05
    else:
        rsi_pos_score = 0.0
    rsi_surge_score = min(1.0, max(0.0, rsi_delta / 20.0))
    rsi_score = (rsi_pos_score + rsi_surge_score) / 2.0

    # Range expansion — did the ignition period actually show bigger
    # daily price ranges than the base? This is the smoking gun that
    # separates a real breakout from a smooth uptrend continuation:
    # HYLN expanded 3-5×, EP-PC-style trend continuations don't.
    def _range_pct(window):
        if len(window) < 2:
            return 0.0
        m = float(window.mean())
        if m <= 0:
            return 0.0
        return float((window.max() - window.min()) / m)

    ignition_closes = closes.iloc[base_end:]
    base_range_pct = _range_pct(base_closes)
    ign_range_pct = _range_pct(ignition_closes)
    range_exp_ratio = (ign_range_pct / base_range_pct
                       if base_range_pct > 0.0005 else 0.0)
    if range_exp_ratio >= 3.0:
        range_exp_score = 1.0
    elif range_exp_ratio >= 1.5:
        range_exp_score = 0.5 + (range_exp_ratio - 1.5) / 3.0
    elif range_exp_ratio >= 1.0:
        range_exp_score = max(0.0, range_exp_ratio - 1.0)
    else:
        range_exp_score = 0.0

    # Weighted blend — vol burst + range expansion are the truly
    # distinguishing signals for a real ignition (vs continuation or
    # bounce). "Price is near the MAs" gets little weight because
    # smooth uptrends also satisfy it without any real ignition.
    ignition = (
        0.05 * ema_pos_score
        + 0.15 * cross_score
        + 0.25 * vol_burst_score
        + 0.20 * macd_score
        + 0.10 * rsi_score
        + 0.25 * range_exp_score
    )

    # --- Earliness ------------------------------------------------------
    price_ema21_pct = ((last_close - last_ema21) / last_ema21 * 100
                      if last_ema21 else 0.0)
    if price_ema21_pct < 0:
        # Below EMA21 — the move hasn't really started; give partial credit.
        price_ema_score = max(0.0, 1.0 + price_ema21_pct / 5.0)
    elif price_ema21_pct <= 5:
        price_ema_score = 1.0
    elif price_ema21_pct <= 15:
        price_ema_score = 1.0 - (price_ema21_pct - 5) / 10.0
    else:
        price_ema_score = 0.0

    ema_gap_pct = ((last_ema21 - last_ema50) / last_ema50 * 100
                   if last_ema50 else 0.0)
    if ema_gap_pct < -2:
        ema_gap_score = 0.3
    elif ema_gap_pct <= 5:
        ema_gap_score = 1.0
    elif ema_gap_pct <= 12:
        ema_gap_score = 1.0 - (ema_gap_pct - 5) / 7.0
    else:
        ema_gap_score = 0.0

    if last_rsi <= 70:
        rsi_early_score = 1.0
    elif last_rsi <= 80:
        rsi_early_score = 1.0 - (last_rsi - 70) / 10.0
    else:
        rsi_early_score = 0.0

    earliness = (price_ema_score + ema_gap_score + rsi_early_score) / 3.0

    # Earliness only contributes when ignition is real — otherwise a
    # flat sideways stock (price ~= EMAs, RSI ~50, MA gap ~0) would
    # collect free earliness credit despite no actual move.
    ignition_gate = max(0.0, min(1.0, (ignition - 0.2) / 0.4))
    effective_earliness = earliness * ignition_gate

    score = 100.0 * (W_BASE * base_quality + W_IGNITION * ignition
                     + W_EARLINESS * effective_earliness)

    return {
        "score": round(score, 1),
        "base_quality": round(base_quality, 3),
        "ignition": round(ignition, 3),
        "earliness": round(earliness, 3),
        "close": round(last_close, 4),
        "breakdown": {
            "tightness_ratio": round(tightness_ratio, 4),
            "tightness_score": round(tightness_score, 3),
            "ma_convergence_ratio": round(ma_conv, 4),
            "ma_convergence_score": round(ma_score, 3),
            "base_volume_ratio": round(vol_ratio, 3),
            "volume_quiet_score": round(vol_quiet_score, 3),
            "base_r_squared": round(r_squared, 3) if r_squared is not None else None,
            "base_flatness_score": round(flatness_score, 3),
            "price_above_emas_score": round(ema_pos_score, 3),
            "cross_recency_score": round(cross_score, 3),
            "volume_burst_x": round(vol_mult, 2),
            "volume_burst_score": round(vol_burst_score, 3),
            "range_expansion_x": round(range_exp_ratio, 2),
            "range_expansion_score": round(range_exp_score, 3),
            "macd_score": round(macd_score, 3),
            "rsi_now": round(last_rsi, 1),
            "rsi_base_avg": round(base_rsi_mean, 1),
            "rsi_score": round(rsi_score, 3),
            "price_ema21_pct": round(price_ema21_pct, 2),
            "price_ema21_score": round(price_ema_score, 3),
            "ema_gap_pct": round(ema_gap_pct, 2),
            "ema_gap_score": round(ema_gap_score, 3),
            "rsi_early_score": round(rsi_early_score, 3),
        },
    }


def _prefilter_sql(as_of: str, min_price: float, max_price: float,
                   min_dollar_vol: float):
    """SQL that returns candidate snapshot rows likely to score well.
    Gates on:
      - the move has started (close > EMA21, MACD > 0, RSI in band)
      - price band (min_price / max_price)
      - liquidity (trailing 10-day avg daily dollar volume)
    Cuts the scan from ~7,800 to ~500-1,500 tickers, keeping
    /api/setups responsive."""
    sql = (
        "SELECT ticker, close, ema21, ema50, rsi14, macd_hist, "
        "macd_hist_prev, recent_bars "
        "FROM daily_snapshot "
        "WHERE as_of = %s "
        "  AND close IS NOT NULL AND close >= %s AND close <= %s "
        "  AND ema21 IS NOT NULL AND ema50 IS NOT NULL "
        "  AND close > ema21 "
        "  AND macd_hist IS NOT NULL AND macd_hist > 0 "
        "  AND rsi14 BETWEEN 45 AND 80 "
        "  AND avg_volume IS NOT NULL "
        "  AND avg_volume * close >= %s"
    )
    return sql, [as_of, float(min_price), float(max_price), float(min_dollar_vol)]


def scan_setups(as_of: str, min_score: float = 60.0, limit: int = 25,
                min_price: float = 3.0, max_price: float = 1000.0,
                min_dollar_vol: float = 1_000_000.0) -> list[dict]:
    """Scan today's snapshot for base-breakout candidates. Filters by
    score >= `min_score`, the price band [min_price, max_price], and
    trailing avg daily dollar volume >= `min_dollar_vol`. Returns up
    to `limit` rows sorted by score descending."""
    if not snapshots.enabled():
        return []
    sql, args = _prefilter_sql(as_of, min_price, max_price, min_dollar_vol)
    try:
        with snapshots._conn() as c, c.cursor(name="setups_scan") as cur:
            cur.itersize = 500
            cur.execute(sql, args)
            candidates = []
            for r in cur:
                ticker = r[0]
                row = {
                    "close": r[1], "ema21": r[2], "ema50": r[3],
                    "rsi14": r[4], "macd_hist": r[5], "macd_hist_prev": r[6],
                }
                bars_payload = r[7]
                if isinstance(bars_payload, str):
                    import json as _json
                    try:
                        bars_payload = _json.loads(bars_payload)
                    except Exception:
                        bars_payload = {}
                bars = (bars_payload or {}).get("bars") or []
                if len(bars) < 35:
                    continue
                try:
                    result = score_base_breakout(bars, row)
                except Exception as exc:
                    log.warning("score_base_breakout failed for %s: %s", ticker, exc)
                    continue
                if result is None or result["score"] < min_score:
                    continue
                result["ticker"] = ticker
                candidates.append(result)
    except Exception as exc:
        log.warning("scan_setups failed: %s", exc)
        return []
    candidates.sort(key=lambda x: x["score"], reverse=True)
    # Attach company names for the top N only — cheap lookup.
    top = candidates[:limit]
    try:
        from screener import _company_name
        for r in top:
            r["name"] = _company_name(r["ticker"])
    except Exception:
        for r in top:
            r["name"] = r["ticker"]
    return top
