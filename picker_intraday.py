"""
Stage 2: intraday monitor for the nightly watchlist (top 25).

Runs every ~5 min during US market hours via GitHub Actions. Watches
today's top 25 picks via Alpaca 5-min bars and fires a Telegram alert
the first time each ticker prints one of:

  - pivot_breakout: 5-min bar closes above the prior 20-day high
    on >= 1.5x the avg 5-min volume (daily_avg_volume / 78). This is
    the breakout the nightly composite's DP sub-score predicted — the
    watchlist sits ~1.5% below the pivot by design, so this trigger
    catches the exact moment the setup resolves up.

  - orb: Opening Range Breakout. The first 3 regular-session bars
    (9:30-9:45 ET) define the morning high; fire on a later bar that
    closes above that high on >= 1.2x the opening-range average
    volume. Self-contained — doesn't need a multi-day baseline.

Both are higher-conviction than the previous vwap_reclaim trigger
(which fired any time price re-crossed VWAP and produced too many
false positives for pre-vetted watchlist names).

Premarket bars are filtered out — pivot breaks and ORBs both require
regular-session trades only.

Idempotent via picker_intraday_alerts PK on (date, ticker, trigger):
re-running this cron multiple times on the same trading day re-sends
zero alerts.

TSX tickers (.TO suffix) are skipped — Alpaca doesn't carry them
intraday. They still appear in the nightly digest + UI watchlist.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("picker_intraday")


_ET_OFFSET_HOURS = -5   # EST baseline; alerts.py uses zoneinfo for accuracy
_FORCE_RUN_ENV = "PICKER_INTRADAY_FORCE_RUN"


def _et_now() -> datetime:
    """ET wall clock, DST-aware via zoneinfo (Python 3.9+)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        # Fallback — treat as EST (will be 1hr off during DST).
        return datetime.now(timezone.utc) + timedelta(hours=_ET_OFFSET_HOURS)


def _market_is_open(now_et: datetime) -> bool:
    """Loose check: weekday + 9:30-16:00 ET. Doesn't account for
    holidays — the cron skips off-hours but a holiday-day run is
    cheap (Alpaca returns no bars, nothing to evaluate, no alerts)."""
    if now_et.weekday() >= 5:
        return False
    hm = now_et.hour * 100 + now_et.minute
    return 930 <= hm <= 1600


def _today_et_date(now_et: datetime) -> str:
    return now_et.strftime("%Y-%m-%d")


def _is_us_ticker(t: str) -> bool:
    """TSX (.TO) and TSXV (.V) aren't on Alpaca."""
    if not t:
        return False
    return not (t.endswith(".TO") or t.endswith(".V"))


def _fetch_5min_bars_today(symbols: list[str], date_str: str) -> dict[str, list[dict]]:
    """One call to Alpaca's /v2/stocks/bars at timeframe=5Min for `date_str`.
    Reuses the same auth + symbol-translation conventions alerts.py uses
    for daily bars. Returns {symbol: [bar, ...]} keyed by the caller's
    original symbols."""
    import alerts  # noqa: WPS433 — runtime dep, lets us share Alpaca auth
    if not (alerts.ALPACA_API_KEY and alerts.ALPACA_SECRET_KEY) or not symbols:
        return {}

    import requests

    # Alpaca uses dots for share classes (BRK.B); the universe carries
    # hyphens (BRK-B). Translate for the request, then map response keys
    # back to the original.
    req_for = {s: s.replace("-", ".") for s in symbols}
    orig_for = {a: s for s, a in req_for.items()}
    headers = {
        "APCA-API-KEY-ID": alerts.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": alerts.ALPACA_SECRET_KEY,
    }
    start = f"{date_str}T00:00:00Z"
    out: dict[str, list[dict]] = {}
    chunk = 50  # batch — Alpaca rejects very large symbol lists
    for i in range(0, len(symbols), chunk):
        batch = symbols[i:i + chunk]
        params: dict[str, Any] = {
            "symbols": ",".join(req_for[s] for s in batch),
            "timeframe": "5Min",
            "start": start,
            "limit": 10000,
            "feed": "iex",
            "adjustment": "raw",
        }
        page_token = None
        while True:
            if page_token:
                params["page_token"] = page_token
            try:
                r = requests.get(
                    f"{alerts.ALPACA_DATA_URL}/stocks/bars",
                    headers=headers, params=params, timeout=20,
                )
            except Exception as exc:
                log.warning("alpaca 5min request error: %s", exc)
                break
            if r.status_code >= 400:
                body = (r.text or "").strip().replace("\n", " ")[:160]
                log.warning("alpaca 5min HTTP %d: %s", r.status_code, body)
                break
            data = r.json()
            for sym, bars in (data.get("bars") or {}).items():
                out.setdefault(orig_for.get(sym, sym), []).extend(bars)
            page_token = data.get("next_page_token")
            if not page_token:
                break
    return out


