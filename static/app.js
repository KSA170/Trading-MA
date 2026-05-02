const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const els = {
  runBtn: $('#run-btn'),
  status: $('#status-text'),
  matchCount: $('#match-count'),
  asOfLabel: $('#as-of-label'),
  body: $('#results-body'),
  thead: document.querySelector('#results-table thead'),
  thHigh: $('#th-high'),
  historyBody: $('#history-body'),
  modal: $('#chart-modal'),
  modalClose: $('#chart-close'),
  chartTitle: $('#chart-title'),
  chartContainer: $('#chart-container'),
};

let lastResults = [];
let sortState = { key: null, dir: null }; // dir: 'asc' | 'desc'

const inputs = {
  high_lookback: $('#high_lookback'),
  rsi_min: $('#rsi_min'),
  rsi_max: $('#rsi_max'),
  rsi_dev_min_pct: $('#rsi_dev_min_pct'),
  rsi_dev_max_pct: $('#rsi_dev_max_pct'),
  rvol_lookback: $('#rvol_lookback'),
  rvol_min: $('#rvol_min'),
  price_min: $('#price_min'),
  price_max: $('#price_max'),
};

const toggles = {
  apply_high: $('#apply_high'),
  apply_rsi: $('#apply_rsi'),
  apply_rsi_dev: $('#apply_rsi_dev'),
  apply_rvol: $('#apply_rvol'),
  apply_price: $('#apply_price'),
};

const listFilter = $('#list_filter');
const asOfSelect = $('#as_of_offset');

const LIST_LABELS = {
  sp500: 'S&P 500',
  dow: 'Dow 30',
  nasdaq: 'Nasdaq',
  tsx: 'TSX',
};

function setStatus(text) { els.status.textContent = text; }

