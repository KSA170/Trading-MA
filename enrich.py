"""Per-ticker enrichment for momentum-scanner alerts.

Two entry points, both designed for the alert-fire path (not the scan
path) — they make 1-3 external HTTP calls each, take 1-5 seconds, and
return None on any failure so a flaky upstream never blocks an alert.

  last_insider_transaction(ticker)
      Hits SEC EDGAR (submissions JSON + the latest Form 4 XML),
      returns the most recent insider transaction: who, role, code,
      shares, price, dollar value, transaction date, filing date.

  fundamentals(ticker)
      Pulls yfinance.Ticker.info and extracts market cap, P/E (TTM +
      forward), revenue + YoY growth, gross/operating margin, D/E.

Both are US-only — TSX/TSXV tickers ('.TO', '.V') are already
filtered upstream in scanner_momentum._is_us_symbol so they never
reach these functions.
"""
from __future__ import annotations

import logging
import time
from typing import Any
from xml.etree import ElementTree as ET

import requests

log = logging.getLogger("enrich")

# SEC requires a descriptive User-Agent identifying the requester. The
# operator email is the simplest stable identifier.
_SEC_UA = "Trading-MA Momentum Scanner fateh.adam20@gmail.com"
_SEC_HEADERS = {"User-Agent": _SEC_UA, "Accept-Encoding": "gzip, deflate"}

# data.sec.gov asks for ≤10 req/sec; 1 req/sec is conservative and only
# matters if multiple tickers fire in the same scan run.
_MIN_INTERVAL_SEC = 0.12
_last_request_ts: float = 0.0

# Process-wide cache of the ticker→CIK map (~1MB, ~10k rows). Each
# scanner invocation is a fresh process, so this is re-fetched ~every
# 5 min — well under any rate limit.
_cik_map: dict[str, int] | None = None


def _throttle() -> None:
    global _last_request_ts
    elapsed = time.time() - _last_request_ts
    if elapsed < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - elapsed)
    _last_request_ts = time.time()


def _sec_get(url: str, timeout: float = 10.0) -> requests.Response:
    _throttle()
    return requests.get(url, headers=_SEC_HEADERS, timeout=timeout)


def _load_cik_map() -> dict[str, int]:
    global _cik_map
    if _cik_map is not None:
        return _cik_map
    try:
        r = _sec_get("https://www.sec.gov/files/company_tickers.json")
        r.raise_for_status()
        data = r.json()
        # Format: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        _cik_map = {row["ticker"].upper(): int(row["cik_str"])
                    for row in data.values()}
        log.info("loaded SEC ticker→CIK map (%d entries)", len(_cik_map))
    except Exception as exc:
        log.warning("could not load SEC ticker→CIK map: %s", exc)
        _cik_map = {}
    return _cik_map


# Transaction-code → human label. See SEC Form 4 Table I/II coding.
_CODE_LABELS = {
    "P": "BUY",                # Open-market or private purchase
    "S": "SELL",               # Open-market or private sale
    "A": "Award",              # Grant / award (RSU, etc.)
    "M": "Option exercise",
    "F": "Tax withhold",
    "D": "Sale to issuer",
    "G": "Gift",
    "X": "ITM exercise",
    "V": "Voluntary",
    "J": "Other",
    "K": "Equity swap",
}


def _label_for_code(code: str | None) -> str:
    if not code:
        return "transaction"
    return _CODE_LABELS.get(code.upper(), code.upper())


