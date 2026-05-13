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

MAX_AS_OF_OFFSET = 10


def evaluate_ticker(
    ticker: str,
    high_lookback: int = 2,
    rsi_period: int = 14,
    rsi_min: float = 45.0,
    rsi_max: float = 65.0,
    rsi_sma_period: int = 9,
    rsi_dev_min_pct: float = 0.0,
    rsi_dev_max_pct: float = 10.0,
    rvol_lookback: int = 10,
    rvol_min: float = 1.2,
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
    apply_high: bool = True,
    apply_rsi: bool = True,
    apply_rsi_dev: bool = True,
    apply_rvol: bool = True,
    apply_price: bool = True,
    apply_price_dev: bool = True,
    apply_ema_dev: bool = True,
    apply_macd: bool = True,
    as_of_offset: int = 0,
) -> ScreenHit | None:
    if as_of_offset < 0:
        as_of_offset = 0
    if as_of_offset > MAX_AS_OF_OFFSET:
        as_of_offset = MAX_AS_OF_OFFSET

    df = _cached_history(ticker, period="6mo")
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

    # Higher-high streak: each of the last `high_lookback` bars must have a
    # daily high strictly greater than the bar before it. That's N consecutive
    # comparisons across N+1 bars (eval bar plus the N preceding).
    highs = df["High"]
    hh_start = eval_idx - high_lookback
    if eval_idx + 1 < 0:
        hh_window = highs.iloc[hh_start:eval_idx + 1]
    else:
        hh_window = highs.iloc[hh_start:]
    if len(hh_window) < high_lookback + 1:
        return None
    eval_high = float(hh_window.iloc[-1])
    streak_start_high = float(hh_window.iloc[0])
    streak_ok = bool(hh_window.diff().iloc[1:].gt(0).all())
    if apply_high and not streak_ok:
        return None

    # RSI(14) computed up to and including the eval bar
    closes_to_eval = closes.iloc[: len(closes) + eval_idx + 1] if eval_idx < -1 else closes
    rsi_series = rsi_wilder(closes_to_eval, period=rsi_period)
    rsi_val = rsi_series.iloc[-1]
    if not np.isfinite(rsi_val):
        return None
    if apply_rsi and not (rsi_min <= rsi_val <= rsi_max):
        return None

    # 9-day SMA of RSI(14) and RSI's deviation from it.
    rsi_sma_series = rsi_series.rolling(window=rsi_sma_period, min_periods=rsi_sma_period).mean()
    rsi_sma_val = rsi_sma_series.iloc[-1]
    if not np.isfinite(rsi_sma_val) or rsi_sma_val == 0:
        return None
    rsi_dev_pct = (float(rsi_val) - float(rsi_sma_val)) / float(rsi_sma_val) * 100.0
    if apply_rsi_dev and not (rsi_dev_min_pct <= rsi_dev_pct <= rsi_dev_max_pct):
        return None

    # EMA(21) of close, evaluated through the eval bar, and price's
    # deviation from it as a percentage.
    ema_series = ema(closes_to_eval, ema_period)
    ema_val = ema_series.iloc[-1]
    if not np.isfinite(ema_val) or ema_val == 0:
        return None
    ema_val = float(ema_val)
    price_ema21_dev_pct = (prev_close - ema_val) / ema_val * 100.0
    if apply_price_dev and not (price_dev_min_pct <= price_ema21_dev_pct <= price_dev_max_pct):
        return None

    # EMA(50) of close and the EMA21-vs-EMA50 deviation. Positive = EMA21 is
    # above EMA50 (golden-cross territory); negative = EMA21 below EMA50.
    ema_long_series = ema(closes_to_eval, ema_long_period)
    ema_long_val = ema_long_series.iloc[-1]
    if not np.isfinite(ema_long_val) or ema_long_val == 0:
        return None
    ema_long_val = float(ema_long_val)
    ema21_ema50_dev_pct = (ema_val - ema_long_val) / ema_long_val * 100.0
    if apply_ema_dev and not (ema_dev_min_pct <= ema21_ema50_dev_pct <= ema_dev_max_pct):
        return None

    # MACD(12, 26, 9): histogram = MACD line - signal line. "Bullish trending"
    # = histogram is at or above `macd_hist_min` AND today's hist is greater
    # than yesterday's (momentum building).
    macd_line_series = ema(closes_to_eval, 12) - ema(closes_to_eval, 26)
    macd_signal_series = ema(macd_line_series, 9)
    macd_hist_series = macd_line_series - macd_signal_series
    macd_val = macd_line_series.iloc[-1]
    macd_signal_val = macd_signal_series.iloc[-1]
    macd_hist_val = macd_hist_series.iloc[-1]
    macd_hist_prev = macd_hist_series.iloc[-2] if len(macd_hist_series) > 1 else float("nan")
    if not (np.isfinite(macd_val) and np.isfinite(macd_signal_val) and
            np.isfinite(macd_hist_val) and np.isfinite(macd_hist_prev)):
        return None
    if apply_macd:
        if float(macd_hist_val) < macd_hist_min:
            return None
        if macd_require_rising and not (float(macd_hist_val) > float(macd_hist_prev)):
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

    pct_change = (prev_close - prior_close) / prior_close * 100.0 if prior_close else 0.0
    exchange = "TSX" if ticker.endswith(".TO") else "US"
    breakout = (eval_high - streak_start_high) / streak_start_high if streak_start_high else 0.0
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
        high_lookback=round(eval_high, 4),
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
        score=round(score, 4),
    )


