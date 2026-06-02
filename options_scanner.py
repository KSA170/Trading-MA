"""
Options universe scanner.

Independent of the stock screener / picker. Picks its own short list of
candidates each run by:

  1. Liquidity gate — price >= $20, 20-day avg volume >= 500k. Strikes
     are too coarse + options too illiquid below these floors.

  2. Cheap pre-score (no per-ticker network I/O) — runs the Price
     Trajectory and Sector layers on cached snapshot data only.
     Sector ETF / SPY 5-day moves are fetched ONCE at the start of the
     scan, not per-ticker. Resulting "pre-composite" is a quick proxy
     for directional bias.

  3. Rank by |pre_composite - 50| descending; keep top N (default 50).
     N is small enough to make the expensive full pipeline tractable.

  4. Full composite scoring (5 layers, ~10-15 yfinance + Finnhub
     calls per ticker) on the top N. Persists every result to
     options_recommendations (BUY / WATCH / PASS alike).

  5. Digest filter — BUY at any composite, or high-conviction WATCH
     (composite >= 70 for calls, <= 30 for puts). These go to the
     Telegram digest; everything else is still in the DB for the UI.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date
from typing import Any

log = logging.getLogger("options_scanner")


# Universe liquidity gates — independent of the screener.
SCANNER_PRICE_FLOOR     = 20.0
SCANNER_VOLUME_FLOOR    = 500_000

# Default scan sizes
DEFAULT_NIGHTLY_TOP_N   = 50
DEFAULT_MANUAL_TOP_N    = 8

# Cheap pre-filter — only consider candidates whose 2-cheap-layer
# pre-composite is at least this far from neutral (50). Filters out
# the dead-center majority before we incur the expensive layers.
PRE_SCORE_MIN_DISTANCE  = 8

# Digest inclusion thresholds (matches the user's "BUY + high-conv WATCH").
DIGEST_WATCH_CALL_MIN   = 70
DIGEST_WATCH_PUT_MAX    = 30


def _build_sector_5d_cache() -> dict[str, float]:
    """Fetch sector ETF + SPY 5-day moves once per scan. Returns
    {etf_symbol: pct, "SPY": pct, sector_name: pct} so lookups by
    either sector name or ETF symbol work."""
    import options as opt
    out: dict[str, float] = {}
    spy = opt._fetch_etf_5d_move("SPY")
    if spy is not None:
        out["SPY"] = spy
    for sector_name, etf in opt._SECTOR_ETFS.items():
        v = opt._fetch_etf_5d_move(etf)
        if v is not None:
            out[etf] = v
            out[sector_name] = v
    return out


def _pre_compose(price_layer_score: float, sector_layer_score: float) -> float:
    """Re-normalize the Price (30%) + Sector (10%) layer weights to
    sum to 1.0 since we're computing a 2-layer pre-composite."""
    total_w = 0.30 + 0.10   # 0.40
    return (0.30 * price_layer_score + 0.10 * sector_layer_score) / total_w


def pre_score_universe(snap_date: str | None = None,
                       price_floor: float = SCANNER_PRICE_FLOOR,
                       vol_floor: float = SCANNER_VOLUME_FLOOR,
                       ) -> list[dict]:
    """Returns a list of {ticker, pre_composite, snap_row,
    distance_from_neutral} for every liquid snapshot ticker.

    No per-ticker network I/O. Sector ETF moves are fetched once and
    cached. Suitable for ranking 2k+ tickers in a few seconds."""
    import snapshots, options as opt, scanner_momentum

    if not snapshots.enabled():
        log.warning("snapshots disabled (no DATABASE_URL) — pre_score returns []")
        return []
    if snap_date is None:
        dates = snapshots.available_dates(1)
        if not dates:
            log.warning("no snapshot dates available")
            return []
        snap_date = dates[0]
    log.info("pre-scoring universe for %s", snap_date)

    sector_cache = _build_sector_5d_cache()
    spy_5d = sector_cache.get("SPY")

    pre_scored: list[dict] = []
    scanned = liquid = 0
    for ticker, snap_row in snapshots.iter_for_date(snap_date):
        scanned += 1
        try:
            close = float(snap_row.get("close") or 0)
        except (TypeError, ValueError):
            continue
        if close < price_floor:
            continue
        # Average volume from the trailing bars (same helper the main
        # engine uses, so behavior is consistent).
        avg_vol = opt._avg_volume_20(snap_row) or 0
        if avg_vol < vol_floor:
            continue
        liquid += 1
        # Cheap layers only — no I/O.
        price_layer = opt._score_price_trajectory(snap_row, avg_vol)
        sector_name = snap_row.get("sector")
        sector_5d = sector_cache.get(sector_name) if sector_name else None
        sector_layer = opt._score_sector(sector_name, sector_5d, spy_5d)
        pre = _pre_compose(price_layer["score"], sector_layer["score"])
        dist = abs(pre - 50)
        if dist < PRE_SCORE_MIN_DISTANCE:
            continue
        pre_scored.append({
            "ticker": ticker,
            "pre_composite": round(pre, 1),
            "distance": round(dist, 1),
            "direction_bias": "call" if pre >= 50 else "put",
            "snap_row": snap_row,
        })
    log.info("pre_score: %d scanned, %d liquid, %d above pre-filter",
             scanned, liquid, len(pre_scored))
    pre_scored.sort(key=lambda r: -r["distance"])
    return pre_scored


