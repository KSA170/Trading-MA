const $ = (sel) => document.querySelector(sel);

const els = {
  runBtn: $('#run-btn'),
  warmBtn: $('#warm-btn'),
  cacheStatus: $('#cache-status'),
  snapshotStatus: $('#snapshot-status'),
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
  copyQuestradeBtn: $('#copy-questrade-btn'),
  exportBtn: $('#export-btn'),
  clearSelectionBtn: $('#clear-selection-btn'),
  diagnoseTicker: $('#diagnose-ticker'),
  diagnoseBtn: $('#diagnose-btn'),
  diagnoseClearBtn: $('#diagnose-clear-btn'),
  diagnoseStatus: $('#diagnose-status'),
  diagnoseOutput: $('#diagnose-output'),
  diagnoseBody: $('#diagnose-body'),
  diagnoseToggle: $('#diagnose-toggle'),
  filtersSection: $('#filters-section'),
  filtersToggle: $('#filters-toggle'),
  historyBody: $('#history-body'),
  historyToggle: $('#history-toggle'),
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
  streak_mode: $('#streak_mode'),
  rsi_min: $('#rsi_min'),
  rsi_max: $('#rsi_max'),
  rsi_dev_min_pct: $('#rsi_dev_min_pct'),
  rsi_dev_max_pct: $('#rsi_dev_max_pct'),
  rvol_lookback: $('#rvol_lookback'),
  rvol_min: $('#rvol_min'),
  avg_volume_min: $('#avg_volume_min'),
  price_min: $('#price_min'),
  price_max: $('#price_max'),
  price_dev_min_pct: $('#price_dev_min_pct'),
  price_dev_max_pct: $('#price_dev_max_pct'),
  ema_dev_min_pct: $('#ema_dev_min_pct'),
  ema_dev_max_pct: $('#ema_dev_max_pct'),
  macd_hist_min: $('#macd_hist_min'),
  turnover_min_pct: $('#turnover_min_pct'),
  turnover_max_pct: $('#turnover_max_pct'),
};

const refreshUniverseBtn = $('#refresh-universe-btn');

const toggles = {
  apply_high: $('#apply_high'),
  apply_rsi: $('#apply_rsi'),
  apply_rsi_dev: $('#apply_rsi_dev'),
  apply_rvol: $('#apply_rvol'),
  apply_avg_volume: $('#apply_avg_volume'),
  apply_price: $('#apply_price'),
  apply_price_dev: $('#apply_price_dev'),
  apply_ema_dev: $('#apply_ema_dev'),
  apply_macd: $('#apply_macd'),
  macd_require_rising: $('#macd_require_rising'),
  apply_turnover: $('#apply_turnover'),
};

const listAllCb = $('#list_all');
const listCheckboxes = Array.from(document.querySelectorAll('input[data-list-key]'));
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

function getSelectedListKeys() {
  return listCheckboxes.filter((cb) => cb.checked).map((cb) => cb.dataset.listKey);
}

// --- cache-status indicator -----------------------------------------------
// Shows next to Run: "cache: 7950/8126 warm" — colour-coded so the user knows
// whether the next screen will be fast (disk) or slow (cold, hits Yahoo).
let _cacheStatusTimer = null;

async function refreshCacheStatus() {
  if (!els.cacheStatus) return;
  const sel = getSelectedListKeys();
  const qs = new URLSearchParams();
  if (sel.length && listCheckboxes.length && sel.length < listCheckboxes.length) {
    qs.set('lists', sel.join(','));
  }
  try {
    const res = await fetch('/api/admin/cache-status?' + qs.toString());
    if (!res.ok) return;
    const s = await res.json();
    if (!s.total) {
      els.cacheStatus.textContent = '';
      els.cacheStatus.classList.remove('warn', 'cold');
      return;
    }
    const pct = Math.round((100 * s.warm) / s.total);
    els.cacheStatus.textContent = `cache: ${s.warm.toLocaleString()}/${s.total.toLocaleString()} warm`;
    els.cacheStatus.classList.toggle('cold', pct < 10);
    els.cacheStatus.classList.toggle('warn', pct >= 10 && pct < 80);
    const tip = pct >= 80
      ? `${pct}% cached — screen will be fast.`
      : `${pct}% cached. A cold run on the rest (~${(s.total - s.warm).toLocaleString()} tickers) hits Yahoo and may take minutes — risks a gateway timeout. Click Warm cache first for a smooth run.`;
    els.cacheStatus.title = tip;
  } catch (_) { /* silent */ }
}