function fmtNum(n, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return Number(n).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function fmtVol(n) {
  if (!n && n !== 0) return '—';
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return String(n);
}

function buildQuery() {
  const params = new URLSearchParams();
  for (const [k, el] of Object.entries(inputs)) {
    params.set(k, el.value);
  }
  for (const [k, el] of Object.entries(toggles)) {
    params.set(k, el.checked ? '1' : '0');
  }
  if (listFilter && listFilter.value) {
    params.set('lists', listFilter.value);
  }
  if (asOfSelect) {
    params.set('as_of_offset', asOfSelect.value || '0');
  }
  return params.toString();
}

function syncDisabledStates() {
  const map = {
    apply_high: 'high',
    apply_rsi: 'rsi',
    apply_rsi_dev: 'rsi_dev',
    apply_rvol: 'rvol',
    apply_price: 'price',
  };
  for (const [toggleId, groupKey] of Object.entries(map)) {
    const t = toggles[toggleId];
    const group = document.querySelector(`.filter-group[data-group="${groupKey}"]`);
    if (!t || !group) continue;
    group.classList.toggle('disabled', !t.checked);
  }
}

async function loadDates() {
  if (!asOfSelect) return;
  try {
    const res = await fetch('/api/dates');
    const data = await res.json();
    const dates = data.dates || [];
    if (!dates.length) return;
    asOfSelect.innerHTML = '';
    dates.forEach((d, i) => {
      const opt = document.createElement('option');
      opt.value = String(d.offset);
      opt.textContent = i === 0 ? `${d.date} (latest)` : d.date;
      asOfSelect.appendChild(opt);
    });
  } catch (err) {
    console.warn('date list load failed:', err);
  }
}

async function runScreen() {
  setStatus('running…');
  els.runBtn.disabled = true;
  els.body.innerHTML = '<tr class="empty"><td colspan="12">Fetching market data — this may take 30–90s on a cold cache…</td></tr>';
  els.matchCount.textContent = '';
  if (els.asOfLabel) els.asOfLabel.textContent = '';
  updateHighHeader();
  try {
    const res = await fetch('/api/screen?' + buildQuery());
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    lastResults = data.results || [];
    renderTable();
    if (els.asOfLabel) {
      const d = data.as_of_date || (asOfSelect && asOfSelect.options[asOfSelect.selectedIndex]?.text) || '';
      els.asOfLabel.textContent = d ? `as of ${d}` : '';
    }
    setStatus(data.cached ? 'cached' : `done in ${data.elapsed_sec || '?'}s`);
    loadHistory();
  } catch (err) {
    console.error(err);
    setStatus('error');
    els.body.innerHTML = `<tr class="empty"><td colspan="12">Error: ${err.message}</td></tr>`;
  } finally {
    els.runBtn.disabled = false;
  }
}

function updateHighHeader() {
  if (!els.thHigh) return;
  const n = parseInt(inputs.high_lookback.value, 10);
  els.thHigh.textContent = (Number.isFinite(n) && n > 0) ? `${n}d high` : 'High';
}

function applySortIndicators() {
  if (!els.thead) return;
  els.thead.querySelectorAll('th[data-sort]').forEach((th) => {
    th.classList.remove('sort-asc', 'sort-desc');
    if (sortState.key && th.dataset.sort === sortState.key) {
      th.classList.add(sortState.dir === 'asc' ? 'sort-asc' : 'sort-desc');
    }
  });
}

function sortedResults() {
  if (!sortState.key) return lastResults;
  const th = els.thead && els.thead.querySelector(`th[data-sort="${sortState.key}"]`);
  const type = th ? th.dataset.type : 'text';
  const sign = sortState.dir === 'asc' ? 1 : -1;
  const out = lastResults.slice();
  out.sort((a, b) => {
    const va = a[sortState.key];
    const vb = b[sortState.key];
    if (va === vb) return 0;
    if (va === null || va === undefined) return 1;
    if (vb === null || vb === undefined) return -1;
    if (type === 'num') return (Number(va) - Number(vb)) * sign;
    return String(va).localeCompare(String(vb)) * sign;
  });
  return out;
}

function renderResults(results) {
  els.matchCount.textContent = `(${results.length})`;
  if (!results.length) {
    els.body.innerHTML = '<tr class="empty"><td colspan="12">No matches with these filters.</td></tr>';
    return;
  }
  els.body.innerHTML = '';
  for (const r of results) {
    const tr = document.createElement('tr');
    const pctClass = r.pct_change >= 0 ? 'pos' : 'neg';
    const devClass = r.rsi_dev_pct >= 0 ? 'pos' : 'neg';
    if (r.rsi !== null && r.rsi_sma9 !== null && r.rsi !== undefined && r.rsi_sma9 !== undefined && r.rsi === r.rsi_sma9) {
      tr.classList.add('row-equal');
    }
    tr.innerHTML = `
      <td><strong>${r.ticker}</strong></td>
      <td>${escapeHtml(r.name || '')}</td>
      <td><span class="chip">${r.exchange}</span></td>
      <td class="num">${fmtNum(r.close)}</td>
      <td class="num ${pctClass}">${r.pct_change >= 0 ? '+' : ''}${fmtNum(r.pct_change)}%</td>
      <td class="num">${fmtNum(r.high_lookback)}</td>
      <td class="num">${fmtNum(r.rsi)}</td>
      <td class="num">${fmtNum(r.rsi_sma9)}</td>
      <td class="num ${devClass}">${r.rsi_dev_pct >= 0 ? '+' : ''}${fmtNum(r.rsi_dev_pct)}%</td>
      <td class="num">${fmtNum(r.rel_volume)}×</td>
      <td class="num">${fmtVol(r.volume)}</td>
      <td><button class="link" data-ticker="${escapeHtml(r.ticker)}">view</button></td>
    `;
    els.body.appendChild(tr);
  }
  els.body.querySelectorAll('button.link').forEach((b) => {
    b.addEventListener('click', () => openChart(b.dataset.ticker));
  });
}

function renderTable() {
  applySortIndicators();
  renderResults(sortedResults());
}

function onSortHeaderClick(ev) {
  const th = ev.target.closest('th[data-sort]');
  if (!th) return;
  const key = th.dataset.sort;
  if (sortState.key === key) {
    sortState.dir = sortState.dir === 'asc' ? 'desc' : 'asc';
  } else {
    sortState = { key, dir: 'asc' };
  }
  renderTable();
}

async function loadHistory() {
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    renderHistory(data.records || []);
  } catch (err) {
    console.error('history load failed', err);
  }
}

