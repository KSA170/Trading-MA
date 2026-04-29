const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const els = {
  runBtn: $('#run-btn'),
  status: $('#status-text'),
  matchCount: $('#match-count'),
  body: $('#results-body'),
  historyBody: $('#history-body'),
  modal: $('#chart-modal'),
  modalClose: $('#chart-close'),
  chartTitle: $('#chart-title'),
  priceChart: $('#price-chart'),
  rsiChart: $('#rsi-chart'),
};

const inputs = {
  high_lookback: $('#high_lookback'),
  rsi_min: $('#rsi_min'),
  rsi_max: $('#rsi_max'),
  rvol_lookback: $('#rvol_lookback'),
  rvol_min: $('#rvol_min'),
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
  return params.toString();
}

async function runScreen() {
  setStatus('running…');
  els.runBtn.disabled = true;
  els.body.innerHTML = '<tr class="empty"><td colspan="10">Fetching market data — this may take 30–90s on a cold cache…</td></tr>';
  els.matchCount.textContent = '';
  try {
    const res = await fetch('/api/screen?' + buildQuery());
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    renderResults(data.results || []);
    setStatus(data.cached ? 'cached' : `done in ${data.elapsed_sec || '?'}s`);
    loadHistory();
  } catch (err) {
    console.error(err);
    setStatus('error');
    els.body.innerHTML = `<tr class="empty"><td colspan="10">Error: ${err.message}</td></tr>`;
  } finally {
    els.runBtn.disabled = false;
  }
}

function renderResults(results) {
  els.matchCount.textContent = `(${results.length})`;
  if (!results.length) {
    els.body.innerHTML = '<tr class="empty"><td colspan="10">No matches with these filters.</td></tr>';
    return;
  }
  els.body.innerHTML = '';
  for (const r of results) {
    const tr = document.createElement('tr');
    const pctClass = r.pct_change >= 0 ? 'pos' : 'neg';
    tr.innerHTML = `
      <td><strong>${r.ticker}</strong></td>
      <td>${escapeHtml(r.name || '')}</td>
      <td><span class="chip">${r.exchange}</span></td>
      <td class="num">${fmtNum(r.close)}</td>
      <td class="num ${pctClass}">${r.pct_change >= 0 ? '+' : ''}${fmtNum(r.pct_change)}%</td>
      <td class="num">${fmtNum(r.high_lookback)}</td>
      <td class="num">${fmtNum(r.rsi)}</td>
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
      .map((t) => `<li><strong>${escapeHtml(t.ticker)}</strong> — ${escapeHtml(t.name || '')} <span class="muted">RSI ${fmtNum(t.rsi)}, RVol ${fmtNum(t.rel_volume)}×</span></li>`)
      .join('');
    div.innerHTML = `
      <h3><span>${rec.date}</span><span class="muted">${rec.top.length} stk</span></h3>
      <ol>${items || '<li class="muted">empty</li>'}</ol>`;
    els.historyBody.appendChild(div);
  }
}

// --- chart modal -----------------------------------------------------------

let priceChart, rsiChart, candleSeries, ema21Series, ema50Series, rsiSeries, volSeries;

function disposeCharts() {
  [priceChart, rsiChart].forEach((c) => c && c.remove && c.remove());
  priceChart = rsiChart = candleSeries = ema21Series = ema50Series = rsiSeries = volSeries = null;
  els.priceChart.innerHTML = '';
  els.rsiChart.innerHTML = '';
}

async function openChart(ticker) {
  els.chartTitle.textContent = ticker + ' — daily';
  els.modal.classList.remove('hidden');
  disposeCharts();
  try {
    const res = await fetch('/api/chart/' + encodeURIComponent(ticker));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    drawChart(data);
  } catch (err) {
    els.priceChart.innerHTML = `<p class="muted" style="padding:20px">Failed to load chart: ${err.message}</p>`;
  }
}

function closeChart() {
  els.modal.classList.add('hidden');
  disposeCharts();
}

function drawChart(data) {
  const rows = (data.rows || []).filter((r) => r.close !== null);
  if (!rows.length) {
    els.priceChart.innerHTML = '<p class="muted" style="padding:20px">No chart data.</p>';
    return;
  }
  els.chartTitle.textContent = `${data.ticker} ${data.name ? '— ' + data.name : ''} (daily)`;

  const baseOpts = {
    layout: { background: { color: '#161b22' }, textColor: '#c9d1d9' },
    grid: { vertLines: { color: '#22272e' }, horzLines: { color: '#22272e' } },
    timeScale: { borderColor: '#2a313c' },
    rightPriceScale: { borderColor: '#2a313c' },
    crosshair: { mode: 1 },
  };

  priceChart = LightweightCharts.createChart(els.priceChart, {
    ...baseOpts,
    width: els.priceChart.clientWidth,
    height: els.priceChart.clientHeight,
  });
  candleSeries = priceChart.addCandlestickSeries({
    upColor: '#3fb950', downColor: '#f85149',
    wickUpColor: '#3fb950', wickDownColor: '#f85149',
    borderVisible: false,
  });
  ema21Series = priceChart.addLineSeries({ color: '#d2a8ff', lineWidth: 2, priceLineVisible: false });
  ema50Series = priceChart.addLineSeries({ color: '#ffa657', lineWidth: 2, priceLineVisible: false });
  volSeries = priceChart.addHistogramSeries({
    priceFormat: { type: 'volume' },
    priceScaleId: '',
    color: '#30363d',
  });
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

  rsiChart = LightweightCharts.createChart(els.rsiChart, {
    ...baseOpts,
    width: els.rsiChart.clientWidth,
    height: els.rsiChart.clientHeight,
  });
  rsiSeries = rsiChart.addLineSeries({ color: '#58a6ff', lineWidth: 2 });
  rsiSeries.setData(rows.filter((r) => r.rsi !== null).map((r) => ({ time: r.time, value: r.rsi })));
  rsiSeries.createPriceLine({ price: 70, color: '#f85149', lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: '70' });
  rsiSeries.createPriceLine({ price: 30, color: '#3fb950', lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: '30' });
  rsiSeries.createPriceLine({ price: 50, color: '#8b949e', lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: '50' });

  // sync time axes
  priceChart.timeScale().subscribeVisibleLogicalRangeChange((r) => r && rsiChart.timeScale().setVisibleLogicalRange(r));
  rsiChart.timeScale().subscribeVisibleLogicalRangeChange((r) => r && priceChart.timeScale().setVisibleLogicalRange(r));

  priceChart.timeScale().fitContent();
  rsiChart.timeScale().fitContent();

  // resize to container changes
  const ro = new ResizeObserver(() => {
    if (priceChart) priceChart.applyOptions({ width: els.priceChart.clientWidth, height: els.priceChart.clientHeight });
    if (rsiChart) rsiChart.applyOptions({ width: els.rsiChart.clientWidth, height: els.rsiChart.clientHeight });
  });
  ro.observe(els.priceChart);
  ro.observe(els.rsiChart);
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

loadHistory();
