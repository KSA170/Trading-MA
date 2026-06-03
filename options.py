"""
Options recommendation engine — composite-score framework.

Pipeline for `recommend_for_ticker(ticker, dte_min=15, dte_max=60)`:

  1. Snapshot baseline — close, EMAs, MACD, RSI, sector, recent bars.
  2. Composite Score (0-100, 50 = neutral). Five weighted layers:

        Layer            Weight   Sub-signals
        ---------------- ------   ----------------------------------------
        Price            30%      RSI, MACD, EMA stack, volume spike
        Catalyst         25%      Earnings timing, analyst upgrades/downgr
        Institutional    20%      Insider Form 4 + analyst sentiment proxy
                                  (dark pool / unusual flow / 13F deferred —
                                  requires paid data; flagged "partial")
        Fundamentals     15%      Revenue YoY, P/E reasonableness
        Sector           10%      Sector ETF 5d vs SPY 5d

     Each sub-signal scores 0-100 (50 = neutral). Layer score is the
     mean of its sub-signals. Composite = weighted sum.

  3. Direction + verdict from composite:
        >= 65   → BUY CALL
        >= 50   → WATCH (mild bull, not enough conviction)
        <= 35   → BUY PUT
        <= 50   → WATCH (mild bear)
        else    → no trade

  4. Conviction → strike target:
        >= 80 or <= 20  → high conviction → 1-step OTM
        65-79 or 21-35  → medium conviction → ATM

  5. Expiry selection:
        normally        → within user-specified DTE window (default 15-60)
        catalyst near   → if next earnings falls inside DTE window, pick
                          expiration 7-10 days AFTER earnings instead
                          (avoids holding through IV crush).

  6. Quality gates per contract: OI >= 100, spread <= 15% of mid,
     delta in [0.30, 0.65].

  7. IV context (separate from composite): ATM IV vs 20d realized vol.
     "Rich" IV downgrades borderline BUY → WATCH. Cheap IV strengthens
     the rationale but doesn't change the verdict.

  8. Natural-language paragraph rationale + bullet-point reasons.

Informational only — surfaces a disclaimer flag on every recommendation.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta
from typing import Any

log = logging.getLogger("options")


# --- tuning constants -----------------------------------------------------

# Default DTE window — user can override per request.
DEFAULT_DTE_MIN         = 15
DEFAULT_DTE_MAX         = 60

# Composite-score layer weights (must sum to 1.0).
WEIGHTS = {
    "price":         0.30,
    "catalyst":      0.25,
    "institutional": 0.20,
    "fundamentals":  0.15,
    "sector":        0.10,
}

# Verdict thresholds on composite (0-100; 50 = neutral).
SCORE_CALL_BUY      = 65
SCORE_PUT_BUY       = 35
# High-conviction band — empirically reachable when ~4 of the 5
# layers stack bullishly. Symmetric on the bear side (<= 25).
SCORE_HIGH_CONV     = 75
SCORE_MED_CONV      = SCORE_CALL_BUY

# Contract quality gates (per user spec)
OI_FLOOR                = 100
SPREAD_FRAC_MAX         = 0.15
DELTA_BAND              = (0.30, 0.65)

# Earnings catalyst override window
POST_EARNINGS_DTE_MIN   = 7
POST_EARNINGS_DTE_MAX   = 10

PRICE_FLOOR             = 20.0   # strike granularity floor
RISK_FREE_RATE          = 0.045

# Sector ETF mapping for the Sector layer
_SECTOR_ETFS = {
    "Technology":             "XLK",
    "Communication Services": "XLC",
    "Financial Services":     "XLF",
    "Energy":                 "XLE",
    "Healthcare":             "XLV",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    "Industrials":            "XLI",
    "Basic Materials":        "XLB",
    "Utilities":              "XLU",
    "Real Estate":            "XLRE",
}


# --- schema ---------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS options_recommendations (
    as_of            DATE NOT NULL,
    ticker           TEXT NOT NULL,
    direction        TEXT,
    verdict          TEXT NOT NULL,
    score            REAL NOT NULL,
    contract_symbol  TEXT,
    strike           REAL,
    expiration       DATE,
    dte              INT,
    mid_price        REAL,
    delta            REAL,
    iv               REAL,
    open_interest    INT,
    rationale        TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, ticker)
);

-- New columns for the composite-score build (idempotent — IF NOT EXISTS)
ALTER TABLE options_recommendations ADD COLUMN IF NOT EXISTS composite_score      REAL;
ALTER TABLE options_recommendations ADD COLUMN IF NOT EXISTS layer_scores         JSONB;
ALTER TABLE options_recommendations ADD COLUMN IF NOT EXISTS conviction           TEXT;
ALTER TABLE options_recommendations ADD COLUMN IF NOT EXISTS prose_rationale      TEXT;
ALTER TABLE options_recommendations ADD COLUMN IF NOT EXISTS dte_window           TEXT;
ALTER TABLE options_recommendations ADD COLUMN IF NOT EXISTS post_earnings_override BOOLEAN;

CREATE TABLE IF NOT EXISTS options_iv_history (
    ticker      TEXT NOT NULL,
    as_of       DATE NOT NULL,
    atm_iv      REAL NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, as_of)
);

-- Single-row config table for the universe scanner. `id` is always 1
-- (enforced by the CHECK constraint) — the UI's "Save defaults" upserts
-- this row, and the cron + manual scan endpoints fall back to it when
-- a request body doesn't override.
CREATE TABLE IF NOT EXISTS options_scan_config (
    id                       INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    price_floor              REAL NOT NULL,
    volume_floor             BIGINT NOT NULL,
    min_directional_distance REAL NOT NULL,
    top_n                    INT NOT NULL,
    dte_min                  INT NOT NULL,
    dte_max                  INT NOT NULL,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def init_tables() -> None:
    import snapshots
    if not snapshots.enabled():
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(_SCHEMA)
    except Exception as exc:
        log.warning("options.init_tables failed: %s", exc)


# --- math helpers ---------------------------------------------------------

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_delta(spot: float, strike: float, t_years: float,
              sigma: float, is_call: bool,
              r: float = RISK_FREE_RATE) -> float:
    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * math.sqrt(t_years))
    cdf_d1 = _norm_cdf(d1)
    return cdf_d1 if is_call else (cdf_d1 - 1.0)


def _realized_vol_20d(closes: list[float]) -> float | None:
    if not closes or len(closes) < 21:
        return None
    rets = []
    for i in range(len(closes) - 20, len(closes)):
        prev, curr = closes[i - 1], closes[i]
        if prev > 0 and curr > 0:
            rets.append(math.log(curr / prev))
    if len(rets) < 10:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _to_f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


# --- layer scorers (each returns {score, sub_scores, reasons}) -----------

def _score_price_trajectory(snap_row: dict | None,
                            avg_vol_20: float | None) -> dict:
    """Layer 1 — Price Trajectory (30% of composite).
    Sub-signals: RSI, MACD, EMA stack, volume spike. All normalized 0-100.

    A sub-signal is *skipped* (not defaulted to 50) when its raw inputs
    are missing — the composite renormalizes over present sub-signals
    only, so missing data doesn't drag the layer back to neutral.
    Genuinely-neutral readings (e.g. RSI 46-55) still score 50 and
    contribute, since that *is* a real signal."""
    subs: dict[str, float] = {}
    reasons: list[str] = []

    rsi = _to_f((snap_row or {}).get("rsi"))
    macd_val  = _to_f((snap_row or {}).get("macd"))
    macd_hist = _to_f((snap_row or {}).get("macd_hist"))
    ema21 = _to_f((snap_row or {}).get("ema21"))
    ema50 = _to_f((snap_row or {}).get("ema50"))
    close = _to_f((snap_row or {}).get("close"))
    prior = _to_f((snap_row or {}).get("prior_close"))
    vol_today = _to_f((snap_row or {}).get("volume"))

    # RSI: oversold rebound bullish, overbought = bear exhaustion, midband mild
    if rsi is not None:
        if   rsi <= 30: subs["rsi"] = 75.0; reasons.append(f"RSI {rsi:.0f} oversold (bullish bounce setup)")
        elif rsi <= 45: subs["rsi"] = 60.0; reasons.append(f"RSI {rsi:.0f} (mild bull)")
        elif rsi <= 55: subs["rsi"] = 50.0
        elif rsi <= 65: subs["rsi"] = 55.0
        elif rsi <= 75: subs["rsi"] = 35.0; reasons.append(f"RSI {rsi:.0f} approaching overbought")
        else:           subs["rsi"] = 20.0; reasons.append(f"RSI {rsi:.0f} overbought")

    # MACD: combine line sign + histogram momentum
    if macd_val is not None or macd_hist is not None:
        m = 50.0
        if macd_val is not None:
            m += 15.0 if macd_val > 0 else -15.0
        if macd_hist is not None:
            m += 15.0 if macd_hist > 0 else -15.0
        subs["macd"] = _clamp(m)
        if (macd_val or 0) > 0 and (macd_hist or 0) > 0:
            reasons.append("MACD positive + histogram rising (bull)")
        elif (macd_val or 0) < 0 and (macd_hist or 0) < 0:
            reasons.append("MACD negative + histogram falling (bear)")

    # EMA stack — we have 21/50 from the snapshot (not 200, but the
    # short/medium relationship still captures trend direction).
    if ema21 is not None and ema50 is not None and close is not None:
        if close > ema21 > ema50:
            subs["ma_stack"] = 85.0; reasons.append("Price > EMA21 > EMA50 (bullish stack)")
        elif close > ema21 and ema21 > ema50:
            subs["ma_stack"] = 75.0
        elif close > ema21 and ema21 < ema50:
            subs["ma_stack"] = 55.0
        elif close < ema21 < ema50:
            subs["ma_stack"] = 15.0; reasons.append("Price < EMA21 < EMA50 (bearish stack)")
        elif close < ema21:
            subs["ma_stack"] = 30.0
        else:
            subs["ma_stack"] = 50.0

    # Volume spike — needs today's volume vs 20-day avg
    if close is not None and prior is not None and vol_today is not None and avg_vol_20:
        rel = vol_today / avg_vol_20 if avg_vol_20 > 0 else 1.0
        moved_up = close >= prior
        if rel >= 2.0 and moved_up:
            subs["volume"] = 85.0; reasons.append(f"Volume {rel:.1f}× avg on up-move (accumulation)")
        elif rel >= 1.5 and moved_up:
            subs["volume"] = 70.0
        elif rel >= 2.0 and not moved_up:
            subs["volume"] = 15.0; reasons.append(f"Volume {rel:.1f}× avg on down-move (distribution)")
        elif rel >= 1.5 and not moved_up:
            subs["volume"] = 30.0
        elif rel <= 0.5:
            subs["volume"] = 50.0   # quiet day — neutral
        else:
            subs["volume"] = 55.0 if moved_up else 45.0

    score = (sum(subs.values()) / len(subs)) if subs else None
    return {
        "score": round(score, 1) if score is not None else None,
        "sub_scores": {k: round(v, 1) for k, v in subs.items()},
        "reasons": reasons,
    }


def _score_catalyst(news: list[dict] | None,
                    earnings_date: str | None,
                    analyst_recs: dict | None,
                    dte_max: int) -> dict:
    """Layer 2 — Catalyst Events (25%).
    Sub-signals: earnings timing, analyst upgrades/downgrades, news volume.

    Each sub is *skipped* when its underlying data isn't available — so
    a stock with no analyst coverage and no recent news doesn't get
    penalized by neutral defaults; the composite renormalizes over the
    layers that do have data."""
    subs: dict[str, float] = {}
    reasons: list[str] = []

    # Earnings timing — earnings near = slightly bull tactically.
    if earnings_date:
        try:
            ed = datetime.strptime(earnings_date, "%Y-%m-%d").date()
            d = (ed - date.today()).days
            if 0 <= d <= dte_max:
                subs["earnings_timing"] = 60.0
                reasons.append(f"Earnings in {d}d (catalyst within window)")
            elif d < 0 and d >= -7:
                subs["earnings_timing"] = 55.0
                reasons.append(f"Earnings {abs(d)}d ago (post-event move continues)")
            else:
                subs["earnings_timing"] = 50.0
        except (TypeError, ValueError):
            pass   # unparseable date → no data, skip the sub-signal

    # Analyst upgrades / downgrades — net actions in last 30 days
    if analyst_recs and "net_30d" in analyst_recs:
        net = int(analyst_recs["net_30d"])
        if   net >= 3:  subs["analyst"] = 80.0; reasons.append(f"+{net} net analyst upgrades 30d")
        elif net >= 1:  subs["analyst"] = 65.0; reasons.append(f"+{net} net analyst upgrade(s) 30d")
        elif net == 0:  subs["analyst"] = 50.0
        elif net >= -2: subs["analyst"] = 35.0; reasons.append(f"{net} net analyst downgrade(s) 30d")
        else:           subs["analyst"] = 20.0; reasons.append(f"{net} net analyst downgrades 30d")

    # News count — secondary tailwind / not directional on its own
    if news:
        n = len(news)
        if   n >= 3: subs["news_volume"] = 60.0; reasons.append(f"{n} recent catalyst stories")
        elif n >= 1: subs["news_volume"] = 55.0

    score = (sum(subs.values()) / len(subs)) if subs else None
    return {
        "score": round(score, 1) if score is not None else None,
        "sub_scores": {k: round(v, 1) for k, v in subs.items()},
        "reasons": reasons,
    }


def _score_institutional(insider: dict | None,
                         analyst_summary: dict | None) -> dict:
    """Layer 3 — Institutional Activity (20%).

    Note: dark pool prints + true unusual options flow require paid
    feeds we don't have. SEC EDGAR 13F is available but quarterly +
    lagged; deferred.

    Sub-signals we can measure: insider Form 4 + analyst recommendation
    summary (Strong Buy / Buy / Hold / Sell counts)."""
    subs: dict[str, float] = {}
    reasons: list[str] = []
    partial = True  # always partial without paid feeds; surfaces in UI

    # Insider Form 4 — skip the sub-signal entirely when no recent
    # filing exists, rather than defaulting to neutral 50.
    if insider:
        code = (insider.get("code") or "").upper()
        recent = _is_recent_insider(insider, max_days=30)
        if recent and code == "P":
            subs["insider"] = 75.0; reasons.append("recent insider BUY (Form 4)")
        elif recent and code == "S":
            subs["insider"] = 35.0; reasons.append("recent insider SELL (Form 4)")
        elif code == "P":
            subs["insider"] = 60.0
        elif code == "S":
            subs["insider"] = 45.0
        # else: stale unknown-code filing — no useful signal, skip.

    # Analyst summary — sentiment proxy.
    # analyst_summary expected: {'strong_buy': n, 'buy': n, 'hold': n,
    # 'sell': n, 'strong_sell': n}. yfinance .recommendations_summary
    # gives this directly.
    if analyst_summary:
        sb = int(analyst_summary.get("strong_buy") or 0)
        bu = int(analyst_summary.get("buy") or 0)
        ho = int(analyst_summary.get("hold") or 0)
        se = int(analyst_summary.get("sell") or 0)
        ss = int(analyst_summary.get("strong_sell") or 0)
        total = sb + bu + ho + se + ss
        if total > 0:
            bull = (sb * 1.0 + bu * 0.6) / total
            bear = (ss * 1.0 + se * 0.6) / total
            tilt = bull - bear   # -1 (full bear) .. +1 (full bull)
            subs["analyst_summary"] = _clamp(50 + tilt * 40)
            if tilt > 0.3 or tilt < -0.3:
                reasons.append(f"{sb + bu} buy / {se + ss} sell across {total} analysts")

    score = (sum(subs.values()) / len(subs)) if subs else None
    return {
        "score": round(score, 1) if score is not None else None,
        "sub_scores": {k: round(v, 1) for k, v in subs.items()},
        "reasons": reasons,
        "partial_data": partial,
        "missing": ["dark_pool_prints", "unusual_options_flow", "13f_changes"],
    }


def _score_fundamentals(fund: dict | None) -> dict:
    """Layer 4 — Fundamentals (15%). Revenue growth YoY + P/E reasonableness.

    Skips each sub-signal when its underlying data is unavailable
    (rather than defaulting to 50). If `fund` is None entirely or
    contains nothing usable, the layer returns score=None and the
    composite renormalizes over the remaining layers."""
    subs: dict[str, float] = {}
    reasons: list[str] = []

    if fund:
        rev = fund.get("revenue_growth_yoy")
        if isinstance(rev, (int, float)):
            r = float(rev) * 100  # to percent
            if   r >= 30:  subs["revenue"] = 90.0; reasons.append(f"revenue +{r:.0f}% YoY")
            elif r >= 15:  subs["revenue"] = 75.0; reasons.append(f"revenue +{r:.0f}% YoY")
            elif r >=  5:  subs["revenue"] = 60.0
            elif r >=  0:  subs["revenue"] = 52.0
            elif r >= -10: subs["revenue"] = 40.0
            elif r >= -25: subs["revenue"] = 25.0; reasons.append(f"revenue {r:.0f}% YoY")
            else:          subs["revenue"] = 15.0; reasons.append(f"revenue {r:.0f}% YoY")

        pe = fund.get("trailing_pe") or fund.get("forward_pe")
        if isinstance(pe, (int, float)) and pe > 0:
            p = float(pe)
            if   p < 10: subs["pe"] = 50.0
            elif p < 25: subs["pe"] = 62.0
            elif p < 40: subs["pe"] = 48.0
            else:        subs["pe"] = 38.0; reasons.append(f"P/E {p:.0f} elevated")

    score = (sum(subs.values()) / len(subs)) if subs else None
    return {
        "score": round(score, 1) if score is not None else None,
        "sub_scores": {k: round(v, 1) for k, v in subs.items()},
        "reasons": reasons,
    }


def _score_sector(sector: str | None,
                  sector_5d: float | None,
                  spy_5d: float | None) -> dict:
    """Layer 5 — Sector Trend (10%). Sector ETF 5d move minus SPY 5d move.

    Skipped (score=None) when either the sector ETF or SPY 5d-move
    fetch failed — the composite renormalizes over the remaining
    layers. SPY almost always resolves, so the common reason for skip
    is a ticker with no mapped sector."""
    subs: dict[str, float] = {}
    reasons: list[str] = []

    etf = _SECTOR_ETFS.get(sector) if sector else None

    if sector_5d is not None and spy_5d is not None:
        rel = sector_5d - spy_5d   # in percent
        if   rel >=  3: subs["sector_vs_spy"] = 85.0; reasons.append(f"{etf or 'sector'} +{rel:.1f}% vs SPY (strong tailwind)")
        elif rel >=  1: subs["sector_vs_spy"] = 65.0; reasons.append(f"{etf or 'sector'} +{rel:.1f}% vs SPY")
        elif rel >= -1: subs["sector_vs_spy"] = 50.0
        elif rel >= -3: subs["sector_vs_spy"] = 35.0; reasons.append(f"{etf or 'sector'} {rel:.1f}% vs SPY")
        else:           subs["sector_vs_spy"] = 15.0; reasons.append(f"{etf or 'sector'} {rel:.1f}% vs SPY (strong headwind)")

    score = (sum(subs.values()) / len(subs)) if subs else None
    return {
        "score": round(score, 1) if score is not None else None,
        "sub_scores": {k: round(v, 1) for k, v in subs.items()},
        "reasons": reasons,
        "sector_etf": etf,
    }


# --- composite scorer -----------------------------------------------------

def _composite(layers: dict) -> dict:
    """Weighted sum of layer scores, renormalized over layers with data.

    A layer with score=None (i.e. all its sub-signals lacked source
    data — common for mid/small caps with no analyst coverage or
    sparse fundamentals) is *excluded* from both the numerator and
    denominator. So a ticker with strong Price+Sector signals but no
    Catalyst/Institutional/Fundamentals data is scored as
    (0.30·price + 0.10·sector) / 0.40 instead of being dragged
    toward 50 by three neutral defaults.

    `used_weight` is also returned so the UI / digest can warn when
    a verdict came from very thin layer coverage (e.g. only Price)."""
    total = 0.0
    used_weight = 0.0
    contributing: list[str] = []
    for key, w in WEIGHTS.items():
        layer = layers.get(key) or {}
        s = layer.get("score")
        if s is None:
            continue
        total += w * float(s)
        used_weight += w
        contributing.append(key)
    score = total / used_weight if used_weight > 0 else 50.0
    return {
        "score": round(score, 1),
        "weights": WEIGHTS,
        "used_weight": round(used_weight, 3),
        "contributing_layers": contributing,
    }


def _verdict(composite_score: float, iv_rich: bool) -> tuple[str, str, str]:
    """Map composite + IV-rich flag → (verdict, direction, conviction).
    IV-rich downgrades borderline BUY (65-69) to WATCH because option
    premium is unfavorable for a long-premium directional bet."""
    s = composite_score
    if s >= SCORE_HIGH_CONV:
        return ("BUY", "call", "high")
    if s >= SCORE_CALL_BUY:
        if iv_rich and s < 70:
            return ("WATCH", "call", "medium")
        return ("BUY", "call", "medium")
    if s <= 100 - SCORE_HIGH_CONV:   # <= 25
        return ("BUY", "put", "high")
    if s <= SCORE_PUT_BUY:           # <= 35
        if iv_rich and s > 30:
            return ("WATCH", "put", "medium")
        return ("BUY", "put", "medium")
    if s > 50:
        return ("WATCH", "call", "low")
    if s < 50:
        return ("WATCH", "put", "low")
    return ("PASS", None, "none")


# --- option chain fetch + IV ---------------------------------------------

def _fetch_chains_in_window(ticker: str,
                            dte_min: int,
                            dte_max: int) -> list[dict]:
    """Pull every chain inside [dte_min, dte_max]. Returns list of
    {expiration, dte, calls, puts}."""
    try:
        import yfinance as yf
    except Exception as exc:
        log.warning("yfinance import failed: %s", exc)
        return []
    try:
        yft = yf.Ticker(ticker)
        expirations = list(yft.options or ())
    except Exception as exc:
        log.warning("options chain lookup failed for %s: %s", ticker, exc)
        return []
    today = date.today()
    out: list[dict] = []
    for exp_str in expirations:
        try:
            exp = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (exp - today).days
        if not (dte_min <= dte <= dte_max):
            continue
        try:
            ch = yft.option_chain(exp_str)
        except Exception as exc:
            log.warning("option_chain(%s, %s) failed: %s", ticker, exp_str, exc)
            continue
        out.append({"expiration": exp_str, "dte": dte,
                    "calls": ch.calls, "puts": ch.puts})
    return out


def _atm_iv(chains: list[dict], current_price: float) -> float | None:
    """ATM 30-DTE IV — closest-to-30 chain, mean of 3 ATM strikes."""
    if not chains or current_price <= 0:
        return None
    best = min(chains, key=lambda c: abs(c["dte"] - 30))
    for df in (best.get("calls"), best.get("puts")):
        if df is None or len(df) == 0:
            continue
        try:
            df_atm = df.iloc[(df["strike"] - current_price).abs().argsort()].head(3)
            iv_vals = [float(v) for v in df_atm["impliedVolatility"].tolist() if v and v > 0]
            if iv_vals:
                return sum(iv_vals) / len(iv_vals)
        except Exception:
            continue
    return None


def _iv_regime(atm_iv: float | None, realized_vol_20d: float | None) -> dict:
    """IV/realized ratio classifier — cheap/moderate/fair/rich."""
    if atm_iv is None or realized_vol_20d is None or realized_vol_20d <= 0:
        return {"atm_iv": atm_iv, "realized_vol_20d": realized_vol_20d,
                "ratio": None, "regime": "unknown"}
    ratio = atm_iv / realized_vol_20d
    if   ratio < 0.9:  regime = "cheap"
    elif ratio < 1.2:  regime = "moderate"
    elif ratio < 1.5:  regime = "fair"
    else:              regime = "rich"
    return {"atm_iv": round(atm_iv, 4),
            "realized_vol_20d": round(realized_vol_20d, 4),
            "ratio": round(ratio, 3),
            "regime": regime}


# --- contract selection ---------------------------------------------------

def _select_contract_by_target(chain_df, current_price: float,
                               t_years: float, is_call: bool,
                               target_strike: float | None) -> dict | None:
    """Pick the contract closest to `target_strike` (or to ATM if None)
    that passes all quality gates (OI, spread, delta band). Returns
    None if no contract clears."""
    if chain_df is None or len(chain_df) == 0:
        return None
    if target_strike is None:
        target_strike = current_price
    best = None
    best_diff = float("inf")
    for _, row in chain_df.iterrows():
        try:
            strike = float(row.get("strike") or 0)
            iv = float(row.get("impliedVolatility") or 0)
            bid = float(row.get("bid") or 0)
            ask = float(row.get("ask") or 0)
            oi = int(row.get("openInterest") or 0)
            vol = int(row.get("volume") or 0)
            sym = str(row.get("contractSymbol") or "")
        except (TypeError, ValueError):
            continue
        if strike <= 0 or iv <= 0 or bid <= 0 or ask <= 0:
            continue
        if oi < OI_FLOOR:
            continue
        mid = (bid + ask) / 2.0
        if mid <= 0 or (ask - bid) / mid > SPREAD_FRAC_MAX:
            continue
        delta = _bs_delta(current_price, strike, t_years, iv, is_call)
        if not (DELTA_BAND[0] <= abs(delta) <= DELTA_BAND[1]):
            continue
        diff = abs(strike - target_strike)
        if diff < best_diff:
            best_diff = diff
            best = {
                "contract_symbol": sym, "strike": strike,
                "bid": bid, "ask": ask, "mid": round(mid, 2),
                "delta": round(delta, 4), "iv": round(iv, 4),
                "open_interest": oi, "volume": vol,
            }
    return best


def _target_strike(chain_df, current_price: float,
                   is_call: bool, conviction: str) -> float | None:
    """High conviction → 1-step OTM. Medium → ATM. Returns the strike
    price found on the actual chain (so the selector can match it)."""
    if chain_df is None or len(chain_df) == 0:
        return None
    try:
        strikes = sorted(set(float(s) for s in chain_df["strike"].tolist() if s and s > 0))
    except Exception:
        return None
    if not strikes:
        return None
    atm = min(strikes, key=lambda k: abs(k - current_price))
    if conviction != "high":
        return atm
    idx = strikes.index(atm)
    if is_call:
        return strikes[idx + 1] if idx + 1 < len(strikes) else atm
    else:
        return strikes[idx - 1] if idx >= 1 else atm


def _select_best_contract(chains: list[dict], current_price: float,
                          is_call: bool, conviction: str,
                          earnings_date: str | None,
                          dte_min: int, dte_max: int,
                          ) -> tuple[dict | None, bool]:
    """Returns (best_contract, post_earnings_override_used). The
    override pins expiration to 7-10 days AFTER the earnings date if
    earnings falls within the user's DTE window."""
    if not chains:
        return None, False

    # Post-earnings override
    override_used = False
    if earnings_date:
        try:
            ed = datetime.strptime(earnings_date, "%Y-%m-%d").date()
            d_to_earn = (ed - date.today()).days
            if dte_min <= d_to_earn <= dte_max or (0 <= d_to_earn < dte_min):
                target_dte_min = d_to_earn + POST_EARNINGS_DTE_MIN
                target_dte_max = d_to_earn + POST_EARNINGS_DTE_MAX
                chains_in_window = [c for c in chains
                                    if target_dte_min <= c["dte"] <= target_dte_max]
                if chains_in_window:
                    chains = chains_in_window
                    override_used = True
        except (TypeError, ValueError):
            pass

    best = None
    best_proximity = float("inf")
    for ch in chains:
        df = ch["calls"] if is_call else ch["puts"]
        target = _target_strike(df, current_price, is_call, conviction)
        if target is None:
            continue
        t_years = max(ch["dte"], 1) / 365.0
        pick = _select_contract_by_target(df, current_price, t_years, is_call, target)
        if not pick:
            continue
        # Across expirations, prefer the one whose chosen strike is
        # closest to the target (i.e., good liquidity at the right strike).
        prox = abs(pick["strike"] - target)
        if prox < best_proximity:
            best_proximity = prox
            pick["expiration"] = ch["expiration"]
            pick["dte"] = ch["dte"]
            pick["spans_earnings"] = _spans_earnings(ch["expiration"], earnings_date)
            best = pick
    return best, override_used