function scheduleCacheStatus(delayMs = 350) {
  if (_cacheStatusTimer) clearTimeout(_cacheStatusTimer);
  _cacheStatusTimer = setTimeout(refreshCacheStatus, delayMs);
}

async function refreshSnapshotStatus() {
  if (!els.snapshotStatus) return;
  try {
    const res = await fetch('/api/admin/snapshot/status');
    if (!res.ok) return;
    const s = await res.json();
    if (!s.enabled) {
      const diag = s.diagnostics || {};
      els.snapshotStatus.textContent = 'snapshot: off';
      els.snapshotStatus.classList.add('cold');
      els.snapshotStatus.classList.remove('warn');
      const reason = diag.init_error || (diag.database_url_set ? 'DB connection failed' : 'DATABASE_URL env var not set on this worker');
      els.snapshotStatus.title = `Snapshot disabled. ${reason}. `
        + `Worker sees: DATABASE_URL=${diag.database_url_set ? 'set' : 'unset'}`
        + (diag.database_url_host ? ` (host=${diag.database_url_host}, scheme=${diag.database_url_scheme})` : '')
        + (diag.driver_error ? ` · driver_error=${diag.driver_error}` : '');
      return;
    }
    const dates = s.available_dates || [];
    if (s.running) {
      const pct = s.total ? Math.round((100 * s.done) / s.total) : 0;
      const tag = s.cancelled ? ' (stopping…)' : '';
      els.snapshotStatus.textContent = `snapshot: writing ${s.done}/${s.total} (${pct}%)${tag} · click to stop`;
      els.snapshotStatus.classList.remove('cold');
      els.snapshotStatus.classList.add('warn');
      els.snapshotStatus.title = 'Snapshot write in progress. Click to cancel.';
      els.snapshotStatus.style.cursor = 'pointer';
      setTimeout(refreshSnapshotStatus, 4000);
      return;
    }
    els.snapshotStatus.style.cursor = 'pointer';
    const ran = !!(s.finished_at && s.started_at);
    const wrote = s.last_written || 0;

    // Latest run wrote 0 rows: foreground the skip breakdown right in
    // the pill text so the user can see *why* without hovering.
    if (ran && wrote === 0) {
      const skipParts = [
        ['missing', s.skipped_missing],
        ['stale', s.skipped_stale],
        ['unenriched', s.skipped_unenriched],
        ['corrupt', s.skipped_corrupt],
        ['short', s.skipped_short],
      ].filter(([, n]) => n > 0).map(([k, n]) => `${k}=${n.toLocaleString()}`);
      const skipTxt = skipParts.length ? ` (${skipParts.join(', ')})` : '';
      const errTxt = s.last_error ? ' · DB error' : '';
      els.snapshotStatus.textContent = `snapshot: 0 rows${skipTxt}${errTxt} · click to retry`;
      els.snapshotStatus.classList.remove('warn');
      els.snapshotStatus.classList.add('cold');
      const lines = [
        `Last run wrote 0 rows. Processed ${s.done}/${s.total} pickles.`,
        skipParts.length ? `Skipped: ${skipParts.join(', ')}` : '',
        s.last_error ? `DB error: ${s.last_error}` : '',
      ].filter(Boolean);
      els.snapshotStatus.title = lines.join(' · ');
      return;
    }

    if (!dates.length) {
      els.snapshotStatus.textContent = 'snapshot: empty · click to write';
      els.snapshotStatus.classList.remove('warn');
      els.snapshotStatus.classList.add('cold');
      els.snapshotStatus.title = 'No snapshot rows yet. Click to write the current pickle cache to the DB.';
      return;
    }
    const latest = dates[0];
    const wroteTxt = `, ${wrote.toLocaleString()} rows`;
    els.snapshotStatus.textContent = `snapshot: ${latest}${wroteTxt} · click to refresh`;
    els.snapshotStatus.classList.remove('cold', 'warn');
    els.snapshotStatus.title = `Snapshot dates: ${dates.join(', ')}. Retention: ${s.retention_days} days. Click to write a fresh snapshot from the current pickle cache.`;
  } catch (_) { /* silent */ }
}

