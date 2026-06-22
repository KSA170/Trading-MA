"""One-shot backfill: seed stock_outcomes / option_outcomes from the
last 90 days of historical events (alert_sent, nightly_picks,
momentum_scanner_alerts, options_recommendations).

Safe to re-run — every insert uses ON CONFLICT DO UPDATE that appends
sources rather than duplicating rows. After seeding, the nightly
outcomes filler will compute forward returns for any matured windows on
its next run; call `outcomes.run_nightly()` explicitly to force it.

Usage:
    python backfill_outcomes.py            # 90 days default
    python backfill_outcomes.py --days 30  # last 30 days only
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import outcomes
import snapshots


log = logging.getLogger("backfill_outcomes")


def _stock_close_on(cur, ticker: str, as_of: str) -> float | None:
    cur.execute(
        "SELECT close FROM daily_snapshot "
        "WHERE ticker = %s AND as_of <= %s "
        "ORDER BY as_of DESC LIMIT 1",
        (ticker, as_of),
    )
    r = cur.fetchone()
    return float(r[0]) if r and r[0] is not None else None


def backfill_alerts(days: int) -> int:
    n = 0
    with snapshots._conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT a.rule_id, a.ticker, a.trigger_date, r.name, r.rule_type "
            "FROM alert_sent a LEFT JOIN alert_rules r ON r.id = a.rule_id "
            "WHERE a.trigger_date >= CURRENT_DATE - INTERVAL '%s days'" % int(days)
        )
        rows = cur.fetchall()
    for rule_id, ticker, trigger_date, rule_name, rule_type in rows:
        with snapshots._conn() as c, c.cursor() as cur:
            ec = _stock_close_on(cur, ticker, str(trigger_date))
        kind = "alert_setup" if rule_type == "setup" else "alert_screener"
        ok = outcomes.record_stock_outcome(
            ticker, trigger_date, ec,
            {"kind": kind, "id": rule_id, "label": rule_name or "Alert"},
        )
        if ok: n += 1
    log.info("backfill_alerts: %d/%d", n, len(rows))
    return n


def backfill_picker(days: int) -> int:
    n = 0
    with snapshots._conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT pick_date, rank, ticker, close FROM nightly_picks "
            "WHERE pick_date >= CURRENT_DATE - INTERVAL '%s days'" % int(days)
        )
        rows = cur.fetchall()
    for pick_date, rank, ticker, close in rows:
        ok = outcomes.record_stock_outcome(
            ticker, pick_date, float(close) if close else None,
            {"kind": "picker", "id": int(rank),
             "label": f"Picker rank {rank}"},
        )
        if ok: n += 1
    log.info("backfill_picker: %d/%d", n, len(rows))
    return n


def backfill_momentum(days: int) -> int:
    n = 0
    with snapshots._conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT alert_date, ticker, price FROM momentum_scanner_alerts "
            "WHERE alert_date >= CURRENT_DATE - INTERVAL '%s days'" % int(days)
        )
        rows = cur.fetchall()
    for alert_date, ticker, price in rows:
        ok = outcomes.record_stock_outcome(
            ticker, alert_date, float(price) if price else None,
            {"kind": "momentum_scan", "id": None,
             "label": "Momentum scanner"},
        )
        if ok: n += 1
    log.info("backfill_momentum: %d/%d", n, len(rows))
    return n


def backfill_options_pins(days: int) -> int:
    """Seed option_outcomes from every existing options_pinned_recs row
    in the window. Pins are an explicit user signal — we record them
    even when the original recommendation's verdict was PASS, and we
    tag the source as 'user_pin' with the pin id so the report can
    distinguish manual pins from nightly_scan picks."""
    n = 0
    with snapshots._conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT id, ticker, as_of, snapshot FROM options_pinned_recs "
            "WHERE as_of >= CURRENT_DATE - INTERVAL '%s days'" % int(days)
        )
        rows = cur.fetchall()
    for pin_id, ticker, as_of, snapshot in rows:
        # snapshot is the full rec dict (JSONB). psycopg2 returns it as
        # a dict; tolerate str defensively.
        rec = snapshot
        if isinstance(rec, str):
            try:
                import json as _json
                rec = _json.loads(rec)
            except Exception:
                continue
        if not isinstance(rec, dict):
            continue
        # Pins were the user's explicit "track this" signal — we want
        # them recorded even for verdict=PASS. Force a non-PASS verdict
        # if the snapshot's verdict would otherwise short-circuit the
        # recorder.
        if (rec.get("verdict") or "").upper() in ("PASS", ""):
            rec = dict(rec)
            rec["verdict"] = "PINNED"
        ok = outcomes.record_option_outcome(
            ticker, as_of, rec,
            {"kind": "user_pin", "id": int(pin_id), "label": "User pin"},
        )
        if ok: n += 1
    log.info("backfill_options_pins: %d/%d", n, len(rows))
    return n


def backfill_options(days: int) -> int:
    n = 0
    with snapshots._conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT as_of, ticker, direction, verdict, composite_score, "
            "       contract_symbol, strike, expiration, dte, mid_price "
            "FROM options_recommendations "
            "WHERE as_of >= CURRENT_DATE - INTERVAL '%s days' "
            "  AND verdict IS NOT NULL AND verdict <> 'PASS' "
            "  AND contract_symbol IS NOT NULL" % int(days)
        )
        rows = cur.fetchall()
    for (as_of, ticker, direction, verdict, composite,
         csym, strike, expiration, dte, mid) in rows:
        # Reconstruct a minimal recommendation dict for the writer.
        with snapshots._conn() as c, c.cursor() as cur:
            ec = _stock_close_on(cur, ticker, str(as_of))
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
        )
        if ok: n += 1
    log.info("backfill_options: %d/%d", n, len(rows))
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

    total = 0
    total += backfill_alerts(args.days)
    total += backfill_picker(args.days)
    total += backfill_momentum(args.days)
    total += backfill_options(args.days)
    total += backfill_options_pins(args.days)
    log.info("backfill total seeded: %d", total)

    # Fill forward returns + regime tags on the seeded rows.
    r = outcomes.run_nightly()
    log.info("nightly fill after backfill: %s", json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