# --- earnings + sector lookups -------------------------------------------

def _next_earnings_date(ticker: str) -> str | None:
    try:
        import yfinance as yf
        yft = yf.Ticker(ticker)
        try:
            cal = yft.calendar
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if isinstance(ed, list) and ed:
                    return _ensure_iso_date(ed[0])
                if ed:
                    return _ensure_iso_date(ed)
        except Exception:
            pass
        try:
            df = yft.earnings_dates
            if df is not None and len(df) > 0:
                import pandas as _pd
                if df.index.tz:
                    future = df[df.index >= _pd.Timestamp.now(tz=df.index.tz)]
                else:
                    future = df[df.index >= _pd.Timestamp.now()]
                if len(future) > 0:
                    return str(future.index[0].date())
        except Exception:
            pass
    except Exception as exc:
        log.warning("earnings lookup failed for %s: %s", ticker, exc)
    return None


def _ensure_iso_date(v: Any) -> str | None:
    try:
        if isinstance(v, str):
            return v[:10]
        if hasattr(v, "isoformat"):
            return v.isoformat()[:10]
    except Exception:
        pass
    return None


def _spans_earnings(expiration: str, earnings_date: str | None) -> bool:
    if not earnings_date:
        return False
    try:
        exp = datetime.strptime(expiration, "%Y-%m-%d").date()
        ed  = datetime.strptime(earnings_date, "%Y-%m-%d").date()
        return date.today() <= ed <= exp
    except (TypeError, ValueError):
        return False


