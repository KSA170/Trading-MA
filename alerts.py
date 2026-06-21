"""
Realtime alert engine for Trading-MA.

Runs as a standalone script (see .github/workflows/alerts.yml) on a ~15-minute
cron during US market hours. It evaluates a set of *alert rules*, each
independently scoped:

  - watchlist  — the manually-curated ticker list (alert_watchlist table)
  - sector     — every stock in a yfinance sector  (e.g. "Healthcare")
  - industry   — every stock in a yfinance industry (e.g. "Biotechnology")

For each enabled rule it resolves the scope to a ticker list, fetches ~9
months of daily bars from Alpaca (the last bar is the in-progress trading
day, so indicators reflect the live price), evaluates each ticker with the
same screener.evaluate_ticker logic the web UI uses, and sends a Telegram
message per new match — deduped per (rule, ticker, day).

`python alerts.py`           runs one alert cycle.
`python alerts.py classify`  rebuilds the ticker -> sector/industry map
                             (slow; see .github/workflows/classify.yml).

Env vars (set as GitHub Actions secrets):
  DATABASE_URL         Postgres external URL (shared with the web app)
  ALPACA_API_KEY       Alpaca API key id
  ALPACA_SECRET_KEY    Alpaca API secret
  TELEGRAM_BOT_TOKEN   from @BotFather
  TELEGRAM_CHAT_ID     your chat id

Data caveat: Alpaca's free tier serves IEX-only data. Prices (and hence
RSI/EMA/MACD) are realtime and accurate. Volume is IEX-only — a fraction
of consolidated volume — so the relative-volume *ratio* is roughly
preserved but the absolute avg-volume floor is not; apply_avg_volume
defaults to False for alerts for that reason.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, time as dt_time

import pandas as pd
import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

import screener
import snapshots

log = logging.getLogger("alerts")

ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "").strip()
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "").strip()
ALPACA_DATA_URL = "https://data.alpaca.markets/v2"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Alert criteria default to the screener's defaults, with two changes:
# avg-volume floor off (IEX volume undercounts — see module docstring),
# and turnover off (no shares-outstanding feed in the alert path).
DEFAULT_ALERT_PARAMS: dict = {
    "high_lookback": 2,
    "streak_mode": "high",
    "rsi_min": 45.0, "rsi_max": 65.0,
    "rsi_dev_min_pct": 0.0, "rsi_dev_max_pct": 10.0,
    "rvol_lookback": 10, "rvol_min": 1.2,
    "avg_volume_min": 50000,
    "price_min": 1.0, "price_max": 1000.0,
    "price_dev_min_pct": -1.0, "price_dev_max_pct": 4.0,
    "ema_dev_min_pct": -3.0, "ema_dev_max_pct": 3.0,
    "macd_hist_min": 0.0, "macd_require_rising": True,
    "turnover_min_pct": 0.5, "turnover_max_pct": 100.0,
    "apply_high": True, "apply_rsi": True, "apply_rsi_dev": True,
    "apply_rvol": True, "apply_avg_volume": False,
    "apply_price": True, "apply_price_dev": True,
    "apply_ema_dev": True, "apply_macd": True,
    "apply_turnover": False,
}

# Only these keys are valid kwargs for screener.evaluate_ticker.
_PARAM_KEYS = frozenset(DEFAULT_ALERT_PARAMS.keys())

# Setup-type rules run pattern_scan.scan_setups against the daily snapshot
# instead of evaluate_ticker on live bars. Their params drive scan_setups.
SETUP_DEFAULT_PARAMS: dict = {
    "score_min": 70.0,
    "min_price": 3.0,
    "max_price": 1000.0,
    "min_dollar_vol": 1_000_000.0,
}
_SETUP_PARAM_KEYS = frozenset(SETUP_DEFAULT_PARAMS.keys())

RULE_TYPES = ("screener", "setup")
# 'all' is a setup-only scope ("score every ticker the snapshot pre-filter
# returns") — using it with a screener rule would blow up Alpaca quota.
SCOPE_TYPES = ("watchlist", "sector", "industry", "all")


# --- schema ----------------------------------------------------------------

_ALERT_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_watchlist (
    ticker   TEXT PRIMARY KEY,
    added_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS alert_config (
    id         INT PRIMARY KEY,
    params     JSONB,
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ticker_sector (
    ticker        TEXT PRIMARY KEY,
    sector        TEXT,
    industry      TEXT,
    classified_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ticker_sector_industry_idx ON ticker_sector (industry);
CREATE INDEX IF NOT EXISTS ticker_sector_sector_idx ON ticker_sector (sector);
CREATE TABLE IF NOT EXISTS alert_rules (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    scope_type  TEXT NOT NULL,
    scope_value TEXT NOT NULL DEFAULT '',
    rule_type   TEXT NOT NULL DEFAULT 'screener',
    params      JSONB,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE alert_rules
    ADD COLUMN IF NOT EXISTS rule_type TEXT NOT NULL DEFAULT 'screener';
CREATE TABLE IF NOT EXISTS alert_sent (
    rule_id      INT  NOT NULL,
    ticker       TEXT NOT NULL,
    trigger_date DATE NOT NULL,
    detail       TEXT,
    sent_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (rule_id, ticker, trigger_date)
);
CREATE TABLE IF NOT EXISTS rule_run_stats (
    rule_id     INT PRIMARY KEY,
    last_run_at TIMESTAMPTZ,
    scope       INT NOT NULL DEFAULT 0,
    evaluated   INT NOT NULL DEFAULT 0,
    matched     INT NOT NULL DEFAULT 0,
    deduped     INT NOT NULL DEFAULT 0,
    no_data     INT NOT NULL DEFAULT 0,
    errors      INT NOT NULL DEFAULT 0
);
"""


