"""Shared Telegram message-formatting primitives.

Every Telegram message in the app goes out via alerts.send_telegram with
parse_mode="HTML", so every helper here emits HTML — never Markdown.
(Two of the older digests were written in Markdown and rendered with
literal '*' / '_' characters under the HTML parser; routing them through
these helpers fixes that.)

Centralizing the header / row / severity vocabulary keeps the six
different message types visually consistent:
  - momentum "LIVE ALERT"        (scanner_momentum)
  - screener-rule alert          (alerts)
  - setup-rule alert             (alerts)
  - options nightly digest       (options_scanner)
  - picker nightly watchlist     (picker_cron)
  - intraday breakout            (picker_intraday)

Visual language (matches the user's requested layout):
    🚨 LIVE ALERT — TICKER
    🏢 Company Name
    ⏰ 02:01 PM ET

    💰 Price: $4.52
    🔥 RVOL(20): 🔥🔥 128.78x  ← EXTREME
    👤 Insider buy: N/A
"""

from __future__ import annotations

import html as _html
from datetime import datetime
from typing import Iterable

# Sentinel shown for any value we don't have. Single source of truth so
# every message uses the same "missing data" token.
NA = "N/A"


def esc(s) -> str:
    """HTML-escape an arbitrary value for safe inclusion in a message."""
    return _html.escape(str(s)) if s is not None else ""


def b(s) -> str:
    """Bold an (escaped) value."""
    return f"<b>{esc(s)}</b>"


def i(s) -> str:
    """Italicize an (escaped) value."""
    return f"<i>{esc(s)}</i>"


# --- header ---------------------------------------------------------------

def header(category: str, ticker: str, *, name: str | None = None,
           when: str | None = None, emoji: str = "🚨") -> list[str]:
    """Top block: bold 'CATEGORY — TICKER', optional company line,
    optional timestamp line, then a blank separator. Returns a list of
    lines so the caller can extend it."""
    lines = [f"{emoji} <b>{esc(category)} — {esc(ticker)}</b>"]
    if name:
        lines.append(f"🏢 {esc(name)}")
    if when:
        lines.append(f"⏰ {esc(when)}")
    lines.append("")
    return lines


# --- rows -----------------------------------------------------------------

def row(emoji: str, label: str, value, *, callout: str | None = None) -> str:
    """A single 'emoji Label: value' line. `value` may already contain
    HTML (e.g. a bold number) — it is NOT re-escaped, so callers must
    escape any user-derived text they fold into it. `callout` renders as
    a bold '← CALLOUT' suffix (the severity tag in the user's example)."""
    line = f"{emoji} {esc(label)}: {value}"
    if callout:
        line += f"  ← <b>{esc(callout)}</b>"
    return line


# --- severity classifiers + tagged rows -----------------------------------
# Thresholds mirror scanner_momentum.compute_verdict so the inline tags
# agree with the verdict score.

_FIRE = {"ELEVATED": "", "HIGH": "🔥 ", "EXTREME": "🔥🔥 "}


def rvol_level(x: float | None) -> str | None:
    if x is None:
        return None
    if x >= 10:  return "EXTREME"
    if x >= 5:   return "HIGH"
    if x >= 2.5: return "ELEVATED"
    return None


def pct_change_level(x: float | None) -> str | None:
    if x is None:
        return None
    if x >= 15: return "EXTREME"
    if x >= 8:  return "HIGH"
    if x >= 5:  return "ELEVATED"
    return None


def vol_float_level(x: float | None) -> str | None:
    """`x` is volume as a percent of float (e.g. 6.41 == 6.41%)."""
    if x is None:
        return None
    if x >= 3: return "EXTREME"
    if x >= 1: return "HIGH"
    if x >= 0.5: return "ELEVATED"
    return None


def severity_row(emoji: str, label: str, value_str: str,
                 level: str | None) -> str:
    """A metric row with an escalating fire prefix on the value and a
    '← LEVEL' callout. `level` is one of None / ELEVATED / HIGH / EXTREME.
    ELEVATED gets the callout but no fire (keeps the noise floor low)."""
    fire = _FIRE.get(level or "", "")
    line = f"{emoji} {esc(label)}: {fire}{value_str}"
    if level:
        line += f"  ← <b>{esc(level)}</b>"
    return line


# --- sections -------------------------------------------------------------

