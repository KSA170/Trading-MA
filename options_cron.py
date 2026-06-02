"""Nightly entry point for the options scanner.

Run by GitHub Actions cron at ~22:30 UTC weekdays (after the daily-
snapshot writer and the nightly picker). Scans the liquid universe,
saves every result to options_recommendations, and sends a Telegram
digest containing only BUYs and high-conviction WATCHes.

Idempotent — `save_recommendation` upserts on (as_of, ticker), so
re-running on the same calendar day overwrites the previous results.
"""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("options_cron")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("env %s=%r is not an int; using default %d", name, raw, default)
        return default


def main() -> int:
    import snapshots
    import options
    import options_scanner
    import alerts

    if not snapshots.enabled():
        log.error("DATABASE_URL not set — cannot run options scanner")
        return 1

    options.init_tables()

    top_n = _env_int("OPTIONS_TOP_N", options_scanner.DEFAULT_NIGHTLY_TOP_N)
    dte_min = _env_int("OPTIONS_DTE_MIN", 15)
    dte_max = _env_int("OPTIONS_DTE_MAX", 60)

    log.info("options scan: top_n=%d dte=%d-%d", top_n, dte_min, dte_max)

    def _progress(i: int, total: int, ticker: str) -> None:
        log.info("[%d/%d] %s", i, total, ticker)

    result = options_scanner.scan_universe(
        top_n=top_n, dte_min=dte_min, dte_max=dte_max,
        persist=True, progress_cb=_progress,
    )

    log.info(
        "scan complete: %d candidates → %d recommendations → %d in digest",
        result.get("candidates", 0),
        result.get("scanned", 0),
        len(result.get("digest", [])),
    )

    body = options_scanner.format_digest_for_telegram(result)
    try:
        ok = alerts.send_telegram(body)
        if ok:
            log.info("telegram digest sent")
        else:
            log.warning("telegram send returned False — check token / chat id")
    except Exception as exc:
        log.warning("telegram send failed: %s", exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