# --- session helpers + per-pick baseline ----------------------------------

# Pivot breakout requires per-ticker baseline from yesterday's snapshot:
#   prior_20d_high: max(high) over the last 20 trading days strictly before
#                   today — same definition the nightly composite uses for
#                   the DP sub-score, so the trigger fires at the exact
#                   pivot the pick was selected against.
#   avg_5min_vol:   approximation = daily avg volume / 78 (5-min bars in
#                   a 6.5hr regular session). Crude but consistent — a
#                   1.5x multiplier still cleanly separates accumulation
#                   from background noise.
_REGULAR_SESSION_PER_DAY_BARS = 78
_PIVOT_LOOKBACK_DAYS          = 20
_PIVOT_BREAKOUT_RVOL_MIN      = 1.5
_ORB_RANGE_BARS               = 3     # first 15 min of the regular session
_ORB_BREAKOUT_RVOL_MIN        = 1.2


def _bar_dt_et(bar: dict):
    """Return the bar's start timestamp in ET, or None if unparseable."""
    ts = bar.get("t")
    if not isinstance(ts, str) or not ts:
        return None
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        return None


def _in_regular_session(bar: dict) -> bool:
    """Filter out premarket / after-hours 5-min bars. Both triggers
    need RTH-only prints — premarket prints are thin and the ORB by
    definition starts at 9:30 ET."""
    et = _bar_dt_et(bar)
    if et is None:
        return False
    hm = et.hour * 100 + et.minute
    # 09:30 inclusive through 15:55 inclusive (the 15:55 bar covers
    # 15:55-16:00, which is the last regular-session bar Alpaca emits).
    return 930 <= hm <= 1555


def _load_pick_baselines(tickers: list[str], today_str: str) -> dict[str, dict]:
    """For each ticker, pull yesterday's snapshot row and derive the
    prior 20-day high + avg daily volume the pivot trigger needs.
    Returns {ticker: {prior_20d_high, avg_daily_vol}} — tickers not in
    the snapshot are silently absent (their pivot trigger won't fire,
    but ORB still can since ORB is self-contained per-day)."""
    import snapshots
    import scanner_momentum   # share the _bars_from_row helper
    if not tickers or not snapshots.enabled():
        return {}
    dates = snapshots.available_dates(1)
    if not dates:
        return {}
    snap_as_of = dates[0]
    out: dict[str, dict] = {}
    for ticker, row in snapshots.iter_for_date(snap_as_of, tickers=tickers):
        bars = scanner_momentum._bars_from_row(row)
        if not bars:
            continue
        prior = [
            b for b in bars
            if isinstance(b, dict) and (b.get("d") or "9999-12-31") < today_str
        ]
        if len(prior) < _PIVOT_LOOKBACK_DAYS:
            continue
        try:
            high_n = max(float(b.get("h") or 0) for b in prior[-_PIVOT_LOOKBACK_DAYS:])
        except (TypeError, ValueError):
            continue
        avg_vol = row.get("avg_volume")
        try:
            avg_vol_f = float(avg_vol) if avg_vol is not None else 0.0
        except (TypeError, ValueError):
            avg_vol_f = 0.0
        if high_n <= 0 or avg_vol_f <= 0:
            continue
        out[ticker] = {
            "prior_20d_high": high_n,
            "avg_daily_vol":  avg_vol_f,
        }
    log.info("loaded baseline for %d/%d picks (snap %s)",
             len(out), len(tickers), snap_as_of)
    return out


# --- evaluators -----------------------------------------------------------

