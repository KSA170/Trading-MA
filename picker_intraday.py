"""
Stage 2: intraday monitor for the nightly watchlist (top 25).

Runs every ~5 min during US market hours via GitHub Actions. Watches
today's top 25 picks via Alpaca 5-min bars and fires a Telegram alert
the first time each ticker prints a confirmed VWAP reclaim.

VWAP reclaim logic (state machine, single pass over today's 5-min bars):

  state = "above"  if the first bar closed above session VWAP
  state = "below"  if it closed below

  above -> below            when a bar closes below VWAP (the dip)
  below -> reclaim_pending  when a bar closes above VWAP
  reclaim_pending -> held   when the NEXT bar also closes above VWAP
                            (FIRE the alert here — 2 consecutive above
                            after a confirmed dip)
  reclaim_pending -> below  if the next bar closes back below

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


def _evaluate_vwap_reclaim(bars: list[dict]) -> dict | None:
    """Walk this morning's 5-min bars and return a dict describing the
    first confirmed VWAP reclaim, or None if no reclaim has formed yet.

    Confirmed reclaim = the stock dipped below session VWAP at some
    point, then closed above VWAP for 2 consecutive 5-min bars. The
    fire point is the SECOND of those two bars."""
    if not bars or len(bars) < 3:
        return None

    cum_pv = 0.0   # sum of typical-price * volume
    cum_v = 0.0    # sum of volume
    state: str | None = None   # 'above' | 'below' | 'reclaim_pending'

    for i, b in enumerate(bars):
        try:
            high = float(b.get("h"))
            low = float(b.get("l"))
            close = float(b.get("c"))
            vol = float(b.get("v") or 0.0)
        except (TypeError, ValueError):
            continue
        if vol <= 0:
            # Skip zero-volume bars (rare; Alpaca occasionally emits
            # them in the first minute after open). They don't move
            # VWAP and shouldn't change state.
            continue
        typical = (high + low + close) / 3.0
        cum_pv += typical * vol
        cum_v += vol
        if cum_v <= 0:
            continue
        vwap = cum_pv / cum_v

        if state is None:
            state = "above" if close > vwap else "below"
            continue

        if state == "above":
            if close < vwap:
                state = "below"
        elif state == "below":
            if close > vwap:
                state = "reclaim_pending"
        elif state == "reclaim_pending":
            if close > vwap:
                # Confirmed — 2 consecutive bars above VWAP after a dip.
                return {
                    "fired_at_idx": i,
                    "fired_at_ts":  b.get("t"),
                    "price":        close,
                    "vwap":         vwap,
                    "details": (
                        f"VWAP reclaim confirmed at ${close:.2f} "
                        f"(VWAP ${vwap:.2f}). Closed above for 2 "
                        f"consecutive 5-min bars after a session dip."
                    ),
                }
            else:
                state = "below"
    return None


def _format_telegram(ticker: str, trigger_type: str, evt: dict) -> str:
    """One-line Telegram payload for a single trigger. Markdown-safe."""
    return (
        f"⚡ *{ticker}* · VWAP reclaim · ${evt['price']:.2f}\n"
        f"_VWAP ${evt['vwap']:.2f}. Two consecutive 5-min bars above "
        f"after a session dip._"
    )


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

    # Skip tickers that have already fired today — cheap pre-check that
    # avoids the Alpaca call for tickers we can't act on anyway.
    needs_eval = [
        p for p in us_picks
        if not picker.already_fired(today, p["ticker"], "vwap_reclaim")
    ]
    if not needs_eval:
        log.info("all watched tickers already triggered VWAP reclaim today")
        return 0

    bars_by_ticker = _fetch_5min_bars_today(
        [p["ticker"] for p in needs_eval], today,
    )

    fired = 0
    for p in needs_eval:
        t = p["ticker"]
        bars = bars_by_ticker.get(t)
        if not bars:
            continue
        evt = _evaluate_vwap_reclaim(bars)
        if not evt:
            continue
        fresh = picker.record_intraday(
            today, t, "vwap_reclaim",
            price=evt["price"], vwap=evt["vwap"], details=evt["details"],
        )
        if not fresh:
            continue   # raced with a parallel run; the other run sent it
        msg = _format_telegram(t, "vwap_reclaim", evt)
        try:
            ok = alerts.send_telegram(msg)
            log.info("VWAP reclaim fired: %s @ $%.2f (telegram ok=%s)",
                     t, evt["price"], ok)
        except Exception as exc:
            log.warning("telegram send failed for %s: %s", t, exc)
        fired += 1

    log.info("intraday pass complete — %d new alert(s) fired", fired)
    return 0


if __name__ == "__main__":
    sys.exit(run())
