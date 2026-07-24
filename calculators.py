"""Reverse-solve calculators for the Calculators tab.

First calculator: Reverse Stochastic Slow %K — given a ticker and a bar
interval, solve backwards from the Slow %K formula for the price the next
bar(s) would need to trade at for Slow %K to reach the oversold and
overbought thresholds.

Math refresher (classic stochastic oscillator):
    Fast %K_t = 100 * (C_t - LL_n) / (HH_n - LL_n)   n = k_len (default 14)
    Slow %K_t = SMA_m(Fast %K)                        m = smooth (default 3)
    %D_t      = SMA_m(Slow %K)

Because Slow %K averages the last m Fast %K readings, a single bar often
cannot drag it from overbought to oversold — the prior Fast %K terms are
still high even if the new bar's Fast %K collapses to 0. So the solver
answers, for each horizon k = 1..m:

    "If price gaps to P on the next bar and holds there for k bars
     (each synthetic bar O=H=L=C=P), what P puts Slow %K at the
     threshold?"

Slow %K after k flat bars at P is monotonic non-decreasing in P (a higher
price raises each synthetic bar's Fast %K and never lowers the rolling
HH/LL window), so each horizon is solved by bisection on the simulated
value. The k=1 in-range case also has a closed form, used as an oracle in
the unit tests.

Data sourcing: the 1-day interval prefers the latest daily_snapshot row's
recent_bars (zero fetch cost); every other interval — and the 1-day
fallback — fetches from Yahoo via yfinance, with a short in-process TTL
cache per (ticker, interval).
"""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("calculators")

# interval -> (yfinance period, human label, cache TTL seconds).
# Periods sit inside Yahoo's per-interval history caps (1m ≤ 7d,
# 5m-30m ≤ 60d, 1h ≤ 730d) while giving far more bars than the
# stochastic needs.
INTERVALS: dict[str, tuple[str, str, int]] = {
    "1m":  ("5d",  "1 minute",   180),
    "5m":  ("1mo", "5 minutes",  180),
    "15m": ("1mo", "15 minutes", 180),
    "30m": ("1mo", "30 minutes", 180),
    "1h":  ("3mo", "1 hour",     600),
    "1d":  ("6mo", "1 day",      1800),
    "1wk": ("2y",  "1 week",     3600),
    "1mo": ("10y", "1 month",    3600),
}

_cache: dict[tuple[str, str], tuple[float, list, str]] = {}
_cache_lock = threading.Lock()


# --- pure math (no I/O — unit-testable in isolation) -----------------------

def stoch_series(bars: list[dict], k_len: int = 14, smooth: int = 3):
    """Fast %K and Slow %K over a bar list ({h, l, c} dicts, oldest
    first). Returns two lists aligned to `bars`, None where the lookback
    window isn't filled yet or a bar has missing values."""
    n = len(bars)
    fast: list[float | None] = [None] * n
    for i in range(k_len - 1, n):
        win = bars[i - k_len + 1:i + 1]
        try:
            hh = max(float(b["h"]) for b in win)
            ll = min(float(b["l"]) for b in win)
            c = float(bars[i]["c"])
        except (TypeError, ValueError, KeyError):
            continue
        if hh == ll:
            # Flat window — %K is undefined (0/0); use the neutral 50.
            fast[i] = 50.0
        else:
            fast[i] = max(0.0, min(100.0, (c - ll) / (hh - ll) * 100.0))
    slow: list[float | None] = [None] * n
    for i in range(smooth - 1, n):
        win_f = fast[i - smooth + 1:i + 1]
        if all(v is not None for v in win_f):
            slow[i] = sum(win_f) / smooth
    return fast, slow


def slow_k_after(bars: list[dict], price: float, k_bars: int,
                 k_len: int = 14, smooth: int = 3) -> float | None:
    """Slow %K after appending k_bars synthetic flat bars at `price`
    (each O=H=L=C=price)."""
    synth = [{"h": price, "l": price, "c": price}] * k_bars
    _, slow = stoch_series(list(bars) + synth, k_len, smooth)
    return slow[-1]


