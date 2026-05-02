# Trading-MA

A web app that screens US and Canadian stocks for a breakout setup, then lets
you click any name for a daily chart with RSI(14), RSI(9) and the 21/50 EMA.

## Universe

Tickers are organised into named lists; the UI dropdown lets you screen any
single list or all of them combined ("Any"):

| key          | label       | size  |
|--------------|-------------|-------|
| `sp500`      | S&P 500     | ~500  |
| `dow`        | Dow 30      | 30    |
| `nasdaq`     | Nasdaq (broader, ~390 names) | ~390 |
| `tsx`        | TSX (Canada, `.TO` suffix) | ~150 |

Each result row shows which lists the ticker is a member of (e.g. AAPL is in
S&P 500, Dow 30, and Nasdaq).

## Default screen

A ticker passes when **all five** are true on the close being evaluated
(latest by default; up to 10 prior trading days are selectable):

1. **30-day high** — that close ≥ the highest close in the prior 30 days.
2. **RSI(14) ∈ [45, 50]** — Wilder smoothing.
3. **RSI(14) deviation vs its 9-day SMA ∈ [-5%, +5%]** —
   `(RSI14 − SMA(RSI14, 9)) / SMA(RSI14, 9)`.
4. **10-day relative volume > 0.5** — that day's volume / mean of the prior
   10 days.
5. **Price between $1 and $1000** — based on that close.

Every filter is adjustable from the UI. Each criterion has an "Apply"
checkbox — uncheck it to ignore that filter while still seeing its measured
value in the table. The "As-of close" dropdown lets you re-run the screen on
any of the last 10 trading days; the actual evaluated date is shown both in
the header and per row (the per-row date can differ between US and Canadian
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
- `GET /api/chart/<ticker>` — OHLCV + EMA21 + EMA50 + RSI(14) + 9d SMA of RSI
- `GET /api/history` — top-5 hits per day from `history.json`
- `GET /api/lists` — available list keys + labels
- `GET /api/dates?n=11` — last N US trading-day dates (anchored on SPY)

`/api/screen` query params:

| param                  | default | notes                                       |
|------------------------|---------|---------------------------------------------|
| `as_of_offset`         | 0       | 0 = latest close; up to 10 = 10 days back   |
| `high_lookback`        | 30      | days for the prev-close-is-N-day-high check |
| `rsi_min`, `rsi_max`   | 45, 50  | RSI(14) band                                |
| `rsi_dev_min_pct`      | -5      | min `(RSI14 - SMA(RSI14, 9)) / SMA * 100`  |
| `rsi_dev_max_pct`      | 5       | max `(RSI14 - SMA(RSI14, 9)) / SMA * 100`  |
| `rvol_lookback`        | 10      | trailing days for average volume            |
| `rvol_min`             | 0.5     | min volume / avg(rvol_lookback)             |
| `price_min`, `price_max` | 1, 1000 | inclusive price range                     |
| `apply_high`           | 1       | `0` to skip the 30-day high check           |
| `apply_rsi`            | 1       | `0` to skip the RSI(14) band check          |
| `apply_rsi_dev`        | 1       | `0` to skip the RSI-vs-SMA deviation check  |
| `apply_rvol`           | 1       | `0` to skip the relative-volume check       |
| `apply_price`          | 1       | `0` to skip the price-range check           |
| `lists`                | (all)   | one of `sp500,dow,nasdaq,tsx`; empty = all   |

## History

Every default-parameter run (all four filters on, default thresholds, all
lists) writes the top 5 results to `history.json` (keyed by date, last ~60
days kept). The sidebar on the page lists those days so you can see what was
hot before.

## Files

| file           | purpose                                              |
|----------------|------------------------------------------------------|
| `app.py`       | Flask app and JSON endpoints                         |
| `screener.py`  | Indicator math + per-ticker evaluation               |
| `tickers.py`   | List membership (S&P 500 / Dow 30 / Nasdaq / TSX)    |
| `templates/`   | `index.html`                                         |
| `static/`      | `style.css`, `app.js` (uses lightweight-charts CDN)  |
| `history.json` | Daily top-5 snapshots (created on first run)         |
| `render.yaml`  | Render.com blueprint for remote hosting              |
