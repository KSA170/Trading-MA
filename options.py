"""
Options recommendation engine.

Pipeline for `recommend_for_ticker(ticker)`:
  1. Optionability gate — chain exists, price floor, mcap floor.
  2. Direction signal — score the bull case from multiple sources
     (price trajectory, insider activity, catalysts, fundamentals,
     sector momentum). >+15 → call, <-15 → put, otherwise no trade.
  3. IV context — current ATM IV vs 20-day realized volatility as
     a proxy for IV rank (until we have 60+ days of stored history).
     "Cheap" IV (realized > implied) favors buying premium; "rich"
     IV (implied >> realized) suggests caution on long single legs.
  4. Contract selection — within 15-60 DTE, pick the strike closest
     to target delta (0.35) with adequate liquidity (OI >= 100,
     bid-ask spread <= 15% of mid).
  5. Verdict — BUY / WATCH / PASS based on the collective score.
  6. Rationale — concatenated reasons for human review.

No automated execution — output is informational. Adds a disclaimer
flag on every recommendation so the UI can surface "not financial
advice" prominently.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta
from typing import Any

log = logging.getLogger("options")


# --- tuning constants -----------------------------------------------------

DTE_MIN                 = 15
DTE_MAX                 = 60
TARGET_DELTA            = 0.35   # OTM directional bet, gamma/theta balance
DELTA_BAND              = (0.25, 0.50)   # acceptable strike range
OI_FLOOR                = 100    # liquidity gate per contract
SPREAD_FRAC_MAX         = 0.15   # max (ask-bid)/mid
PRICE_FLOOR             = 20.0   # below ~$20 strike granularity is poor
RISK_FREE_RATE          = 0.045  # current short-end rate; tweak if needed

# Direction-score bands → call/put/skip decision
DIRECTION_CALL_MIN      = 15
DIRECTION_PUT_MAX       = -15

# Final verdict bands (max ~30 with all signals stacked)
VERDICT_BUY_MIN         = 18
VERDICT_WATCH_MIN       = 8

# Sector ETF mapping — keep it small, just the canonical SPDRs.
_SECTOR_ETFS = {
    "Technology":             "XLK",
    "Communication Services": "XLC",
    "Financial Services":     "XLF",
    "Energy":                 "XLE",
    "Healthcare":             "XLV",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    "Industrials":            "XLI",
    "Basic Materials":        "XLB",
    "Utilities":              "XLU",
    "Real Estate":            "XLRE",
}


# --- schema ---------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS options_recommendations (
    as_of            DATE NOT NULL,
    ticker           TEXT NOT NULL,
    direction        TEXT NOT NULL,                       -- 'call' | 'put'
    verdict          TEXT NOT NULL,                       -- 'BUY' | 'WATCH' | 'PASS'
    score            REAL NOT NULL,
    contract_symbol  TEXT NOT NULL,
    strike           REAL,
    expiration       DATE,
    dte              INT,
    mid_price        REAL,
    delta            REAL,
    iv               REAL,
    open_interest    INT,
    rationale        TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, ticker)
);

CREATE TABLE IF NOT EXISTS options_iv_history (
    -- ATM 30-day IV captured nightly. After ~60 days of history we
    -- can compute real IV rank from this instead of the realized-vol
    -- proxy; until then it's just being collected.
    ticker      TEXT NOT NULL,
    as_of       DATE NOT NULL,
    atm_iv      REAL NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, as_of)
);
"""


def init_tables() -> None:
    import snapshots
    if not snapshots.enabled():
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(_SCHEMA)
    except Exception as exc:
        log.warning("options.init_tables failed: %s", exc)


# --- math helpers ---------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """Standard-normal CDF without a scipy dep."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_delta(spot: float, strike: float, t_years: float,
              sigma: float, is_call: bool,
              r: float = RISK_FREE_RATE) -> float:
    """Black-Scholes delta. Returns 0 for degenerate inputs rather
    than raising — caller iterates over chain rows and would have to
    catch otherwise."""
    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * math.sqrt(t_years))
    cdf_d1 = _norm_cdf(d1)
    return cdf_d1 if is_call else (cdf_d1 - 1.0)


