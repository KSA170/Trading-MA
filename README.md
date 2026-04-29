# Trading-MA

A simple web app that screens US (S&P 500) and Canadian (TSX) stocks for a
breakout setup, then lets you click any name for a daily chart with RSI(14)
and the 21/50 EMA.

## Default screen

A ticker passes when **all four** are true on the most recent daily close:

1. **30-day high** — previous close ≥ the highest close in the prior 30 days.
2. **RSI(14) ∈ [45, 50]** — Wilder smoothing.
3. **RSI(9) deviation vs RSI(14) ∈ [-5%, +10%]** —
   `(RSI9 − RSI14) / RSI14`.
4. **10-day relative volume > 0.5** — yesterday's volume / mean of the prior
   10 days.

Each filter (lookback windows, RSI band, RSI(9) deviation band, RVol
threshold) is adjustable from the UI.

Data source: Yahoo Finance via [`yfinance`](https://pypi.org/project/yfinance/).
Canadian tickers use the `.TO` suffix.

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
- `GET /api/screen?high_lookback=30&rsi_min=45&rsi_max=50&rsi9_dev_min_pct=-5&rsi9_dev_max_pct=10&rvol_lookback=10&rvol_min=0.5`
- `GET /api/chart/<ticker>` — OHLCV + EMA21 + EMA50 + RSI(14)
- `GET /api/history` — top-5 hits per day from `history.json`

## History

Every default-parameter run writes the top 5 results to `history.json`
(keyed by date, last ~60 days kept). The right-hand column on the page lists
those days so you can see what was hot before.

## Files

| file               | purpose                                              |
|--------------------|------------------------------------------------------|
| `app.py`           | Flask app and JSON endpoints                         |
| `screener.py`      | Indicator math + per-ticker evaluation              |
| `tickers.py`       | US / Canadian ticker universe                        |
| `templates/`       | `index.html`                                         |
| `static/`          | `style.css`, `app.js` (uses lightweight-charts CDN) |
| `history.json`     | Daily top-5 snapshots (created on first run)         |
