"""
Flask web app exposing:
  GET  /                  -> single page UI
  GET  /api/screen        -> run screener (cached for the trading session)
  GET  /api/lists         -> available list keys / labels
  GET  /api/dates         -> last N trading-day dates for the date picker
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import screener
from tickers import LIST_LABELS

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
    "high_lookback": 30,
    "rsi_min": 45.0,
    "rsi_max": 50.0,
    "rsi_dev_min_pct": -5.0,
    "rsi_dev_max_pct": 5.0,
    "rvol_lookback": 10,
    "rvol_min": 0.5,
    "price_min": 1.0,
    "price_max": 1000.0,
    "price_dev_min_pct": -5.0,
    "price_dev_max_pct": 5.0,
    "apply_high": True,
    "apply_rsi": True,
    "apply_rsi_dev": True,
    "apply_rvol": True,
    "apply_price": True,
    "apply_price_dev": True,
    "as_of_offset": 0,
    "lists": tuple(sorted(_VALID_LISTS)),
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
    lists = tuple(sorted(params["lists"]))
    as_of = int(params["as_of_offset"])
    return ("v5", as_of, price, price_dev, high, rsi, rsi_dev, rvol, lists)


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
    as_of_offset = int(request.args.get("as_of_offset", 0))
    if as_of_offset < 0:
        as_of_offset = 0
    if as_of_offset > screener.MAX_AS_OF_OFFSET:
        as_of_offset = screener.MAX_AS_OF_OFFSET
    return {
        "high_lookback": int(request.args.get("high_lookback", 30)),
        "rsi_min": float(request.args.get("rsi_min", 45)),
        "rsi_max": float(request.args.get("rsi_max", 50)),
        "rsi_dev_min_pct": float(request.args.get("rsi_dev_min_pct", -5)),
        "rsi_dev_max_pct": float(request.args.get("rsi_dev_max_pct", 5)),
        "rvol_lookback": int(request.args.get("rvol_lookback", 10)),
        "rvol_min": float(request.args.get("rvol_min", 0.5)),
        "price_min": float(request.args.get("price_min", 1)),
        "price_max": float(request.args.get("price_max", 1000)),
        "price_dev_min_pct": float(request.args.get("price_dev_min_pct", -5)),
        "price_dev_max_pct": float(request.args.get("price_dev_max_pct", 5)),
        "apply_high": _parse_bool("apply_high", True),
        "apply_rsi": _parse_bool("apply_rsi", True),
        "apply_rsi_dev": _parse_bool("apply_rsi_dev", True),
        "apply_rvol": _parse_bool("apply_rvol", True),
        "apply_price": _parse_bool("apply_price", True),
        "apply_price_dev": _parse_bool("apply_price_dev", True),
        "as_of_offset": as_of_offset,
        "lists": tuple(wanted),
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
        apply_high=params["apply_high"],
        apply_rsi=params["apply_rsi"],
        apply_rsi_dev=params["apply_rsi_dev"],
        apply_rvol=params["apply_rvol"],
        apply_price=params["apply_price"],
        apply_price_dev=params["apply_price_dev"],
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
