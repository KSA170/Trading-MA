"""
Flask web app exposing:
  GET   /                    -> single page UI
  GET   /api/screen          -> run screener (cached for the trading session)
  GET   /api/chart/<tkr>     -> daily OHLCV + SMA(10/20/30/40) + RSI(14)/9d-SMA
  GET   /api/lists           -> available list keys / labels
  GET   /api/dates           -> last N trading-day dates for the date picker
  POST  /api/export/xlsx     -> download selected rows as an Excel workbook
"""

from __future__ import annotations

import logging
import os
import threading
import time
from io import BytesIO
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

import screener
import snapshots
import alerts
import calculators
import pattern_scan
import picker
import filter_presets
import ui_prefs
import scanner_momentum
from tickers import LIST_LABELS, refresh_universe, last_fetch_errors

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")

ROOT = Path(__file__).resolve().parent

app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))


# In-memory cache so re-running with the same parameters is instant.
_screen_cache: dict[tuple, tuple[float, list]] = {}
_screen_lock = threading.Lock()
_SCREEN_TTL_SEC = 60 * 30  # 30 minutes


_VALID_LISTS = set(LIST_LABELS.keys())

DEFAULT_PARAMS: dict = {
    "high_lookback": 2,
    "streak_mode": "high",
    "rsi_min": 45.0,
    "rsi_max": 65.0,
    "rsi_dev_min_pct": 0.0,
    "rsi_dev_max_pct": 10.0,
    "rvol_lookback": 10,
    "rvol_min": 1.2,
    "avg_volume_min": 50000,
    "price_min": 1.0,
    "price_max": 1000.0,
    "price_dev_min_pct": -1.0,
    "price_dev_max_pct": 4.0,
    "ema_dev_min_pct": -3.0,
    "ema_dev_max_pct": 3.0,
    "macd_within_pct": True,
    "macd_vs_signal_pct": 5.0,
    "macd_above_signal": False,
    "macd_line_rising": False,
    "turnover_min_pct": 0.5,
    "turnover_max_pct": 100.0,
    "market_cap_min_m": 0.0,
    "market_cap_max_m": 10_000_000.0,   # $10T = effectively no ceiling
    "pct_change_min": 5.0,
    "apply_high": True,
    "apply_rsi": True,
    "apply_rsi_dev": True,
    "apply_rsi_rising": False,
    "apply_rvol": True,
    "apply_avg_volume": True,
    "apply_price": True,
    "apply_price_dev": True,
    "apply_ema_dev": True,
    # Standalone SMA-trend deviation gates (off by default; wide ranges).
    "apply_price_sma10_dev": False,
    "price_sma10_dev_min_pct": -3.0,
    "price_sma10_dev_max_pct": 5.0,
    "apply_sma10_sma20_dev": False,
    "sma10_sma20_dev_min_pct": -2.0,
    "sma10_sma20_dev_max_pct": 4.0,
    "apply_macd_vs_signal": False,
    "apply_macd_hist_rising": False,
    "apply_turnover": False,
    "apply_market_cap": False,
    "apply_pct_change": False,
    # SMA Revival — see screener.evaluate_ticker for semantics.
    "apply_sma_revival": False,
    "sma_cross_lookback": 3,
    "sma_slope_turn_lookback": 5,
    "sma_slope_window": 3,
    "sma_min_slope_pct": 0.10,
    "sma_require_long_flat": False,
    "sma_long_flat_max_pct": 0.30,
    "sma_require_volume": False,
    "sma_volume_mult": 1.20,
    "as_of_offset": 0,
    "lists": tuple(sorted(_VALID_LISTS)),
}


def _cache_key(params: dict) -> tuple:
    # When a filter is disabled, its threshold values don't matter — collapse
    # them to a sentinel so the cache hits regardless of slider position.
    high = (int(params["high_lookback"]), str(params["streak_mode"])) if params["apply_high"] else ("off",)
    rsi = (round(float(params["rsi_min"]), 3), round(float(params["rsi_max"]), 3)) if params["apply_rsi"] else ("off",)
    rsi_dev = (round(float(params["rsi_dev_min_pct"]), 3), round(float(params["rsi_dev_max_pct"]), 3)) if params["apply_rsi_dev"] else ("off",)
    rvol = (int(params["rvol_lookback"]), round(float(params["rvol_min"]), 3)) if params["apply_rvol"] else ("off",)
    avg_vol = (int(params["avg_volume_min"]),) if params["apply_avg_volume"] else ("off",)
    price = (round(float(params["price_min"]), 4), round(float(params["price_max"]), 4)) if params["apply_price"] else ("off",)
    price_dev = (round(float(params["price_dev_min_pct"]), 3), round(float(params["price_dev_max_pct"]), 3)) if params["apply_price_dev"] else ("off",)
    ema_dev = (round(float(params["ema_dev_min_pct"]), 3), round(float(params["ema_dev_max_pct"]), 3)) if params["apply_ema_dev"] else ("off",)
    price_sma10_dev = (round(float(params["price_sma10_dev_min_pct"]), 3),
                       round(float(params["price_sma10_dev_max_pct"]), 3)) \
                      if params["apply_price_sma10_dev"] else ("off",)
    sma10_sma20_dev = (round(float(params["sma10_sma20_dev_min_pct"]), 3),
                       round(float(params["sma10_sma20_dev_max_pct"]), 3)) \
                      if params["apply_sma10_sma20_dev"] else ("off",)
    macd_vs_sig = (
        bool(params["macd_within_pct"]),
        round(float(params["macd_vs_signal_pct"]), 4),
        bool(params["macd_above_signal"]),
        bool(params["macd_line_rising"]),
    ) if params["apply_macd_vs_signal"] else ("off",)
    # Two standalone boolean momentum gates (no thresholds).
    rsi_rising = bool(params["apply_rsi_rising"])
    macd_hist_rising = bool(params["apply_macd_hist_rising"])
    turnover = (round(float(params["turnover_min_pct"]), 4), round(float(params["turnover_max_pct"]), 4)) if params["apply_turnover"] else ("off",)
    market_cap = (round(float(params["market_cap_min_m"]), 2), round(float(params["market_cap_max_m"]), 2)) if params["apply_market_cap"] else ("off",)
    pct_change = (round(float(params["pct_change_min"]), 4),) if params["apply_pct_change"] else ("off",)
    sma_rev = (
        int(params["sma_cross_lookback"]),
        int(params["sma_slope_turn_lookback"]),
        int(params["sma_slope_window"]),
        round(float(params["sma_min_slope_pct"]), 4),
        bool(params["sma_require_long_flat"]),
        round(float(params["sma_long_flat_max_pct"]), 4),
        bool(params["sma_require_volume"]),
        round(float(params["sma_volume_mult"]), 4),
    ) if params["apply_sma_revival"] else ("off",)
    lists = tuple(sorted(params["lists"]))
    # Cache key uses the RESOLVED as-of date (not the offset) so cache
    # entries don't get reused across calendar drift. With offset-based
    # keying, today's offset=1 and yesterday's offset=1 would collide
    # but mean different calendar dates → stale rows served under the
    # wrong date. Resolved-date keying is drift-proof.
    as_of_key = params.get("as_of_date_resolved") or int(params["as_of_offset"])
    # Bumped to v21 — adding apply_rsi_rising / apply_macd_hist_rising.
    # Old v20 entries would be served against the new filter-set otherwise.
    return ("v21", as_of_key, price, price_dev, ema_dev, price_sma10_dev,
            sma10_sma20_dev, macd_vs_sig, macd_hist_rising, turnover,
            market_cap, pct_change, sma_rev, high, rsi, rsi_dev, rsi_rising,
            rvol, avg_vol, lists)


def _parse_bool(name: str, default: bool) -> bool:
    raw = request.args.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _flt(name: str, default: float) -> float:
    """float() query param with fallback — handles empty strings & nonsense."""
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _int(name: str, default: int) -> int:
    """int() query param with fallback — handles empty strings & nonsense.
    Accepts "5000.0" or "5e3" too via the intermediate float()."""
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return int(default)