function buildQuery() {
  const params = new URLSearchParams();
  for (const [k, el] of Object.entries(inputs)) {
    params.set(k, el.value);
  }
  for (const [k, el] of Object.entries(toggles)) {
    params.set(k, el.checked ? '1' : '0');
  }
  const selectedLists = getSelectedListKeys();
  if (listCheckboxes.length && selectedLists.length < listCheckboxes.length) {
    // Subset (or none) selected — send the explicit list. Empty string tells
    // the backend "no lists" (returns no candidates); the UI normally
    // disables the Run button before this can happen.
    params.set('lists', selectedLists.join(','));
  }
  if (asOfSelect) {
    params.set('as_of_offset', asOfSelect.value || '0');
  }
  return params.toString();
}

function updateListAllState() {
  if (!listAllCb || !listCheckboxes.length) return;
  const total = listCheckboxes.length;
  const checked = listCheckboxes.filter((cb) => cb.checked).length;
  listAllCb.checked = checked === total;
  listAllCb.indeterminate = checked > 0 && checked < total;
  // Disable Run if nothing is selected — empty universe is not a useful screen.
  if (els.runBtn) {
    if (checked === 0) {
      els.runBtn.disabled = true;
      els.runBtn.title = 'Select at least one list / exchange';
    } else {
      els.runBtn.disabled = false;
      els.runBtn.title = '';
    }
  }
}

function onListAllChange() {
  if (!listAllCb) return;
  const checked = listAllCb.checked;
  listCheckboxes.forEach((cb) => { cb.checked = checked; });
  updateListAllState();
}

function syncDisabledStates() {
  const map = {
    apply_high: 'high',
    apply_rsi: 'rsi',
    apply_rsi_dev: 'rsi_dev',
    apply_rvol: 'rvol',
    apply_avg_volume: 'avg_volume',
    apply_price: 'price',
    apply_price_dev: 'price_dev',
    apply_ema_dev: 'ema_dev',
    apply_macd: 'macd',
    apply_turnover: 'turnover',
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
      const head = i === 0 ? `${d.date} (latest)` : d.date;
      // Only flag snapshot-backed dates explicitly — historical dates
      // outside the snapshot window just show the bare date.
      const tag = d.in_snapshot ? ' • snapshot' : '';
      opt.textContent = head + tag;
      opt.title = d.in_snapshot
        ? 'Served from the Postgres snapshot — fast.'
        : '';
      asOfSelect.appendChild(opt);
    });
  } catch (err) {
    console.warn('date list load failed:', err);
  }
}

let _screenAbort = null;

function setRunButtonState(running) {
  if (!els.runBtn) return;
  if (running) {
    els.runBtn.textContent = 'Stop';
    els.runBtn.classList.remove('primary');
    els.runBtn.classList.add('warn');
  } else {
    els.runBtn.textContent = 'Run screen';
    els.runBtn.classList.add('primary');
    els.runBtn.classList.remove('warn');
  }
}

async function runScreen() {
  if (_screenAbort) {
    // Already running — second click acts as Stop.
    _screenAbort.abort();
    return;
  }
  _screenAbort = new AbortController();
  setRunButtonState(true);
  setStatus('running…');
  els.body.innerHTML = '<tr class="empty"><td colspan="18">Fetching market data — this may take 30–90s on a cold cache…</td></tr>';
  els.matchCount.textContent = '';
  if (els.asOfLabel) els.asOfLabel.textContent = '';
  updateHighHeader();
  try {
    const res = await fetch('/api/screen?' + buildQuery(), { signal: _screenAbort.signal });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    lastResults = data.results || [];
    renderTable();
    if (els.asOfLabel) {
      const d = data.as_of_date || (asOfSelect && asOfSelect.options[asOfSelect.selectedIndex]?.text) || '';
      els.asOfLabel.textContent = d ? `as of ${d}` : '';
    }
    setStatus(data.cached ? 'cached' : `done in ${data.elapsed_sec || '?'}s`);
    if (asOfSelect && asOfSelect.options.length <= 1) loadDates();
    // Record this run for the match-history panel (no-op when 0 hits).
    if (data.params) recordHistory(data, data.params);
  } catch (err) {
    if (err && err.name === 'AbortError') {
      setStatus('stopped');
      els.body.innerHTML = '<tr class="empty"><td colspan="18">Stopped.</td></tr>';
    } else {
      console.error(err);
      setStatus('error');
      els.body.innerHTML = `<tr class="empty"><td colspan="18">Error: ${err.message}</td></tr>`;
    }
  } finally {
    _screenAbort = null;
    setRunButtonState(false);
    scheduleCacheStatus();  // a run warmed many ticker files; reflect that
  }
}

