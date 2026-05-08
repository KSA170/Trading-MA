const $ = (sel) => document.querySelector(sel);

const els = {
  runBtn: $('#run-btn'),
  status: $('#status-text'),
  matchCount: $('#match-count'),
  asOfLabel: $('#as-of-label'),
  body: $('#results-body'),
  thead: document.querySelector('#results-table thead'),
  thHigh: $('#th-high'),
  selectAll: $('#select-all'),
  selectionCount: $('#selection-count'),
  emailBtn: $('#email-btn'),
  shareBtn: $('#share-btn'),
  exportBtn: $('#export-btn'),
  clearSelectionBtn: $('#clear-selection-btn'),
  hoverChart: $('#hover-chart'),
  hoverChartTitle: $('#hover-chart-title'),
  hoverChartStatus: $('#hover-chart-status'),
  hoverChartContainer: $('#hover-chart-container'),
};

const selectedTickers = new Set();

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
  price_dev_min_pct: $('#price_dev_min_pct'),
  price_dev_max_pct: $('#price_dev_max_pct'),
  ema_dev_min_pct: $('#ema_dev_min_pct'),
  ema_dev_max_pct: $('#ema_dev_max_pct'),
};

const toggles = {
  apply_high: $('#apply_high'),
  apply_rsi: $('#apply_rsi'),
  apply_rsi_dev: $('#apply_rsi_dev'),
  apply_rvol: $('#apply_rvol'),
  apply_price: $('#apply_price'),
  apply_price_dev: $('#apply_price_dev'),
  apply_ema_dev: $('#apply_ema_dev'),
};

const listFilter = $('#list_filter');
const asOfSelect = $('#as_of_offset');

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
    apply_price_dev: 'price_dev',
    apply_ema_dev: 'ema_dev',
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
  els.body.innerHTML = '<tr class="empty"><td colspan="16">Fetching market data — this may take 30–90s on a cold cache…</td></tr>';
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
  } catch (err) {
    console.error(err);
    setStatus('error');
    els.body.innerHTML = `<tr class="empty"><td colspan="16">Error: ${err.message}</td></tr>`;
  } finally {
    els.runBtn.disabled = false;
  }
}

function updateHighHeader() {
  if (!els.thHigh) return;
  const n = parseInt(inputs.high_lookback.value, 10);
  els.thHigh.textContent = (Number.isFinite(n) && n > 0) ? `${n}d HH` : 'HH';
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
    els.body.innerHTML = '<tr class="empty"><td colspan="16">No matches with these filters.</td></tr>';
    return;
  }
  els.body.innerHTML = '';
  for (const r of results) {
    const tr = document.createElement('tr');
    const pctClass = r.pct_change >= 0 ? 'pos' : 'neg';
    const devClass = r.rsi_dev_pct >= 0 ? 'pos' : 'neg';
    const emaDevClass = r.price_ema21_dev_pct >= 0 ? 'pos' : 'neg';
    const emaCrossClass = r.ema21_ema50_dev_pct >= 0 ? 'pos' : 'neg';
    if (r.rsi !== null && r.rsi_sma9 !== null && r.rsi !== undefined && r.rsi_sma9 !== undefined && r.rsi === r.rsi_sma9) {
      tr.classList.add('row-equal');
    }
    const isSelected = selectedTickers.has(r.ticker);
    tr.innerHTML = `
      <td class="check"><input type="checkbox" data-select="${escapeHtml(r.ticker)}"${isSelected ? ' checked' : ''} aria-label="Select ${escapeHtml(r.ticker)}" /></td>
      <td data-ticker="${escapeHtml(r.ticker)}"><strong>${r.ticker}</strong></td>
      <td>${escapeHtml(r.name || '')}</td>
      <td><span class="chip">${r.exchange}</span></td>
      <td class="num">${fmtNum(r.close)}</td>
      <td class="num ${pctClass}">${r.pct_change >= 0 ? '+' : ''}${fmtNum(r.pct_change)}%</td>
      <td class="num">${fmtNum(r.high_lookback)}</td>
      <td class="num">${fmtNum(r.rsi)}</td>
      <td class="num">${fmtNum(r.rsi_sma9)}</td>
      <td class="num ${devClass}">${r.rsi_dev_pct >= 0 ? '+' : ''}${fmtNum(r.rsi_dev_pct)}%</td>
      <td class="num">${fmtNum(r.ema21)}</td>
      <td class="num ${emaDevClass}">${r.price_ema21_dev_pct >= 0 ? '+' : ''}${fmtNum(r.price_ema21_dev_pct)}%</td>
      <td class="num">${fmtNum(r.ema50)}</td>
      <td class="num ${emaCrossClass}">${r.ema21_ema50_dev_pct >= 0 ? '+' : ''}${fmtNum(r.ema21_ema50_dev_pct)}%</td>
      <td class="num">${fmtNum(r.rel_volume)}×</td>
      <td class="num">${fmtVol(r.volume)}</td>
    `;
    els.body.appendChild(tr);
  }
}

