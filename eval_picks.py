"""Evaluate which picker signals actually predict forward returns.

Read-only. Joins nightly_picks (the sub-scores recorded at pick time) with
stock_outcomes (forward returns filled by the outcomes cron) on
(ticker, pick_date == entry_date), then reports, per signal, its rank
correlation with forward returns and a top-vs-bottom quintile spread.

Use it to see whether the hand-set composite weights match reality BEFORE
retuning them or enabling the confirmation gate — a signal with ~0
correlation is dead weight; a strongly positive one deserves more weight.

Note: nightly_picks only records the top-N picks each night, so this is a
survivorship-biased sample (no rejected names) — good for judging the
*relative* usefulness of the signals among selected picks, not for training
a universe-wide model. The new feature_log table (whole universe) is what a
real model should train on once it has accumulated a few months of history.

Usage:  python eval_picks.py [--horizon 1|3|5|10|20] [--min-rows N]
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

SIGNALS = ["composite", "vc_score", "rs_score", "va_score",
           "mt_score", "dp_score", "sr_score", "confirm_score"]


def _rank(a: np.ndarray) -> np.ndarray:
    order = a.argsort()
    ranks = np.empty(len(a), dtype=float)
    ranks[order] = np.arange(len(a), dtype=float)
    return ranks


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Rank (Spearman) correlation, NaN-tolerant. Implemented on numpy so
    the script has no scipy dependency."""
    mask = np.isfinite(x) & np.isfinite(y)
    if int(mask.sum()) < 10:
        return float("nan")
    xr = _rank(x[mask])
    yr = _rank(y[mask])
    xr = xr - xr.mean()
    yr = yr - yr.mean()
    denom = np.sqrt((xr ** 2).sum() * (yr ** 2).sum())
    return float((xr * yr).sum() / denom) if denom > 0 else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--horizon", type=int, default=10, choices=[1, 3, 5, 10, 20])
    ap.add_argument("--min-rows", type=int, default=30)
    args = ap.parse_args()

    import snapshots
    if not snapshots.enabled():
        print("DATABASE_URL not set — cannot evaluate.")
        return 1
    import picker
    picker.init_tables()

    retcol = f"ret_{args.horizon}d"
    cols = ", ".join("p." + s for s in SIGNALS)
    query = (
        f"SELECT {cols}, o.{retcol} "
        "FROM nightly_picks p "
        "JOIN stock_outcomes o "
        "  ON p.ticker = o.ticker AND p.pick_date = o.entry_date "
        f"WHERE o.{retcol} IS NOT NULL"
    )
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
    except Exception as exc:
        print(f"query failed: {exc}")
        return 1

    if len(rows) < args.min_rows:
        print(f"Only {len(rows)} labeled picks available for {retcol} "
              f"(need >= {args.min_rows}). Let stock_outcomes accumulate a "
              f"few more weeks, then re-run.")
        return 0

    data = np.array(
        [[(v if v is not None else np.nan) for v in row] for row in rows],
        dtype=float,
    )
    ret = data[:, -1]
    n = len(ret)

    print(f"\nPicker signal evaluation — horizon {args.horizon}d, "
          f"N={n} labeled picks")
    print(f"Baseline (all picks): mean fwd return {np.nanmean(ret) * 100:+.2f}%, "
          f"hit-rate {(ret > 0).mean() * 100:.1f}%\n")
    header = (f"{'signal':14}{'rank-corr':>11}{'top20% ret':>12}"
             f"{'bot20% ret':>12}{'spread':>10}")
    print(header)
    print("-" * len(header))

    results = []
    for i, sig in enumerate(SIGNALS):
        x = data[:, i]
        rho = _spearman(x, ret)
        mask = np.isfinite(x)
        xv, rv = x[mask], ret[mask]
        if len(xv) >= 10:
            k = max(1, len(xv) // 5)
            order = xv.argsort()
            bot = float(np.nanmean(rv[order[:k]]))
            top = float(np.nanmean(rv[order[-k:]]))
        else:
            top = bot = float("nan")
        results.append((sig, rho, top, bot))
        print(f"{sig:14}{rho:>11.3f}{top * 100:>11.2f}%"
              f"{bot * 100:>11.2f}%{(top - bot) * 100:>9.2f}%")

    print("\nSignals ranked by predictive strength (|rank-corr|):")
    for sig, rho, top, bot in sorted(
        results, key=lambda r: -(abs(r[1]) if np.isfinite(r[1]) else 0.0)
    ):
        if np.isfinite(rho):
            print(f"  {sig:14} corr {rho:+.3f}   "
                  f"top-minus-bottom quintile {(top - bot) * 100:+.2f}%")
    print("\nReading it: a signal near 0 correlation with a ~0 spread is not "
          "earning its weight; a positive correlation with a positive spread "
          "means higher score → better forward return (what you want).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
