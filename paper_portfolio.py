"""Paper portfolio — a simulated $500k book.

Positions are booked from the stock screener (buy at the day's close) or
the options screener (buy at the recommended contract's mid). Each buy is
its own lot, tagged with the filter setup it came from (a label + the full
filter-state JSON) so we can later ask "which setups made money?".

Accounting model:
  - Cash-only (no margin): a buy that costs more than available cash is
    rejected.
  - Lot-based: every buy is a separate row in paper_positions. Sells are
    whole-lot for now (partial sells are a later addition).
  - Stocks: multiplier 1, price is per share. Options: multiplier 100,
    price is the per-share contract mid, so a contract costs mid * 100.
  - Realized P&L is booked to cash on sell/expire; unrealized P&L is
    derived from each open lot's last mark (filled by the nightly
    mark-to-market job — phase 2).

This module owns the schema + accounting. Mark-to-market pricing and the
equity-curve cron live alongside it but are added in phase 2; the price-
fetch helpers they need are defined here so the sell path can also use
them.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

import snapshots

log = logging.getLogger("paper_portfolio")

STARTING_CASH = 500_000.0
STOCK_MULT = 1
OPTION_MULT = 100

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_portfolio (
    id            INT PRIMARY KEY DEFAULT 1,
    starting_cash REAL NOT NULL DEFAULT 500000,
    cash          REAL NOT NULL DEFAULT 500000,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_positions (
    id            SERIAL PRIMARY KEY,
    asset_type    TEXT NOT NULL,            -- 'stock' | 'option'
    ticker        TEXT NOT NULL,
    option_type   TEXT,                     -- 'call' | 'put' (options only)
    strike        REAL,
    expiration    DATE,
    multiplier    INT  NOT NULL DEFAULT 1,
    qty           REAL NOT NULL,            -- shares or contracts
    entry_date    DATE NOT NULL,
    entry_price   REAL NOT NULL,            -- per share / per-contract-share
    cost_basis    REAL NOT NULL,            -- qty * entry_price * multiplier
    source_label  TEXT,                     -- preset name / 'manual' / 'options-scan'
    source_filter JSONB,                    -- full filter-state snapshot
    status        TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'closed'
    last_price    REAL,                     -- latest mark (nightly)
    last_priced_at DATE,
    exit_date     DATE,
    exit_price    REAL,
    realized_pnl  REAL,
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS paper_positions_status_idx ON paper_positions (status);
CREATE INDEX IF NOT EXISTS paper_positions_source_idx ON paper_positions (source_label);

CREATE TABLE IF NOT EXISTS paper_transactions (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ DEFAULT now(),
    action      TEXT NOT NULL,             -- 'buy' | 'sell' | 'expire' | 'reset'
    position_id INT,
    asset_type  TEXT,
    ticker      TEXT,
    qty         REAL,
    price       REAL,
    amount      REAL,                      -- cash delta: negative buy, positive sell
    note        TEXT
);
CREATE INDEX IF NOT EXISTS paper_transactions_ts_idx ON paper_transactions (ts DESC);

CREATE TABLE IF NOT EXISTS paper_equity (
    as_of           DATE PRIMARY KEY,
    cash            REAL,
    positions_value REAL,
    total_equity    REAL,
    spy_close       REAL
);
"""


def init_tables() -> None:
    if not snapshots.enabled():
        return
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(_SCHEMA)
            # Ensure the singleton portfolio row exists.
            cur.execute(
                "INSERT INTO paper_portfolio (id, starting_cash, cash) "
                "VALUES (1, %s, %s) ON CONFLICT (id) DO NOTHING",
                (STARTING_CASH, STARTING_CASH),
            )
    except Exception as exc:
        log.warning("paper_portfolio.init_tables failed: %s", exc)


# --- pure accounting helpers (no DB — unit-testable) ----------------------

def lot_cost(qty: float, price: float, multiplier: int) -> float:
    """Cash outlay for a lot."""
    return float(qty) * float(price) * int(multiplier)


def realized_pnl(qty: float, entry_price: float, exit_price: float,
                 multiplier: int) -> float:
    """Realized P&L for closing a whole lot at exit_price."""
    return float(qty) * (float(exit_price) - float(entry_price)) * int(multiplier)


def market_value(qty: float, price: float, multiplier: int) -> float:
    """Current market value of an open lot at `price`."""
    return float(qty) * float(price) * int(multiplier)


def unrealized_pnl(qty: float, entry_price: float, mark: float,
                   multiplier: int) -> float:
    return float(qty) * (float(mark) - float(entry_price)) * int(multiplier)


