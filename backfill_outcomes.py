"""One-shot backfill: seed stock_outcomes / option_outcomes from the
last 90 days of historical events (alert_sent, nightly_picks,
momentum_scanner_alerts, options_recommendations, options_pinned_recs).

Safe to re-run — every insert uses ON CONFLICT DO UPDATE that appends
sources rather than duplicating rows. After seeding, the nightly
outcomes filler will compute forward returns for any matured windows on
its next run; this script also calls `outcomes.run_nightly()` at the end
to fill them immediately.

Performance note (vs the original impl): each phase now reuses a single
Postgres connection across all rows, instead of opening a new connection
per row. On a remote DB the per-connection TLS+auth handshake is
~200-500ms, which dominates wall time for the 1000s of rows a typical
90-day backfill seeds. Single-connection brings it to ~5-30 seconds per
phase. Progress is logged every 100 rows so a long-running phase shows
heartbeats in the workflow log.

Phase ordering: pins → options recs → momentum → picker → alerts.
Pins are the smallest set and the highest-signal (explicit user action),
so they land first even if the job is killed mid-run.

Usage:
    python backfill_outcomes.py            # 90 days default
    python backfill_outcomes.py --days 30  # last 30 days only
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

import outcomes
import snapshots


log = logging.getLogger("backfill_outcomes")

# Heartbeat interval — log progress every N rows within a phase.
PROGRESS_EVERY = 100


class _CloseCache:
    """Per-phase ticker → {date: close} cache, sourced from
    daily_snapshot.recent_bars.

    Why this exists: daily_snapshot only retains the most recent ~5
    distinct as_of dates (RETENTION_DAYS), so a `SELECT close FROM
    daily_snapshot WHERE as_of <= entry_date` query returns NULL for
    any entry older than the retention horizon. That's why the first
    backfill run left rows from before ~June 15 with entry_close NULL.

    Each retained row, however, carries 60 trailing OHLCV bars in its
    recent_bars JSONB — ~12 weeks of history. So one query per ticker
    against the latest snapshot row pulls every close we need for that
    ticker, no matter how far back the entry sits within the 90-day
    backfill window.

    Lookup semantics: exact-match on the entry date first; falls back
    to the most recent prior bar (for the rare case the caller passes
    a non-trading day).
    """

    def __init__(self, cur):
        self.cur = cur
        self._cache: dict[str, dict[str, float]] = {}
        self.misses = 0   # tickers with no snapshot row at all
        self.hits   = 0

    def get(self, ticker: str, as_of: str) -> float | None:
        ticker = (ticker or "").strip().upper()
        if not ticker:
            return None
        bars_by_date = self._cache.get(ticker)
        if bars_by_date is None:
            bars_by_date = self._load(ticker)
            self._cache[ticker] = bars_by_date
            if not bars_by_date:
                self.misses += 1
        as_of = str(as_of)
        if as_of in bars_by_date:
            self.hits += 1
            return bars_by_date[as_of]
        # Fallback: most recent prior bar.
        prior = [d for d in bars_by_date if d <= as_of]
        if not prior:
            return None
        self.hits += 1
        return bars_by_date[max(prior)]

    def _load(self, ticker: str) -> dict[str, float]:
        self.cur.execute(
            "SELECT recent_bars FROM daily_snapshot "
            "WHERE ticker = %s "
            "ORDER BY as_of DESC LIMIT 1",
            (ticker,),
        )
        r = self.cur.fetchone()
        if not r or not r[0]:
            return {}
        rb = r[0]
        if isinstance(rb, str):
            try:
                rb = json.loads(rb)
            except Exception:
                return {}
        if not isinstance(rb, dict):
            return {}
        bars = rb.get("bars") or []
        out: dict[str, float] = {}
        for b in bars:
            if not isinstance(b, dict):
                continue
            d = b.get("date") or b.get("as_of")
            c = b.get("close")
            if d is None or c is None:
                continue
            try:
                out[str(d)] = float(c)
            except (TypeError, ValueError):
                pass
        return out


def _log_progress(phase: str, i: int, total: int, t0: float) -> None:
    if i and (i % PROGRESS_EVERY == 0 or i == total):
        elapsed = time.time() - t0
        rate = i / elapsed if elapsed > 0 else 0
        eta = (total - i) / rate if rate > 0 else 0
        log.info("  %s: %d/%d (%.0f rows/s, ETA %.0fs)",
                 phase, i, total, rate, eta)


def backfill_alerts(days: int) -> int:
    n = 0
    t0 = time.time()
    with snapshots._conn() as c, c.cursor() as cur:
        closes = _CloseCache(cur)
        cur.execute(
            "SELECT a.rule_id, a.ticker, a.trigger_date, r.name, r.rule_type "
            "FROM alert_sent a LEFT JOIN alert_rules r ON r.id = a.rule_id "
            "WHERE a.trigger_date >= CURRENT_DATE - INTERVAL '%s days'" % int(days)
        )
        rows = cur.fetchall()
        log.info("backfill_alerts: scanning %d rows", len(rows))
        for i, (rule_id, ticker, trigger_date, rule_name, rule_type) in enumerate(rows, 1):
            ec = closes.get(ticker, str(trigger_date))
            kind = "alert_setup" if rule_type == "setup" else "alert_screener"
            ok = outcomes.record_stock_outcome(
                ticker, trigger_date, ec,
                {"kind": kind, "id": rule_id, "label": rule_name or "Alert"},
                cur=cur,
            )
            if ok: n += 1
            _log_progress("backfill_alerts", i, len(rows), t0)
        log.info("  close cache: %d hits, %d tickers with no snapshot",
                 closes.hits, closes.misses)
    log.info("backfill_alerts: %d/%d in %.1fs", n, len(rows), time.time() - t0)
    return n


def backfill_picker(days: int) -> int:
    n = 0
    t0 = time.time()
    with snapshots._conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT pick_date, rank, ticker, close FROM nightly_picks "
            "WHERE pick_date >= CURRENT_DATE - INTERVAL '%s days'" % int(days)
        )
        rows = cur.fetchall()
        log.info("backfill_picker: scanning %d rows", len(rows))
        for i, (pick_date, rank, ticker, close) in enumerate(rows, 1):
            ok = outcomes.record_stock_outcome(
                ticker, pick_date, float(close) if close else None,
                {"kind": "picker", "id": int(rank),
                 "label": f"Picker rank {rank}"},
                cur=cur,
            )
            if ok: n += 1
            _log_progress("backfill_picker", i, len(rows), t0)
    log.info("backfill_picker: %d/%d in %.1fs", n, len(rows), time.time() - t0)
    return n


def backfill_momentum(days: int) -> int:
    n = 0
    t0 = time.time()
    with snapshots._conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT alert_date, ticker, price FROM momentum_scanner_alerts "
            "WHERE alert_date >= CURRENT_DATE - INTERVAL '%s days'" % int(days)
        )
        rows = cur.fetchall()
        log.info("backfill_momentum: scanning %d rows", len(rows))
        for i, (alert_date, ticker, price) in enumerate(rows, 1):
            ok = outcomes.record_stock_outcome(
                ticker, alert_date, float(price) if price else None,
                {"kind": "momentum_scan", "id": None,
                 "label": "Momentum scanner"},
                cur=cur,
            )
            if ok: n += 1
            _log_progress("backfill_momentum", i, len(rows), t0)
    log.info("backfill_momentum: %d/%d in %.1fs", n, len(rows), time.time() - t0)
    return n


def backfill_options_pins(days: int) -> int:
    """Seed option_outcomes from every existing options_pinned_recs row
    in the window. Pins are an explicit user signal — we record them
    even when the original recommendation's verdict was PASS, and we
    tag the source as 'user_pin' with the pin id so the report can
    distinguish manual pins from nightly_scan picks."""
    n = 0
    t0 = time.time()
    with snapshots._conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT id, ticker, as_of, snapshot FROM options_pinned_recs "
            "WHERE as_of >= CURRENT_DATE - INTERVAL '%s days'" % int(days)
        )
        rows = cur.fetchall()
        log.info("backfill_options_pins: scanning %d rows", len(rows))
        for i, (pin_id, ticker, as_of, snapshot) in enumerate(rows, 1):
            rec = snapshot
            if isinstance(rec, str):
                try:
                    rec = json.loads(rec)
                except Exception:
                    continue
            if not isinstance(rec, dict):
                continue
            # Pins were the user's explicit "track this" signal — record
            # even for verdict=PASS by forcing PINNED so the recorder's
            # verdict gate doesn't drop them.
            if (rec.get("verdict") or "").upper() in ("PASS", ""):
                rec = dict(rec)
                rec["verdict"] = "PINNED"
            ok = outcomes.record_option_outcome(
                ticker, as_of, rec,
                {"kind": "user_pin", "id": int(pin_id), "label": "User pin"},
                cur=cur,
            )
            if ok: n += 1
            _log_progress("backfill_options_pins", i, len(rows), t0)
    log.info("backfill_options_pins: %d/%d in %.1fs", n, len(rows), time.time() - t0)
    return n


def backfill_options(days: int) -> int:
    n = 0
    t0 = time.time()
    with snapshots._conn() as c, c.cursor() as cur:
        closes = _CloseCache(cur)
        cur.execute(
            "SELECT as_of, ticker, direction, verdict, composite_score, "
            "       contract_symbol, strike, expiration, dte, mid_price "
            "FROM options_recommendations "
            "WHERE as_of >= CURRENT_DATE - INTERVAL '%s days' "
            "  AND verdict IS NOT NULL AND verdict <> 'PASS' "
            "  AND contract_symbol IS NOT NULL" % int(days)
        )
        rows = cur.fetchall()
        log.info("backfill_options: scanning %d rows", len(rows))
        for i, (as_of, ticker, direction, verdict, composite,
                csym, strike, expiration, dte, mid) in enumerate(rows, 1):
            ec = closes.get(ticker, str(as_of))
            rec = {
                "ticker":          ticker,
                "direction":       direction,
                "verdict":         verdict,
                "composite_score": composite,
                "close":           ec,
                "contract": {
                    "contract_symbol": csym,
                    "strike":          strike,
                    "expiration":      expiration,
                    "dte":             dte,
                    "mid":             mid,
                },
            }
            ok = outcomes.record_option_outcome(
                ticker, as_of, rec,
                {"kind": "nightly_scan", "id": None,
                 "label": "Options recommender (historical)"},
                cur=cur,
            )
            if ok: n += 1
            _log_progress("backfill_options", i, len(rows), t0)
        log.info("  close cache: %d hits, %d tickers with no snapshot",
                 closes.hits, closes.misses)
    log.info("backfill_options: %d/%d in %.1fs", n, len(rows), time.time() - t0)
    return n


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90,
                    help="how many days back to seed (default 90)")
    args = ap.parse_args()

    if not snapshots.enabled():
        log.error("DATABASE_URL not set — backfill cannot run")
        return 1
    snapshots.init()
    outcomes.init_tables()

    # Phase order: smallest/highest-signal first so a killed job still
    # delivers the most valuable data.
    total = 0
    total += backfill_options_pins(args.days)
    total += backfill_options(args.days)
    total += backfill_momentum(args.days)
    total += backfill_picker(args.days)
    total += backfill_alerts(args.days)
    log.info("backfill total seeded: %d", total)

    # Fill forward returns + regime tags on the seeded rows.
    log.info("running nightly fill (forward returns + regime tags)...")
    t0 = time.time()
    r = outcomes.run_nightly()
    log.info("nightly fill done in %.1fs: %s", time.time() - t0, json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
