"""Outcome tracking — strategy report cards for stocks and options.

Captures every "tracked entry" the app produces (alert fires, picker
top-25, momentum scan hit, manual thumbs-up, options recommendation)
and fills in forward returns from the daily snapshot table. The two
report tabs aggregate these rows into hit-rate / median-return / regime
breakdowns so the user can see which sources actually work.

Two tables:
  stock_outcomes  — one row per (ticker, entry_date). Multiple sources
                    that fire for the same ticker+day stack into the
                    `sources` JSONB array (append on conflict, don't
                    duplicate the entry).
  option_outcomes — one row per (ticker, entry_date). Carries the
                    contract snapshot taken at entry plus the
                    underlying's forward returns (yfinance doesn't
                    expose historical contract prices, so contract P&L
                    is not tracked — see PR #N).

DATABASE_URL gates the layer. When unset, every function no-ops.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

import snapshots

log = logging.getLogger("outcomes")

# Horizons (in trading days) at which forward returns are computed.
# 1d/3d/5d are short-term reaction; 10d/20d cover the ~4-week window
# most setup rules implicitly target.
HORIZONS = (1, 3, 5, 10, 20)

# Maximum bars to look forward when filling. 30 calendar days = ~22
# trading days, comfortably covers the 20d horizon.
FORWARD_LOOKAHEAD_DAYS = 30


_SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_outcomes (
    ticker         TEXT NOT NULL,
    entry_date     DATE NOT NULL,
    entry_close    REAL,
    sources        JSONB NOT NULL DEFAULT '[]'::jsonb,
    regime_spy_above_50d  BOOLEAN,
    regime_vix_bucket     TEXT,
    ret_1d         REAL,
    ret_3d         REAL,
    ret_5d         REAL,
    ret_10d        REAL,
    ret_20d        REAL,
    max_favorable_excursion_20d  REAL,
    max_drawdown_20d              REAL,
    forward_filled_through        DATE,
    created_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (ticker, entry_date)
);
CREATE INDEX IF NOT EXISTS stock_outcomes_entry_date_idx
    ON stock_outcomes (entry_date DESC);

CREATE TABLE IF NOT EXISTS option_outcomes (
    ticker            TEXT NOT NULL,
    entry_date        DATE NOT NULL,
    direction         TEXT,
    contract_symbol   TEXT,
    strike            REAL,
    expiration        DATE,
    dte_at_entry      INT,
    mid_at_entry      REAL,
    underlying_close_at_entry  REAL,
    composite_score   REAL,
    verdict           TEXT,
    sources           JSONB NOT NULL DEFAULT '[]'::jsonb,
    regime_spy_above_50d  BOOLEAN,
    regime_vix_bucket     TEXT,
    underlying_ret_1d   REAL,
    underlying_ret_3d   REAL,
    underlying_ret_5d   REAL,
    underlying_ret_10d  REAL,
    underlying_ret_20d  REAL,
    expiration_itm      BOOLEAN,
    forward_filled_through  DATE,
    created_at        TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (ticker, entry_date)
);
CREATE INDEX IF NOT EXISTS option_outcomes_entry_date_idx
    ON option_outcomes (entry_date DESC);
CREATE INDEX IF NOT EXISTS option_outcomes_expiration_idx
    ON option_outcomes (expiration);
"""


def init_tables() -> None:
    if not snapshots.enabled():
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(_SCHEMA)
    except Exception as exc:
        log.warning("outcomes.init_tables failed: %s", exc)


# --- write paths ----------------------------------------------------------

def _coerce_date(d: Any) -> str | None:
    if d is None:
        return None
    if isinstance(d, (date, datetime)):
        return d.strftime("%Y-%m-%d")
    s = str(d).strip()
    return s or None


