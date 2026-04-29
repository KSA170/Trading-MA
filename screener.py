"""
Screener for US/Canadian stocks. Each filter is independently toggleable;
when disabled the criterion is skipped but the value is still reported.

Default filters (all enabled):
  - Previous close set a new N-day high (default 30)
  - Daily RSI(14) inside [rsi_min, rsi_max] (default 45-50)
  - RSI(9) deviation vs RSI(14) within [rsi9_dev_min, rsi9_dev_max]%
    (default -5%..+10%)
  - Relative volume over the trailing N days greater than threshold
    (default 10-day, > 0.5)

Universe is selected via list keys: 'sp500', 'dow', 'nasdaq100', 'tsx'.

Data source: yfinance (Yahoo Finance public endpoints).
"""

from __future__ import annotations

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from typing import Iterable

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
    close: float
    prev_close: float
    pct_change: float
    high_lookback: float
    rsi: float
    rsi9: float
    rsi9_dev_pct: float
    rel_volume: float
    avg_volume: float
    volume: float
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

# Module-level price-history cache so repeated requests within a short window
# don't hammer Yahoo. Keyed by ticker -> (timestamp, DataFrame).
_PRICE_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_PRICE_TTL_SEC = 60 * 30  # 30 minutes


def _cached_history(ticker: str, period: str = "6mo") -> pd.DataFrame | None:
    now = time.time()
    cached = _PRICE_CACHE.get(ticker)
    if cached and now - cached[0] < _PRICE_TTL_SEC:
        return cached[1]
    try:
        df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    except Exception as exc:
        log.warning("history fetch failed for %s: %s", ticker, exc)
        return None
    if df is None or df.empty:
        return None
    df = df.dropna(subset=["Close", "Volume"])
    _PRICE_CACHE[ticker] = (now, df)
    return df


# yfinance's `info` is slow; use a small symbol -> name cache populated lazily.
_NAME_CACHE: dict[str, str] = {}


def _company_name(ticker: str) -> str:
    if ticker in _NAME_CACHE:
        return _NAME_CACHE[ticker]
    try:
        info = yf.Ticker(ticker).get_info()
        name = info.get("shortName") or info.get("longName") or ticker
    except Exception:
        name = ticker
    _NAME_CACHE[ticker] = name
    return name


# --- core screening --------------------------------------------------------

def evaluate_ticker(
    ticker: str,
    high_lookback: int = 30,
    rsi_period: int = 14,
    rsi_min: float = 45.0,
    rsi_max: float = 50.0,
    rsi9_period: int = 9,
    rsi9_dev_min_pct: float = -5.0,
    rsi9_dev_max_pct: float = 10.0,
    rvol_lookback: int = 10,
    rvol_min: float = 0.5,
    apply_high: bool = True,
    apply_rsi: bool = True,
    apply_rsi9: bool = True,
    apply_rvol: bool = True,
) -> ScreenHit | None:
    df = _cached_history(ticker, period="6mo")
    if df is None or len(df) < max(high_lookback + 2, rsi_period + 5, rvol_lookback + 2):
        return None

    closes = df["Close"]
    volumes = df["Volume"]

    # "Based on previous close": evaluate using the most recent completed bar.
    prev_close = float(closes.iloc[-1])
    prior_close = float(closes.iloc[-2])
    volume = float(volumes.iloc[-1])

    # N-day high lookup uses the prior `high_lookback` closes (excluding the
    # current bar). When the high filter is enabled, prev_close must be >= max.
    window = closes.iloc[-(high_lookback + 1):-1]
    if window.empty:
        return None
    lookback_high = float(window.max())
    if apply_high and prev_close < lookback_high:
        return None

    # RSI(14)
    rsi_series = rsi_wilder(closes, period=rsi_period)
    rsi_val = rsi_series.iloc[-1]
    if not np.isfinite(rsi_val):
        return None
    if apply_rsi and not (rsi_min <= rsi_val <= rsi_max):
        return None

    # RSI(9) and deviation vs RSI(14)
    rsi9_series = rsi_wilder(closes, period=rsi9_period)
    rsi9_val = rsi9_series.iloc[-1]
    if not np.isfinite(rsi9_val) or rsi_val == 0:
        return None
    rsi9_dev_pct = (float(rsi9_val) - float(rsi_val)) / float(rsi_val) * 100.0
    if apply_rsi9 and not (rsi9_dev_min_pct <= rsi9_dev_pct <= rsi9_dev_max_pct):
        return None

    # Relative volume: last bar volume / mean of prior N bars
    vol_window = volumes.iloc[-(rvol_lookback + 1):-1]
    if vol_window.empty or vol_window.mean() == 0:
        return None
    avg_volume = float(vol_window.mean())
    rel_vol = volume / avg_volume
    if apply_rvol and rel_vol <= rvol_min:
        return None

    pct_change = (prev_close - prior_close) / prior_close * 100.0 if prior_close else 0.0
    exchange = "TSX" if ticker.endswith(".TO") else "US"
    breakout = max(0.0, prev_close - lookback_high) / lookback_high if lookback_high else 0.0
    score = max(rel_vol, 0.01) * (1 + breakout)

    membership = lists_for(ticker)
    return ScreenHit(
        ticker=display_symbol(ticker),
        name=_company_name(ticker),
        exchange=exchange,
        lists=membership,
        list_labels=list_labels(membership),
        close=round(prev_close, 4),
        prev_close=round(prior_close, 4),
        pct_change=round(pct_change, 2),
        high_lookback=round(lookback_high, 4),
        rsi=round(float(rsi_val), 2),
        rsi9=round(float(rsi9_val), 2),
        rsi9_dev_pct=round(rsi9_dev_pct, 2),
        rel_volume=round(rel_vol, 2),
        avg_volume=round(avg_volume, 0),
        volume=round(volume, 0),
        score=round(score, 4),
    )


