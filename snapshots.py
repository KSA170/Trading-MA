"""Postgres-backed daily-snapshot table.

Stores one row per (ticker, as_of_date) with the indicator values the
screener needs plus a JSONB blob of the trailing ~60 OHLCV bars so streak
and rvol gates work without re-reading the 6-month pickle. Lets a screen
run against a historical date serve from a single bulk SELECT instead of
8k disk reads + DataFrame slices.

DATABASE_URL enables the layer. When unset, every function no-ops and
the screener falls back to its pickle-cache path.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from typing import Iterable

log = logging.getLogger("snapshots")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Last error encountered during init() — exposed via diagnostics so the
# UI can surface "you set DATABASE_URL but the connection failed" vs
# "DATABASE_URL is missing entirely".
_init_error: str | None = None

# Last error encountered importing psycopg2 — surfaces "you added the
# env var but the binary wheel isn't installed yet" type issues.
_driver_error: str | None = None

# Last error returned by upsert_many — captured so the UI can show why
# rows aren't being persisted even though the connection is "up".
_last_write_error: str | None = None


def diagnostics() -> dict:
    """Snapshot of what the worker can see about the DB layer. Safe to
    expose — never returns the URL itself, only its scheme/host so the
    user can confirm the env var is actually plumbed through."""
    url = DATABASE_URL
    scheme = host = None
    if url:
        try:
            from urllib.parse import urlparse
            p = urlparse(url)
            scheme = p.scheme or None
            host = p.hostname or None
        except Exception:
            pass
    return {
        "database_url_set": bool(url),
        "database_url_scheme": scheme,
        "database_url_host": host,
        "driver_error": _driver_error,
        "init_error": _init_error,
        "initialized": _initialized,
    }

# Last N OHLCV bars stored per row as JSONB. 60 covers any reasonable
# streak or rvol lookback the UI exposes (max 60 days).
RECENT_BARS_KEEP = 60

# Trim the table to the most recent N distinct as_of dates after each
# snapshot write.
RETENTION_DAYS = 5

_init_lock = threading.Lock()
_initialized = False


def enabled() -> bool:
    return bool(DATABASE_URL)


@contextmanager
def _conn():
    global _driver_error
    try:
        import psycopg2  # local import so the rest of the app starts even
        # when psycopg2 isn't installed yet (e.g. the first deploy where
        # DATABASE_URL exists but the wheel hasn't been picked up).
    except Exception as exc:
        _driver_error = f"{type(exc).__name__}: {exc}"
        raise
    # TCP keepalives — without these, Render's Postgres aggressively
    # closes connections that sit "idle" between queries (even sub-second
    # gaps during a Python loop count). The forward-fill cron caught
    # this as "SSL connection has been closed unexpectedly" mid-batch,
    # rolling back the entire transaction. Sending a keepalive probe
    # every 30s with a 10s retry interval keeps the TCP socket healthy
    # without meaningful overhead.
    c = psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
    )
    try:
        yield c
        c.commit()
    except Exception:
        try:
            c.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            c.close()
        except Exception:
            pass


_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_snapshot (
    ticker         TEXT  NOT NULL,
    as_of          DATE  NOT NULL,
    close          REAL,
    prior_close    REAL,
    volume         REAL,
    avg_volume     REAL,
    ema21          REAL,
    ema50          REAL,
    rsi14          REAL,
    rsi14_prev     REAL,
    rsi_sma9       REAL,
    macd           REAL,
    macd_prev      REAL,
    macd_signal    REAL,
    macd_hist      REAL,
    macd_hist_prev REAL,
    shares         REAL,
    recent_bars    JSONB,
    created_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (ticker, as_of)
);
CREATE INDEX IF NOT EXISTS daily_snapshot_as_of_idx ON daily_snapshot (as_of);
ALTER TABLE daily_snapshot ADD COLUMN IF NOT EXISTS macd_prev REAL;
ALTER TABLE daily_snapshot ADD COLUMN IF NOT EXISTS rsi14_prev REAL;
"""


def init() -> None:
    """Idempotent CREATE TABLE — safe to call on every worker boot."""
    global _initialized, _init_error
    if not enabled():
        log.info("snapshots: DATABASE_URL not set — disabled")
        _init_error = "DATABASE_URL env var not set on this worker"
        return
    with _init_lock:
        if _initialized:
            return
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute(_SCHEMA)
            _initialized = True
            _init_error = None
            log.info("snapshots: table ready")
        except Exception as exc:
            _init_error = f"{type(exc).__name__}: {exc}"
            log.warning("snapshots: init failed: %s", exc)


def has_date(as_of: str) -> bool:
    if not enabled():
        return False
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM daily_snapshot WHERE as_of = %s LIMIT 1",
                (as_of,),
            )
            return cur.fetchone() is not None
    except Exception as exc:
        log.warning("snapshots.has_date(%s) failed: %s", as_of, exc)
        return False


