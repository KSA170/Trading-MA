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


def _bump_rate_limit_counter_if(exc: BaseException | None, hit: bool) -> None:
    """Bump scan_state.rate_limited_count when a per-ticker failure
    looks like a Yahoo 429. The UI uses this counter to show a clear
    'Yahoo is rate-limiting' banner so the user knows the scan isn't
    silently broken. Defined at module level so scan_universe can call
    it without circular-import gymnastics."""
    if not hit:
        return
    try:
        with _scan_lock:
            _scan_state["rate_limited_count"] = (
                _scan_state.get("rate_limited_count", 0) + 1
            )
    except NameError:
        # _scan_lock isn't defined yet during import — happens only if
        # scan_universe is called before start_scan has initialised the
        # background-job state. Safe to no-op; the cron path doesn't
        # need the counter (it logs directly).
        pass


def _build_sector_5d_cache() -> dict[str, float]:
    """Fetch sector ETF + SPY 5-day moves once per scan, in parallel.
    Returns {etf_symbol: pct, "SPY": pct, sector_name: pct} so lookups
    by either sector name or ETF symbol work.

    Hard 10-second overall budget — if Yahoo is throttling and the
    fetches don't finish in time, we abandon whatever's still in
    flight and continue with an empty cache. The pre-score's sector
    layer then returns None for affected tickers and the renormalized
    composite uses Price alone. Better than blocking the entire scan
    on stuck yfinance retries.

    Previous bug: `as_completed(futures, timeout=None)` waited
    indefinitely for the next future, and a per-future
    `fut.result(timeout=15)` is a no-op since as_completed only yields
    futures that have ALREADY completed. So if every fetch was stuck
    in yfinance's internal retry loop on a 429, the whole pre-score
    hung. Replaced with `cf.wait(timeout=10)` which has true overall
    semantics."""
    import concurrent.futures as cf
    import options as opt
    t0 = time.time()
    targets: list[tuple[str | None, str]] = [(None, "SPY")]
    for sector_name, etf in opt._SECTOR_ETFS.items():
        targets.append((sector_name, etf))

    def _one(symbol: str) -> tuple[str, float | None]:
        s0 = time.time()
        try:
            v = opt._fetch_etf_5d_move(symbol)
        except Exception as exc:
            log.warning("ETF fetch %s raised: %s", symbol, exc)
            v = None
        log.debug("ETF %s fetched in %.1fs -> %s", symbol, time.time() - s0, v)
        return (symbol, v)

    OVERALL_TIMEOUT = 10.0
    out: dict[str, float] = {}
    pool = cf.ThreadPoolExecutor(max_workers=8, thread_name_prefix="etf-fetch")
    try:
        futures = {pool.submit(_one, etf): (sector_name, etf)
                   for sector_name, etf in targets}
        done, not_done = cf.wait(futures, timeout=OVERALL_TIMEOUT)
        for fut in done:
            sector_name, etf = futures[fut]
            try:
                _, v = fut.result()
            except Exception as exc:
                log.warning("ETF %s result raised: %s", etf, exc)
                v = None
            if v is None:
                continue
            if sector_name is None:   # the SPY entry
                out["SPY"] = v
            else:
                out[etf] = v
                out[sector_name] = v
        if not_done:
            abandoned = [futures[f][1] for f in not_done]
            log.warning("abandoned %d ETF fetches after %.0fs budget: %s",
                        len(not_done), OVERALL_TIMEOUT, abandoned)
    finally:
        # wait=False — orphaned daemon threads will exit when their
        # in-flight yfinance call returns. Without this, we'd block
        # on exiting the with-block until the slowest fetch finished.
        pool.shutdown(wait=False)
    log.info("sector ETF cache built in %.1fs (%d/%d resolved)",
             time.time() - t0,
             len([k for k in out if not k.startswith(" ")]),
             len(opt._SECTOR_ETFS) + 1)
    return out


