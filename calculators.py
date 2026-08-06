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

Backtesting: an optional `as_of` anchor restricts the calculation to
bars at or before that moment — the anchor bar becomes "current", so
the state and target prices are exactly what the calculator would have
said back then (no lookahead). When later bars exist, the result also
carries an `actual` section — the next `smooth` bars' closes and Slow
%K plus when each threshold was really hit — so the prediction can be
compared against what happened.
"""

from __future__ import annotations

import logging
import re
import threading
import time

log = logging.getLogger("calculators")

# interval -> (yfinance period, human label, cache TTL seconds).
# Periods sit AT Yahoo's per-interval history caps (1m ≤ ~7d,
# 5m-30m ≤ 60d, 1h ≤ 730d) so backtest anchors reach as far back as
# the data source allows.
INTERVALS: dict[str, tuple[str, str, int]] = {
    "1m":  ("7d",   "1 minute",   180),
    "5m":  ("60d",  "5 minutes",  180),
    "15m": ("60d",  "15 minutes", 180),
    "30m": ("60d",  "30 minutes", 180),
    "1h":  ("730d", "1 hour",     600),
    "1d":  ("2y",   "1 day",      1800),
    "1wk": ("10y",  "1 week",     3600),
    "1mo": ("max",  "1 month",    3600),
}

_cache: dict[tuple, tuple[float, list, str]] = {}
_cache_lock = threading.Lock()

# "YYYY-MM-DD", optionally with "T" or " " and "HH:MM[:SS]".
_ANCHOR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$")


def normalize_anchor(as_of) -> str | None:
    """Validate + normalize a backtest anchor to 'YYYY-MM-DD[ HH:MM]'.
    Returns None when the input is empty or malformed. The normalized
    form compares lexicographically against every bar-label format this
    module emits ('YYYY-MM', 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM')."""
    s = str(as_of or "").strip()
    if not s or not _ANCHOR_RE.match(s):
        return None
    s = s.replace("T", " ")
    return s[:16]   # drop seconds if present


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
                 k_len: int = 14, smooth: int = 3,
                 path: str = "hold") -> float | None:
    """Slow %K after appending k_bars synthetic bars.

    path 'hold':  every synthetic bar sits at `price` (gap and hold) —
                  models an immediate move that then consolidates.
    path 'drift': closes interpolate linearly from the last real close
                  to `price` across the k bars — models a steady
                  multi-bar swing, which is how OB→OS transitions
                  usually unfold on intraday charts. The trailing HH/LL
                  window rolls down (or up) along the path, so drift
                  targets differ meaningfully from hold targets.
    Either way each synthetic bar is flat (O=H=L=C)."""
    if path == "drift" and k_bars > 1:
        try:
            p0 = float(bars[-1]["c"])
        except (TypeError, ValueError, KeyError, IndexError):
            p0 = price
        synth = []
        for i in range(1, k_bars + 1):
            c = p0 + (price - p0) * i / k_bars
            synth.append({"h": c, "l": c, "c": c})
    else:
        synth = [{"h": price, "l": price, "c": price}] * k_bars
    _, slow = stoch_series(list(bars) + synth, k_len, smooth)
    return slow[-1]


