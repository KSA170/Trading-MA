"""
Flask web app exposing:
  GET   /                    -> single page UI
  GET   /api/screen          -> run screener (cached for the trading session)
  GET   /api/chart/<tkr>     -> daily OHLCV + EMA21/50 + RSI(14)/9d-SMA
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
import pattern_scan
import picker
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
    "macd_hist_min": 0.0,
    "macd_require_rising": True,
    "turnover_min_pct": 0.5,
    "turnover_max_pct": 100.0,
    "apply_high": True,
    "apply_rsi": True,
    "apply_rsi_dev": True,
    "apply_rvol": True,
    "apply_avg_volume": True,
    "apply_price": True,
    "apply_price_dev": True,
    "apply_ema_dev": True,
    "apply_macd": True,
    "apply_turnover": False,
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
    macd = (round(float(params["macd_hist_min"]), 4), bool(params["macd_require_rising"])) if params["apply_macd"] else ("off",)
    turnover = (round(float(params["turnover_min_pct"]), 4), round(float(params["turnover_max_pct"]), 4)) if params["apply_turnover"] else ("off",)
    lists = tuple(sorted(params["lists"]))
    as_of = int(params["as_of_offset"])
    return ("v11", as_of, price, price_dev, ema_dev, macd, turnover, high, rsi, rsi_dev, rvol, avg_vol, lists)


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
    as_of_offset = _int("as_of_offset", 0)
    if as_of_offset < 0:
        as_of_offset = 0
    if as_of_offset > screener.MAX_AS_OF_OFFSET:
        as_of_offset = screener.MAX_AS_OF_OFFSET
    return {
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
        "macd_hist_min": _flt("macd_hist_min", 0),
        "macd_require_rising": _parse_bool("macd_require_rising", True),
        "turnover_min_pct": _flt("turnover_min_pct", 0.5),
        "turnover_max_pct": _flt("turnover_max_pct", 100.0),
        "apply_high": _parse_bool("apply_high", True),
        "apply_rsi": _parse_bool("apply_rsi", True),
        "apply_rsi_dev": _parse_bool("apply_rsi_dev", True),
        "apply_rvol": _parse_bool("apply_rvol", True),
        "apply_avg_volume": _parse_bool("apply_avg_volume", True),
        "apply_price": _parse_bool("apply_price", True),
        "apply_price_dev": _parse_bool("apply_price_dev", True),
        "apply_ema_dev": _parse_bool("apply_ema_dev", True),
        "apply_macd": _parse_bool("apply_macd", True),
        "apply_turnover": _parse_bool("apply_turnover", False),
        "as_of_offset": as_of_offset,
        "lists": tuple(wanted),
    }


# --- routes ----------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


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
        macd_hist_min=params["macd_hist_min"],
        macd_require_rising=params["macd_require_rising"],
        turnover_min_pct=params["turnover_min_pct"],
        turnover_max_pct=params["turnover_max_pct"],
        apply_high=params["apply_high"],
        apply_rsi=params["apply_rsi"],
        apply_rsi_dev=params["apply_rsi_dev"],
        apply_rvol=params["apply_rvol"],
        apply_avg_volume=params["apply_avg_volume"],
        apply_price=params["apply_price"],
        apply_price_dev=params["apply_price_dev"],
        apply_ema_dev=params["apply_ema_dev"],
        apply_macd=params["apply_macd"],
        apply_turnover=params["apply_turnover"],
        as_of_offset=params["as_of_offset"],
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
    started = time.time()
    results = pattern_scan.scan_setups(
        as_of, min_score=min_score, limit=limit,
        min_price=min_price, max_price=max_price,
        min_dollar_vol=min_dollar_vol,
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
        macd_hist_min=params["macd_hist_min"],
        macd_require_rising=params["macd_require_rising"],
        turnover_min_pct=params["turnover_min_pct"],
        turnover_max_pct=params["turnover_max_pct"],
        apply_high=params["apply_high"],
        apply_rsi=params["apply_rsi"],
        apply_rsi_dev=params["apply_rsi_dev"],
        apply_rvol=params["apply_rvol"],
        apply_avg_volume=params["apply_avg_volume"],
        apply_price=params["apply_price"],
        apply_price_dev=params["apply_price_dev"],
        apply_ema_dev=params["apply_ema_dev"],
        apply_macd=params["apply_macd"],
        apply_turnover=params["apply_turnover"],
        as_of_offset=params["as_of_offset"],
    )
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
      - rule_type='setup': criteria from `setup_params` in the JSON body
        — {score_min, min_price, max_price, min_dollar_vol}.
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
    if rule_type == "setup":
        sp = payload.get("setup_params") or {}
        params = {
            k: sp[k] for k in ("score_min", "min_price", "max_price", "min_dollar_vol")
            if k in sp
        }
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
    if sp:
        params = {
            k: sp[k] for k in ("score_min", "min_price", "max_price", "min_dollar_vol")
            if k in sp
        }
    else:
        params = _parse_params()
        params.pop("lists", None)
    ok = alerts.set_rule_params(rule_id, params)
    return jsonify({"updated": ok, "rules": alerts.list_rules()})


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
    on universe size. Body: {weights?, price_min?, price_max?, save?}.
    `save=true` (default) overwrites the latest persisted picks and
    saves the config so the next nightly cron uses these settings."""
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
    save = bool(payload.get("save", True))

    picks, as_of = picker.rank_universe(
        weights=weights, price_min=price_min, price_max=price_max,
        limit=picker.DEFAULT_LIMIT,
    )
    if save:
        picker.save_config(weights, price_min, price_max)
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


@app.route("/api/picks/config", methods=["POST"])
def api_picks_config():
    """Save picker config without recomputing."""
    payload = request.get_json(silent=True) or {}
    cfg = picker.get_config()
    weights = payload.get("weights") if isinstance(payload.get("weights"), dict) else cfg["weights"]
    try:
        price_min = float(payload.get("price_min", cfg["price_min"]))
        price_max = float(payload.get("price_max", cfg["price_max"]))
    except (TypeError, ValueError):
        return jsonify({"error": "price_min / price_max must be numeric"}), 400
    ok = picker.save_config(weights, price_min, price_max)
    return jsonify({"saved": ok, "config": picker.get_config()})


# Provision the Postgres snapshot + alert tables (no-ops when DATABASE_URL
# is unset), then kick off the daily auto-warm scheduler. The auto-warm
# thread will write a snapshot row per ticker when each warm completes.
snapshots.init()
alerts.init_tables()
picker.init_tables()
screener.start_auto_warm()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
