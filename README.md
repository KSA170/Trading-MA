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
| `nasdaq100`  | Nasdaq 100  | ~100  |
| `tsx`        | TSX (Canada, `.TO` suffix) | ~150 |

Each result row shows which lists the ticker is a member of (e.g. AAPL is in
S&P 500, Dow 30, and Nasdaq 100).

## Default screen

A ticker passes when **all four** are true on the most recent daily close:

1. **30-day high** — previous close ≥ the highest close in the prior 30 days.
2. **RSI(14) ∈ [45, 50]** — Wilder smoothing.
3. **RSI(9) deviation vs RSI(14) ∈ [-5%, +10%]** — `(RSI9 − RSI14) / RSI14`.
4. **10-day relative volume > 0.5** — yesterday's volume / mean of the prior
   10 days.

Every filter is adjustable from the UI. Each criterion has an "Apply"
checkbox — uncheck it to ignore that filter while still seeing its measured
value in the table.

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
- `GET /api/chart/<ticker>` — OHLCV + EMA21 + EMA50 + RSI(14) + RSI(9)
- `GET /api/history` — top-5 hits per day from `history.json`
- `GET /api/lists` — available list keys + labels

`/api/screen` query params:

| param                 | default | notes                                       |
|-----------------------|---------|---------------------------------------------|
| `high_lookback`       | 30      | days for the prev-close-is-N-day-high check |
| `rsi_min`, `rsi_max`  | 45, 50  | RSI(14) band                                |
| `rsi9_dev_min_pct`    | -5      | min `(RSI9-RSI14)/RSI14 * 100`             |
| `rsi9_dev_max_pct`    | 10      | max `(RSI9-RSI14)/RSI14 * 100`             |
| `rvol_lookback`       | 10      | trailing days for average volume            |
| `rvol_min`            | 0.5     | min volume / avg(rvol_lookback)             |
| `apply_high`          | 1       | `0` to skip the 30-day high check           |
| `apply_rsi`           | 1       | `0` to skip the RSI(14) band check          |
| `apply_rsi9`          | 1       | `0` to skip the RSI(9) deviation check      |
| `apply_rvol`          | 1       | `0` to skip the relative-volume check       |
| `lists`               | (all)   | one of `sp500,dow,nasdaq100,tsx`; empty = all |

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
| `tickers.py`   | List membership (S&P 500 / Dow 30 / Nasdaq 100 / TSX)|
| `templates/`   | `index.html`                                         |
| `static/`      | `style.css`, `app.js` (uses lightweight-charts CDN)  |
| `history.json` | Daily top-5 snapshots (created on first run)         |
| `render.yaml`  | Render.com blueprint for remote hosting              |
