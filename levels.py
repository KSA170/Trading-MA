"""Prior-session price structure — the horizontal levels a discretionary
trader actually targets.

Replaying the validated trades made one thing clear: the targets were not
oscillator projections, they were *yesterday's price structure*. Two
examples from the 5m QQQ tape:

  Jul 30 put  — entry 679.47, target 678.00. Prior session high 680.05,
                gap +13.03 (+1.97%). The target sat just under the prior
                high, on the retest of the gap.
  Aug 6  call — entry 714.85, target 718.00. Prior close 717.30, gap
                −6.54 (−0.91%). The target was the gap fill.

So: the stochastic times the entry, the prior session says where price is
going. This module supplies the second half — pure bar math, no I/O.

Everything here works off the bar dicts calculators.fetch_bars returns
({d,o,h,l,c,v}) and is interval-agnostic: intraday labels
("YYYY-MM-DD HH:MM") group into sessions by their date prefix, while
daily/weekly/monthly labels are already one bar per period.
"""

from __future__ import annotations

# Levels further away than this are noise for an intraday swing — a level
# 8% away isn't the target of a 5m bounce. Callers can override.
MAX_TARGET_PCT = 5.0


def _session_key(label) -> str:
    """Date portion of a bar label. Intraday labels are
    'YYYY-MM-DD HH:MM' (one session spans many bars); daily and higher
    labels are already unique per period, so they key to themselves."""
    s = str(label or "")
    return s[:10] if " " in s else s


def _f(bar: dict, key: str):
    try:
        v = bar.get(key)
        return None if v is None else float(v)
    except (AttributeError, TypeError, ValueError):
        return None


def _agg(bars: list[dict]) -> dict | None:
    """OHLC(V) of a group of bars, tolerating missing fields on some of
    them (Yahoo occasionally serves a bar with a null open)."""
    highs = [v for v in (_f(b, "h") for b in bars) if v is not None]
    lows = [v for v in (_f(b, "l") for b in bars) if v is not None]
    closes = [v for v in (_f(b, "c") for b in bars) if v is not None]
    if not (highs and lows and closes):
        return None
    opens = [v for v in (_f(b, "o") for b in bars) if v is not None]
    vols = [v for v in (_f(b, "v") for b in bars) if v is not None]
    return {
        "open": opens[0] if opens else None,
        "high": max(highs),
        "low": min(lows),
        "close": closes[-1],
        "volume": sum(vols) if vols else None,
        "bars": len(bars),
    }


def _group_sessions(bars: list[dict]) -> list[tuple[str, list[dict]]]:
    """Consecutive bars sharing a session key, in order. Bars are assumed
    chronological (calculators guarantees it)."""
    groups: list[tuple[str, list[dict]]] = []
    for b in bars:
        k = _session_key(b.get("d") if isinstance(b, dict) else None)
        if groups and groups[-1][0] == k:
            groups[-1][1].append(b)
        else:
            groups.append((k, [b]))
    return groups


def session_levels(bars: list[dict]) -> dict | None:
    """Prior-session levels plus the overnight gap, or None when the bar
    history doesn't cover two sessions.

    Returns:
      prior_date / prior_open / prior_high / prior_low / prior_close
      session_date / session_open / session_high / session_low
      gap        — session open minus prior close, in dollars
      gap_pct    — the same as a percent of the prior close
      gap_dir    — 'up' | 'down' | 'flat' (flat = under 0.05%)
      gap_filled — True once the current session has traded back through
                   the prior close (the gap-fill trade is already done)
    """
    if not bars:
        return None
    groups = _group_sessions(bars)
    if len(groups) < 2:
        return None
    prior_key, prior_bars = groups[-2]
    cur_key, cur_bars = groups[-1]
    prior, cur = _agg(prior_bars), _agg(cur_bars)
    if not prior or not cur:
        return None

    out = {
        "prior_date": prior_key,
        "prior_open": prior["open"],
        "prior_high": prior["high"],
        "prior_low": prior["low"],
        "prior_close": prior["close"],
        "prior_volume": prior["volume"],
        "session_date": cur_key,
        "session_open": cur["open"],
        "session_high": cur["high"],
        "session_low": cur["low"],
        "session_bars": cur["bars"],
    }
    p_close, s_open = prior["close"], cur["open"]
    if s_open is not None and p_close:
        gap = s_open - p_close
        gap_pct = gap / p_close * 100.0
        out["gap"] = round(gap, 4)
        out["gap_pct"] = round(gap_pct, 3)
        # 0.05% of a $700 index is ~35 cents — below that it's an open
        # print, not a gap worth trading toward.
        out["gap_dir"] = "up" if gap_pct > 0.05 else \
                         "down" if gap_pct < -0.05 else "flat"
        if out["gap_dir"] == "up":
            out["gap_filled"] = cur["low"] <= p_close
        elif out["gap_dir"] == "down":
            out["gap_filled"] = cur["high"] >= p_close
        else:
            out["gap_filled"] = True
    return out