def run_screen(
    high_lookback: int = 2,
    rsi_min: float = 45.0,
    rsi_max: float = 65.0,
    rsi_dev_min_pct: float = 0.0,
    rsi_dev_max_pct: float = 10.0,
    rvol_lookback: int = 10,
    rvol_min: float = 1.2,
    price_min: float = 1.0,
    price_max: float = 1000.0,
    price_dev_min_pct: float = -1.0,
    price_dev_max_pct: float = 4.0,
    ema_dev_min_pct: float = -3.0,
    ema_dev_max_pct: float = 3.0,
    macd_hist_min: float = 0.0,
    macd_require_rising: bool = True,
    apply_high: bool = True,
    apply_rsi: bool = True,
    apply_rsi_dev: bool = True,
    apply_rvol: bool = True,
    apply_price: bool = True,
    apply_price_dev: bool = True,
    apply_ema_dev: bool = True,
    apply_macd: bool = True,
    as_of_offset: int = 0,
    lists: list[str] | None = None,
    universe: Iterable[str] | None = None,
    max_workers: int = 32,
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
                rsi_dev_min_pct=rsi_dev_min_pct,
                rsi_dev_max_pct=rsi_dev_max_pct,
                rvol_lookback=rvol_lookback,
                rvol_min=rvol_min,
                price_min=price_min,
                price_max=price_max,
                price_dev_min_pct=price_dev_min_pct,
                price_dev_max_pct=price_dev_max_pct,
                ema_dev_min_pct=ema_dev_min_pct,
                ema_dev_max_pct=ema_dev_max_pct,
                macd_hist_min=macd_hist_min,
                macd_require_rising=macd_require_rising,
                apply_high=apply_high,
                apply_rsi=apply_rsi,
                apply_rsi_dev=apply_rsi_dev,
                apply_rvol=apply_rvol,
                apply_price=apply_price,
                apply_price_dev=apply_price_dev,
                apply_ema_dev=apply_ema_dev,
                apply_macd=apply_macd,
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


def reference_dates(n: int = 11) -> list[dict]:
    """Last `n` US trading-day dates from a reference ticker (SPY).

    Returns a list of {"offset": k, "date": "YYYY-MM-DD"} most recent first.
    The dropdown uses these as anchors; per-ticker actual dates may differ on
    Canadian holidays (each row's `as_of_date` reports what was actually used).
    """
    df = _cached_history("SPY", period="3mo")
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