function updateHighHeader() {
  if (!els.thHigh) return;
  const n = parseInt(inputs.high_lookback.value, 10);
  const mode = inputs.streak_mode ? inputs.streak_mode.value : 'high';
  const suffix = mode === 'close' ? 'HC'
    : mode === 'green' ? 'green'
    : mode === 'close_green' ? 'HC+G'
    : 'HH';
  els.thHigh.textContent = (Number.isFinite(n) && n > 0) ? `${n}d ${suffix}` : suffix;
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
    els.body.innerHTML = '<tr class="empty"><td colspan="18">No matches with these filters.</td></tr>';
    return;
  }
  els.body.innerHTML = '';
  for (const r of results) {
    const tr = document.createElement('tr');
    const pctClass = r.pct_change >= 0 ? 'pos' : 'neg';
    const devClass = r.rsi_dev_pct >= 0 ? 'pos' : 'neg';
    const emaDevClass = r.price_ema21_dev_pct >= 0 ? 'pos' : 'neg';
    const emaCrossClass = r.ema21_ema50_dev_pct >= 0 ? 'pos' : 'neg';
    const macdHistClass = r.macd_hist >= 0 ? 'pos' : 'neg';
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
      <td class="num ${macdHistClass}">${fmtNum(r.macd_hist, 4)}</td>
      <td class="num">${fmtNum(r.rel_volume)}×</td>
      <td class="num">${fmtVol(r.volume)}</td>
      <td class="num" title="${r.market_cap ? 'mkt cap ' + fmtVol(r.market_cap) : 'shares outstanding unknown'}">${r.turnover_pct == null ? '—' : fmtNum(r.turnover_pct, 2) + '%'}</td>
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
  [els.emailBtn, els.shareBtn, els.copyQuestradeBtn, els.exportBtn, els.clearSelectionBtn].forEach((b) => {
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

async function copyForQuestrade() {
  const rows = selectedRows();
  if (!rows.length) return;
  // Questrade Pro accepts pasted ticker lists in its watchlist input.
  // .TO suffix is preserved for Canadian names — Questrade resolves it
  // to the TSX listing automatically.
  const text = rows.map((r) => r.ticker).join('\n');
  try {
    await navigator.clipboard.writeText(text);
    setStatus(`copied ${rows.length} ticker${rows.length > 1 ? 's' : ''} for Questrade`);
  } catch (_) {
    window.prompt(`Copy the tickers below, then paste into Questrade Pro's watchlist input:`, text);
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

function clearDiagnose() {
  if (els.diagnoseOutput) {
    els.diagnoseOutput.classList.add('hidden');
    els.diagnoseOutput.innerHTML = '';
  }
  if (els.diagnoseStatus) els.diagnoseStatus.textContent = '';
  if (els.diagnoseTicker) els.diagnoseTicker.value = '';
  if (els.diagnoseClearBtn) els.diagnoseClearBtn.disabled = true;
}

// --- collapsible sections (filters, diagnose) ----------------------------

function wireCollapse(toggleBtn, targets, storageKey) {
  if (!toggleBtn) return;
  const arr = (Array.isArray(targets) ? targets : [targets]).filter(Boolean);
  const apply = (collapsed) => {
    toggleBtn.classList.toggle('collapsed', collapsed);
    toggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    arr.forEach((el) => el.classList.toggle('collapsed-section', collapsed));
  };
  apply(localStorage.getItem(storageKey) === '1');
  toggleBtn.addEventListener('click', () => {
    const next = !toggleBtn.classList.contains('collapsed');
    apply(next);
    try { localStorage.setItem(storageKey, next ? '1' : '0'); } catch (_) {}
  });
}

async function runDiagnose() {
  if (!els.diagnoseTicker) return;
  const ticker = (els.diagnoseTicker.value || '').trim().toUpperCase();
  if (!ticker) {
    els.diagnoseStatus.textContent = 'enter a ticker';
    return;
  }
  els.diagnoseStatus.textContent = 'checking…';
  els.diagnoseOutput.classList.add('hidden');
  try {
    const res = await fetch('/api/debug/' + encodeURIComponent(ticker) + '?' + buildQuery());
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    renderDiagnose(data);
    els.diagnoseStatus.textContent = '';
    if (els.diagnoseClearBtn) els.diagnoseClearBtn.disabled = false;
  } catch (err) {
    console.error(err);
    els.diagnoseStatus.textContent = 'error: ' + err.message;
  }
}

function renderDiagnose(d) {
  const out = els.diagnoseOutput;
  if (!out) return;
  out.classList.remove('hidden');
  const pillClass = d.all_pass ? 'pass' : 'fail';
  const header = `
    <div class="diagnose-header">
      <strong>${escapeHtml(d.ticker)}</strong>
      ${d.in_universe ? `<span class="pill">in universe: ${escapeHtml((d.lists || []).join(', ') || 'yes')}</span>` : '<span class="pill" style="color:var(--red)">NOT in universe</span>'}
      ${d.as_of_date ? `<span class="pill">as of ${escapeHtml(d.as_of_date)}</span>` : ''}
      ${d.data_bars ? `<span class="pill">${d.data_bars} bars</span>` : ''}
      <span class="pill" style="color:var(${d.all_pass ? '--green' : '--red'})">${d.all_pass ? 'all checks pass' : 'rejected'}</span>
    </div>
  `;
  if (d.error) {
    out.innerHTML = header + `<div style="color:var(--red)">${escapeHtml(d.error)}</div>`;
    return;
  }
  const fmt = (v) => (v === null || v === undefined) ? '—' : (typeof v === 'number' ? Number(v).toLocaleString(undefined, { maximumFractionDigits: 4 }) : String(v));
  const checks = (d.checks || []).map((c) => {
    const cls = !c.applied ? 'skip' : (c.pass ? 'pass' : 'fail');
    let extras = '';
    if (c.extra) {
      const parts = Object.entries(c.extra).slice(0, 4).map(([k, v]) => {
        if (Array.isArray(v)) {
          return `${k}=[${v.slice(0, 6).map(fmt).join(', ')}${v.length > 6 ? '…' : ''}]`;
        }
        return `${k}=${fmt(v)}`;
      });
      extras = parts.length ? ` <span class="ext">${escapeHtml(parts.join(' · '))}</span>` : '';
    }
    const bandTxt = c.band ? ` <span class="ext">band [${fmt(c.band[0])}, ${c.band[1] === null ? '∞' : fmt(c.band[1])}]</span>` : '';
    const status = !c.applied ? 'OFF' : (c.pass ? '✓' : '✗');
    return `
      <div class="diagnose-check ${cls}">
        <span class="name">${status} ${escapeHtml(c.label)}${bandTxt}${extras}</span>
        <span class="val">${fmt(c.value)}</span>
      </div>
    `;
  }).join('');
  out.innerHTML = header + `<div class="diagnose-checks">${checks}</div>`;
}

// --- warm-cache button + status polling ----------------------------------

let _warmPollTimer = null;
let _warmIsRunning = false;

function setWarmButtonState(running) {
  if (!els.warmBtn) return;
  _warmIsRunning = !!running;
  els.warmBtn.textContent = running ? 'Stop warming' : 'Warm cache';
  els.warmBtn.classList.toggle('warn', !!running);
  els.warmBtn.disabled = false;  // we never grey it out — it just changes role
}

async function pollWarmStatus() {
  try {
    const res = await fetch('/api/admin/warm-status');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const s = await res.json();
    if (s.running) {
      const pct = s.total ? Math.round((100 * s.done) / s.total) : 0;
      const tag = s.cancelled ? ' (stopping…)' : '';
      setStatus(`warming cache… ${s.done}/${s.total} (${pct}%)${tag}`);
      setWarmButtonState(true);
      _warmPollTimer = setTimeout(pollWarmStatus, 3000);
    } else {
      setWarmButtonState(false);
      scheduleCacheStatus(100);  // cache just got warm — refresh indicator
      // The post-warm snapshot fires ~immediately and takes ~30s on a warm
      // universe; poll a couple of times so the indicator updates.
      refreshSnapshotStatus();
      setTimeout(refreshSnapshotStatus, 10000);
      setTimeout(refreshSnapshotStatus, 45000);
      if (s.total) {
        const dur = s.finished_at && s.started_at
          ? Math.round(s.finished_at - s.started_at) + 's'
          : '';
        const errs = s.errors ? `, ${s.errors} errors` : '';
        const verb = s.cancelled ? 'cancelled' : 'warmed';
        setStatus(`cache ${verb}: ${s.done}/${s.total}${errs}${dur ? ` in ${dur}` : ''}`);
      }
    }
  } catch (err) {
    setWarmButtonState(false);
    console.warn('warm-status poll failed:', err);
  }
}

async function warmCache() {
  if (!els.warmBtn) return;
  if (_warmIsRunning) {
    // Second click → cancel.
    setStatus('stopping warm cache…');
    try {
      await fetch('/api/admin/warm-cache/cancel', { method: 'POST' });
    } catch (_) { /* the next poll will reflect reality */ }
    return;
  }
  setStatus('starting warm cache…');
  try {
    const res = await fetch('/api/admin/warm-cache', { method: 'POST' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    await res.json();
    setWarmButtonState(true);
    pollWarmStatus();
  } catch (err) {
    setStatus('warm cache failed: ' + err.message);
    setWarmButtonState(false);
  }
}

async function refreshUniverse() {
  if (!refreshUniverseBtn) return;
  refreshUniverseBtn.disabled = true;
  setStatus('refreshing universe…');
  try {
    const res = await fetch('/api/admin/refresh-universe', { method: 'POST' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const sizes = data.sizes || {};
    const summary = Object.entries(sizes).map(([k, v]) => `${k}=${v}`).join(', ');
    const errs = data.errors || {};
    const errParts = Object.entries(errs).map(([file, msg]) => `${file}: ${msg}`);
    if (errParts.length) {
      setStatus(`universe refreshed (${summary}) — fetch errors: ${errParts.join('; ')}`);
      console.warn('refresh-universe fetch errors:', errs);
    } else {
      setStatus(`universe refreshed (${summary})`);
    }
  } catch (err) {
    console.error(err);
    setStatus('refresh failed');
  } finally {
    refreshUniverseBtn.disabled = false;
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
if (els.copyQuestradeBtn) els.copyQuestradeBtn.addEventListener('click', copyForQuestrade);
if (els.exportBtn) els.exportBtn.addEventListener('click', exportSelected);
if (els.clearSelectionBtn) els.clearSelectionBtn.addEventListener('click', clearSelection);
if (els.diagnoseBtn) els.diagnoseBtn.addEventListener('click', runDiagnose);
if (els.diagnoseClearBtn) els.diagnoseClearBtn.addEventListener('click', clearDiagnose);
if (els.diagnoseTicker) {
  els.diagnoseTicker.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); runDiagnose(); }
  });
}

// Collapse / expand the filter and diagnose sections, persisted in
// localStorage so the user's preference survives reloads.
wireCollapse(els.filtersToggle, els.filtersSection, 'collapse_filters');
wireCollapse(els.historyToggle, els.historyBody, 'collapse_history');
renderHistory();
wireCollapse(
  els.diagnoseToggle,
  [els.diagnoseBody, els.diagnoseOutput],
  'collapse_diagnose'
);

updateSelectionUI();

// --- match history (last 5 successful runs) -------------------------------
// Persisted in localStorage so it survives reloads. Each entry stores the
// full filter params + the result rows so "Restore" can put a past run
// back into the table without re-running the screen.

const HISTORY_KEY = 'match_history_v1';
const HISTORY_MAX = 5;

// Subset of the params dict that's actually filter-relevant (everything
// except the lists tuple, which we render separately for readability).
const HISTORY_PARAM_KEYS = [
  'high_lookback', 'streak_mode',
  'rsi_min', 'rsi_max', 'rsi_dev_min_pct', 'rsi_dev_max_pct',
  'price_min', 'price_max', 'price_dev_min_pct', 'price_dev_max_pct',
  'ema_dev_min_pct', 'ema_dev_max_pct',
  'macd_hist_min', 'macd_require_rising',
  'rvol_lookback', 'rvol_min', 'avg_volume_min',
  'turnover_min_pct', 'turnover_max_pct',
  'apply_high', 'apply_rsi', 'apply_rsi_dev', 'apply_rvol', 'apply_avg_volume',
  'apply_price', 'apply_price_dev', 'apply_ema_dev', 'apply_macd', 'apply_turnover',
  'as_of_offset',
];

function loadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch (_) {
    return [];
  }
}

function saveHistory(entries) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, HISTORY_MAX)));
  } catch (err) {
    // quotaExceeded most likely — drop the oldest entry and retry once.
    if (entries.length > 1) {
      try { localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, entries.length - 1))); } catch (_) {}
    }
  }
}

