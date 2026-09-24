"""The entry checklist as an alert rule — pure evaluation, no I/O.

The Checklist tab in the UI is a gate a person works top to bottom before
an options entry. This module runs the machine-checkable part of that same
gate over a bar series, so a ticker list can be watched for setups that
pass it rather than for a bare oscillator trigger.

Design constraints that fall out of "it must BE the checklist":

  * Every item maps 1:1 to a numbered item on the tab, and each carries
    the tab's own wording. If the two ever disagree, the alert is lying
    about what it checked.
  * The result is an itemised report, not a boolean. A near-miss is worth
    seeing in the run log, and the alert body renders the passing items as
    the ticked list they are.
  * Both directions are evaluated on every bar. The checklist mirrors for
    puts and calls, and a rule watching a ticker should say WHICH side set
    up rather than making that a configuration choice.
  * Items the machine cannot judge (a scheduled release, position size,
    post-entry discipline) are never silently dropped — they ride along
    as `manual` so the alert can still show them as the reader's job.

Nothing here fetches, and nothing here decides to send. alerts.py owns
the bars, the dedupe and the Telegram body.
"""

from __future__ import annotations

import levels as levels_mod
import technicals as TH

# Items the engine cannot evaluate, surfaced in the alert so the reader
# knows the gate is not fully automated. Wording matches the tab.
MANUAL_ITEMS = (
    "No scheduled event in the next hour (CPI, FOMC, jobs, major earnings)",
    "Size is 1 contract — not scaling up because the last trade won",
    "Place the stop order now, and start the 60-minute clock",
)

DEFAULT_PARAMS: dict = {
    "interval": "5m",
    "sides": "both",                 # both | call | put
    # Evaluate only bars that have closed. ON by default: alerts.py explains
    # the measurement, but the short version is that reading the forming bar
    # produced 5 false starts in 12 alerts over 7 sessions, and a sent alert
    # cannot be recalled. Turn it off to trade the bar as it forms.
    "closed_only": True,

    # --- Step 1: context ------------------------------------------------
    "step1_gap": True,
    "gap_veto_pct": 0.5,
    "step1_rsi": True,
    "rsi_length": 14,
    "rsi_max_for_puts": 60.0,
    "rsi_min_for_calls": 40.0,
    "step1_failed_extreme": True,
    "step1_open_bar": True,
    # Against OTHER OPENING BARS, not against the preceding bars: every
    # 9:30 bar is enormous, so the only question worth asking is whether
    # this one was enormous even for an open. Over the Sept sample those
    # ratios ran 0.61x-1.26x, so 1.5x is a genuine outlier — but that is
    # seven sessions, which is weak calibration.
    "open_bar_max_ratio": 1.5,

    # --- Step 2: signal -------------------------------------------------
    "k_len": 14,
    "smooth": 3,
    "d_len": 3,
    "oversold": 20.0,
    "overbought": 80.0,
    "lookback_bars": 4,
    "step2_turn_min": 3.0,           # the tab says "at least 3-5 points"
    "step2_fast_k": True,
    "step2_kd": True,
    "step2_exit_band": False,        # the tab's "best confirmation"

    # --- Step 3: volume -------------------------------------------------
    "step3_volume": True,
    "vol_lookback": 5,
    "vol_min_ratio": 1.5,
    # How many bars, ending at the signal bar, may carry the expansion.
    # 1 is the literal reading of the tab ("the signal bar"); 2 also
    # accepts the bar before it.
    #
    # Replaying 2026-09-16..09-23, requiring it on the signal bar alone
    # produced 0 alerts from 816 side-evaluations — the gate could not
    # open. Loosening the RATIO did not help (1.2x still gave 0); only
    # widening the WINDOW did. That is the honest reading of the tape:
    # the surge marks the bar a move starts on, and the oscillator
    # confirms a bar or two later, so demanding both on the same five
    # minutes asks for a coincidence rather than a condition.
    "vol_window": 2,

    # --- Step 4: plan ---------------------------------------------------
    "step4_rr": True,
    "min_rr": 1.5,
    "stop_buffer_pct": 0.15,
    # A prior-session level nearer than this stops being a target and
    # becomes where price already is. 0.15% is about two median QQQ 5m
    # bars (the median bar spans 0.082% of price, p90 is 0.180%), so a
    # target inside it sits within a single bar's noise. Measured on
    # 2026-09-24: price 741.79, prior close 741.17 — 0.08% away — scored
    # the trade 0.31:1 and failed the reward test, while the prior low
    # 0.48% below scored 1.82:1.
    "target_min_pct": 0.15,
}