def option_intrinsic(option_type: str, underlying: float, strike: float) -> float:
    """Per-share intrinsic value of an option at expiration."""
    if option_type == "call":
        return max(0.0, float(underlying) - float(strike))
    return max(0.0, float(strike) - float(underlying))


def _normalize_option_type(v) -> str:
    v = str(v or "").strip().lower()
    if v in ("call", "c", "long_call"):
        return "call"
    if v in ("put", "p", "long_put"):
        return "put"
    return "call"


# --- portfolio state ------------------------------------------------------

def get_portfolio() -> dict:
    """Return {starting_cash, cash, created_at}. Initializes on first use."""
    out = {"starting_cash": STARTING_CASH, "cash": STARTING_CASH, "created_at": None}
    if not snapshots.enabled():
        return out
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT starting_cash, cash, created_at FROM paper_portfolio WHERE id = 1"
            )
            row = cur.fetchone()
    except Exception as exc:
        log.warning("paper_portfolio.get_portfolio failed: %s", exc)
        return out
    if row:
        out["starting_cash"] = float(row[0]) if row[0] is not None else STARTING_CASH
        out["cash"] = float(row[1]) if row[1] is not None else STARTING_CASH
        out["created_at"] = row[2].isoformat() if row[2] else None
    return out


def _cash(cur) -> float:
    cur.execute("SELECT cash FROM paper_portfolio WHERE id = 1")
    row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else STARTING_CASH


# --- buys -----------------------------------------------------------------

def _buy(asset_type: str, ticker: str, qty: float, entry_price: float,
         multiplier: int, entry_date: str, source_label: str | None,
         source_filter, *, option_type=None, strike=None, expiration=None) -> dict:
    """Book a lot if there's enough cash. Returns {ok, ...} / {ok:False,error}."""
    if not snapshots.enabled():
        return {"ok": False, "error": "no_db"}
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return {"ok": False, "error": "ticker_required"}
    try:
        qty = float(qty)
        entry_price = float(entry_price)
    except (TypeError, ValueError):
        return {"ok": False, "error": "qty_price_numeric"}
    if qty <= 0 or entry_price <= 0:
        return {"ok": False, "error": "qty_price_positive"}
    cost = lot_cost(qty, entry_price, multiplier)
    entry_date = entry_date or date.today().isoformat()
    sf = json.dumps(source_filter) if source_filter is not None else None
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cash = _cash(cur)
            if cost > cash + 1e-6:
                return {"ok": False, "error": "insufficient_cash",
                        "cost": cost, "cash": cash}
            cur.execute(
                "INSERT INTO paper_positions ("
                "  asset_type, ticker, option_type, strike, expiration, multiplier,"
                "  qty, entry_date, entry_price, cost_basis, source_label,"
                "  source_filter, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open') RETURNING id",
                (asset_type, ticker, option_type, strike, expiration, multiplier,
                 qty, entry_date, entry_price, cost, source_label, sf),
            )
            pos_id = cur.fetchone()[0]
            cur.execute(
                "UPDATE paper_portfolio SET cash = cash - %s WHERE id = 1", (cost,)
            )
            cur.execute(
                "INSERT INTO paper_transactions "
                "(action, position_id, asset_type, ticker, qty, price, amount, note) "
                "VALUES ('buy', %s, %s, %s, %s, %s, %s, %s)",
                (pos_id, asset_type, ticker, qty, entry_price, -cost,
                 source_label or ""),
            )
        return {"ok": True, "position_id": pos_id, "cost": cost}
    except Exception as exc:
        log.warning("paper_portfolio._buy failed: %s", exc)
        return {"ok": False, "error": "db_error"}


def buy_stock(ticker: str, qty: float, entry_price: float,
              entry_date: str | None = None, source_label: str | None = None,
              source_filter=None) -> dict:
    """Book `qty` shares at `entry_price` (the day's close shown in the
    screener)."""
    return _buy("stock", ticker, qty, entry_price, STOCK_MULT,
                entry_date, source_label, source_filter)


def buy_option(ticker: str, option_type: str, strike: float, expiration: str,
               contracts: float, entry_mid: float,
               entry_date: str | None = None, source_label: str | None = None,
               source_filter=None) -> dict:
    """Book `contracts` of an option at the recommended per-share mid
    (a contract costs mid * 100)."""
    return _buy("option", ticker, contracts, entry_mid, OPTION_MULT,
                entry_date, source_label, source_filter,
                option_type=_normalize_option_type(option_type),
                strike=strike, expiration=expiration)


# --- sells ----------------------------------------------------------------