def _fetch_etf_5d_move(symbol: str) -> float | None:
    """5-trading-day percent change for an ETF (used for sector + SPY)."""
    try:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period="10d", interval="1d")
        if hist is None or len(hist) < 6:
            return None
        closes = hist["Close"].tolist()
        last, ref = float(closes[-1]), float(closes[-6])
        if ref <= 0:
            return None
        return (last - ref) / ref * 100.0
    except Exception as exc:
        log.warning("ETF 5d lookup failed for %s: %s", symbol, exc)
        return None


# --- analyst data via yfinance -------------------------------------------

def _analyst_data(ticker: str) -> tuple[dict | None, dict | None]:
    """Returns (recs_30d_net, recs_summary). recs_30d_net = {'net_30d': int}
    from yfinance .upgrades_downgrades (or .recommendations).
    recs_summary = {'strong_buy', 'buy', 'hold', 'sell', 'strong_sell'}."""
    net = None
    summary = None
    try:
        import yfinance as yf
        yft = yf.Ticker(ticker)

        # Upgrades / downgrades in last 30d
        try:
            ud = yft.upgrades_downgrades
            if ud is not None and len(ud) > 0:
                import pandas as _pd
                cutoff = _pd.Timestamp.now(tz=ud.index.tz) if ud.index.tz else _pd.Timestamp.now()
                cutoff = cutoff - _pd.Timedelta(days=30)
                recent = ud[ud.index >= cutoff]
                up_words = ("upgrade", "buy", "overweight", "outperform")
                dn_words = ("downgrade", "sell", "underweight", "underperform")
                ups = downs = 0
                for _, r in recent.iterrows():
                    action = str(r.get("Action") or "").lower()
                    to_grade = str(r.get("ToGrade") or "").lower()
                    if any(w in action for w in up_words) or "up" in action:
                        ups += 1
                    elif any(w in action for w in dn_words) or "down" in action:
                        downs += 1
                    elif to_grade in ("buy", "strong buy", "outperform", "overweight"):
                        ups += 1
                    elif to_grade in ("sell", "strong sell", "underperform", "underweight"):
                        downs += 1
                net = {"net_30d": ups - downs, "ups_30d": ups, "downs_30d": downs}
        except Exception as exc:
            log.warning("upgrades_downgrades lookup failed for %s: %s", ticker, exc)

        # Recommendation summary
        try:
            recs = yft.recommendations
            if recs is not None and len(recs) > 0:
                latest = recs.iloc[-1]   # most recent month
                summary = {
                    "strong_buy":  int(latest.get("strongBuy") or 0),
                    "buy":         int(latest.get("buy") or 0),
                    "hold":        int(latest.get("hold") or 0),
                    "sell":        int(latest.get("sell") or 0),
                    "strong_sell": int(latest.get("strongSell") or 0),
                }
        except Exception as exc:
            log.warning("recommendations lookup failed for %s: %s", ticker, exc)
    except Exception as exc:
        log.warning("analyst data lookup failed for %s: %s", ticker, exc)

    return net, summary