SIDES = ("both", "call", "put")


def _session_bars(bars: list[dict]) -> list[dict]:
    """Bars belonging to the latest session key (date prefix for intraday
    labels, the single bar itself for daily and above)."""
    if not bars:
        return []
    key = levels_mod._session_key(bars[-1].get("d"))
    return [b for b in bars if levels_mod._session_key(b.get("d")) == key]


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


# --- individual checks ----------------------------------------------------
# Each returns (ok, detail). detail always describes the reading, whether
# it passed or not, so a near-miss is legible in the run log.


def _targets(lv, price, bearish, p):
    """Target candidates under this rule's own minimum-distance floor.
    Both the reward gate and the reported plan go through here so they
    can never disagree about which level is being aimed at."""
    return levels_mod.target_candidates(
        lv, price, bearish, min_pct=float(p.get("target_min_pct", 0.15)))


def check_gap(bars, lv, bearish, p):
    blocked, why = levels_mod.gap_veto(lv, bearish, float(p.get("gap_veto_pct", 0.5)))
    if blocked:
        return False, why
    if not lv or lv.get("gap_pct") is None:
        return True, "no prior session to gap from"
    state = "filled" if lv.get("gap_filled") else "unfilled"
    return True, f"gap {lv['gap_pct']:+.2f}% · {state}"


def check_rsi(closes, bearish, p):
    blocked, detail = TH.rsi_regime_block(
        closes, len(closes) - 1, length=int(p.get("rsi_length", 14)),
        bearish=bearish, put_max=float(p.get("rsi_max_for_puts", 60.0)),
        call_min=float(p.get("rsi_min_for_calls", 40.0)))
    if detail is None:
        return True, "RSI not warm yet — not blocking"
    return (not blocked), detail


def check_failed_extreme(bars, bearish):
    """Tab item 1c: price is making lower highs / has failed at the day's
    high (mirrored: higher lows / has stopped falling).

    Mechanised as: the session's extreme in the trade's favour is NOT the
    bar we are standing on. Fading an extreme that is still being made is
    the 9/17 mistake in miniature — there is nothing to fade yet."""
    sess = _session_bars(bars)
    if len(sess) < 2:
        # Two very different situations produce a one-bar session.
        #
        # Intraday, this is the OPENING bar: nothing has failed yet, which
        # is a genuine "no" rather than missing data, so it must block. It
        # previously passed here, and on 2026-09-23 that handed a free tick
        # to a 09:30 put — the one bar of the day where, by construction,
        # price cannot yet have failed at anything.
        #
        # On a daily or higher interval one bar IS a session, so the item
        # has no meaning and passing is correct.
        groups = levels_mod._group_sessions(bars)
        intraday = any(len(g[1]) > 1 for g in groups[:-1])
        if intraday:
            return False, "opening bar — nothing has failed yet"
        return True, "one bar per session — item does not apply"
    highs = [_f(b.get("h")) for b in sess]
    lows = [_f(b.get("l")) for b in sess]
    if bearish:
        vals = [v for v in highs if v is not None]
        if not vals:
            return True, "no session highs"
        ext = max(vals)
        at_extreme = highs[-1] is not None and highs[-1] >= ext - 1e-9
        bars_since = len(sess) - 1 - max(
            i for i, v in enumerate(highs) if v is not None and v >= ext - 1e-9)
        return (not at_extreme), (
            f"session high {ext:.2f} set {bars_since} bar(s) ago"
            if not at_extreme else
            f"still making the session high ({ext:.2f}) — no failure yet")
    vals = [v for v in lows if v is not None]
    if not vals:
        return True, "no session lows"
    ext = min(vals)
    at_extreme = lows[-1] is not None and lows[-1] <= ext + 1e-9
    bars_since = len(sess) - 1 - max(
        i for i, v in enumerate(lows) if v is not None and v <= ext + 1e-9)
    return (not at_extreme), (
        f"session low {ext:.2f} set {bars_since} bar(s) ago"
        if not at_extreme else
        f"still making the session low ({ext:.2f}) — no turn yet")