def _parse_params() -> dict:
    raw_lists = request.args.get("lists", "")
    if raw_lists.strip():
        wanted = [s.strip() for s in raw_lists.split(",") if s.strip()]
        wanted = [s for s in wanted if s in _VALID_LISTS]
    else:
        wanted = sorted(_VALID_LISTS)
    if not wanted:
        wanted = sorted(_VALID_LISTS)
    # Preferred path: client sends `as_of=YYYY-MM-DD` (the actual date
    # the user picked). Resolve to an offset against the CURRENT calendar
    # so downstream code keeps using offset-based slicing, but the cache
    # key (below) is the date string — drift-proof.
    #
    # Fallback: `as_of_offset` (legacy clients / bookmarks). Subject to
    # calendar drift if the calendar advanced since the page loaded —
    # the symptom users reported as "I picked June 17 but got June 18".
    raw_as_of_date = (request.args.get("as_of") or "").strip()
    resolved_as_of_date: str | None = None
    if raw_as_of_date:
        calendar = screener._calendar_dates(screener.MAX_AS_OF_OFFSET + 1)
        try:
            as_of_offset = calendar.index(raw_as_of_date)
            resolved_as_of_date = raw_as_of_date
        except ValueError:
            # User's picked date is no longer in the calendar (e.g. the
            # page sat open across a snapshot-retention window roll-off).
            # Fall back to latest so the screen still returns something
            # meaningful instead of erroring.
            as_of_offset = 0
            resolved_as_of_date = calendar[0] if calendar else None
    else:
        as_of_offset = _int("as_of_offset", 0)
        if as_of_offset < 0:
            as_of_offset = 0
        if as_of_offset > screener.MAX_AS_OF_OFFSET:
            as_of_offset = screener.MAX_AS_OF_OFFSET
        resolved_as_of_date = screener._resolve_as_of_date(as_of_offset)
    return {
        "as_of_date_resolved": resolved_as_of_date,
        "high_lookback": _int("high_lookback", 2),
        "streak_mode": (request.args.get("streak_mode", "high") or "high").strip().lower()
                       if (request.args.get("streak_mode", "high") or "high").strip().lower()
                       in ("high", "close", "green", "close_green") else "high",
        "rsi_min": _flt("rsi_min", 45),
        "rsi_max": _flt("rsi_max", 65),
        "rsi_dev_min_pct": _flt("rsi_dev_min_pct", 0),
        "rsi_dev_max_pct": _flt("rsi_dev_max_pct", 10),
        "rvol_lookback": _int("rvol_lookback", 10),
        "rvol_min": _flt("rvol_min", 1.2),
        "avg_volume_min": _int("avg_volume_min", 50000),
        "price_min": _flt("price_min", 1),
        "price_max": _flt("price_max", 1000),
        "price_dev_min_pct": _flt("price_dev_min_pct", -1),
        "price_dev_max_pct": _flt("price_dev_max_pct", 4),
        "ema_dev_min_pct": _flt("ema_dev_min_pct", -3),
        "ema_dev_max_pct": _flt("ema_dev_max_pct", 3),
        "price_sma10_dev_min_pct": _flt("price_sma10_dev_min_pct", -3),
        "price_sma10_dev_max_pct": _flt("price_sma10_dev_max_pct", 5),
        "sma10_sma20_dev_min_pct": _flt("sma10_sma20_dev_min_pct", -2),
        "sma10_sma20_dev_max_pct": _flt("sma10_sma20_dev_max_pct", 4),
        "macd_within_pct": _parse_bool("macd_within_pct", True),
        "macd_vs_signal_pct": _flt("macd_vs_signal_pct", 5.0),
        "macd_above_signal": _parse_bool("macd_above_signal", False),
        "macd_line_rising": _parse_bool("macd_line_rising", False),
        "turnover_min_pct": _flt("turnover_min_pct", 0.5),
        "turnover_max_pct": _flt("turnover_max_pct", 100.0),
        "market_cap_min_m": _flt("market_cap_min_m", 0),
        "market_cap_max_m": _flt("market_cap_max_m", 10_000_000),
        "pct_change_min": _flt("pct_change_min", 5.0),
        "apply_high": _parse_bool("apply_high", True),
        "apply_rsi": _parse_bool("apply_rsi", True),
        "apply_rsi_dev": _parse_bool("apply_rsi_dev", True),
        "apply_rsi_rising": _parse_bool("apply_rsi_rising", False),
        "apply_rvol": _parse_bool("apply_rvol", True),
        "apply_avg_volume": _parse_bool("apply_avg_volume", True),
        "apply_price": _parse_bool("apply_price", True),
        "apply_price_dev": _parse_bool("apply_price_dev", True),
        "apply_ema_dev": _parse_bool("apply_ema_dev", True),
        "apply_price_sma10_dev": _parse_bool("apply_price_sma10_dev", False),
        "apply_sma10_sma20_dev": _parse_bool("apply_sma10_sma20_dev", False),
        "apply_macd_vs_signal": _parse_bool("apply_macd_vs_signal", False),
        "apply_macd_hist_rising": _parse_bool("apply_macd_hist_rising", False),
        "apply_turnover": _parse_bool("apply_turnover", False),
        "apply_market_cap": _parse_bool("apply_market_cap", False),
        "apply_pct_change": _parse_bool("apply_pct_change", False),
        # SMA Revival
        "apply_sma_revival": _parse_bool("apply_sma_revival", False),
        "sma_cross_lookback": _int("sma_cross_lookback", 3),
        "sma_slope_turn_lookback": _int("sma_slope_turn_lookback", 5),
        "sma_slope_window": _int("sma_slope_window", 3),
        "sma_min_slope_pct": _flt("sma_min_slope_pct", 0.10),
        "sma_require_long_flat": _parse_bool("sma_require_long_flat", False),
        "sma_long_flat_max_pct": _flt("sma_long_flat_max_pct", 0.30),
        "sma_require_volume": _parse_bool("sma_require_volume", False),
        "sma_volume_mult": _flt("sma_volume_mult", 1.20),
        "as_of_offset": as_of_offset,
        "lists": tuple(wanted),
    }


# --- routes ----------------------------------------------------------------

# Cache-busting stamp for the static bundle — the max mtime of the two
# assets, computed at boot (each deploy restarts the worker). Without
# it, long-lived mobile-Safari tabs keep running a stale app.js against
# fresh HTML, which shows up as "the new field doesn't save".
_ASSET_REV = str(int(max(
    (ROOT / "static" / "app.js").stat().st_mtime,
    (ROOT / "static" / "style.css").stat().st_mtime,
)))


@app.route("/")
def index():
    # Inject server-stored UI prefs into the page so the JS can read
    # them synchronously at boot (avoids a flash where collapsed
    # sections / column layout briefly show defaults before hydrating).
    return render_template("index.html", ui_prefs=ui_prefs.get_all(),
                           asset_rev=_ASSET_REV)


@app.route("/api/screen")
def api_screen():
    try:
        return _api_screen_impl()
    except Exception as exc:
        import traceback
        log.error("api_screen failed: %s\n%s", exc, traceback.format_exc())
        return jsonify({"error": str(exc), "type": type(exc).__name__}), 500


def _api_screen_impl():
    params = _parse_params()
    key = _cache_key(params)
    now = time.time()

    with _screen_lock:
        cached = _screen_cache.get(key)
        if cached and now - cached[0] < _SCREEN_TTL_SEC:
            cached_payload = cached[1]
            return jsonify({
                "results": cached_payload,
                "cached": True,
                "params": {**params, "lists": list(params["lists"])},
                "as_of_date": cached_payload[0]["as_of_date"] if cached_payload else None,
            })

    started = time.time()
    hits = screener.run_screen(
        high_lookback=params["high_lookback"],
        streak_mode=params["streak_mode"],
        rsi_min=params["rsi_min"],
        rsi_max=params["rsi_max"],
        rsi_dev_min_pct=params["rsi_dev_min_pct"],
        rsi_dev_max_pct=params["rsi_dev_max_pct"],
        rvol_lookback=params["rvol_lookback"],
        rvol_min=params["rvol_min"],
        avg_volume_min=params["avg_volume_min"],
        price_min=params["price_min"],
        price_max=params["price_max"],
        price_dev_min_pct=params["price_dev_min_pct"],
        price_dev_max_pct=params["price_dev_max_pct"],
        ema_dev_min_pct=params["ema_dev_min_pct"],
        ema_dev_max_pct=params["ema_dev_max_pct"],
        macd_within_pct=params["macd_within_pct"],
        macd_above_signal=params["macd_above_signal"],
        macd_vs_signal_pct=params["macd_vs_signal_pct"],
        macd_line_rising=params["macd_line_rising"],
        turnover_min_pct=params["turnover_min_pct"],
        turnover_max_pct=params["turnover_max_pct"],
        market_cap_min_m=params["market_cap_min_m"],
        market_cap_max_m=params["market_cap_max_m"],
        pct_change_min=params["pct_change_min"],
        apply_high=params["apply_high"],
        apply_rsi=params["apply_rsi"],
        apply_rsi_dev=params["apply_rsi_dev"],
        apply_rsi_rising=params["apply_rsi_rising"],
        apply_rvol=params["apply_rvol"],
        apply_avg_volume=params["apply_avg_volume"],
        apply_price=params["apply_price"],
        apply_price_dev=params["apply_price_dev"],
        apply_ema_dev=params["apply_ema_dev"],
        apply_macd_vs_signal=params["apply_macd_vs_signal"],
        apply_macd_hist_rising=params["apply_macd_hist_rising"],
        apply_turnover=params["apply_turnover"],
        apply_market_cap=params["apply_market_cap"],
        apply_pct_change=params["apply_pct_change"],
        apply_sma_revival=params["apply_sma_revival"],
        sma_cross_lookback=params["sma_cross_lookback"],
        sma_slope_turn_lookback=params["sma_slope_turn_lookback"],
        sma_slope_window=params["sma_slope_window"],
        sma_min_slope_pct=params["sma_min_slope_pct"],
        sma_require_long_flat=params["sma_require_long_flat"],
        sma_long_flat_max_pct=params["sma_long_flat_max_pct"],
        sma_require_volume=params["sma_require_volume"],
        sma_volume_mult=params["sma_volume_mult"],
        as_of_offset=params["as_of_offset"],
        as_of_date=params.get("as_of_date_resolved"),
        lists=list(params["lists"]),
    )
    payload = [h.to_dict() for h in hits]
    elapsed = time.time() - started
    log.info("screen complete: %d hits in %.1fs (params=%s)", len(payload), elapsed, params)

    with _screen_lock:
        _screen_cache[key] = (now, payload)

    serializable_params = {**params, "lists": list(params["lists"])}
    summary_date = payload[0]["as_of_date"] if payload else None
    return jsonify({
        "results": payload,
        "cached": False,
        "params": serializable_params,
        "as_of_date": summary_date,
        "elapsed_sec": round(elapsed, 1),
    })