def _ns_strip(tag: str) -> str:
    """ElementTree returns tags as '{ns}name'; strip the namespace."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find_text(elem: ET.Element | None, *path: str) -> str | None:
    """Walk child tags by local name, return first matching .text."""
    if elem is None:
        return None
    cur: ET.Element | None = elem
    for name in path:
        match: ET.Element | None = None
        for child in list(cur):  # type: ignore[arg-type]
            if _ns_strip(child.tag) == name:
                match = child
                break
        if match is None:
            return None
        cur = match
    return (cur.text or "").strip() if cur is not None else None


def _parse_form4(xml_bytes: bytes) -> dict | None:
    """Extract the most material non-derivative transaction from a
    Form 4 XML payload. 'Most material' = largest absolute dollar
    value among all transactions in this filing."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        log.warning("Form 4 XML parse failed: %s", exc)
        return None

    # Reporting owner (the insider). Pick the first one.
    owner_name: str | None = None
    owner_title: str | None = None
    for child in root.iter():
        if _ns_strip(child.tag) == "reportingOwner":
            owner_name = _find_text(child, "reportingOwnerId", "rptOwnerName")
            rel = next(
                (c for c in list(child) if _ns_strip(c.tag) == "reportingOwnerRelationship"),
                None,
            )
            if rel is not None:
                title = _find_text(rel, "officerTitle")
                flags = []
                if (_find_text(rel, "isDirector") or "").lower() in ("1", "true"):
                    flags.append("Director")
                if (_find_text(rel, "isOfficer") or "").lower() in ("1", "true"):
                    flags.append(title or "Officer")
                if (_find_text(rel, "isTenPercentOwner") or "").lower() in ("1", "true"):
                    flags.append("10% owner")
                owner_title = ", ".join([f for f in flags if f]) or title
            break

    # Collect every non-derivative transaction; pick the largest by value.
    best: dict | None = None
    for txn in root.iter():
        if _ns_strip(txn.tag) != "nonDerivativeTransaction":
            continue
        txn_date = _find_text(txn, "transactionDate", "value")
        code = _find_text(txn, "transactionCoding", "transactionCode")
        shares_raw = _find_text(txn, "transactionAmounts", "transactionShares", "value")
        price_raw = _find_text(txn, "transactionAmounts", "transactionPricePerShare", "value")
        try:
            shares = float(shares_raw) if shares_raw else None
        except ValueError:
            shares = None
        try:
            price = float(price_raw) if price_raw else None
        except ValueError:
            price = None
        if shares is None:
            continue
        value = (shares * price) if price else 0.0
        cand = {
            "transaction_date": txn_date,
            "code": code,
            "shares": shares,
            "price": price,
            "value": value,
        }
        if best is None or abs(value) > abs(best["value"]):
            best = cand

    if best is None:
        return None
    best["owner"] = owner_name
    best["title"] = owner_title
    return best


def last_insider_transaction(ticker: str) -> dict | None:
    """Return the most recent insider transaction for `ticker` from
    SEC EDGAR Form 4 filings, or None if the lookup fails / the issuer
    has no recent Form 4s on file.

    Result schema:
        {
            "filing_date":      "YYYY-MM-DD",
            "transaction_date": "YYYY-MM-DD" | None,
            "code":             "P" | "S" | "A" | ... | None,
            "code_label":       "BUY" | "SELL" | ...,
            "owner":            "John Doe" | None,
            "title":            "CEO, Director" | None,
            "shares":           float,
            "price":            float | None,
            "value":            float,  # shares * price, signed by code
        }
    """
    try:
        cik_map = _load_cik_map()
        cik = cik_map.get(ticker.upper().replace(".", "-"))
        if cik is None:
            return None

        # List recent filings to find the most recent Form 4 / 4/A.
        sub_url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        r = _sec_get(sub_url)
        r.raise_for_status()
        sub = r.json()
        recent = sub.get("filings", {}).get("recent", {}) or {}
        forms = recent.get("form", []) or []
        accessions = recent.get("accessionNumber", []) or []
        filings_dates = recent.get("filingDate", []) or []
        primary_docs = recent.get("primaryDocument", []) or []

        idx = next(
            (i for i, f in enumerate(forms) if f in ("4", "4/A")),
            -1,
        )
        if idx < 0:
            return None
        accession = accessions[idx]
        filing_date = filings_dates[idx]
        primary_doc = primary_docs[idx]
        accession_nodashes = accession.replace("-", "")

        xml_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/"
            f"{accession_nodashes}/{primary_doc}"
        )
        r2 = _sec_get(xml_url)
        r2.raise_for_status()
        parsed = _parse_form4(r2.content)
        if parsed is None:
            return None
        parsed["filing_date"] = filing_date
        parsed["code_label"] = _label_for_code(parsed.get("code"))
        return parsed
    except Exception as exc:
        log.warning("insider lookup failed for %s: %s", ticker, exc)
        return None