function recordHistory(data, params) {
  const results = data.results || [];
  if (!results.length) return;  // only successful runs with matches
  const entry = {
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    ranAt: new Date().toISOString(),
    asOfDate: data.as_of_date || null,
    matchCount: results.length,
    params: pickParams(params || {}),
    results: results,
  };
  const existing = loadHistory();
  existing.unshift(entry);
  saveHistory(existing.slice(0, HISTORY_MAX));
  renderHistory();
}

function pickParams(p) {
  const out = {};
  for (const k of HISTORY_PARAM_KEYS) {
    if (p[k] !== undefined) out[k] = p[k];
  }
  if (Array.isArray(p.lists)) out.lists = p.lists.slice();
  return out;
}

function fmtParamValue(k, v) {
  if (Array.isArray(v)) return v.join(', ') || '(all)';
  if (typeof v === 'boolean') return v ? 'on' : 'off';
  if (typeof v === 'number') {
    return Number.isInteger(v) ? String(v) : (v.toLocaleString(undefined, { maximumFractionDigits: 3 }));
  }
  return String(v);
}

function renderHistory() {
  if (!els.historyBody) return;
  const entries = loadHistory();
  if (!entries.length) {
    els.historyBody.innerHTML = '<p class="muted history-empty">No runs yet — successful screens will be saved here automatically.</p>';
    return;
  }
  els.historyBody.innerHTML = '';
  for (const e of entries) {
    const div = document.createElement('div');
    div.className = 'history-entry';
    div.dataset.id = e.id;
    const ts = new Date(e.ranAt);
    const tsTxt = ts.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
    const asOf = e.asOfDate ? `<span class="muted">as of ${escapeHtml(e.asOfDate)}</span>` : '';
    div.innerHTML = `
      <div class="entry-meta">
        <span class="entry-time">${escapeHtml(tsTxt)}</span>
        ${asOf}
        <span class="entry-count">${e.matchCount} match${e.matchCount === 1 ? '' : 'es'}</span>
        <button class="entry-restore" type="button">Restore</button>
        <button class="entry-toggle-filters" type="button">Show filters</button>
        <button class="entry-delete" type="button" title="Delete this entry">×</button>
      </div>
      <div class="entry-filters hidden"></div>
    `;
    els.historyBody.appendChild(div);
  }
}