def _pre_compose(price_layer_score: float | None,
                 sector_layer_score: float | None) -> float | None:
    """Re-normalize the Price (30%) + Sector (10%) layer weights to
    sum to 1.0 since we're computing a 2-layer pre-composite.

    Either input may be None when the underlying scorer had no data
    (Price almost always has snapshot data; Sector returns None for
    tickers with no mapped sector). If both are None → None (ticker
    is dropped from the pool). If one is None → renormalize over the
    other alone."""
    if price_layer_score is None and sector_layer_score is None:
        return None
    total_w = 0.0
    total = 0.0
    if price_layer_score is not None:
        total += 0.30 * float(price_layer_score); total_w += 0.30
    if sector_layer_score is not None:
        total += 0.10 * float(sector_layer_score); total_w += 0.10
    return total / total_w


def pre_score_universe(snap_date: str | None = None,
                       price_floor: float = SCANNER_PRICE_FLOOR,
                       vol_floor: float = SCANNER_VOLUME_FLOOR,
                       min_distance: float = PRE_SCORE_MIN_DISTANCE,
                       ) -> list[dict]:
    """Returns a list of {ticker, pre_composite, snap_row,
    distance_from_neutral} for every liquid snapshot ticker.

    No per-ticker network I/O. Sector ETF moves are fetched once and
    cached. Suitable for ranking 2k+ tickers in a few seconds. Counts
    + the same result are also returned by `preview_universe()` —
    that wrapper is what the UI / preview endpoint calls."""
    result = _pre_score_with_counts(
        snap_date=snap_date, price_floor=price_floor,
        vol_floor=vol_floor, min_distance=min_distance,
    )
    return result["pre_scored"]