def digest_filter(rec: dict) -> bool:
    """True if a recommendation should appear in the Telegram digest:
    BUY at any composite, or high-conviction WATCH (composite >= 70 /
    <= 30 by direction)."""
    verdict = rec.get("verdict")
    score = rec.get("composite_score")
    if score is None:
        return False
    if verdict == "BUY":
        return True
    if verdict == "WATCH":
        direction = rec.get("direction")
        if direction == "call" and score >= DIGEST_WATCH_CALL_MIN:
            return True
        if direction == "put" and score <= DIGEST_WATCH_PUT_MAX:
            return True
    return False


def scan_universe(top_n: int = DEFAULT_NIGHTLY_TOP_N,
                  dte_min: int = 15,
                  dte_max: int = 60,
                  persist: bool = True,
                  progress_cb: Any = None,
                  should_cancel: Any = None) -> dict:
    """Run the full pipeline on the top N pre-scored candidates.

    Returns:
      {
        'as_of': iso-date string,
        'scanned': int,           # total tickers passed to full pipeline
        'recommendations': list,  # all rec dicts, sorted by |composite - 50|
        'digest': list,           # filtered for Telegram (BUY + high-WATCH)
      }

    `progress_cb(i, total, ticker)` is called before each ticker if
    provided — useful for the UI manual-trigger progress indicator.
    `should_cancel()` is polled before each ticker; if it returns
    truthy, the loop exits early and partial results are returned."""
    import options as opt

    pre_scored = pre_score_universe()
    pool = pre_scored[: max(1, int(top_n))]
    log.info("scan_universe: top %d of %d pre-scored candidates",
             len(pool), len(pre_scored))

    out_recs: list[dict] = []
    for i, cand in enumerate(pool, start=1):
        if should_cancel:
            try:
                if should_cancel():
                    log.info("scan_universe: cancelled at %d/%d", i - 1, len(pool))
                    break
            except Exception:
                pass
        ticker = cand["ticker"]
        if progress_cb:
            try:
                progress_cb(i, len(pool), ticker)
            except Exception:
                pass
        try:
            rec = opt.recommend_for_ticker(ticker, dte_min=dte_min, dte_max=dte_max)
        except Exception as exc:
            log.warning("recommend_for_ticker(%s) failed: %s", ticker, exc)
            continue
        if rec.get("composite_score") is None:
            # Hit an early gate (no chain, below floor, etc.) — skip.
            continue
        # Tag with the pre-score for transparency in the digest.
        rec["pre_composite"] = cand["pre_composite"]
        rec["pre_direction_bias"] = cand["direction_bias"]
        out_recs.append(rec)
        if persist:
            try:
                opt.save_recommendation(rec)
            except Exception as exc:
                log.warning("save_recommendation(%s) failed: %s", ticker, exc)

    # Sort by |composite - 50| descending so the digest leads with the
    # strongest directional setups first.
    out_recs.sort(key=lambda r: -abs((r.get("composite_score") or 50) - 50))
    digest = [r for r in out_recs if digest_filter(r)]
    log.info("scan_universe: %d recs, %d in digest", len(out_recs), len(digest))

    return {
        "as_of": date.today().isoformat(),
        "scanned": len(out_recs),
        "candidates": len(pool),
        "recommendations": out_recs,
        "digest": digest,
    }