def check_open_bar(bars, bearish, p):
    """Tab item 1d: the session's opening bar was not a huge surge against
    the trade.

    'Huge' is measured against the FIRST BAR OF PRIOR SESSIONS, not against
    the bars immediately before — every 9:30 print is enormous, so the only
    meaningful question is whether this one was enormous even for an open.

    That distinction matters, and it cost an earlier claim: 9/17's open was
    described as "3.41x normal" on the strength of comparing it to the
    previous session's CLOSING bars. Against other opens it was 1.01x —
    entirely ordinary. The tell on 9/17 was the unfilled +1.60% gap and RSI
    72.5, both caught by items 1a and 1b. Opening volume was a red herring,
    so this item is a weak guard rather than the one that saves the trade.

    Direction still has to be against the trade — a big opening bar in the
    trade's own direction is not a warning."""
    sess = _session_bars(bars)
    if not sess:
        return True, "no session bars"
    first = sess[0]
    o, c, v = _f(first.get("o")), _f(first.get("c")), _f(first.get("v"))
    if None in (o, c, v) or v <= 0:
        return True, "opening bar not measurable — not blocking"
    prior = [b for b in bars if b not in sess]
    # Same slot in previous sessions: the first bar of each.
    keys, firsts = set(), []
    for b in prior:
        k = levels_mod._session_key(b.get("d"))
        if k not in keys:
            keys.add(k)
            fv = _f(b.get("v"))
            if fv:
                firsts.append(fv)
    if not firsts:
        return True, f"opening bar {v:,.0f} (no history to compare)"
    base = TH._median(firsts)
    ratio = v / base if base > 0 else None
    if ratio is None:
        return True, f"opening bar {v:,.0f} (no usable baseline)"
    against = (c > o) if bearish else (c < o)
    limit = float(p.get("open_bar_max_ratio", 2.5))
    if against and ratio >= limit:
        return False, (f"opening bar {ratio:.2f}x normal and "
                       f"{'up' if c > o else 'down'} — a drive against this trade")
    return True, (f"opening bar {ratio:.2f}x normal"
                  + (f", {'up' if c > o else 'down'}" if against else ""))


def check_signal(fast, slow, pct_d, bearish, p):
    """Tab items 2a-2e, as one report.

    Returns (ok, details_by_item) where details_by_item is a list of
    (label, ok, detail) — the alert renders the whole list so a reader can
    see which part of the turn is missing."""
    out = []
    ob = float(p.get("overbought", 80.0))
    os_ = float(p.get("oversold", 20.0))
    lb = max(1, int(p.get("lookback_bars", 4)))
    band = ob if bearish else os_

    # 2a — visited the band within the lookback
    recent = [v for v in slow[-(lb + 1):-1] if v is not None]
    if not recent:
        return False, [("Reached the band", False, "not enough history")]
    reached = (max(recent) >= ob) if bearish else (min(recent) <= os_)
    edge = max(recent) if bearish else min(recent)
    out.append((f"%K reached {'above' if bearish else 'below'} {band:g} in the last {lb} bars",
                reached, f"extreme {edge:.1f}"))

    # 2b — a real turn, not a wiggle
    turn_min = float(p.get("step2_turn_min", 3.0))
    moved = (slow[-2] - slow[-1]) if bearish else (slow[-1] - slow[-2])
    turned = moved >= turn_min
    out.append((f"%K has turned {'down' if bearish else 'up'} at least {turn_min:g} points",
                turned, f"{slow[-2]:.1f} → {slow[-1]:.1f} ({moved:+.1f})"))

    # 2c — Fast %K agrees (the engine's original test)
    if p.get("step2_fast_k"):
        ok = (fast[-1] < slow[-1]) if bearish else (fast[-1] > slow[-1])
        out.append((f"Fast %K is {'below' if bearish else 'above'} %K",
                    ok, f"Fast %K {fast[-1]:.1f} vs %K {slow[-1]:.1f}"))

    # 2d — the signal line agrees (what the chart actually shows)
    if p.get("step2_kd"):
        d = pct_d[-1]
        if d is None:
            out.append(("%K has crossed %D", True, "%D not warm — not blocking"))
        else:
            ok = (slow[-1] < d) if bearish else (slow[-1] > d)
            out.append((f"%K is {'below' if bearish else 'above'} %D",
                        ok, f"%K {slow[-1]:.1f} vs %D {d:.1f}"))

    # 2e — back out of the band (the tab's "best confirmation")
    if p.get("step2_exit_band"):
        ok = (slow[-1] < ob) if bearish else (slow[-1] > os_)
        out.append((f"%K is back {'under' if bearish else 'over'} {band:g}",
                    ok, f"%K {slow[-1]:.1f}"))

    return all(o for _, o, _ in out), out