function entryFromEvent(ev) {
  const node = ev.target.closest('.history-entry');
  if (!node) return null;
  const id = node.dataset.id;
  const all = loadHistory();
  const idx = all.findIndex((e) => e.id === id);
  return { node, id, idx, entry: all[idx], all };
}

if (els.historyBody) {
  els.historyBody.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button');
    if (!btn) return;
    const ctx = entryFromEvent(ev);
    if (!ctx || !ctx.entry) return;
    if (btn.classList.contains('entry-restore')) {
      lastResults = ctx.entry.results || [];
      renderTable();
      if (els.matchCount) els.matchCount.textContent = `(${lastResults.length})`;
      if (els.asOfLabel) {
        els.asOfLabel.textContent = ctx.entry.asOfDate ? `as of ${ctx.entry.asOfDate}` : '';
      }
      setStatus(`restored ${lastResults.length} matches from ${new Date(ctx.entry.ranAt).toLocaleString()}`);
    } else if (btn.classList.contains('entry-toggle-filters')) {
      const panel = ctx.node.querySelector('.entry-filters');
      if (!panel) return;
      const hidden = panel.classList.toggle('hidden');
      btn.textContent = hidden ? 'Show filters' : 'Hide filters';
      if (!hidden && !panel.dataset.filled) {
        const p = ctx.entry.params || {};
        const rows = HISTORY_PARAM_KEYS
          .filter((k) => k in p)
          .map((k) => `<div><span class="k">${escapeHtml(k)}</span>: ${escapeHtml(fmtParamValue(k, p[k]))}</div>`);
        if (p.lists) rows.unshift(`<div><span class="k">lists</span>: ${escapeHtml(fmtParamValue('lists', p.lists))}</div>`);
        panel.innerHTML = rows.join('');
        panel.dataset.filled = '1';
      }
    } else if (btn.classList.contains('entry-delete')) {
      ctx.all.splice(ctx.idx, 1);
      saveHistory(ctx.all);
      renderHistory();
    }
  });
}