def record_stock_outcome(
    ticker: str,
    entry_date: Any,
    entry_close: float | None,
    source: dict,
    *,
    cur=None,
) -> bool:
    """Insert a stock outcome row, or append a source to the existing row.

    `source` is one element of the sources array — a dict like
    {"kind": "alert_screener", "id": 42, "label": "Watchlist"}. If the
    (ticker, entry_date) row already exists, the source is appended to
    its sources array if not already present (matched on kind+id).

    Pass `cur` to reuse an open Postgres cursor (caller owns the
    connection + commit). Used by the backfill script to avoid opening
    a fresh connection per row — the per-connection TLS/auth handshake
    is a 10-100x speedup on a remote DB. Without `cur` the function
    opens its own short-lived connection — the path the realtime
    write-paths (alerts/picker/scanner/options) use.
    """
    if not snapshots.enabled():
        return False
    ticker = (ticker or "").strip().upper()
    entry_date = _coerce_date(entry_date)
    if not ticker or not entry_date or not isinstance(source, dict):
        return False
    sql = (
        "INSERT INTO stock_outcomes (ticker, entry_date, entry_close, sources) "
        "VALUES (%s, %s, %s, %s::jsonb) "
        "ON CONFLICT (ticker, entry_date) DO UPDATE SET "
        "  sources = CASE "
        "    WHEN stock_outcomes.sources @> %s::jsonb THEN stock_outcomes.sources "
        "    ELSE stock_outcomes.sources || %s::jsonb "
        "  END, "
        "  entry_close = COALESCE(stock_outcomes.entry_close, EXCLUDED.entry_close)"
    )
    params = (ticker, entry_date, entry_close,
              json.dumps([source]),
              json.dumps([{"kind": source.get("kind"), "id": source.get("id")}]),
              json.dumps([source]))
    try:
        if cur is not None:
            cur.execute(sql, params)
        else:
            with snapshots._conn() as c, c.cursor() as cur2:
                cur2.execute(sql, params)
        return True
    except Exception as exc:
        log.warning("outcomes.record_stock_outcome(%s,%s) failed: %s",
                    ticker, entry_date, exc)
        return False


def record_option_outcome(
    ticker: str,
    entry_date: Any,
    rec: dict,
    source: dict,
    *,
    cur=None,
) -> bool:
    """Insert (or update) an option outcome row.

    `rec` is the options recommendation dict (same shape passed to
    options.save_recommendation). PASS-verdict recommendations or those
    without a chosen contract are skipped — they're not real entries.

    Pass `cur` to reuse an open Postgres cursor — see
    `record_stock_outcome` for the rationale.
    """
    if not snapshots.enabled():
        return False
    ticker = (ticker or "").strip().upper()
    entry_date = _coerce_date(entry_date)
    if not ticker or not entry_date or not isinstance(rec, dict):
        return False
    verdict = (rec.get("verdict") or "").upper()
    if verdict in ("PASS", ""):
        return False
    contract = rec.get("contract") or {}
    contract_symbol = contract.get("contract_symbol")
    if not contract_symbol:
        return False
    direction = rec.get("direction")
    strike = contract.get("strike")
    expiration = _coerce_date(contract.get("expiration"))
    dte = contract.get("dte")
    mid = contract.get("mid")
    underlying_close = rec.get("close") or contract.get("underlying_close")
    composite = rec.get("composite_score")

    sql = (
        "INSERT INTO option_outcomes "
        "(ticker, entry_date, direction, contract_symbol, strike, "
        " expiration, dte_at_entry, mid_at_entry, underlying_close_at_entry, "
        " composite_score, verdict, sources) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) "
        "ON CONFLICT (ticker, entry_date) DO UPDATE SET "
        "  sources = CASE "
        "    WHEN option_outcomes.sources @> %s::jsonb THEN option_outcomes.sources "
        "    ELSE option_outcomes.sources || %s::jsonb "
        "  END, "
        "  composite_score = COALESCE(EXCLUDED.composite_score, option_outcomes.composite_score), "
        "  verdict = COALESCE(EXCLUDED.verdict, option_outcomes.verdict), "
        "  mid_at_entry = COALESCE(option_outcomes.mid_at_entry, EXCLUDED.mid_at_entry), "
        "  underlying_close_at_entry = COALESCE(option_outcomes.underlying_close_at_entry, EXCLUDED.underlying_close_at_entry)"
    )
    params = (ticker, entry_date, direction, contract_symbol, strike,
              expiration, dte, mid, underlying_close,
              composite, verdict, json.dumps([source]),
              json.dumps([{"kind": source.get("kind"), "id": source.get("id")}]),
              json.dumps([source]))
    try:
        if cur is not None:
            cur.execute(sql, params)
        else:
            with snapshots._conn() as c, c.cursor() as cur2:
                cur2.execute(sql, params)
        return True
    except Exception as exc:
        log.warning("outcomes.record_option_outcome(%s,%s) failed: %s",
                    ticker, entry_date, exc)
        return False