# --- prose-paragraph rationale -------------------------------------------

def _prose_rationale(ticker: str, current_price: float,
                     composite: float, verdict: str,
                     direction: str | None, conviction: str,
                     layers: dict, iv_ctx: dict,
                     contract: dict | None,
                     earnings_date: str | None,
                     post_earnings_override: bool) -> str:
    """Stitch the score breakdown into a 3-5 sentence natural-language
    summary. Reads like a research analyst's note, not a JSON dump."""

    if verdict == "PASS" or not direction:
        return (
            f"{ticker} at ${current_price:.2f} shows no clear directional edge "
            f"(composite {composite:.0f}/100, balanced across the five layers). "
            f"Neither the call nor the put case is strong enough to justify "
            f"buying premium right now — wait for the picture to clarify."
        )

    side = "bullish" if direction == "call" else "bearish"
    side_action = "buying calls" if direction == "call" else "buying puts"
    strength = {"high": "strong", "medium": "moderate", "low": "tentative"}[conviction]

    # Layer commentary — pick the 2 strongest layers and call them out
    layer_names = {
        "price": "price action", "catalyst": "catalysts",
        "institutional": "institutional positioning",
        "fundamentals": "fundamentals", "sector": "sector",
    }
    # Layers with score=None had no underlying data — exclude them
    # from the "strongest layers" callout entirely instead of treating
    # a missing reading as a neutral 50.
    layer_scores = {k: float(v.get("score")) for k, v in layers.items()
                    if v.get("score") is not None}
    if direction == "call":
        top = sorted(layer_scores.items(), key=lambda x: -x[1])[:2]
        case_word = "bull case"
    else:
        top = sorted(layer_scores.items(), key=lambda x: x[1])[:2]
        case_word = "bear case"
    top_phrase = (" and ".join(f"{layer_names[k]} ({v:.0f})" for k, v in top)
                  if top else "the available layers")

    # IV commentary
    iv_phrase = ""
    if iv_ctx.get("regime") == "rich":
        iv_phrase = (f" Option premium is rich relative to realized volatility "
                     f"(IV/RV {iv_ctx.get('ratio', 0):.2f}), so size positions modestly.")
    elif iv_ctx.get("regime") == "cheap":
        iv_phrase = (f" Option premium is cheap relative to realized volatility "
                     f"(IV/RV {iv_ctx.get('ratio', 0):.2f}) — favorable backdrop "
                     f"for long premium.")

    # Contract pick
    contract_phrase = ""
    if contract:
        contract_phrase = (
            f" The suggested contract is the {contract.get('expiration')} "
            f"${contract.get('strike'):.2f} {direction} "
            f"(delta {contract.get('delta'):+.2f}, mid ${contract.get('mid'):.2f}, "
            f"{contract.get('dte')}-day expiry, {int(contract.get('open_interest') or 0):,} OI)."
        )

    # Earnings commentary
    earn_phrase = ""
    if post_earnings_override and earnings_date:
        earn_phrase = (
            f" Earnings on {earnings_date} fall within the standard DTE window, "
            f"so the expiry was shifted to land 7-10 days after the event to "
            f"sidestep IV crush."
        )
    elif contract and contract.get("spans_earnings"):
        earn_phrase = (
            f" Note: this contract spans the {earnings_date} earnings — "
            f"expect IV crush after the announcement; consider closing before."
        )

    verdict_action = {"BUY": "supports", "WATCH": "leans toward but doesn't yet confirm"}.get(verdict, "")
    intro = (
        f"{ticker} at ${current_price:.2f} shows a {strength} {side} setup "
        f"(composite {composite:.0f}/100). The {case_word} is led by {top_phrase}. "
        f"That {verdict_action} {side_action}."
    )
    return intro + iv_phrase + contract_phrase + earn_phrase


