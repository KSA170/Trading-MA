"""One-shot stochastic backtest report.

Replays a set of known trade timestamps through the Reverse Stochastic
calculator (calculators.stoch_reverse) and prints a per-trade comparison:
the stochastic state at entry, the calculator's to-overbought /
to-oversold boundary prices, the trade's stated target/stop, and what
actually happened next.

Runs inside GitHub Actions (see .github/workflows/stoch-backtest.yml)
because the runner has open egress to Yahoo; results are read from the
job log. Pass a JSON list via STOCH_TRADES_JSON to override the default
trade set: [{"ticker", "ts", "target", "stop", "outcome"}, ...].
"""

from __future__ import annotations

import json
import os

import calculators

# The trader's QQQ call entries (US market time, ET).
DEFAULT_TRADES = [
    {"ticker": "QQQ", "ts": "2026-07-16 10:28", "target": 714.6, "stop": 708.0, "outcome": "LOSS"},
    {"ticker": "QQQ", "ts": "2026-07-17 12:12", "target": 701.5, "stop": 696.0, "outcome": "WIN"},
    {"ticker": "QQQ", "ts": "2026-07-20 10:28", "target": 704.0, "stop": 697.5, "outcome": "WIN"},
    {"ticker": "QQQ", "ts": "2026-07-21 10:40", "target": 708.6, "stop": 703.2, "outcome": "WIN"},
    {"ticker": "QQQ", "ts": "2026-07-23 11:53", "target": 693.4, "stop": 687.0, "outcome": "WIN"},
]

INTERVAL = "5m"
HORIZON = 12
PATH = "drift"


def main() -> int:
    raw = os.environ.get("STOCH_TRADES_JSON", "").strip()
    trades = json.loads(raw) if raw else DEFAULT_TRADES

    results = []
    for t in trades:
        r = calculators.stoch_reverse(
            t["ticker"], INTERVAL, path=PATH, horizon=HORIZON,
            as_of=t["ts"])
        row = {"trade": t, "result": r}
        results.append(row)
        print(f"\n=== {t['ticker']} @ {t['ts']}  (stated outcome: {t.get('outcome')}) ===")
        if "error" in r:
            print("  ERROR:", r["error"])
            continue
        print(f"  anchor bar {r['as_of']} · price {r['price']} · "
              f"fast %K {r['fast_k']} · slow %K {r['slow_k']} · "
              f"%D {r['percent_d']} · state {r['state'].upper()}")
        for key, label in (("to_overbought", "to OB"), ("to_oversold", "to OS")):
            rows = [f"k={x['bars']}:{x['price']}" if x["price"] is not None
                    else f"k={x['bars']}:{'-' if not x['achievable'] else 'any'}"
                    for x in r[key]]
            print(f"  {label}: " + "  ".join(rows))
        a = r.get("actual")
        if a and a.get("rows"):
            path_txt = " ".join(
                f"[{x['d'][-5:]} c={x['close']} k={x['slow_k']}]" for x in a["rows"])
            print(f"  actual: {path_txt}")
            print(f"  hit OS after: {a['hit_oversold_after']} bars · "
                  f"hit OB after: {a['hit_overbought_after']} bars")

    print("\n===JSON_START===")
    print(json.dumps(results, default=str))
    print("===JSON_END===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