# Prior-session levels only. The CURRENT session's high and low are
# deliberately excluded: on the evaluated bar price is standing on or
# near one of them, so they'd win "nearest level ahead" almost every
# time and crowd out the structure that actually matters. They stay in
# session_levels() for gap-fill bookkeeping and context.
#
# Order matters only as a tie-break, when two levels share a price.
_LEVEL_FIELDS = (
    ("prior_close", "prior close"),
    ("prior_high", "prior high"),
    ("prior_low", "prior low"),
)


def target_candidates(levels: dict | None, price: float, bearish: bool,
                      *, max_pct: float = MAX_TARGET_PCT) -> list[dict]:
    """Prior-session levels lying AHEAD of `price` in the trade's
    direction, nearest first.

    Bullish trades look up (levels above price), bearish trades look
    down. Levels beyond `max_pct` are dropped — an intraday swing is not
    aiming 8% away.

    Each entry: {key, label, price, pct, gap_fill}. gap_fill marks the
    prior close when the trade direction is the direction that closes an
    unfilled gap — the single most reliable target in the replayed
    trades.

    A level BEHIND price is not returned, and that's intentional even
    though such a level is still informative: on Jul 30 the prior high
    (680.05) sat just above a short entry at 679.47 and was the risk
    anchor, not the target — his stop went above it at 683.80. The raw
    H/C/L row in the alert body carries that reading; this function is
    only about where price is headed.
    """
    if not levels or not price or price <= 0:
        return []
    gap_dir = levels.get("gap_dir")
    unfilled = gap_dir in ("up", "down") and not levels.get("gap_filled")
    # A down gap fills by rallying back to the prior close; an up gap
    # fills by selling off to it.
    fill_is_ours = unfilled and ((gap_dir == "up") == bearish)

    out: list[dict] = []
    for key, label in _LEVEL_FIELDS:
        v = levels.get(key)
        if v is None:
            continue
        v = float(v)
        ahead = (v < price) if bearish else (v > price)
        if not ahead:
            continue
        pct = (v - price) / price * 100.0
        if abs(pct) > max_pct:
            continue
        out.append({
            "key": key,
            "label": label,
            "price": round(v, 4),
            "pct": round(pct, 3),
            "gap_fill": bool(fill_is_ours and key == "prior_close"),
        })
    out.sort(key=lambda d: abs(d["pct"]))
    return out


def primary_target(candidates: list[dict]) -> dict | None:
    """The level to actually aim at: an unfilled gap fill if one is on
    the table (that's what the replayed winners took), otherwise the
    nearest level ahead."""
    if not candidates:
        return None
    for c in candidates:
        if c.get("gap_fill"):
            return c
    return candidates[0]


def describe_gap(levels: dict | None) -> str | None:
    """One-line gap summary for an alert body, or None when there's no
    gap worth mentioning."""
    if not levels or levels.get("gap") is None:
        return None
    d = levels.get("gap_dir")
    if d == "flat":
        return None
    state = "filled" if levels.get("gap_filled") else "unfilled"
    return (f"gap {d} {levels['gap']:+.2f} ({levels['gap_pct']:+.2f}%) "
            f"· {state}")
