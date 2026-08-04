"""Pure technical-condition engine for the 'technical' alert rule type.

Evaluates RSI, MACD and price-streak conditions over a plain bar list
(the {d,o,h,l,c,v} dicts calculators.fetch_bars returns), so it works
on ANY interval — 1m through 1mo — with no DataFrame or DB dependency.
Every function here is deterministic and network-free; alerts.py owns
the fetching, dedupe and Telegram formatting.

Indicator formulas are deliberately identical to screener._enrich
(Wilder RSI, SMA of RSI, EMA-based MACD) so an alert and a screen can
never disagree about the same bar.

Two evaluation modes per condition:
  state — true whenever the condition holds on the evaluated bar.
  cross — true only on the bar where it FIRST becomes true (it was
          false on the prior bar). Naturally one signal per setup.

Bearish rules mirror every comparison (RSI below / MACD below signal /
lower-low streak), so one rule carries one direction.
"""

from __future__ import annotations

# --- indicator primitives (mirrors of screener._enrich) -------------------


def _ema(values: list[float], period: int) -> list[float | None]:
    """EMA with min_periods=period — matches pandas ewm(span, adjust=False,
    min_periods=period): seeded from the first `period` values so early
    bars are None rather than a ramp-up artifact."""
    n = len(values)
    out: list[float | None] = [None] * n
    if n < period or period < 1:
        return out
    k = 2.0 / (period + 1.0)
    # pandas' adjust=False recursion starts at the first observation; the
    # min_periods rule only masks the first period-1 outputs.
    prev = values[0]
    for i in range(1, n):
        prev = values[i] * k + prev * (1 - k)
        if i >= period - 1:
            out[i] = prev
    if period == 1:
        out[0] = values[0]
    return out