function renderHistory(records) {
  if (!records.length) {
    els.historyBody.innerHTML = '<p class="muted">No history yet. Run the screener to start logging.</p>';
    return;
  }
  els.historyBody.innerHTML = '';
  for (const rec of records) {
    const div = document.createElement('div');
    div.className = 'history-day';
    const items = (rec.top || [])
      .map((t) => {
        const dev = t.rsi_dev_pct ?? t.rsi9_dev_pct; // back-compat for old snapshots
        const devTxt = dev === undefined || dev === null ? '' : `, Δsma ${dev >= 0 ? '+' : ''}${fmtNum(dev)}%`;
        return `<li><strong>${escapeHtml(t.ticker)}</strong> — ${escapeHtml(t.name || '')} <span class="muted">RSI ${fmtNum(t.rsi)}${devTxt}, RVol ${fmtNum(t.rel_volume)}×</span></li>`;
      })
      .join('');
    div.innerHTML = `
      <h3><span>${rec.date}</span><span class="muted">${rec.top.length} stk</span></h3>
      <ol>${items || '<li class="muted">empty</li>'}</ol>`;
    els.historyBody.appendChild(div);
  }
}

// --- chart modal -----------------------------------------------------------

let chart, chartResizeObserver;

function disposeChart() {
  if (chartResizeObserver) {
    try { chartResizeObserver.disconnect(); } catch (_) { /* ignore */ }
    chartResizeObserver = null;
  }
  if (chart && chart.remove) {
    try { chart.remove(); } catch (_) { /* ignore */ }
  }
  chart = null;
  els.chartContainer.innerHTML = '';
}

async function openChart(ticker) {
  els.chartTitle.textContent = ticker + ' — daily';
  els.modal.classList.remove('hidden');
  disposeChart();
  try {
    const res = await fetch('/api/chart/' + encodeURIComponent(ticker));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    drawChart(data);
  } catch (err) {
    els.chartContainer.innerHTML = `<p class="muted" style="padding:20px">Failed to load chart: ${err.message}</p>`;
  }
}

function closeChart() {
  els.modal.classList.add('hidden');
  disposeChart();
}