def _pre_score_with_counts(snap_date: str | None = None,
                           price_floor: float = SCANNER_PRICE_FLOOR,
                           vol_floor: float = SCANNER_VOLUME_FLOOR,
                           min_distance: float = PRE_SCORE_MIN_DISTANCE,
                           ) -> dict:
    """Internal worker. Returns
        {snap_date, scanned, liquid, qualifying,
         call_bias, put_bias, pre_scored: [...]}
    so callers can either consume the full list (scan_universe) or
    just the counts (preview endpoint)."""
    import snapshots, options as opt, scanner_momentum

    out_empty = {"snap_date": None, "scanned": 0, "liquid": 0,
                 "qualifying": 0, "call_bias": 0, "put_bias": 0,
                 "pre_scored": []}
    if not snapshots.enabled():
        log.warning("snapshots disabled (no DATABASE_URL) — pre_score returns []")
        return out_empty
    if snap_date is None:
        dates = snapshots.available_dates(1)
        if not dates:
            log.warning("no snapshot dates available")
            return out_empty
        snap_date = dates[0]
    log.info("pre-scoring universe for %s (price>=%.2f vol>=%d dist>=%.1f)",
             snap_date, price_floor, vol_floor, min_distance)

    sector_cache = _build_sector_5d_cache()
    spy_5d = sector_cache.get("SPY")

    pre_scored: list[dict] = []
    scanned = liquid = call_bias = put_bias = 0
    for ticker, snap_row in snapshots.iter_for_date(snap_date):
        scanned += 1
        try:
            close = float(snap_row.get("close") or 0)
        except (TypeError, ValueError):
            continue
        if close < price_floor:
            continue
        avg_vol = opt._avg_volume_20(snap_row) or 0
        if avg_vol < vol_floor:
            continue
        liquid += 1
        price_layer = opt._score_price_trajectory(snap_row, avg_vol)
        sector_name = snap_row.get("sector")
        sector_5d = sector_cache.get(sector_name) if sector_name else None
        sector_layer = opt._score_sector(sector_name, sector_5d, spy_5d)
        pre = _pre_compose(price_layer["score"], sector_layer["score"])
        if pre is None:   # both Price + Sector lacked data — skip ticker
            continue
        dist = abs(pre - 50)
        if dist < min_distance:
            continue
        direction = "call" if pre >= 50 else "put"
        if direction == "call":
            call_bias += 1
        else:
            put_bias += 1
        pre_scored.append({
            "ticker": ticker,
            "pre_composite": round(pre, 1),
            "distance": round(dist, 1),
            "direction_bias": direction,
            "snap_row": snap_row,
        })
    log.info("pre_score: %d scanned, %d liquid, %d qualifying (%d call / %d put)",
             scanned, liquid, len(pre_scored), call_bias, put_bias)
    pre_scored.sort(key=lambda r: -r["distance"])
    return {
        "snap_date": snap_date, "scanned": scanned, "liquid": liquid,
        "qualifying": len(pre_scored),
        "call_bias": call_bias, "put_bias": put_bias,
        "pre_scored": pre_scored,
    }


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
                  should_cancel: Any = None,
                  price_floor: float = SCANNER_PRICE_FLOOR,
                  volume_floor: float = SCANNER_VOLUME_FLOOR,
                  min_directional_distance: float = PRE_SCORE_MIN_DISTANCE,
                  mid_min: float = 0.0,
                  mid_max: float = 1e9,
                  ) -> dict:
    """Run the full pipeline on the top N pre-scored candidates.

    Returns:
      {
        'as_of': iso-date string,
        'scanned': int,           # total tickers passed to full pipeline
        'candidates': int,        # tickers above pre-filter (== survived Gate 2)
        'qualifying': int,        # same as candidates, for UI consistency
        'recommendations': list,  # all rec dicts, sorted by |composite - 50|
        'digest': list,           # filtered for Telegram (BUY + high-WATCH)
        'gates': {price_floor, volume_floor, min_directional_distance}
      }

    The three `*_floor` / `min_directional_distance` kwargs default to
    the original hardcoded constants so the cron and existing callers
    don't need to change. The UI / API plumbs them in to relax/tighten.

    `progress_cb(i, total, ticker)` is called before each ticker if
    provided — useful for the UI manual-trigger progress indicator.
    `should_cancel()` is polled before each ticker; if it returns
    truthy, the loop exits early and partial results are returned."""
    import options as opt

    pre_result, was_cached = _pre_score_cached(
        price_floor=price_floor, vol_floor=volume_floor,
        min_distance=min_directional_distance,
    )
    pre_scored = pre_result["pre_scored"]
    pool = pre_scored[: max(1, int(top_n))]
    log.info("scan_universe: top %d of %d pre-scored candidates (cache %s)",
             len(pool), len(pre_scored), "HIT" if was_cached else "MISS")

    out_recs: list[dict] = []
    # Per-ticker hard cap (seconds). recommend_for_ticker makes ~10-15
    # yfinance + Finnhub calls per ticker with no built-in timeout — a
    # single hung call could stall the whole scan. Wrap each call in a
    # single-worker pool; if it doesn't return within the cap, log +
    # skip. Orphaned daemon thread will exit when the underlying call
    # eventually returns or the process restarts.
    import concurrent.futures as _cf
    _PER_TICKER_TIMEOUT_SEC = 60.0
    _ticker_pool = _cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="opt-rec")

    def _looks_rate_limited(exc: BaseException) -> bool:
        m = str(exc).lower()
        return ("too many" in m or "rate limit" in m or "429" in m
                or "throttl" in m)

    try:
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
            t0 = time.time()
            log.info("scan [%d/%d] %s starting", i, len(pool), ticker)
            try:
                fut = _ticker_pool.submit(
                    opt.recommend_for_ticker,
                    ticker, dte_min=dte_min, dte_max=dte_max,
                )
                rec = fut.result(timeout=_PER_TICKER_TIMEOUT_SEC)
            except _cf.TimeoutError:
                log.warning("scan [%d/%d] %s TIMED OUT after %.0fs — skipping",
                            i, len(pool), ticker, _PER_TICKER_TIMEOUT_SEC)
                _bump_rate_limit_counter_if(None, hit=False)
                continue
            except Exception as exc:
                log.warning("scan [%d/%d] %s failed: %s", i, len(pool), ticker, exc)
                if _looks_rate_limited(exc):
                    _bump_rate_limit_counter_if(exc, hit=True)
                continue
            log.info("scan [%d/%d] %s done in %.1fs (composite=%s)",
                     i, len(pool), ticker, time.time() - t0,
                     rec.get("composite_score"))
            # Chain fetch failed inside recommend_for_ticker — bump the
            # rate-limit counter so the UI banner appears, without
            # losing the partial composite result for visibility.
            if rec.get("chain_fetch_status") == "rate_limited":
                _bump_rate_limit_counter_if(None, hit=True)
            if rec.get("composite_score") is None:
                # Hit an early gate (no chain, below floor, etc.) — skip.
                continue
            # Tag with the pre-score for transparency in the digest.
            rec["pre_composite"] = cand["pre_composite"]
            rec["pre_direction_bias"] = cand["direction_bias"]
            out_recs.append(rec)
            if persist:
                try:
                    opt.save_recommendation_with_iv(rec)
                except Exception as exc:
                    log.warning("save_recommendation(%s) failed: %s", ticker, exc)
                # Note: option_outcomes is intentionally NOT written here.
                # Only user-pinned recommendations (options.pin_rec) feed
                # the Options Strategy Report — nightly scans and ad-hoc
                # lookups would drown the report in noise.
    finally:
        # wait=False so a still-hanging in-flight ticker doesn't block
        # the worker from returning. The orphaned daemon thread will
        # exit when the underlying call eventually returns.
        _ticker_pool.shutdown(wait=False)

    # Sort by |composite - 50| descending so the digest leads with the
    # strongest directional setups first.
    out_recs.sort(key=lambda r: -abs((r.get("composite_score") or 50) - 50))

    # Post-filter on the chosen contract's mid price. Only applied when
    # the user has narrowed the range from "no filter" defaults — a
    # full-width range (0, 1e9) is treated as a no-op so existing
    # callers and the nightly cron behave exactly as before.
    pre_mid_filter_count = len(out_recs)
    if mid_min > 0 or mid_max < 1e8:
        def _in_mid_range(r: dict) -> bool:
            c = r.get("contract") or {}
            mid = c.get("mid")
            try:
                m = float(mid) if mid is not None else None
            except (TypeError, ValueError):
                m = None
            if m is None:
                return False   # no contract / no mid → drop when filter active
            return mid_min <= m <= mid_max
        out_recs = [r for r in out_recs if _in_mid_range(r)]
        log.info("scan_universe: mid-price filter [%.2f, %.2f] kept %d of %d recs",
                 mid_min, mid_max, len(out_recs), pre_mid_filter_count)

    digest = [r for r in out_recs if digest_filter(r)]
    log.info("scan_universe: %d recs, %d in digest", len(out_recs), len(digest))

    return {
        "as_of": date.today().isoformat(),
        "scanned": len(out_recs),
        "candidates": len(pool),
        "qualifying": pre_result["qualifying"],
        "recommendations": out_recs,
        "digest": digest,
        "gates": {
            "price_floor": price_floor,
            "volume_floor": int(volume_floor),
            "min_directional_distance": min_directional_distance,
            "mid_min": mid_min,
            "mid_max": mid_max,
        },
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
    # "idle" | "preflight" (running pre-score) | "scanning" (per-ticker
    # full pipeline) | "done". Lets the UI label the elapsed counter
    # accurately — "Pre-scoring universe…" vs "Scanning AAPL (5/100)"
    # instead of always "Scanning 0/N" before the first ticker.
    "phase": "idle",
    # Count of per-ticker failures whose exception message looks like a
    # Yahoo Finance 429 / rate limit. The UI shows a visible banner
    # when this is > 0 so the user knows the scan is being throttled
    # rather than silently failing every ticker.
    "rate_limited_count": 0,
}
_scan_lock = threading.Lock()
_scan_thread: "threading.Thread | None" = None