def available_dates(limit: int = 30) -> list[str]:
    """Distinct as_of dates currently in the table, most recent first."""
    if not enabled():
        return []
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT as_of FROM daily_snapshot GROUP BY as_of "
                "ORDER BY as_of DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
        return [r[0].strftime("%Y-%m-%d") for r in rows]
    except Exception as exc:
        log.warning("snapshots.available_dates failed: %s", exc)
        return []


def date_counts(limit: int = 10) -> list[dict]:
    """Distinct as_of dates with their actual row counts, most recent
    first. Lets the UI report how many rows are *really* in the DB for a
    date, instead of last_written (which only reflects the latest run)."""
    if not enabled():
        return []
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT as_of, COUNT(*) FROM daily_snapshot GROUP BY as_of "
                "ORDER BY as_of DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
        return [{"date": r[0].strftime("%Y-%m-%d"), "rows": r[1]} for r in rows]
    except Exception as exc:
        log.warning("snapshots.date_counts failed: %s", exc)
        return []


_LOAD_COLS = (
    "ticker", "close", "prior_close", "volume", "avg_volume",
    "ema21", "ema50", "rsi14", "rsi14_prev", "rsi_sma9",
    "macd", "macd_prev", "macd_signal", "macd_hist", "macd_hist_prev",
    "shares", "recent_bars",
)


def iter_for_date(as_of: str, tickers: Iterable[str] | None = None, chunk: int = 500):
    """Stream rows for `as_of` one at a time via a server-side cursor.
    Yields (ticker, row_dict) tuples. Peak memory stays bounded to
    `chunk` rows regardless of how many match — the 7,800-row × ~5KB
    JSONB-per-row payload is ~35MB raw and ~100MB once parsed into
    Python dicts, which OOMs a 512MB Render worker if pulled into
    memory all at once via fetchall()."""
    if not enabled():
        return
    sql = (
        f"SELECT {', '.join(_LOAD_COLS)} FROM daily_snapshot "
        "WHERE as_of = %s"
    )
    args: list = [as_of]
    if tickers is not None:
        sql += " AND ticker = ANY(%s)"
        args.append(list(tickers))
    try:
        with _conn() as c:
            # name= triggers psycopg2's server-side cursor: rows are
            # fetched `itersize` at a time on demand, instead of the
            # entire result set being buffered client-side at execute().
            with c.cursor(name="snap_iter") as cur:
                cur.itersize = chunk
                cur.execute(sql, args)
                for r in cur:
                    d = dict(zip(_LOAD_COLS, r))
                    t = d.pop("ticker")
                    yield t, d
    except Exception as exc:
        log.warning("snapshots.iter_for_date(%s) failed: %s", as_of, exc)


_WRITE_COLS = (
    "ticker", "as_of", "close", "prior_close", "volume", "avg_volume",
    "ema21", "ema50", "rsi14", "rsi14_prev", "rsi_sma9",
    "macd", "macd_prev", "macd_signal", "macd_hist", "macd_hist_prev",
    "shares", "recent_bars",
)


def upsert_many(rows: list[dict]) -> int:
    """Bulk upsert. Returns count of rows submitted (Postgres doesn't tell
    us how many actually changed without RETURNING, which we skip)."""
    global _last_write_error
    if not enabled() or not rows:
        return 0
    from psycopg2.extras import execute_values

    def _pack(r: dict) -> tuple:
        out = []
        for col in _WRITE_COLS:
            v = r.get(col)
            if col == "recent_bars" and v is not None and not isinstance(v, str):
                v = json.dumps(v)
            out.append(v)
        return tuple(out)

    values = [_pack(r) for r in rows]
    update_set = ", ".join(
        f"{c}=EXCLUDED.{c}" for c in _WRITE_COLS if c not in ("ticker", "as_of")
    )
    sql = (
        f"INSERT INTO daily_snapshot ({', '.join(_WRITE_COLS)}) VALUES %s "
        f"ON CONFLICT (ticker, as_of) DO UPDATE SET {update_set}"
    )
    try:
        with _conn() as c, c.cursor() as cur:
            execute_values(cur, sql, values, page_size=500)
        _last_write_error = None
        return len(values)
    except Exception as exc:
        # Capture the first error verbatim so the UI can surface it.
        _last_write_error = f"{type(exc).__name__}: {exc}"
        log.warning("snapshots.upsert_many failed (%d rows): %s", len(values), exc)
        return 0


def last_write_error() -> str | None:
    return _last_write_error


def trim_to_last(n_dates: int = RETENTION_DAYS) -> int:
    """Delete rows whose as_of isn't among the most recent N distinct
    dates. Returns rows deleted."""
    if not enabled():
        return 0
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                "DELETE FROM daily_snapshot WHERE as_of NOT IN ("
                "  SELECT as_of FROM daily_snapshot GROUP BY as_of "
                "  ORDER BY as_of DESC LIMIT %s)",
                (n_dates,),
            )
            return cur.rowcount or 0
    except Exception as exc:
        log.warning("snapshots.trim_to_last failed: %s", exc)
        return 0