def _evaluate_pivot_breakout(bars: list[dict], prior_20d_high: float,
                             avg_daily_vol: float,
                             min_rvol: float = _PIVOT_BREAKOUT_RVOL_MIN
                             ) -> dict | None:
    """Fire on the first regular-session 5-min bar that closes above
    `prior_20d_high` with volume >= min_rvol * (avg_daily_vol / 78).

    The 1.5x default keeps a meaningful gap between accumulation and
    background — a bar that prints above the pivot on ordinary volume
    is just noise; one that prints with 1.5x normal volume is real
    interest. No state machine needed — we want the first valid bar."""
    if not bars or prior_20d_high <= 0 or avg_daily_vol <= 0:
        return None
    avg_5min = avg_daily_vol / _REGULAR_SESSION_PER_DAY_BARS
    vol_floor = avg_5min * min_rvol
    for b in bars:
        if not _in_regular_session(b):
            continue
        try:
            close = float(b.get("c") or 0)
            vol   = float(b.get("v") or 0)
        except (TypeError, ValueError):
            continue
        if close <= 0 or vol <= 0:
            continue
        if close > prior_20d_high and vol >= vol_floor:
            rvol = vol / avg_5min
            return {
                "fired_at_ts":    b.get("t"),
                "price":          close,
                "ref_level":      prior_20d_high,
                "rvol":           rvol,
                "details": (
                    f"Closed ${close:.2f} above prior 20-day high "
                    f"${prior_20d_high:.2f} on {rvol:.1f}x avg 5-min vol."
                ),
            }
    return None


def _evaluate_orb(bars: list[dict],
                  range_bars: int = _ORB_RANGE_BARS,
                  min_rvol: float = _ORB_BREAKOUT_RVOL_MIN) -> dict | None:
    """Opening Range Breakout: the first `range_bars` regular-session
    5-min bars set the morning high. Fire on the first later bar that
    closes above that high with volume >= min_rvol * the avg volume
    during the range itself.

    Bar-relative volume baseline (no daily lookup needed) so this
    trigger keeps working even on names that weren't in last night's
    snapshot. The 1.2x multiplier is intentionally softer than the
    pivot breakout — the ORB is more about timing than conviction."""
    rth_bars = [b for b in bars if _in_regular_session(b)]
    if len(rth_bars) <= range_bars:
        return None
    range_window = rth_bars[:range_bars]
    try:
        range_high = max(float(b.get("h") or 0) for b in range_window)
        avg_range_vol = sum(float(b.get("v") or 0) for b in range_window) / range_bars
    except (TypeError, ValueError):
        return None
    if range_high <= 0 or avg_range_vol <= 0:
        return None
    vol_floor = avg_range_vol * min_rvol
    for b in rth_bars[range_bars:]:
        try:
            close = float(b.get("c") or 0)
            vol   = float(b.get("v") or 0)
        except (TypeError, ValueError):
            continue
        if close <= 0 or vol <= 0:
            continue
        if close > range_high and vol >= vol_floor:
            rvol = vol / avg_range_vol
            return {
                "fired_at_ts":    b.get("t"),
                "price":          close,
                "ref_level":      range_high,
                "rvol":           rvol,
                "details": (
                    f"Closed ${close:.2f} above 15-min opening high "
                    f"${range_high:.2f} on {rvol:.1f}x opening-range vol."
                ),
            }
    return None


# --- Telegram -------------------------------------------------------------

def _format_telegram(ticker: str, trigger_type: str, evt: dict) -> str:
    """One-line Telegram payload, dispatched on trigger type. HTML mode
    (matches scanner_momentum); the picks-intraday channel uses the
    same parse-mode wrapper in alerts.send_telegram."""
    if trigger_type == "pivot_breakout":
        return (
            f"🎯 <b>{ticker}</b> · 20-day pivot breakout · "
            f"<b>${evt['price']:.2f}</b>\n"
            f"<i>Closed above prior 20-day high ${evt['ref_level']:.2f} "
            f"on {evt['rvol']:.1f}× avg 5-min volume.</i>"
        )
    if trigger_type == "orb":
        return (
            f"🚀 <b>{ticker}</b> · Opening Range Breakout · "
            f"<b>${evt['price']:.2f}</b>\n"
            f"<i>Closed above 15-min opening high ${evt['ref_level']:.2f} "
            f"on {evt['rvol']:.1f}× opening-range volume.</i>"
        )
    return f"⚡ <b>{ticker}</b> · {trigger_type} · ${evt.get('price', 0):.2f}"


