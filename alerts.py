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
    "turnover_min_pct": 0.5, "turnover_max_pct": 100.0,
    "apply_high": True, "apply_rsi": True, "apply_rsi_dev": True,
    "apply_rvol": True, "apply_avg_volume": False,
    "apply_price": True, "apply_price_dev": True,
    "apply_ema_dev": True,
    # Standalone SMA-trend deviation gates (off by default).
    "apply_price_sma10_dev": False,
    "price_sma10_dev_min_pct": -3.0, "price_sma10_dev_max_pct": 5.0,
    "apply_sma10_sma20_dev": False,
    "sma10_sma20_dev_min_pct": -2.0, "sma10_sma20_dev_max_pct": 4.0,
    "apply_turnover": False,
    # Latest-bar % gain.
    "apply_pct_change": False, "pct_change_min": 5.0,
    # MACD vs signal line — 5 knobs (gate + 4 sub-conditions).
    "apply_macd_vs_signal": False,
    "macd_within_pct": True, "macd_vs_signal_pct": 5.0,
    "macd_above_signal": False, "macd_line_rising": False,
    # Market cap filter — input is $M.
    "apply_market_cap": False,
    "market_cap_min_m": 0.0, "market_cap_max_m": 10_000_000.0,
    # SMA Revival (10-SMA turn-up + price cross). Defaults match
    # app.py:DEFAULT_PARAMS and screener.evaluate_ticker so a rule
    # created with the filter toggled on but other knobs untouched
    # behaves the same as the same screen in the main UI.
    "apply_sma_revival": False,
    "sma_cross_lookback": 3,
    "sma_slope_turn_lookback": 5,
    "sma_slope_window": 3,
    "sma_min_slope_pct": 0.10,
    "sma_require_long_flat": False,
    "sma_long_flat_max_pct": 0.30,
    "sma_require_volume": False,
    "sma_volume_mult": 1.20,
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
    # Per-sub-score floors (0–100). Default 0 = off. AND-stack with
    # score_min so a setup must clear BOTH the composite and any
    # sub-score floors the user set.
    "base_min": 0.0,
    "ignition_min": 0.0,
    "earliness_min": 0.0,
}
_SETUP_PARAM_KEYS = frozenset(SETUP_DEFAULT_PARAMS.keys())

# Stoch-type rules watch the stochastic oscillator on intraday bars
# (Yahoo via calculators.fetch_bars) and fire on the oversold-bounce
# signature. Built for small, hand-curated scopes (the watchlist) —
# every ticker costs one Yahoo intraday fetch per run.
STOCH_DEFAULT_PARAMS: dict = {
    "interval": "5m",
    "k_len": 14,
    "smooth": 3,
    "oversold": 20.0,
    "overbought": 80.0,
    # trigger — bullish (call-side) and bearish (put-side) mirrors:
    #   curl_up            — Slow %K visited oversold within
    #                        `lookback_bars` and has now turned up with
    #                        Fast %K leading (the validated dip-buy
    #                        signature).
    #   entered_oversold   — Slow %K crossed down into oversold on the
    #                        latest bar (earliest heads-up, pre-turn).
    #   curl_down          — Slow %K visited overbought within the
    #                        lookback and has turned down with Fast %K
    #                        leading lower (the put-side rollover).
    #   entered_overbought — Slow %K crossed up into overbought on the
    #                        latest bar.
    "trigger": "curl_up",
    "lookback_bars": 4,
    # Episode re-arm: after an alert fires for a ticker, no new alert
    # until Slow %K has crossed this level on a later bar (>= for the
    # call side — the bounce played out; <= for the put side). Each
    # swing episode alerts once, and a fresh setup the same day alerts
    # again — unlike the one-per-day dedupe the other rule types use.
    # 50 = the midline.
    "rearm_level": 50.0,
    # Stop placement: the stop-loss price sits this % BEYOND the
    # stays-oversold boundary (below it for calls, above the
    # stays-overbought ceiling for puts). The validated trades placed
    # stops just past the band — at the boundary itself, a normal
    # oversold flush tags the stop on the low tick of a winning trade.
    # 0 = stop exactly at the boundary.
    "stop_buffer_pct": 0.15,
    # Option-math framing for the alert body: estimated per-position
    # P&L at the target / risk levels via the linear delta
    # approximation (gain ≈ Δ × move × 100 × contracts). Delta is the
    # magnitude of the contract you intend to trade (calls or puts) —
    # also the target for the contract recommendation below.
    "opt_delta": 0.35,
    "opt_contracts": 1,
    # Contract recommendation: when the rule fires, pick the liquid
    # contract closest to opt_delta inside this DTE window (the
    # validated trades used 2-4 DTE). The pick's REAL delta then
    # replaces the assumed one in the P&L estimate.
    "opt_dte_min": 2,
    "opt_dte_max": 6,
}
_STOCH_PARAM_KEYS = frozenset(STOCH_DEFAULT_PARAMS.keys())
_STOCH_INTERVALS = ("1m", "5m", "15m", "30m", "1h", "1d")
_STOCH_TRIGGERS = ("curl_up", "entered_oversold",
                   "curl_down", "entered_overbought")
_STOCH_BEARISH_TRIGGERS = ("curl_down", "entered_overbought")

# Technical rules: RSI / MACD / price-streak conditions AND-ed together on
# any interval. Params + condition math live in technicals.py.
import technicals

TECHNICAL_DEFAULT_PARAMS: dict = dict(technicals.DEFAULT_PARAMS)
_TECHNICAL_PARAM_KEYS = frozenset(TECHNICAL_DEFAULT_PARAMS.keys())
# Daily+ rules evaluate the last CLOSED bar (a partial session would fire
# alerts that are false by the close); intraday uses the latest bar.
_TECH_CLOSED_ONLY_INTERVALS = ("1d", "1wk", "1mo")

