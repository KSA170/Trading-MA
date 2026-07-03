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


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("env %s=%r is not a float; using %s", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


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
    # Optional absolute-quality gates. Source of truth is the saved picks
    # config (tuned from the "Tune…" panel); env vars still override for
    # ops. When on, weak days return fewer (or no) picks instead of always
    # emitting `limit` names.
    min_composite = _env_float("PICKER_MIN_COMPOSITE", cfg.get("min_composite", 0.0))
    require_confirmation = _env_bool("PICKER_REQUIRE_CONFIRMATION",
                                     cfg.get("require_confirmation", False))
    confirm_min = _env_float("PICKER_CONFIRM_MIN", cfg.get("confirm_min", 50.0))
    log.info(
        "picker config: weights=%s price=%g-%g limit=%d "
        "gates[min_composite=%.1f require_confirmation=%s confirm_min=%.0f]",
        cfg["weights"], cfg["price_min"], cfg["price_max"], cfg["pick_limit"],
        min_composite, require_confirmation, confirm_min,
    )

    picks, as_of = picker.rank_universe(
        weights=cfg["weights"],
        price_min=cfg["price_min"],
        price_max=cfg["price_max"],
        limit=cfg["pick_limit"],
        min_composite=min_composite,
        require_confirmation=require_confirmation,
        confirm_min=confirm_min,
    )

    # Persist the whole-universe feature log (ML groundwork) regardless of
    # how many picks survived the gates — best-effort, never blocks picks.
    if as_of:
        try:
            picker.log_features(as_of=as_of, weights=cfg["weights"],
                                price_min=cfg["price_min"], price_max=cfg["price_max"])
        except Exception as exc:
            log.warning("feature_log write failed: %s", exc)

    if not picks:
        log.warning("ranking returned 0 picks — nothing to write or alert")
        return 0

    n = picker.save_picks(picks, as_of)
    log.info("wrote %d picks for %s", n, as_of)

    # Telegram digest (HTML — send_telegram forces parse_mode=HTML, so
    # the old Markdown '*'/'_' rendered as literal characters). Format:
    # rank · ticker · composite · sub-score breakdown so the recipient
    # sees at-a-glance which signals drive each pick. Kept terse
    # (≤ 4000 chars) to fit one message.
    import tg_format as T
    header = (
        f"📊 <b>NIGHTLY WATCHLIST — {T.esc(as_of)}</b>\n"
        f"{T.i(f'Top {len(picks)} by composite · VC/RS/VA/MT/DP/CF')}\n"
    )
    body_lines = []
    for p in picks:
        body_lines.append(
            f"{p['rank']:>2}. <b>{T.esc(p['ticker'])}</b> · "
            f"<b>{p['composite']:.0f}</b>  "
            f"<i>VC {(p.get('vc_score') or 0):.0f} · RS {(p.get('rs_score') or 0):.0f} · "
            f"VA {(p.get('va_score') or 0):.0f} · MT {(p.get('mt_score') or 0):.0f} · "
            f"DP {(p.get('dp_score') or 0):.0f} · CF {(p.get('confirm_score') or 0):.0f}</i>"
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
