"""Nightly cron entry: fill forward returns + regime tags on every
outcome row whose window has matured. Idempotent — safe to re-run.

Runs after the picker cron so daily_snapshot has today's bars for every
ticker the report could possibly reference.
"""

from __future__ import annotations

import logging
import sys

import outcomes
import snapshots


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("outcomes_cron")
    if not snapshots.enabled():
        log.error("DATABASE_URL not set — outcomes filler cannot run")
        return 1
    snapshots.init()
    result = outcomes.run_nightly()
    log.info("done: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