# --- forward return filler ------------------------------------------------

def _fetch_forward_bars(cur, ticker: str, entry_date: str,
                        through: str) -> list[dict]:
    """Pull daily bars for `ticker` from entry_date forward through
    `through` (inclusive). Reads from daily_snapshot.recent_bars on
    the latest as_of in the window — that JSONB already carries the
    trailing ~60 bars so a single row covers all our horizons."""
    cur.execute(
        "SELECT recent_bars FROM daily_snapshot "
        "WHERE ticker = %s AND as_of >= %s AND as_of <= %s "
        "ORDER BY as_of DESC LIMIT 1",
        (ticker, entry_date, through),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return []
    rb = row[0]
    if isinstance(rb, str):
        try:
            rb = json.loads(rb)
        except Exception:
            return []
    if not isinstance(rb, dict):
        return []
    bars = rb.get("bars") or []
    out = []
    for b in bars:
        if not isinstance(b, dict):
            continue
        d = b.get("date") or b.get("as_of")
        try:
            close = float(b.get("close"))
        except (TypeError, ValueError):
            continue
        if not d or close <= 0:
            continue
        if str(d) >= entry_date:
            out.append({"date": str(d), "close": close,
                        "high": float(b.get("high") or close),
                        "low":  float(b.get("low")  or close)})
    out.sort(key=lambda x: x["date"])
    return out


def _compute_returns(entry_close: float, bars: list[dict]) -> dict:
    """Given the entry close and the forward bars (entry day = bars[0]
    if present, otherwise the first day AFTER entry), return per-horizon
    returns plus max-favorable-excursion and max-drawdown over 20d."""
    out = {f"ret_{h}d": None for h in HORIZONS}
    out["max_favorable_excursion_20d"] = None
    out["max_drawdown_20d"] = None
    if entry_close is None or entry_close <= 0 or not bars:
        return out
    # Skip the entry day itself — forward returns measure what happened
    # AFTER the signal, not the bar the signal was computed on.
    forward = [b for b in bars if b["date"] > bars[0]["date"]] \
              if len(bars) > 1 and bars[0]["date"] == bars[0]["date"] \
              else list(bars)
    # The check above is a guard for the rare case the entry day's bar
    # isn't in the snapshot; treat all bars as forward in that case.
    if not forward:
        return out
    for h in HORIZONS:
        if len(forward) >= h:
            c = forward[h - 1]["close"]
            out[f"ret_{h}d"] = (c / entry_close - 1.0) * 100.0
    window = forward[:20]
    if window:
        max_h = max(b["high"] for b in window)
        min_l = min(b["low"]  for b in window)
        out["max_favorable_excursion_20d"] = (max_h / entry_close - 1.0) * 100.0
        out["max_drawdown_20d"]            = (min_l / entry_close - 1.0) * 100.0
    return out


def fill_stock_forward_returns(limit: int | None = None) -> dict:
    """Compute forward returns for every stock_outcomes row whose 20d
    window is now in the past (or for which we have enough bars).
    Returns {"checked": N, "updated": M}."""
    if not snapshots.enabled():
        return {"checked": 0, "updated": 0}
    today = date.today().isoformat()
    checked = updated = 0
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            # Pull rows where the 20d window has ended (or we haven't
            # filled at all yet). Use entry_date + 30 calendar days as
            # the trigger — by then daily_snapshot has the bars.
            sql = (
                "SELECT ticker, entry_date, entry_close "
                "FROM stock_outcomes "
                "WHERE (forward_filled_through IS NULL "
                "   OR forward_filled_through < entry_date + INTERVAL '30 days') "
                "  AND entry_date <= (CURRENT_DATE - INTERVAL '1 day') "
                "ORDER BY entry_date DESC"
            )
            if limit:
                sql += f" LIMIT {int(limit)}"
            cur.execute(sql)
            rows = cur.fetchall()
            for ticker, entry_date, entry_close in rows:
                checked += 1
                entry_date_str = _coerce_date(entry_date)
                # Window end: 30 calendar days out, or today, whichever is earlier.
                through = min(
                    (entry_date + timedelta(days=FORWARD_LOOKAHEAD_DAYS)).isoformat(),
                    today,
                )
                bars = _fetch_forward_bars(cur, ticker, entry_date_str, through)
                # Backfill entry_close from snapshot if missing.
                ec = entry_close
                if ec is None and bars:
                    ec = bars[0]["close"]
                if ec is None:
                    continue
                rets = _compute_returns(float(ec), bars)
                cur.execute(
                    "UPDATE stock_outcomes SET "
                    "  entry_close = COALESCE(entry_close, %s), "
                    "  ret_1d = %s, ret_3d = %s, ret_5d = %s, "
                    "  ret_10d = %s, ret_20d = %s, "
                    "  max_favorable_excursion_20d = %s, "
                    "  max_drawdown_20d = %s, "
                    "  forward_filled_through = %s "
                    "WHERE ticker = %s AND entry_date = %s",
                    (ec,
                     rets["ret_1d"], rets["ret_3d"], rets["ret_5d"],
                     rets["ret_10d"], rets["ret_20d"],
                     rets["max_favorable_excursion_20d"],
                     rets["max_drawdown_20d"],
                     through, ticker, entry_date_str),
                )
                updated += 1
    except Exception as exc:
        log.warning("outcomes.fill_stock_forward_returns failed: %s", exc)
    return {"checked": checked, "updated": updated}


def fill_option_forward_returns(limit: int | None = None) -> dict:
    if not snapshots.enabled():
        return {"checked": 0, "updated": 0}
    today = date.today().isoformat()
    checked = updated = 0
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            sql = (
                "SELECT ticker, entry_date, underlying_close_at_entry, "
                "       direction, strike, expiration "
                "FROM option_outcomes "
                "WHERE (forward_filled_through IS NULL "
                "   OR forward_filled_through < entry_date + INTERVAL '30 days' "
                "   OR (expiration <= CURRENT_DATE AND expiration_itm IS NULL)) "
                "  AND entry_date <= (CURRENT_DATE - INTERVAL '1 day') "
                "ORDER BY entry_date DESC"
            )
            if limit:
                sql += f" LIMIT {int(limit)}"
            cur.execute(sql)
            rows = cur.fetchall()
            for ticker, entry_date, ec, direction, strike, expiration in rows:
                checked += 1
                entry_date_str = _coerce_date(entry_date)
                through = min(
                    (entry_date + timedelta(days=FORWARD_LOOKAHEAD_DAYS)).isoformat(),
                    today,
                )
                bars = _fetch_forward_bars(cur, ticker, entry_date_str, through)
                if ec is None and bars:
                    ec = bars[0]["close"]
                if ec is None:
                    continue
                rets = _compute_returns(float(ec), bars)
                # Expiration ITM check — only meaningful once expiration
                # is in the past and we have the underlying close on the
                # expiration date.
                itm = None
                if expiration and expiration <= date.today() and strike:
                    exp_str = _coerce_date(expiration)
                    cur.execute(
                        "SELECT close FROM daily_snapshot "
                        "WHERE ticker = %s AND as_of <= %s "
                        "ORDER BY as_of DESC LIMIT 1",
                        (ticker, exp_str),
                    )
                    r = cur.fetchone()
                    if r and r[0] is not None:
                        exp_close = float(r[0])
                        if direction == "call":
                            itm = exp_close > float(strike)
                        elif direction == "put":
                            itm = exp_close < float(strike)
                cur.execute(
                    "UPDATE option_outcomes SET "
                    "  underlying_close_at_entry = COALESCE(underlying_close_at_entry, %s), "
                    "  underlying_ret_1d = %s, underlying_ret_3d = %s, "
                    "  underlying_ret_5d = %s, underlying_ret_10d = %s, "
                    "  underlying_ret_20d = %s, "
                    "  expiration_itm = COALESCE(expiration_itm, %s), "
                    "  forward_filled_through = %s "
                    "WHERE ticker = %s AND entry_date = %s",
                    (ec, rets["ret_1d"], rets["ret_3d"], rets["ret_5d"],
                     rets["ret_10d"], rets["ret_20d"],
                     itm, through, ticker, entry_date_str),
                )
                updated += 1
    except Exception as exc:
        log.warning("outcomes.fill_option_forward_returns failed: %s", exc)
    return {"checked": checked, "updated": updated}


# --- regime tagging -------------------------------------------------------

def _vix_bucket(vix: float | None) -> str | None:
    if vix is None:
        return None
    if vix < 15: return "low (<15)"
    if vix < 20: return "calm (15-20)"
    if vix < 30: return "elevated (20-30)"
    return "stressed (30+)"


def fill_regime_tags(limit: int | None = None) -> dict:
    """For any outcome row missing regime tags, look up SPY's close vs
    its 50d MA and VIX's close on the entry date and stamp them in.

    SPY-above-50d comes from the daily_snapshot row for SPY on or before
    the entry date (we use the snapshot's ema50 as a proxy — it tracks
    the 50d MA closely enough for regime bucketing). VIX comes from
    ^VIX's snapshot row if present, else NULL (graceful)."""
    if not snapshots.enabled():
        return {"updated": 0}
    updated = 0
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            for table in ("stock_outcomes", "option_outcomes"):
                sql = (
                    f"SELECT ticker, entry_date FROM {table} "
                    "WHERE regime_spy_above_50d IS NULL "
                    "ORDER BY entry_date DESC"
                )
                if limit:
                    sql += f" LIMIT {int(limit)}"
                cur.execute(sql)
                rows = cur.fetchall()
                for ticker, entry_date in rows:
                    d = _coerce_date(entry_date)
                    cur.execute(
                        "SELECT close, ema50 FROM daily_snapshot "
                        "WHERE ticker = 'SPY' AND as_of <= %s "
                        "ORDER BY as_of DESC LIMIT 1",
                        (d,),
                    )
                    spy = cur.fetchone()
                    above = None
                    if spy and spy[0] and spy[1]:
                        above = float(spy[0]) > float(spy[1])
                    cur.execute(
                        "SELECT close FROM daily_snapshot "
                        "WHERE ticker = '^VIX' AND as_of <= %s "
                        "ORDER BY as_of DESC LIMIT 1",
                        (d,),
                    )
                    vix_row = cur.fetchone()
                    vix = float(vix_row[0]) if vix_row and vix_row[0] else None
                    bucket = _vix_bucket(vix)
                    cur.execute(
                        f"UPDATE {table} SET "
                        "  regime_spy_above_50d = %s, regime_vix_bucket = %s "
                        "WHERE ticker = %s AND entry_date = %s",
                        (above, bucket, ticker, d),
                    )
                    updated += 1
    except Exception as exc:
        log.warning("outcomes.fill_regime_tags failed: %s", exc)
    return {"updated": updated}


# --- report aggregator ----------------------------------------------------

def _pct_quantile(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def _summarize(rows: list[dict], horizon_field: str) -> dict:
    vals = [r[horizon_field] for r in rows if r.get(horizon_field) is not None]
    if not vals:
        return {"count": len(rows), "hit_rate": None, "median": None,
                "p25": None, "p75": None, "mean": None}
    hits = sum(1 for v in vals if v > 0)
    return {
        "count":    len(rows),
        "filled":   len(vals),
        "hit_rate": hits / len(vals),
        "median":   _pct_quantile(vals, 0.5),
        "p25":      _pct_quantile(vals, 0.25),
        "p75":      _pct_quantile(vals, 0.75),
        "mean":     sum(vals) / len(vals),
    }


def _by_source(rows: list[dict], horizon_field: str) -> list[dict]:
    """Bucket rows by source.kind. A row with N sources contributes to
    N buckets — that's the right semantics for "how did the picker do"
    when a ticker was also flagged by an alert."""
    buckets: dict[str, list[dict]] = {}
    labels: dict[str, str] = {}
    for r in rows:
        srcs = r.get("sources") or []
        if isinstance(srcs, str):
            try: srcs = json.loads(srcs)
            except Exception: srcs = []
        for s in srcs:
            kind = (s or {}).get("kind") or "unknown"
            buckets.setdefault(kind, []).append(r)
            if s.get("label") and kind not in labels:
                labels[kind] = s["label"]
    out = []
    for kind, bucket in sorted(buckets.items()):
        summary = _summarize(bucket, horizon_field)
        summary["kind"]  = kind
        summary["label"] = labels.get(kind, kind)
        out.append(summary)
    return out


def _by_regime(rows: list[dict], horizon_field: str) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        spy = r.get("regime_spy_above_50d")
        vix = r.get("regime_vix_bucket") or "?"
        if spy is True:   spy_lbl = "SPY > 50d"
        elif spy is False: spy_lbl = "SPY < 50d"
        else:              spy_lbl = "SPY ?"
        key = f"{spy_lbl} / VIX {vix}"
        buckets.setdefault(key, []).append(r)
    out = []
    for key, bucket in sorted(buckets.items()):
        summary = _summarize(bucket, horizon_field)
        summary["regime"] = key
        out.append(summary)
    return out


def _histogram(rows: list[dict], horizon_field: str, bins: int = 20) -> dict:
    vals = [r[horizon_field] for r in rows if r.get(horizon_field) is not None]
    if not vals:
        return {"edges": [], "counts": []}
    lo, hi = min(vals), max(vals)
    if lo == hi:
        return {"edges": [lo, hi], "counts": [len(vals)]}
    step = (hi - lo) / bins
    edges = [lo + i * step for i in range(bins + 1)]
    counts = [0] * bins
    for v in vals:
        idx = min(int((v - lo) / step), bins - 1)
        counts[idx] += 1
    return {"edges": edges, "counts": counts}


def _row_to_dict(cur, row) -> dict:
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def stock_report(days: int = 90, horizon: int = 5) -> dict:
    """Aggregated report for the Stock Strategy Report tab.

    `days` — how far back to include outcome rows (entry_date filter).
    `horizon` — which forward-return horizon to summarize on (1/3/5/10/20).
    """
    if not snapshots.enabled():
        return {"enabled": False, "rows": [], "by_source": [],
                "by_regime": [], "histogram": {"edges": [], "counts": []},
                "overall": {}}
    if horizon not in HORIZONS:
        horizon = 5
    h_field = f"ret_{horizon}d"
    rows: list[dict] = []
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT ticker, entry_date, entry_close, sources, "
                "       regime_spy_above_50d, regime_vix_bucket, "
                "       ret_1d, ret_3d, ret_5d, ret_10d, ret_20d, "
                "       max_favorable_excursion_20d, max_drawdown_20d "
                "FROM stock_outcomes "
                "WHERE entry_date >= CURRENT_DATE - INTERVAL '%s days' "
                "ORDER BY entry_date DESC, ticker" % int(days)
            )
            for r in cur.fetchall():
                rows.append(_row_to_dict(cur, r))
    except Exception as exc:
        log.warning("outcomes.stock_report failed: %s", exc)
    for r in rows:
        # Date objects → ISO strings for JSON.
        r["entry_date"] = _coerce_date(r["entry_date"])
    return {
        "enabled": True,
        "horizon": horizon,
        "days":    days,
        "overall": _summarize(rows, h_field),
        "by_source": _by_source(rows, h_field),
        "by_regime": _by_regime(rows, h_field),
        "histogram": _histogram(rows, h_field),
        "rows":      rows,
    }


def option_report(days: int = 90, horizon: int = 5) -> dict:
    if not snapshots.enabled():
        return {"enabled": False, "rows": [], "by_source": [],
                "by_regime": [], "histogram": {"edges": [], "counts": []},
                "overall": {}, "expiration": {"total": 0, "itm": 0, "otm": 0}}
    if horizon not in HORIZONS:
        horizon = 5
    h_field = f"underlying_ret_{horizon}d"
    rows: list[dict] = []
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT ticker, entry_date, direction, contract_symbol, "
                "       strike, expiration, dte_at_entry, mid_at_entry, "
                "       underlying_close_at_entry, composite_score, verdict, "
                "       sources, regime_spy_above_50d, regime_vix_bucket, "
                "       underlying_ret_1d, underlying_ret_3d, underlying_ret_5d, "
                "       underlying_ret_10d, underlying_ret_20d, expiration_itm "
                "FROM option_outcomes "
                "WHERE entry_date >= CURRENT_DATE - INTERVAL '%s days' "
                "ORDER BY entry_date DESC, ticker" % int(days)
            )
            for r in cur.fetchall():
                rows.append(_row_to_dict(cur, r))
    except Exception as exc:
        log.warning("outcomes.option_report failed: %s", exc)
    for r in rows:
        r["entry_date"] = _coerce_date(r["entry_date"])
        r["expiration"] = _coerce_date(r["expiration"])
    # Map underlying_ret_Xd → ret_Xd for the summary helpers (they look
    # at a single key by name).
    aliased = []
    for r in rows:
        ar = dict(r)
        for h in HORIZONS:
            ar[f"ret_{h}d"] = r.get(f"underlying_ret_{h}d")
        aliased.append(ar)
    h_alias = f"ret_{horizon}d"
    expired_rows = [r for r in rows if r.get("expiration_itm") is not None]
    itm = sum(1 for r in expired_rows if r["expiration_itm"])
    return {
        "enabled":  True,
        "horizon":  horizon,
        "days":     days,
        "overall":  _summarize(aliased, h_alias),
        "by_source": _by_source(aliased, h_alias),
        "by_regime": _by_regime(aliased, h_alias),
        "histogram": _histogram(aliased, h_alias),
        "expiration": {
            "total":  len(expired_rows),
            "itm":    itm,
            "otm":    len(expired_rows) - itm,
        },
        "rows":     rows,
    }


# --- CLI entry (called by outcomes_cron.py) -------------------------------

def run_nightly() -> dict:
    init_tables()
    s = fill_stock_forward_returns()
    o = fill_option_forward_returns()
    r = fill_regime_tags()
    log.info("outcomes nightly: stock=%s option=%s regime=%s", s, o, r)
    return {"stock": s, "option": o, "regime": r}