def check_volume(bars, p):
    """Tab item 3: did the move carry participation, or is it drift?

    Each candidate bar is scored against the MEDIAN volume of the five
    bars before IT — a ratio, so it means the same thing on any ticker
    and any interval, and a median so one outlier (the 9:30 print above
    all) cannot drag the baseline and make a real expansion read as a
    contraction.

    `vol_window` bars ending at the signal bar are searched, and the
    first one clearing the ratio satisfies the item. The detail always
    names WHICH bar carried it, so a reader can find it on the chart.
    """
    lb = max(1, int(p.get("vol_lookback", 5)))
    win = max(1, int(p.get("vol_window", 2)))
    need = float(p.get("vol_min_ratio", 1.5))
    idx = len(bars) - 1
    best = None
    for back in range(win):
        i = idx - back
        if i < 0:
            break
        now, base, ratio = TH.volume_expansion(bars, i, lb)
        if ratio is None:
            continue
        where = ("on the signal bar" if back == 0
                 else f"{back} bar{'s' if back > 1 else ''} earlier")
        if ratio >= need:
            return True, (f"{ratio:.2f}x the prior {lb}-bar median {where} "
                          f"({now:,.0f} vs {base:,.0f}), need {need:.2f}x")
        if best is None or ratio > best[0]:
            best = (ratio, where)
    if best is None:
        return True, "volume not measurable — not blocking"
    if win == 1:
        return False, f"{best[0]:.2f}x on the signal bar, need {need:.2f}x"
    return False, (f"best {best[0]:.2f}x in the last {win} bars ({best[1]}), "
                   f"need {need:.2f}x")


def check_rr(price, lv, bearish, p):
    """Tab item 4a: reward at least min_rr x risk, using prior-session
    structure for the target and the session extreme for the stop — the
    same two anchors the tab's worked examples use."""
    cands = _targets(lv, price, bearish, p)
    target = levels_mod.primary_target(cands)
    if not target:
        return False, ("no prior-session level far enough ahead to target "
                       f"(need {float(p.get('target_min_pct', 0.15)):.2f}% clear)")
    buf = float(p.get("stop_buffer_pct", 0.15)) / 100.0
    if not lv:
        return False, "no session levels"
    ext = lv.get("session_high") if bearish else lv.get("session_low")
    if ext is None:
        return False, "no session extreme to place a stop against"
    stop = ext * ((1 + buf) if bearish else (1 - buf))
    risk = abs(price - stop)
    reward = abs(target["price"] - price)
    if risk < 1e-6:
        return False, "stop sits on the entry"
    rr = reward / risk
    need = float(p.get("min_rr", 1.5))
    return rr >= need, (f"{rr:.2f}:1 — target {target['price']:.2f} "
                        f"({target['label']}), stop {stop:.2f}, need {need:.2f}:1")


# --- the whole gate -------------------------------------------------------