function renderTable() {
  pruneSelection();
  applySortIndicators();
  renderResults(sortedResults());
  updateSelectionUI();
}

function pruneSelection() {
  if (!selectedTickers.size) return;
  const visible = new Set(lastResults.map((r) => r.ticker));
  for (const t of Array.from(selectedTickers)) {
    if (!visible.has(t)) selectedTickers.delete(t);
  }
}

function updateSelectionUI() {
  const count = selectedTickers.size;
  if (els.selectionCount) {
    els.selectionCount.textContent = count === 1 ? '1 selected' : `${count} selected`;
  }
  [els.emailBtn, els.shareBtn, els.exportBtn, els.clearSelectionBtn].forEach((b) => {
    if (b) b.disabled = count === 0;
  });
  if (els.selectAll) {
    if (!lastResults.length) {
      els.selectAll.checked = false;
      els.selectAll.indeterminate = false;
    } else {
      const allChecked = lastResults.every((r) => selectedTickers.has(r.ticker));
      els.selectAll.checked = allChecked && count > 0;
      els.selectAll.indeterminate = count > 0 && !allChecked;
    }
  }
}

function onRowCheckboxChange(ev) {
  const cb = ev.target.closest('input[data-select]');
  if (!cb) return;
  const ticker = cb.dataset.select;
  if (cb.checked) selectedTickers.add(ticker);
  else selectedTickers.delete(ticker);
  updateSelectionUI();
}

function onSelectAllChange() {
  if (!els.selectAll) return;
  if (els.selectAll.checked) {
    lastResults.forEach((r) => selectedTickers.add(r.ticker));
  } else {
    lastResults.forEach((r) => selectedTickers.delete(r.ticker));
  }
  renderTable();
}

function selectedRows() {
  return lastResults.filter((r) => selectedTickers.has(r.ticker));
}

function summariseRow(r) {
  const parts = [
    r.ticker,
    r.name ? `— ${r.name}` : '',
    `$${r.close}`,
    `(${r.pct_change >= 0 ? '+' : ''}${r.pct_change}%)`,
    `RSI ${r.rsi}`,
    `RVol ${r.rel_volume}×`,
  ];
  return parts.filter(Boolean).join(' ');
}