def solve_price_for_slow_k(bars: list[dict], threshold: float, direction: str,
                           k_bars: int, k_len: int = 14, smooth: int = 3,
                           path: str = "hold") -> dict:
    """Bisection solve on the synthetic-bar simulation (see slow_k_after
    for the 'hold' vs 'drift' path models — both are monotonic in P, so
    the same bisection applies).

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
    f = lambda p: slow_k_after(tail, p, k_bars, k_len, smooth, path)

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


def _bar_label_fmt(interval: str) -> str:
    if interval in ("1m", "5m", "15m", "30m", "1h"):
        return "%Y-%m-%d %H:%M"
    if interval == "1mo":
        return "%Y-%m"
    return "%Y-%m-%d"


def _df_to_bars(df, interval: str) -> list[dict]:
    """OHLCV frame -> the bar-dict list the rest of the app consumes.

    Open and Volume are included: the technical rules' green/red candle
    streaks read 'o' and the liquidity gate reads 'v'. (They were absent
    here originally, which silently made every candle-colour streak and
    every avg-volume gate fail on Yahoo-sourced bars.)

    Intraday timestamps are normalized to America/New_York so a bar
    label means the same thing no matter which fetch path produced it —
    stoch_rule_state dedupe compares these labels as strings."""
    fmt = _bar_label_fmt(interval)
    tz_convert = interval in ("1m", "5m", "15m", "30m", "1h")
    out: list[dict] = []
    for idx, r in df.iterrows():
        try:
            o = float(r["Open"]); h = float(r["High"])
            l = float(r["Low"]); c = float(r["Close"])
        except (TypeError, ValueError, KeyError):
            continue
        # NaN row (halted / not-yet-traded bar in a batch frame)
        if o != o or h != h or l != l or c != c:
            continue
        try:
            v = float(r["Volume"])
            if v != v:
                v = None
        except (TypeError, ValueError, KeyError):
            v = None
        ts = idx
        if tz_convert and getattr(ts, "tzinfo", None) is not None:
            try:
                ts = ts.tz_convert("America/New_York")
            except Exception:
                pass
        out.append({"d": ts.strftime(fmt), "o": o, "h": h,
                    "l": l, "c": c, "v": v})
    return out


def _bars_from_yahoo(ticker: str, interval: str) -> tuple[list | None, str | None]:
    """Fetch OHLC bars from Yahoo for a single ticker."""
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
    bars = _df_to_bars(df, interval)
    return (bars, "live (Yahoo)") if bars else (None, None)


def prefetch_bars(tickers, interval: str, chunk: int = 50) -> int:
    """Warm the cache for many tickers with ONE Yahoo request per chunk.

    Per-ticker fetching does not survive a 5-minute alert cadence: with
    several rules × a dozen-plus tickers each, the lane was issuing ~50
    requests every run and Yahoo answered with empty frames (logged as
    no_data on every ticker, so no rule could ever evaluate). Batched
    downloads collapse that to 1-2 requests per interval per run.

    Only fills cache entries that are missing or stale, and never
    overwrites a good entry with an empty result, so a partial batch
    failure degrades to the per-ticker path rather than poisoning the
    cache. Returns the number of tickers warmed."""
    want = [t for t in dict.fromkeys(tickers) if t]
    if not want or interval not in INTERVALS:
        return 0
    period, _, ttl = INTERVALS[interval]
    now = time.time()
    with _cache_lock:
        todo = [t for t in want
                if not (_cache.get((t, interval, False))
                        and (now - _cache[(t, interval, False)][0]) < ttl)]
    if not todo:
        return 0

    try:
        import yfinance as yf
        import pandas as pd
    except Exception as exc:
        log.warning("prefetch_bars: import failed: %s", exc)
        return 0

    warmed = 0
    for i in range(0, len(todo), chunk):
        batch = todo[i:i + chunk]
        try:
            df = yf.download(tickers=" ".join(batch), period=period,
                             interval=interval, auto_adjust=False,
                             progress=False, threads=False,
                             group_by="ticker", prepost=False)
        except Exception as exc:
            log.warning("prefetch_bars %s batch (%d syms) failed: %s",
                        interval, len(batch), exc)
            continue
        if df is None or df.empty:
            log.info("prefetch_bars %s: empty frame for %d syms",
                     interval, len(batch))
            continue
        multi = isinstance(df.columns, pd.MultiIndex)
        stamp = time.time()
        for sym in batch:
            try:
                sub = df[sym] if multi else df
            except (KeyError, ValueError):
                continue
            if sub is None or sub.empty:
                continue
            bars = _df_to_bars(sub, interval)
            if not bars:
                continue
            with _cache_lock:
                _cache[(sym, interval, False)] = (stamp, bars, "live (Yahoo)")
            warmed += 1
    if warmed:
        log.info("prefetch_bars: warmed %d/%d %s tickers in %d request(s)",
                 warmed, len(todo), interval,
                 (len(todo) + chunk - 1) // chunk)
    return warmed


def fetch_bars(ticker: str, interval: str,
               skip_snapshot: bool = False) -> tuple[list | None, str | None]:
    """Bars for (ticker, interval), oldest first, with a source label.
    1-day prefers the DB snapshot (already holds 60 daily bars); every
    other interval — and the 1-day fallback — goes to Yahoo. Cached
    in-process per INTERVALS TTL.

    skip_snapshot forces the Yahoo path for 1-day bars — used when a
    backtest anchor sits too far back for the snapshot's 60-bar window
    (Yahoo's 2y daily history reaches much further)."""
    key = (ticker, interval, skip_snapshot)
    ttl = INTERVALS[interval][2]
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and (now - hit[0]) < ttl:
            return hit[1], hit[2]

    bars, source = (None, None)
    if interval == "1d" and not skip_snapshot:
        bars, source = _bars_from_snapshot(ticker)
    if bars is None:
        bars, source = _bars_from_yahoo(ticker, interval)
    if bars is not None:
        with _cache_lock:
            _cache[key] = (now, bars, source)
    return bars, source


# --- calculator orchestrator ----------------------------------------------

def project_bar_label(last_label: str | None, k: int, interval: str) -> str | None:
    """Approximate label of the k-th future bar after `last_label`, in
    the same format that interval's bars use. Intraday projection stays
    inside the regular session (09:30–16:00 ET) and rolls across days;
    daily skips weekends. Market holidays are NOT skipped — the label is
    informational, not a trading clock — so a projection spanning a
    holiday reads one day early."""
    if not last_label or k <= 0:
        return None
    from datetime import datetime as _dt, timedelta as _td
    s = str(last_label)
    try:
        if interval == "1mo":
            d = _dt.strptime(s[:7], "%Y-%m")
            mo = d.month - 1 + k
            return f"{d.year + mo // 12:04d}-{mo % 12 + 1:02d}"
        if interval == "1wk":
            d = _dt.strptime(s[:10], "%Y-%m-%d")
            return (d + _td(weeks=k)).strftime("%Y-%m-%d")
        if interval == "1d":
            d = _dt.strptime(s[:10], "%Y-%m-%d")
            step = 0
            while step < k:
                d += _td(days=1)
                if d.weekday() < 5:
                    step += 1
            return d.strftime("%Y-%m-%d")
        mins = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}.get(interval)
        if not mins:
            return None
        d = _dt.strptime(s[:16], "%Y-%m-%d %H:%M")
        open_min, close_min = 9 * 60 + 30, 16 * 60
        for _ in range(k):
            d += _td(minutes=mins)
            hm = d.hour * 60 + d.minute
            if hm >= close_min:
                d = (d + _td(days=1)).replace(hour=9, minute=30)
            elif hm < open_min:
                d = d.replace(hour=9, minute=30)
            while d.weekday() >= 5:
                d += _td(days=1)
        return d.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None