def enabled() -> bool:
    """The alert layer needs Postgres; everything else degrades to a no-op."""
    return snapshots.enabled()


def init_tables() -> None:
    """Idempotent CREATE TABLE for the alert tables. Also migrates a
    pre-existing watchlist setup into a default 'Watchlist' rule so
    alerts configured before the multi-rule change keep working."""
    if not enabled():
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(_ALERT_SCHEMA)
            cur.execute("SELECT COUNT(*) FROM alert_rules")
            if (cur.fetchone()[0] or 0) == 0:
                params = dict(DEFAULT_ALERT_PARAMS)
                # Inherit the old single-config criteria if present.
                try:
                    cur.execute("SELECT params FROM alert_config WHERE id = 1")
                    row = cur.fetchone()
                    if row and row[0]:
                        stored = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                        for k, v in stored.items():
                            if k in _PARAM_KEYS:
                                params[k] = v
                except Exception:
                    pass
                cur.execute(
                    "INSERT INTO alert_rules (name, scope_type, scope_value, "
                    "params, enabled) VALUES (%s, 'watchlist', '', %s, TRUE)",
                    ("Watchlist", json.dumps(params)),
                )
                log.info("alerts: migrated existing setup into a 'Watchlist' rule")
    except Exception as exc:
        log.warning("alerts: init_tables failed: %s", exc)


def _clean_params(raw: dict | None, rule_type: str = "screener") -> dict:
    """Keep only the params that apply to this rule type, filling gaps
    with that type's defaults. Setup rules carry score_min + price /
    dollar-volume band; screener rules carry the evaluate_ticker kwargs."""
    if rule_type == "setup":
        params = dict(SETUP_DEFAULT_PARAMS)
        for k, v in (raw or {}).items():
            if k in _SETUP_PARAM_KEYS:
                params[k] = v
        return params
    params = dict(DEFAULT_ALERT_PARAMS)
    for k, v in (raw or {}).items():
        if k in _PARAM_KEYS:
            params[k] = v
    return params


# --- watchlist -------------------------------------------------------------

def get_watchlist() -> list[str]:
    if not enabled():
        return []
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("SELECT ticker FROM alert_watchlist ORDER BY ticker")
            return [r[0] for r in cur.fetchall()]
    except Exception as exc:
        log.warning("alerts: get_watchlist failed: %s", exc)
        return []


def add_to_watchlist(tickers: list[str]) -> int:
    clean = sorted({t.strip().upper() for t in tickers if t and t.strip()})
    if not enabled() or not clean:
        return 0
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.executemany(
                "INSERT INTO alert_watchlist (ticker) VALUES (%s) "
                "ON CONFLICT (ticker) DO NOTHING",
                [(t,) for t in clean],
            )
        return len(clean)
    except Exception as exc:
        log.warning("alerts: add_to_watchlist failed: %s", exc)
        return 0


def remove_from_watchlist(ticker: str) -> bool:
    if not enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM alert_watchlist WHERE ticker = %s",
                        (ticker.strip().upper(),))
            return (cur.rowcount or 0) > 0
    except Exception as exc:
        log.warning("alerts: remove_from_watchlist failed: %s", exc)
        return False


# --- alert rules -----------------------------------------------------------

