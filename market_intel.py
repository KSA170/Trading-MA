"""Optional market-intelligence layer (Alpha Vantage).

Adds fundamentals / analyst-rating / price-target / news-sentiment signals
to the alert + options verdicts, blended into one 0-100 "conviction" score.

OFF by default and fully best-effort: enabled() is false unless BOTH
INTEL_ENABLED is truthy AND ALPHAVANTAGE_API_KEY is set, so with no config
every consumer skips it and behaviour is identical to before this module.

Alpha Vantage free tier is ~25 requests/day, 5/min — very tight. So:
  - Two endpoints per ticker (OVERVIEW + NEWS_SENTIMENT) = 2 calls.
  - Per-ticker in-process cache (6h) so repeat alerts on a name cost 0.
  - On any rate-limit note / parse failure the affected signal is skipped
    (never defaulted to neutral); the composite renormalizes over what's
    present, exactly like options._score_catalyst already does.
  - Fetched only on alert-fire and single-ticker options analyze — never
    the options universe scan or the whole screener universe.
The daily budget is shared across the web + cron processes (each keeps its
own cache); once exhausted, intel simply degrades to "unavailable".
"""

from __future__ import annotations

import logging
import math
import os
import time

import requests

log = logging.getLogger("market_intel")

_AV_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
_BASE = "https://www.alphavantage.co/query"
_MIN_INTERVAL = 1.2                 # ~5/min free-tier ceiling
_CACHE_TTL = 6 * 3600
_last_call = [0.0]
_cache: dict[tuple, tuple] = {}     # (fn, ticker) -> (fetched_ts, value)


def _feature_on() -> bool:
    return str(os.environ.get("INTEL_ENABLED", "")).strip().lower() in (
        "1", "true", "yes", "on")


def enabled() -> bool:
    """Both a key AND the feature flag are required. Default: off."""
    return bool(_AV_KEY) and _feature_on()


# --- Alpha Vantage fetch --------------------------------------------------

def _av_get(params: dict):
    if not _AV_KEY:
        return None
    dt = time.time() - _last_call[0]
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _last_call[0] = time.time()
    params["apikey"] = _AV_KEY
    try:
        r = requests.get(_BASE, params=params, timeout=10)
        r.raise_for_status()
        j = r.json()
    except Exception as exc:
        log.warning("alphavantage %s failed: %s", params.get("function"), exc)
        return None
    if not isinstance(j, dict):
        return None
    # AV signals throttling / errors via a JSON key, not an HTTP status.
    for k in ("Note", "Information", "Error Message"):
        if k in j:
            log.info("alphavantage %s throttled/err: %s",
                     params.get("function"), str(j[k])[:100])
            return None
    return j


def _cached(fn: str, ticker: str, fetch):
    key = (fn, ticker)
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < _CACHE_TTL:
        return hit[1]
    val = fetch()
    _cache[key] = (now, val)
    return val