@app.route("/api/chart/<path:ticker>")
def api_chart(ticker: str):
    """OHLCV + EMA(21)/EMA(50) + RSI(14)/9d-SMA for the ticker hover chart."""
    payload = screener.chart_payload(ticker)
    if payload is None:
        return jsonify({"error": f"no data for {ticker}"}), 404
    return jsonify(payload)


@app.route("/api/lists")
def api_lists():
    return jsonify({
        "lists": [{"key": k, "label": v} for k, v in LIST_LABELS.items()],
    })


@app.route("/api/dates")
def api_dates():
    """Last N US trading-day dates (anchored on SPY) for the date picker.
    Each entry is tagged `in_snapshot` so the UI can show which dates the
    screener can serve from Postgres (fast) vs which will fall back to
    the live pickle path (slower, may refetch from Yahoo)."""
    n = _int("n", screener.MAX_AS_OF_OFFSET + 1)
    n = max(1, min(n, screener.MAX_AS_OF_OFFSET + 1))
    dates = screener.reference_dates(n=n)
    snap_dates = set(snapshots.available_dates(50)) if snapshots.enabled() else set()
    for d in dates:
        d["in_snapshot"] = d["date"] in snap_dates
    return jsonify({"dates": dates, "snapshot_enabled": snapshots.enabled()})


@app.route("/api/admin/warm-cache", methods=["POST"])
def api_warm_cache():
    """Kick off a background fetch of the full universe into the disk
    price cache. Returns immediately; poll /api/admin/warm-status for
    progress."""
    started = screener.warm_cache()
    return jsonify({"started": started, "status": screener.warm_status()})


@app.route("/api/admin/warm-cache/cancel", methods=["POST"])
def api_warm_cache_cancel():
    """Ask the running warm thread to stop. Already-started fetches will
    finish; queued ones are skipped."""
    cancelled = screener.cancel_warm_cache()
    return jsonify({"cancelled": cancelled, "status": screener.warm_status()})


@app.route("/api/admin/warm-status")
def api_warm_status():
    return jsonify({
        **screener.warm_status(),
        "auto": screener.auto_warm_status(),
    })


@app.route("/api/admin/pruned-tickers")
def api_pruned_tickers():
    """List tickers the warm-cache prune logic has dropped from the
    universe — plus tickers approaching the threshold so the user can
    see what's about to be dropped."""
    return jsonify(screener.prune_status())


@app.route("/api/admin/pruned-tickers/restore", methods=["POST"])
def api_pruned_tickers_restore():
    """Restore one or more pruned tickers. Body: {"tickers": [...]} for
    a targeted restore, or {"all": true} to reset every counter and
    unprune everything."""
    payload = request.get_json(silent=True) or {}
    tickers = payload.get("tickers")
    if payload.get("all"):
        tickers = None
    elif tickers is not None and not isinstance(tickers, list):
        return jsonify({"error": "tickers must be a list"}), 400
    elif tickers is None:
        return jsonify({"error": "specify {tickers: [...]} or {all: true}"}), 400
    n = screener.restore_pruned(tickers)
    # Force tickers.universe() to re-read the JSON so the next /api/screen
    # call sees the restored ticker(s) without a server restart.
    from tickers import invalidate_pruned_cache
    invalidate_pruned_cache()
    return jsonify({"restored": n, "status": screener.prune_status()})


@app.route("/api/admin/snapshot", methods=["POST"])
def api_take_snapshot():
    """Manually trigger a Postgres snapshot of the current pickle cache.
    Runs in a background thread so the request returns immediately —
    poll /api/admin/snapshot/status for progress. No-ops with
    enabled=false when DATABASE_URL isn't set."""
    if not snapshots.enabled():
        return jsonify({"enabled": False,
                        "error": "DATABASE_URL not set"}), 400
    # Background-spawn so the HTTP request doesn't hold open for the
    # full ~1-2 minute snapshot pass.
    started = False
    if not screener.snapshot_status().get("running"):
        screener._snapshot_thread = threading.Thread(
            target=screener.take_snapshot, daemon=True, name="manual-snapshot",
        )
        screener._snapshot_thread.start()
        started = True
    return jsonify({"started": started, "status": screener.snapshot_status()})


@app.route("/api/admin/snapshot/cancel", methods=["POST"])
def api_cancel_snapshot():
    cancelled = screener.cancel_snapshot()
    return jsonify({"cancelled": cancelled, "status": screener.snapshot_status()})


@app.route("/api/admin/snapshot/status")
def api_snapshot_status():
    return jsonify({
        "enabled": snapshots.enabled(),
        "available_dates": snapshots.available_dates(10),
        "date_counts": snapshots.date_counts(10),
        "retention_days": snapshots.RETENTION_DAYS,
        "diagnostics": snapshots.diagnostics(),
        **screener.snapshot_status(),
    })


@app.route("/api/setups")
def api_setups():
    """Scan the most recent snapshot for base-breakout / momentum-
    ignition setups. Synchronous — typically 5-15s on a ~1k-candidate
    pre-filtered pool. Query params:
      date       YYYY-MM-DD (defaults to the latest snapshot)
      min_score  0-100 (defaults to 65)
      limit      max results (defaults to 25, capped at 100)
    """
    if not snapshots.enabled():
        return jsonify({"error": "DATABASE_URL not set — snapshot required"}), 400
    raw_date = (request.args.get("date") or "").strip()
    available = snapshots.available_dates(50)
    if not available:
        return jsonify({"error": "no snapshot rows yet — warm the cache first"}), 400
    as_of = raw_date if raw_date in available else available[0]
    try:
        min_score = float(request.args.get("min_score", "65"))
    except (TypeError, ValueError):
        min_score = 65.0
    try:
        limit = int(request.args.get("limit", "25"))
    except (TypeError, ValueError):
        limit = 25
    limit = max(1, min(limit, 100))
    try:
        min_price = float(request.args.get("min_price", "3"))
    except (TypeError, ValueError):
        min_price = 3.0
    try:
        max_price = float(request.args.get("max_price", "1000"))
    except (TypeError, ValueError):
        max_price = 1000.0
    try:
        min_dollar_vol = float(request.args.get("min_dollar_vol", "1000000"))
    except (TypeError, ValueError):
        min_dollar_vol = 1_000_000.0
    # Optional per-sub-score floors (0–100, default 0 = off). Used by
    # the Setup criteria modal so a rule can require e.g. base_min=70 +
    # ignition_min=50 on top of the overall score_min.
    def _flt_arg(name: str) -> float:
        try:
            return float(request.args.get(name, "0"))
        except (TypeError, ValueError):
            return 0.0
    base_min     = _flt_arg("base_min")
    ignition_min = _flt_arg("ignition_min")
    earliness_min = _flt_arg("earliness_min")
    started = time.time()
    results = pattern_scan.scan_setups(
        as_of, min_score=min_score, limit=limit,
        min_price=min_price, max_price=max_price,
        min_dollar_vol=min_dollar_vol,
        base_min=base_min, ignition_min=ignition_min, earliness_min=earliness_min,
    )
    elapsed = round(time.time() - started, 1)
    return jsonify({
        "as_of": as_of,
        "available_dates": available,
        "min_score": min_score,
        "limit": limit,
        "min_price": min_price,
        "max_price": max_price,
        "min_dollar_vol": min_dollar_vol,
        "results": results,
        "elapsed_sec": elapsed,
    })