def fundamentals(ticker: str) -> dict:
    """Return a dict of basic fundamentals via yfinance.Ticker.info.
    Always returns a dict (possibly empty/all-None on failure) so the
    formatter can render whichever fields are available without
    branching on None at every read."""
    out: dict[str, Any] = {
        "name": None,
        "market_cap": None,
        "trailing_pe": None,
        "forward_pe": None,
        "revenue": None,
        "revenue_growth_yoy": None,
        "gross_margin": None,
        "operating_margin": None,
        "debt_to_equity": None,
    }
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        # yfinance exposes the issuer's name under one of three keys
        # depending on the data source; prefer longName, then shortName.
        out["name"] = (info.get("longName") or info.get("shortName")
                       or info.get("displayName"))
        out["market_cap"]        = info.get("marketCap")
        out["trailing_pe"]       = info.get("trailingPE")
        out["forward_pe"]        = info.get("forwardPE")
        out["revenue"]           = info.get("totalRevenue")
        out["revenue_growth_yoy"] = info.get("revenueGrowth")
        out["gross_margin"]      = info.get("grossMargins")
        out["operating_margin"]  = info.get("operatingMargins")
        # yfinance returns debtToEquity as a percentage-like number
        # (e.g. 45.2 for 0.452); pass through as-is, formatter divides.
        out["debt_to_equity"]    = info.get("debtToEquity")
    except Exception as exc:
        log.warning("fundamentals lookup failed for %s: %s", ticker, exc)
    return out


# --- catalyst news --------------------------------------------------------

def _yf_news_item_normalise(item: dict) -> dict | None:
    """yfinance's news payload changed shape around 0.2.50 — older
    entries are flat ({title, publisher, providerPublishTime, summary,
    link}), newer ones nest in a `content` dict. Normalise to a flat
    dict the caller can use without knowing which shape it got."""
    if not isinstance(item, dict):
        return None
    content = item.get("content") if isinstance(item.get("content"), dict) else None
    title     = (content or item).get("title")
    summary   = (content or item).get("summary") or (content or item).get("description")
    publisher = None
    if content:
        provider = content.get("provider")
        if isinstance(provider, dict):
            publisher = provider.get("displayName")
    publisher = publisher or item.get("publisher")
    raw_ts = ((content or {}).get("pubDate")
              or item.get("providerPublishTime")
              or item.get("pubDate"))
    pub_ts: float | None = None
    if isinstance(raw_ts, (int, float)):
        pub_ts = float(raw_ts)
    elif isinstance(raw_ts, str) and raw_ts:
        try:
            from datetime import datetime
            pub_ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            pub_ts = None
    link = None
    if content:
        canonical = content.get("canonicalUrl")
        if isinstance(canonical, dict):
            link = canonical.get("url")
    link = link or item.get("link")
    if not title:
        return None
    return {
        "title":     title,
        "summary":   summary,
        "publisher": publisher,
        "pub_ts":    pub_ts,
        "link":      link,
    }


def recent_news(ticker: str, limit: int = 4,
                max_age_days: int = 7) -> list[dict]:
    """Latest news items for `ticker` from Yahoo Finance, filtered to
    the last `max_age_days` and capped at `limit` entries. Used as the
    "catalyst" block on momentum-scanner Telegram alerts. Returns []
    on any upstream failure so the alert still goes out without the
    catalyst section."""
    try:
        import yfinance as yf
        items = yf.Ticker(ticker).news or []
    except Exception as exc:
        log.warning("recent_news lookup failed for %s: %s", ticker, exc)
        return []
    if not items:
        return []
    import time as _time
    cutoff = _time.time() - max_age_days * 86400
    normalised: list[dict] = []
    for raw in items:
        n = _yf_news_item_normalise(raw)
        if n is None:
            continue
        if n["pub_ts"] is not None and n["pub_ts"] < cutoff:
            continue
        normalised.append(n)
    # Newest first — pubDate may be missing on some items so they keep
    # their feed order at the bottom.
    normalised.sort(
        key=lambda x: x["pub_ts"] if x["pub_ts"] is not None else 0,
        reverse=True,
    )
    return normalised[:limit]


def _time_ago(pub_ts: float | None) -> str:
    if pub_ts is None:
        return ""
    import time as _time
    delta = _time.time() - pub_ts
    if delta < 0:
        return ""
    if delta < 3600:
        return f"{int(delta // 60)}m"
    if delta < 86400:
        return f"{int(delta // 3600)}h"
    return f"{int(delta // 86400)}d"