def run_screen(
    high_lookback: int = 30,
    rsi_min: float = 45.0,
    rsi_max: float = 50.0,
    rsi9_dev_min_pct: float = -5.0,
    rsi9_dev_max_pct: float = 10.0,
    rvol_lookback: int = 10,
    rvol_min: float = 0.5,
    apply_high: bool = True,
    apply_rsi: bool = True,
    apply_rsi9: bool = True,
    apply_rvol: bool = True,
    lists: list[str] | None = None,
    universe: Iterable[str] | None = None,
    max_workers: int = 16,
) -> list[ScreenHit]:
    if universe is not None:
        tickers = list(universe)
    elif lists:
        tickers = build_universe(lists)
    else:
        tickers = all_tickers()
    hits: list[ScreenHit] = []

    def _eval(t: str) -> ScreenHit | None:
        try:
            return evaluate_ticker(
                t,
                high_lookback=high_lookback,
                rsi_min=rsi_min,
                rsi_max=rsi_max,
                rsi9_dev_min_pct=rsi9_dev_min_pct,
                rsi9_dev_max_pct=rsi9_dev_max_pct,
                rvol_lookback=rvol_lookback,
                rvol_min=rvol_min,
                apply_high=apply_high,
                apply_rsi=apply_rsi,
                apply_rsi9=apply_rsi9,
                apply_rvol=apply_rvol,
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


# --- chart payload ---------------------------------------------------------

def chart_payload(ticker: str, period: str = "1y") -> dict | None:
    # accept user-facing ticker (e.g. "RY.TO") and use as-is
    df = _cached_history(ticker, period=period)
    if df is None or df.empty:
        return None

    df = df.copy()
    df["EMA21"] = ema(df["Close"], 21)
    df["EMA50"] = ema(df["Close"], 50)
    df["RSI"] = rsi_wilder(df["Close"], 14)
    df["RSI9"] = rsi_wilder(df["Close"], 9)

    def _row(idx, r):
        ts = idx.strftime("%Y-%m-%d")
        return {
            "time": ts,
            "open": _safe(r["Open"]),
            "high": _safe(r["High"]),
            "low": _safe(r["Low"]),
            "close": _safe(r["Close"]),
            "volume": _safe(r["Volume"]),
            "ema21": _safe(r["EMA21"]),
            "ema50": _safe(r["EMA50"]),
            "rsi": _safe(r["RSI"]),
            "rsi9": _safe(r["RSI9"]),
        }

    rows = [_row(idx, r) for idx, r in df.iterrows()]
    return {
        "ticker": display_symbol(ticker),
        "name": _company_name(ticker),
        "rows": rows,
    }


def _safe(v):
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f