# --- main entry point -----------------------------------------------------

def recommend_for_ticker(ticker: str,
                         dte_min: int = DEFAULT_DTE_MIN,
                         dte_max: int = DEFAULT_DTE_MAX) -> dict:
    """Full composite-score pipeline.

    `dte_min`/`dte_max` are user-adjustable; if earnings falls inside
    the window, the contract selector overrides expiry to 7-10 days
    after earnings."""
    ticker = (ticker or "").strip().upper()
    # Sanitise the DTE inputs.
    try:
        dte_min = max(1, int(dte_min))
        dte_max = max(dte_min + 1, int(dte_max))
    except (TypeError, ValueError):
        dte_min, dte_max = DEFAULT_DTE_MIN, DEFAULT_DTE_MAX

    out: dict = {
        "ticker": ticker, "as_of": date.today().isoformat(),
        "dte_window": [dte_min, dte_max],
        "composite_score": None,
        "verdict": "PASS", "direction": None, "conviction": "none",
        "layers": None, "contract": None,
        "iv_context": None, "sector": None,
        "earnings_date": None, "earnings_spans_expiration": False,
        "post_earnings_override": False,
        "reasons": [], "prose_rationale": None, "reason": None,
        "partial_data_note": None,
        "disclaimer": "Informational only — not investment advice. "
                       "Options can expire worthless; size positions accordingly.",
    }
    if not ticker:
        out["reason"] = "ticker required"
        return out

    snap_row = _load_snapshot_row(ticker)
    if not snap_row:
        out["reason"] = (f"{ticker} not in latest snapshot — outside the "
                          f"screened universe, or the nightly job hasn't covered it")
        return out

    current_price = _to_f(snap_row.get("close"))
    if not current_price or current_price < PRICE_FLOOR:
        out["reason"] = (
            f"price ${current_price or 0:.2f} below floor ${PRICE_FLOOR:.0f} — "
            f"strike granularity too coarse for liquid options trading"
        )
        return out

    # Enrichment
    import enrich
    insider = enrich.last_insider_transaction(ticker)
    fund    = enrich.fundamentals(ticker)
    news    = enrich.recent_news(ticker, limit=4, max_age_days=7)
    sector  = (fund or {}).get("sector") or snap_row.get("sector")
    out["sector"] = sector

    # Sector + SPY 5d moves
    sector_etf = _SECTOR_ETFS.get(sector) if sector else None
    sector_5d  = _fetch_etf_5d_move(sector_etf) if sector_etf else None
    spy_5d     = _fetch_etf_5d_move("SPY")

    # Earnings + analyst data
    earnings = _next_earnings_date(ticker)
    out["earnings_date"] = earnings
    analyst_net, analyst_summary = _analyst_data(ticker)

    # 20-day avg volume for the price-volume sub-signal
    closes = _closes_from_bars(snap_row)
    avg_vol_20 = _avg_volume_20(snap_row)
    realized_vol = _realized_vol_20d(closes)

    # Layer scoring
    layers = {
        "price":         _score_price_trajectory(snap_row, avg_vol_20),
        "catalyst":      _score_catalyst(news, earnings, analyst_net, dte_max),
        "institutional": _score_institutional(insider, analyst_summary),
        "fundamentals":  _score_fundamentals(fund),
        "sector":        _score_sector(sector, sector_5d, spy_5d),
    }
    composite = _composite(layers)
    out["composite_score"] = composite["score"]
    out["layers"] = layers

    # Aggregate reasons (sub-signal-level)
    for k in WEIGHTS:
        out["reasons"].extend(layers[k].get("reasons") or [])

    if layers["institutional"].get("partial_data"):
        out["partial_data_note"] = (
            "Institutional layer uses insider Form 4 + analyst sentiment "
            "only. Dark pool prints, unusual options flow, and 13F filings "
            "require paid data feeds and are not measured."
        )

    # Option chain + IV context
    chains = _fetch_chains_in_window(ticker, dte_min, dte_max)
    if not chains:
        out["reason"] = (
            f"no liquid option chain available in {dte_min}-{dte_max} DTE "
            f"(yfinance returned nothing or ticker isn't optionable)"
        )
        return out
    atm_iv = _atm_iv(chains, current_price)
    iv_ctx = _iv_regime(atm_iv, realized_vol)
    out["iv_context"] = iv_ctx

    # Verdict
    verdict, direction, conviction = _verdict(composite["score"], iv_ctx.get("regime") == "rich")
    out["verdict"], out["direction"], out["conviction"] = verdict, direction, conviction

    # Contract selection — only if BUY (WATCH/PASS doesn't recommend a contract)
    if verdict == "BUY":
        is_call = (direction == "call")
        best, override = _select_best_contract(
            chains, current_price, is_call, conviction, earnings, dte_min, dte_max
        )
        out["post_earnings_override"] = override
        if not best:
            out["reason"] = (
                f"no contract in the {dte_min}-{dte_max} DTE window cleared "
                f"liquidity gates (OI ≥ {OI_FLOOR}, spread ≤ {int(SPREAD_FRAC_MAX*100)}% "
                f"of mid, delta in {DELTA_BAND}) at the {conviction}-conviction "
                f"strike target — downgrading to WATCH"
            )
            out["verdict"] = "WATCH"
        else:
            out["contract"] = best
            out["earnings_spans_expiration"] = best.get("spans_earnings", False)

    # Prose rationale
    out["prose_rationale"] = _prose_rationale(
        ticker, current_price, composite["score"], out["verdict"],
        out["direction"], out["conviction"], layers, iv_ctx,
        out["contract"], earnings, out["post_earnings_override"]
    )

    # Short reason summary (one-line, for the tile)
    if out["contract"]:
        c = out["contract"]
        out["reason"] = (
            f"{direction.upper()} {c['expiration']} ${c['strike']:.2f} · "
            f"Δ {c['delta']:+.2f} · mid ${c['mid']:.2f} · "
            f"composite {composite['score']:.0f}/100"
        )
    elif direction:
        out["reason"] = (
            f"{verdict} {direction.upper()} · composite {composite['score']:.0f}/100 "
            f"({conviction} conviction)"
        )
    else:
        out["reason"] = f"PASS · composite {composite['score']:.0f}/100"

    return out