@app.route("/api/setups/inspect")
def api_setups_inspect():
    """Score one or more named tickers regardless of any threshold or
    prefilter — for calibrating the Setups scoring against real data.
    Query params:
      tickers  comma-separated ticker symbols (required)
      date     YYYY-MM-DD (defaults to the latest snapshot)
    Returns the full breakdown dict for each ticker, plus a `note`
    when a ticker has no snapshot row or insufficient bars.
    """
    if not snapshots.enabled():
        return jsonify({"error": "DATABASE_URL not set — snapshot required"}), 400
    raw = (request.args.get("tickers") or "").strip()
    if not raw:
        return jsonify({"error": "tickers query param required"}), 400
    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
    if not tickers:
        return jsonify({"error": "no valid tickers parsed"}), 400
    raw_date = (request.args.get("date") or "").strip()
    available = snapshots.available_dates(50)
    if not available:
        return jsonify({"error": "no snapshot rows yet"}), 400
    as_of = raw_date if raw_date in available else available[0]
    found: dict[str, dict] = {}
    for t, row in snapshots.iter_for_date(as_of, tickers=tickers):
        found[t] = row
    out = []
    for t in tickers:
        row = found.get(t)
        if not row:
            out.append({"ticker": t, "note": "no snapshot row for this date"})
            continue
        bars_payload = row.get("recent_bars") or {}
        if isinstance(bars_payload, str):
            import json as _json
            try:
                bars_payload = _json.loads(bars_payload)
            except Exception:
                bars_payload = {}
        bars = (bars_payload or {}).get("bars") or []
        try:
            result = pattern_scan.score_base_breakout(bars, row)
        except Exception as exc:
            out.append({"ticker": t, "note": f"score error: {exc}"})
            continue
        if result is None:
            out.append({"ticker": t, "note": "insufficient bars"})
            continue
        result["ticker"] = t
        out.append(result)
    return jsonify({"as_of": as_of, "tickers": tickers, "results": out})


@app.route("/api/admin/cache-status")
def api_cache_status():
    """Report disk-cache freshness for the currently-selected universe.
    Lets the UI tell the user whether a screen will be warm (fast, disk)
    or cold (slow, will hit Yahoo for thousands of tickers)."""
    from tickers import universe as build_universe

    raw_lists = request.args.get("lists", "")
    if raw_lists.strip():
        wanted = [s.strip() for s in raw_lists.split(",") if s.strip()]
        wanted = [s for s in wanted if s in _VALID_LISTS]
    else:
        wanted = sorted(_VALID_LISTS)
    if not wanted:
        wanted = sorted(_VALID_LISTS)
    tickers = build_universe(wanted)
    raw_extras = request.args.get("extras", "")
    if raw_extras.strip():
        seen = set(tickers)
        for s in raw_extras.split(","):
            t = s.strip().upper()
            if t and t not in seen:
                seen.add(t)
                tickers.append(t)
    return jsonify(screener.cache_status(tickers))


@app.route("/api/admin/refresh-universe", methods=["POST"])
def api_refresh_universe():
    """Drop the disk + in-memory caches of the US symbol directory and
    rebuild from a fresh fetch. Returns the new per-exchange counts plus
    any fetch errors so a 403/timeout shows up in the UI status line."""
    try:
        # Also bust the in-memory screen cache since the universe just changed.
        with _screen_lock:
            _screen_cache.clear()
        sizes = refresh_universe()
        errors = last_fetch_errors()
        return jsonify({"ok": True, "sizes": sizes, "errors": errors})
    except Exception as exc:
        log.warning("refresh_universe failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/debug/<path:ticker>")
def api_debug(ticker: str):
    """Run each filter against a single ticker and return a pass/fail
    breakdown — used by the "Diagnose" panel in the UI to explain why a
    given ticker did or did not match a screen."""
    params = _parse_params()
    result = screener.diagnose_ticker(
        ticker.upper().strip(),
        high_lookback=params["high_lookback"],
        streak_mode=params["streak_mode"],
        rsi_min=params["rsi_min"],
        rsi_max=params["rsi_max"],
        rsi_dev_min_pct=params["rsi_dev_min_pct"],
        rsi_dev_max_pct=params["rsi_dev_max_pct"],
        rvol_lookback=params["rvol_lookback"],
        rvol_min=params["rvol_min"],
        avg_volume_min=params["avg_volume_min"],
        price_min=params["price_min"],
        price_max=params["price_max"],
        price_dev_min_pct=params["price_dev_min_pct"],
        price_dev_max_pct=params["price_dev_max_pct"],
        ema_dev_min_pct=params["ema_dev_min_pct"],
        ema_dev_max_pct=params["ema_dev_max_pct"],
        macd_within_pct=params["macd_within_pct"],
        macd_above_signal=params["macd_above_signal"],
        macd_vs_signal_pct=params["macd_vs_signal_pct"],
        macd_line_rising=params["macd_line_rising"],
        turnover_min_pct=params["turnover_min_pct"],
        turnover_max_pct=params["turnover_max_pct"],
        market_cap_min_m=params["market_cap_min_m"],
        market_cap_max_m=params["market_cap_max_m"],
        pct_change_min=params["pct_change_min"],
        apply_high=params["apply_high"],
        apply_rsi=params["apply_rsi"],
        apply_rsi_dev=params["apply_rsi_dev"],
        apply_rsi_rising=params["apply_rsi_rising"],
        apply_rvol=params["apply_rvol"],
        apply_avg_volume=params["apply_avg_volume"],
        apply_price=params["apply_price"],
        apply_price_dev=params["apply_price_dev"],
        apply_ema_dev=params["apply_ema_dev"],
        apply_macd_vs_signal=params["apply_macd_vs_signal"],
        apply_macd_hist_rising=params["apply_macd_hist_rising"],
        apply_turnover=params["apply_turnover"],
        apply_market_cap=params["apply_market_cap"],
        apply_pct_change=params["apply_pct_change"],
        apply_sma_revival=params["apply_sma_revival"],
        sma_cross_lookback=params["sma_cross_lookback"],
        sma_slope_turn_lookback=params["sma_slope_turn_lookback"],
        sma_slope_window=params["sma_slope_window"],
        sma_min_slope_pct=params["sma_min_slope_pct"],
        sma_require_long_flat=params["sma_require_long_flat"],
        sma_long_flat_max_pct=params["sma_long_flat_max_pct"],
        sma_require_volume=params["sma_require_volume"],
        sma_volume_mult=params["sma_volume_mult"],
        as_of_offset=params["as_of_offset"],
        as_of_date=params.get("as_of_date_resolved"),
    )
    return jsonify(result)


@app.route("/api/calc/stoch-reverse")
def api_calc_stoch_reverse():
    """Reverse Slow %K calculator — see calculators.stoch_reverse. Solves
    for the price the next bar(s) must trade at for the stochastic
    Slow %K to reach the oversold / overbought thresholds."""
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400
    interval = (request.args.get("interval") or "1d").strip().lower()
    if interval not in calculators.INTERVALS:
        return jsonify({"error": f"unsupported interval '{interval}'"}), 400

    def _bounded_int(name: str, dflt: int, lo: int, hi: int) -> int:
        try:
            v = int(float(request.args.get(name) or dflt))
        except (TypeError, ValueError):
            v = dflt
        return max(lo, min(hi, v))

    k_len = _bounded_int("k_len", 14, 2, 50)
    smooth = _bounded_int("smooth", 3, 1, 10)
    overbought = max(0.0, min(100.0, _flt("overbought", 80.0)))
    oversold = max(0.0, min(100.0, _flt("oversold", 20.0)))
    if oversold >= overbought:
        return jsonify({"error": "oversold threshold must be below "
                                 "the overbought threshold"}), 400
    # Optional backtest anchor — "YYYY-MM-DD" or "YYYY-MM-DD HH:MM"
    # (datetime-local's "T" separator accepted).
    as_of = (request.args.get("as_of") or "").strip()
    if as_of and calculators.normalize_anchor(as_of) is None:
        return jsonify({"error": "as_of must look like YYYY-MM-DD or "
                                 "YYYY-MM-DD HH:MM"}), 400
    # Path model + how many future bars to solve for.
    path = (request.args.get("path") or "hold").strip().lower()
    if path not in ("hold", "drift"):
        return jsonify({"error": "path must be 'hold' or 'drift'"}), 400
    horizon = _bounded_int("horizon", smooth, 1, max(1, k_len - 1))
    try:
        result = calculators.stoch_reverse(
            ticker, interval, k_len=k_len, smooth=smooth,
            overbought=overbought, oversold=oversold,
            as_of=as_of or None, path=path, horizon=horizon)
    except Exception as exc:
        import traceback
        log.error("stoch-reverse failed for %s/%s: %s\n%s",
                  ticker, interval, exc, traceback.format_exc())
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify(result)


# Column order + display labels for the Excel export. Keys must match the
# fields produced by ScreenHit.to_dict().
_EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("ticker", "Ticker"),
    ("momentum_score", "Momentum"),
    ("name", "Name"),
    ("exchange", "Exchange"),
    ("as_of_date", "As-of date"),
    ("close", "Close"),
    ("prev_close", "Prior close"),
    ("pct_change", "% change"),
    ("high_lookback", "Streak high"),
    ("rsi", "RSI(14)"),
    ("rsi_sma9", "9d SMA RSI"),
    ("rsi_dev_pct", "RSI dev %"),
    ("ema21", "EMA(21)"),
    ("price_ema21_dev_pct", "Price vs EMA21 %"),
    ("ema50", "EMA(50)"),
    ("ema21_ema50_dev_pct", "EMA21 vs EMA50 %"),
    ("rel_volume", "RVol"),
    ("avg_volume", "Avg volume"),
    ("volume", "Volume"),
    ("shares", "Shares outstanding"),
    ("market_cap", "Market cap"),
    ("turnover_pct", "Turnover %"),
    ("score", "Score"),
]


