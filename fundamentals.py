"""Fundamental analysis for a single ticker.

Pulls the three statements plus the company profile and the earnings
calendar from yfinance (free, no API key), reduces them to the handful of
series that actually carry information, and scores them deterministically.

Three principles, all learned the hard way elsewhere in this app:

  1. EVERY SCORE SHOWS ITS NUMBERS. A sub-score is (value, score, detail)
     and the detail says what the value was and what it was compared
     against. A verdict you cannot audit is a verdict you cannot trust,
     and the checklist alerts already work this way.

  2. MISSING IS NOT NEUTRAL. A company with no cash-flow statement does
     not score 0 on cash generation — it is dropped and the composite
     renormalises over what was actually present, the same treatment
     market_intel.conviction and options._score_catalyst use. Scoring an
     absent input as "average" quietly invents evidence.

  3. SHORT TERM AND LONG TERM COME FROM DIFFERENT INSTRUMENTS. The
     long-term view reads the statements. The short-term view reads the
     tape (price vs the SMA stack, RSI, MACD) plus event proximity,
     because a balance sheet says nothing about the next two weeks.

The AI narrative is optional and additive: with no ANTHROPIC_API_KEY the
module returns exactly the same scorecard, and `narrative` is None. It
never feeds the verdict — the numbers decide, the prose explains.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from datetime import date, datetime, timezone

log = logging.getLogger("fundamentals")

# Statements change quarterly; the profile barely moves. Six hours keeps a
# working session instant without serving a stale quarter after a report.
_CACHE_TTL = 6 * 3600
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 400

MAX_TICKERS = 15          # per request; each ticker is ~6 Yahoo calls


# --- small helpers ---------------------------------------------------------

def _f(v):
    """Coerce to a finite float, or None. pandas/numpy scalars, NaN, inf
    and the various string shapes Yahoo returns all land here."""
    if v is None:
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _row(df, *names):
    """First matching row of a statement as a list of floats, newest
    first, or [] when none of `names` is present.

    Statement row labels differ by filer and have been renamed between
    yfinance versions ("Total Revenue" vs "TotalRevenue", "Operating
    Expense" vs "Total Expenses"), so every read passes several
    candidates rather than betting on one."""
    if df is None or getattr(df, "empty", True):
        return []
    try:
        index = {str(i).strip().lower(): i for i in df.index}
    except Exception:
        return []
    for want in names:
        key = str(want).strip().lower()
        if key in index:
            try:
                return [_f(v) for v in df.loc[index[key]].tolist()]
            except Exception:
                continue
    return []


def _periods(df, limit=5):
    """Column labels of a statement as ISO dates, newest first."""
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for c in list(df.columns)[:limit]:
        try:
            out.append(c.strftime("%Y-%m-%d"))
        except Exception:
            out.append(str(c)[:10])
    return out


def _pct_change(series):
    """Period-over-period change of a newest-first series, as percents,
    index-aligned with it. Each entry compares that period with the one
    after it (the older one), so the final entry is always None — there is
    no earlier period to compare the oldest against."""
    out = []
    for i, now in enumerate(series):
        prev = series[i + 1] if i + 1 < len(series) else None
        out.append(((now - prev) / abs(prev) * 100.0)
                   if (now is not None and prev not in (None, 0)) else None)
    return out


def _yoy(series):
    """Newest period vs the one before it, in percent."""
    if len(series) < 2:
        return None
    now, prev = series[0], series[1]
    if now is None or prev in (None, 0):
        return None
    return (now - prev) / abs(prev) * 100.0


def _cagr(series):
    """Compound annual growth over the full newest-first series. None when
    the oldest point is zero or negative — a growth rate off a negative
    base is arithmetic, not information."""
    pts = [v for v in series if v is not None]
    if len(pts) < 2:
        return None
    newest, oldest = pts[0], pts[-1]
    years = len(pts) - 1
    if oldest is None or oldest <= 0 or newest is None or newest <= 0:
        return None
    return ((newest / oldest) ** (1.0 / years) - 1.0) * 100.0


def _safe_div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


# --- scoring ---------------------------------------------------------------

def _band(value, thresholds, labels):
    """Map a value onto (score, label) using ascending `thresholds`.
    Scores run -2..+2; `labels` must be one longer than `thresholds`."""
    if value is None:
        return None, None
    idx = 0
    for t in thresholds:
        if value >= t:
            idx += 1
    scores = [-2, -1, 0, 1, 2][:len(labels)]
    return scores[idx], labels[idx]


class _Card:
    """Collects sub-scores and renormalises the composite over the ones
    that were actually measurable."""

    def __init__(self):
        self.items: list[dict] = []

    def add(self, key, label, value, score, detail, unit=""):
        self.items.append({
            "key": key, "label": label, "value": value, "score": score,
            "detail": detail, "unit": unit,
        })

    def composite(self):
        scored = [i["score"] for i in self.items if i["score"] is not None]
        if not scored:
            return None, 0
        return sum(scored) / len(scored), len(scored)


def _verdict(avg, scale):
    """Turn a mean sub-score in [-2, +2] into a word. Deliberately not
    BUY/SELL: the scorecard measures business health and tape posture, and
    labelling that an instruction would overstate what it knows."""
    if avg is None:
        return "No data", "nothing measurable was returned for this ticker"
    if avg >= 1.2:
        return scale[0], ""
    if avg >= 0.4:
        return scale[1], ""
    if avg > -0.4:
        return scale[2], ""
    if avg > -1.2:
        return scale[3], ""
    return scale[4], ""


LONG_SCALE = ("Strong", "Constructive", "Mixed", "Weak", "Deteriorating")
SHORT_SCALE = ("Constructive", "Leaning positive", "Neutral",
               "Leaning cautious", "Cautious")


# --- the analysis ----------------------------------------------------------

def _company(info):
    return {
        "name": (info.get("longName") or info.get("shortName")
                 or info.get("displayName")),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "employees": info.get("fullTimeEmployees"),
        "website": info.get("website"),
        "summary": info.get("longBusinessSummary"),
        "market_cap": _f(info.get("marketCap")),
        "enterprise_value": _f(info.get("enterpriseValue")),
        "shares_out": _f(info.get("sharesOutstanding")),
        "price": _f(info.get("currentPrice") or info.get("regularMarketPrice")),
        "week52_high": _f(info.get("fiftyTwoWeekHigh")),
        "week52_low": _f(info.get("fiftyTwoWeekLow")),
        "trailing_pe": _f(info.get("trailingPE")),
        "forward_pe": _f(info.get("forwardPE")),
        "price_to_sales": _f(info.get("priceToSalesTrailing12Months")),
        "short_pct_float": _f(info.get("shortPercentOfFloat")),
    }


def _revenue_block(inc, qinc, card):
    rev = _row(inc, "Total Revenue", "TotalRevenue", "Operating Revenue")
    qrev = _row(qinc, "Total Revenue", "TotalRevenue", "Operating Revenue")
    cogs = _row(inc, "Cost Of Revenue", "CostOfRevenue",
                "Reconciled Cost Of Revenue")
    gross = _row(inc, "Gross Profit", "GrossProfit")
    if not gross and rev and cogs:
        gross = [(_f(r) - _f(c)) if (r is not None and c is not None) else None
                 for r, c in zip(rev, cogs)]

    yoy = _yoy(rev)
    s, lbl = _band(yoy, [-10, 0, 10, 25],
                   ["contracting hard", "contracting", "flat",
                    "growing", "growing fast"])
    card.add("revenue_growth", "Revenue growth (latest FY, YoY)", yoy, s,
             f"{yoy:+.1f}% year over year — {lbl}" if yoy is not None
             else "no comparable annual revenue", "%")

    cagr = _cagr(rev)
    s, lbl = _band(cagr, [-5, 3, 12, 25],
                   ["shrinking", "stagnant", "modest", "solid", "rapid"])
    card.add("revenue_cagr", f"Revenue CAGR ({max(0, len(rev) - 1)}y)", cagr, s,
             f"{cagr:+.1f}% a year — {lbl}" if cagr is not None
             else "not enough annual history", "%")

    qyoy = None
    if len(qrev) >= 5:                      # same quarter a year earlier
        now, prior = qrev[0], qrev[4]
        if now is not None and prior not in (None, 0):
            qyoy = (now - prior) / abs(prior) * 100.0
    s, lbl = _band(qyoy, [-10, 0, 10, 25],
                   ["contracting hard", "contracting", "flat",
                    "growing", "growing fast"])
    card.add("revenue_q_yoy", "Revenue growth (latest quarter, YoY)", qyoy, s,
             f"{qyoy:+.1f}% vs the same quarter last year — {lbl}"
             if qyoy is not None else "fewer than 5 quarters reported", "%")

    gm = _safe_div(gross[0] if gross else None, rev[0] if rev else None)
    gm = gm * 100.0 if gm is not None else None
    gm_prev = _safe_div(gross[1] if len(gross) > 1 else None,
                        rev[1] if len(rev) > 1 else None)
    gm_prev = gm_prev * 100.0 if gm_prev is not None else None
    s, lbl = _band(gm, [10, 30, 50, 70],
                   ["negative/none", "thin", "moderate", "healthy", "premium"])
    delta = (f", {gm - gm_prev:+.1f}pp vs prior year"
             if (gm is not None and gm_prev is not None) else "")
    card.add("gross_margin", "Gross margin", gm, s,
             f"{gm:.1f}% — {lbl}{delta}" if gm is not None
             else "gross profit not reported", "%")

    return {
        "periods": _periods(inc),
        "revenue": rev,
        "revenue_change_pct": _pct_change(rev),
        "cost_of_revenue": cogs,
        "gross_profit": gross,
        "quarterly_periods": _periods(qinc, 6),
        "quarterly_revenue": qrev,
        "revenue_yoy_pct": yoy,
        "revenue_cagr_pct": cagr,
        "revenue_q_yoy_pct": qyoy,
        "gross_margin_pct": gm,
    }


def _opex_block(inc, card, rev):
    rnd = _row(inc, "Research And Development", "ResearchAndDevelopment")
    sga = _row(inc, "Selling General And Administration",
               "Selling General And Administrative",
               "SellingGeneralAndAdministration")
    opex = _row(inc, "Operating Expense", "OperatingExpense", "Total Expenses")
    op_inc = _row(inc, "Operating Income", "OperatingIncome",
                  "Total Operating Income As Reported", "EBIT")
    net = _row(inc, "Net Income", "NetIncome",
               "Net Income Common Stockholders")

    om = _safe_div(op_inc[0] if op_inc else None, rev[0] if rev else None)
    om = om * 100.0 if om is not None else None
    s, lbl = _band(om, [-20, 0, 10, 25],
                   ["heavy losses", "loss-making", "breakeven",
                    "profitable", "highly profitable"])
    card.add("operating_margin", "Operating margin", om, s,
             f"{om:.1f}% — {lbl}" if om is not None
             else "operating income not reported", "%")

    # Operating leverage: is the cost base growing slower than the top line?
    # This is what separates a company scaling into profit from one buying
    # revenue, and neither margin level nor growth rate alone shows it.
    lev = None
    rev_g, opex_g = _yoy(rev), _yoy(opex)
    if rev_g is not None and opex_g is not None:
        lev = rev_g - opex_g
    s, lbl = _band(lev, [-10, -2, 2, 10],
                   ["costs outrunning revenue", "costs growing faster",
                    "costs tracking revenue", "scaling", "scaling strongly"])
    card.add("operating_leverage", "Operating leverage", lev, s,
             (f"revenue {rev_g:+.1f}% vs opex {opex_g:+.1f}% "
              f"({lev:+.1f}pp) — {lbl}") if lev is not None
             else "operating expense not comparable across years", "pp")

    return {
        "research_development": rnd,
        "sga": sga,
        "operating_expense": opex,
        "operating_income": op_inc,
        "net_income": net,
        "operating_margin_pct": om,
        "net_margin_pct": (_safe_div(net[0] if net else None,
                                     rev[0] if rev else None) or 0) * 100.0
                          if (net and rev and net[0] is not None
                              and rev[0]) else None,
        "opex_pct_of_revenue": [
            (_safe_div(o, r) * 100.0) if (_safe_div(o, r) is not None) else None
            for o, r in zip(opex, rev)
        ] if (opex and rev) else [],
        "operating_leverage_pp": lev,
    }


def _cashflow_block(cf, qcf, card, rev):
    ocf = _row(cf, "Operating Cash Flow", "OperatingCashFlow",
               "Cash Flow From Continuing Operating Activities")
    capex = _row(cf, "Capital Expenditure", "CapitalExpenditure")
    fcf = _row(cf, "Free Cash Flow", "FreeCashFlow")
    if not fcf and ocf:
        fcf = [(o + c) if (o is not None and c is not None) else None
               for o, c in zip(ocf, capex or [None] * len(ocf))]
    qocf = _row(qcf, "Operating Cash Flow", "OperatingCashFlow")

    latest_fcf = fcf[0] if fcf else None
    fcf_margin = _safe_div(latest_fcf, rev[0] if rev else None)
    fcf_margin = fcf_margin * 100.0 if fcf_margin is not None else None
    s, lbl = _band(fcf_margin, [-20, 0, 8, 20],
                   ["burning heavily", "burning cash", "around breakeven",
                    "cash generative", "strongly cash generative"])
    card.add("fcf_margin", "Free cash flow margin", fcf_margin, s,
             (f"{fcf_margin:.1f}% of revenue "
              f"({_money(latest_fcf)}) — {lbl}") if fcf_margin is not None
             else "free cash flow not derivable", "%")

    improving = None
    if len(fcf) >= 2 and fcf[0] is not None and fcf[1] is not None:
        improving = fcf[0] - fcf[1]
    s, lbl = _band(improving, [-1e9, -1, 1, 1e9],
                   ["much worse", "worse", "flat", "better", "much better"])
    card.add("fcf_trend", "Free cash flow direction", improving, s,
             (f"{_money(fcf[1])} → {_money(fcf[0])} — {lbl} than prior year")
             if improving is not None else "no comparable prior year")

    return {
        "periods": _periods(cf),
        "operating_cash_flow": ocf,
        "capital_expenditure": capex,
        "free_cash_flow": fcf,
        "quarterly_periods": _periods(qcf, 6),
        "quarterly_operating_cash_flow": qocf,
        "fcf_margin_pct": fcf_margin,
    }


def _balance_block(bs, card, cash_block):
    cash = _row(bs, "Cash And Cash Equivalents",
                "Cash Cash Equivalents And Short Term Investments",
                "CashAndCashEquivalents")
    debt = _row(bs, "Total Debt", "TotalDebt")
    equity = _row(bs, "Stockholders Equity", "StockholdersEquity",
                  "Total Equity Gross Minority Interest")
    cur_assets = _row(bs, "Current Assets", "Total Current Assets")
    cur_liab = _row(bs, "Current Liabilities", "Total Current Liabilities")

    net_cash = None
    if cash and debt and cash[0] is not None and debt[0] is not None:
        net_cash = cash[0] - debt[0]
    elif cash and cash[0] is not None and not debt:
        net_cash = cash[0]
    ratio = _safe_div(net_cash, cash_block.get("_mktcap"))
    ratio = ratio * 100.0 if ratio is not None else None
    s, lbl = _band(ratio, [-30, -5, 5, 20],
                   ["heavily levered", "net debt", "balanced",
                    "net cash", "strong net cash"])
    card.add("net_cash", "Net cash position", net_cash, s,
             (f"{_money(net_cash)} net "
              f"{'cash' if net_cash and net_cash >= 0 else 'debt'}"
              + (f" ({ratio:+.0f}% of market cap)" if ratio is not None else "")
              + f" — {lbl}") if net_cash is not None
             else "cash and debt not both reported")

    current = _safe_div(cur_assets[0] if cur_assets else None,
                        cur_liab[0] if cur_liab else None)
    s, lbl = _band(current, [0.8, 1.2, 2.0, 3.5],
                   ["cannot cover near-term bills", "tight", "adequate",
                    "comfortable", "very liquid"])
    card.add("current_ratio", "Current ratio", current, s,
             f"{current:.2f}× current liabilities — {lbl}"
             if current is not None else "current assets/liabilities not split")

    # Runway only means something for a company actually burning cash.
    runway_q = None
    qocf = cash_block.get("quarterly_operating_cash_flow") or []
    burn = [v for v in qocf[:4] if v is not None and v < 0]
    if burn and cash and cash[0] is not None:
        avg_burn = abs(sum(burn) / len(burn))
        if avg_burn > 0:
            runway_q = cash[0] / avg_burn
    if runway_q is not None:
        s, lbl = _band(runway_q, [4, 8, 12, 20],
                       ["under a year", "about a year", "two years",
                        "three years", "well funded"])
        card.add("runway", "Cash runway", runway_q, s,
                 f"{runway_q:.1f} quarters at the recent burn rate — {lbl}",
                 "quarters")

    return {
        "periods": _periods(bs),
        "cash": cash,
        "total_debt": debt,
        "equity": equity,
        "current_assets": cur_assets,
        "current_liabilities": cur_liab,
        "net_cash": net_cash,
        "current_ratio": current,
        "runway_quarters": runway_q,
    }


def _money(v):
    """Sign outside the currency symbol — "-$115.95B", not "$-115.95B",
    which reads as a typo on a cash-flow line."""
    if v is None:
        return "n/a"
    a = abs(v)
    sign = "-" if v < 0 else ""
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{sign}${a / div:,.2f}{suf}"
    return f"{sign}${a:,.0f}"


def _catalysts(tk, info, qinc):
    """Dated, checkable events — not speculation about what might happen."""
    out = {"events": [], "earnings": None, "recent_surprises": [], "news": []}
    today = date.today()

    cal = {}
    try:
        cal = tk.calendar or {}
    except Exception:
        cal = {}
    ed = cal.get("Earnings Date")
    nxt = None
    if isinstance(ed, (list, tuple)) and ed:
        nxt = ed[0]
    elif ed:
        nxt = ed
    if isinstance(nxt, datetime):
        nxt = nxt.date()
    if isinstance(nxt, date):
        days = (nxt - today).days
        out["earnings"] = {
            "date": nxt.isoformat(), "days_away": days,
            "eps_estimate": _f(cal.get("Earnings Average")),
            "eps_low": _f(cal.get("Earnings Low")),
            "eps_high": _f(cal.get("Earnings High")),
            "revenue_estimate": _f(cal.get("Revenue Average")),
        }
        out["events"].append({
            "kind": "earnings", "date": nxt.isoformat(), "days_away": days,
            "label": f"Q results in {days} days" if days >= 0
                     else f"Q results {abs(days)} days ago",
            "detail": ("consensus EPS "
                       f"{_f(cal.get('Earnings Average')):+.3f}"
                       if _f(cal.get("Earnings Average")) is not None else ""),
        })

    exdiv = info.get("exDividendDate")
    if exdiv:
        try:
            d = datetime.fromtimestamp(float(exdiv), tz=timezone.utc).date()
            days = (d - today).days
            if -30 <= days <= 120:
                out["events"].append({
                    "kind": "ex_dividend", "date": d.isoformat(),
                    "days_away": days,
                    "label": f"Ex-dividend in {days} days" if days >= 0
                             else f"Went ex-dividend {abs(days)} days ago",
                    "detail": (f"yield {_f(info.get('dividendYield')) or 0:.2f}%"
                               if info.get("dividendYield") else ""),
                })
        except Exception:
            pass

    try:
        hist = tk.earnings_dates
        if hist is not None and not hist.empty:
            for idx, r in hist.head(8).iterrows():
                surprise = _f(r.get("Surprise(%)"))
                reported = _f(r.get("Reported EPS"))
                if surprise is None and reported is None:
                    continue
                try:
                    when = idx.strftime("%Y-%m-%d")
                except Exception:
                    when = str(idx)[:10]
                if when > today.isoformat():
                    continue
                out["recent_surprises"].append({
                    "date": when, "surprise_pct": surprise,
                    "reported_eps": reported,
                    "estimate_eps": _f(r.get("EPS Estimate")),
                })
            out["recent_surprises"] = out["recent_surprises"][:4]
    except Exception:
        pass

    try:
        import enrich
        out["news"] = enrich.recent_news(info.get("symbol") or "", limit=5,
                                         max_age_days=14)
    except Exception:
        out["news"] = []
    return out


def _short_term(tech, catalysts, card):
    """Tape posture plus event proximity. `tech` comes from the screener's
    own enriched columns, so this says the same thing the screener does
    rather than computing a second opinion."""
    if not tech:
        card.add("tape", "Price trend", None, None,
                 "no recent price history available")
        return

    price = _f(tech.get("price"))
    sma10, sma20, sma40 = (_f(tech.get("sma10")), _f(tech.get("sma20")),
                           _f(tech.get("sma40")))
    stack = [s for s in (sma10, sma20, sma40) if s is not None]
    above = sum(1 for s in stack if price is not None and price > s)
    if stack and price is not None:
        frac = above / len(stack)
        s, lbl = _band(frac, [0.01, 0.34, 0.67, 0.99],
                       ["below every average", "below most",
                        "mixed", "above most", "above every average"])
        card.add("tape", "Price vs the 10/20/40 SMA stack", frac, s,
                 f"above {above} of {len(stack)} — {lbl}")

    rsi = _f(tech.get("rsi14"))
    # Deliberately not "high RSI = sell". For a short-term posture read,
    # strength is strength; the extremes at both ends are what cost money.
    s, lbl = _band(rsi, [30, 45, 65, 80],
                   ["oversold", "weak", "neutral", "firm", "overbought"])
    if rsi is not None and rsi >= 80:
        s = 0
    card.add("rsi", "RSI(14)", rsi, s,
             f"{rsi:.1f} — {lbl}" if rsi is not None else "RSI unavailable")

    hist = _f(tech.get("macd_hist"))
    prev = _f(tech.get("macd_hist_prev"))
    if hist is not None:
        rising = (prev is not None and hist > prev)
        s = 1 if hist > 0 else -1
        if hist > 0 and rising:
            s = 2
        if hist < 0 and not rising:
            s = -2
        card.add("macd", "MACD histogram", hist, s,
                 f"{hist:+.3f} and {'expanding' if rising else 'contracting'}")

    e = catalysts.get("earnings") or {}
    days = e.get("days_away")
    if isinstance(days, int) and 0 <= days <= 45:
        # Binary event risk cuts both ways, so it never scores positive —
        # it is a reason to size differently, not a reason to be bullish.
        s = -2 if days <= 7 else (-1 if days <= 21 else 0)
        card.add("event_risk", "Earnings proximity", days, s,
                 f"reports in {days} days — binary event risk"
                 if days <= 21 else f"reports in {days} days", "days")


def analyze(ticker: str, tech: dict | None = None,
            use_cache: bool = True) -> dict:
    """Full fundamental analysis for one ticker. Never raises — an
    upstream failure returns a dict with `error` set so a multi-ticker
    request still renders the rest."""
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return {"ticker": ticker, "error": "no ticker"}
    now = time.time()
    if use_cache:
        hit = _CACHE.get(ticker)
        if hit and now - hit[0] < _CACHE_TTL:
            out = dict(hit[1])
            # The tape half is cheap and moves intraday; recompute it even
            # on a cache hit so a cached report is never stale on price.
            if tech:
                out = _rescore_short(out, tech)
            return out

    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        info = tk.info or {}
    except Exception as exc:
        log.warning("fundamentals: info fetch failed for %s: %s", ticker, exc)
        return {"ticker": ticker, "error": f"no data for {ticker}"}
    if not info or not (info.get("longName") or info.get("shortName")):
        return {"ticker": ticker, "error": f"no company profile for {ticker}"}
    info.setdefault("symbol", ticker)

    def _get(name):
        try:
            return getattr(tk, name)
        except Exception as exc:
            log.info("fundamentals: %s unavailable for %s: %s", name, ticker, exc)
            return None

    inc, qinc = _get("income_stmt"), _get("quarterly_income_stmt")
    bs = _get("balance_sheet")
    cf, qcf = _get("cashflow"), _get("quarterly_cashflow")

    company = _company(info)
    long_card, short_card = _Card(), _Card()

    revenue = _revenue_block(inc, qinc, long_card)
    rev_series = revenue["revenue"]
    opex = _opex_block(inc, long_card, rev_series)
    cash = _cashflow_block(cf, qcf, long_card, rev_series)
    cash["_mktcap"] = company["market_cap"]
    balance = _balance_block(bs, long_card, cash)
    cash.pop("_mktcap", None)

    catalysts = _catalysts(tk, info, qinc)
    _short_term(tech, catalysts, short_card)

    long_avg, long_n = long_card.composite()
    short_avg, short_n = short_card.composite()
    long_label, _ = _verdict(long_avg, LONG_SCALE)
    short_label, _ = _verdict(short_avg, SHORT_SCALE)

    out = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "company": company,
        "revenue": revenue,
        "opex": opex,
        "cashflow": cash,
        "balance": balance,
        "catalysts": catalysts,
        "scorecard": {
            "long_term": {
                "items": long_card.items, "score": long_avg,
                "measured": long_n, "verdict": long_label,
                "drivers": _drivers(long_card.items),
            },
            "short_term": {
                "items": short_card.items, "score": short_avg,
                "measured": short_n, "verdict": short_label,
                "drivers": _drivers(short_card.items),
            },
        },
        "narrative": None,
        "ai": {"enabled": ai_enabled(), "status": "off"},
    }
    if use_cache:
        with _CACHE_LOCK:
            _CACHE[ticker] = (now, out)
            if len(_CACHE) > _CACHE_MAX:
                for k in list(_CACHE.keys())[:_CACHE_MAX // 5]:
                    _CACHE.pop(k, None)
    return out


def _drivers(items):
    """The strongest argument for and against, so the verdict always comes
    with the two lines a reader would otherwise have to hunt for."""
    scored = [i for i in items if i["score"] is not None]
    if not scored:
        return {"for": None, "against": None}
    best = max(scored, key=lambda i: i["score"])
    worst = min(scored, key=lambda i: i["score"])
    return {
        "for": {"label": best["label"], "detail": best["detail"]}
               if best["score"] > 0 else None,
        "against": {"label": worst["label"], "detail": worst["detail"]}
                   if worst["score"] < 0 else None,
    }


def _rescore_short(out, tech):
    """Recompute only the tape half of a cached report."""
    card = _Card()
    _short_term(tech, out.get("catalysts") or {}, card)
    avg, n = card.composite()
    label, _ = _verdict(avg, SHORT_SCALE)
    out = dict(out)
    out["scorecard"] = dict(out["scorecard"])
    out["scorecard"]["short_term"] = {
        "items": card.items, "score": avg, "measured": n,
        "verdict": label, "drivers": _drivers(card.items),
    }
    return out


# --- optional AI narrative -------------------------------------------------

_AI_MODEL = os.environ.get("FUNDAMENTALS_AI_MODEL", "claude-sonnet-5-5").strip()


def ai_enabled() -> bool:
    """On only when a key is present AND the feature is switched on, the
    same two-part gate market_intel.enabled() uses — so a stray key in the
    environment cannot start spending money by itself."""
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()) and \
        str(os.environ.get("FUNDAMENTALS_AI", "")).strip().lower() in (
            "1", "true", "yes", "on")


_SYSTEM = """You are writing a short fundamental brief for one equity, for \
an experienced retail trader who will read the numbers himself.

You are given a fact sheet already computed from the company's filed \
statements, plus a deterministic scorecard. Rules:

- The scorecard is the verdict. Do not overturn it, re-rate the company, or \
  offer a different conclusion. Explain what is driving it and what would \
  change it.
- Use only the figures in the fact sheet. Do not introduce numbers, events, \
  products, competitors or management commentary from memory — your training \
  data is older than these filings and the reader cannot tell which is which.
- Where the fact sheet says a figure is unavailable, say so plainly rather \
  than working around it.
- Lead with what the business actually does and where the revenue comes \
  from, since that is the one thing the numbers do not say.
- Be concrete about the near-term catalyst if there is a dated one.
- No preamble, no disclaimer, no "as an AI". The app adds its own.

Four short paragraphs, under 320 words total:
1. The business and its revenue base.
2. What the statements show — trend in revenue, costs, cash.
3. Balance sheet and what it permits or constrains.
4. The next dated catalyst and what would most change the long-term read."""


def _fact_sheet(r: dict) -> str:
    """A compact text rendering of the report for the model. Deliberately
    the derived figures rather than the raw frames: it keeps the request
    small, and it means the prose can only reference numbers the scorecard
    also saw."""
    c = r.get("company") or {}
    rev, opx = r.get("revenue") or {}, r.get("opex") or {}
    cf, bal = r.get("cashflow") or {}, r.get("balance") or {}
    cat = r.get("catalysts") or {}
    L = []
    L.append(f"TICKER {r.get('ticker')} — {c.get('name')}")
    L.append(f"Sector {c.get('sector')} / {c.get('industry')}, "
             f"{c.get('country')}, {c.get('employees')} employees")
    if c.get("summary"):
        L.append(f"Business summary (from the filing): {c['summary'][:1500]}")
    L.append(f"Market cap {_money(c.get('market_cap'))}, "
             f"P/E trailing {c.get('trailing_pe')}, forward {c.get('forward_pe')}, "
             f"P/S {c.get('price_to_sales')}")

    def series(name, periods, vals):
        if not vals:
            return
        pairs = ", ".join(f"{p}: {_money(v)}"
                          for p, v in zip(periods or [], vals) if v is not None)
        if pairs:
            L.append(f"{name} (newest first) — {pairs}")

    series("Annual revenue", rev.get("periods"), rev.get("revenue"))
    series("Quarterly revenue", rev.get("quarterly_periods"),
           rev.get("quarterly_revenue"))
    series("Gross profit", rev.get("periods"), rev.get("gross_profit"))
    series("R&D", rev.get("periods"), opx.get("research_development"))
    series("SG&A", rev.get("periods"), opx.get("sga"))
    series("Operating income", rev.get("periods"), opx.get("operating_income"))
    series("Operating cash flow", cf.get("periods"),
           cf.get("operating_cash_flow"))
    series("Free cash flow", cf.get("periods"), cf.get("free_cash_flow"))
    series("Cash", bal.get("periods"), bal.get("cash"))
    series("Total debt", bal.get("periods"), bal.get("total_debt"))

    for half in ("long_term", "short_term"):
        sc = (r.get("scorecard") or {}).get(half) or {}
        L.append(f"\nSCORECARD {half} — verdict: {sc.get('verdict')} "
                 f"(mean {sc.get('score')} over {sc.get('measured')} measures)")
        for i in sc.get("items") or []:
            L.append(f"  [{i.get('score')}] {i.get('label')}: {i.get('detail')}")

    if cat.get("events"):
        L.append("\nDATED EVENTS:")
        for e in cat["events"]:
            L.append(f"  {e.get('date')} — {e.get('label')} {e.get('detail')}")
    sp = [s for s in (cat.get("recent_surprises") or [])
          if s.get("surprise_pct") is not None]
    if sp:
        L.append("Recent EPS surprises: " + ", ".join(
            f"{s['date']} {s['surprise_pct']:+.1f}%" for s in sp))
    if cat.get("news"):
        L.append("Recent headlines: " + "; ".join(
            n.get("title", "") for n in cat["news"][:5]))
    else:
        L.append("Recent headlines: none retrieved (news feed unavailable)")
    return "\n".join(L)


def narrate(report: dict, timeout: float = 45.0) -> dict:
    """Optional written analysis for an already-computed report.

    Returns {"status", "text"}. Never raises and never changes the
    scorecard — on any failure the caller still has the full numeric
    report, which is the whole reason the narrative is a separate step.
    """
    if report.get("error"):
        return {"status": "skipped", "text": None}
    if not ai_enabled():
        return {"status": "off", "text": None}
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    try:
        import requests
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _AI_MODEL,
                "max_tokens": 900,
                "system": _SYSTEM,
                "messages": [{"role": "user", "content": _fact_sheet(report)}],
            },
            timeout=timeout,
        )
    except Exception as exc:
        log.warning("fundamentals: AI request failed for %s: %s",
                    report.get("ticker"), exc)
        return {"status": "error", "text": None, "detail": str(exc)[:160]}
    if resp.status_code != 200:
        log.warning("fundamentals: AI HTTP %s for %s: %s", resp.status_code,
                    report.get("ticker"), resp.text[:200])
        return {"status": "error", "text": None,
                "detail": f"HTTP {resp.status_code}"}
    try:
        blocks = resp.json().get("content") or []
        text = "\n".join(b.get("text", "") for b in blocks
                         if b.get("type") == "text").strip()
    except Exception as exc:
        return {"status": "error", "text": None, "detail": str(exc)[:160]}
    return {"status": "ok" if text else "empty", "text": text or None,
            "model": _AI_MODEL}
