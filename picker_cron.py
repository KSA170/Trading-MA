"""Nightly entry point for the picker.

Run by GitHub Actions cron at market close + 1hr (~22:00 UTC on
weekdays). Reads the latest daily snapshot, ranks the universe by
the 5-signal composite using the user's saved config, writes the top
10 to the ``nightly_picks`` table, and pushes a Telegram message.

Idempotent — re-running on the same calendar date overwrites the
previous picks for that date.
"""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("picker_cron")


def main() -> int:
    import picker
    import alerts
    import snapshots

    if not snapshots.enabled():
        log.error("DATABASE_URL not set — cannot run picker")
        return 1

    # Make sure the picker tables exist (idempotent).
    picker.init_tables()

    cfg = picker.get_config()
    log.info(
        "picker config: weights=%s price=%g-%g",
        cfg["weights"], cfg["price_min"], cfg["price_max"],
    )

    picks, as_of = picker.rank_universe(
        weights=cfg["weights"],
        price_min=cfg["price_min"],
        price_max=cfg["price_max"],
        limit=picker.DEFAULT_LIMIT,
    )
    if not picks:
        log.warning("ranking returned 0 picks — nothing to write or alert")
        return 0

    n = picker.save_picks(picks, as_of)
    log.info("wrote %d picks for %s", n, as_of)

    # Telegram digest. Format: rank · ticker · composite · sub-score
    # breakdown so the recipient sees at-a-glance which signals are
    # driving each pick. Kept terse (≤ 4000 chars) to fit in one
    # Telegram message.
    header = (
        f"📊 *Nightly watchlist for {as_of}*\n"
        f"_Top {len(picks)} by composite — VC/RS/VA/MT/DP_\n"
    )
    body_lines = []
    for p in picks:
        body_lines.append(
            f"{p['rank']:>2}. *{p['ticker']}* · {p['composite']:.0f}  "
            f"(VC {p['vc_score']:.0f} · RS {p['rs_score']:.0f} · "
            f"VA {p['va_score']:.0f} · MT {p['mt_score']:.0f} · "
            f"DP {p['dp_score']:.0f})"
        )
    body = header + "\n".join(body_lines)
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