def rules_with_last_trigger() -> dict:
    """For every rule with at least one alert sent, return the most
    recent trigger event (per-minute grouping — one alerts.py run sends
    its matches within a single minute, so per-minute is one trigger).
    Returns {rule_id: (datetime, match_count)}."""
    if not enabled():
        return {}
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            # Two-step: find each rule's latest minute, then count rows
            # at that minute. Using MAX() explicitly (rather than
            # DISTINCT ON + ORDER BY) avoids the subtle ordering
            # gotchas the latter has when rows have identical timestamps
            # or NULL sent_at values.
            cur.execute(
                "SELECT m.rule_id, m.last_minute, "
                "       (SELECT COUNT(*)::int FROM alert_sent a "
                "        WHERE a.rule_id = m.rule_id "
                "          AND date_trunc('minute', a.sent_at) = m.last_minute) "
                "FROM ("
                "  SELECT rule_id, MAX(date_trunc('minute', sent_at)) AS last_minute "
                "  FROM alert_sent "
                "  WHERE sent_at IS NOT NULL "
                "  GROUP BY rule_id"
                ") m"
            )
            rows = cur.fetchall()
        return {r[0]: (r[1], int(r[2])) for r in rows}
    except Exception as exc:
        log.warning("alerts: rules_with_last_trigger failed: %s", exc)
        return {}


def rule_last_run_stats() -> dict:
    """Latest run stats per rule — explains "why didn't this rule fire?"
    (it scanned N tickers and matched 0). {rule_id: {scope, ...}}."""
    if not enabled():
        return {}
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT rule_id, last_run_at, scope, evaluated, matched, "
                "deduped, no_data, errors FROM rule_run_stats"
            )
            rows = cur.fetchall()
        return {
            r[0]: {
                "last_run_at": r[1].isoformat() if r[1] else None,
                "scope": int(r[2]), "evaluated": int(r[3]),
                "matched": int(r[4]), "deduped": int(r[5]),
                "no_data": int(r[6]), "errors": int(r[7]),
            }
            for r in rows
        }
    except Exception as exc:
        log.warning("alerts: rule_last_run_stats failed: %s", exc)
        return {}


def _record_rule_run_stats(stats_list: list[dict]) -> None:
    """Upsert the per-rule scan stats from this run. One row per rule —
    overwrites the previous run's stats, so the UI always shows the
    most recent scan."""
    if not enabled() or not stats_list:
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            for s in stats_list:
                cur.execute(
                    "INSERT INTO rule_run_stats (rule_id, last_run_at, "
                    "scope, evaluated, matched, deduped, no_data, errors) "
                    "VALUES (%s, now(), %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (rule_id) DO UPDATE SET "
                    "last_run_at = now(), scope = EXCLUDED.scope, "
                    "evaluated = EXCLUDED.evaluated, matched = EXCLUDED.matched, "
                    "deduped = EXCLUDED.deduped, no_data = EXCLUDED.no_data, "
                    "errors = EXCLUDED.errors",
                    (s["rule_id"], s["scope"], s["evaluated"],
                     s["matched"], s["deduped"], s["no_data"], s["errors"]),
                )
    except Exception as exc:
        log.warning("alerts: _record_rule_run_stats failed: %s", exc)


def rule_trigger_history(rule_id: int, limit: int = 20) -> list[dict]:
    """Recent trigger events for a single rule, newest first. Each event
    is the per-minute aggregation of alert_sent rows for that rule."""
    if not enabled():
        return []
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT date_trunc('minute', sent_at) AS t, COUNT(*)::int "
                "FROM alert_sent WHERE rule_id = %s "
                "GROUP BY t ORDER BY t DESC LIMIT %s",
                (int(rule_id), int(limit)),
            )
            rows = cur.fetchall()
        return [
            {"triggered_at": r[0].isoformat() if r[0] else None,
             "match_count": int(r[1])}
            for r in rows
        ]
    except Exception as exc:
        log.warning("alerts: rule_trigger_history failed: %s", exc)
        return []