# --- persistence ----------------------------------------------------------

def save_recommendation(rec: dict) -> bool:
    import snapshots
    if not snapshots.enabled():
        return False
    try:
        c = rec.get("contract") or {}
        dte_win = rec.get("dte_window")
        dte_win_str = f"{dte_win[0]}-{dte_win[1]}" if dte_win else None
        with snapshots._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO options_recommendations "
                "(as_of, ticker, direction, verdict, score, contract_symbol, "
                "strike, expiration, dte, mid_price, delta, iv, "
                "open_interest, rationale, composite_score, layer_scores, "
                "conviction, prose_rationale, dte_window, post_earnings_override) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                " %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (as_of, ticker) DO UPDATE SET "
                "direction = EXCLUDED.direction, "
                "verdict = EXCLUDED.verdict, "
                "score = EXCLUDED.score, "
                "contract_symbol = EXCLUDED.contract_symbol, "
                "strike = EXCLUDED.strike, "
                "expiration = EXCLUDED.expiration, "
                "dte = EXCLUDED.dte, "
                "mid_price = EXCLUDED.mid_price, "
                "delta = EXCLUDED.delta, "
                "iv = EXCLUDED.iv, "
                "open_interest = EXCLUDED.open_interest, "
                "rationale = EXCLUDED.rationale, "
                "composite_score = EXCLUDED.composite_score, "
                "layer_scores = EXCLUDED.layer_scores, "
                "conviction = EXCLUDED.conviction, "
                "prose_rationale = EXCLUDED.prose_rationale, "
                "dte_window = EXCLUDED.dte_window, "
                "post_earnings_override = EXCLUDED.post_earnings_override, "
                "created_at = now()",
                (rec["as_of"], rec["ticker"], rec.get("direction"),
                 rec.get("verdict") or "PASS",
                 rec.get("composite_score") or 0,
                 c.get("contract_symbol"), c.get("strike"),
                 c.get("expiration"), c.get("dte"), c.get("mid"),
                 c.get("delta"), c.get("iv"), c.get("open_interest"),
                 json.dumps(rec.get("reasons") or []),
                 rec.get("composite_score"),
                 json.dumps(_layer_scores_compact(rec.get("layers") or {})),
                 rec.get("conviction"),
                 rec.get("prose_rationale"),
                 dte_win_str,
                 bool(rec.get("post_earnings_override"))),
            )
        return True
    except Exception as exc:
        log.warning("options.save_recommendation failed: %s", exc)
        return False