def scan_status() -> dict:
    # `thread_alive` distinguishes "truly idle" from "a previous thread
    # is still draining" — e.g. yfinance can hang for a long time after
    # cancel before the worker exits. The UI uses this to show a more
    # accurate message than "server idle".
    alive = _scan_thread is not None and _scan_thread.is_alive()
    with _scan_lock:
        return {**_scan_state, "thread_alive": alive}


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
        _scan_state["phase"] = "done"
        return True


def start_scan(top_n: int,
               dte_min: int = 15,
               dte_max: int = 60,
               persist: bool = True,
               price_floor: float = SCANNER_PRICE_FLOOR,
               volume_floor: float = SCANNER_VOLUME_FLOOR,
               min_directional_distance: float = PRE_SCORE_MIN_DISTANCE,
               mid_min: float = 0.0,
               mid_max: float = 1e9,
               ) -> dict:
    """Kick off scan_universe in a daemon thread. Returns a status snapshot
    with `started` = True if a new run kicked off, False if one was
    already in progress (in which case nothing changes — the caller can
    still poll scan_status())."""
    global _scan_thread
    if _scan_thread is not None and _scan_thread.is_alive():
        # Zombie-thread recovery: if running is already False (cancel
        # was honored on the state side but the worker is still
        # draining — typically a yfinance call hanging without a
        # timeout), orphan the old thread and start fresh. The old
        # thread is daemon=True; it will exit when its current
        # network call returns and won't affect anything in the
        # meantime. Without this, the user gets stuck with "Scan did
        # not start (server idle)" until the process restarts.
        with _scan_lock:
            still_running = bool(_scan_state["running"])
        if still_running:
            return {"started": False, **scan_status()}
        log.warning("orphaning zombie scan thread (cancelled but still alive)")
        _scan_thread = None
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
            phase="preflight",
            rate_limited_count=0,
        )

    def _progress(i: int, total: int, ticker: str) -> None:
        with _scan_lock:
            # First progress callback marks the transition from preflight
            # (pre-scoring universe) to scanning (full per-ticker pipeline).
            _scan_state["phase"] = "scanning"
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
                price_floor=price_floor, volume_floor=volume_floor,
                min_directional_distance=min_directional_distance,
                mid_min=mid_min, mid_max=mid_max,
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
                _scan_state["phase"] = "done"

    _scan_thread = threading.Thread(target=_run, daemon=True, name="options-scan")
    _scan_thread.start()
    return {"started": True, **scan_status()}