def solve_price_for_slow_k(bars: list[dict], threshold: float, direction: str,
                           k_bars: int, k_len: int = 14, smooth: int = 3) -> dict:
    """Bisection solve on the flat-bar simulation.

    direction 'down': highest price P with SlowK_after(P) <= threshold
                      (how far price must fall to reach oversold).
    direction 'up':   lowest price P with SlowK_after(P) >= threshold
                      (how far price must rise to reach overbought).

    Returns {achievable, price, slow_k, note}: price is None either when
    the horizon can't reach the threshold at all (achievable=False) or
    when every price already satisfies it (achievable=True + note).
    """
    # Only the tail matters once k_bars synthetic bars are appended.
    tail = bars[-(k_len + smooth + 2):]
    f = lambda p: slow_k_after(tail, p, k_bars, k_len, smooth)

    highs = [float(b["h"]) for b in tail if b.get("h") is not None]
    lo, hi = 0.0, max(highs) * 2.0 if highs else 1.0
    f_lo, f_hi = f(lo), f(hi)
    if f_lo is None or f_hi is None:
        return {"achievable": False, "price": None, "slow_k": None,
                "note": "not enough bars to simulate"}

    if direction == "down":
        if f_lo > threshold:
            return {"achievable": False, "price": None, "slow_k": None,
                    "note": f"not achievable in {k_bars} bar{'s' if k_bars > 1 else ''}"
                            " — prior %K readings hold the average too high"}
        if f_hi <= threshold:
            return {"achievable": True, "price": None, "slow_k": f_hi,
                    "note": "satisfied at any price"}
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if f(mid) <= threshold:
                lo = mid
            else:
                hi = mid
        return {"achievable": True, "price": round(lo, 4),
                "slow_k": round(f(lo), 2), "note": None}

    # direction == "up"
    if f_hi < threshold:
        return {"achievable": False, "price": None, "slow_k": None,
                "note": f"not achievable in {k_bars} bar{'s' if k_bars > 1 else ''}"
                        " — prior %K readings hold the average too low"}
    if f_lo >= threshold:
        return {"achievable": True, "price": None, "slow_k": f_lo,
                "note": "satisfied at any price"}
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if f(mid) >= threshold:
            hi = mid
        else:
            lo = mid
    return {"achievable": True, "price": round(hi, 4),
            "slow_k": round(f(hi), 2), "note": None}


# --- data sourcing ---------------------------------------------------------

def _bars_from_snapshot(ticker: str) -> tuple[list | None, str | None]:
    """Latest daily_snapshot recent_bars for `ticker`, or (None, None)."""
    try:
        import snapshots
        if not snapshots.enabled():
            return None, None
        dates = snapshots.available_dates(limit=1)
        if not dates:
            return None, None
        for tk, row in snapshots.iter_for_date(dates[0], [ticker]):
            if tk.upper() != ticker:
                continue
            payload = row.get("recent_bars")
            if isinstance(payload, str):
                import json
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = None
            bars = (payload or {}).get("bars") or []
            bars = [b for b in bars
                    if b.get("h") is not None and b.get("l") is not None
                    and b.get("c") is not None]
            if bars:
                return bars, f"snapshot {dates[0]}"
    except Exception as exc:
        log.warning("calculators snapshot read failed for %s: %s", ticker, exc)
    return None, None


def _bars_from_yahoo(ticker: str, interval: str) -> tuple[list | None, str | None]:
    """Fetch OHLC bars from Yahoo for any supported interval."""
    period = INTERVALS[interval][0]
    try:
        import yfinance as yf
        df = yf.Ticker(ticker).history(
            period=period, interval=interval,
            auto_adjust=False, prepost=False)
    except Exception as exc:
        log.warning("calculators yahoo fetch failed for %s/%s: %s",
                    ticker, interval, exc)
        return None, None
    if df is None or df.empty:
        return None, None
    if interval in ("1m", "5m", "15m", "30m", "1h"):
        dfmt = "%Y-%m-%d %H:%M"
    elif interval == "1mo":
        dfmt = "%Y-%m"
    else:
        dfmt = "%Y-%m-%d"
    bars = []
    for idx, r in df.iterrows():
        try:
            h, l, c = float(r["High"]), float(r["Low"]), float(r["Close"])
        except (TypeError, ValueError, KeyError):
            continue
        if h != h or l != l or c != c:   # NaN row (halted / partial bar)
            continue
        bars.append({"d": idx.strftime(dfmt), "h": h, "l": l, "c": c})
    return (bars, "live (Yahoo)") if bars else (None, None)


