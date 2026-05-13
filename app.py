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
from tickers import LIST_LABELS, refresh_universe

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
    "rsi_min": 45.0,
    "rsi_max": 65.0,
    "rsi_dev_min_pct": 0.0,
    "rsi_dev_max_pct": 10.0,
    "rvol_lookback": 10,
    "rvol_min": 1.2,
    "price_min": 1.0,
    "price_max": 1000.0,
    "price_dev_min_pct": -1.0,
    "price_dev_max_pct": 4.0,
    "ema_dev_min_pct": -3.0,
    "ema_dev_max_pct": 3.0,
    "macd_hist_min": 0.0,
    "macd_require_rising": True,
    "apply_high": True,
    "apply_rsi": True,
    "apply_rsi_dev": True,
    "apply_rvol": True,
    "apply_price": True,
    "apply_price_dev": True,
    "apply_ema_dev": True,
    "apply_macd": True,
    "as_of_offset": 0,
    "lists": tuple(sorted(_VALID_LISTS)),
    "extras": (),
}


def _cache_key(params: dict) -> tuple:
    # When a filter is disabled, its threshold values don't matter — collapse
    # them to a sentinel so the cache hits regardless of slider position.
    high = (int(params["high_lookback"]),) if params["apply_high"] else ("off",)
    rsi = (round(float(params["rsi_min"]), 3), round(float(params["rsi_max"]), 3)) if params["apply_rsi"] else ("off",)
    rsi_dev = (round(float(params["rsi_dev_min_pct"]), 3), round(float(params["rsi_dev_max_pct"]), 3)) if params["apply_rsi_dev"] else ("off",)
    rvol = (int(params["rvol_lookback"]), round(float(params["rvol_min"]), 3)) if params["apply_rvol"] else ("off",)
    price = (round(float(params["price_min"]), 4), round(float(params["price_max"]), 4)) if params["apply_price"] else ("off",)
    price_dev = (round(float(params["price_dev_min_pct"]), 3), round(float(params["price_dev_max_pct"]), 3)) if params["apply_price_dev"] else ("off",)
    ema_dev = (round(float(params["ema_dev_min_pct"]), 3), round(float(params["ema_dev_max_pct"]), 3)) if params["apply_ema_dev"] else ("off",)
    macd = (round(float(params["macd_hist_min"]), 4), bool(params["macd_require_rising"])) if params["apply_macd"] else ("off",)
    lists = tuple(sorted(params["lists"]))
    extras = tuple(sorted(params.get("extras") or ()))
    as_of = int(params["as_of_offset"])
    return ("v8", as_of, price, price_dev, ema_dev, macd, high, rsi, rsi_dev, rvol, lists, extras)


def _parse_bool(name: str, default: bool) -> bool:
    raw = request.args.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _parse_params() -> dict:
    raw_lists = request.args.get("lists", "")
    if raw_lists.strip():
        wanted = [s.strip() for s in raw_lists.split(",") if s.strip()]
        wanted = [s for s in wanted if s in _VALID_LISTS]
    else:
        wanted = sorted(_VALID_LISTS)
    if not wanted:
        wanted = sorted(_VALID_LISTS)
    raw_extras = request.args.get("extras", "")
    extras: list[str] = []
    if raw_extras.strip():
        seen: set[str] = set()
        for s in raw_extras.split(","):
            t = s.strip().upper()
            if t and t not in seen:
                seen.add(t)
                extras.append(t)
    as_of_offset = int(request.args.get("as_of_offset", 0))
    if as_of_offset < 0:
        as_of_offset = 0
    if as_of_offset > screener.MAX_AS_OF_OFFSET:
        as_of_offset = screener.MAX_AS_OF_OFFSET
    return {
        "high_lookback": int(request.args.get("high_lookback", 2)),
        "rsi_min": float(request.args.get("rsi_min", 45)),
        "rsi_max": float(request.args.get("rsi_max", 65)),
        "rsi_dev_min_pct": float(request.args.get("rsi_dev_min_pct", 0)),
        "rsi_dev_max_pct": float(request.args.get("rsi_dev_max_pct", 10)),
        "rvol_lookback": int(request.args.get("rvol_lookback", 10)),
        "rvol_min": float(request.args.get("rvol_min", 1.2)),
        "price_min": float(request.args.get("price_min", 1)),
        "price_max": float(request.args.get("price_max", 1000)),
        "price_dev_min_pct": float(request.args.get("price_dev_min_pct", -1)),
        "price_dev_max_pct": float(request.args.get("price_dev_max_pct", 4)),
        "ema_dev_min_pct": float(request.args.get("ema_dev_min_pct", -3)),
        "ema_dev_max_pct": float(request.args.get("ema_dev_max_pct", 3)),
        "macd_hist_min": float(request.args.get("macd_hist_min", 0)),
        "macd_require_rising": _parse_bool("macd_require_rising", True),
        "apply_high": _parse_bool("apply_high", True),
        "apply_rsi": _parse_bool("apply_rsi", True),
        "apply_rsi_dev": _parse_bool("apply_rsi_dev", True),
        "apply_rvol": _parse_bool("apply_rvol", True),
        "apply_price": _parse_bool("apply_price", True),
        "apply_price_dev": _parse_bool("apply_price_dev", True),
        "apply_ema_dev": _parse_bool("apply_ema_dev", True),
        "apply_macd": _parse_bool("apply_macd", True),
        "as_of_offset": as_of_offset,
        "lists": tuple(wanted),
        "extras": tuple(extras),
    }