@app.route("/api/export/xlsx", methods=["POST"])
def api_export_xlsx():
    """Build an .xlsx workbook from a JSON `rows` array and stream it back."""
    import pandas as pd

    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return jsonify({"error": "no rows provided"}), 400

    df = pd.DataFrame(rows)
    keep_keys = [k for k, _ in _EXPORT_COLUMNS if k in df.columns]
    rename_map = {k: label for k, label in _EXPORT_COLUMNS if k in df.columns}
    df = df[keep_keys].rename(columns=rename_map)

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Screened", index=False)
        # Auto-size columns to content for readability.
        ws = writer.sheets["Screened"]
        for col_cells in ws.columns:
            length = max(len(str(c.value)) if c.value is not None else 0 for c in col_cells)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 8), 30)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name="trading-ma-export.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/alerts/watchlist", methods=["GET"])
def api_alerts_watchlist():
    """Tickers currently monitored by the realtime alert engine."""
    return jsonify({
        "enabled": alerts.enabled(),
        "tickers": alerts.get_watchlist(),
    })


@app.route("/api/alerts/watchlist", methods=["POST"])
def api_alerts_watchlist_add():
    """Add tickers to the alert watchlist (JSON body: {"tickers": [...]})."""
    if not alerts.enabled():
        return jsonify({"error": "DATABASE_URL not set"}), 400
    payload = request.get_json(silent=True) or {}
    tickers = payload.get("tickers") or []
    if not isinstance(tickers, list) or not tickers:
        return jsonify({"error": "no tickers provided"}), 400
    added = alerts.add_to_watchlist([str(t) for t in tickers])
    return jsonify({"added": added, "tickers": alerts.get_watchlist()})


@app.route("/api/alerts/watchlist/remove", methods=["POST"])
def api_alerts_watchlist_remove():
    """Remove one ticker (JSON body: {"ticker": "AAPL"})."""
    if not alerts.enabled():
        return jsonify({"error": "DATABASE_URL not set"}), 400
    payload = request.get_json(silent=True) or {}
    ticker = (payload.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "no ticker provided"}), 400
    removed = alerts.remove_from_watchlist(ticker)
    return jsonify({"removed": removed, "tickers": alerts.get_watchlist()})


@app.route("/api/alerts/rules", methods=["GET"])
def api_alerts_rules():
    """All alert rules — each scoped to the watchlist, a sector, or an
    industry, with its own filter criteria."""
    return jsonify({
        "enabled": alerts.enabled(),
        "rules": alerts.list_rules(),
        "classification": alerts.classification_status(),
    })


@app.route("/api/alerts/rules", methods=["POST"])
def api_alerts_rule_create():
    """Create an alert rule. JSON body: {name, scope_type, scope_value,
    rule_type, setup_params?}.
      - rule_type='screener' (default): criteria taken from screener
        filters in the query string (same params /api/screen accepts).
      - rule_type='setup': criteria from `setup_params` in the JSON
        body — see alerts.SETUP_DEFAULT_PARAMS for the accepted keys
        (score_min, the price / dollar-volume band, and the optional
        per-sub-score floors base_min / ignition_min / earliness_min).
    """
    if not alerts.enabled():
        return jsonify({"error": "DATABASE_URL not set"}), 400
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    scope_type = (payload.get("scope_type") or "").strip().lower()
    scope_value = (payload.get("scope_value") or "").strip()
    rule_type = (payload.get("rule_type") or "screener").strip().lower()
    if not name:
        return jsonify({"error": "rule name required"}), 400
    if rule_type not in alerts.RULE_TYPES:
        return jsonify({"error": "invalid rule_type"}), 400
    if scope_type not in alerts.SCOPE_TYPES:
        return jsonify({"error": "invalid scope_type"}), 400
    if scope_type == "all" and rule_type != "setup":
        return jsonify({"error": "scope 'all' is only valid for setup rules"}), 400
    if scope_type in ("sector", "industry") and not scope_value:
        return jsonify({"error": "scope_value required for sector/industry rules"}), 400
    if scope_type == "tickers" and not alerts.normalize_ticker_scope(scope_value):
        return jsonify({"error": "enter 1-"
                                 f"{alerts.MAX_SCOPE_TICKERS} ticker symbols "
                                 "for the specific-tickers scope"}), 400
    if rule_type == "setup":
        sp = payload.get("setup_params") or {}
        # Drive the whitelist off alerts._SETUP_PARAM_KEYS (the canonical
        # set derived from SETUP_DEFAULT_PARAMS) so new floor keys added
        # there flow through here automatically. A previous hand-rolled
        # 4-tuple silently dropped base_min/ignition_min/earliness_min.
        params = {k: sp[k] for k in alerts._SETUP_PARAM_KEYS if k in sp}
    elif rule_type == "stoch":
        sp = payload.get("stoch_params") or {}
        params = {k: sp[k] for k in alerts._STOCH_PARAM_KEYS if k in sp}
    else:
        params = _parse_params()
        params.pop("lists", None)  # not an evaluate_ticker kwarg
    rule_id = alerts.add_rule(name, scope_type, scope_value, params, rule_type=rule_type)
    if rule_id is None:
        return jsonify({"error": "could not create rule"}), 500
    return jsonify({"id": rule_id, "rules": alerts.list_rules()})


@app.route("/api/alerts/rules/delete", methods=["POST"])
def api_alerts_rule_delete():
    if not alerts.enabled():
        return jsonify({"error": "DATABASE_URL not set"}), 400
    payload = request.get_json(silent=True) or {}
    ok = alerts.delete_rule(int(payload.get("id", 0)))
    return jsonify({"deleted": ok, "rules": alerts.list_rules()})


@app.route("/api/alerts/rules/toggle", methods=["POST"])
def api_alerts_rule_toggle():
    if not alerts.enabled():
        return jsonify({"error": "DATABASE_URL not set"}), 400
    payload = request.get_json(silent=True) or {}
    ok = alerts.set_rule_enabled(int(payload.get("id", 0)), bool(payload.get("enabled")))
    return jsonify({"updated": ok, "rules": alerts.list_rules()})


@app.route("/api/alerts/rules/update-criteria", methods=["POST"])
def api_alerts_rule_update_criteria():
    """Replace a rule's criteria with the current filters. For screener
    rules, criteria come from the query string (same params /api/screen
    accepts). For setup rules, send `setup_params` in the JSON body."""
    if not alerts.enabled():
        return jsonify({"error": "DATABASE_URL not set"}), 400
    payload = request.get_json(silent=True) or {}
    rule_id = int(payload.get("id", 0))
    sp = payload.get("setup_params")
    stp = payload.get("stoch_params")
    if sp:
        # Same single-source-of-truth pattern as api_alerts_rule_create.
        params = {k: sp[k] for k in alerts._SETUP_PARAM_KEYS if k in sp}
    elif stp:
        params = {k: stp[k] for k in alerts._STOCH_PARAM_KEYS if k in stp}
    else:
        params = _parse_params()
        params.pop("lists", None)
    ok = alerts.set_rule_params(rule_id, params)
    return jsonify({"updated": ok, "rules": alerts.list_rules()})


@app.route("/api/alerts/rules/update", methods=["POST"])
def api_alerts_rule_update():
    """Edit a rule's name / scope_type / scope_value. Body:
        {id, name?, scope_type?, scope_value?}
    Missing fields are left unchanged. rule_type is intentionally
    immutable — switching it would invalidate params; delete + recreate
    if that's the intent."""
    if not alerts.enabled():
        return jsonify({"error": "DATABASE_URL not set"}), 400
    payload = request.get_json(silent=True) or {}
    try:
        rule_id = int(payload.get("id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "id required"}), 400
    if not rule_id:
        return jsonify({"error": "id required"}), 400
    if ((payload.get("scope_type") or "").strip().lower() == "tickers"
            and not alerts.normalize_ticker_scope(payload.get("scope_value"))):
        return jsonify({"error": "enter 1-"
                                 f"{alerts.MAX_SCOPE_TICKERS} ticker symbols "
                                 "for the specific-tickers scope"}), 400
    ok = alerts.update_rule(
        rule_id,
        name=payload.get("name"),
        scope_type=payload.get("scope_type"),
        scope_value=payload.get("scope_value"),
    )
    if not ok:
        # Surface the failure — a 200 with updated:false read as success
        # in the UI, so a rejected save looked like a saved one.
        return jsonify({"error": "rule update was not saved — check the "
                                 "name and scope values", "updated": False}), 400
    return jsonify({"updated": True, "rules": alerts.list_rules()})


@app.route("/api/alerts/rules/history", methods=["GET"])
def api_alerts_rule_history():
    """Recent trigger events for one rule — (timestamp, match count) per
    minute-grouped event, newest first."""
    try:
        rule_id = int(request.args.get("id", "0"))
    except (TypeError, ValueError):
        rule_id = 0
    try:
        limit = int(request.args.get("limit", "20"))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))
    return jsonify({
        "id": rule_id,
        "history": alerts.rule_trigger_history(rule_id, limit),
    })