def _realized_vol_20d(closes: list[float]) -> float | None:
    """Annualised stdev of 20 trailing daily log-returns. None if
    insufficient data."""
    if not closes or len(closes) < 21:
        return None
    rets = []
    for i in range(len(closes) - 20, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev > 0 and curr > 0:
            rets.append(math.log(curr / prev))
    if len(rets) < 10:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


# --- option chain fetch ---------------------------------------------------

def _fetch_chains_in_window(ticker: str,
                            dte_min: int = DTE_MIN,
                            dte_max: int = DTE_MAX) -> list[dict]:
    """Pull every option chain with `dte_min <= DTE <= dte_max`.
    Returns list of {expiration, dte, calls_df, puts_df}. Empty list
    when the ticker isn't optionable or yfinance returned nothing."""
    try:
        import yfinance as yf
    except Exception as exc:
        log.warning("yfinance import failed: %s", exc)
        return []
    try:
        yf_ticker = yf.Ticker(ticker)
        expirations = list(yf_ticker.options or ())
    except Exception as exc:
        log.warning("options chain lookup failed for %s: %s", ticker, exc)
        return []
    today = date.today()
    out: list[dict] = []
    for exp_str in expirations:
        try:
            exp = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (exp - today).days
        if not (dte_min <= dte <= dte_max):
            continue
        try:
            chain = yf_ticker.option_chain(exp_str)
        except Exception as exc:
            log.warning("option_chain(%s, %s) failed: %s", ticker, exp_str, exc)
            continue
        out.append({
            "expiration": exp_str,
            "dte": dte,
            "calls": chain.calls,
            "puts": chain.puts,
        })
    return out


def _select_contract(chain_df, current_price: float, t_years: float,
                     is_call: bool,
                     target_delta: float = TARGET_DELTA) -> dict | None:
    """Walk one expiration's chain, score every row by |delta - target|
    after liquidity filters, return the closest match. None if no
    contract clears the floors."""
    if chain_df is None or len(chain_df) == 0:
        return None
    best = None
    best_diff = float("inf")
    for _, row in chain_df.iterrows():
        try:
            strike = float(row.get("strike") or 0)
            iv = float(row.get("impliedVolatility") or 0)
            bid = float(row.get("bid") or 0)
            ask = float(row.get("ask") or 0)
            oi = int(row.get("openInterest") or 0)
            vol = int(row.get("volume") or 0)
            contract_sym = str(row.get("contractSymbol") or "")
        except (TypeError, ValueError):
            continue
        if strike <= 0 or iv <= 0 or bid <= 0 or ask <= 0:
            continue
        if oi < OI_FLOOR:
            continue
        mid = (bid + ask) / 2.0
        if mid <= 0:
            continue
        if (ask - bid) / mid > SPREAD_FRAC_MAX:
            continue
        delta = _bs_delta(current_price, strike, t_years, iv, is_call)
        if not (DELTA_BAND[0] <= abs(delta) <= DELTA_BAND[1]):
            continue
        diff = abs(abs(delta) - target_delta)
        if diff < best_diff:
            best_diff = diff
            best = {
                "contract_symbol": contract_sym,
                "strike":          strike,
                "bid":             bid,
                "ask":             ask,
                "mid":             round(mid, 2),
                "delta":           round(delta, 4),
                "iv":              round(iv, 4),
                "open_interest":   oi,
                "volume":          vol,
            }
    return best


# --- direction signal -----------------------------------------------------

def _direction_signal(ticker: str, snap_row: dict | None,
                      fund: dict | None,
                      insider: dict | None,
                      news: list[dict] | None,
                      sector_alignment: dict | None,
                      ) -> dict:
    """Score the bull case across price trajectory, insider activity,
    catalysts, fundamentals, and sector context. Returns:
      {direction: 'call'|'put'|None, score: int, reasons: list[str]}
    """
    score = 0
    reasons: list[str] = []

    if snap_row:
        close       = _to_f(snap_row.get("close"))
        prior_close = _to_f(snap_row.get("prior_close"))
        ema21       = _to_f(snap_row.get("ema21"))
        ema50       = _to_f(snap_row.get("ema50"))
        macd_val    = _to_f(snap_row.get("macd"))
        macd_hist   = _to_f(snap_row.get("macd_hist"))
        rsi         = _to_f(snap_row.get("rsi"))

        if close and prior_close and prior_close > 0:
            pct = (close - prior_close) / prior_close * 100.0
            if   pct >=  3:  score += 8; reasons.append(f"+{pct:.1f}% last bar")
            elif pct >=  1:  score += 4
            elif pct <= -3:  score -= 8; reasons.append(f"{pct:.1f}% last bar")
            elif pct <= -1:  score -= 4
        if ema21 and ema50:
            if ema21 > ema50:
                score += 5; reasons.append("EMA21 > EMA50 (uptrend)")
            else:
                score -= 5; reasons.append("EMA21 < EMA50 (downtrend)")
        if macd_val is not None:
            if macd_val > 0:
                score += 4; reasons.append("MACD line positive")
            else:
                score -= 4; reasons.append("MACD line negative")
        if macd_hist is not None:
            if macd_hist > 0: score += 2
            else:             score -= 2
        if rsi is not None:
            if   rsi >= 70: score -= 3; reasons.append(f"RSI {rsi:.0f} overbought")
            elif rsi <= 30: score += 3; reasons.append(f"RSI {rsi:.0f} oversold")

    if insider and _is_recent_insider(insider):
        code = (insider.get("code") or "").upper()
        if code == "P":
            score += 8; reasons.append("recent insider BUY")
        elif code == "S":
            score -= 4; reasons.append("recent insider SELL")

    # Catalysts as a directional tailwind. Without sentiment analysis
    # we can only treat presence-of-news as mildly bullish since most
    # momentum-stock news is "up" news. Don't let it flip the sign.
    n_news = len(news or [])
    if n_news >= 1:
        bump = min(3, n_news)
        score += bump
        reasons.append(f"{n_news} recent catalyst(s)")

    # Fundamentals — only flag extremes so they don't drown out price action.
    if fund:
        rev_growth = fund.get("revenue_growth_yoy")
        if isinstance(rev_growth, (int, float)):
            if rev_growth >= 0.20:
                score += 3; reasons.append(f"revenue +{rev_growth*100:.0f}% YoY")
            elif rev_growth <= -0.10:
                score -= 3; reasons.append(f"revenue {rev_growth*100:.0f}% YoY")

    if sector_alignment:
        a = sector_alignment.get("pct_change_5d")
        if isinstance(a, (int, float)):
            if   a >=  3: score += 4; reasons.append(f"{sector_alignment.get('sector_etf')} +{a:.1f}% 5d (sector tailwind)")
            elif a >=  1: score += 2
            elif a <= -3: score -= 4; reasons.append(f"{sector_alignment.get('sector_etf')} {a:.1f}% 5d (sector headwind)")
            elif a <= -1: score -= 2

    if score >= DIRECTION_CALL_MIN:
        direction = "call"
    elif score <= DIRECTION_PUT_MAX:
        direction = "put"
    else:
        direction = None
    return {"direction": direction, "score": score, "reasons": reasons}


# --- IV context -----------------------------------------------------------

def _atm_iv(chains: list[dict], current_price: float) -> float | None:
    """Pull the closest-to-30-DTE call's ATM IV as a single
    representative volatility quote. Falls back to closest-to-30-DTE
    put if calls aren't useful."""
    if not chains or current_price <= 0:
        return None
    best_chain = min(chains, key=lambda c: abs(c["dte"] - 30))
    for df in (best_chain.get("calls"), best_chain.get("puts")):
        if df is None or len(df) == 0:
            continue
        try:
            df_atm = df.iloc[(df["strike"] - current_price).abs().argsort()].head(3)
            iv_vals = [float(v) for v in df_atm["impliedVolatility"].tolist() if v and v > 0]
            if iv_vals:
                return sum(iv_vals) / len(iv_vals)
        except Exception:
            continue
    return None


def _iv_regime(atm_iv: float | None, realized_vol_20d: float | None) -> dict:
    """Until we have 60+ days of stored IV history, use the ratio
    IV / 20-day realized vol as the cheap/rich gauge:
      ratio < 1.0  → IV below realized; options unusually cheap.
      ratio ~ 1.2  → typical premium for unknown future vol.
      ratio > 1.5  → IV rich vs reality; risky to buy premium.
    """
    if atm_iv is None or realized_vol_20d is None or realized_vol_20d <= 0:
        return {"atm_iv": atm_iv, "realized_vol_20d": realized_vol_20d,
                "ratio": None, "regime": "unknown", "score": 0}
    ratio = atm_iv / realized_vol_20d
    if   ratio < 0.9:  regime, sc = "cheap",    +5
    elif ratio < 1.2:  regime, sc = "moderate", +2
    elif ratio < 1.5:  regime, sc = "fair",      0
    else:              regime, sc = "rich",     -5
    return {"atm_iv": round(atm_iv, 4),
            "realized_vol_20d": round(realized_vol_20d, 4),
            "ratio": round(ratio, 3),
            "regime": regime,
            "score": sc}


# --- sector alignment -----------------------------------------------------

def _sector_alignment(sector: str | None) -> dict | None:
    """Look up the SPDR sector ETF for this stock's sector and return
    its 5-day % change. Used as a directional tailwind/headwind in the
    score."""
    if not sector:
        return None
    etf = _SECTOR_ETFS.get(sector)
    if not etf:
        return None
    try:
        import yfinance as yf
        hist = yf.Ticker(etf).history(period="10d", interval="1d")
        if hist is None or len(hist) < 6:
            return {"sector_etf": etf, "pct_change_5d": None}
        closes = hist["Close"].tolist()
        last = float(closes[-1])
        ref  = float(closes[-6])  # 5 trading days back
        if ref <= 0:
            return {"sector_etf": etf, "pct_change_5d": None}
        pct = (last - ref) / ref * 100.0
        return {"sector_etf": etf, "pct_change_5d": round(pct, 2)}
    except Exception as exc:
        log.warning("sector ETF lookup failed for %s/%s: %s", sector, etf, exc)
        return {"sector_etf": etf, "pct_change_5d": None}


# --- earnings proximity ---------------------------------------------------

def _next_earnings_date(ticker: str) -> str | None:
    """yfinance's `Ticker.calendar` returns a dict with 'Earnings Date'
    in some cases, or `Ticker.earnings_dates` returns a DataFrame.
    Try both; return ISO date string of the next upcoming earnings."""
    try:
        import yfinance as yf
        yft = yf.Ticker(ticker)
        try:
            cal = yft.calendar
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if isinstance(ed, list) and ed:
                    return _ensure_iso_date(ed[0])
                if ed:
                    return _ensure_iso_date(ed)
        except Exception:
            pass
        try:
            df = yft.earnings_dates
            if df is not None and len(df) > 0:
                import pandas as _pd
                future = df[df.index >= _pd.Timestamp.now(tz=df.index.tz)] if df.index.tz else df[df.index >= _pd.Timestamp.now()]
                if len(future) > 0:
                    return str(future.index[0].date())
        except Exception:
            pass
    except Exception as exc:
        log.warning("earnings lookup failed for %s: %s", ticker, exc)
    return None


def _ensure_iso_date(v: Any) -> str | None:
    try:
        if isinstance(v, str):
            return v[:10]
        if hasattr(v, "isoformat"):
            return v.isoformat()[:10]
    except Exception:
        pass
    return None


def _spans_earnings(expiration: str, earnings_date: str | None) -> bool:
    if not earnings_date:
        return False
    try:
        exp = datetime.strptime(expiration, "%Y-%m-%d").date()
        ed  = datetime.strptime(earnings_date, "%Y-%m-%d").date()
        return date.today() <= ed <= exp
    except (TypeError, ValueError):
        return False


# --- snapshot lookup ------------------------------------------------------

def _load_snapshot_row(ticker: str) -> dict | None:
    import snapshots
    if not snapshots.enabled():
        return None
    dates = snapshots.available_dates(1)
    if not dates:
        return None
    for _t, row in snapshots.iter_for_date(dates[0], tickers=[ticker]):
        return row
    return None


def _closes_from_bars(snap_row: dict | None) -> list[float]:
    if not snap_row:
        return []
    import scanner_momentum
    bars = scanner_momentum._bars_from_row(snap_row) or []
    out = []
    for b in bars:
        try:
            c = float(b.get("c") or 0)
            if c > 0:
                out.append(c)
        except (TypeError, ValueError):
            continue
    return out


# --- main entry point -----------------------------------------------------

def recommend_for_ticker(ticker: str) -> dict:
    """Full pipeline: optionability → direction → IV → contract →
    verdict → rationale. Returns a structured dict either with a
    populated recommendation or with reason='...' explaining why no
    trade was found."""
    ticker = (ticker or "").strip().upper()
    out: dict = {
        "ticker": ticker,
        "as_of": date.today().isoformat(),
        "direction": None,
        "verdict": "PASS",
        "score": 0,
        "contract": None,
        "iv_context": None,
        "sector": None,
        "earnings_date": None,
        "earnings_spans_expiration": False,
        "rationale": [],
        "reason": None,
        "disclaimer": "Informational only — not investment advice. "
                       "Options can expire worthless; size positions accordingly.",
    }
    if not ticker:
        out["reason"] = "ticker required"
        return out

    # 1. Snapshot baseline (gives us price, EMA stack, MACD, RSI, sector)
    snap_row = _load_snapshot_row(ticker)
    if not snap_row:
        out["reason"] = (
            f"{ticker} not in latest snapshot — outside the screened "
            f"universe, or the nightly job hasn't covered it"
        )
        return out

    current_price = _to_f(snap_row.get("close"))
    if not current_price or current_price < PRICE_FLOOR:
        out["reason"] = (
            f"price ${current_price or 0:.2f} below floor "
            f"${PRICE_FLOOR:.0f} — options strike granularity too coarse"
        )
        return out

    # 2. Enrichment (insider, fundamentals, catalysts, sector)
    import enrich
    insider = enrich.last_insider_transaction(ticker)
    fund    = enrich.fundamentals(ticker)
    news    = enrich.recent_news(ticker, limit=4, max_age_days=7)
    sector  = (fund or {}).get("sector") or snap_row.get("sector")
    out["sector"] = sector
    sector_align = _sector_alignment(sector)

    # 3. Direction signal
    dir_sig = _direction_signal(ticker, snap_row, fund, insider, news, sector_align)
    out["score"] = dir_sig["score"]
    out["rationale"].extend(dir_sig["reasons"])
    if dir_sig["direction"] is None:
        out["reason"] = (
            f"no clear directional bias (score {dir_sig['score']:+d}; "
            f"need ≥{DIRECTION_CALL_MIN} for call, ≤{DIRECTION_PUT_MAX} for put)"
        )
        return out
    out["direction"] = dir_sig["direction"]

    # 4. Option chain + IV context
    chains = _fetch_chains_in_window(ticker, DTE_MIN, DTE_MAX)
    if not chains:
        out["reason"] = (
            f"no liquid option chain available in {DTE_MIN}-{DTE_MAX} DTE "
            f"window (yfinance returned nothing or ticker isn't optionable)"
        )
        return out
    atm_iv = _atm_iv(chains, current_price)
    realized_vol = _realized_vol_20d(_closes_from_bars(snap_row))
    iv_ctx = _iv_regime(atm_iv, realized_vol)
    out["iv_context"] = iv_ctx
    out["score"] += iv_ctx["score"]
    if iv_ctx["regime"] == "rich":
        out["rationale"].append(
            f"IV/realized ratio {iv_ctx['ratio']:.2f} — options rich vs realized"
        )
    elif iv_ctx["regime"] == "cheap":
        out["rationale"].append(
            f"IV/realized ratio {iv_ctx['ratio']:.2f} — options cheap vs realized"
        )

    # 5. Earnings flag (flag, don't filter — per user preference)
    earnings = _next_earnings_date(ticker)
    out["earnings_date"] = earnings

    # 6. Pick the best contract across all in-window expirations
    is_call = (out["direction"] == "call")
    best_pick = None
    best_diff = float("inf")
    for ch in chains:
        df = ch["calls"] if is_call else ch["puts"]
        t_years = max(ch["dte"], 1) / 365.0
        pick = _select_contract(df, current_price, t_years, is_call)
        if not pick:
            continue
        diff = abs(abs(pick["delta"]) - TARGET_DELTA)
        if diff < best_diff:
            best_diff = diff
            pick["expiration"] = ch["expiration"]
            pick["dte"] = ch["dte"]
            pick["spans_earnings"] = _spans_earnings(ch["expiration"], earnings)
            best_pick = pick

    if not best_pick:
        out["reason"] = (
            f"no contract in the {DTE_MIN}-{DTE_MAX} DTE window cleared "
            f"liquidity (OI ≥ {OI_FLOOR}, spread ≤ {int(SPREAD_FRAC_MAX*100)}% of mid) "
            f"with delta in [{DELTA_BAND[0]:.2f}, {DELTA_BAND[1]:.2f}]"
        )
        return out

    out["contract"] = best_pick
    out["earnings_spans_expiration"] = best_pick["spans_earnings"]
    if best_pick["spans_earnings"]:
        out["rationale"].append(
            f"⚠ contract spans earnings ({earnings}) — IV crush risk"
        )

    # 7. Verdict — final classification using the total score
    if out["score"] >= VERDICT_BUY_MIN and not best_pick["spans_earnings"]:
        out["verdict"] = "BUY"
    elif out["score"] >= VERDICT_WATCH_MIN:
        out["verdict"] = "WATCH"
    else:
        out["verdict"] = "PASS"

    out["reason"] = (
        f"{out['direction'].upper()} {best_pick['expiration']} "
        f"${best_pick['strike']:.2f} · "
        f"delta {best_pick['delta']:+.2f} · "
        f"mid ${best_pick['mid']:.2f} · "
        f"score {out['score']:+d}"
    )
    return out


# --- persistence ----------------------------------------------------------

def save_recommendation(rec: dict) -> bool:
    """Persist a recommendation. Idempotent on (as_of, ticker)."""
    import snapshots
    if not snapshots.enabled() or not rec.get("contract"):
        return False
    try:
        c = rec["contract"]
        with snapshots._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO options_recommendations "
                "(as_of, ticker, direction, verdict, score, contract_symbol, "
                "strike, expiration, dte, mid_price, delta, iv, "
                "open_interest, rationale) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (as_of, ticker) DO UPDATE SET "
                "direction = EXCLUDED.direction, "
                "verdict = EXCLUDED.verdict, "
                "score = EXCLUDED.score, "
                "contract_symbol = EXCLUDED.contract_symbol, "
                "strike = EXCLUDED.strike, "
                "expiration = EXCLUDED.expiration, "
                "dte = EXCLUDED.dte, "
                "mid_price = EXCLUDED.mid_price, "
                "delta = EXCLUDED.delta, "
                "iv = EXCLUDED.iv, "
                "open_interest = EXCLUDED.open_interest, "
                "rationale = EXCLUDED.rationale, "
                "created_at = now()",
                (rec["as_of"], rec["ticker"], rec["direction"], rec["verdict"],
                 rec["score"], c["contract_symbol"], c["strike"],
                 c["expiration"], c["dte"], c["mid"], c["delta"], c["iv"],
                 c["open_interest"], json.dumps(rec.get("rationale") or [])),
            )
        return True
    except Exception as exc:
        log.warning("options.save_recommendation failed: %s", exc)
        return False


