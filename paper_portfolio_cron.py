"""Nightly mark-to-market for the paper portfolio.

Values every open lot at its latest price, auto-settles expired options at
intrinsic value, and appends today's equity snapshot (with SPY) to
paper_equity so the performance graph has a daily point. Idempotent per
date — re-running overwrites the same day's equity row.

Cron: a few minutes after the nightly outcomes filler so the day's closes
are available from yfinance.
"""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("paper_portfolio_cron")


def main() -> int:
    import snapshots
    import paper_portfolio

    if not snapshots.enabled():
        log.error("DATABASE_URL not set — cannot mark the paper portfolio")
        return 1

    paper_portfolio.init_tables()
    result = paper_portfolio.mark_to_market()
    log.info("done: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