def sell_position(position_id: int, exit_price: float | None = None,
                  exit_date: str | None = None, action: str = "sell") -> dict:
    """Close a whole lot at `exit_price` (latest/last-available price). If
    `exit_price` is None, use the lot's last mark, else fetch it live."""
    if not snapshots.enabled():
        return {"ok": False, "error": "no_db"}
    exit_date = exit_date or date.today().isoformat()
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT asset_type, ticker, option_type, strike, expiration, "
                "multiplier, qty, entry_price, status, last_price "
                "FROM paper_positions WHERE id = %s", (position_id,)
            )
            row = cur.fetchone()
            if not row:
                return {"ok": False, "error": "not_found"}
            (asset_type, ticker, option_type, strike, expiration, mult,
             qty, entry_price, status, last_price) = row
            if status != "open":
                return {"ok": False, "error": "already_closed"}
            price = exit_price
            if price is None:
                price = last_price
            if price is None:
                price = latest_mark(asset_type, ticker, option_type, strike, expiration)
            if price is None:
                return {"ok": False, "error": "no_price"}
            price = float(price)
            proceeds = market_value(qty, price, mult)
            pnl = realized_pnl(qty, float(entry_price), price, mult)
            cur.execute(
                "UPDATE paper_positions SET status='closed', exit_date=%s, "
                "exit_price=%s, realized_pnl=%s, last_price=%s, last_priced_at=%s "
                "WHERE id = %s",
                (exit_date, price, pnl, price, exit_date, position_id),
            )
            cur.execute(
                "UPDATE paper_portfolio SET cash = cash + %s WHERE id = 1", (proceeds,)
            )
            cur.execute(
                "INSERT INTO paper_transactions "
                "(action, position_id, asset_type, ticker, qty, price, amount, note) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (action, position_id, asset_type, ticker, qty, price, proceeds,
                 f"pnl={pnl:.2f}"),
            )
        return {"ok": True, "proceeds": proceeds, "realized_pnl": pnl, "price": price}
    except Exception as exc:
        log.warning("paper_portfolio.sell_position failed: %s", exc)
        return {"ok": False, "error": "db_error"}


# --- reads ----------------------------------------------------------------

def list_positions(status: str | None = "open") -> list[dict]:
    if not snapshots.enabled():
        return []
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            if status in ("open", "closed"):
                cur.execute(
                    "SELECT id, asset_type, ticker, option_type, strike, expiration, "
                    "multiplier, qty, entry_date, entry_price, cost_basis, "
                    "source_label, status, last_price, last_priced_at, exit_date, "
                    "exit_price, realized_pnl "
                    "FROM paper_positions WHERE status = %s "
                    "ORDER BY entry_date DESC, id DESC", (status,)
                )
            else:
                cur.execute(
                    "SELECT id, asset_type, ticker, option_type, strike, expiration, "
                    "multiplier, qty, entry_date, entry_price, cost_basis, "
                    "source_label, status, last_price, last_priced_at, exit_date, "
                    "exit_price, realized_pnl "
                    "FROM paper_positions ORDER BY entry_date DESC, id DESC"
                )
            rows = cur.fetchall()
    except Exception as exc:
        log.warning("paper_portfolio.list_positions failed: %s", exc)
        return []
    out = []
    for r in rows:
        (pid, atype, tk, otype, strike, exp, mult, qty, edate, eprice, cost,
         src, st, lastp, lastd, xdate, xprice, rpnl) = r
        mark = lastp if lastp is not None else eprice
        mv = market_value(qty, mark, mult) if mark is not None else None
        upnl = (unrealized_pnl(qty, eprice, mark, mult)
                if (st == "open" and mark is not None) else None)
        out.append({
            "id": pid, "asset_type": atype, "ticker": tk,
            "option_type": otype, "strike": float(strike) if strike is not None else None,
            "expiration": exp.isoformat() if exp else None,
            "multiplier": int(mult), "qty": float(qty),
            "entry_date": edate.isoformat() if edate else None,
            "entry_price": float(eprice), "cost_basis": float(cost),
            "source_label": src, "status": st,
            "last_price": float(lastp) if lastp is not None else None,
            "last_priced_at": lastd.isoformat() if lastd else None,
            "market_value": mv, "unrealized_pnl": upnl,
            "exit_date": xdate.isoformat() if xdate else None,
            "exit_price": float(xprice) if xprice is not None else None,
            "realized_pnl": float(rpnl) if rpnl is not None else None,
        })
    return out


def summary() -> dict:
    """Portfolio headline numbers: cash, positions value, total equity,
    realized + unrealized P&L, total return vs starting cash."""
    pf = get_portfolio()
    cash = pf["cash"]
    start = pf["starting_cash"]
    open_pos = list_positions("open")
    closed_pos = list_positions("closed")
    positions_value = sum(p["market_value"] or 0.0 for p in open_pos)
    unrealized = sum(p["unrealized_pnl"] or 0.0 for p in open_pos)
    realized = sum(p["realized_pnl"] or 0.0 for p in closed_pos)
    total_equity = cash + positions_value
    return {
        "starting_cash": start,
        "cash": cash,
        "positions_value": positions_value,
        "total_equity": total_equity,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "total_return_pct": ((total_equity / start - 1.0) * 100.0) if start else 0.0,
        "open_count": len(open_pos),
        "closed_count": len(closed_pos),
    }