def _avf(d: dict, key: str):
    """Parse an Alpha Vantage numeric field (returned as strings, with
    'None' / '-' / '' sentinels for missing)."""
    v = d.get(key)
    if v in (None, "None", "-", "", "NaN"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def company_overview(ticker: str):
    """AV OVERVIEW (free): analyst ratings, target price, ROE, growth."""
    def _f():
        j = _av_get({"function": "OVERVIEW", "symbol": ticker})
        return j if (j and j.get("Symbol")) else None
    return _cached("OVERVIEW", ticker, _f)


def news_sentiment(ticker: str):
    """AV NEWS_SENTIMENT (free): averages the ticker-level sentiment score
    across recent articles. Returns {avg_score (-1..1), bullish_pct, n}."""
    def _f():
        j = _av_get({"function": "NEWS_SENTIMENT", "tickers": ticker, "limit": 50})
        if not j or "feed" not in j:
            return None
        scores = []
        up = ticker.upper()
        for item in j["feed"]:
            for ts in (item.get("ticker_sentiment") or []):
                if (ts.get("ticker") or "").upper() == up:
                    try:
                        scores.append(float(ts["ticker_sentiment_score"]))
                    except (TypeError, ValueError, KeyError):
                        pass
        if not scores:
            return None
        return {"avg_score": sum(scores) / len(scores),
                "bullish_pct": sum(1 for s in scores if s >= 0.15) / len(scores),
                "n": len(scores)}
    return _cached("NEWS", ticker, _f)


# --- pure component scorers (0-100, 50=neutral; None if no data) ----------
# All DB-free and network-free — unit-testable in isolation.

def _sigmoid(x: float, mid: float, k: float) -> float:
    return 100.0 / (1.0 + math.exp(-(x - mid) / k))


def score_analyst(ov: dict | None):
    """Weighted mean of AV analyst rating counts (strongBuy=100 .. strongSell=0)."""
    if not ov:
        return None
    counts = [(_avf(ov, k) or 0.0) for k in (
        "AnalystRatingStrongBuy", "AnalystRatingBuy", "AnalystRatingHold",
        "AnalystRatingSell", "AnalystRatingStrongSell")]
    n = sum(counts)
    if n <= 0:
        return None
    weighted = counts[0]*100 + counts[1]*75 + counts[2]*50 + counts[3]*25 + counts[4]*0
    return weighted / n


def score_price_target(ov: dict | None, price: float | None):
    """Analyst mean target vs current price; +10% upside → ~50, +30% → ~84."""
    if not ov or not price or price <= 0:
        return None
    tgt = _avf(ov, "AnalystTargetPrice")
    if tgt is None or tgt <= 0:
        return None
    return _sigmoid(tgt / price - 1.0, 0.10, 0.12)


def score_fundamentals(ov: dict | None):
    """Blend of ROE and quarterly revenue growth (each sigmoid-mapped)."""
    if not ov:
        return None
    parts = []
    roe = _avf(ov, "ReturnOnEquityTTM")
    if roe is not None:
        parts.append(_sigmoid(roe, 0.05, 0.08))
    rg = _avf(ov, "QuarterlyRevenueGrowthYOY")
    if rg is not None:
        parts.append(_sigmoid(rg, 0.05, 0.10))
    return (sum(parts) / len(parts)) if parts else None


def score_news(ns: dict | None):
    """Map AV avg sentiment (-0.35 bearish .. +0.35 bullish) to 0-100."""
    if not ns or ns.get("avg_score") is None:
        return None
    return max(0.0, min(100.0, 50.0 + (ns["avg_score"] / 0.35) * 35.0))


def score_insider(insider: dict | None):
    """Latest SEC Form 4 transaction code: open-market buy vs sell."""
    if not insider:
        return None
    code = (insider.get("code") or "").upper()
    return {"P": 80.0, "S": 25.0}.get(code, 50.0)


# --- composite ------------------------------------------------------------

def conviction(ticker: str, *, price: float | None = None,
               insider: dict | None = None) -> dict:
    """Blend available signals into a 0-100 conviction + per-component
    scores. Fetches AV OVERVIEW + NEWS_SENTIMENT (cached); insider is
    passed in from the SEC data the caller already has. Missing signals
    are skipped, not defaulted."""
    ov = company_overview(ticker)
    ns = news_sentiment(ticker)
    comps = {
        "analyst":      score_analyst(ov),
        "price_target": score_price_target(ov, price),
        "fundamentals": score_fundamentals(ov),
        "news":         score_news(ns),
        "insider":      score_insider(insider),
    }
    present = {k: v for k, v in comps.items() if v is not None}
    score = (sum(present.values()) / len(present)) if present else None
    label = None
    if score is not None:
        label = "bullish" if score >= 60 else "bearish" if score < 40 else "neutral"
    return {"score": score, "components": comps, "n": len(present), "label": label}


def conviction_for(ticker: str, *, price: float | None = None,
                   insider: dict | None = None) -> dict | None:
    """enabled()-gated wrapper: returns None when the feature is off (or
    on failure) so callers can invoke it unconditionally and treat a
    None result as 'no intel'."""
    if not enabled():
        return None
    try:
        return conviction(ticker, price=price, insider=insider)
    except Exception as exc:
        log.warning("market_intel.conviction_for(%s) failed: %s", ticker, exc)
        return None


# --- verdict helpers (shared by the alert paths) --------------------------

def band(intel: dict | None, up2: int, up1: int, down1: int) -> int:
    """Map an intel result to a verdict point delta. 0 when intel is
    absent/unscored so the off-path is a no-op:
      score >= 70 → up2 · >= 55 → up1 · < 35 → down1 · else 0."""
    if not intel or intel.get("score") is None:
        return 0
    s = intel["score"]
    if s >= 70:
        return up2
    if s >= 55:
        return up1
    if s < 35:
        return down1
    return 0


def summary_row(intel: dict | None) -> str | None:
    """Compact one-line intel summary for a Telegram alert body, or None
    when there's nothing to show."""
    if not intel or intel.get("score") is None:
        return None
    c = intel["components"]
    order = [("analyst", "analyst"), ("price_target", "target"),
             ("fundamentals", "fund"), ("news", "news"), ("insider", "insider")]
    bits = [f"{lbl} {c[key]:.0f}" for key, lbl in order if c.get(key) is not None]
    return f"{intel['score']:.0f}/100 ({intel['label']}) · " + " · ".join(bits)