RULE_TYPES = ("screener", "setup", "stoch", "technical")
# 'all' is a setup-only scope ("score every ticker the snapshot pre-filter
# returns") — using it with a screener rule would blow up Alpaca quota,
# and with a stoch rule the per-ticker Yahoo fetches.
# 'tickers' is a hand-typed per-rule list stored in scope_value as a
# comma-separated string — the dedicated input for rules whose universe
# the user curates directly (the main use: stoch rules, since the shared
# alert watchlist is nightly-picker-derived, not hand-managed).
SCOPE_TYPES = ("watchlist", "sector", "industry", "all", "tickers")

# Per-rule ticker lists are fetched one Yahoo call per ticker per run
# (stoch rules) — cap the list so a paste-accident can't melt the cron.
MAX_SCOPE_TICKERS = 50


def normalize_ticker_scope(value: str | None) -> str | None:
    """Normalize a hand-typed ticker list ('qqq, spy aapl') into the
    canonical stored form ('AAPL,QQQ,SPY'). None when empty or over the
    MAX_SCOPE_TICKERS cap."""
    import re as _re
    parts = sorted({t.strip().upper()
                    for t in _re.split(r"[,\s;]+", value or "") if t.strip()})
    if not parts or len(parts) > MAX_SCOPE_TICKERS:
        return None
    return ",".join(parts)


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
CREATE TABLE IF NOT EXISTS stoch_rule_state (
    rule_id  INT  NOT NULL,
    ticker   TEXT NOT NULL,
    last_bar TEXT,
    fired_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (rule_id, ticker)
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
    dollar-volume band; stoch rules carry the oscillator knobs; screener
    rules carry the evaluate_ticker kwargs."""
    if rule_type == "setup":
        params = dict(SETUP_DEFAULT_PARAMS)
        for k, v in (raw or {}).items():
            if k in _SETUP_PARAM_KEYS:
                params[k] = v
        return params
    if rule_type == "technical":
        params = dict(TECHNICAL_DEFAULT_PARAMS)
        for k, v in (raw or {}).items():
            if k in _TECHNICAL_PARAM_KEYS:
                params[k] = v
        if params.get("interval") not in _STOCH_INTERVALS + ("1wk", "1mo"):
            params["interval"] = "1d"
        if params.get("direction") not in technicals.DIRECTIONS:
            params["direction"] = "bullish"
        for key in ("rsi_mode", "rsi_sma_mode", "macd_mode"):
            if params.get(key) not in technicals.MODES:
                params[key] = "cross"
        if params.get("streak_mode") not in technicals.STREAK_MODES:
            params["streak_mode"] = "close"

        def _tnum(key, dflt, lo, hi, cast=float):
            try:
                params[key] = max(lo, min(hi, cast(params[key])))
            except (TypeError, ValueError):
                params[key] = dflt
        _tnum("rsi_length", 14, 2, 50, int)
        _tnum("rsi_threshold", 60.0, 0.0, 100.0)
        _tnum("rsi_sma_length", 9, 2, 50, int)
        _tnum("rsi_sma_min_gap_pct", 0.0, 0.0, 100.0)
        _tnum("macd_fast", 12, 2, 50, int)
        _tnum("macd_slow", 26, 3, 100, int)
        _tnum("macd_signal", 9, 2, 50, int)
        _tnum("macd_min_gap_pct", 0.0, 0.0, 100.0)
        _tnum("streak_bars", 3, 1, 20, int)
        _tnum("avg_volume_lookback", 20, 1, 100, int)
        _tnum("avg_volume_min", 500000.0, 0.0, 1e12)
        if params["macd_fast"] >= params["macd_slow"]:
            params["macd_fast"], params["macd_slow"] = 12, 26
        for key in ("apply_rsi_level", "apply_rsi_vs_sma", "apply_macd",
                    "apply_streak", "apply_avg_volume", "macd_hist_rising"):
            params[key] = bool(params.get(key))
        return params
    if rule_type == "stoch":
        params = dict(STOCH_DEFAULT_PARAMS)
        for k, v in (raw or {}).items():
            if k in _STOCH_PARAM_KEYS:
                params[k] = v
        # Sanitize — bad values fall back to defaults instead of failing
        # at evaluation time in the cron.
        if params.get("interval") not in _STOCH_INTERVALS:
            params["interval"] = "5m"
        if params.get("trigger") not in _STOCH_TRIGGERS:
            params["trigger"] = "curl_up"
        def _num(key, dflt, lo, hi, cast=float):
            try:
                params[key] = max(lo, min(hi, cast(params[key])))
            except (TypeError, ValueError):
                params[key] = dflt
        _num("k_len", 14, 2, 50, int)
        _num("smooth", 3, 1, 10, int)
        _num("oversold", 20.0, 0.0, 50.0)
        _num("overbought", 80.0, 50.0, 100.0)
        _num("lookback_bars", 4, 1, 20, int)
        _num("rearm_level", 50.0, 0.0, 100.0)
        _num("stop_buffer_pct", 0.15, 0.0, 2.0)
        _num("opt_delta", 0.35, 0.05, 0.95)
        _num("opt_contracts", 1, 1, 1000, int)
        _num("opt_dte_min", 2, 0, 60, int)
        _num("opt_dte_max", 6, 1, 90, int)
        if params["opt_dte_min"] > params["opt_dte_max"]:
            params["opt_dte_min"], params["opt_dte_max"] = \
                params["opt_dte_max"], params["opt_dte_min"]
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
    if scope_type == "tickers":
        scope_value = normalize_ticker_scope(scope_value)
        if not scope_value:
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


def update_rule(rule_id: int,
                name: str | None = None,
                scope_type: str | None = None,
                scope_value: str | None = None) -> bool:
    """Update an existing rule's name, scope_type, and/or scope_value.
    Any field passed as None is left unchanged. Returns True on success.

    rule_type is intentionally NOT editable — switching a screener rule
    into a setup rule (or vice versa) would invalidate its `params`
    column, and the user has a clearer path (delete + recreate) when
    that's actually what they want.
    """
    if not enabled():
        return False
    sets: list[str] = []
    args: list = []
    if name is not None:
        clean = (name or "").strip()
        if not clean:
            return False
        sets.append("name = %s"); args.append(clean)
    if scope_type is not None:
        st = (scope_type or "").strip().lower()
        if st not in SCOPE_TYPES:
            return False
        sets.append("scope_type = %s"); args.append(st)
        # If caller is changing scope_type, force a fresh scope_value
        # (the old one may not be valid for the new scope). Caller
        # should pass scope_value too — fall back to '' if not.
        if scope_value is None:
            scope_value = ""
        # A hand-typed ticker list must normalize to a non-empty,
        # capped, canonical form.
        if st == "tickers":
            scope_value = normalize_ticker_scope(scope_value)
            if not scope_value:
                return False
    if scope_value is not None:
        sv = (scope_value or "").strip()
        sets.append("scope_value = %s"); args.append(sv)
    if not sets:
        return False
    args.append(int(rule_id))
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                f"UPDATE alert_rules SET {', '.join(sets)} WHERE id = %s",
                tuple(args),
            )
            return (cur.rowcount or 0) > 0
    except Exception as exc:
        log.warning("alerts: update_rule failed: %s", exc)
        return False


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
    if scope_type == "tickers":
        return [t for t in (scope_value or "").split(",") if t]
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
                # Stoch rules can legitimately alert the same ticker more
                # than once per day (episode re-arm); refresh the row so
                # the UI's "Last alert" header tracks the latest one.
                "ON CONFLICT (rule_id, ticker, trigger_date) "
                "DO UPDATE SET detail = EXCLUDED.detail, sent_at = now()",
                (rule_id, ticker, trigger_date, detail),
            )
    except Exception as exc:
        log.warning("alerts: record_sent failed: %s", exc)


def _stoch_state_for_rule(rule_id: int) -> dict[str, str]:
    """ticker -> bar label of the last alert this stoch rule fired."""
    if not enabled():
        return {}
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT ticker, last_bar FROM stoch_rule_state WHERE rule_id = %s",
                (int(rule_id),),
            )
            return {r[0]: r[1] for r in cur.fetchall() if r[1]}
    except Exception as exc:
        log.warning("alerts: _stoch_state_for_rule failed: %s", exc)
        return {}


def _record_stoch_state(rule_id: int, ticker: str, last_bar: str | None) -> None:
    if not enabled() or not last_bar:
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO stoch_rule_state (rule_id, ticker, last_bar) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (rule_id, ticker) "
                "DO UPDATE SET last_bar = EXCLUDED.last_bar, fired_at = now()",
                (int(rule_id), ticker, str(last_bar)),
            )
    except Exception as exc:
        log.warning("alerts: _record_stoch_state failed: %s", exc)


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


# --- enrichment-aware formatters ------------------------------------------
# Both alert paths (screener-rule, setup-rule) now emit a rich Telegram
# body matching the look of the realtime momentum scanner: header →
# headline metrics → insider/fund/news enrichment → verdict + entry
# recommendation.

def _verdict_screener(hit, intel: dict | None = None) -> dict:
    """BUY / WATCH / PASS rollup for a screener-rule alert. Inputs all
    drawn from screener.evaluate_ticker's ScreenHit. Base score out of 9 —
    high momentum + high RVOL + decent pct-change + above-lookback-high
    pushes BUY; weak everything stays PASS even though it cleared the
    rule's filter bar.

    When market intel is available it adds a ±3 band on top (analyst /
    price-target / fundamentals / news sentiment), so a technically-fine
    but fundamentally-weak name — negative trend, poor ROE, insider
    selling — gets marked down rather than waved through. No-op (and /max
    stays 9) when intel is absent."""
    score = 0
    mom = float(getattr(hit, "momentum_score", 0) or 0)
    if   mom >= 80: score += 3
    elif mom >= 60: score += 2
    elif mom >= 40: score += 1
    rvol = float(getattr(hit, "rel_volume", 0) or 0)
    if   rvol >= 5:   score += 3
    elif rvol >= 2.5: score += 2
    elif rvol >= 1.5: score += 1
    pct = float(getattr(hit, "pct_change", 0) or 0)
    if   pct >= 10: score += 2
    elif pct >= 5:  score += 1
    if float(getattr(hit, "breakout_pct", 0) or 0) > 0:
        score += 1  # broke out above the lookback window high

    max_score = 9
    if intel and intel.get("score") is not None:
        import market_intel
        max_score += 3
        score += market_intel.band(intel, 3, 1, -2)

    if score >= 7: return {"label": "BUY",   "glyph": "🟢", "score": score, "max": max_score}
    if score >= 4: return {"label": "WATCH", "glyph": "🟡", "score": score, "max": max_score}
    return {"label": "PASS", "glyph": "🔴", "score": score, "max": max_score}


def _verdict_setup(result: dict) -> dict:
    """Verdict from a setup-rule alert — the score is already a 0-100
    composite of base / ignition / earliness, so just bucket."""
    score = float(result.get("score") or 0)
    if score >= 80: return {"label": "BUY",   "glyph": "🟢", "score": score, "max": 100}
    if score >= 60: return {"label": "WATCH", "glyph": "🟡", "score": score, "max": 100}
    return {"label": "PASS", "glyph": "🔴", "score": score, "max": 100}


def _entry_reco_screener(hit) -> str:
    """Entry / stop / target string for a screener-rule alert.

    No ATR available in the alert pipeline (we'd need to re-fetch the
    bars), so use a flat 2.5% stop below current close and a 1.5R
    profit target. Conservative; user can tighten or loosen visually."""
    price = float(getattr(hit, "close", 0) or 0)
    if price <= 0:
        return ""
    stop   = price * 0.975
    target = price + (price - stop) * 1.5
    return (f"🎯 Entry now: <b>${price:.2f}</b>  ·  "
            f"Stop: ${stop:.2f}  ·  Target: ${target:.2f}")


def _entry_reco_setup(result: dict) -> str:
    """Setup is a base/inflection signal — the breakout hasn't
    happened yet. Suggest a trigger price 0.5% above the inflection
    bar's close, 5% stop below it, 2R target."""
    pivot = float(result.get("close") or 0)
    if pivot <= 0:
        return ""
    trigger = pivot * 1.005
    stop    = pivot * 0.95
    target  = trigger + (trigger - stop) * 2
    return (f"🎯 Trigger above <b>${trigger:.2f}</b>  ·  "
            f"Stop ${stop:.2f}  ·  Target ${target:.2f}")


def _analysis_screener(hit, verdict: dict,
                       insider: dict | None, news: list | None) -> str:
    """One-line plain-English read of what the alert is saying. Composed
    deterministically from the same metric facts the verdict uses, so
    the analysis line and the verdict can never contradict each other."""
    parts = []
    rvol = float(getattr(hit, "rel_volume", 0) or 0)
    pct  = float(getattr(hit, "pct_change", 0) or 0)
    mom  = float(getattr(hit, "momentum_score", 0) or 0)
    if   rvol >= 5:   parts.append(f"unusual volume ({rvol:.1f}× avg)")
    elif rvol >= 2.5: parts.append(f"elevated volume ({rvol:.1f}× avg)")
    if pct >= 10: parts.append(f"strong day ({pct:+.1f}%)")
    elif pct >= 5: parts.append(f"green day ({pct:+.1f}%)")
    if mom >= 70: parts.append(f"high momentum ({mom:.0f}/100)")
    if float(getattr(hit, "breakout_pct", 0) or 0) > 0:
        parts.append("broke prior high")
    if insider:
        code = (insider.get("code") or "").upper()
        if code == "P": parts.append("insider buying")
    if news: parts.append(f"{len(news)} fresh news item(s)")
    if not parts:
        return f"📝 Cleared filter; otherwise unremarkable → {verdict['label']}."
    return "📝 " + ", ".join(parts) + f" → {verdict['label']}."


def _analysis_setup(result: dict, verdict: dict) -> str:
    base  = float(result.get("base_quality") or 0) * 100
    ign   = float(result.get("ignition") or 0) * 100
    early = float(result.get("earliness") or 0) * 100
    parts = []
    if base  >= 70: parts.append(f"tight base ({base:.0f})")
    if ign   >= 70: parts.append(f"strong ignition ({ign:.0f})")
    if early >= 70: parts.append(f"early in the move ({early:.0f})")
    if not parts:
        return f"📝 Setup cleared composite gate; sub-scores mixed → {verdict['label']}."
    return "📝 " + ", ".join(parts) + f" → {verdict['label']}."


def _format_alert(rule_name: str, hit, as_of: datetime,
                  insider: dict | None = None,
                  fund: dict | None = None,
                  news: list | None = None,
                  intel: dict | None = None) -> str:
    """Telegram body for a screener-rule trigger, in the shared
    tg_format style: header → metric rows (with severity callouts) →
    enrichment rows → analysis + verdict + entry reco."""
    import enrich
    import tg_format as T
    name = getattr(hit, "name", None) or None
    rvol = getattr(hit, "rel_volume", None)
    pct = getattr(hit, "pct_change", None)

    lines = T.header("SCREENER ALERT", hit.ticker, name=name,
                     when=T.time_et(as_of))
    lines.append(T.row("🏷", "Rule", T.b(rule_name)))
    lines.append("")
    lines += [
        T.severity_row("💰", "Price",
                       T.b(T.money(getattr(hit, "close", None)))
                       + f" ({T.signed_pct(pct)})",
                       T.pct_change_level(pct)),
        T.row("📈", "Momentum", T.b(f"{hit.momentum_score:.0f}/100")),
        T.severity_row("🔥", "RVOL", T.b(T.multiple(rvol)), T.rvol_level(rvol)),
        T.row("📊", "RSI / MACD",
              f"RSI {hit.rsi:.1f} · MACD hist {hit.macd_hist:+.3f}"),
    ]
    lines += T.fundamentals_rows(fund)
    lines.append(T.insider_row(insider))
    import market_intel
    intel_row = market_intel.summary_row(intel)
    if intel_row:
        lines.append(T.row("🧠", "Intel", intel_row))
    news_block = enrich.format_news_block(news)
    if news_block:
        lines.append("")
        lines.append(news_block)

    v = _verdict_screener(hit, intel=intel)
    lines.append("")
    lines.append(_analysis_screener(hit, v, insider, news))
    lines.append(
        f"🧭 <b>Verdict:</b> {v['glyph']} <b>{v['label']}</b> "
        f"<i>({v['score']}/{v['max']})</i>"
    )
    entry = _entry_reco_screener(hit)
    if entry:
        lines.append(entry)
    return "\n".join(lines)


def _format_setup_alert(rule_name: str, result: dict, snapshot_date: str,
                        insider: dict | None = None,
                        fund: dict | None = None,
                        news: list | None = None) -> str:
    """Telegram body for a setup-rule trigger. Same shared style as
    _format_alert; the score row surfaces the three sub-scores
    (base / ignition / earliness) that explain the overall score."""
    import enrich
    import tg_format as T
    name = result.get("name") or None

    lines = T.header("SETUP ALERT", result["ticker"], name=name,
                     emoji="⚡")
    lines.append(T.row("🏷", "Rule", T.b(rule_name)))
    lines.append(T.row("🗓", "Snapshot", snapshot_date))
    lines.append("")
    lines += [
        T.row("💰", "Price", T.b(T.money(result.get("close")))),
        T.row("⚡", "Setup score", T.b(f"{result['score']:.0f}/100")),
        T.row("🔬", "Sub-scores",
              f"base {result['base_quality']*100:.0f} · "
              f"ign {result['ignition']*100:.0f} · "
              f"early {result['earliness']*100:.0f}"),
    ]
    lines += T.fundamentals_rows(fund)
    lines.append(T.insider_row(insider))
    news_block = enrich.format_news_block(news)
    if news_block:
        lines.append("")
        lines.append(news_block)

    v = _verdict_setup(result)
    lines.append("")
    lines.append(_analysis_setup(result, v))
    lines.append(
        f"🧭 <b>Verdict:</b> {v['glyph']} <b>{v['label']}</b> "
        f"<i>({v['score']:.0f}/{v['max']})</i>"
    )
    entry = _entry_reco_setup(result)
    if entry:
        lines.append(entry)
    return "\n".join(lines)


# --- market clock ----------------------------------------------------------

def _now_et() -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            pass
    return datetime.utcnow() - timedelta(hours=4)


# --- stoch-type rules ------------------------------------------------------

# Minutes per intraday interval — used for the stale-tape guard.
_STOCH_INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


def _stoch_rearmed(slow: list, bars: list[dict], last_bar: str,
                   bearish: bool, rearm_level: float) -> bool:
    """True when a new alert may fire after one at `last_bar`: some Slow
    %K reading on a bar strictly after it must have crossed the re-arm
    level (>= for call-side rules — the bounce played out; <= for
    put-side — the pullback completed). Marks the previous swing episode
    finished so the next dip/rollover counts as a new one. Day
    boundaries need no special-casing: a cross on any later bar
    (including the next session) re-arms."""
    since = [s for b, s in zip(bars, slow)
             if s is not None and str(b.get("d") or "") > last_bar]
    if not since:
        return False
    return (min(since) <= rearm_level) if bearish else (max(since) >= rearm_level)


def _evaluate_stoch_rule(ticker: str, p: dict, now: datetime,
                         last_bar: str | None = None) -> tuple[str, dict | None]:
    """Evaluate one ticker against a stoch rule's params. Returns
    (status, signal): status is 'no_data' | 'stale' | 'deduped' |
    'quiet' | 'fired'; signal is populated only when fired.

    last_bar is the bar label of this rule's previous alert for the
    ticker (from stoch_rule_state) — episode dedupe: no re-fire on the
    same or an older bar, and none until Slow %K has crossed
    rearm_level since (see _stoch_rearmed). This replaces the
    one-per-day dedupe the other rule types use: a 5m stochastic can
    legitimately set up several times a day, and each episode should
    alert once.

    Data comes from calculators.fetch_bars (Yahoo intraday, TTL-cached;
    snapshot-first for 1d) — no Alpaca dependency."""
    import calculators

    interval = p.get("interval", "5m")
    k_len = int(p.get("k_len", 14))
    smooth = int(p.get("smooth", 3))
    oversold = float(p.get("oversold", 20.0))
    lookback = max(1, int(p.get("lookback_bars", 4)))

    bars, source = calculators.fetch_bars(ticker, interval)
    if not bars or len(bars) < k_len + smooth + lookback:
        return "no_data", None

    # Stale-tape guard (intraday only): if Yahoo's latest bar is older
    # than ~6 intervals, the tape is gappy (halt, delisting, symbol typo)
    # — a "signal" computed on it would be hours old. Bar labels are ET
    # ("YYYY-MM-DD HH:MM"), and `now` is ET, so plain string comparison
    # works.
    mins = _STOCH_INTERVAL_MINUTES.get(interval)
    if mins:
        from datetime import timedelta
        cutoff = (now - timedelta(minutes=6 * mins)).strftime("%Y-%m-%d %H:%M")
        if str(bars[-1].get("d") or "") < cutoff:
            return "stale", None

    fast, slow = calculators.stoch_series(bars, k_len, smooth)
    if fast[-1] is None or slow[-1] is None or slow[-2] is None:
        return "no_data", None

    trigger = p.get("trigger", "curl_up")
    overbought = float(p.get("overbought", 80.0))
    bearish = trigger in _STOCH_BEARISH_TRIGGERS

    # Episode dedupe — same/older bar can't re-fire (the cron often runs
    # more than once inside one bar), and after a fire the ticker stays
    # quiet until Slow %K crosses the re-arm level.
    if last_bar:
        if str(bars[-1].get("d") or "") <= str(last_bar):
            return "deduped", None
        if not _stoch_rearmed(slow, bars, str(last_bar), bearish,
                              float(p.get("rearm_level", 50.0))):
            return "deduped", None

    # Curl turns must be a real half-point move, not float jitter on a
    # flat tape — a steady one-way tape keeps Slow %K mathematically
    # constant, and an any-epsilon comparison would fire on noise.
    recent = [v for v in slow[-(lookback + 1):-1] if v is not None]
    if trigger == "entered_oversold":
        fired = slow[-1] <= oversold < slow[-2]
    elif trigger == "entered_overbought":
        fired = slow[-1] >= overbought > slow[-2]
    elif trigger == "curl_down":
        fired = (bool(recent) and max(recent) >= overbought
                 and slow[-1] < slow[-2] - 0.5 and fast[-1] < slow[-1])
    else:  # curl_up
        fired = (bool(recent) and min(recent) <= oversold
                 and slow[-1] > slow[-2] + 0.5 and fast[-1] > slow[-1])
    if not fired:
        return "quiet", None

    price = float(bars[-1]["c"])
    sig = {
        "ticker": ticker, "interval": interval, "price": price,
        "bar_time": bars[-1].get("d"), "source": source, "trigger": trigger,
        "direction": "bearish" if bearish else "bullish",
        "fast_k": round(fast[-1], 1), "slow_k": round(slow[-1], 1),
        "slow_k_prev": round(slow[-2], 1),
    }
    # Bounce map from the reverse solver (steady drift over `smooth`
    # bars). Call side: target = drift-to-overbought level, risk = the
    # stays-oversold boundary below. Put side mirrors: target =
    # drift-to-oversold level, risk = the stays-overbought floor above.
    try:
        ob = calculators.solve_price_for_slow_k(
            bars, overbought, "up", smooth, k_len, smooth, "drift")
        osb = calculators.solve_price_for_slow_k(
            bars, oversold, "down", smooth, k_len, smooth, "drift")
        if bearish:
            sig["target_price"] = osb.get("price")
            sig["risk_price"] = ob.get("price")
        else:
            sig["target_price"] = ob.get("price")
            sig["risk_price"] = osb.get("price")
        # Explicit trade-plan prices. The STOP sits `stop_buffer_pct`
        # beyond the boundary (below it for calls, above for puts) — at
        # the boundary itself, a normal in-band flush tags the stop on
        # the low tick of a winning trade (the 7/20 validated trade
        # survived by ~$1 for exactly this reason).
        buf = float(p.get("stop_buffer_pct", 0.15)) / 100.0
        if sig.get("risk_price") is not None:
            sig["stop_price"] = round(
                sig["risk_price"] * ((1 + buf) if bearish else (1 - buf)), 4)
        if price > 0:
            if sig.get("target_price") is not None:
                sig["target_pct"] = round(
                    (sig["target_price"] - price) / price * 100.0, 2)
            if sig.get("stop_price") is not None:
                sig["stop_pct"] = round(
                    (sig["stop_price"] - price) / price * 100.0, 2)
        # Contract recommendation — the liquid contract closest to the
        # rule's target delta inside its DTE window. Best-effort: on
        # any failure (throttle, closed market, illiquid chain) the
        # alert falls back to assumed-delta math.
        delta = float(p.get("opt_delta", 0.35))
        contracts = max(1, int(p.get("opt_contracts", 1)))
        contract = None
        try:
            import options as options_mod
            contract = options_mod.select_contract_for_delta(
                ticker, "put" if bearish else "call", price, delta,
                int(p.get("opt_dte_min", 2)), int(p.get("opt_dte_max", 6)))
        except Exception as exc:
            log.warning("stoch contract pick failed for %s: %s", ticker, exc)
        if contract:
            sig["contract"] = contract
        # Option framing — linear delta approximation of the position
        # P&L if the underlying reaches the target / risk level, using
        # the recommended contract's REAL delta when one was found.
        # Gamma is ignored (it flatters winners slightly), so these are
        # conservative ballparks, not quotes.
        if contract and contract.get("delta") is not None:
            delta_used = abs(float(contract["delta"]))
            sig["opt_delta_source"] = "chain"
        else:
            delta_used = delta
            sig["opt_delta_source"] = "assumed"
        if sig.get("target_price") is not None and sig.get("risk_price") is not None:
            sig["opt_delta"] = round(delta_used, 2)
            sig["opt_contracts"] = contracts
            sig["opt_gain"] = round(
                abs(sig["target_price"] - price) * delta_used * 100 * contracts, 2)
            # Loss estimate uses the actual (buffered) stop price, not
            # the raw boundary, so the alert's risk number matches the
            # stop it recommends.
            stop_ref = sig.get("stop_price", sig["risk_price"])
            sig["opt_loss"] = round(
                abs(price - stop_ref) * delta_used * 100 * contracts, 2)
            if contract and contract.get("mid"):
                sig["opt_cost"] = round(
                    float(contract["mid"]) * 100 * contracts, 2)
    except Exception as exc:
        log.warning("stoch bounce-map failed for %s: %s", ticker, exc)
    return "fired", sig


_STOCH_TRIG_TEXT = {
    "curl_up": "curled up from oversold",
    "entered_oversold": "entered oversold",
    "curl_down": "curled down from overbought",
    "entered_overbought": "entered overbought",
}


def _format_stoch_alert(rule_name: str, sig: dict, as_of: datetime) -> str:
    """Telegram body for a stoch-rule trigger — compact: the oscillator
    move, plus the reverse-solver's target/boundary levels. Call-side
    triggers frame the map for a bounce long; put-side triggers frame
    the mirrored breakdown short."""
    import tg_format as T
    trig_txt = _STOCH_TRIG_TEXT.get(sig.get("trigger"), sig.get("trigger") or "")
    bearish = sig.get("direction") == "bearish"
    side_txt = "put side" if bearish else "call side"
    lines = T.header("STOCH ALERT", sig["ticker"], when=T.time_et(as_of),
                     emoji="🌀")
    lines.append(T.row("🏷", "Rule", T.b(rule_name) + f" · {side_txt}"))
    lines.append("")
    lines.append(T.row("💰", "Entry", T.b(T.money(sig.get("price")))
                       + f" · {T.esc(sig.get('interval') or '')} bars"))
    lines.append(T.row("🌀", "Slow %K",
                       T.b(f"{sig['slow_k_prev']} → {sig['slow_k']}")
                       + f" · fast {sig['fast_k']} · {trig_txt}"))

    # Trade plan — the two prices to act on, stated plainly. The
    # reasoning (which stochastic level each comes from) rides along as
    # a smaller footnote line underneath.
    def _pct_sfx(key: str) -> str:
        v = sig.get(key)
        return f" ({v:+.2f}%)" if isinstance(v, (int, float)) else ""

    plan = []
    if sig.get("target_price") is not None:
        plan.append(T.row("🎯", "Target",
                          T.b(T.money(sig["target_price"])) + _pct_sfx("target_pct")
                          + " — take profit here"))
    if sig.get("stop_price") is not None:
        plan.append(T.row("🛑", "Stop loss",
                          T.b(T.money(sig["stop_price"])) + _pct_sfx("stop_pct")
                          + " — exit if reached"))
    if plan:
        lines.append("")
        lines += plan
        if sig.get("risk_price") is not None:
            note = (f"target = drift-to-{'oversold' if bearish else 'overbought'}"
                    f" level · stop sits just "
                    f"{'above the stays-overbought ceiling' if bearish else 'below the stays-oversold boundary'}"
                    f" ({T.money(sig['risk_price'])})")
            lines.append(T.i(note))
        lines.append("")
    c = sig.get("contract")
    if c:
        kind = "put" if bearish else "call"
        lines.append(T.row("🎫", "Contract",
                           T.b(f"{T.money(c.get('strike'), 0)} {kind}")
                           + f" · exp {T.esc(c.get('expiration') or '?')}"
                           + f" ({c.get('dte', '?')} DTE)"))
        oi = c.get("open_interest")
        lines.append(T.row("💵", "Quote",
                           "mid " + T.b(T.money(c.get("mid")))
                           + f" (bid {T.money(c.get('bid'))} / ask {T.money(c.get('ask'))})"
                           + f" · Δ{abs(c.get('delta') or 0):.2f}"
                           + (f" · OI {oi:,}" if oi else "")))
        if sig.get("opt_cost") is not None:
            n_c = sig.get("opt_contracts") or 1
            lines.append(T.row("🧾", "Cost",
                               "≈ " + T.b(T.money(sig["opt_cost"], 0))
                               + f" to open ({n_c} × {T.money(c.get('mid'))})"))
    if sig.get("opt_gain") is not None and sig.get("opt_loss") is not None:
        n_c = sig.get("opt_contracts") or 1
        src = "chain Δ" if sig.get("opt_delta_source") == "chain" else "assumed Δ"
        pos_txt = f"{src}{sig.get('opt_delta')} × {n_c} contract{'s' if n_c > 1 else ''}"
        lines.append(T.row("📐",
                           "Put est" if bearish else "Call est",
                           T.b("+" + T.money(sig["opt_gain"], 0)) + " at target · "
                           + T.b("−" + T.money(sig["opt_loss"], 0)) + " at stop"
                           + f" ({pos_txt}, delta approx)"))
    if sig.get("bar_time"):
        lines.append(T.row("🕒", "Bar", T.esc(str(sig["bar_time"])) + " ET"))
    lines.append("")
    lines.append(T.i("Informational only — not financial advice."))
    return "\n".join(lines)


def _evaluate_technical_rule(ticker: str, p: dict, now: datetime,
                             last_bar: str | None = None) -> tuple[str, dict | None]:
    """Evaluate one ticker against a technical rule. Returns
    (status, signal) with status in 'no_data' | 'stale' | 'deduped' |
    'quiet' | 'fired'.

    Dedupe is once per bar period: the rule can't re-fire while the
    evaluated bar label is unchanged (a 1d rule alerts at most once per
    session; a 5m rule once per 5m bar)."""
    import calculators

    interval = p.get("interval", "1d")
    bars, source = calculators.fetch_bars(ticker, interval)
    if not bars or len(bars) < 3:
        return "no_data", None

    # Stale-tape guard for intraday intervals only (daily+ bars are
    # naturally "old" outside market hours).
    mins = _STOCH_INTERVAL_MINUTES.get(interval)
    if mins:
        from datetime import timedelta
        cutoff = (now - timedelta(minutes=6 * mins)).strftime("%Y-%m-%d %H:%M")
        if str(bars[-1].get("d") or "") < cutoff:
            return "stale", None

    closed_only = interval in _TECH_CLOSED_ONLY_INTERVALS
    res = technicals.evaluate(bars, p, closed_only=closed_only)
    if not res.get("ok"):
        reason = res.get("reason")
        return ("no_data" if reason in ("no_bars", "not_warm") else "quiet"), None

    bar_label = str(res.get("bar") or "")
    if last_bar and bar_label <= str(last_bar):
        return "deduped", None

    return "fired", {
        "ticker": ticker, "interval": interval, "source": source,
        "direction": p.get("direction", "bullish"),
        "price": res.get("price"), "bar_time": res.get("bar"),
        "details": res.get("details") or [],
        "closed_only": closed_only,
    }


def _format_technical_alert(rule_name: str, sig: dict, as_of: datetime) -> str:
    """Telegram body for a technical-rule trigger: which conditions
    matched, on which bar, at what price."""
    import tg_format as T
    bearish = str(sig.get("direction")) == "bearish"
    side = "bearish" if bearish else "bullish"
    lines = T.header("TECHNICAL ALERT", sig["ticker"], when=T.time_et(as_of),
                     emoji="📐")
    lines.append(T.row("🏷", "Rule", T.b(rule_name) + f" · {side}"))
    lines.append("")
    lines.append(T.row("💰", "Price", T.b(T.money(sig.get("price")))
                       + f" · {T.esc(sig.get('interval') or '')} bars"))
    lines.append("")
    lines.append("✅ <b>Conditions met</b>")
    for d in sig.get("details") or []:
        lines.append("• " + T.esc(str(d)))
    if sig.get("bar_time"):
        lines.append("")
        suffix = " (closed bar)" if sig.get("closed_only") else ""
        lines.append(T.row("🕒", "Bar", T.esc(str(sig["bar_time"])) + suffix))
    lines.append("")
    lines.append(T.i("Informational only — not financial advice."))
    return "\n".join(lines)


def _partition_rules(rules: list[dict], only_stoch: bool = False,
                     skip_stoch: bool = False) -> tuple[list, list, list]:
    """Split enabled rules into the three evaluation groups.

    The third group is the FAST LANE — stoch and technical rules alike:
    both read intraday bars via calculators.fetch_bars and finish in
    seconds, so they share `python alerts.py stoch` and the 5-minute
    stoch-alerts workflow.

    only_stoch — the fast-lane mode: just that group (skip flag ignored).
    skip_stoch — the main engine when the fast lane owns the group
    (ALERT_SKIP_STOCH env), so the two lanes never double-send."""
    stoch = [r for r in rules if r.get("rule_type") in ("stoch", "technical")]
    if only_stoch:
        return [], [], stoch
    screener = [r for r in rules
                if r.get("rule_type") not in ("setup", "stoch", "technical")]
    setup = [r for r in rules if r.get("rule_type") == "setup"]
    return screener, setup, ([] if skip_stoch else stoch)


def market_is_open(now: datetime | None = None) -> bool:
    """US regular session, weekdays 9:30am-4:00pm ET. Does not account
    for market holidays — a holiday just yields zero fresh bars, so the
    worst case is a wasted run, not a wrong alert."""
    now = now or _now_et()
    if now.weekday() >= 5:
        return False
    return dt_time(9, 30) <= now.time() <= dt_time(16, 0)


# --- main loop -------------------------------------------------------------

def run(only_stoch: bool = False) -> int:
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

    # Lane split: the fast lane ('python alerts.py stoch', driven by its
    # own workflow) evaluates only stoch rules so 5-minute-bar signals
    # aren't stuck behind the ~10-minute screener sweep; the main engine
    # sets ALERT_SKIP_STOCH so the two lanes never double-send.
    skip_stoch = str(os.environ.get("ALERT_SKIP_STOCH", "")).strip().lower() \
        in ("1", "true", "yes", "on")
    screener_rules, setup_rules, stoch_rules = _partition_rules(
        rules, only_stoch=only_stoch, skip_stoch=skip_stoch)
    log.info("lane=%s: %d screener / %d setup / %d stoch rule(s) to evaluate",
             "stoch-only" if only_stoch else "main",
             len(screener_rules), len(setup_rules), len(stoch_rules))

    triggered_screener: list[tuple[dict, str, object]] = []   # (rule, ticker, hit)
    triggered_setup: list[tuple[dict, dict]] = []             # (rule, result)
    triggered_stoch: list[tuple[dict, dict]] = []             # (rule, signal)
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
                        base_min=float(p.get("base_min", 0.0)),
                        ignition_min=float(p.get("ignition_min", 0.0)),
                        earliness_min=float(p.get("earliness_min", 0.0)),
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

    # --- stoch-type rules (Yahoo intraday via calculators) ----------------
    if stoch_rules:
        for rule in stoch_rules:
            p = rule["params"]
            scope = tickers_for_scope(rule["scope_type"], rule["scope_value"]) or []
            # Episode dedupe replaces the one-per-day gate: the evaluator
            # blocks re-fires until Slow %K crosses the rule's re-arm
            # level after the previous alert's bar (stoch_rule_state).
            fired_state = _stoch_state_for_rule(rule["id"])
            ev = de = nd = er = mt = 0
            is_tech = rule.get("rule_type") == "technical"
            for ticker in scope:
                try:
                    evaluator = (_evaluate_technical_rule if is_tech
                                 else _evaluate_stoch_rule)
                    status, sig = evaluator(
                        ticker, p, now, last_bar=fired_state.get(ticker))
                except Exception as exc:
                    log.warning("%s evaluate failed for %s (rule %s): %s",
                                "technical" if is_tech else "stoch",
                                ticker, rule["id"], exc)
                    er += 1
                    continue
                if status == "deduped":
                    de += 1
                    continue
                if status in ("no_data", "stale"):
                    nd += 1
                    continue
                ev += 1
                if status == "fired":
                    mt += 1
                    triggered_stoch.append((rule, sig))
            log.info(
                'rule %d "%s" (' + ("technical" if is_tech else "stoch")
                + ' %s%s): scope=%d evaluated=%d '
                'matched=%d deduped=%d no_data=%d errors=%d',
                rule["id"], rule["name"], rule["scope_type"],
                (":" + rule["scope_value"]) if rule["scope_value"] else "",
                len(scope), ev, mt, de, nd, er,
            )
            stats_list.append({
                "rule_id": rule["id"], "scope": len(scope), "evaluated": ev,
                "matched": mt, "deduped": de, "no_data": nd, "errors": er,
            })

    _record_rule_run_stats(stats_list)

    if not triggered_screener and not triggered_setup and not triggered_stoch:
        log.info("no new alerts this run")
        return 0

    sent = 0
    import outcomes
    import enrich

    # Per-ticker enrichment cache so two rules firing on the same
    # ticker in the same run only pay one yfinance + Finnhub round-trip
    # each. Every enrichment call is best-effort (returns None / [] / {}
    # on failure) — the alert still goes out without the missing block.
    _enrich_cache: dict[str, dict] = {}

    def _enrich_for(ticker: str) -> dict:
        if ticker in _enrich_cache:
            return _enrich_cache[ticker]
        out = {"insider": None, "fund": None, "news": None}
        try: out["insider"] = enrich.last_insider_transaction(ticker)
        except Exception as exc:
            log.warning("enrich.insider(%s) failed: %s", ticker, exc)
        try: out["fund"] = enrich.fundamentals(ticker)
        except Exception as exc:
            log.warning("enrich.fundamentals(%s) failed: %s", ticker, exc)
        try: out["news"] = enrich.recent_news(ticker)
        except Exception as exc:
            log.warning("enrich.news(%s) failed: %s", ticker, exc)
        _enrich_cache[ticker] = out
        return out

    import market_intel
    for rule, ticker, hit in triggered_screener:
        e = _enrich_for(ticker)
        # Optional intel (Alpha Vantage) — None unless INTEL_ENABLED + key.
        intel = market_intel.conviction_for(
            ticker, price=getattr(hit, "close", None), insider=e["insider"])
        if send_telegram(_format_alert(rule["name"], hit, now,
                                        insider=e["insider"], fund=e["fund"],
                                        news=e["news"], intel=intel)):
            record_sent(rule["id"], ticker, today,
                        f"momentum={hit.momentum_score}")
            outcomes.record_stock_outcome(
                ticker, today, getattr(hit, "close", None),
                {"kind": "alert_screener", "id": rule["id"],
                 "label": rule.get("name") or "Screener alert"},
            )
            sent += 1
    for rule, res in triggered_setup:
        ticker = res["ticker"]
        e = _enrich_for(ticker)
        if send_telegram(_format_setup_alert(rule["name"], res,
                                              snapshot_as_of or today,
                                              insider=e["insider"], fund=e["fund"],
                                              news=e["news"])):
            record_sent(rule["id"], ticker, today,
                        f"setup_score={res.get('score')}")
            outcomes.record_stock_outcome(
                ticker, today, res.get("close"),
                {"kind": "alert_setup", "id": rule["id"],
                 "label": rule.get("name") or "Setup alert"},
            )
            sent += 1
    for rule, sig in triggered_stoch:
        is_tech = rule.get("rule_type") == "technical"
        body = (_format_technical_alert(rule["name"], sig, now) if is_tech
                else _format_stoch_alert(rule["name"], sig, now))
        if send_telegram(body):
            detail = ("; ".join(sig.get("details") or [])[:200] if is_tech
                      else f"slow_k={sig['slow_k']}")
            record_sent(rule["id"], sig["ticker"], today, detail)
            _record_stoch_state(rule["id"], sig["ticker"],
                                sig.get("bar_time"))
            outcomes.record_stock_outcome(
                sig["ticker"], today, sig.get("price"),
                {"kind": "alert_technical" if is_tech else "alert_stoch",
                 "id": rule["id"],
                 "label": rule.get("name")
                          or ("Technical alert" if is_tech else "Stoch alert")},
            )
            sent += 1
    total = (len(triggered_screener) + len(triggered_setup)
             + len(triggered_stoch))
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
    if len(sys.argv) > 1 and sys.argv[1] == "stoch":
        # Fast lane — evaluate only the stoch rules (~seconds), so the
        # 5-minute cadence isn't consumed by the screener sweep.
        raise SystemExit(run(only_stoch=True))
    raise SystemExit(run())