# ---------------------------------------------------------------------------
# Pre-score cache — shared between the preview endpoint and scan_universe.
# The full _pre_score_with_counts() result (including the per-ticker
# pre_scored list) is cached for 5 min keyed on (snap_date, gates), so:
#   - clicking "Refresh preview" then "Scan Universe" within the same 5m
#     reuses one pre-score (skips ~13 sector-ETF yfinance calls)
#   - flipping between scan sizes (Top 25 vs Top 50) doesn't re-pre-score
#
# Was preview-only before; scan_universe re-ran _pre_score_with_counts
# from scratch even when the preview had just populated the cache.

_PRE_SCORE_TTL_SEC = 5 * 60
_pre_score_cache: dict = {"key": None, "expires": 0.0, "result": None}
_pre_score_lock = threading.Lock()


def invalidate_preview_cache() -> None:
    """Drop the cached pre-score. Called on settings change so the next
    preview / scan recomputes against the new gates."""
    with _pre_score_lock:
        _pre_score_cache["key"] = None
        _pre_score_cache["expires"] = 0.0
        _pre_score_cache["result"] = None


def _pre_score_cached(price_floor: float,
                      vol_floor: float,
                      min_distance: float,
                      force: bool = False) -> tuple[dict, bool]:
    """Return (full _pre_score_with_counts result, was_cached). Reuses the
    in-memory cache when the gates and snap_date match; bypasses on
    force=True. Cache key includes the snap_date so a new daily snapshot
    landing during the TTL doesn't serve stale counts."""
    import snapshots
    snap_date = None
    if snapshots.enabled():
        dates = snapshots.available_dates(1)
        if dates:
            snap_date = dates[0]
    key = (snap_date, round(price_floor, 3), int(vol_floor), round(min_distance, 3))

    now = time.time()
    if not force:
        with _pre_score_lock:
            if (_pre_score_cache["key"] == key
                    and _pre_score_cache["expires"] > now
                    and _pre_score_cache["result"] is not None):
                return _pre_score_cache["result"], True

    result = _pre_score_with_counts(
        snap_date=snap_date, price_floor=price_floor,
        vol_floor=vol_floor, min_distance=min_distance,
    )
    with _pre_score_lock:
        _pre_score_cache["key"] = key
        _pre_score_cache["expires"] = now + _PRE_SCORE_TTL_SEC
        _pre_score_cache["result"] = result
    return result, False