def list_rules(enabled_only: bool = False) -> list[dict]:
    if not enabled():
        return []
    sql = ("SELECT id, name, scope_type, scope_value, params, enabled, "
           "rule_type FROM alert_rules")
    if enabled_only:
        sql += " WHERE enabled = TRUE"
    sql += " ORDER BY id"
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception as exc:
        log.warning("alerts: list_rules failed: %s", exc)
        return []
    latest = rules_with_last_trigger()
    stats = rule_last_run_stats()
    out = []
    for r in rows:
        params = r[4] if isinstance(r[4], dict) else (json.loads(r[4]) if r[4] else {})
        rule_type = r[6] or "screener"
        ts, cnt = latest.get(r[0], (None, 0))
        s = stats.get(r[0], {})
        out.append({
            "id": r[0], "name": r[1], "scope_type": r[2],
            "scope_value": r[3], "rule_type": rule_type,
            "params": _clean_params(params, rule_type),
            "enabled": bool(r[5]),
            "last_triggered_at": ts.isoformat() if ts is not None else None,
            "last_match_count": cnt,
            # Last scan stats — explains "scanned but no match" cases.
            "last_run_at": s.get("last_run_at"),
            "scan_scope": s.get("scope", 0),
            "scan_evaluated": s.get("evaluated", 0),
            "scan_matched": s.get("matched", 0),
            "scan_deduped": s.get("deduped", 0),
            "scan_no_data": s.get("no_data", 0),
            "scan_errors": s.get("errors", 0),
        })
    return out


def add_rule(name: str, scope_type: str, scope_value: str, params: dict,
             rule_type: str = "screener") -> int | None:
    name = (name or "").strip()
    scope_type = (scope_type or "").strip().lower()
    scope_value = (scope_value or "").strip()
    rule_type = (rule_type or "screener").strip().lower()
    if not enabled() or not name or scope_type not in SCOPE_TYPES:
        return None
    if rule_type not in RULE_TYPES:
        return None
    # 'all' is setup-only; setup rules accept watchlist/sector/industry/all.
    if scope_type == "all" and rule_type != "setup":
        return None
    if scope_type in ("sector", "industry") and not scope_value:
        return None
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO alert_rules (name, scope_type, scope_value, "
                "rule_type, params, enabled) VALUES (%s, %s, %s, %s, %s, TRUE) "
                "RETURNING id",
                (name, scope_type, scope_value, rule_type,
                 json.dumps(_clean_params(params, rule_type))),
            )
            return cur.fetchone()[0]
    except Exception as exc:
        log.warning("alerts: add_rule failed: %s", exc)
        return None


def delete_rule(rule_id: int) -> bool:
    if not enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM alert_rules WHERE id = %s", (int(rule_id),))
            return (cur.rowcount or 0) > 0
    except Exception as exc:
        log.warning("alerts: delete_rule failed: %s", exc)
        return False


def set_rule_enabled(rule_id: int, is_enabled: bool) -> bool:
    if not enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("UPDATE alert_rules SET enabled = %s WHERE id = %s",
                        (bool(is_enabled), int(rule_id)))
            return (cur.rowcount or 0) > 0
    except Exception as exc:
        log.warning("alerts: set_rule_enabled failed: %s", exc)
        return False


def set_rule_params(rule_id: int, params: dict) -> bool:
    if not enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            # Read rule_type so we apply the correct param filter on update.
            cur.execute("SELECT rule_type FROM alert_rules WHERE id = %s",
                        (int(rule_id),))
            row = cur.fetchone()
            if not row:
                return False
            rule_type = row[0] or "screener"
            cur.execute("UPDATE alert_rules SET params = %s WHERE id = %s",
                        (json.dumps(_clean_params(params, rule_type)),
                         int(rule_id)))
            return (cur.rowcount or 0) > 0
    except Exception as exc:
        log.warning("alerts: set_rule_params failed: %s", exc)
        return False


# --- sector / industry map -------------------------------------------------

def tickers_for_scope(scope_type: str, scope_value: str) -> list[str] | None:
    """Resolve a rule's scope to a concrete ticker list. Returns None for
    scope_type='all' (setup-only, means "no scope filter — score every
    ticker the setup pre-filter SQL returns")."""
    if scope_type == "all":
        return None
    if scope_type == "watchlist":
        return get_watchlist()
    if scope_type not in ("sector", "industry") or not enabled():
        return []
    col = "sector" if scope_type == "sector" else "industry"
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                f"SELECT ticker FROM ticker_sector WHERE {col} = %s ORDER BY ticker",
                (scope_value,),
            )
            return [r[0] for r in cur.fetchall()]
    except Exception as exc:
        log.warning("alerts: tickers_for_scope failed: %s", exc)
        return []