def record_iv(ticker: str, as_of: str, atm_iv: float | None) -> bool:
    """Append today's ATM IV reading to the rolling per-ticker history.
    Idempotent on (ticker, as_of) — same-day reruns of the scan overwrite
    instead of duplicating. Returns False on no-op (DB disabled or atm_iv
    missing) without logging, True on a successful upsert.

    Builds the per-ticker baseline IV rank / IV percentile signals will
    eventually read. ~60 trading days of writes gets us to a usable
    distribution; until then it's just accumulating quietly."""
    if atm_iv is None:
        return False
    import snapshots
    if not snapshots.enabled():
        return False
    try:
        with snapshots._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO options_iv_history (ticker, as_of, atm_iv) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (ticker, as_of) DO UPDATE SET "
                "atm_iv = EXCLUDED.atm_iv, captured_at = now()",
                (ticker, as_of, float(atm_iv)),
            )
        return True
    except Exception as exc:
        log.warning("options.record_iv(%s) failed: %s", ticker, exc)
        return False


def save_recommendation_with_iv(rec: dict) -> bool:
    """Persist the recommendation AND the ATM IV reading. The two writes
    are independent — one failing does not skip the other. Returns the
    recommendation write's success bit (the IV write is best-effort)."""
    rec_ok = save_recommendation(rec)
    iv_ctx = rec.get("iv_context") or {}
    record_iv(rec.get("ticker"), rec.get("as_of"), iv_ctx.get("atm_iv"))
    return rec_ok