# ---------------------------------------------------------------------------
# Persisted UI settings (single-row config table) + preview-counts endpoint.
# `options_scan_config` is created by options.init_tables(); see options.py
# _SCHEMA. Stored values shadow the hardcoded constants for both the manual
# scan and the nightly cron — env vars in the cron override when set.

# Hardcoded defaults the table falls back to when missing or DB is disabled.
DEFAULT_SETTINGS: dict = {
    "price_floor": SCANNER_PRICE_FLOOR,
    "volume_floor": SCANNER_VOLUME_FLOOR,
    "min_directional_distance": PRE_SCORE_MIN_DISTANCE,
    "top_n": DEFAULT_NIGHTLY_TOP_N,
    "dte_min": 15,
    "dte_max": 60,
    # Mid-price bounds for the chosen contract. Defaults are wide
    # enough that they act as "no filter" out of the box; user
    # narrows them in the UI to e.g. ($0.50, $5) to only see
    # candidates whose recommended contract premium is in range.
    "mid_min": 0.0,
    "mid_max": 1000.0,
}

# Per-field clamps. Looser than the UI's dropdown choices on purpose —
# the API accepts anything in range, the UI just curates a few presets.
_SETTING_CLAMPS = {
    "price_floor":              (1.0,     1000.0),
    "volume_floor":             (10_000,  100_000_000),
    "min_directional_distance": (1.0,     40.0),
    "top_n":                    (1,       200),
    "dte_min":                  (1,       365),
    "dte_max":                  (2,       365),
    "mid_min":                  (0.0,     10_000.0),
    "mid_max":                  (0.05,    10_000.0),
}


def _clamp_settings(raw: dict) -> dict:
    """Coerce + clamp a settings dict to defaults+ranges. Unknown keys
    are dropped; missing keys fall back to DEFAULT_SETTINGS. dte_max is
    forced >= dte_min + 1 to keep _select_contract_by_target sane."""
    out = dict(DEFAULT_SETTINGS)
    for k, default in DEFAULT_SETTINGS.items():
        v = raw.get(k, default)
        if v is None:
            v = default
        try:
            v = float(v) if isinstance(default, float) else int(v)
        except (TypeError, ValueError):
            v = default
        lo, hi = _SETTING_CLAMPS[k]
        v = max(lo, min(hi, v))
        out[k] = v
    if out["dte_max"] <= out["dte_min"]:
        out["dte_max"] = out["dte_min"] + 1
    # mid_max must stay strictly above mid_min; bump by a penny if a
    # bad pair came in. Lets the UI submit free-form values without
    # extra validation while keeping the post-filter predicate sane.
    if out["mid_max"] <= out["mid_min"]:
        out["mid_max"] = out["mid_min"] + 0.01
    return out