def rsi_wilder(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder RSI, matching screener.rsi_wilder bar-for-bar.

    That implementation is pandas ewm(alpha=1/period, adjust=False,
    min_periods=period) over close.diff() — i.e. the recursion is SEEDED
    FROM THE FIRST DELTA (index 1), not from an SMA of the first `period`
    deltas as textbook Wilder does. The two agree asymptotically but
    differ by several RSI points in the first ~50 bars, which would make
    an alert and a screen disagree about the same bar. Replicated
    exactly here, including the min_periods masking (first output lands
    at index `period`: the 14th non-NaN delta)."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n <= period or period < 1:
        return out
    a = 1.0 / period
    avg_g = max(closes[1] - closes[0], 0.0)     # seed = first delta
    avg_l = max(closes[0] - closes[1], 0.0)
    for i in range(2, n):
        ch = closes[i] - closes[i - 1]
        avg_g = a * max(ch, 0.0) + (1 - a) * avg_g
        avg_l = a * max(-ch, 0.0) + (1 - a) * avg_l
        if i >= period:
            out[i] = 100.0 if avg_l == 0 else \
                100.0 - (100.0 / (1.0 + avg_g / avg_l))
    if period == 1 and n > 1:
        out[1] = 100.0 if avg_l == 0 else \
            100.0 - (100.0 / (1.0 + avg_g / avg_l))
    return out


def sma_of(series: list[float | None], window: int) -> list[float | None]:
    """Rolling mean with min_periods=window (None until the window fills,
    and None wherever the source series is still None)."""
    n = len(series)
    out: list[float | None] = [None] * n
    for i in range(n):
        if i + 1 < window:
            continue
        win = series[i - window + 1:i + 1]
        if any(v is None for v in win):
            continue
        out[i] = sum(win) / window          # type: ignore[arg-type]
    return out


def macd_series(closes: list[float], fast: int = 12, slow: int = 26,
                signal: int = 9) -> tuple[list, list, list]:
    """(macd_line, signal_line, histogram) — EMA(fast) - EMA(slow), then
    EMA(signal) of that line. None wherever not yet warm."""
    n = len(closes)
    ef, es = _ema(closes, fast), _ema(closes, slow)
    line: list[float | None] = [
        (ef[i] - es[i]) if (ef[i] is not None and es[i] is not None) else None
        for i in range(n)
    ]
    # The signal EMA runs over the warm portion of the MACD line only.
    warm = [i for i, v in enumerate(line) if v is not None]
    sig: list[float | None] = [None] * n
    hist: list[float | None] = [None] * n
    if warm:
        vals = [line[i] for i in warm]
        sig_vals = _ema(vals, signal)       # type: ignore[arg-type]
        for pos, i in enumerate(warm):
            sig[i] = sig_vals[pos]
            if sig[i] is not None:
                hist[i] = line[i] - sig[i]  # type: ignore[operator]
    return line, sig, hist


# --- condition helpers ----------------------------------------------------

def _cmp(value: float, threshold: float, bearish: bool) -> bool:
    """Bullish: value >= threshold. Bearish mirrors to value <= threshold."""
    return (value <= threshold) if bearish else (value >= threshold)


def _state_and_cross(states: list[bool | None], idx: int) -> tuple[bool, bool]:
    """(state_now, crossed_now) for a per-bar boolean series. A cross needs
    the prior bar to be a definite False — an unknown (None, i.e. not warm)
    prior bar is NOT treated as a cross."""
    now = states[idx] is True
    prev = states[idx - 1] if idx - 1 >= 0 else None
    return now, bool(now and prev is False)


def gap_pct(a: float, b: float) -> float:
    """Percent gap of a over b, guarding a near-zero denominator (MACD
    lines legitimately sit at ~0)."""
    denom = abs(b) if abs(b) > 1e-6 else 1e-6
    return (a - b) / denom * 100.0


# --- individual conditions ------------------------------------------------
# Each returns (passed, detail_str | None). detail is rendered in the
# alert body so the message shows exactly why it fired.


def cond_rsi_level(closes: list[float], idx: int, *, length: int,
                   threshold: float, mode: str, bearish: bool):
    rsi = rsi_wilder(closes, length)
    if rsi[idx] is None:
        return False, None
    states = [(_cmp(v, threshold, bearish) if v is not None else None)
              for v in rsi]
    now, crossed = _state_and_cross(states, idx)
    ok = crossed if mode == "cross" else now
    if not ok:
        return False, None
    arrow = "≤" if bearish else "≥"
    verb = "crossed " if mode == "cross" else ""
    return True, f"RSI({length}) {rsi[idx]:.1f} {verb}{arrow} {threshold:g}"


def cond_rsi_vs_sma(closes: list[float], idx: int, *, length: int,
                    sma_len: int, min_gap_pct: float, mode: str,
                    bearish: bool):
    rsi = rsi_wilder(closes, length)
    rsi_sma = sma_of(rsi, sma_len)
    if rsi[idx] is None or rsi_sma[idx] is None:
        return False, None
    states: list[bool | None] = []
    for r, s in zip(rsi, rsi_sma):
        if r is None or s is None:
            states.append(None)
            continue
        g = gap_pct(r, s)
        states.append((g <= -min_gap_pct) if bearish else (g >= min_gap_pct))
    now, crossed = _state_and_cross(states, idx)
    ok = crossed if mode == "cross" else now
    if not ok:
        return False, None
    g = gap_pct(rsi[idx], rsi_sma[idx])
    rel = "below" if bearish else "above"
    verb = f"crossed {rel}" if mode == "cross" else rel
    return True, (f"RSI {rsi[idx]:.1f} {verb} SMA({sma_len}) "
                  f"{rsi_sma[idx]:.1f} ({g:+.1f}%)")


def cond_macd_vs_signal(closes: list[float], idx: int, *, fast: int,
                        slow: int, signal: int, min_gap_pct: float,
                        mode: str, bearish: bool, require_hist_rising: bool):
    line, sig, hist = macd_series(closes, fast, slow, signal)
    if line[idx] is None or sig[idx] is None:
        return False, None
    states: list[bool | None] = []
    for m, s in zip(line, sig):
        if m is None or s is None:
            states.append(None)
            continue
        g = gap_pct(m, s)
        states.append((g <= -min_gap_pct) if bearish else (g >= min_gap_pct))
    now, crossed = _state_and_cross(states, idx)
    ok = crossed if mode == "cross" else now
    if not ok:
        return False, None
    detail = ""
    if require_hist_rising:
        # Bullish wants a rising histogram (momentum building), bearish a
        # falling one. Needs a warm prior bar.
        h, hp = hist[idx], hist[idx - 1] if idx - 1 >= 0 else None
        if h is None or hp is None:
            return False, None
        if (h >= hp) if bearish else (h <= hp):
            return False, None
        detail = f" · hist {h:+.3f} {'falling' if bearish else 'rising'}"
    rel = "below" if bearish else "above"
    verb = f"crossed {rel}" if mode == "cross" else rel
    return True, (f"MACD({fast},{slow},{signal}) {line[idx]:+.3f} {verb} "
                  f"signal {sig[idx]:+.3f}{detail}")


def cond_streak(bars: list[dict], idx: int, *, bars_n: int, streak_mode: str,
                bearish: bool):
    """Price-streak modes mirroring the screener's:
      high        — each bar's high above the prior bar's high
                    (bearish: each low below the prior low)
      close       — each close above the prior close (bearish: below)
      green       — each bar closes above its own open (bearish: red)
      close_green — both close-vs-prior-close AND body colour
    """
    if bars_n < 1 or idx + 1 < bars_n + 1:
        return False, None
    win = bars[idx - bars_n:idx + 1]          # bars_n + 1 bars
    try:
        closes = [float(b["c"]) for b in win]
        opens = [float(b["o"]) for b in win]
        highs = [float(b["h"]) for b in win]
        lows = [float(b["l"]) for b in win]
    except (KeyError, TypeError, ValueError):
        return False, None

    def _seq_ok(vals: list[float]) -> bool:
        return all((vals[i] < vals[i - 1]) if bearish else (vals[i] > vals[i - 1])
                   for i in range(1, len(vals)))

    def _body_ok() -> bool:
        return all((c < o) if bearish else (c > o)
                   for c, o in zip(closes[1:], opens[1:]))

    if streak_mode == "green":
        ok = _body_ok()
        label = f"{bars_n}-bar {'red' if bearish else 'green'} streak"
    elif streak_mode == "close":
        ok = _seq_ok(closes)
        label = f"{bars_n}-bar {'lower' if bearish else 'higher'}-close streak"
    elif streak_mode == "close_green":
        ok = _seq_ok(closes) and _body_ok()
        label = (f"{bars_n}-bar {'lower' if bearish else 'higher'}-close + "
                 f"{'red' if bearish else 'green'} streak")
    else:  # "high" (bearish: lows)
        ok = _seq_ok(lows if bearish else highs)
        label = f"{bars_n}-bar {'lower-low' if bearish else 'higher-high'} streak"
    if not ok:
        return False, None
    return True, label


def cond_avg_volume(bars: list[dict], idx: int, *, lookback: int,
                    min_avg: float):
    """Liquidity gate — mean volume over the `lookback` bars ending at idx
    must clear min_avg. Direction-independent."""
    if lookback < 1 or idx + 1 < lookback:
        return False, None
    vols = []
    for b in bars[idx - lookback + 1:idx + 1]:
        v = b.get("v")
        if v is None:
            return False, None
        try:
            vols.append(float(v))
        except (TypeError, ValueError):
            return False, None
    avg = sum(vols) / len(vols)
    if avg < min_avg:
        return False, None
    return True, f"avg vol {avg:,.0f} ≥ {min_avg:,.0f} ({lookback} bars)"


# --- rule evaluation ------------------------------------------------------

# Only these keys are meaningful for a technical rule.
DEFAULT_PARAMS: dict = {
    "interval": "1d",
    "direction": "bullish",          # bullish | bearish

    "apply_rsi_level": True,
    "rsi_length": 14,
    "rsi_threshold": 60.0,
    "rsi_mode": "cross",             # state | cross

    "apply_rsi_vs_sma": False,
    "rsi_sma_length": 9,
    "rsi_sma_min_gap_pct": 0.0,
    "rsi_sma_mode": "cross",

    "apply_macd": False,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "macd_min_gap_pct": 0.0,
    "macd_mode": "cross",
    "macd_hist_rising": False,

    "apply_streak": False,
    "streak_bars": 3,
    "streak_mode": "close",          # high | close | green | close_green

    "apply_avg_volume": True,
    "avg_volume_lookback": 20,
    "avg_volume_min": 500000.0,
}

MODES = ("state", "cross")
STREAK_MODES = ("high", "close", "green", "close_green")
DIRECTIONS = ("bullish", "bearish")


def evaluate(bars: list[dict], p: dict, *, closed_only: bool) -> dict:
    """Run every enabled condition against `bars`.

    closed_only drops the last (in-progress) bar before evaluating — used
    for 1d/1wk/1mo rules so a partial session can't fire an alert that's
    false by the close. Intraday rules evaluate the latest bar directly.

    Returns {ok, bar, price, details, reason}: ok=False carries a reason
    ('no_bars' | 'not_warm' | 'no_match'); ok=True carries the matched
    bar label, its close, and one detail line per satisfied condition.
    """
    if closed_only and len(bars) >= 2:
        bars = bars[:-1]
    if not bars:
        return {"ok": False, "reason": "no_bars"}
    idx = len(bars) - 1
    try:
        closes = [float(b["c"]) for b in bars]
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "reason": "no_bars"}

    bearish = str(p.get("direction", "bullish")).lower() == "bearish"
    details: list[str] = []
    enabled = 0

    if p.get("apply_rsi_level"):
        enabled += 1
        ok, d = cond_rsi_level(
            closes, idx, length=int(p.get("rsi_length", 14)),
            threshold=float(p.get("rsi_threshold", 60.0)),
            mode=str(p.get("rsi_mode", "cross")), bearish=bearish)
        if not ok:
            return {"ok": False, "reason": "no_match"}
        details.append(d)

    if p.get("apply_rsi_vs_sma"):
        enabled += 1
        ok, d = cond_rsi_vs_sma(
            closes, idx, length=int(p.get("rsi_length", 14)),
            sma_len=int(p.get("rsi_sma_length", 9)),
            min_gap_pct=float(p.get("rsi_sma_min_gap_pct", 0.0)),
            mode=str(p.get("rsi_sma_mode", "cross")), bearish=bearish)
        if not ok:
            return {"ok": False, "reason": "no_match"}
        details.append(d)

    if p.get("apply_macd"):
        enabled += 1
        ok, d = cond_macd_vs_signal(
            closes, idx, fast=int(p.get("macd_fast", 12)),
            slow=int(p.get("macd_slow", 26)),
            signal=int(p.get("macd_signal", 9)),
            min_gap_pct=float(p.get("macd_min_gap_pct", 0.0)),
            mode=str(p.get("macd_mode", "cross")), bearish=bearish,
            require_hist_rising=bool(p.get("macd_hist_rising")))
        if not ok:
            return {"ok": False, "reason": "no_match"}
        details.append(d)

    if p.get("apply_streak"):
        enabled += 1
        ok, d = cond_streak(
            bars, idx, bars_n=int(p.get("streak_bars", 3)),
            streak_mode=str(p.get("streak_mode", "close")), bearish=bearish)
        if not ok:
            return {"ok": False, "reason": "no_match"}
        details.append(d)

    if p.get("apply_avg_volume"):
        enabled += 1
        ok, d = cond_avg_volume(
            bars, idx, lookback=int(p.get("avg_volume_lookback", 20)),
            min_avg=float(p.get("avg_volume_min", 0.0)))
        if not ok:
            return {"ok": False, "reason": "no_match"}
        details.append(d)

    if not enabled:
        # A rule with nothing enabled would alert on every bar — treat it
        # as inert rather than a firehose.
        return {"ok": False, "reason": "no_conditions"}

    return {"ok": True, "bar": bars[idx].get("d"),
            "price": closes[idx], "details": details}