function emailSelected() {
  const rows = selectedRows();
  if (!rows.length) return;
  const subject = `Trading-MA screen: ${rows.length} ticker${rows.length > 1 ? 's' : ''}`;
  const body = [
    `Trading-MA screen results — ${new Date().toISOString().slice(0, 10)}`,
    '',
    ...rows.map(summariseRow),
    '',
  ].join('\n');
  const href = `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  window.location.href = href;
}

async function shareSelected() {
  const rows = selectedRows();
  if (!rows.length) return;
  const text = rows.map(summariseRow).join('\n');
  if (navigator.share) {
    try {
      await navigator.share({ title: 'Trading-MA tickers', text });
      return;
    } catch (_) { /* user cancelled or unsupported */ }
  }
  // SMS fallback first; then clipboard.
  const isMobile = /Android|iPhone|iPad/i.test(navigator.userAgent);
  if (isMobile) {
    const sep = /iPhone|iPad/i.test(navigator.userAgent) ? '&' : '?';
    window.location.href = `sms:${sep}body=${encodeURIComponent(text)}`;
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setStatus('copied to clipboard');
  } catch (_) {
    window.prompt('Copy the tickers below:', text);
  }
}

async function exportSelected() {
  const rows = selectedRows();
  if (!rows.length) return;
  setStatus('exporting…');
  try {
    const res = await fetch('/api/export/xlsx', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows }),
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trading-ma-${new Date().toISOString().slice(0, 10)}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    setStatus('exported');
  } catch (err) {
    console.error(err);
    setStatus('export failed');
  }
}

function clearSelection() {
  if (!selectedTickers.size) return;
  selectedTickers.clear();
  renderTable();
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

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (m) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[m]));
}

// --- hover chart popover --------------------------------------------------
// Hovering a ticker cell opens a small daily chart (price + EMAs + volume on
// pane 0, RSI(14) + 9d SMA on pane 1) anchored next to the cell. Fetched
// payloads are cached per ticker for the session so a second hover is
// instant.

const HOVER_DELAY_MS = 220;
const HOVER_W = 620;
const HOVER_H = 380;
const _chartCache = new Map();
let _hoverChart = null;
let _hoverShowTimer = null;
let _hoverTicker = null;

function disposeHoverChart() {
  if (_hoverChart && _hoverChart.remove) {
    try { _hoverChart.remove(); } catch (_) { /* ignore */ }
  }
  _hoverChart = null;
  if (els.hoverChartContainer) els.hoverChartContainer.innerHTML = '';
}

function hideHoverChart() {
  if (_hoverShowTimer) {
    clearTimeout(_hoverShowTimer);
    _hoverShowTimer = null;
  }
  _hoverTicker = null;
  if (els.hoverChart) els.hoverChart.classList.add('hidden');
  disposeHoverChart();
}

function positionHoverChart(rect) {
  const margin = 12;
  let left = rect.right + margin;
  if (left + HOVER_W > window.innerWidth - margin) {
    left = rect.left - HOVER_W - margin;
  }
  if (left < margin) left = margin;
  let top = rect.top;
  if (top + HOVER_H > window.innerHeight - margin) {
    top = window.innerHeight - HOVER_H - margin;
  }
  if (top < margin) top = margin;
  els.hoverChart.style.left = left + 'px';
  els.hoverChart.style.top = top + 'px';
}

async function showHoverChart(ticker, anchorEl) {
  if (!els.hoverChart || typeof LightweightCharts === 'undefined') return;
  _hoverTicker = ticker;
  els.hoverChartTitle.textContent = ticker;
  els.hoverChartStatus.textContent = 'loading…';
  positionHoverChart(anchorEl.getBoundingClientRect());
  els.hoverChart.classList.remove('hidden');
  disposeHoverChart();
  let payload = _chartCache.get(ticker);
  if (!payload) {
    try {
      const res = await fetch('/api/chart/' + encodeURIComponent(ticker));
      if (!res.ok) throw new Error('HTTP ' + res.status);
      payload = await res.json();
      _chartCache.set(ticker, payload);
    } catch (err) {
      if (_hoverTicker === ticker) {
        els.hoverChartStatus.textContent = 'failed';
      }
      return;
    }
  }
  if (_hoverTicker !== ticker) return; // user moved off before fetch completed
  els.hoverChartStatus.textContent = payload.name || '';
  drawHoverChart(payload);
}

function drawHoverChart(data) {
  const rows = (data.rows || []).filter((r) => r.close !== null);
  if (!rows.length) {
    els.hoverChartStatus.textContent = 'no data';
    return;
  }
  _hoverChart = LightweightCharts.createChart(els.hoverChartContainer, {
    layout: { background: { color: '#161b22' }, textColor: '#c9d1d9' },
    grid: { vertLines: { color: '#22272e' }, horzLines: { color: '#22272e' } },
    rightPriceScale: { borderColor: '#2a313c', minimumWidth: 56 },
    leftPriceScale: { visible: false },
    timeScale: { borderColor: '#2a313c', rightOffset: 2, barSpacing: 4 },
    crosshair: { mode: 1 },
    autoSize: true,
  });

  // Pane 0 — candles + EMA21 + EMA50 + volume overlay
  const candle = _hoverChart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: '#3fb950', downColor: '#f85149',
    wickUpColor: '#3fb950', wickDownColor: '#f85149',
    borderVisible: false,
  }, 0);
  const ema21 = _hoverChart.addSeries(LightweightCharts.LineSeries, {
    color: '#d2a8ff', lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
  }, 0);
  const ema50 = _hoverChart.addSeries(LightweightCharts.LineSeries, {
    color: '#ffa657', lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
  }, 0);
  const vol = _hoverChart.addSeries(LightweightCharts.HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: '',
    color: '#30363d',
    lastValueVisible: false,
    priceLineVisible: false,
  }, 0);
  vol.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

  candle.setData(rows.map((r) => ({
    time: r.time, open: r.open, high: r.high, low: r.low, close: r.close,
  })));
  ema21.setData(rows.filter((r) => r.ema21 != null).map((r) => ({ time: r.time, value: r.ema21 })));
  ema50.setData(rows.filter((r) => r.ema50 != null).map((r) => ({ time: r.time, value: r.ema50 })));
  vol.setData(rows.map((r) => ({
    time: r.time, value: r.volume || 0,
    color: r.close >= r.open ? 'rgba(63,185,80,0.4)' : 'rgba(248,81,73,0.4)',
  })));

  // Pane 1 — RSI(14) + 9d SMA of RSI
  const rsi = _hoverChart.addSeries(LightweightCharts.LineSeries, {
    color: '#58a6ff', lineWidth: 2, priceLineVisible: false,
  }, 1);
  const rsiSma = _hoverChart.addSeries(LightweightCharts.LineSeries, {
    color: '#f0883e', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
  }, 1);
  rsi.setData(rows.filter((r) => r.rsi != null).map((r) => ({ time: r.time, value: r.rsi })));
  rsiSma.setData(rows.filter((r) => r.rsi_sma9 != null).map((r) => ({ time: r.time, value: r.rsi_sma9 })));
  rsi.createPriceLine({ price: 70, color: '#f85149', lineStyle: 2, lineWidth: 1, axisLabelVisible: false });
  rsi.createPriceLine({ price: 30, color: '#3fb950', lineStyle: 2, lineWidth: 1, axisLabelVisible: false });

  // Compress the RSI pane (~25% of plot area). setHeight on the small pane
  // forces pane 0 to absorb the rest.
  const apply = () => {
    try {
      const panes = _hoverChart.panes() || [];
      panes.forEach((p) => {
        try { p.priceScale('right').applyOptions({ minimumWidth: 56 }); } catch (_) {}
      });
      if (panes.length >= 2 && panes[1].setHeight) {
        panes[1].setHeight(80);
      }
    } catch (_) { /* ignore */ }
    try { _hoverChart.timeScale().fitContent(); } catch (_) {}
  };
  apply();
  requestAnimationFrame(apply);
  setTimeout(apply, 80);
}

function onTickerEnter(ev) {
  const cell = ev.target.closest('td[data-ticker]');
  if (!cell) return;
  const ticker = cell.dataset.ticker;
  if (!ticker || _hoverTicker === ticker) return;
  if (_hoverShowTimer) clearTimeout(_hoverShowTimer);
  _hoverShowTimer = setTimeout(() => {
    showHoverChart(ticker, cell);
  }, HOVER_DELAY_MS);
}

function onTickerLeave(ev) {
  const cell = ev.target.closest('td[data-ticker]');
  if (!cell) return;
  const related = ev.relatedTarget;
  if (related && cell.contains(related)) return;
  hideHoverChart();
}

if (els.body) {
  els.body.addEventListener('mouseover', onTickerEnter);
  els.body.addEventListener('mouseout', onTickerLeave);
  els.body.addEventListener('change', onRowCheckboxChange);
}
window.addEventListener('scroll', hideHoverChart, true);

if (els.selectAll) els.selectAll.addEventListener('change', onSelectAllChange);
if (els.emailBtn) els.emailBtn.addEventListener('click', emailSelected);
if (els.shareBtn) els.shareBtn.addEventListener('click', shareSelected);
if (els.exportBtn) els.exportBtn.addEventListener('click', exportSelected);
if (els.clearSelectionBtn) els.clearSelectionBtn.addEventListener('click', clearSelection);
updateSelectionUI();

// --- bootstrap -------------------------------------------------------------

els.runBtn.addEventListener('click', runScreen);

Object.values(toggles).forEach((t) => t && t.addEventListener('change', syncDisabledStates));
syncDisabledStates();

if (els.thead) els.thead.addEventListener('click', onSortHeaderClick);
if (inputs.high_lookback) inputs.high_lookback.addEventListener('input', updateHighHeader);
updateHighHeader();

loadDates();