def list_scopes() -> dict:
    """Distinct sectors and industries (with member counts) for the UI
    rule-builder dropdowns."""
    out = {"sectors": [], "industries": []}
    if not enabled():
        return out
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT sector, COUNT(*) FROM ticker_sector "
                "WHERE sector IS NOT NULL AND sector <> '' "
                "GROUP BY sector ORDER BY sector")
            out["sectors"] = [{"name": r[0], "count": r[1]} for r in cur.fetchall()]
            cur.execute(
                "SELECT industry, COUNT(*) FROM ticker_sector "
                "WHERE industry IS NOT NULL AND industry <> '' "
                "GROUP BY industry ORDER BY industry")
            out["industries"] = [{"name": r[0], "count": r[1]} for r in cur.fetchall()]
    except Exception as exc:
        log.warning("alerts: list_scopes failed: %s", exc)
    return out


def classification_status() -> dict:
    """How much of the universe has a sector/industry tag."""
    if not enabled():
        return {"enabled": False, "classified": 0, "last_classified_at": None}
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute("SELECT COUNT(*), MAX(classified_at) FROM ticker_sector")
            row = cur.fetchone()
        return {
            "enabled": True,
            "classified": row[0] or 0,
            "last_classified_at": row[1].isoformat() if row[1] else None,
        }
    except Exception as exc:
        log.warning("alerts: classification_status failed: %s", exc)
        return {"enabled": True, "classified": 0, "last_classified_at": None}


def classify_universe(max_workers: int = 8) -> dict:
    """Rebuild the ticker -> sector/industry map from yfinance industry
    data. Slow (~30-40 min for the full universe) and a bit flaky — run
    weekly via .github/workflows/classify.yml. Partial failures are
    fine; a re-run fills the gaps."""
    if not enabled():
        return {"enabled": False}
    import yfinance as yf
    from psycopg2.extras import execute_values
    from tickers import all_tickers

    tk = all_tickers()
    log.info("classify: fetching sector/industry for %d tickers", len(tk))

    def _one(t: str):
        try:
            info = yf.Ticker(t).info or {}
            return (t, info.get("sector"), info.get("industry"))
        except Exception:
            return (t, None, None)

    rows: list[tuple] = []
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for t, sector, industry in pool.map(_one, tk):
            done += 1
            if sector or industry:
                rows.append((t, sector or None, industry or None))
            if done % 1000 == 0:
                log.info("classify: %d/%d processed, %d tagged", done, len(tk), len(rows))

    written = 0
    if rows:
        try:
            with snapshots._conn() as c, c.cursor() as cur:
                execute_values(
                    cur,
                    "INSERT INTO ticker_sector (ticker, sector, industry) VALUES %s "
                    "ON CONFLICT (ticker) DO UPDATE SET sector = EXCLUDED.sector, "
                    "industry = EXCLUDED.industry, classified_at = now()",
                    rows, page_size=500,
                )
            written = len(rows)
        except Exception as exc:
            log.warning("classify: upsert failed: %s", exc)
    log.info("classify complete: %d/%d tickers tagged", written, len(tk))
    return {"enabled": True, "tagged": written, "total": len(tk)}


# --- dedup state -----------------------------------------------------------

def already_sent(rule_id: int, ticker: str, trigger_date: str) -> bool:
    if not enabled():
        return False
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM alert_sent WHERE rule_id = %s AND ticker = %s "
                "AND trigger_date = %s",
                (rule_id, ticker, trigger_date),
            )
            return cur.fetchone() is not None
    except Exception as exc:
        log.warning("alerts: already_sent failed: %s", exc)
        return False


def record_sent(rule_id: int, ticker: str, trigger_date: str, detail: str) -> None:
    if not enabled():
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO alert_sent (rule_id, ticker, trigger_date, detail) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (rule_id, ticker, trigger_date) DO NOTHING",
                (rule_id, ticker, trigger_date, detail),
            )
    except Exception as exc:
        log.warning("alerts: record_sent failed: %s", exc)


# --- Alpaca market data ----------------------------------------------------