def load_settings() -> dict:
    """Read the saved settings row, falling back to DEFAULT_SETTINGS for
    missing fields (or when the DB is disabled / unreachable). Always
    returns a fully-populated, clamped dict."""
    import snapshots
    if not snapshots.enabled():
        return dict(DEFAULT_SETTINGS)
    try:
        with snapshots._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT price_floor, volume_floor, min_directional_distance, "
                "       top_n, dte_min, dte_max, mid_min, mid_max "
                "FROM options_scan_config WHERE id = 1"
            )
            row = cur.fetchone()
        if not row:
            return dict(DEFAULT_SETTINGS)
        return _clamp_settings({
            "price_floor": row[0],
            "volume_floor": row[1],
            "min_directional_distance": row[2],
            "top_n": row[3],
            "dte_min": row[4],
            "dte_max": row[5],
            "mid_min": row[6],
            "mid_max": row[7],
        })
    except Exception as exc:
        log.warning("load_settings failed (using defaults): %s", exc)
        return dict(DEFAULT_SETTINGS)


def save_settings(raw: dict) -> dict:
    """Upsert the settings row. Returns the post-clamp dict actually
    written (so the UI can echo it back). Invalidates the preview
    cache since changing the gates invalidates the counts."""
    import snapshots
    settings = _clamp_settings(raw or {})
    if not snapshots.enabled():
        log.warning("save_settings: DB disabled, returning clamped values without persist")
        return settings
    try:
        with snapshots._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO options_scan_config "
                "  (id, price_floor, volume_floor, min_directional_distance, "
                "   top_n, dte_min, dte_max, mid_min, mid_max, updated_at) "
                "VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET "
                "  price_floor = EXCLUDED.price_floor, "
                "  volume_floor = EXCLUDED.volume_floor, "
                "  min_directional_distance = EXCLUDED.min_directional_distance, "
                "  top_n = EXCLUDED.top_n, "
                "  dte_min = EXCLUDED.dte_min, "
                "  dte_max = EXCLUDED.dte_max, "
                "  mid_min = EXCLUDED.mid_min, "
                "  mid_max = EXCLUDED.mid_max, "
                "  updated_at = now()",
                (settings["price_floor"], int(settings["volume_floor"]),
                 settings["min_directional_distance"],
                 settings["top_n"], settings["dte_min"], settings["dte_max"],
                 settings["mid_min"], settings["mid_max"]),
            )
    except Exception as exc:
        log.warning("save_settings failed: %s", exc)
    finally:
        invalidate_preview_cache()
    return settings


# --- Preview-counts endpoint -----------------------------------------------
# Uses the shared _pre_score_cached() helper above so the next scan_universe
# call within the cache TTL reuses the same pre-scored list.

def preview_counts(price_floor: float | None = None,
                   volume_floor: float | None = None,
                   min_directional_distance: float | None = None,
                   force: bool = False) -> dict:
    """Run pre_score_universe with the given gates and return JUST the
    counts (not the per-ticker pre_scored list, which is large). 5-min
    cached via the shared `_pre_score_cached` helper; pass force=True
    to bypass."""
    settings = load_settings()
    pf = settings["price_floor"] if price_floor is None else float(price_floor)
    vf = settings["volume_floor"] if volume_floor is None else float(volume_floor)
    md = (settings["min_directional_distance"]
          if min_directional_distance is None else float(min_directional_distance))

    result, was_cached = _pre_score_cached(pf, vf, md, force=force)
    top_bull = [r for r in result["pre_scored"] if r["direction_bias"] == "call"][:5]
    top_bear = [r for r in result["pre_scored"] if r["direction_bias"] == "put"][:5]
    return {
        "snap_date": result["snap_date"],
        "scanned": result["scanned"],
        "liquid": result["liquid"],
        "qualifying": result["qualifying"],
        "call_bias": result["call_bias"],
        "put_bias": result["put_bias"],
        "top_bull": [{"ticker": r["ticker"], "pre_composite": r["pre_composite"]}
                     for r in top_bull],
        "top_bear": [{"ticker": r["ticker"], "pre_composite": r["pre_composite"]}
                     for r in top_bear],
        "gates": {"price_floor": pf, "volume_floor": int(vf),
                  "min_directional_distance": md},
        "computed_at": time.time(),
        "cached": was_cached,
    }