def pnl_by_source() -> list[dict]:
    """"Which setups made money?" — realized + unrealized P&L grouped by
    the filter-setup label each lot was booked from."""
    if not snapshots.enabled():
        return []
    agg: dict[str, dict] = {}
    for p in list_positions(None):
        key = p["source_label"] or "(unlabeled)"
        a = agg.setdefault(key, {"source_label": key, "positions": 0,
                                 "open": 0, "closed": 0, "cost_basis": 0.0,
                                 "realized_pnl": 0.0, "unrealized_pnl": 0.0})
        a["positions"] += 1
        a["cost_basis"] += p["cost_basis"] or 0.0
        if p["status"] == "open":
            a["open"] += 1
            a["unrealized_pnl"] += p["unrealized_pnl"] or 0.0
        else:
            a["closed"] += 1
            a["realized_pnl"] += p["realized_pnl"] or 0.0
    out = []
    for a in agg.values():
        a["total_pnl"] = a["realized_pnl"] + a["unrealized_pnl"]
        out.append(a)
    out.sort(key=lambda x: -x["total_pnl"])
    return out


def equity_curve() -> list[dict]:
    if not snapshots.enabled():
        return []
    try:
        with snapshots._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT as_of, cash, positions_value, total_equity, spy_close "
                "FROM paper_equity ORDER BY as_of"
            )
            rows = cur.fetchall()
    except Exception as exc:
        log.warning("paper_portfolio.equity_curve failed: %s", exc)
        return []
    return [{
        "as_of": r[0].isoformat() if r[0] else None,
        "cash": float(r[1]) if r[1] is not None else None,
        "positions_value": float(r[2]) if r[2] is not None else None,
        "total_equity": float(r[3]) if r[3] is not None else None,
        "spy_close": float(r[4]) if r[4] is not None else None,
    } for r in rows]


# --- price fetch (used by sell + the phase-2 mark-to-market cron) ---------

def latest_stock_price(ticker: str) -> float | None:
    """Best-effort latest stock price via yfinance."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        try:
            p = float(t.fast_info["last_price"])
            if p > 0:
                return p
        except Exception:
            pass
        hist = t.history(period="5d", interval="1d", auto_adjust=False)
        if hist is not None and len(hist):
            return float(hist["Close"].iloc[-1])
    except Exception as exc:
        log.warning("latest_stock_price(%s) failed: %s", ticker, exc)
    return None


def latest_option_mid(ticker: str, option_type: str, strike: float,
                      expiration: str) -> float | None:
    """Latest per-share mid for a specific listed contract. Returns None if
    the contract can't be found (delisted / no quotes) — the caller then
    falls back to intrinsic value (at/after expiration) or the last mark."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        chain = t.option_chain(str(expiration))
        df = chain.calls if _normalize_option_type(option_type) == "call" else chain.puts
        match = df[df["strike"] == float(strike)]
        if match is None or not len(match):
            return None
        bid = float(match["bid"].iloc[0])
        ask = float(match["ask"].iloc[0])
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        last = float(match["lastPrice"].iloc[0])
        return last if last > 0 else None
    except Exception as exc:
        log.warning("latest_option_mid(%s %s %s) failed: %s",
                    ticker, strike, expiration, exc)
    return None


def latest_mark(asset_type: str, ticker: str, option_type=None, strike=None,
                expiration=None) -> float | None:
    """Latest per-unit mark for a position. For options past expiration,
    settle at intrinsic value from the underlying's latest price."""
    if asset_type == "stock":
        return latest_stock_price(ticker)
    # option
    if expiration is not None:
        try:
            exp_d = (expiration if isinstance(expiration, date)
                     else datetime.strptime(str(expiration), "%Y-%m-%d").date())
            if exp_d < date.today():
                under = latest_stock_price(ticker)
                if under is None:
                    return None
                return option_intrinsic(_normalize_option_type(option_type),
                                        under, float(strike))
        except Exception:
            pass
    mid = latest_option_mid(ticker, option_type, strike, expiration)
    if mid is not None:
        return mid
    # Fall back to intrinsic if the contract vanished but we have a strike.
    under = latest_stock_price(ticker)
    if under is not None and strike is not None:
        return option_intrinsic(_normalize_option_type(option_type), under, float(strike))
    return None