def _anchor_index(bars: list[dict], anchor: str) -> int | None:
    """Index of the last bar at or before `anchor`, or None. Bar 'd'
    labels and the normalized anchor share lexicographic date ordering
    across all this module's formats."""
    idx = None
    for i, b in enumerate(bars):
        d = b.get("d")
        if d is not None and str(d) <= anchor:
            idx = i
    return idx


def stoch_reverse(ticker: str, interval: str, *, k_len: int = 14,
                  smooth: int = 3, overbought: float = 80.0,
                  oversold: float = 20.0, as_of: str | None = None,
                  path: str = "hold", horizon: int | None = None) -> dict:
    """Full reverse-Slow-%K calculation. Returns a JSON-ready dict;
    on failure a dict with just {"error": ...}.

    as_of (normalized 'YYYY-MM-DD[ HH:MM]') anchors a backtest: only
    bars at or before it feed the calculation, and later bars — when
    they exist — populate the `actual` outcome section.

    path is the synthetic-bar model ('hold' or 'drift' — see
    slow_k_after). horizon is the furthest bar count solved for
    (default = smooth; capped at k_len - 1, beyond which the trailing
    window would be entirely synthetic and the answer degenerates).
    Past k = smooth, 'hold' targets move only through HH/LL window
    rolloff (old extremes dropping out); 'drift' targets change with
    every horizon since the path itself stretches."""
    ticker = ticker.strip().upper()
    if interval not in INTERVALS:
        return {"error": f"unsupported interval '{interval}'"}
    if path not in ("hold", "drift"):
        return {"error": f"unsupported path model '{path}'"}
    period, label, _ = INTERVALS[interval]
    needed = k_len + smooth - 1
    horizon = smooth if horizon is None else int(horizon)
    horizon = max(1, min(max(1, k_len - 1), horizon))

    bars, source = fetch_bars(ticker, interval)
    if not bars:
        return {"error": f"no {label} bars available for {ticker} — "
                         "check the ticker symbol (or Yahoo may be "
                         "rate-limiting; retry in a minute)"}

    anchor = normalize_anchor(as_of) if as_of else None
    if as_of and anchor is None:
        return {"error": "start-from must look like YYYY-MM-DD or "
                         "YYYY-MM-DD HH:MM"}
    future: list[dict] = []
    if anchor:
        idx = _anchor_index(bars, anchor)
        # The snapshot only holds ~60 daily bars; when the anchor sits
        # too deep for it, retry against Yahoo's 2y daily history.
        if (interval == "1d" and source and source.startswith("snapshot")
                and (idx is None or idx + 1 < needed)):
            deep_bars, deep_source = fetch_bars(ticker, interval,
                                                skip_snapshot=True)
            if deep_bars:
                deep_idx = _anchor_index(deep_bars, anchor)
                if deep_idx is not None and (idx is None or deep_idx + 1 > idx + 1):
                    bars, source, idx = deep_bars, deep_source, deep_idx
        if idx is None:
            return {"error": f"no {label} bars at or before {anchor} for "
                             f"{ticker} — this interval's history reaches "
                             f"back about {period}"}
        future = bars[idx + 1: idx + 1 + horizon]
        bars = bars[:idx + 1]

    if len(bars) < needed:
        return {"error": f"only {len(bars)} {label} bars available for "
                         f"{ticker}"
                         + (f" at or before {anchor}" if anchor else "")
                         + f"; %K {k_len} with smoothing {smooth} needs "
                           f"at least {needed}"}

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
        last_d = bars[-1].get("d")
        for k in range(1, horizon + 1):
            r = solve_price_for_slow_k(bars, threshold, direction, k,
                                       k_len, smooth, path)
            r["bars"] = k
            # Projected timestamp of the k-th future bar — lets the UI
            # render target rows in the same shape as the actual-outcome
            # rows (and line up 1:1 with them in a backtest).
            r["d"] = project_bar_label(last_d, k, interval)
            r["pct_move"] = (round((r["price"] - price) / price * 100.0, 2)
                             if (r["price"] is not None and price > 0) else None)
            out.append(r)
        return out

    # Backtest outcome: what really happened over the next `horizon`
    # bars. Stochastic values at each future bar depend only on bars up
    # to that bar, so computing over past+future introduces no lookahead
    # into any individual reading.
    actual = None
    if future:
        _, slow_ext = stoch_series(bars + future, k_len, smooth)
        rows = []
        hit_os = hit_ob = None
        for j, fb in enumerate(future):
            sk = slow_ext[len(bars) + j]
            fc = fb.get("c")
            rows.append({
                "d": fb.get("d"),
                "close": round(float(fc), 4) if fc is not None else None,
                "slow_k": round(sk, 2) if sk is not None else None,
                "pct_move": (round((float(fc) - price) / price * 100.0, 2)
                             if (fc is not None and price > 0) else None),
            })
            if sk is not None:
                if hit_os is None and sk <= oversold:
                    hit_os = j + 1
                if hit_ob is None and sk >= overbought:
                    hit_ob = j + 1
        actual = {"rows": rows,
                  "hit_oversold_after": hit_os,
                  "hit_overbought_after": hit_ob}

    return {
        "ticker": ticker,
        "interval": interval,
        "interval_label": label,
        "source": source,
        "bar_count": len(bars),
        "as_of": bars[-1].get("d"),
        "anchored": bool(anchor),
        "anchor": anchor,
        "price": round(price, 4),
        "fast_k": round(fast_k, 2),
        "slow_k": round(slow_k, 2),
        "percent_d": round(percent_d, 2) if percent_d is not None else None,
        "state": state,
        "path": path,
        "horizon": horizon,
        "params": {"k_len": k_len, "smooth": smooth,
                   "overbought": overbought, "oversold": oversold},
        "to_oversold": _solve(oversold, "down"),
        "to_overbought": _solve(overbought, "up"),
        "actual": actual,
    }