@app.route("/api/alerts/scopes", methods=["GET"])
def api_alerts_scopes():
    """Distinct sectors and industries for the rule-builder dropdowns."""
    return jsonify(alerts.list_scopes())


# --- nightly picker -------------------------------------------------------
# Stage 1 of the watchlist workflow: rank every snapshot ticker by the
# 5-signal composite (VC / RS / VA / MT / DP) and surface the top 10.
# /api/picks returns the most recent persisted ranking; /api/picks/run
# re-ranks live using the supplied (or saved) config; /api/picks/config
# persists weights + price range for the nightly cron to pick up.

@app.route("/api/picks", methods=["GET"])
def api_picks():
    return jsonify({
        "picks":  picker.load_picks(),
        "config": picker.get_config(),
    })


@app.route("/api/picks/run", methods=["POST"])
def api_picks_run():
    """Re-rank the universe now. Synchronous — expect 5-30s depending
    on universe size. Body: {weights?, price_min?, price_max?,
    pick_limit?, save?}. `save=true` (default) overwrites the latest
    persisted picks and saves the config so the next nightly cron uses
    these settings."""
    payload = request.get_json(silent=True) or {}
    cfg = picker.get_config()
    weights = payload.get("weights")
    if not isinstance(weights, dict):
        weights = cfg["weights"]
    try:
        price_min = float(payload.get("price_min", cfg["price_min"]))
        price_max = float(payload.get("price_max", cfg["price_max"]))
    except (TypeError, ValueError):
        return jsonify({"error": "price_min / price_max must be numeric"}), 400
    pick_limit = picker._clamp_limit(payload.get("pick_limit", cfg["pick_limit"]))
    save = bool(payload.get("save", True))
    # Absolute-quality gates (tunable from the "Tune…" panel).
    try:
        min_composite = float(payload.get("min_composite", cfg["min_composite"]))
        confirm_min = float(payload.get("confirm_min", cfg["confirm_min"]))
    except (TypeError, ValueError):
        return jsonify({"error": "min_composite / confirm_min must be numeric"}), 400
    require_confirmation = bool(payload.get("require_confirmation",
                                           cfg["require_confirmation"]))

    picks, as_of = picker.rank_universe(
        weights=weights, price_min=price_min, price_max=price_max,
        limit=pick_limit,
        min_composite=min_composite,
        require_confirmation=require_confirmation,
        confirm_min=confirm_min,
    )
    if save:
        picker.save_config(weights, price_min, price_max, pick_limit=pick_limit,
                           min_composite=min_composite,
                           require_confirmation=require_confirmation,
                           confirm_min=confirm_min)
        if picks and as_of:
            picker.save_picks(picks, as_of)
    return jsonify({
        "picks": picks,
        "as_of": as_of,
        "config": picker.get_config(),
    })


@app.route("/api/picks/intraday-alerts", methods=["GET"])
def api_picks_intraday_alerts():
    """Intraday trigger alerts for the requested date (default: today's
    most recent date in picker_intraday_alerts). Used by the UI to
    badge each pick row with whatever's fired today."""
    date = (request.args.get("date") or "").strip() or None
    return jsonify({"alerts": picker.intraday_alerts_for_date(date)})


@app.route("/api/picks/intraday-alerts/enabled", methods=["POST"])
def api_picks_intraday_alerts_toggle():
    """UI kill-switch for the picker_intraday workflow. When OFF, the
    GitHub Actions cron still fires every 5 min but picker_intraday.run
    exits immediately — no Alpaca calls, no DB writes, no Telegram."""
    payload = request.get_json(silent=True) or {}
    if "enabled" not in payload:
        return jsonify({"error": "missing 'enabled' boolean"}), 400
    enabled = bool(payload["enabled"])
    if not picker.set_intraday_alerts_enabled(enabled):
        return jsonify({"error": "could not persist toggle"}), 500
    return jsonify({"enabled": picker.get_config()["intraday_alerts_enabled"]})


@app.route("/api/picks/config", methods=["POST"])
def api_picks_config():
    """Save picker config without recomputing."""
    payload = request.get_json(silent=True) or {}
    cfg = picker.get_config()
    weights = payload.get("weights") if isinstance(payload.get("weights"), dict) else cfg["weights"]
    try:
        price_min = float(payload.get("price_min", cfg["price_min"]))
        price_max = float(payload.get("price_max", cfg["price_max"]))
        min_composite = float(payload.get("min_composite", cfg["min_composite"]))
        confirm_min = float(payload.get("confirm_min", cfg["confirm_min"]))
    except (TypeError, ValueError):
        return jsonify({"error": "numeric fields must be numeric"}), 400
    require_confirmation = bool(payload.get("require_confirmation",
                                           cfg["require_confirmation"]))
    ok = picker.save_config(weights, price_min, price_max,
                            min_composite=min_composite,
                            require_confirmation=require_confirmation,
                            confirm_min=confirm_min)
    return jsonify({"saved": ok, "config": picker.get_config()})


# --- paper portfolio ------------------------------------------------------
# A simulated $500k book. Buys are booked from the stock screener (day's
# close) or the options screener (contract mid), each lot tagged with the
# filter setup it came from. Mark-to-market + the equity curve are filled
# by a nightly cron (added separately).

@app.route("/api/portfolio", methods=["GET"])
def api_portfolio():
    import paper_portfolio as pp
    return jsonify({
        "portfolio": pp.get_portfolio(),
        "summary": pp.summary(),
        "positions": {
            "open": pp.list_positions("open"),
            "closed": pp.list_positions("closed"),
        },
    })


@app.route("/api/portfolio/buy", methods=["POST"])
def api_portfolio_buy():
    """Book a lot. Body (stock): {asset_type:'stock', ticker, qty, price,
    entry_date?, source_label?, source_filter?}. Body (option):
    {asset_type:'option', ticker, option_type, strike, expiration,
    contracts, mid, entry_date?, source_label?, source_filter?}."""
    import paper_portfolio as pp
    payload = request.get_json(silent=True) or {}
    atype = str(payload.get("asset_type") or "").strip().lower()
    src_label = payload.get("source_label")
    src_filter = payload.get("source_filter")
    entry_date = payload.get("entry_date")
    if atype == "stock":
        r = pp.buy_stock(payload.get("ticker"), payload.get("qty"),
                         payload.get("price"), entry_date, src_label, src_filter)
    elif atype == "option":
        r = pp.buy_option(payload.get("ticker"), payload.get("option_type"),
                          payload.get("strike"), payload.get("expiration"),
                          payload.get("contracts"), payload.get("mid"),
                          entry_date, src_label, src_filter)
    else:
        return jsonify({"ok": False, "error": "asset_type must be 'stock' or 'option'"}), 400
    status = 200 if r.get("ok") else (409 if r.get("error") == "insufficient_cash" else 400)
    return jsonify(r), status


@app.route("/api/portfolio/sell", methods=["POST"])
def api_portfolio_sell():
    """Close a whole lot. Body: {position_id, price?}. Without `price`, the
    lot's last mark is used, else a live price is fetched."""
    import paper_portfolio as pp
    payload = request.get_json(silent=True) or {}
    pid = payload.get("position_id")
    if pid is None:
        return jsonify({"ok": False, "error": "position_id required"}), 400
    raw_price = payload.get("price")
    try:
        price = float(raw_price) if raw_price not in (None, "") else None
        r = pp.sell_position(int(pid), price)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "position_id / price must be numeric"}), 400
    status = 200 if r.get("ok") else (404 if r.get("error") == "not_found" else 400)
    return jsonify(r), status


@app.route("/api/portfolio/equity", methods=["GET"])
def api_portfolio_equity():
    import paper_portfolio as pp
    return jsonify({"equity": pp.equity_curve()})


@app.route("/api/portfolio/by-source", methods=["GET"])
def api_portfolio_by_source():
    import paper_portfolio as pp
    return jsonify({"by_source": pp.pnl_by_source()})


# --- filter presets (cross-device persistence) ----------------------------
# Stored in Postgres so the same saved filter setups load on every device.
# Cap is enforced server-side via filter_presets.MAX_PRESETS. Falls back
# silently when DATABASE_URL isn't set (the UI then keeps the legacy
# localStorage behaviour).

@app.route("/api/filter-presets", methods=["GET"])
def api_filter_presets_list():
    return jsonify(filter_presets.list_presets())