// --- bootstrap -------------------------------------------------------------

els.runBtn.addEventListener('click', runScreen);

Object.values(toggles).forEach((t) => t && t.addEventListener('change', syncDisabledStates));
syncDisabledStates();

if (els.thead) els.thead.addEventListener('click', onSortHeaderClick);
if (inputs.high_lookback) inputs.high_lookback.addEventListener('input', updateHighHeader);
if (inputs.streak_mode) inputs.streak_mode.addEventListener('change', updateHighHeader);
updateHighHeader();

if (listAllCb) listAllCb.addEventListener('change', onListAllChange);
listCheckboxes.forEach((cb) => cb.addEventListener('change', () => {
  updateListAllState();
  scheduleCacheStatus();
}));
if (listAllCb) listAllCb.addEventListener('change', () => scheduleCacheStatus());
// Initial cache snapshot.
scheduleCacheStatus(50);
refreshSnapshotStatus();
updateListAllState();

if (refreshUniverseBtn) refreshUniverseBtn.addEventListener('click', refreshUniverse);
if (els.warmBtn) els.warmBtn.addEventListener('click', warmCache);
if (els.snapshotStatus) {
  els.snapshotStatus.addEventListener('click', async () => {
    // Cancel if currently writing; otherwise trigger a fresh snapshot
    // of whatever's already on disk (no Yahoo refetch).
    const txt = (els.snapshotStatus.textContent || '');
    const isWriting = txt.includes('writing');
    const url = isWriting ? '/api/admin/snapshot/cancel' : '/api/admin/snapshot';
    // Immediate visual feedback so the user knows the click registered
    // — without this, a POST that takes >50ms looks like nothing happened.
    els.snapshotStatus.textContent = isWriting ? 'snapshot: stopping…' : 'snapshot: starting…';
    els.snapshotStatus.classList.add('warn');
    els.snapshotStatus.classList.remove('cold');
    try {
      const res = await fetch(url, { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok && res.status !== 400) {
        els.snapshotStatus.textContent = `snapshot: HTTP ${res.status}`;
        els.snapshotStatus.classList.add('cold');
        els.snapshotStatus.classList.remove('warn');
        return;
      }
      if (data && data.error) {
        els.snapshotStatus.textContent = `snapshot: ${data.error}`;
        els.snapshotStatus.classList.add('cold');
        els.snapshotStatus.classList.remove('warn');
        return;
      }
      // Pick up the new running state on the next tick.
      setTimeout(refreshSnapshotStatus, 400);
    } catch (err) {
      els.snapshotStatus.textContent = 'snapshot: network error';
      els.snapshotStatus.classList.add('cold');
      els.snapshotStatus.classList.remove('warn');
      console.warn('snapshot click action failed:', err);
    }
  });
}
// If a warm job is already running (page reload mid-warm), pick up its
// progress.
fetch('/api/admin/warm-status').then((r) => r.json()).then((s) => {
  if (s && s.running) pollWarmStatus();
}).catch(() => {});

loadDates();