def load_recommendations(as_of: str | None = None) -> list[dict]:
    """Return recommendations for `as_of` (default: most recent date
    with any rows). Newest score first."""
    import snapshots
    if not snapshots.enabled():
        return []
    try:
        with snapshots._conn() as conn, conn.cursor() as cur:
            if as_of:
                cur.execute(
                    "SELECT as_of, ticker, direction, verdict, score, "
                    "contract_symbol, strike, expiration, dte, mid_price, "
                    "delta, iv, open_interest, rationale "
                    "FROM options_recommendations WHERE as_of = %s "
                    "ORDER BY score DESC", (as_of,),
                )
            else:
                cur.execute(
                    "SELECT as_of, ticker, direction, verdict, score, "
                    "contract_symbol, strike, expiration, dte, mid_price, "
                    "delta, iv, open_interest, rationale "
                    "FROM options_recommendations WHERE as_of = ("
                    "  SELECT MAX(as_of) FROM options_recommendations"
                    ") ORDER BY score DESC"
                )
            rows = cur.fetchall()
    except Exception as exc:
        log.warning("options.load_recommendations failed: %s", exc)
        return []
    out = []
    for r in rows:
        try:
            rationale = json.loads(r[13]) if r[13] else []
        except Exception:
            rationale = []
        out.append({
            "as_of": r[0].isoformat() if r[0] else None,
            "ticker": r[1],
            "direction": r[2],
            "verdict": r[3],
            "score": float(r[4]) if r[4] is not None else 0,
            "contract_symbol": r[5],
            "strike": float(r[6]) if r[6] is not None else None,
            "expiration": r[7].isoformat() if r[7] else None,
            "dte": int(r[8]) if r[8] is not None else None,
            "mid_price": float(r[9]) if r[9] is not None else None,
            "delta": float(r[10]) if r[10] is not None else None,
            "iv": float(r[11]) if r[11] is not None else None,
            "open_interest": int(r[12]) if r[12] is not None else None,
            "rationale": rationale,
        })
    return out


# --- internal -------------------------------------------------------------

def _to_f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _is_recent_insider(insider: dict | None, max_days: int = 60) -> bool:
    if not insider:
        return False
    raw = insider.get("transaction_date") or insider.get("filing_date")
    if not raw:
        return False
    try:
        d = datetime.strptime(raw, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    return 0 <= (datetime.utcnow() - d).days <= max_days