def section(title_emoji: str, title: str, bullets: Iterable[str]) -> list[str]:
    """A titled bullet section (e.g. catalysts). bullets are already-
    formatted HTML strings. Returns [] when empty so the caller can skip
    it without adding a stray blank line."""
    bullets = [x for x in bullets if x]
    if not bullets:
        return []
    out = [f"{title_emoji} <b>{esc(title)}:</b>"]
    out.extend(f"• {x}" for x in bullets)
    return out


def disclaimer(text: str) -> str:
    return i(text)


# --- value formatters -----------------------------------------------------

def money(x: float | None, digits: int = 2) -> str:
    """A dollar price like $4.52. NA when missing."""
    if x is None:
        return NA
    return f"${x:,.{digits}f}"


def big_money(n: float | None) -> str:
    """Abbreviated large dollar amount: $54.0M, $3.40B, $1.2T. NA when missing."""
    if n is None:
        return NA
    a = abs(n)
    if a >= 1e12: return f"${n / 1e12:.2f}T"
    if a >= 1e9:  return f"${n / 1e9:.2f}B"
    if a >= 1e6:  return f"${n / 1e6:.1f}M"
    if a >= 1e3:  return f"${n / 1e3:.0f}k"
    return f"${n:,.0f}"


def signed_pct(x: float | None, digits: int = 2) -> str:
    """A signed percent like +48.20%. NA when missing."""
    if x is None:
        return NA
    return f"{x:+.{digits}f}%"


def multiple(x: float | None, digits: int = 2) -> str:
    """A multiple like 128.78x. NA when missing."""
    if x is None:
        return NA
    return f"{x:.{digits}f}x"


def _fmt_pe(x: float | None) -> str:
    if x is None or x != x:   # None or NaN
        return NA
    if x < 0:
        return "neg"
    return f"{x:.1f}"


# --- enrichment row builders (consume the structured dicts) ---------------

def insider_row(insider: dict | None) -> str:
    """One row summarizing the latest insider transaction. Always shown;
    N/A when there's no Form-4 data."""
    if not insider:
        return row("👤", "Insider buy", NA)
    code = insider.get("code_label") or insider.get("code") or "transaction"
    shares = insider.get("shares") or 0
    val = insider.get("value") or 0
    when = insider.get("transaction_date") or insider.get("filing_date") or "?"
    who_parts = [p for p in (insider.get("owner"), insider.get("title")) if p]
    who = " — ".join(who_parts) if who_parts else "insider"
    val_str = big_money(val) if val else NA
    value = (f"{b(code)} {int(shares):,} sh ({val_str}) "
             f"by {esc(who)} on {esc(when)}")
    return row("👤", "Insider", value)


def fundamentals_rows(fund: dict | None) -> list[str]:
    """MCap row (always shown, N/A when missing, P/E appended inline) plus
    an optional secondary detail row (revenue / margins / leverage)."""
    f = fund or {}
    mcap = f.get("market_cap")
    pe = f.get("trailing_pe")
    fpe = f.get("forward_pe")
    mcap_val = big_money(mcap) if mcap is not None else NA
    if pe is not None or fpe is not None:
        pe_str = f"P/E {_fmt_pe(pe)}"
        if fpe is not None:
            pe_str += f" (fwd {_fmt_pe(fpe)})"
        mcap_val = f"{mcap_val}  ·  {pe_str}"
    out = [row("🏢", "MCap", mcap_val)]
    detail: list[str] = []
    if f.get("revenue") is not None:
        rev = big_money(f["revenue"])
        if f.get("revenue_growth_yoy") is not None:
            g = f["revenue_growth_yoy"]
            rev += f" ({'+' if g >= 0 else ''}{g * 100:.0f}% YoY)"
        detail.append(f"Rev {rev}")
    if f.get("gross_margin") is not None:
        detail.append(f"GM {f['gross_margin'] * 100:.0f}%")
    if f.get("operating_margin") is not None:
        detail.append(f"OpM {f['operating_margin'] * 100:.0f}%")
    if f.get("debt_to_equity") is not None:
        # yfinance returns 45.2 to mean 0.452 (45.2%); show as 0.45×.
        detail.append(f"D/E {f['debt_to_equity'] / 100:.2f}")
    if detail:
        out.append(row("📊", "Fundamentals", " · ".join(detail)))
    return out


def time_et(dt: datetime | None) -> str:
    """'02:01 PM ET' from a datetime. NA when missing. Strips a leading
    zero on the hour for readability."""
    if dt is None:
        return NA
    s = dt.strftime("%I:%M %p")
    if s.startswith("0"):
        s = s[1:]
    return f"{s} ET"