def format_news_block(news: list[dict] | None,
                      summary_chars: int = 180) -> str | None:
    """HTML block of catalyst lines for the Telegram alert. Returns
    None when there's nothing to show so the caller can omit the
    section cleanly."""
    if not news:
        return None
    import html as _html
    lines = ["📰 <b>Catalysts:</b>"]
    for n in news:
        title = _html.escape(n.get("title") or "")
        meta_parts: list[str] = []
        if n.get("publisher"):
            meta_parts.append(_html.escape(n["publisher"]))
        ago = _time_ago(n.get("pub_ts"))
        if ago:
            meta_parts.append(ago)
        meta = f" <i>({' · '.join(meta_parts)})</i>" if meta_parts else ""
        lines.append(f"• <b>{title}</b>{meta}")
        summary = (n.get("summary") or "").strip()
        if summary:
            summary = " ".join(summary.split())
            if len(summary) > summary_chars:
                summary = summary[:summary_chars - 1].rstrip() + "…"
            lines.append(f"  {_html.escape(summary)}")
    return "\n".join(lines)


# --- formatting helpers used by the Telegram message ----------------

def _fmt_big(n: float | None) -> str:
    if n is None:
        return "—"
    a = abs(n)
    if a >= 1e12: return f"${n / 1e12:.2f}T"
    if a >= 1e9:  return f"${n / 1e9:.2f}B"
    if a >= 1e6:  return f"${n / 1e6:.1f}M"
    if a >= 1e3:  return f"${n / 1e3:.0f}k"
    return f"${n:,.0f}"


def _fmt_pct(x: float | None, digits: int = 1) -> str:
    if x is None:
        return "—"
    return f"{x * 100:.{digits}f}%"


def _fmt_pe(x: float | None) -> str:
    if x is None or x != x:   # None or NaN
        return "—"
    if x < 0:
        return "neg"
    return f"{x:.1f}"


def format_insider_line(t: dict | None) -> str | None:
    """One-line HTML summary for Telegram. Returns None if no data."""
    if not t:
        return None
    code = t.get("code_label") or "transaction"
    shares = t.get("shares") or 0
    val = t.get("value") or 0
    date = t.get("transaction_date") or t.get("filing_date") or "?"
    who_parts = [p for p in (t.get("owner"), t.get("title")) if p]
    who = " — ".join(who_parts) if who_parts else "insider"
    val_str = _fmt_big(val) if val else "—"
    return (
        f"📋 Insider: <b>{code}</b> {int(shares):,} sh "
        f"({val_str}) by {who} on {date}"
    )


def format_fundamentals_line(f: dict | None) -> str | None:
    """One-line HTML summary for Telegram. Returns None if every
    field is missing."""
    if not f or not any(v is not None for v in f.values()):
        return None
    parts: list[str] = []
    if f.get("market_cap") is not None:
        parts.append(f"MCap {_fmt_big(f['market_cap'])}")
    if f.get("trailing_pe") is not None or f.get("forward_pe") is not None:
        parts.append(
            f"P/E {_fmt_pe(f.get('trailing_pe'))} "
            f"(fwd {_fmt_pe(f.get('forward_pe'))})"
        )
    if f.get("revenue") is not None:
        rev = _fmt_big(f["revenue"])
        if f.get("revenue_growth_yoy") is not None:
            sign = "+" if f["revenue_growth_yoy"] >= 0 else ""
            rev += f" ({sign}{_fmt_pct(f['revenue_growth_yoy'], 0)} YoY)"
        parts.append(f"Rev {rev}")
    if f.get("gross_margin") is not None:
        parts.append(f"GM {_fmt_pct(f['gross_margin'], 0)}")
    if f.get("operating_margin") is not None:
        parts.append(f"OpM {_fmt_pct(f['operating_margin'], 0)}")
    if f.get("debt_to_equity") is not None:
        # yfinance returns 45.2 to mean 0.452 (i.e. 45.2%); show as 0.45×
        parts.append(f"D/E {f['debt_to_equity'] / 100:.2f}")
    if not parts:
        return None
    return "📊 " + " · ".join(parts)