@app.route("/api/filter-presets", methods=["POST"])
def api_filter_presets_mutate():
    """Body: {action: "save"|"delete"|"select"|"reset", name?, state?}.
    Returns the refreshed list_presets() payload so the client doesn't
    have to round-trip."""
    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").strip().lower()
    name = payload.get("name") or ""
    if action == "save":
        result = filter_presets.save_preset(name, payload.get("state") or {})
    elif action == "delete":
        result = filter_presets.delete_preset(name)
    elif action == "select":
        result = filter_presets.mark_used(name)
    elif action == "reset":
        result = filter_presets.clear_last_used()
    else:
        return jsonify({"error": "unknown action"}), 400
    status = 200 if result.get("ok") else 409 if result.get("error") == "cap_reached" else 400
    if not result.get("ok") and result.get("error") not in ("cap_reached",):
        status = 500 if result.get("error") == "db_error" else 400
    response = {**result, **filter_presets.list_presets()}
    return jsonify(response), status


# --- UI prefs (cross-device persistence) ----------------------------------
# Key/value bag for things like column layout, collapsed-section state,
# active tab, etc. — anything that used to live in browser localStorage.
# The page render also injects these into window.__UI_PREFS__ so the JS
# can read them synchronously; these endpoints handle writes and a fresh
# read for clients that don't trust the server-rendered cache.

@app.route("/api/ui-prefs", methods=["GET"])
def api_ui_prefs_get():
    return jsonify(ui_prefs.get_all())


@app.route("/api/ui-prefs", methods=["POST"])
def api_ui_prefs_set():
    """Body: {key, value} for a single upsert, or {prefs: {...}} for a
    batch (used by the one-time localStorage migration)."""
    payload = request.get_json(silent=True) or {}
    # Batch path — migration uploads everything in one POST.
    if isinstance(payload.get("prefs"), dict):
        failed = []
        for k, v in payload["prefs"].items():
            r = ui_prefs.set_pref(k, v)
            if not r.get("ok"):
                failed.append({"key": k, "error": r.get("error")})
        return jsonify({"ok": not failed, "failed": failed, "prefs": ui_prefs.get_all()})
    # Single-key path — typical write from a UI interaction.
    key = payload.get("key")
    if "value" not in payload:
        return jsonify({"ok": False, "error": "value required"}), 400
    result = ui_prefs.set_pref(key, payload.get("value"))
    status = 200 if result.get("ok") else 400 if result.get("error") in ("empty_key", "key_too_long", "unserialisable_value") else 500
    return jsonify(result), status


# --- real-time momentum scanner -------------------------------------------
# Independent of the nightly watchlist. Walks the full snapshot universe
# every 5 min during market hours via .github/workflows/momentum-scanner.yml
# and fires Telegram whenever a ticker passes all 4 filters (pct change,
# RVOL, new N-day high, vol/mcap). UI panel lets the user tune thresholds;
# /api/momentum/alerts feeds today's hit list back to the panel.

@app.route("/api/momentum/config", methods=["GET"])
def api_momentum_config():
    return jsonify({"config": scanner_momentum.get_config()})


@app.route("/api/momentum/config", methods=["POST"])
def api_momentum_save_config():
    payload = request.get_json(silent=True) or {}
    cfg = scanner_momentum.get_config()
    try:
        pct_change_min = float(payload.get("pct_change_min", cfg["pct_change_min"]))
        rvol_min       = float(payload.get("rvol_min",       cfg["rvol_min"]))
        rvol_lookback  = int(payload.get("rvol_lookback",    cfg["rvol_lookback"]))
        high_lookback  = int(payload.get("high_lookback",    cfg["high_lookback"]))
        vol_mcap_min   = float(payload.get("vol_mcap_min",   cfg["vol_mcap_min"]))
        mcap_min_m     = float(payload.get("mcap_min_m",     cfg["mcap_min_m"]))
        mcap_max_m     = float(payload.get("mcap_max_m",     cfg["mcap_max_m"]))
    except (TypeError, ValueError):
        return jsonify({"error": "all fields must be numeric"}), 400
    if rvol_lookback < 1 or high_lookback < 1:
        return jsonify({"error": "lookback windows must be >= 1 day"}), 400
    if mcap_min_m < 0 or mcap_max_m <= 0 or mcap_min_m >= mcap_max_m:
        return jsonify({"error": "market-cap band must satisfy 0 <= min < max"}), 400
    ok = scanner_momentum.save_config(
        pct_change_min, rvol_min, rvol_lookback, high_lookback, vol_mcap_min,
        mcap_min_m, mcap_max_m,
    )
    return jsonify({"saved": ok, "config": scanner_momentum.get_config()})


@app.route("/api/momentum/alerts", methods=["GET"])
def api_momentum_alerts():
    date = (request.args.get("date") or "").strip() or None
    return jsonify({"alerts": scanner_momentum.alerts_for_date(date)})


# --- Options recommender --------------------------------------------------
# Two endpoints. /lookup runs the full pipeline on-demand for a single
# ticker (1-3s incl. yfinance round-trips); /recommendations reads the
# persisted output from the nightly scanner (Phase 2). Lookup also
# persists its result so subsequent /recommendations calls show it.

@app.route("/api/options/lookup", methods=["GET"])
def api_options_lookup():
    import options
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "ticker query param required"}), 400
    dte_min_raw = request.args.get("dte_min")
    dte_max_raw = request.args.get("dte_max")
    try:
        dte_min = int(dte_min_raw) if dte_min_raw else options.DEFAULT_DTE_MIN
        dte_max = int(dte_max_raw) if dte_max_raw else options.DEFAULT_DTE_MAX
    except (TypeError, ValueError):
        return jsonify({"error": "dte_min/dte_max must be integers"}), 400
    rec = options.recommend_for_ticker(ticker, dte_min=dte_min, dte_max=dte_max)
    if rec.get("composite_score") is not None:
        # Persist any analyzed ticker (even WATCH/PASS) — useful for
        # the daily history view; load_recommendations sorts by score.
        options.save_recommendation(rec)
    return jsonify(rec)


@app.route("/api/options/recommendations", methods=["GET"])
def api_options_recommendations():
    import options
    as_of = (request.args.get("date") or "").strip() or None
    return jsonify({"recommendations": options.load_recommendations(as_of)})


@app.route("/api/options/recommendation_dates", methods=["GET"])
def api_options_recommendation_dates():
    """Distinct as_of dates with recs, most recent first. Powers the
    date picker on the Recent recommendations panel."""
    import options
    return jsonify({"dates": options.available_rec_dates(limit=60)})