def format_digest_for_telegram(scan_result: dict) -> str:
    """Markdown body for the Telegram nightly digest. Kept under
    ~4000 chars to fit one message. Truncates the digest list with a
    "+N more" line if it overflows."""
    as_of = scan_result.get("as_of") or date.today().isoformat()
    digest = scan_result.get("digest") or []
    if not digest:
        return (
            f"📊 *Options scan — {as_of}*\n"
            f"_{scan_result.get('scanned', 0)} tickers scanned, "
            f"none cleared BUY or high-conviction WATCH._\n"
            f"Sit out today; no setups stacked enough across the 5 layers."
        )
    header = (
        f"📊 *Options scan — {as_of}*\n"
        f"_{len(digest)} setup(s) from {scan_result.get('scanned', 0)} scanned_\n"
    )

    glyph = {"BUY": "🟢", "WATCH": "🟡"}
    arrow = {"call": "📈 CALL", "put": "📉 PUT"}

    lines: list[str] = []
    used_chars = len(header)
    for r in digest:
        score = int(round(r.get("composite_score") or 0))
        verdict = r.get("verdict") or "?"
        direction = r.get("direction") or ""
        ticker = r.get("ticker") or ""
        conv = r.get("conviction") or ""
        contract = r.get("contract") or {}
        post_e = r.get("post_earnings_override")
        head = (
            f"{glyph.get(verdict, '⚪')} *{ticker}*  "
            f"{arrow.get(direction, '·')} · "
            f"composite *{score}/100*"
            f"{' · ' + conv + ' conv' if conv and conv != 'none' else ''}"
        )
        if contract:
            strike = contract.get("strike")
            exp = contract.get("expiration")
            mid = contract.get("mid")
            delta = contract.get("delta")
            sub = (
                f"   {exp} ${strike:.2f} · "
                f"Δ {(delta or 0):+.2f} · mid ${(mid or 0):.2f}"
                f"{' · post-earn expiry' if post_e else ''}"
            )
        else:
            reason = (r.get("reason") or "")[:60]
            sub = f"   {reason}"
        block = head + "\n" + sub
        if used_chars + len(block) + 2 > 3900:
            remaining = len(digest) - len(lines)
            lines.append(f"_…+{remaining} more (see UI)_")
            break
        lines.append(block)
        used_chars += len(block) + 2

    return header + "\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Background-job wrappers — mirrors the screener's snapshot/warm pattern.
# Lets the UI kick off a scan that may run for tens of minutes (Top 100,
# 200), then poll for progress and a final result without holding an HTTP
# request open. Cron path (options_cron.py) still calls scan_universe
# directly and doesn't use these.

_scan_state: dict = {
    "running": False,
    "done": 0,
    "total": 0,
    "errors": 0,
    "cancelled": False,
    "started_at": None,
    "finished_at": None,
    "current_ticker": None,
    "top_n": 0,
    "dte_min": 0,
    "dte_max": 0,
    "last_result": None,    # full scan_universe() return value
    "last_error": None,
}
_scan_lock = threading.Lock()
_scan_thread: "threading.Thread | None" = None


def scan_status() -> dict:
    with _scan_lock:
        return dict(_scan_state)


def cancel_scan() -> bool:
    """Ask the running scan to stop. Returns True if a run was in flight."""
    global _scan_thread
    alive = _scan_thread is not None and _scan_thread.is_alive()
    with _scan_lock:
        if not _scan_state["running"] and not alive:
            return False
        _scan_state["cancelled"] = True
        _scan_state["running"] = False
        _scan_state["finished_at"] = time.time()
        return True


def start_scan(top_n: int,
               dte_min: int = 15,
               dte_max: int = 60,
               persist: bool = True) -> dict:
    """Kick off scan_universe in a daemon thread. Returns a status snapshot
    with `started` = True if a new run kicked off, False if one was
    already in progress (in which case nothing changes — the caller can
    still poll scan_status())."""
    global _scan_thread
    if _scan_thread is not None and _scan_thread.is_alive():
        return {"started": False, **scan_status()}
    with _scan_lock:
        if _scan_state["running"]:
            return {"started": False, **scan_status()}
        _scan_state.update(
            running=True, done=0, total=int(top_n),
            errors=0, cancelled=False,
            started_at=time.time(), finished_at=None,
            current_ticker=None,
            top_n=int(top_n), dte_min=int(dte_min), dte_max=int(dte_max),
            last_result=None, last_error=None,
        )

    def _progress(i: int, total: int, ticker: str) -> None:
        with _scan_lock:
            # `done` is the count finished BEFORE this ticker; the UI
            # shows "scanning ticker (i of total)" while it works.
            _scan_state["done"] = max(0, i - 1)
            _scan_state["total"] = total
            _scan_state["current_ticker"] = ticker

    def _should_cancel() -> bool:
        with _scan_lock:
            return bool(_scan_state["cancelled"])

    def _run() -> None:
        try:
            result = scan_universe(
                top_n=top_n, dte_min=dte_min, dte_max=dte_max,
                persist=persist,
                progress_cb=_progress, should_cancel=_should_cancel,
            )
            with _scan_lock:
                _scan_state["last_result"] = result
                _scan_state["done"] = _scan_state["total"]
                _scan_state["current_ticker"] = None
        except Exception as exc:
            log.warning("options scan failed: %s", exc, exc_info=True)
            with _scan_lock:
                _scan_state["last_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            with _scan_lock:
                _scan_state["running"] = False
                _scan_state["finished_at"] = time.time()

    _scan_thread = threading.Thread(target=_run, daemon=True, name="options-scan")
    _scan_thread.start()
    return {"started": True, **scan_status()}
