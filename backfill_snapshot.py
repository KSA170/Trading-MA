"""Daily-snapshot backfill for close dates the nightly writer missed.

The nightly writer lives in the Render web app's auto-warm scheduler
(16:30 / 19:00 ET) — a suspended service silently skips that close
(2026-07-30 was lost this way, and 07-31 came back short). This script
rebuilds specific dates from GitHub Actions.

Fetching is BATCHED via yf.download (200 symbols per request, ~42
requests for the whole universe) because Yahoo aggressively rate-limits
per-ticker calls from runner IPs — the first version of this script got
7,421 instant 429s out of 8,309 tickers. Each batch frame is split per
ticker, enriched with the screener's own indicator pipeline, truncated
to bars at or before each target date (safe: enrichment is causal, so
the target date's values match what the nightly run would have
written), and rowed via the same _row_from_df.

Notes:
  - Rows are only written for tickers with a bar ON the target date.
  - Tickers already present for every requested date are skipped, so
    reruns only chase the stragglers.
  - Shares outstanding is NOT fetched (it would need one Yahoo call
    per ticker — the exact thing that gets rate-limited). Backfilled
    rows carry shares=NULL, so turnover/market-cap columns are blank
    for that date; every indicator/price field is complete.

Env:
  SNAPSHOT_TARGET_DATE  required — one date, a comma list
                        ("2026-07-30,2026-07-31"), or "auto" for the
                        most recent completed US close (see
                        _resolve_auto_date) — the nightly-cron mode.
  SNAPSHOT_TICKERS      optional comma/space subset (default universe).
  SNAPSHOT_BATCH        optional symbols per Yahoo request (default 200).
  SNAPSHOT_ALLOW_EMPTY  "1" -> exit 0 even when nothing was written.
                        The nightly cron sets it: on a market holiday
                        no ticker has a bar for the date, and on a
                        quiet rerun skip-existing leaves nothing to do
                        — both are clean no-ops, not failures.
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import screener
import snapshots

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill_snapshot")

_UPSERT_BATCH = 500


def _resolve_auto_date(now_et: datetime | None = None) -> str:
    """The most recent COMPLETED US close, in ET.

    Before ~16:05 ET on a weekday, "today" is still an in-progress
    session — writing it would mislabel partial bars as the close — so
    auto resolves to the previous trading day instead. Weekends roll
    back to Friday. Market holidays are not special-cased: on a holiday
    the resolved date simply has no bars, every ticker skips as
    no_target_bar, and the run is a clean no-op (SNAPSHOT_ALLOW_EMPTY).
    """
    now_et = now_et or datetime.now(ZoneInfo("America/New_York"))
    d = now_et.date()
    if now_et.hour * 60 + now_et.minute < 16 * 60 + 5:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _existing_tickers(as_of: str) -> set[str]:
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("SELECT ticker FROM daily_snapshot WHERE as_of = %s",
                        (as_of,))
            return {r[0] for r in cur.fetchall()}
    except Exception as exc:
        log.warning("existing-ticker query failed for %s: %s", as_of, exc)
        return set()


def _fetch_batch(symbols: list[str]):
    """One batched Yahoo request for 6mo daily bars. Returns
    {symbol: flat OHLCV frame} for symbols that came back with data.
    Retries the whole batch once on failure."""
    import yfinance as yf
    for attempt in (1, 2):
        try:
            df = yf.download(
                tickers=" ".join(symbols), period="6mo", interval="1d",
                auto_adjust=False, progress=False, threads=False,
                group_by="ticker",
            )
            break
        except Exception as exc:
            log.warning("batch download failed (attempt %d, %d syms): %s",
                        attempt, len(symbols), exc)
            if attempt == 2:
                return {}
            time.sleep(30)
    if df is None or df.empty:
        return {}
    out = {}
    is_multi = isinstance(df.columns, pd.MultiIndex)
    for sym in symbols:
        try:
            sub = df[sym] if is_multi else df
        except (KeyError, ValueError):
            continue
        if sub is None or sub.empty:
            continue
        sub = sub.dropna(subset=["Close"])
        if len(sub) >= 2:
            out[sym] = sub
    return out


def main() -> int:
    raw_dates = (os.environ.get("SNAPSHOT_TARGET_DATE") or "").strip()
    if raw_dates.lower() == "auto":
        raw_dates = _resolve_auto_date()
        log.info("auto target date resolved to %s", raw_dates)
    dates = [d.strip() for d in raw_dates.split(",") if d.strip()]
    if not dates or any(not re.match(r"^\d{4}-\d{2}-\d{2}$", d) for d in dates):
        log.error("SNAPSHOT_TARGET_DATE (YYYY-MM-DD[,...] or 'auto') required")
        return 1
    if not snapshots.enabled():
        log.error("DATABASE_URL not set")
        return 1
    snapshots.init()

    tick_env = (os.environ.get("SNAPSHOT_TICKERS") or "").strip()
    universe = ([t.strip().upper() for t in re.split(r"[,\s]+", tick_env) if t.strip()]
                if tick_env else screener.all_tickers())
    batch_size = max(20, int(os.environ.get("SNAPSHOT_BATCH") or 200))

    have = {d: _existing_tickers(d) for d in dates}
    for d in dates:
        log.info("%s currently has %d rows", d, len(have[d]))
    todo = [t for t in universe if any(t not in have[d] for d in dates)]
    log.info("backfilling %s: %d of %d tickers still needed",
             dates, len(todo), len(universe))

    counts = {"written": 0, "no_data": 0, "no_target_bar": 0,
              "row_none": 0, "errors": 0}
    rows: list[dict] = []

    def _flush():
        if rows:
            counts["written"] += snapshots.upsert_many(rows)
            rows.clear()

    for i in range(0, len(todo), batch_size):
        chunk = todo[i:i + batch_size]
        frames = _fetch_batch(chunk)
        for sym in chunk:
            df = frames.get(sym)
            if df is None:
                counts["no_data"] += 1
                continue
            try:
                enriched = screener._enrich(df.copy())
            except Exception as exc:
                log.warning("enrich failed for %s: %s", sym, exc)
                counts["errors"] += 1
                continue
            wrote_any = False
            for d in dates:
                if sym in have[d]:
                    continue
                cut = enriched[enriched.index.strftime("%Y-%m-%d") <= d]
                if len(cut) < 2 or cut.index[-1].strftime("%Y-%m-%d") != d:
                    continue
                try:
                    row = screener._row_from_df(sym, cut)
                except Exception as exc:
                    log.warning("row build failed for %s@%s: %s", sym, d, exc)
                    counts["errors"] += 1
                    continue
                if row is None:
                    counts["row_none"] += 1
                    continue
                rows.append(row)
                wrote_any = True
                if len(rows) >= _UPSERT_BATCH:
                    _flush()
            if not wrote_any:
                counts["no_target_bar"] += 1
        log.info("progress %d/%d — %s", min(i + batch_size, len(todo)),
                 len(todo), counts)
        time.sleep(1.5)   # be polite between batch requests

    _flush()
    trimmed = (snapshots.trim_to_last(snapshots.RETENTION_DAYS)
               if counts["written"] else 0)
    log.info("done: %s · trimmed=%d", counts, trimmed)
    log.info("date_counts now: %s", snapshots.date_counts(8))
    if snapshots.last_write_error():
        log.error("last write error: %s", snapshots.last_write_error())
    allow_empty = str(os.environ.get("SNAPSHOT_ALLOW_EMPTY", "")).strip() \
        in ("1", "true", "yes", "on")
    return 0 if (counts["written"] or allow_empty) else 1


if __name__ == "__main__":
    raise SystemExit(main())