@app.route("/api/options/pinned", methods=["GET", "POST"])
def api_options_pinned():
    """GET → list every pinned rec (full snapshot each), newest first.
    POST body {ticker, as_of, note?} → snapshot the live rec into the
    pin store. Re-pinning the same (ticker, as_of) updates the note."""
    import options
    if request.method == "GET":
        return jsonify({"pinned": options.load_pinned()})
    body = request.get_json(silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    as_of  = (body.get("as_of")  or "").strip()
    note   = body.get("note") or ""
    if not ticker or not as_of:
        return jsonify({"error": "ticker and as_of are required"}), 400
    pin = options.pin_rec(ticker, as_of, note)
    if pin is None:
        return jsonify({"error": f"no recommendation found for {ticker} on {as_of}"}), 404
    return jsonify({"pin": pin})


@app.route("/api/options/pinned/<int:pin_id>", methods=["PATCH", "DELETE"])
def api_options_pinned_item(pin_id: int):
    """PATCH body {note} → update the note. DELETE → unpin."""
    import options
    if request.method == "DELETE":
        ok = options.unpin(pin_id)
        return jsonify({"deleted": ok}), (200 if ok else 404)
    body = request.get_json(silent=True) or {}
    note = body.get("note") or ""
    ok = options.update_pinned_note(pin_id, note)
    return jsonify({"updated": ok}), (200 if ok else 404)


@app.route("/api/options/scan", methods=["POST"])
def api_options_scan():
    """Kick off an async universe scan. Returns immediately — the UI
    polls /api/options/scan/status for progress. Body JSON (all
    optional): {"top_n": 50, "dte_min": 15, "dte_max": 60}

    Cap at 200 — gunicorn's 600s timeout is irrelevant now since the
    scan runs in a background thread, but the per-ticker work is
    unchanged so a Top 200 run takes ~40 min wall-clock."""
    import options_scanner
    body = request.get_json(silent=True) or {}
    # Fall back to the persisted UI settings for any field the request
    # body doesn't specify. Lets the user save defaults once and have
    # subsequent scans honor them without re-sending the full set.
    saved = options_scanner.load_settings()
    try:
        top_n   = int(body.get("top_n",   saved["top_n"]))
        dte_min = int(body.get("dte_min", saved["dte_min"]))
        dte_max = int(body.get("dte_max", saved["dte_max"]))
        price_floor  = float(body.get("price_floor",  saved["price_floor"]))
        volume_floor = float(body.get("volume_floor", saved["volume_floor"]))
        min_dist     = float(body.get("min_directional_distance",
                                       saved["min_directional_distance"]))
        mid_min      = float(body.get("mid_min", saved["mid_min"]))
        mid_max      = float(body.get("mid_max", saved["mid_max"]))
    except (TypeError, ValueError):
        return jsonify({"error": "scan params must be numeric"}), 400
    # Direction is a string enum — clamp client-side & whitelist here.
    direction = str(body.get("direction") or saved["direction"]).strip().lower()
    if direction not in ("call", "put", "both"):
        direction = "both"
    # Skip-scanned is a boolean — accept JSON bool or stringy truthy.
    raw_skip = body.get("skip_scanned", saved.get("skip_scanned", False))
    if isinstance(raw_skip, bool):
        skip_scanned = raw_skip
    else:
        skip_scanned = str(raw_skip).strip().lower() in ("1", "true", "yes", "on")
    top_n = max(1, min(top_n, 200))
    return jsonify(options_scanner.start_scan(
        top_n=top_n, dte_min=dte_min, dte_max=dte_max, persist=True,
        price_floor=price_floor, volume_floor=volume_floor,
        min_directional_distance=min_dist,
        mid_min=mid_min, mid_max=mid_max,
        direction=direction,
        skip_scanned=skip_scanned,
    ))


@app.route("/api/options/scan/status")
def api_options_scan_status():
    """Poll endpoint: current scan progress + last_result once the run
    finishes. Safe to call repeatedly while idle."""
    import options_scanner
    return jsonify(options_scanner.scan_status())


@app.route("/api/options/scan/cancel", methods=["POST"])
def api_options_scan_cancel():
    """Cancel the in-progress scan. The worker honors the request
    before its next ticker; partial results stay in last_result."""
    import options_scanner
    cancelled = options_scanner.cancel_scan()
    return jsonify({"cancelled": cancelled, **options_scanner.scan_status()})


@app.route("/api/options/scan/preview")
def api_options_scan_preview():
    """Run only the pre-score step (Gates 1 + 2) and return count
    breakdown so the UI can show 'X stocks qualify (Y bull / Z bear)'
    above the Scan button. Query params override saved settings for
    a live what-if (?price_floor=10&volume_floor=100000&min_directional_distance=5).
    `?force=1` bypasses the 5-min cache."""
    import options_scanner
    def _flt_param(name: str) -> float | None:
        raw = request.args.get(name)
        if raw is None or raw == "":
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    force = (request.args.get("force") or "").strip() in ("1", "true", "yes")
    return jsonify(options_scanner.preview_counts(
        price_floor=_flt_param("price_floor"),
        volume_floor=_flt_param("volume_floor"),
        min_directional_distance=_flt_param("min_directional_distance"),
        force=force,
    ))


@app.route("/api/options/scan/settings", methods=["GET", "PUT"])
def api_options_scan_settings():
    """GET — return the saved settings (or defaults if nothing saved).
    PUT body — same dict shape; upserts the single config row. Returns
    the post-clamp dict actually written so the UI can echo it back."""
    import options_scanner
    if request.method == "GET":
        return jsonify({
            "settings": options_scanner.load_settings(),
            "defaults": dict(options_scanner.DEFAULT_SETTINGS),
        })
    body = request.get_json(silent=True) or {}
    return jsonify({"settings": options_scanner.save_settings(body)})


@app.route("/api/momentum/alerts/hide", methods=["POST"])
def api_momentum_alerts_hide():
    """Soft-delete momentum alerts from the panel. Body:
        {date?: 'YYYY-MM-DD', tickers?: ['BTU', ...]}
    Missing date → most recent date with visible rows.
    Missing/empty tickers → clear ALL visible rows for the date."""
    payload = request.get_json(silent=True) or {}
    date = (payload.get("date") or "").strip() or None
    raw_tickers = payload.get("tickers")
    if raw_tickers is not None and not isinstance(raw_tickers, list):
        return jsonify({"error": "tickers must be a list"}), 400
    n = scanner_momentum.hide_alerts(date, raw_tickers)
    return jsonify({"hidden": n})


@app.route("/api/momentum/diagnose", methods=["GET"])
def api_momentum_diagnose():
    """Dry-run the scanner against one ticker — returns each filter's
    measured value vs its threshold so the user can see why a name
    they expected didn't fire. Optional `date=YYYY-MM-DD` flips into
    historical mode (sources the "today" bar from the snapshot's
    recent_bars instead of Alpaca, so you can re-check the last few
    trading days). Without `date`, hits Alpaca for the live bar."""
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "ticker query param required"}), 400
    as_of = (request.args.get("date") or "").strip() or None
    return jsonify(scanner_momentum.diagnose(ticker, as_of=as_of))


@app.route("/api/momentum/enabled", methods=["POST"])
def api_momentum_toggle():
    """UI kill-switch for the momentum-scanner workflow. When OFF, the
    GitHub Actions cron still fires every 5 min but scanner_momentum.run
    exits immediately — no Alpaca calls, no DB writes, no Telegram."""
    payload = request.get_json(silent=True) or {}
    if "enabled" not in payload:
        return jsonify({"error": "missing 'enabled' boolean"}), 400
    enabled = bool(payload["enabled"])
    if not scanner_momentum.set_enabled(enabled):
        return jsonify({"error": "could not persist toggle"}), 500
    return jsonify({"enabled": scanner_momentum.get_config()["enabled"]})


# --- Strategy report (outcomes) -------------------------------------------

def _outcomes_args():
    """Parse ?days=N&horizon=N from the request with sane defaults."""
    try:
        days = int(request.args.get("days") or 90)
    except (TypeError, ValueError):
        days = 90
    try:
        horizon = int(request.args.get("horizon") or 5)
    except (TypeError, ValueError):
        horizon = 5
    days = max(1, min(days, 365))
    return days, horizon


@app.route("/api/outcomes/stock/report", methods=["GET"])
def api_outcomes_stock_report():
    import outcomes
    days, horizon = _outcomes_args()
    return jsonify(outcomes.stock_report(days=days, horizon=horizon))


@app.route("/api/outcomes/options/report", methods=["GET"])
def api_outcomes_option_report():
    import outcomes
    days, horizon = _outcomes_args()
    return jsonify(outcomes.option_report(days=days, horizon=horizon))


@app.route("/api/outcomes/thumbs-up", methods=["POST"])
def api_outcomes_thumbs_up():
    """Manual entry-tracking from the stock screener results table.

    Accepts either a single entry or a batch:
      {ticker: 'AAPL', entry_date: 'YYYY-MM-DD', entry_close: 1.23}
      {rows: [{ticker, entry_date, entry_close}, ...]}

    Source kind: 'manual_screener' when the call originates from the
    screener's selection toolbar, 'manual' otherwise. Body may carry
    an explicit `source_label` to override the default label.
    """
    import outcomes
    payload = request.get_json(silent=True) or {}
    label = (payload.get("source_label") or "Screener selection").strip()
    kind  = (payload.get("source_kind")  or "manual_screener").strip()

    def _record(row: dict) -> bool:
        t = (row.get("ticker") or "").strip().upper()
        d = (row.get("entry_date") or "").strip()
        if not t or not d:
            return False
        try:
            ec = float(row["entry_close"]) if row.get("entry_close") is not None else None
        except (TypeError, ValueError):
            ec = None
        return outcomes.record_stock_outcome(
            t, d, ec, {"kind": kind, "id": None, "label": label},
        )

    rows = payload.get("rows")
    if isinstance(rows, list):
        recorded = sum(1 for r in rows if isinstance(r, dict) and _record(r))
        return jsonify({"recorded": recorded, "total": len(rows)})
    if not payload.get("ticker") or not payload.get("entry_date"):
        return jsonify({"error": "ticker+entry_date or rows[] required"}), 400
    ok = _record(payload)
    return jsonify({"recorded": bool(ok)})


def _outcomes_delete_payload():
    payload = request.get_json(silent=True) or {}
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        return None, (jsonify({"error": "entries (non-empty list) required"}), 400)
    return entries, None


@app.route("/api/outcomes/stock/delete", methods=["POST"])
def api_outcomes_stock_delete():
    """Delete rows from stock_outcomes by (ticker, entry_date). Powers
    the Stock Strategy Report's "Remove selected" button. Body:
        {entries: [{ticker, entry_date}, ...]}"""
    import outcomes
    entries, err = _outcomes_delete_payload()
    if err: return err
    return jsonify({"deleted": outcomes.delete_stock_outcomes(entries)})


@app.route("/api/outcomes/options/delete", methods=["POST"])
def api_outcomes_option_delete():
    """Same as stock/delete but for option_outcomes."""
    import outcomes
    entries, err = _outcomes_delete_payload()
    if err: return err
    return jsonify({"deleted": outcomes.delete_option_outcomes(entries)})


# Provision the Postgres snapshot + alert tables (no-ops when DATABASE_URL
# is unset), then kick off the daily auto-warm scheduler. The auto-warm
# thread will write a snapshot row per ticker when each warm completes.
snapshots.init()
alerts.init_tables()
picker.init_tables()
import paper_portfolio  # noqa: E402
paper_portfolio.init_tables()
filter_presets.init_tables()
ui_prefs.init_tables()
scanner_momentum.init_tables()
import options  # imported here so init_tables runs after snapshots.init
options.init_tables()
import outcomes
outcomes.init_tables()
screener.start_auto_warm()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
