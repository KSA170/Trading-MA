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
    # Skip rows without an entry close — the Strategy Report can't
    # compute forward returns from a NULL entry price, and the user
    # has explicitly asked that those rows not appear in the report.
    # Real-time write paths (alerts/picker/scanner/screener thumbs-up)
    # always have a price; backfill skips a row if its ticker has
    # aged out of the daily_snapshot retention window AND isn't in any
    # retained row's trailing-bar JSONB.
    if entry_close is None:
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

    `rec` is an options recommendation dict. Two shapes are accepted
    transparently because two upstream callers exist:

      - `recommend_for_ticker` (the live pipeline) nests contract
        details under `rec["contract"]` with keys like `contract_symbol`,
        `strike`, `mid`, `dte`, `expiration`.
      - `load_recommendations` (the DB reader, used by options.pin_rec
        and the historical backfill) returns FLAT recs with the same
        fields at the top level — and uses `mid_price` for what the
        live pipeline calls `mid`.

    Falling back across both shapes here keeps the writer agnostic to
    where the rec came from. Skips only if no contract_symbol is
    resolvable — verdict gates were removed because the only writer
    is now `user_pin` (explicit user pin), which we always honor.

    Pass `cur` to reuse an open Postgres cursor — see
    `record_stock_outcome` for the rationale.
    """
    if not snapshots.enabled():
        return False
    ticker = (ticker or "").strip().upper()
    entry_date = _coerce_date(entry_date)
    if not ticker or not entry_date or not isinstance(rec, dict):
        return False
    contract = rec.get("contract") or {}

    def _g(key, alt_key=None):
        v = contract.get(key)
        if v is None: v = rec.get(key)
        if v is None and alt_key is not None: v = rec.get(alt_key)
        return v

    contract_symbol = _g("contract_symbol")
    if not contract_symbol:
        return False
    verdict          = (rec.get("verdict") or "").upper() or None
    direction        = rec.get("direction")
    strike           = _g("strike")
    expiration       = _coerce_date(_g("expiration"))
    dte              = _g("dte")
    mid              = _g("mid", alt_key="mid_price")
    underlying_close = rec.get("close") or contract.get("underlying_close")
    composite        = rec.get("composite_score")

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

def _bars_from_yfinance(ticker: str, entry_date: str,
                       through: str) -> list[dict]:
    """Fallback when daily_snapshot has no usable row for `ticker` (the
    snapshot pipeline hasn't refreshed it recently, or the ticker is
    out of the snapshot universe). Fetch the OHLC bars directly from
    yfinance for the [entry_date, through] window.

    Returns the same shape as _fetch_forward_bars (date / close / high /
    low, ordered ascending). Network-bound — ~1-2s per call — so used
    only when the fast path returns empty.
    """
    try:
        import yfinance as yf
        # yfinance's end is exclusive; pad by 2 calendar days so we
        # don't drop the last trading day in the window.
        end_dt = (datetime.strptime(through, "%Y-%m-%d")
                  + timedelta(days=2)).strftime("%Y-%m-%d")
        hist = yf.Ticker(ticker).history(
            start=entry_date, end=end_dt, auto_adjust=False,
        )
        if hist is None or hist.empty:
            return []
        out = []
        for d, row in hist.iterrows():
            try:
                date_str = d.strftime("%Y-%m-%d")
                close = float(row["Close"])
            except (TypeError, ValueError, KeyError):
                continue
            if close <= 0 or date_str < entry_date:
                continue
            try:
                high = float(row.get("High") or close)
                low  = float(row.get("Low")  or close)
            except (TypeError, ValueError):
                high, low = close, close
            out.append({"date": date_str, "close": close,
                        "high": high, "low": low})
        out.sort(key=lambda x: x["date"])
        return out
    except Exception as exc:
        log.warning("yfinance fallback for %s [%s..%s] failed: %s",
                    ticker, entry_date, through, exc)
        return []


def _close_on_from_yfinance(ticker: str, as_of: str) -> float | None:
    """Fallback for the ITM-at-expiration check — fetch a single
    historical close for `ticker` on or just before `as_of` via
    yfinance. Returns None on any failure."""
    try:
        import yfinance as yf
        end_dt = (datetime.strptime(as_of, "%Y-%m-%d")
                  + timedelta(days=2)).strftime("%Y-%m-%d")
        # Pull a small window before as_of so we land on the most recent
        # actual trading day if as_of is a weekend/holiday.
        start_dt = (datetime.strptime(as_of, "%Y-%m-%d")
                    - timedelta(days=7)).strftime("%Y-%m-%d")
        hist = yf.Ticker(ticker).history(
            start=start_dt, end=end_dt, auto_adjust=False,
        )
        if hist is None or hist.empty:
            return None
        prior = [d for d in hist.index if d.strftime("%Y-%m-%d") <= as_of]
        if not prior:
            return None
        close = hist.loc[max(prior), "Close"]
        return float(close) if close is not None else None
    except Exception as exc:
        log.warning("yfinance close-on fallback for %s @ %s failed: %s",
                    ticker, as_of, exc)
        return None


def _fetch_forward_bars(cur, ticker: str, entry_date: str,
                        through: str) -> list[dict]:
    """Pull daily bars for `ticker` from entry_date forward through
    `through` (inclusive). Reads from daily_snapshot.recent_bars on
    the latest as_of in the window — that JSONB already carries the
    trailing ~60 bars so a single row covers all our horizons. Falls
    back to yfinance when no snapshot row covers the entry window
    (e.g., warm-cache hasn't refreshed this ticker recently or it sits
    outside the snapshot universe).
    """
    cur.execute(
        "SELECT recent_bars FROM daily_snapshot "
        "WHERE ticker = %s AND as_of >= %s AND as_of <= %s "
        "ORDER BY as_of DESC LIMIT 1",
        (ticker, entry_date, through),
    )
    row = cur.fetchone()
    out: list[dict] = []
    if row and row[0]:
        rb = row[0]
        if isinstance(rb, str):
            try:
                rb = json.loads(rb)
            except Exception:
                rb = None
        if isinstance(rb, dict):
            bars = rb.get("bars") or []
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
    if out:
        return out
    # Fast path returned nothing — fall back to yfinance.
    return _bars_from_yfinance(ticker, entry_date, through)


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


# Per-batch row count for the forward-fill / regime-tag passes. Small
# enough that a dropped SSL connection only loses ~1s of work, large
# enough that the per-batch handshake overhead stays under 5% of total
# wall time.
_FILL_BATCH_SIZE = 25


def _process_in_batches(work: list, name: str, processor):
    """Run `processor(cur, batch)` against successive batches of `work`,
    each in its own short-lived connection. A batch that raises rolls
    back — its in-flight row count is NOT added to the total — but
    previously committed batches are safe. Returns
    (committed_total, failed_batches).
    """
    committed = 0
    failed = 0
    for i in range(0, len(work), _FILL_BATCH_SIZE):
        batch = work[i:i + _FILL_BATCH_SIZE]
        try:
            with snapshots._conn() as c, c.cursor() as cur:
                n = processor(cur, batch)
            # Reached only if the with-block committed without raising.
            committed += int(n or 0)
        except Exception as exc:
            failed += 1
            log.warning("%s: batch %d (rows %d-%d) failed: %s — "
                        "previously committed batches are intact",
                        name, i // _FILL_BATCH_SIZE + 1,
                        i + 1, min(i + _FILL_BATCH_SIZE, len(work)), exc)
    if failed:
        log.warning("%s: %d/%d batches failed; updated count reflects "
                    "committed work only", name, failed,
                    (len(work) + _FILL_BATCH_SIZE - 1) // _FILL_BATCH_SIZE)
    return committed, failed


def fill_stock_forward_returns(limit: int | None = None) -> dict:
    """Compute forward returns for every stock_outcomes row whose 20d
    window is now in the past (or for which we have enough bars).
    Returns {"checked": N, "updated": M, "skipped_no_close": K, ...}.

    Batched: each chunk of `_FILL_BATCH_SIZE` rows runs in its own
    short-lived Postgres connection so a dropped SSL doesn't roll back
    every other batch's work.
    """
    if not snapshots.enabled():
        return {"checked": 0, "updated": 0}
    today = date.today().isoformat()
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
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(sql)
            work = cur.fetchall()
    except Exception as exc:
        log.warning("fill_stock_forward_returns: fetch failed: %s", exc)
        return {"checked": 0, "updated": 0}

    # Tracked across batches via mutable list for closure access.
    skipped_no_close = [0]

    def _proc(cur, batch):
        n = 0
        for ticker, entry_date, entry_close in batch:
            entry_date_str = _coerce_date(entry_date)
            through = min(
                (entry_date + timedelta(days=FORWARD_LOOKAHEAD_DAYS)).isoformat(),
                today,
            )
            bars = _fetch_forward_bars(cur, ticker, entry_date_str, through)
            ec = entry_close
            if ec is None and bars:
                ec = bars[0]["close"]
            if ec is None:
                skipped_no_close[0] += 1
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
                (ec, rets["ret_1d"], rets["ret_3d"], rets["ret_5d"],
                 rets["ret_10d"], rets["ret_20d"],
                 rets["max_favorable_excursion_20d"],
                 rets["max_drawdown_20d"],
                 through, ticker, entry_date_str),
            )
            n += 1
        return n

    committed, failed = _process_in_batches(
        work, "fill_stock_forward_returns", _proc)
    if skipped_no_close[0]:
        log.info("fill_stock_forward_returns: %d row(s) skipped — no "
                 "entry_close and no forward bars in snapshot",
                 skipped_no_close[0])
    return {"checked": len(work), "updated": committed,
            "skipped_no_close": skipped_no_close[0],
            "failed_batches": failed}


def fill_option_forward_returns(limit: int | None = None) -> dict:
    """Compute underlying forward returns for every option_outcomes
    row whose 20d window is now in the past. Batched (see
    fill_stock_forward_returns) so an SSL drop doesn't cost the whole
    pass. Logs which tickers were skipped and why — usually "no
    snapshot data for ticker X" when the underlying is outside the
    snapshot universe.
    """
    if not snapshots.enabled():
        return {"checked": 0, "updated": 0}
    today = date.today().isoformat()
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
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(sql)
            work = cur.fetchall()
    except Exception as exc:
        log.warning("fill_option_forward_returns: fetch failed: %s", exc)
        return {"checked": 0, "updated": 0}

    skipped: list[str] = []   # tickers skipped this pass + reason

    def _proc(cur, batch):
        n = 0
        for ticker, entry_date, ec, direction, strike, expiration in batch:
            entry_date_str = _coerce_date(entry_date)
            through = min(
                (entry_date + timedelta(days=FORWARD_LOOKAHEAD_DAYS)).isoformat(),
                today,
            )
            bars = _fetch_forward_bars(cur, ticker, entry_date_str, through)
            if ec is None and bars:
                ec = bars[0]["close"]
            if ec is None:
                # Diagnose so the user can see WHY this row didn't update.
                if not bars:
                    skipped.append(f"{ticker}@{entry_date_str}: no snapshot bars")
                else:
                    skipped.append(f"{ticker}@{entry_date_str}: bars present but close missing")
                continue
            rets = _compute_returns(float(ec), bars)
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
                exp_close = float(r[0]) if r and r[0] is not None else None
                if exp_close is None:
                    # Snapshot doesn't cover this ticker on the expiration
                    # date — fall back to yfinance for a single close.
                    exp_close = _close_on_from_yfinance(ticker, exp_str)
                if exp_close is not None:
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
            n += 1
        return n

    committed, failed = _process_in_batches(
        work, "fill_option_forward_returns", _proc)
    if skipped:
        log.info("fill_option_forward_returns: %d row(s) skipped:",
                 len(skipped))
        for line in skipped[:20]:
            log.info("    %s", line)
        if len(skipped) > 20:
            log.info("    ... and %d more", len(skipped) - 20)
    return {"checked": len(work), "updated": committed,
            "skipped": len(skipped),
            "failed_batches": failed}


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
    its 50d EMA and VIX's close on the entry date and stamp them in.

    SPY-above-50d comes from the daily_snapshot row for SPY on or before
    the entry date (we use the snapshot's ema50 as a proxy — it tracks
    the 50d MA closely enough for regime bucketing). VIX comes from
    ^VIX's snapshot row if present, else NULL (graceful).

    Batched per `_FILL_BATCH_SIZE`. Each table processed separately so
    an early failure in one doesn't block the other.
    """
    if not snapshots.enabled():
        return {"updated": 0}
    total_updated = 0
    total_failed = 0
    for table in ("stock_outcomes", "option_outcomes"):
        sql = (
            f"SELECT ticker, entry_date FROM {table} "
            "WHERE regime_spy_above_50d IS NULL "
            "ORDER BY entry_date DESC"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"
        try:
            with snapshots._conn() as c, c.cursor() as cur:
                cur.execute(sql)
                work = cur.fetchall()
        except Exception as exc:
            log.warning("fill_regime_tags(%s): fetch failed: %s", table, exc)
            continue

        def _proc(cur, batch, _table=table):
            n = 0
            for ticker, entry_date in batch:
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
                    f"UPDATE {_table} SET "
                    "  regime_spy_above_50d = %s, regime_vix_bucket = %s "
                    "WHERE ticker = %s AND entry_date = %s",
                    (above, bucket, ticker, d),
                )
                n += 1
            return n

        committed, failed = _process_in_batches(
            work, f"fill_regime_tags({table})", _proc)
        total_updated += committed
        total_failed  += failed
    return {"updated": total_updated, "failed_batches": total_failed}


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