function drawChart(data) {
  const rows = (data.rows || []).filter((r) => r.close !== null);
  if (!rows.length) {
    els.chartContainer.innerHTML = '<p class="muted" style="padding:20px">No chart data.</p>';
    return;
  }
  els.chartTitle.textContent = `${data.ticker} ${data.name ? '— ' + data.name : ''} (daily)`;

  // Single chart with two panes (price on top, RSI below). Because both panes
  // share the same chart instance, they share one bar grid and one time axis.
  // The right price scale must also have the *same width* in every pane,
  // otherwise the pane with the wider scale loses drawing-area width and its
  // bars drift leftward relative to the price pane. We enforce this by
  // (a) keeping series labels off the price scale and (b) pinning a minimum
  // width on every pane's right scale after creation.
  const SCALE_MIN_WIDTH = 80;

  chart = LightweightCharts.createChart(els.chartContainer, {
    layout: { background: { color: '#161b22' }, textColor: '#c9d1d9' },
    grid: { vertLines: { color: '#22272e' }, horzLines: { color: '#22272e' } },
    rightPriceScale: { borderColor: '#2a313c', minimumWidth: SCALE_MIN_WIDTH },
    leftPriceScale: { visible: false },
    timeScale: { borderColor: '#2a313c', rightOffset: 4, barSpacing: 6 },
    crosshair: { mode: 1 },
    autoSize: true,
  });

  // --- Pane 0: candles + EMAs + volume ---
  const candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: '#3fb950', downColor: '#f85149',
    wickUpColor: '#3fb950', wickDownColor: '#f85149',
    borderVisible: false,
  }, 0);
  const ema21Series = chart.addSeries(LightweightCharts.LineSeries, {
    color: '#d2a8ff', lineWidth: 2, priceLineVisible: false,
  }, 0);
  const ema50Series = chart.addSeries(LightweightCharts.LineSeries, {
    color: '#ffa657', lineWidth: 2, priceLineVisible: false,
  }, 0);
  const volSeries = chart.addSeries(LightweightCharts.HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: '',
    color: '#30363d',
    lastValueVisible: false,
    priceLineVisible: false,
  }, 0);
  volSeries.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

  candleSeries.setData(rows.map((r) => ({
    time: r.time, open: r.open, high: r.high, low: r.low, close: r.close,
  })));
  ema21Series.setData(rows.filter((r) => r.ema21 !== null).map((r) => ({ time: r.time, value: r.ema21 })));
  ema50Series.setData(rows.filter((r) => r.ema50 !== null).map((r) => ({ time: r.time, value: r.ema50 })));
  volSeries.setData(rows.map((r) => ({
    time: r.time, value: r.volume || 0,
    color: r.close >= r.open ? 'rgba(63,185,80,0.4)' : 'rgba(248,81,73,0.4)',
  })));

  // --- Pane 1: RSI(14) + 9d SMA of RSI ---
  // No `title` on these series — series titles render as labels on the price
  // scale and would widen this pane's right scale, mis-aligning its bars
  // with the price pane above. The HTML legend already identifies the lines.
  const rsiSeries = chart.addSeries(LightweightCharts.LineSeries, {
    color: '#58a6ff', lineWidth: 2,
    priceLineVisible: false,
  }, 1);
  const rsiSmaSeries = chart.addSeries(LightweightCharts.LineSeries, {
    color: '#f0883e', lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  }, 1);
  rsiSeries.setData(rows.filter((r) => r.rsi !== null).map((r) => ({ time: r.time, value: r.rsi })));
  rsiSmaSeries.setData(rows.filter((r) => r.rsi_sma9 !== null && r.rsi_sma9 !== undefined).map((r) => ({ time: r.time, value: r.rsi_sma9 })));
  rsiSeries.createPriceLine({ price: 70, color: '#f85149', lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: '70' });
  rsiSeries.createPriceLine({ price: 30, color: '#3fb950', lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: '30' });
  rsiSeries.createPriceLine({ price: 50, color: '#8b949e', lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: '50' });

  // --- Pane 2: MACD(12, 26, 9) ---
  // Histogram drawn first so the MACD/signal lines render on top of the bars.
  // TradingView 4-color convention: bright green when histogram is above zero
  // *and rising*, faded green when above zero *but falling*, bright red when
  // below zero *and falling further*, faded red when below zero *but
  // recovering*. Tells you momentum direction at a glance.
  const macdHistSeries = chart.addSeries(LightweightCharts.HistogramSeries, {
    priceFormat: { type: 'price', precision: 4, minMove: 0.0001 },
    priceLineVisible: false,
    lastValueVisible: false,
  }, 2);
  const macdSeries = chart.addSeries(LightweightCharts.LineSeries, {
    color: '#58a6ff', lineWidth: 2,
    priceLineVisible: false,
  }, 2);
  const macdSignalSeries = chart.addSeries(LightweightCharts.LineSeries, {
    color: '#f0883e', lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  }, 2);
  const HIST_BULL_BRIGHT = '#26a69a';
  const HIST_BULL_FADED = 'rgba(38, 166, 154, 0.40)';
  const HIST_BEAR_BRIGHT = '#ef5350';
  const HIST_BEAR_FADED = 'rgba(239, 83, 80, 0.40)';
  const macdRows = rows.filter((r) => r.macd !== null && r.macd !== undefined);
  const histRows = macdRows.filter((r) => r.macd_hist !== null && r.macd_hist !== undefined);
  const histPoints = [];
  let prevHist = null;
  for (const r of histRows) {
    const h = r.macd_hist;
    let color;
    if (h >= 0) {
      color = (prevHist === null || h > prevHist) ? HIST_BULL_BRIGHT : HIST_BULL_FADED;
    } else {
      color = (prevHist === null || h < prevHist) ? HIST_BEAR_BRIGHT : HIST_BEAR_FADED;
    }
    histPoints.push({ time: r.time, value: h, color });
    prevHist = h;
  }
  macdHistSeries.setData(histPoints);
  macdSeries.setData(macdRows.map((r) => ({ time: r.time, value: r.macd })));
  macdSignalSeries.setData(rows
    .filter((r) => r.macd_signal !== null && r.macd_signal !== undefined)
    .map((r) => ({ time: r.time, value: r.macd_signal })));
  macdSeries.createPriceLine({ price: 0, color: '#8b949e', lineStyle: 2, lineWidth: 1, axisLabelVisible: false });

  // Pin every pane's right price scale to the same minimum width so the
  // chart drawing area has identical horizontal extents in each pane.
  const panes = chart.panes() || [];
  panes.forEach((p) => {
    try { p.priceScale('right').applyOptions({ minimumWidth: SCALE_MIN_WIDTH }); }
    catch (_) { /* ignore */ }
  });

  // Pane proportions via stretch factors (the v5-correct API). setHeight
  // alone tends to be ignored under autoSize because the chart re-distributes
  // space using stretch factors. Ratios below give roughly 56/22/22.
  try {
    if (panes.length >= 3) {
      const setStretch = (p, f) => {
        if (typeof p.setStretchFactor === 'function') p.setStretchFactor(f);
        else if (typeof p.setHeight === 'function') p.setHeight(f * 100);
      };
      setStretch(panes[0], 2.6);
      setStretch(panes[1], 1.0);
      setStretch(panes[2], 1.0);
    } else if (panes.length >= 2) {
      const setStretch = (p, f) => {
        if (typeof p.setStretchFactor === 'function') p.setStretchFactor(f);
        else if (typeof p.setHeight === 'function') p.setHeight(f * 100);
      };
      setStretch(panes[0], 2.8);
      setStretch(panes[1], 1.0);
    }
  } catch (_) { /* best-effort */ }

  // Pane labels — overlay HTML divs positioned by each pane's actual rendered
  // pixel height. More reliable than the v5 watermark API across CDN builds.
  const PANE_LABELS = ['Price + EMAs', 'RSI(14) + 9d SMA of RSI', 'MACD(12, 26, 9)'];
  const placeLabels = () => {
    els.chartContainer.querySelectorAll('.pane-label').forEach((n) => n.remove());
    if (!chart) return;
    const ps = chart.panes() || [];
    let topPx = 0;
    ps.forEach((p, i) => {
      if (!PANE_LABELS[i]) return;
      const div = document.createElement('div');
      div.className = 'pane-label';
      div.textContent = PANE_LABELS[i];
      div.style.top = (topPx + 6) + 'px';
      els.chartContainer.appendChild(div);
      try { topPx += (p.getHeight && p.getHeight()) || 0; } catch (_) { /* ignore */ }
    });
  };
  // Defer one frame so pane heights have settled after stretch factors apply.
  requestAnimationFrame(() => { placeLabels(); requestAnimationFrame(placeLabels); });

  // Reposition labels when the modal/container is resized.
  chartResizeObserver = new ResizeObserver(() => requestAnimationFrame(placeLabels));
  chartResizeObserver.observe(els.chartContainer);

  chart.timeScale().fitContent();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (m) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[m]));
}

// --- bootstrap -------------------------------------------------------------

els.runBtn.addEventListener('click', runScreen);
els.modalClose.addEventListener('click', closeChart);
els.modal.addEventListener('click', (e) => { if (e.target === els.modal) closeChart(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeChart(); });

Object.values(toggles).forEach((t) => t && t.addEventListener('change', syncDisabledStates));
syncDisabledStates();

if (els.thead) els.thead.addEventListener('click', onSortHeaderClick);
if (inputs.high_lookback) inputs.high_lookback.addEventListener('input', updateHighHeader);
updateHighHeader();

loadDates();
loadHistory();