def _alpaca_bars_request(batch: list[str], start: str, headers: dict) -> dict[str, list]:
    """Fetch daily bars for `batch` from Alpaca, following pagination.
    On a 4xx/5xx, recursively split the batch in half and retry — this
    adapts automatically to Alpaca's per-request symbol cap and isolates
    a single rejected symbol so it doesn't sink the rest of the batch.
    Returns {symbol: [bar, ...]} keyed by the caller's original symbols."""
    out: dict[str, list] = {}
    # The SEC universe writes share classes with a hyphen (BRK-B);
    # Alpaca expects a dot (BRK.B). Translate for the request, then map
    # the response keys back to the caller's original symbols.
    req_for = {s: s.replace("-", ".") for s in batch}
    orig_for = {a: s for s, a in req_for.items()}
    page_token = None
    while True:
        params = {
            "symbols": ",".join(req_for[s] for s in batch),
            "timeframe": "1Day",
            "start": start,
            "limit": 10000,
            "feed": "iex",
            "adjustment": "raw",
        }
        if page_token:
            params["page_token"] = page_token
        try:
            resp = requests.get(f"{ALPACA_DATA_URL}/stocks/bars",
                                headers=headers, params=params, timeout=30)
        except Exception as exc:
            log.warning("alerts: Alpaca request error (%d symbols): %s",
                        len(batch), exc)
            return out
        if resp.status_code >= 400:
            body = (resp.text or "").strip().replace("\n", " ")[:160]
            if len(batch) > 1:
                # Too many symbols for one request, or one bad symbol in
                # the batch — split in half and retry each side.
                log.info("alerts: Alpaca HTTP %d on %d-symbol batch — "
                         "splitting (%s)", resp.status_code, len(batch), body)
                mid = len(batch) // 2
                merged = _alpaca_bars_request(batch[:mid], start, headers)
                merged.update(_alpaca_bars_request(batch[mid:], start, headers))
                return merged
            log.warning("alerts: Alpaca dropped %s — HTTP %d (%s)",
                        batch[0], resp.status_code, body)
            return out
        data = resp.json()
        for sym, bars in (data.get("bars") or {}).items():
            out.setdefault(orig_for.get(sym, sym), []).extend(bars)
        page_token = data.get("next_page_token")
        if not page_token:
            break
    return out


def fetch_daily_bars(symbols: list[str], lookback_days: int = 270,
                     chunk: int = 50) -> dict[str, pd.DataFrame]:
    """Fetch daily OHLCV bars for `symbols` from Alpaca. The most recent
    bar is the current (in-progress) trading day, so downstream
    indicators reflect the live price. Symbols are requested in chunks;
    _alpaca_bars_request splits any chunk Alpaca rejects."""
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY) or not symbols:
        return {}
    start = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    collected: dict[str, list] = {}
    for i in range(0, len(symbols), chunk):
        collected.update(_alpaca_bars_request(symbols[i:i + chunk], start, headers))
    frames: dict[str, pd.DataFrame] = {}
    for sym, bars in collected.items():
        if not bars:
            continue
        df = pd.DataFrame(bars)
        if df.empty or "c" not in df.columns:
            continue
        df["t"] = pd.to_datetime(df["t"])
        df = df.set_index("t").sort_index()
        df = df.rename(columns={"o": "Open", "h": "High", "l": "Low",
                                "c": "Close", "v": "Volume"})
        keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
        frames[sym] = df[keep].astype("float32")
    return frames


# --- Telegram --------------------------------------------------------------

def send_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        missing = "TELEGRAM_BOT_TOKEN" if not TELEGRAM_BOT_TOKEN else "TELEGRAM_CHAT_ID"
        log.warning("alerts: Telegram not configured — the %s secret is missing", missing)
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
    except Exception as exc:
        log.warning("alerts: Telegram request error: %s", exc)
        return False
    if resp.status_code >= 400:
        # Telegram's error body carries a "description" (e.g. "chat not
        # found", "Unauthorized") — log it verbatim so the cause is clear.
        body = (resp.text or "").strip().replace("\n", " ")[:200]
        log.warning("alerts: Telegram rejected the message — HTTP %d: %s",
                    resp.status_code, body)
        return False
    return True


def _format_alert(rule_name: str, hit, as_of: datetime) -> str:
    return (
        f"<b>[{rule_name}]</b>\n"
        f"<b>{hit.ticker}</b> — {hit.name}\n"
        f"Price ${hit.close:.2f} ({hit.pct_change:+.2f}%)\n"
        f"Momentum {hit.momentum_score:.0f}/100\n"
        f"RSI {hit.rsi:.1f} | MACD hist {hit.macd_hist:+.3f} | "
        f"RVol {hit.rel_volume:.2f}x\n"
        f"Matched alert criteria — market data as of "
        f"{as_of.strftime('%Y-%m-%d %H:%M')} ET"
    )


def _format_setup_alert(rule_name: str, result: dict, snapshot_date: str) -> str:
    """Telegram body for a setup-rule trigger. Surfaces the three
    sub-scores (base / ignition / earliness) which together explain
    *why* the overall setup score is what it is."""
    return (
        f"<b>[{rule_name}]</b>  Setup\n"
        f"<b>{result['ticker']}</b> — {result.get('name', '')}\n"
        f"Setup score <b>{result['score']:.0f}</b>/100  "
        f"(base {result['base_quality']*100:.0f} · "
        f"ign {result['ignition']*100:.0f} · "
        f"early {result['earliness']*100:.0f})\n"
        f"Price ${result['close']:.2f}\n"
        f"Snapshot {snapshot_date}"
    )