def fetch_bars(ticker: str, interval: str) -> tuple[list | None, str | None]:
    """Bars for (ticker, interval), oldest first, with a source label.
    1-day prefers the DB snapshot (already holds 60 daily bars); every
    other interval — and the 1-day fallback — goes to Yahoo. Cached
    in-process per INTERVALS TTL."""
    key = (ticker, interval)
    ttl = INTERVALS[interval][2]
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and (now - hit[0]) < ttl:
            return hit[1], hit[2]

    bars, source = (None, None)
    if interval == "1d":
        bars, source = _bars_from_snapshot(ticker)
    if bars is None:
        bars, source = _bars_from_yahoo(ticker, interval)
    if bars is not None:
        with _cache_lock:
            _cache[key] = (now, bars, source)
    return bars, source


# --- calculator orchestrator ----------------------------------------------

def stoch_reverse(ticker: str, interval: str, *, k_len: int = 14,
                  smooth: int = 3, overbought: float = 80.0,
                  oversold: float = 20.0) -> dict:
    """Full reverse-Slow-%K calculation. Returns a JSON-ready dict;
    on failure a dict with just {"error": ...}."""
    ticker = ticker.strip().upper()
    if interval not in INTERVALS:
        return {"error": f"unsupported interval '{interval}'"}
    label = INTERVALS[interval][1]

    bars, source = fetch_bars(ticker, interval)
    if not bars:
        return {"error": f"no {label} bars available for {ticker} — "
                         "check the ticker symbol (or Yahoo may be "
                         "rate-limiting; retry in a minute)"}
    needed = k_len + smooth - 1
    if len(bars) < needed:
        return {"error": f"only {len(bars)} {label} bars available for "
                         f"{ticker}; %K {k_len} with smoothing {smooth} "
                         f"needs at least {needed}"}

    fast, slow = stoch_series(bars, k_len, smooth)
    fast_k, slow_k = fast[-1], slow[-1]
    if fast_k is None or slow_k is None:
        return {"error": "could not compute the stochastic — bars have "
                         "missing high/low/close values"}
    # %D = SMA(smooth) of Slow %K — display-only context.
    d_win = [v for v in slow[-smooth:] if v is not None]
    percent_d = sum(d_win) / len(d_win) if len(d_win) == smooth else None

    price = float(bars[-1]["c"])
    state = ("overbought" if slow_k >= overbought
             else "oversold" if slow_k <= oversold else "neutral")

    def _solve(threshold: float, direction: str) -> list[dict]:
        out = []
        for k in range(1, smooth + 1):
            r = solve_price_for_slow_k(bars, threshold, direction, k,
                                       k_len, smooth)
            r["bars"] = k
            r["pct_move"] = (round((r["price"] - price) / price * 100.0, 2)
                             if (r["price"] is not None and price > 0) else None)
            out.append(r)
        return out

    return {
        "ticker": ticker,
        "interval": interval,
        "interval_label": label,
        "source": source,
        "bar_count": len(bars),
        "as_of": bars[-1].get("d"),
        "price": round(price, 4),
        "fast_k": round(fast_k, 2),
        "slow_k": round(slow_k, 2),
        "percent_d": round(percent_d, 2) if percent_d is not None else None,
        "state": state,
        "params": {"k_len": k_len, "smooth": smooth,
                   "overbought": overbought, "oversold": oversold},
        "to_oversold": _solve(oversold, "down"),
        "to_overbought": _solve(overbought, "up"),
    }
