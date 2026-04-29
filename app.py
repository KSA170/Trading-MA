"""
Flask web app exposing:
  GET  /                  -> single page UI
  GET  /api/screen        -> run screener (cached for the trading session)
  GET  /api/chart/<tkr>   -> daily OHLCV + RSI + 21/50 EMA for a ticker
  GET  /api/history       -> top-5 hits per past trading day
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date, datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import screener

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")

ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "history.json"

app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))


# In-memory cache so re-running with the same parameters is instant.
_screen_cache: dict[tuple, tuple[float, list]] = {}
_screen_lock = threading.Lock()
_SCREEN_TTL_SEC = 60 * 30  # 30 minutes


def _cache_key(params: dict) -> tuple:
    return (
        int(params["high_lookback"]),
        round(float(params["rsi_min"]), 3),
        round(float(params["rsi_max"]), 3),
        int(params["rvol_lookback"]),
        round(float(params["rvol_min"]), 3),
    )


def _parse_params() -> dict:
    return {
        "high_lookback": int(request.args.get("high_lookback", 30)),
        "rsi_min": float(request.args.get("rsi_min", 45)),
        "rsi_max": float(request.args.get("rsi_max", 50)),
        "rvol_lookback": int(request.args.get("rvol_lookback", 10)),
        "rvol_min": float(request.args.get("rvol_min", 0.5)),
    }


# --- history persistence ---------------------------------------------------

def _load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        return json.loads(HISTORY_PATH.read_text())
    except Exception:
        return []


def _save_history(records: list[dict]) -> None:
    HISTORY_PATH.write_text(json.dumps(records, indent=2))


def _record_history(hits: list[dict]) -> None:
    """Snapshot today's top 5 results to history.json (one record per date)."""
    today = date.today().isoformat()
    records = _load_history()
    records = [r for r in records if r.get("date") != today]
    top5 = hits[:5]
    if not top5:
        return
    records.append({
        "date": today,
        "captured_at": datetime.utcnow().isoformat() + "Z",
        "top": top5,
    })
    records.sort(key=lambda r: r.get("date", ""), reverse=True)
    records = records[:60]  # keep last ~60 trading days
    _save_history(records)


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
            return jsonify({"results": cached[1], "cached": True, "params": params})

    started = time.time()
    hits = screener.run_screen(
        high_lookback=params["high_lookback"],
        rsi_min=params["rsi_min"],
        rsi_max=params["rsi_max"],
        rvol_lookback=params["rvol_lookback"],
        rvol_min=params["rvol_min"],
    )
    payload = [h.to_dict() for h in hits]
    elapsed = time.time() - started
    log.info("screen complete: %d hits in %.1fs (params=%s)", len(payload), elapsed, params)

    with _screen_lock:
        _screen_cache[key] = (now, payload)

    # Only the default-parameter run drives the public history. That keeps
    # daily snapshots stable instead of being overwritten by ad-hoc tweaks.
    if key == _cache_key({
        "high_lookback": 30, "rsi_min": 45, "rsi_max": 50,
        "rvol_lookback": 10, "rvol_min": 0.5,
    }):
        try:
            _record_history(payload)
        except Exception as exc:
            log.warning("history record failed: %s", exc)

    return jsonify({"results": payload, "cached": False, "params": params, "elapsed_sec": round(elapsed, 1)})


@app.route("/api/chart/<path:ticker>")
def api_chart(ticker: str):
    # Frontend may pass the display symbol. The yfinance ticker already matches
    # in our universe, so use the input as-is.
    payload = screener.chart_payload(ticker)
    if payload is None:
        return jsonify({"error": f"no data for {ticker}"}), 404
    return jsonify(payload)


@app.route("/api/history")
def api_history():
    return jsonify({"records": _load_history()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
