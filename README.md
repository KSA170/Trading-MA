# Trading-MA

A web app that screens US and Canadian stocks for a breakout setup. Adjust
the filter band, run the screen, sort the results.

## Universe

The screened universe is grouped by **exchange**. Tick any combination of
the boxes in the "Exchanges" filter card; "Select all" toggles them in
bulk.

| key      | exchange                            | size       | source |
|----------|-------------------------------------|------------|--------|
| `nyse`   | New York Stock Exchange             | ~2,400     | SEC `company_tickers_exchange.json` (fallback: NASDAQ Trader) |
| `nasdaq` | NASDAQ Stock Market                 | ~3,500     | SEC `company_tickers_exchange.json` (fallback: NASDAQ Trader) |
| `amex`   | NYSE American (AMEX)                | ~250       | SEC `company_tickers_exchange.json` (fallback: NASDAQ Trader) |
| `tsx`    | Toronto Stock Exchange (`.TO`)      | ~160       | Curated — TMX does not publish a free directory       |
| `tsxv`   | TSX Venture Exchange (`.V`)         | ~95        | Curated — most-traded subset                          |

Total: ~6,400 deduped tickers when every exchange is selected.

US tickers come from the SEC's government-hosted, programmatic-access
`company_tickers_exchange.json` (which carries the exchange field). If the
SEC source is unreachable the screener falls back to NASDAQ Trader's
symbol-directory files. Both are cached on disk for 24h; the ↻ button next
to "Exchanges" force-refreshes and reports any fetch error inline.

**Cold-cache cost.** A first run against the full US+CA universe takes
**5–8 minutes** on Render's free tier while yfinance fetches 6 months of
daily history for every name. Subsequent runs (same params, within 30 min)
hit the in-memory cache and return in milliseconds. To keep a single run
fast, untick exchanges you don't need — picking only `tsx` is roughly a
3-second screen.

ETFs, warrants, units, and test issues are filtered out of the US
directories so the screen sticks to common-stock listings. Symbol files
are cached on disk for 24h in `.cache/` (gitignored).

## Default screen

Defaults are tuned to catch the early phase of an EMA-reclaim breakout
(RSI rising through 50, price reclaiming EMA21 with EMA21 about to cross
EMA50, MACD histogram flipping bullish, volume above the 10-day average).
A ticker passes when **all eight** are true on the close being evaluated
(latest by default; up to 10 prior trading days are selectable):

1. **Higher-high streak (2 days)** — each of the last 2 daily highs is
   strictly greater than the bar before it.
2. **RSI(14) ∈ [45, 65]** — Wilder smoothing. Above neutral, not yet
   overbought.
3. **RSI(14) deviation vs its 9-day SMA ∈ [0%, +10%]** — RSI is at or
   above its smoothed average (rising momentum).
4. **Price deviation vs EMA(21) ∈ [-1%, +4%]** — close has just reclaimed
   EMA21.
5. **EMA(21) deviation vs EMA(50) ∈ [-3%, +3%]** — EMA21 is at or just
   crossing EMA50 (early golden-cross territory).
6. **MACD(12, 26, 9) histogram bullish** — histogram ≥ 0 *and* today's
   hist > yesterday's. Threshold and "require rising" toggle are
   adjustable.
7. **10-day relative volume ≥ 1.2×** — confirms above-average
   participation.
8. **Price between $1 and $1000** — based on that close.

Every filter is adjustable from the UI. Each criterion has an "Apply"
checkbox — uncheck it to ignore that filter while still seeing its measured
value in the table. The "As-of close" dropdown lets you re-run the screen on
any of the last 10 trading days; the actual evaluated date is shown in the
header and on each row (the per-row date can differ between US and Canadian
names on holidays).

Data source: Yahoo Finance via [`yfinance`](https://pypi.org/project/yfinance/).

## Run it

```bash
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

The first screen takes ~30–90s while it fetches 6 months of daily history for
each name; subsequent runs are cached for 30 minutes.

## Endpoints

- `GET /` — single page UI
- `GET /api/screen?<params>` — see params below
- `GET /api/lists` — available list keys + labels
- `GET /api/dates?n=11` — last N US trading-day dates (anchored on SPY)

`/api/screen` query params:

| param                    | default | notes                                       |
|--------------------------|---------|---------------------------------------------|
| `as_of_offset`           | 0       | 0 = latest close; up to 10 = 10 days back   |
| `high_lookback`          | 2       | required length of the consecutive higher-high streak |
| `rsi_min`, `rsi_max`     | 45, 65  | RSI(14) band                                |
| `rsi_dev_min_pct`        | 0       | min `(RSI14 - SMA(RSI14, 9)) / SMA * 100`   |
| `rsi_dev_max_pct`        | 10      | max `(RSI14 - SMA(RSI14, 9)) / SMA * 100`   |
| `price_dev_min_pct`      | -1      | min `(close - EMA21) / EMA21 * 100`         |
| `price_dev_max_pct`      | 4       | max `(close - EMA21) / EMA21 * 100`         |
| `ema_dev_min_pct`        | -3      | min `(EMA21 - EMA50) / EMA50 * 100`         |
| `ema_dev_max_pct`        | 3       | max `(EMA21 - EMA50) / EMA50 * 100`         |
| `macd_hist_min`          | 0       | min MACD(12,26,9) histogram value           |
| `macd_require_rising`    | 1       | require today's hist > yesterday's hist     |
| `rvol_lookback`          | 10      | trailing days for average volume            |
| `rvol_min`               | 1.2     | min volume / avg(rvol_lookback)             |
| `price_min`, `price_max` | 1, 1000 | inclusive price range                       |
| `apply_high`             | 1       | `0` to skip the higher-high streak check    |
| `apply_rsi`              | 1       | `0` to skip the RSI(14) band check          |
| `apply_rsi_dev`          | 1       | `0` to skip the RSI-vs-SMA deviation check  |
| `apply_price_dev`        | 1       | `0` to skip the price-vs-EMA21 check        |
| `apply_ema_dev`          | 1       | `0` to skip the EMA21-vs-EMA50 check        |
| `apply_macd`             | 1       | `0` to skip the MACD-histogram check        |
| `apply_rvol`             | 1       | `0` to skip the relative-volume check       |
| `apply_price`            | 1       | `0` to skip the price-range check           |
| `lists`                  | (all)   | comma-list of `nyse,nasdaq,amex,tsx,tsxv`; omit = all |

## Files

| file          | purpose                                              |
|---------------|------------------------------------------------------|
| `app.py`      | Flask app and JSON endpoints                         |
| `screener.py` | Indicator math + per-ticker evaluation               |
| `tickers.py`  | List membership (S&P 500 / Dow 30 / Nasdaq / TSX)    |
| `templates/`  | `index.html`                                         |
| `static/`     | `style.css`, `app.js`                                |
| `render.yaml` | Render.com blueprint for remote hosting              |