# --- market clock ----------------------------------------------------------

def _now_et() -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            pass
    return datetime.utcnow() - timedelta(hours=4)


def market_is_open(now: datetime | None = None) -> bool:
    """US regular session, weekdays 9:30am-4:00pm ET. Does not account
    for market holidays — a holiday just yields zero fresh bars, so the
    worst case is a wasted run, not a wrong alert."""
    now = now or _now_et()
    if now.weekday() >= 5:
        return False
    return dt_time(9, 30) <= now.time() <= dt_time(16, 0)


# --- main loop -------------------------------------------------------------

def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Manual-run toggles (workflow_dispatch inputs, passed as env vars).
    # Empty for scheduled runs.
    force_run = os.environ.get("ALERT_FORCE_RUN", "").strip().lower() in ("true", "1", "yes")
    test_telegram = os.environ.get("ALERT_TEST_TELEGRAM", "").strip().lower() in ("true", "1", "yes")

    # "Test Telegram" toggle — proves the bot token + chat id + delivery
    # work, independent of rules / Alpaca / whether anything matches.
    if test_telegram:
        ts = _now_et().strftime("%Y-%m-%d %H:%M ET")
        ok = send_telegram(
            "<b>Trading-MA</b>\nAlert engine test — Telegram delivery is "
            f"working.\nSent {ts}."
        )
        log.info("test Telegram message: %s", "sent OK" if ok else "FAILED")
        return 0 if ok else 1

    if not enabled():
        log.error("DATABASE_URL not set — cannot run alerts")
        return 1
    init_tables()

    now = _now_et()
    if not market_is_open(now):
        if not force_run:
            log.info("market closed (%s ET) — skipping", now.strftime("%a %H:%M"))
            return 0
        log.info("force_run: market closed (%s ET) — evaluating anyway on the "
                 "most recent available bars", now.strftime("%a %H:%M"))

    rules = list_rules(enabled_only=True)
    if not rules:
        log.info("no enabled alert rules — nothing to evaluate")
        return 0

    screener_rules = [r for r in rules if r.get("rule_type") != "setup"]
    setup_rules = [r for r in rules if r.get("rule_type") == "setup"]

    triggered_screener: list[tuple[dict, str, object]] = []   # (rule, ticker, hit)
    triggered_setup: list[tuple[dict, dict]] = []             # (rule, result)
    stats_list: list[dict] = []
    today = now.strftime("%Y-%m-%d")

    # --- screener-type rules (Alpaca-driven, existing path) ---------------
    if screener_rules:
        if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
            log.error("ALPACA_API_KEY / ALPACA_SECRET_KEY not set — "
                      "skipping screener rules")
        else:
            # Resolve every rule's scope, then fetch the union of tickers
            # once so overlapping rules don't double-fetch.
            rule_tickers: dict[int, list[str]] = {}
            universe: set[str] = set()
            for rule in screener_rules:
                ts = tickers_for_scope(rule["scope_type"], rule["scope_value"]) or []
                rule_tickers[rule["id"]] = ts
                universe.update(ts)
            if universe:
                log.info("evaluating %d screener rule(s) over %d distinct tickers",
                         len(screener_rules), len(universe))
                frames = fetch_daily_bars(sorted(universe))
                for rule in screener_rules:
                    rule_tk = rule_tickers[rule["id"]]
                    scope_n = len(rule_tk)
                    ev = de = nd = er = mt = 0
                    for ticker in rule_tk:
                        if already_sent(rule["id"], ticker, today):
                            de += 1
                            continue
                        df = frames.get(ticker)
                        if df is None or len(df) < 40:
                            nd += 1
                            continue
                        ev += 1
                        try:
                            enriched = screener._enrich(df.copy())
                            screener._PRICE_CACHE[ticker] = (time.time(), enriched)
                            hit = screener.evaluate_ticker(ticker, **rule["params"])
                        except Exception as exc:
                            log.warning("evaluate failed for %s (rule %s): %s",
                                        ticker, rule["id"], exc)
                            er += 1
                            continue
                        if hit is not None:
                            mt += 1
                            triggered_screener.append((rule, ticker, hit))
                    log.info(
                        'rule %d "%s" (screener %s%s): scope=%d evaluated=%d '
                        'matched=%d deduped=%d no_data=%d errors=%d',
                        rule["id"], rule["name"], rule["scope_type"],
                        (":" + rule["scope_value"]) if rule["scope_value"] else "",
                        scope_n, ev, mt, de, nd, er,
                    )
                    stats_list.append({
                        "rule_id": rule["id"], "scope": scope_n, "evaluated": ev,
                        "matched": mt, "deduped": de, "no_data": nd, "errors": er,
                    })
            else:
                log.info("screener rules resolved to 0 tickers — skipping")

    # --- setup-type rules (snapshot-driven, no Alpaca dependency) ---------
    snapshot_as_of: str | None = None
    if setup_rules:
        import pattern_scan
        available = snapshots.available_dates(1)
        if not available:
            log.info("setup rules: no snapshot rows yet — skipping")
        else:
            snapshot_as_of = available[0]
            for rule in setup_rules:
                p = rule["params"]
                scope_filter = tickers_for_scope(rule["scope_type"], rule["scope_value"])
                # scope_filter is None for 'all'; a list (possibly empty)
                # for watchlist/sector/industry.
                if scope_filter is not None and not scope_filter:
                    log.info('rule %d "%s" (setup): scope resolved to 0 tickers — skipping',
                             rule["id"], rule["name"])
                    stats_list.append({
                        "rule_id": rule["id"], "scope": 0, "evaluated": 0,
                        "matched": 0, "deduped": 0, "no_data": 0, "errors": 0,
                    })
                    continue
                scope_set = set(scope_filter) if scope_filter is not None else None
                try:
                    results = pattern_scan.scan_setups(
                        snapshot_as_of,
                        min_score=float(p.get("score_min", 70.0)),
                        limit=10_000,
                        min_price=float(p.get("min_price", 3.0)),
                        max_price=float(p.get("max_price", 1000.0)),
                        min_dollar_vol=float(p.get("min_dollar_vol", 1_000_000.0)),
                    )
                except Exception as exc:
                    log.warning("setup rule %d scan failed: %s", rule["id"], exc)
                    results = []
                if scope_set is not None:
                    results = [r for r in results if r.get("ticker") in scope_set]
                de = mt = 0
                for res in results:
                    ticker = res.get("ticker")
                    if not ticker:
                        continue
                    if already_sent(rule["id"], ticker, today):
                        de += 1
                        continue
                    mt += 1
                    triggered_setup.append((rule, res))
                scope_n = len(scope_filter) if scope_filter is not None else len(results) + de
                log.info(
                    'rule %d "%s" (setup %s%s): scope=%d matched=%d deduped=%d',
                    rule["id"], rule["name"], rule["scope_type"],
                    (":" + rule["scope_value"]) if rule["scope_value"] else "",
                    scope_n, mt, de,
                )
                stats_list.append({
                    "rule_id": rule["id"], "scope": scope_n,
                    "evaluated": mt + de, "matched": mt, "deduped": de,
                    "no_data": 0, "errors": 0,
                })

    _record_rule_run_stats(stats_list)

    if not triggered_screener and not triggered_setup:
        log.info("no new alerts this run")
        return 0

    sent = 0
    import outcomes
    for rule, ticker, hit in triggered_screener:
        if send_telegram(_format_alert(rule["name"], hit, now)):
            record_sent(rule["id"], ticker, today,
                        f"momentum={hit.momentum_score}")
            outcomes.record_stock_outcome(
                ticker, today, getattr(hit, "close", None),
                {"kind": "alert_screener", "id": rule["id"],
                 "label": rule.get("name") or "Screener alert"},
            )
            sent += 1
    for rule, res in triggered_setup:
        if send_telegram(_format_setup_alert(rule["name"], res, snapshot_as_of or today)):
            record_sent(rule["id"], res["ticker"], today,
                        f"setup_score={res.get('score')}")
            outcomes.record_stock_outcome(
                res["ticker"], today, res.get("close"),
                {"kind": "alert_setup", "id": rule["id"],
                 "label": rule.get("name") or "Setup alert"},
            )
            sent += 1
    total = len(triggered_screener) + len(triggered_setup)
    log.info("alerts: %d triggered, %d sent to Telegram", total, sent)
    return 0


def classify_main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not enabled():
        log.error("DATABASE_URL not set — cannot classify")
        return 1
    init_tables()
    result = classify_universe()
    log.info("classify result: %s", result)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "classify":
        raise SystemExit(classify_main())
    raise SystemExit(run())