# --- routes ----------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/screen")
def api_screen():
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
        rsi_min=params["rsi_min"],
        rsi_max=params["rsi_max"],
        rsi_dev_min_pct=params["rsi_dev_min_pct"],
        rsi_dev_max_pct=params["rsi_dev_max_pct"],
        rvol_lookback=params["rvol_lookback"],
        rvol_min=params["rvol_min"],
        price_min=params["price_min"],
        price_max=params["price_max"],
        price_dev_min_pct=params["price_dev_min_pct"],
        price_dev_max_pct=params["price_dev_max_pct"],
        ema_dev_min_pct=params["ema_dev_min_pct"],
        ema_dev_max_pct=params["ema_dev_max_pct"],
        macd_hist_min=params["macd_hist_min"],
        macd_require_rising=params["macd_require_rising"],
        apply_high=params["apply_high"],
        apply_rsi=params["apply_rsi"],
        apply_rsi_dev=params["apply_rsi_dev"],
        apply_rvol=params["apply_rvol"],
        apply_price=params["apply_price"],
        apply_price_dev=params["apply_price_dev"],
        apply_ema_dev=params["apply_ema_dev"],
        apply_macd=params["apply_macd"],
        as_of_offset=params["as_of_offset"],
        lists=list(params["lists"]),
        extras=list(params["extras"]),
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
    """Last N US trading-day dates (anchored on SPY) for the date picker."""
    n = int(request.args.get("n", screener.MAX_AS_OF_OFFSET + 1))
    n = max(1, min(n, screener.MAX_AS_OF_OFFSET + 1))
    return jsonify({"dates": screener.reference_dates(n=n)})


@app.route("/api/admin/refresh-universe", methods=["POST"])
def api_refresh_universe():
    """Drop the disk + in-memory caches of the US symbol directory and
    rebuild from a fresh fetch. Returns the new per-exchange counts."""
    try:
        # Also bust the in-memory screen cache since the universe just changed.
        with _screen_lock:
            _screen_cache.clear()
        sizes = refresh_universe()
        return jsonify({"ok": True, "sizes": sizes})
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
        rsi_min=params["rsi_min"],
        rsi_max=params["rsi_max"],
        rsi_dev_min_pct=params["rsi_dev_min_pct"],
        rsi_dev_max_pct=params["rsi_dev_max_pct"],
        rvol_lookback=params["rvol_lookback"],
        rvol_min=params["rvol_min"],
        price_min=params["price_min"],
        price_max=params["price_max"],
        price_dev_min_pct=params["price_dev_min_pct"],
        price_dev_max_pct=params["price_dev_max_pct"],
        ema_dev_min_pct=params["ema_dev_min_pct"],
        ema_dev_max_pct=params["ema_dev_max_pct"],
        macd_hist_min=params["macd_hist_min"],
        macd_require_rising=params["macd_require_rising"],
        apply_high=params["apply_high"],
        apply_rsi=params["apply_rsi"],
        apply_rsi_dev=params["apply_rsi_dev"],
        apply_rvol=params["apply_rvol"],
        apply_price=params["apply_price"],
        apply_price_dev=params["apply_price_dev"],
        apply_ema_dev=params["apply_ema_dev"],
        apply_macd=params["apply_macd"],
        as_of_offset=params["as_of_offset"],
    )
    return jsonify(result)


# Column order + display labels for the Excel export. Keys must match the
# fields produced by ScreenHit.to_dict().
_EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("ticker", "Ticker"),
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