def _layer_scores_compact(layers: dict) -> dict:
    out = {}
    for k, v in (layers or {}).items():
        if isinstance(v, dict):
            out[k] = {
                "score":      v.get("score"),
                "sub_scores": v.get("sub_scores"),
                "weight":     WEIGHTS.get(k),
                "partial":    bool(v.get("partial_data")),
                "missing":    v.get("missing"),
            }
    return out


def load_recommendations(as_of: str | None = None) -> list[dict]:
    import snapshots
    if not snapshots.enabled():
        return []
    try:
        with snapshots._conn() as conn, conn.cursor() as cur:
            sql = (
                "SELECT as_of, ticker, direction, verdict, score, "
                "contract_symbol, strike, expiration, dte, mid_price, "
                "delta, iv, open_interest, rationale, composite_score, "
                "layer_scores, conviction, prose_rationale, dte_window, "
                "post_earnings_override "
                "FROM options_recommendations "
            )
            if as_of:
                cur.execute(sql + "WHERE as_of = %s ORDER BY score DESC", (as_of,))
            else:
                cur.execute(sql + "WHERE as_of = (SELECT MAX(as_of) FROM "
                                  "options_recommendations) ORDER BY score DESC")
            rows = cur.fetchall()
    except Exception as exc:
        log.warning("options.load_recommendations failed: %s", exc)
        return []
    out = []
    for r in rows:
        try:
            reasons = json.loads(r[13]) if r[13] else []
        except Exception:
            reasons = []
        try:
            layer_scores = r[15] if isinstance(r[15], dict) else (json.loads(r[15]) if r[15] else None)
        except Exception:
            layer_scores = None
        out.append({
            "as_of": r[0].isoformat() if r[0] else None,
            "ticker": r[1], "direction": r[2], "verdict": r[3],
            "score": float(r[4]) if r[4] is not None else 0,
            "contract_symbol": r[5],
            "strike": float(r[6]) if r[6] is not None else None,
            "expiration": r[7].isoformat() if r[7] else None,
            "dte": int(r[8]) if r[8] is not None else None,
            "mid_price": float(r[9]) if r[9] is not None else None,
            "delta": float(r[10]) if r[10] is not None else None,
            "iv": float(r[11]) if r[11] is not None else None,
            "open_interest": int(r[12]) if r[12] is not None else None,
            "rationale": reasons,
            "composite_score": float(r[14]) if r[14] is not None else None,
            "layer_scores": layer_scores,
            "conviction": r[16],
            "prose_rationale": r[17],
            "dte_window": r[18],
            "post_earnings_override": bool(r[19]) if r[19] is not None else False,
        })
    return out


# --- helpers --------------------------------------------------------------

def _is_recent_insider(insider: dict | None, max_days: int = 60) -> bool:
    if not insider:
        return False
    raw = insider.get("transaction_date") or insider.get("filing_date")
    if not raw:
        return False
    try:
        d = datetime.strptime(raw, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    return 0 <= (datetime.utcnow() - d).days <= max_days


def _load_snapshot_row(ticker: str) -> dict | None:
    import snapshots
    if not snapshots.enabled():
        return None
    dates = snapshots.available_dates(1)
    if not dates:
        return None
    for _t, row in snapshots.iter_for_date(dates[0], tickers=[ticker]):
        return row
    return None


def _closes_from_bars(snap_row: dict | None) -> list[float]:
    if not snap_row:
        return []
    import scanner_momentum
    bars = scanner_momentum._bars_from_row(snap_row) or []
    out = []
    for b in bars:
        try:
            c = float(b.get("c") or 0)
            if c > 0:
                out.append(c)
        except (TypeError, ValueError):
            continue
    return out


def _avg_volume_20(snap_row: dict | None) -> float | None:
    if not snap_row:
        return None
    import scanner_momentum
    bars = scanner_momentum._bars_from_row(snap_row) or []
    vols: list[float] = []
    for b in bars[-20:]:
        try:
            v = float(b.get("v") or 0)
            if v > 0:
                vols.append(v)
        except (TypeError, ValueError):
            continue
    return (sum(vols) / len(vols)) if vols else None
