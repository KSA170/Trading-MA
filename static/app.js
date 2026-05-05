const $ = (sel) => document.querySelector(sel);

const els = {
  runBtn: $('#run-btn'),
  status: $('#status-text'),
  matchCount: $('#match-count'),
  asOfLabel: $('#as-of-label'),
  body: $('#results-body'),
  thead: document.querySelector('#results-table thead'),
  thHigh: $('#th-high'),
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
  price_dev_min_pct: $('#price_dev_min_pct'),
  price_dev_max_pct: $('#price_dev_max_pct'),
};

const toggles = {
  apply_high: $('#apply_high'),
  apply_rsi: $('#apply_rsi'),
  apply_rsi_dev: $('#apply_rsi_dev'),
  apply_rvol: $('#apply_rvol'),
  apply_price: $('#apply_price'),
  apply_price_dev: $('#apply_price_dev'),
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
  els.body.innerHTML = '<tr class="empty"><td colspan="13">Fetching market data — this may take 30–90s on a cold cache…</td></tr>';
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
    els.body.innerHTML = `<tr class="empty"><td colspan="13">Error: ${err.message}</td></tr>`;
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
    els.body.innerHTML = '<tr class="empty"><td colspan="13">No matches with these filters.</td></tr>';
    return;
  }
  els.body.innerHTML = '';
  for (const r of results) {
    const tr = document.createElement('tr');
    const pctClass = r.pct_change >= 0 ? 'pos' : 'neg';
    const devClass = r.rsi_dev_pct >= 0 ? 'pos' : 'neg';
    const emaDevClass = r.price_ema21_dev_pct >= 0 ? 'pos' : 'neg';
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
      <td class="num">${fmtNum(r.ema21)}</td>
      <td class="num ${emaDevClass}">${r.price_ema21_dev_pct >= 0 ? '+' : ''}${fmtNum(r.price_ema21_dev_pct)}%</td>
      <td class="num">${fmtNum(r.rel_volume)}×</td>
      <td class="num">${fmtVol(r.volume)}</td>
    `;
    els.body.appendChild(tr);
  }
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

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (m) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[m]));
}

// --- bootstrap -------------------------------------------------------------

els.runBtn.addEventListener('click', runScreen);

Object.values(toggles).forEach((t) => t && t.addEventListener('change', syncDisabledStates));
syncDisabledStates();

if (els.thead) els.thead.addEventListener('click', onSortHeaderClick);
if (inputs.high_lookback) inputs.high_lookback.addEventListener('input', updateHighHeader);
updateHighHeader();

loadDates();
