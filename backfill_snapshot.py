"""One-shot daily-snapshot backfill for a missed close date.

The nightly snapshot writer lives in the Render web app's auto-warm
scheduler (16:30 / 19:00 ET) — when the service is suspended, that
date is simply absent from daily_snapshot (2026-07-30 was missed this
way). This script rebuilds a specific date from GitHub Actions: fetch +
enrich each universe ticker through the screener's own cache path,
truncate the frame to bars at or before the target date, and build the
row with the same _row_from_df the app uses. Indicator math stays
identical because enrichment is causal (rolling/ewm at a row only uses
rows at or before it), so truncating an enriched frame preserves the
target date's values exactly.

Rows are written only for tickers that actually have a bar ON the
target date — a truncated frame ending earlier (halted, delisted, IPO
after the date) is skipped, never mislabeled.

Env:
  SNAPSHOT_TARGET_DATE  required, YYYY-MM-DD.
  SNAPSHOT_TICKERS      optional comma/space list (default: universe).
  SNAPSHOT_WORKERS      optional, default 4 — deliberately modest;
                        Yahoo rate-limits GitHub runner IPs.
"""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor

import screener
import snapshots

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill_snapshot")

_BATCH = 500


def main() -> int:
    target = (os.environ.get("SNAPSHOT_TARGET_DATE") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", target):
        log.error("SNAPSHOT_TARGET_DATE (YYYY-MM-DD) is required")
        return 1
    if not snapshots.enabled():
        log.error("DATABASE_URL not set")
        return 1
    snapshots.init()
    if snapshots.has_date(target):
        log.info("note: %s already has rows — upserting over them "
                 "(idempotent)", target)

    tick_env = (os.environ.get("SNAPSHOT_TICKERS") or "").strip()
    tickers = ([t.strip().upper() for t in re.split(r"[,\s]+", tick_env) if t.strip()]
               if tick_env else screener.all_tickers())
    workers = max(1, int(os.environ.get("SNAPSHOT_WORKERS") or 4))
    log.info("backfilling %s for %d tickers (%d workers)",
             target, len(tickers), workers)

    counts = {"written": 0, "no_data": 0, "no_target_bar": 0,
              "row_none": 0, "errors": 0}

    def _one(t: str):
        try:
            df = screener._cached_history(t, period="6mo", need_shares=True)
        except Exception as exc:
            log.warning("fetch failed for %s: %s", t, exc)
            return ("errors", None)
        if df is None or df.empty:
            return ("no_data", None)
        try:
            df = df[df.index.strftime("%Y-%m-%d") <= target]
        except Exception as exc:
            log.warning("truncate failed for %s: %s", t, exc)
            return ("errors", None)
        if df is None or len(df) < 2:
            return ("no_target_bar", None)
        if df.index[-1].strftime("%Y-%m-%d") != target:
            return ("no_target_bar", None)
        try:
            row = screener._row_from_df(t, df)
        except Exception as exc:
            log.warning("row build failed for %s: %s", t, exc)
            return ("errors", None)
        if row is None:
            return ("row_none", None)
        return ("ok", row)

    batch: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (status, row) in enumerate(pool.map(_one, tickers), start=1):
            if status == "ok":
                batch.append(row)
                if len(batch) >= _BATCH:
                    counts["written"] += snapshots.upsert_many(batch)
                    batch.clear()
            else:
                counts[status] += 1
            if i % 500 == 0:
                log.info("progress %d/%d — %s", i, len(tickers), counts)
    if batch:
        counts["written"] += snapshots.upsert_many(batch)
        batch.clear()

    trimmed = (snapshots.trim_to_last(snapshots.RETENTION_DAYS)
               if counts["written"] else 0)
    log.info("done: %s · trimmed=%d", counts, trimmed)
    log.info("date_counts now: %s", snapshots.date_counts(8))
    if snapshots.last_write_error():
        log.error("last write error: %s", snapshots.last_write_error())
    return 0 if counts["written"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