def evaluate_side(bars, fast, slow, pct_d, bearish: bool, p: dict) -> dict:
    """Run every enabled item for one side.

    Returns {ok, side, items, failed, price, plan} where items is a list
    of (label, ok, detail) in checklist order."""
    closes = [float(b["c"]) for b in bars]
    price = closes[-1]
    lv = levels_mod.session_levels(bars)
    items: list[tuple[str, bool, str]] = []

    if p.get("step1_gap"):
        ok, d = check_gap(bars, lv, bearish, p)
        items.append((f"No unfilled gap {'up' if bearish else 'down'} against the trade", ok, d))
    if p.get("step1_rsi"):
        ok, d = check_rsi(closes, bearish, p)
        items.append(("RSI regime allows this side", ok, d))
    if p.get("step1_failed_extreme"):
        ok, d = check_failed_extreme(bars, bearish)
        items.append((f"Price has failed at the session {'high' if bearish else 'low'}", ok, d))
    if p.get("step1_open_bar"):
        ok, d = check_open_bar(bars, bearish, p)
        items.append(("The 9:30 bar was not a surge against the trade", ok, d))

    sig_ok, sig_items = check_signal(fast, slow, pct_d, bearish, p)
    items.extend(sig_items)

    if p.get("step3_volume"):
        ok, d = check_volume(bars, p)
        # The label has to track the window, or a widened rule reports a
        # check it did not actually perform.
        items.append((
            "Volume expanded on the signal bar"
            if int(p.get("vol_window", 2)) <= 1
            else "Volume expanded on or just before the signal bar", ok, d))

    plan = None
    if p.get("step4_rr"):
        ok, d = check_rr(price, lv, bearish, p)
        items.append(("Reward clears the risk multiple", ok, d))

    # The plan numbers ride along whether or not the R:R item is enabled —
    # an alert without a target and a stop is not actionable.
    cands = _targets(lv, price, bearish, p)
    target = levels_mod.primary_target(cands)
    ext = (lv or {}).get("session_high" if bearish else "session_low")
    if target and ext is not None:
        buf = float(p.get("stop_buffer_pct", 0.15)) / 100.0
        stop = ext * ((1 + buf) if bearish else (1 - buf))
        risk = abs(price - stop)
        plan = {
            "target": round(target["price"], 2), "target_label": target["label"],
            "gap_fill": bool(target.get("gap_fill")),
            "stop": round(stop, 2),
            "rr": round(abs(target["price"] - price) / risk, 2) if risk > 1e-6 else None,
            "target_pct": round((target["price"] - price) / price * 100, 2),
            "stop_pct": round((stop - price) / price * 100, 2),
        }

    failed = [lbl for lbl, ok, _ in items if not ok]
    return {
        "ok": not failed, "side": "put" if bearish else "call",
        "items": items, "failed": failed, "price": price,
        "levels": lv, "plan": plan,
        "slow_k": round(slow[-1], 1), "slow_k_prev": round(slow[-2], 1),
        "fast_k": round(fast[-1], 1),
        "pct_d": round(pct_d[-1], 1) if pct_d[-1] is not None else None,
    }


def evaluate(bars: list[dict], p: dict) -> dict:
    """Run the gate for whichever sides the rule watches.

    Returns {ok, reason, result} — result is the passing side's report, or
    the closest near-miss when nothing passed (fewest failed items), so the
    run log can say how close a ticker came."""
    k_len = int(p.get("k_len", 14))
    smooth = int(p.get("smooth", 3))
    lb = max(1, int(p.get("lookback_bars", 4)))
    if not bars or len(bars) < k_len + smooth + lb + 2:
        return {"ok": False, "reason": "no_data"}
    try:
        [float(b["c"]) for b in bars]
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "reason": "no_data"}

    import calculators
    fast, slow = calculators.stoch_series(bars, k_len, smooth)
    if fast[-1] is None or slow[-1] is None or slow[-2] is None:
        return {"ok": False, "reason": "no_data"}
    pct_d = TH.sma_of(slow, max(2, int(p.get("d_len", 3))))

    sides = str(p.get("sides", "both"))
    want = [False, True] if sides == "both" else [sides == "put"]
    reports = [evaluate_side(bars, fast, slow, pct_d, b, p) for b in want]

    passed = [r for r in reports if r["ok"]]
    if passed:
        # Both sides passing at once would mean the parameters are
        # self-contradictory; prefer the one whose plan is defined.
        best = sorted(passed, key=lambda r: (r["plan"] is None,))[0]
        return {"ok": True, "result": best}
    near = sorted(reports, key=lambda r: len(r["failed"]))[0]
    return {"ok": False, "reason": "no_match", "result": near}