def run() -> int:
    """Single pass: load today's picks, evaluate each one, fire any
    new triggers. Designed to be called every 5 min by the cron."""
    import picker
    import alerts
    import snapshots

    if not snapshots.enabled():
        log.error("DATABASE_URL not set — cannot run intraday monitor")
        return 1

    picker.init_tables()

    # UI kill-switch — when the user has toggled alerts OFF in the
    # watchlist panel, exit before any Alpaca calls / DB writes /
    # Telegram. The workflow still runs on its 5-min schedule but
    # does no work and fires nothing.
    if not picker.get_config().get("intraday_alerts_enabled", True):
        log.info("intraday alerts disabled in UI — skipping")
        return 0

    now_et = _et_now()
    force = os.environ.get(_FORCE_RUN_ENV, "").lower() in ("1", "true", "yes")
    if not _market_is_open(now_et) and not force:
        log.info("market closed (%s ET) — skipping",
                 now_et.strftime("%a %H:%M"))
        return 0

    today = _today_et_date(now_et)
    # Pull the picks for today; if nothing's been written yet today
    # (cron beat the nightly job), fall back to the most recent date.
    picks = picker.load_picks(today) or picker.load_picks(None)
    if not picks:
        log.warning("no nightly picks found — nothing to monitor")
        return 0

    us_picks = [p for p in picks if _is_us_ticker(p.get("ticker") or "")]
    if not us_picks:
        log.info("nightly picks contain no US tickers — nothing to monitor")
        return 0
    log.info("monitoring %d US ticker(s) (out of %d picks)",
             len(us_picks), len(picks))

    # Skip per-ticker triggers that have already fired today. Each pick
    # can fire each trigger at most once per day; if both have fired,
    # we don't need the Alpaca call at all.
    trigger_types = ("pivot_breakout", "orb")
    pending: list[tuple[str, list[str]]] = []
    for p in us_picks:
        t = p["ticker"]
        missing = [tt for tt in trigger_types
                   if not picker.already_fired(today, t, tt)]
        if missing:
            pending.append((t, missing))
    if not pending:
        log.info("all watched tickers have already fired every trigger today")
        return 0

    # Baseline + bars batched once per pass — keeps the Alpaca traffic
    # bounded even when both triggers need evaluation.
    tickers_to_fetch = [t for t, _ in pending]
    baselines = _load_pick_baselines(tickers_to_fetch, today)
    bars_by_ticker = _fetch_5min_bars_today(tickers_to_fetch, today)
    log.info("fetched 5-min bars for %d/%d tickers",
             sum(1 for t in tickers_to_fetch if bars_by_ticker.get(t)),
             len(tickers_to_fetch))

    fired = 0
    for t, missing in pending:
        bars = bars_by_ticker.get(t)
        if not bars:
            continue
        for tt in missing:
            if tt == "pivot_breakout":
                base = baselines.get(t)
                if not base:
                    continue   # no snapshot row → can't compute pivot
                evt = _evaluate_pivot_breakout(
                    bars, base["prior_20d_high"], base["avg_daily_vol"],
                )
            elif tt == "orb":
                evt = _evaluate_orb(bars)
            else:
                continue
            if not evt:
                continue
            fresh = picker.record_intraday(
                today, t, tt,
                price=evt["price"], vwap=evt.get("ref_level"),
                details=evt["details"],
            )
            if not fresh:
                continue   # raced with a parallel run; the other sent it
            msg = _format_telegram(t, tt, evt)
            try:
                ok = alerts.send_telegram(msg)
                log.info("%s fired: %s @ $%.2f (telegram ok=%s)",
                         tt, t, evt["price"], ok)
            except Exception as exc:
                log.warning("telegram send failed for %s/%s: %s", t, tt, exc)
            fired += 1

    log.info("intraday pass complete — %d new alert(s) fired", fired)
    return 0


if __name__ == "__main__":
    sys.exit(run())
