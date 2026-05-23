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
  selectAll: $('#select-all'),
  selectionCount: $('#selection-count'),
  emailBtn: $('#email-btn'),
  shareBtn: $('#share-btn'),
  exportTvBtn: $('#export-tv-btn'),
  alertsAddBtn: $('#alerts-add-btn'),
  saveHistoryBtn: $('#save-history-btn'),
  exportBtn: $('#export-btn'),
  clearSelectionBtn: $('#clear-selection-btn'),
  columnsBtn: $('#columns-btn'),
  columnMenu: $('#column-menu'),
  exchangeDdBtn: $('#exchange-dd-btn'),
  exchangeDdMenu: $('#exchange-dd-menu'),
  alertsToggle: $('#alerts-toggle'),
  alertsBody: $('#alerts-body'),
  alertsStatus: $('#alerts-status'),
  alertsWatchlist: $('#alerts-watchlist'),
  rulesToggle: $('#rules-toggle'),
  rulesBody: $('#rules-body'),
  rulesList: $('#rules-list'),
  rulesClassifyNote: $('#rules-classify-note'),
  ruleName: $('#rule-name'),
  ruleScopeType: $('#rule-scope-type'),
  ruleScopeValue: $('#rule-scope-value'),
  ruleCreateBtn: $('#rule-create-btn'),
  rulesMsg: $('#rules-msg'),
  diagnoseTicker: $('#diagnose-ticker'),
  diagnoseBtn: $('#diagnose-btn'),
  diagnoseClearBtn: $('#diagnose-clear-btn'),
  diagnoseStatus: $('#diagnose-status'),
  diagnoseOutput: $('#diagnose-output'),
  diagnoseBody: $('#diagnose-body'),
  diagnoseToggle: $('#diagnose-toggle'),
  filtersSection: $('#filters-section'),
  filtersToggle: $('#filters-toggle'),
  saveDefaultsBtn: $('#save-defaults-btn'),
  resetDefaultsBtn: $('#reset-defaults-btn'),
  defaultsMsg: $('#defaults-msg'),
  historyBody: $('#history-body'),
  historyToggle: $('#history-toggle'),
  setupsToggle: $('#setups-toggle'),
  setupsBody: $('#setups-body'),
  setupsList: $('#setups-list'),
  setupsStatus: $('#setups-status'),
  setupsMinScore: $('#setups-min-score'),
  setupsMinPrice: $('#setups-min-price'),
  setupsMaxPrice: $('#setups-max-price'),
  setupsMinDollarVol: $('#setups-min-dollar-vol'),
  setupsLimit: $('#setups-limit'),
  setupsRunBtn: $('#setups-run-btn'),
  setupsSelectionToolbar: $('#setups-selection-toolbar'),
  setupsSelectAll: $('#setups-select-all'),
  setupsSelectionCount: $('#setups-selection-count'),
  setupsAddWatchlistBtn: $('#setups-add-watchlist-btn'),
  setupsExportTvBtn: $('#setups-export-tv-btn'),
  setupsShareBtn: $('#setups-share-btn'),
  setupsClearSelectionBtn: $('#setups-clear-selection-btn'),
  hoverChart: $('#hover-chart'),
  hoverChartTitle: $('#hover-chart-title'),
  hoverChartStatus: $('#hover-chart-status'),
  hoverChartContainer: $('#hover-chart-container'),
};

const selectedTickers = new Set();

let lastResults = [];
let lastRunData = null;  // the most recent /api/screen response — for "Save to history"
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
    const skipParts = [
      ['missing', s.skipped_missing],
      ['stale', s.skipped_stale],
      ['unenriched', s.skipped_unenriched],
      ['corrupt', s.skipped_corrupt],
      ['short', s.skipped_short],
      ['row_none', s.skipped_row_none],
    ].filter(([, n]) => n > 0).map(([k, n]) => `${k}=${n.toLocaleString()}`);
    if (ran && wrote === 0) {
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
    const counts = s.date_counts || [];
    const latestEntry = counts.find((d) => d.date === latest);
    // Show the real number of rows in the DB for the date — not
    // last_written, which only reflects the most recent write run.
    const dbRows = latestEntry ? latestEntry.rows : wrote;
    els.snapshotStatus.textContent = `snapshot: ${latest}, ${dbRows.toLocaleString()} rows · click to refresh`;
    els.snapshotStatus.classList.remove('cold', 'warn');
    const byDate = counts.map((d) => `${d.date}=${d.rows.toLocaleString()}`).join(', ');
    const skipTip = skipParts.length ? ` Skipped on last run: ${skipParts.join(', ')}.` : '';
    els.snapshotStatus.title = `Rows in DB by date: ${byDate || '(none)'}. `
      + `Last write run added ${wrote.toLocaleString()} rows.${skipTip} `
      + `Retention: ${s.retention_days} days. `
      + `Click to write a fresh snapshot from the current pickle cache.`;
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

function updateExchangeDdLabel() {
  if (!els.exchangeDdBtn || !listCheckboxes.length) return;
  const total = listCheckboxes.length;
  const checked = listCheckboxes.filter((cb) => cb.checked).length;
  els.exchangeDdBtn.textContent = checked === 0 ? 'No exchanges'
    : checked === total ? 'All exchanges'
    : `${checked} of ${total} exchanges`;
}

function updateListAllState() {
  if (!listAllCb || !listCheckboxes.length) return;
  const total = listCheckboxes.length;
  const checked = listCheckboxes.filter((cb) => cb.checked).length;
  listAllCb.checked = checked === total;
  listAllCb.indeterminate = checked > 0 && checked < total;
  updateExchangeDdLabel();
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

// --- saved filter defaults ------------------------------------------------
// Snapshot the current filter values, group toggles and exchange selection
// so they auto-load on the next visit. Stored in localStorage — the app
// has no per-user server account.

const FILTER_DEFAULTS_KEY = 'filter_defaults_v1';

function setDefaultsMsg(text, kind) {
  if (!els.defaultsMsg) return;
  els.defaultsMsg.textContent = text || '';
  els.defaultsMsg.style.color = kind === 'error' ? 'var(--red)'
    : kind === 'ok' ? 'var(--green)' : '';
}

function collectFilterState() {
  const state = { inputs: {}, toggles: {}, exchanges: [] };
  for (const [k, el] of Object.entries(inputs)) {
    if (el) state.inputs[k] = el.value;
  }
  for (const [k, el] of Object.entries(toggles)) {
    if (el) state.toggles[k] = el.checked;
  }
  state.exchanges = listCheckboxes.filter((cb) => cb.checked).map((cb) => cb.dataset.listKey);
  return state;
}

function applyFilterState(state) {
  if (!state || typeof state !== 'object') return;
  for (const [k, v] of Object.entries(state.inputs || {})) {
    if (inputs[k] != null && v != null) inputs[k].value = v;
  }
  for (const [k, v] of Object.entries(state.toggles || {})) {
    if (toggles[k] != null) toggles[k].checked = !!v;
  }
  if (Array.isArray(state.exchanges)) {
    const want = new Set(state.exchanges);
    listCheckboxes.forEach((cb) => { cb.checked = want.has(cb.dataset.listKey); });
  }
  syncDisabledStates();
  updateListAllState();
  updateHighHeader();
}

function saveFilterDefaults() {
  try {
    localStorage.setItem(FILTER_DEFAULTS_KEY, JSON.stringify(collectFilterState()));
    setDefaultsMsg('Saved — these filters will load automatically next visit.', 'ok');
  } catch (_) {
    setDefaultsMsg('Could not save (browser storage unavailable).', 'error');
  }
}

function loadFilterDefaults() {
  try {
    const raw = localStorage.getItem(FILTER_DEFAULTS_KEY);
    if (!raw) return;
    applyFilterState(JSON.parse(raw));
  } catch (_) { /* ignore corrupt saved state */ }
}

function resetFilterDefaults() {
  try { localStorage.removeItem(FILTER_DEFAULTS_KEY); } catch (_) {}
  // The built-in defaults are the HTML `value=` attributes — a reload
  // restores them cleanly.
  location.reload();
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
  els.body.innerHTML = `<tr class="empty"><td colspan="${emptyColspan()}">Fetching market data — this may take 30–90s on a cold cache…</td></tr>`;
  els.matchCount.textContent = '';
  if (els.asOfLabel) els.asOfLabel.textContent = '';
  updateHighHeader();
  try {
    const res = await fetch('/api/screen?' + buildQuery(), { signal: _screenAbort.signal });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    lastResults = data.results || [];
    lastRunData = data;  // kept for "Save to history" — see saveSelectionToHistory
    renderTable();
    if (els.asOfLabel) {
      const d = data.as_of_date || (asOfSelect && asOfSelect.options[asOfSelect.selectedIndex]?.text) || '';
      els.asOfLabel.textContent = d ? `as of ${d}` : '';
    }
    setStatus(data.cached ? 'cached' : `done in ${data.elapsed_sec || '?'}s`);
    if (asOfSelect && asOfSelect.options.length <= 1) loadDates();
  } catch (err) {
    if (err && err.name === 'AbortError') {
      setStatus('stopped');
      els.body.innerHTML = `<tr class="empty"><td colspan="${emptyColspan()}">Stopped.</td></tr>`;
    } else {
      console.error(err);
      setStatus('error');
      els.body.innerHTML = `<tr class="empty"><td colspan="${emptyColspan()}">Error: ${err.message}</td></tr>`;
    }
  } finally {
    _screenAbort = null;
    setRunButtonState(false);
    scheduleCacheStatus();  // a run warmed many ticker files; reflect that
  }
}

// The high-lookback column's header label is dynamic (e.g. "3d HC"),
// so a streak-input change just re-renders the header.
function updateHighHeader() {
  renderHeader();
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

// --- table columns (show / hide / reorder) --------------------------------
// Columns are data-driven so the user can hide them and drag-reorder them.
// The leading checkbox column is fixed and not part of this list. The order
// array and hidden-key set persist in localStorage.

const COLUMN_DEFS = [
  { key: 'ticker', label: 'Ticker', type: 'text',
    title: 'Stock ticker symbol. Hover a ticker in a row to pop up its price chart. Click the header to sort; drag it to reorder columns.',
    render: (r) => `<td data-ticker="${escapeHtml(r.ticker)}"><strong>${escapeHtml(r.ticker)}</strong></td>` },
  { key: 'momentum_score', label: 'Momentum', type: 'num',
    title: 'Heuristic 0-100 momentum-continuation score: a weighted blend of RSI position, EMA stack, MACD strength + slope, relative volume, streak breakout, and turnover. Higher = more indicators aligned for further upside. A ranking signal, not a calibrated probability.',
    render: (r) => {
      const m = r.momentum_score;
      const c = (m == null) ? '' : (m >= 70 ? 'pos' : (m < 40 ? 'neg' : ''));
      return `<td class="num ${c}"><strong>${m == null ? '—' : fmtNum(m, 1)}</strong></td>`;
    } },
  { key: 'name', label: 'Name', type: 'text',
    title: 'Company name.',
    render: (r) => `<td>${escapeHtml(r.name || '')}</td>` },
  { key: 'exchange', label: 'Ex.', type: 'text',
    title: 'Listing exchange — US or TSX (Canada).',
    render: (r) => `<td><span class="chip">${escapeHtml(r.exchange || '')}</span></td>` },
  { key: 'close', label: 'Prev close', type: 'num',
    title: "The previous trading day's closing price, in dollars — the bar the screen evaluates.",
    render: (r) => `<td class="num">${fmtNum(r.close)}</td>` },
  { key: 'pct_change', label: '% chg', type: 'num',
    title: "Percent change of the close versus the prior day's close. Green = up, red = down.",
    render: (r) => `<td class="num ${r.pct_change >= 0 ? 'pos' : 'neg'}">${r.pct_change >= 0 ? '+' : ''}${fmtNum(r.pct_change)}%</td>` },
  { key: 'high_lookback', label: '2d HH', type: 'num',
    title: 'End-of-streak value — the latest higher-high (or higher-close, per the streak mode) that completes the consecutive-up price streak.',
    render: (r) => `<td class="num">${fmtNum(r.high_lookback)}</td>` },
  { key: 'rsi', label: 'RSI(14)', type: 'num',
    title: 'Wilder RSI(14): a 0-100 momentum oscillator. Below ~30 is oversold, above ~70 overbought.',
    render: (r) => `<td class="num">${fmtNum(r.rsi)}</td>` },
  { key: 'rsi_sma9', label: '9d SMA', type: 'num',
    title: '9-day simple moving average of RSI(14) — a smoothed RSI baseline to compare the current RSI against.',
    render: (r) => `<td class="num">${fmtNum(r.rsi_sma9)}</td>` },
  { key: 'rsi_dev_pct', label: 'RSI dev', type: 'num',
    title: 'How far RSI(14) sits above (+) or below (-) its own 9-day average, in percent.',
    render: (r) => `<td class="num ${r.rsi_dev_pct >= 0 ? 'pos' : 'neg'}">${r.rsi_dev_pct >= 0 ? '+' : ''}${fmtNum(r.rsi_dev_pct)}%</td>` },
  { key: 'ema21', label: 'EMA(21)', type: 'num',
    title: '21-day exponential moving average of the closing price.',
    render: (r) => `<td class="num">${fmtNum(r.ema21)}</td>` },
  { key: 'price_ema21_dev_pct', label: 'vs EMA21', type: 'num',
    title: 'How far the close sits above (+) or below (-) the EMA(21), in percent.',
    render: (r) => `<td class="num ${r.price_ema21_dev_pct >= 0 ? 'pos' : 'neg'}">${r.price_ema21_dev_pct >= 0 ? '+' : ''}${fmtNum(r.price_ema21_dev_pct)}%</td>` },
  { key: 'ema50', label: 'EMA(50)', type: 'num',
    title: '50-day exponential moving average of the closing price.',
    render: (r) => `<td class="num">${fmtNum(r.ema50)}</td>` },
  { key: 'ema21_ema50_dev_pct', label: '21 vs 50', type: 'num',
    title: 'How far the EMA(21) sits above (+) or below (-) the EMA(50), in percent — a measure of uptrend strength.',
    render: (r) => `<td class="num ${r.ema21_ema50_dev_pct >= 0 ? 'pos' : 'neg'}">${r.ema21_ema50_dev_pct >= 0 ? '+' : ''}${fmtNum(r.ema21_ema50_dev_pct)}%</td>` },
  { key: 'macd_hist', label: 'MACD hist', type: 'num',
    title: 'MACD histogram: the MACD line (EMA12 - EMA26) minus its 9-day signal line. Positive and rising signals strengthening upward momentum.',
    render: (r) => `<td class="num ${r.macd_hist >= 0 ? 'pos' : 'neg'}">${fmtNum(r.macd_hist, 4)}</td>` },
  { key: 'rel_volume', label: 'RVol', type: 'num',
    title: "Relative volume: the day's volume divided by the average volume of the prior N days. Above 1× means the stock traded busier than usual.",
    render: (r) => `<td class="num">${fmtNum(r.rel_volume)}×</td>` },
  { key: 'volume', label: 'Volume', type: 'num',
    title: 'Number of shares traded on the previous trading day.',
    render: (r) => `<td class="num">${fmtVol(r.volume)}</td>` },
  { key: 'turnover_pct', label: 'Turnover %', type: 'num',
    title: 'Daily volume as a share of market cap (volume / shares outstanding × 100) — how much of the company changed hands that day.',
    render: (r) => `<td class="num" title="${r.market_cap ? 'mkt cap ' + fmtVol(r.market_cap) : 'shares outstanding unknown'}">${r.turnover_pct == null ? '—' : fmtNum(r.turnover_pct, 2) + '%'}</td>` },
];
const COLUMN_BY_KEY = Object.fromEntries(COLUMN_DEFS.map((d) => [d.key, d]));
const ALL_COLUMN_KEYS = COLUMN_DEFS.map((d) => d.key);
const COLS_ORDER_KEY = 'match_columns_order_v1';
const COLS_HIDDEN_KEY = 'match_columns_hidden_v1';

function loadColumnOrder() {
  try {
    const saved = JSON.parse(localStorage.getItem(COLS_ORDER_KEY) || '[]');
    if (Array.isArray(saved)) {
      const valid = saved.filter((k) => COLUMN_BY_KEY[k]);
      for (const k of ALL_COLUMN_KEYS) if (!valid.includes(k)) valid.push(k);
      if (valid.length) return valid;
    }
  } catch (_) { /* fall through */ }
  return ALL_COLUMN_KEYS.slice();
}
function loadHiddenColumns() {
  try {
    const saved = JSON.parse(localStorage.getItem(COLS_HIDDEN_KEY) || '[]');
    if (Array.isArray(saved)) return new Set(saved.filter((k) => COLUMN_BY_KEY[k]));
  } catch (_) { /* fall through */ }
  return new Set();
}
let columnOrder = loadColumnOrder();
let hiddenColumns = loadHiddenColumns();

function saveColumnState() {
  try {
    localStorage.setItem(COLS_ORDER_KEY, JSON.stringify(columnOrder));
    localStorage.setItem(COLS_HIDDEN_KEY, JSON.stringify(Array.from(hiddenColumns)));
  } catch (_) { /* ignore */ }
}
function visibleColumns() {
  return columnOrder.map((k) => COLUMN_BY_KEY[k]).filter((d) => d && !hiddenColumns.has(d.key));
}
function emptyColspan() { return visibleColumns().length + 1; }

function columnLabel(def) {
  if (def.key === 'high_lookback') {
    const n = parseInt(inputs.high_lookback.value, 10);
    const mode = inputs.streak_mode ? inputs.streak_mode.value : 'high';
    const suffix = mode === 'close' ? 'HC'
      : mode === 'green' ? 'green'
      : mode === 'close_green' ? 'HC+G'
      : 'HH';
    return (Number.isFinite(n) && n > 0) ? `${n}d ${suffix}` : suffix;
  }
  return def.label;
}

function renderHeader() {
  if (!els.thead) return;
  const tr = els.thead.querySelector('tr');
  if (!tr) return;
  // Keep the first th (.check — holds #select-all); rebuild the rest.
  while (tr.children.length > 1) tr.removeChild(tr.lastChild);
  for (const def of visibleColumns()) {
    const th = document.createElement('th');
    if (def.type === 'num') th.className = 'num';
    th.dataset.sort = def.key;
    th.dataset.type = def.type;
    th.dataset.colKey = def.key;
    th.draggable = true;
    th.textContent = columnLabel(def);
    if (def.title) th.title = def.title;
    tr.appendChild(th);
  }
  applySortIndicators();
}

// Column drag-to-reorder — HTML5 DnD on the th headers.
let _dragColKey = null;
function onHeadDragStart(ev) {
  const th = ev.target.closest('th[data-col-key]');
  if (!th) return;
  _dragColKey = th.dataset.colKey;
  ev.dataTransfer.effectAllowed = 'move';
  try { ev.dataTransfer.setData('text/plain', _dragColKey); } catch (_) {}
}
function onHeadDragOver(ev) {
  const th = ev.target.closest('th[data-col-key]');
  if (th && _dragColKey) {
    ev.preventDefault();
    ev.dataTransfer.dropEffect = 'move';
    th.classList.add('th-drag-over');
  }
}
function onHeadDragLeave(ev) {
  const th = ev.target.closest('th[data-col-key]');
  if (th) th.classList.remove('th-drag-over');
}
function onHeadDrop(ev) {
  const th = ev.target.closest('th[data-col-key]');
  if (th) th.classList.remove('th-drag-over');
  const dragKey = _dragColKey;
  _dragColKey = null;
  if (!th || !dragKey) return;
  ev.preventDefault();
  const targetKey = th.dataset.colKey;
  if (targetKey === dragKey) return;
  const order = columnOrder.slice();
  const from = order.indexOf(dragKey);
  if (from < 0) return;
  order.splice(from, 1);
  const to = order.indexOf(targetKey);
  if (to < 0) return;
  order.splice(to, 0, dragKey);  // insert before the drop target
  columnOrder = order;
  saveColumnState();
  renderTable();
}

function renderColumnMenu() {
  if (!els.columnMenu) return;
  els.columnMenu.innerHTML = '';
  for (const key of columnOrder) {
    const def = COLUMN_BY_KEY[key];
    if (!def) continue;
    const lbl = document.createElement('label');
    lbl.className = 'col-opt';
    const checked = hiddenColumns.has(key) ? '' : ' checked';
    lbl.innerHTML = `<input type="checkbox" data-col-toggle="${escapeHtml(key)}"${checked} /> ${escapeHtml(def.label)}`;
    els.columnMenu.appendChild(lbl);
  }
  const hint = document.createElement('div');
  hint.className = 'col-menu-hint';
  hint.textContent = 'Drag column headers in the table to reorder them.';
  els.columnMenu.appendChild(hint);
}
function toggleColumnMenu(show) {
  if (!els.columnMenu) return;
  const willShow = (show === undefined) ? els.columnMenu.classList.contains('hidden') : show;
  if (willShow) renderColumnMenu();
  els.columnMenu.classList.toggle('hidden', !willShow);
}

function renderResults(results) {
  els.matchCount.textContent = `(${results.length})`;
  if (!results.length) {
    els.body.innerHTML = `<tr class="empty"><td colspan="${emptyColspan()}">No matches with these filters.</td></tr>`;
    return;
  }
  const cols = visibleColumns();
  els.body.innerHTML = '';
  for (const r of results) {
    const tr = document.createElement('tr');
    if (r.rsi != null && r.rsi_sma9 != null && r.rsi === r.rsi_sma9) {
      tr.classList.add('row-equal');
    }
    const isSelected = selectedTickers.has(r.ticker);
    const checkTd = `<td class="check"><input type="checkbox" data-select="${escapeHtml(r.ticker)}"${isSelected ? ' checked' : ''} aria-label="Select ${escapeHtml(r.ticker)}" /></td>`;
    tr.innerHTML = checkTd + cols.map((c) => c.render(r)).join('');
    els.body.appendChild(tr);
  }
}

function renderTable() {
  pruneSelection();
  renderHeader();
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
  [els.emailBtn, els.shareBtn, els.exportTvBtn, els.alertsAddBtn, els.saveHistoryBtn,
   els.exportBtn, els.clearSelectionBtn].forEach((b) => {
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

async function shareSelected(rows, summariser) {
  rows = rows || selectedRows();
  summariser = summariser || summariseRow;
  if (!rows.length) return;
  const text = rows.map(summariser).join('\n');
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

function exportForTradingView(rows) {
  rows = rows || selectedRows();
  if (!rows.length) return;
  // TradingView's "Import watchlist" takes a .txt of comma-separated
  // symbols. EXCHANGE:SYMBOL is unambiguous; we fall back to a bare
  // symbol when the exchange is unknown. TSX/TSXV display symbols carry
  // a .TO / .V suffix that TradingView doesn't use — strip it.
  const EX = { nyse: 'NYSE', nasdaq: 'NASDAQ', amex: 'AMEX', tsx: 'TSX', tsxv: 'TSXV' };
  const symbols = rows.map((r) => {
    const sym = String(r.ticker || '').toUpperCase().replace(/\.(TO|V)$/, '');
    const key = (Array.isArray(r.lists) && r.lists[0]) || '';
    const ex = EX[key];
    return ex ? `${ex}:${sym}` : sym;
  });
  const blob = new Blob([symbols.join(',')], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `tradingview-watchlist-${new Date().toISOString().slice(0, 10)}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  setStatus(`exported ${rows.length} ticker${rows.length > 1 ? 's' : ''} for TradingView`);
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
const HOVER_W = 820;
const HOVER_H = 520;
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
  // Show the company name beside the ticker in the chart header.
  const sym = payload.ticker || ticker;
  els.hoverChartTitle.textContent = (payload.name && payload.name !== sym)
    ? `${sym} — ${payload.name}`
    : sym;
  els.hoverChartStatus.textContent = '';
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
  const cell = ev.target.closest('[data-ticker]');
  if (!cell) return;
  const ticker = cell.dataset.ticker;
  if (!ticker || _hoverTicker === ticker) return;
  if (_hoverShowTimer) clearTimeout(_hoverShowTimer);
  _hoverShowTimer = setTimeout(() => {
    showHoverChart(ticker, cell);
  }, HOVER_DELAY_MS);
}

function onTickerLeave(ev) {
  const cell = ev.target.closest('[data-ticker]');
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
if (els.exportTvBtn) els.exportTvBtn.addEventListener('click', exportForTradingView);
if (els.saveHistoryBtn) els.saveHistoryBtn.addEventListener('click', saveSelectionToHistory);
if (els.exportBtn) els.exportBtn.addEventListener('click', exportSelected);
if (els.clearSelectionBtn) els.clearSelectionBtn.addEventListener('click', clearSelection);

// Column show/hide menu + drag-to-reorder headers.
if (els.columnsBtn) {
  els.columnsBtn.addEventListener('click', (ev) => { ev.stopPropagation(); toggleColumnMenu(); });
}
if (els.columnMenu) {
  els.columnMenu.addEventListener('change', (ev) => {
    const cb = ev.target.closest('input[data-col-toggle]');
    if (!cb) return;
    const key = cb.dataset.colToggle;
    if (cb.checked) {
      hiddenColumns.delete(key);
    } else {
      // Never let the user hide every column.
      if (hiddenColumns.size >= COLUMN_DEFS.length - 1) {
        cb.checked = true;
        setStatus('keep at least one column visible');
        return;
      }
      hiddenColumns.add(key);
    }
    saveColumnState();
    renderTable();
  });
}
if (els.thead) {
  els.thead.addEventListener('dragstart', onHeadDragStart);
  els.thead.addEventListener('dragover', onHeadDragOver);
  els.thead.addEventListener('dragleave', onHeadDragLeave);
  els.thead.addEventListener('drop', onHeadDrop);
}
document.addEventListener('click', (ev) => {
  if (els.columnMenu && !els.columnMenu.classList.contains('hidden')
      && !ev.target.closest('.column-menu-wrap')) {
    toggleColumnMenu(false);
  }
});
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

// --- match history (last 10 saved selections) -----------------------------
// Persisted in localStorage so it survives reloads. Each entry stores the
// run's filter params + only the rows the user *selected* from that run,
// so "Restore" puts that hand-picked set back into the table.

const HISTORY_KEY = 'match_history_v1';
const HISTORY_MAX = 10;

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

function saveSelectionToHistory() {
  const rows = selectedRows();
  if (!rows.length) { setStatus('select some tickers first'); return; }
  if (!lastRunData) { setStatus('run a screen first'); return; }
  const entry = {
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    ranAt: new Date().toISOString(),
    asOfDate: lastRunData.as_of_date || null,
    matchCount: rows.length,
    params: pickParams(lastRunData.params || {}),
    results: rows.slice(),  // only the user's hand-picked selection
  };
  const existing = loadHistory();
  existing.unshift(entry);
  saveHistory(existing.slice(0, HISTORY_MAX));
  renderHistory();
  setStatus(`saved ${rows.length} ticker${rows.length > 1 ? 's' : ''} to history`);
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
    els.historyBody.innerHTML = '<p class="muted history-empty">No saved runs yet — select tickers from a run and click "Save to history".</p>';
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
        <span class="entry-count">${e.matchCount} ticker${e.matchCount === 1 ? '' : 's'}</span>
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
      setStatus(`restored ${lastResults.length} ticker${lastResults.length === 1 ? '' : 's'} from ${new Date(ctx.entry.ranAt).toLocaleString()}`);
    } else if (btn.classList.contains('entry-toggle-filters')) {
      const panel = ctx.node.querySelector('.entry-filters');
      if (!panel) return;
      const hidden = panel.classList.toggle('hidden');
      btn.textContent = hidden ? 'Show filters' : 'Hide filters';
      if (!hidden && !panel.dataset.filled) {
        const p = ctx.entry.params || {};
        // Show only the filters that were active (apply_* = true) for
        // this run — summarised the same way as the alert-rule criteria.
        const active = summarizeRuleParams(p);
        const rows = active.map((c) => `<div>${escapeHtml(c)}</div>`);
        if (p.lists) {
          rows.unshift(`<div><span class="k">Exchanges</span>: ${escapeHtml(fmtParamValue('lists', p.lists))}</div>`);
        }
        if (!active.length) {
          rows.push('<div class="muted">No indicator filters were active for this run.</div>');
        }
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


// --- alert watchlist ------------------------------------------------------
// The realtime alert engine (alerts.py, run by a GitHub Actions cron)
// monitors these tickers and pushes Telegram messages when they match the
// saved alert criteria. This panel just manages the watchlist + criteria.

function renderAlertWatchlist(data) {
  const tickers = (data && data.tickers) || [];
  if (els.alertsStatus) {
    if (!data || data.enabled === false) {
      els.alertsStatus.textContent = 'alerts disabled — DATABASE_URL not set on the server';
    } else {
      els.alertsStatus.textContent = tickers.length
        ? `${tickers.length} ticker${tickers.length === 1 ? '' : 's'} monitored`
        : 'no tickers monitored yet';
    }
  }
  if (!els.alertsWatchlist) return;
  if (!tickers.length) {
    els.alertsWatchlist.innerHTML = '<p class="muted history-empty">Watchlist empty — select rows above and click "Add to alerts".</p>';
    return;
  }
  els.alertsWatchlist.innerHTML = '';
  for (const t of tickers) {
    const chip = document.createElement('span');
    chip.className = 'alert-chip';
    chip.innerHTML = `<span>${escapeHtml(t)}</span><button type="button" data-remove="${escapeHtml(t)}" title="Remove ${escapeHtml(t)} from alerts">×</button>`;
    els.alertsWatchlist.appendChild(chip);
  }
}

async function loadAlertWatchlist() {
  if (!els.alertsWatchlist) return;
  try {
    const res = await fetch('/api/alerts/watchlist');
    if (!res.ok) return;
    renderAlertWatchlist(await res.json());
  } catch (_) { /* silent */ }
}

async function addSelectedToAlerts(rows) {
  rows = rows || selectedRows();
  if (!rows.length) return;
  const tickers = rows.map((r) => r.ticker);
  try {
    const res = await fetch('/api/alerts/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tickers }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus('alert add failed: ' + (data.error || ('HTTP ' + res.status)));
      return;
    }
    renderAlertWatchlist({ enabled: true, tickers: data.tickers });
    setStatus(`added ${tickers.length} to alert watchlist`);
  } catch (_) {
    setStatus('alert add failed');
  }
}

async function removeFromAlerts(ticker) {
  try {
    const res = await fetch('/api/alerts/watchlist/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker }),
    });
    if (!res.ok) return;
    const data = await res.json();
    renderAlertWatchlist({ enabled: true, tickers: data.tickers });
  } catch (_) { /* silent */ }
}

if (els.alertsAddBtn) els.alertsAddBtn.addEventListener('click', addSelectedToAlerts);
if (els.alertsWatchlist) {
  els.alertsWatchlist.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-remove]');
    if (btn) removeFromAlerts(btn.dataset.remove);
  });
}
wireCollapse(els.alertsToggle, els.alertsBody, 'collapse_alerts');
loadAlertWatchlist();


// --- alert rules ----------------------------------------------------------
// Each rule scans a watchlist / sector / industry against its own filter
// criteria; the alert engine (alerts.py) walks every enabled rule each run.

let _alertScopes = { sectors: [], industries: [] };

function renderRules(data) {
  const rules = (data && data.rules) || [];
  // Classification coverage note — sector/industry rules need the
  // ticker_sector map, which the weekly "Classify universe" workflow builds.
  if (els.rulesClassifyNote) {
    const cl = (data && data.classification) || {};
    if (!data || data.enabled === false) {
      els.rulesClassifyNote.textContent = 'Alerts disabled — DATABASE_URL not set on the server.';
    } else if (!cl.classified) {
      els.rulesClassifyNote.textContent = 'Sector/industry map is empty — run the "Classify universe" workflow in GitHub Actions once to enable sector & industry rules. Watchlist rules work without it.';
    } else {
      els.rulesClassifyNote.textContent = `Sector/industry map: ${cl.classified.toLocaleString()} tickers classified`
        + (cl.last_classified_at ? ` (updated ${cl.last_classified_at.slice(0, 10)})` : '') + '.';
    }
  }
  if (!els.rulesList) return;
  if (!rules.length) {
    els.rulesList.innerHTML = '<p class="muted history-empty">No alert rules yet — create one above.</p>';
    return;
  }
  els.rulesList.innerHTML = '';
  for (const r of rules) {
    const scopeTxt = r.scope_type === 'watchlist'
      ? 'watchlist'
      : `${r.scope_type}: ${r.scope_value}`;
    const crit = summarizeRuleParams(r.params || {});
    const critHtml = crit.length
      ? crit.map((c) => `<span class="rule-crit">${escapeHtml(c)}</span>`).join('')
      : '<span class="rule-crit-none">no filters enabled — every ticker in scope would alert</span>';
    const lastTxt = r.last_triggered_at
      ? `Last: ${formatTriggerTime(r.last_triggered_at)} · ${r.last_match_count} ${r.last_match_count === 1 ? 'ticker' : 'tickers'}`
      : 'Never triggered yet';
    const lastClass = r.last_triggered_at ? 'rule-last' : 'rule-last rule-last-none';
    // Scan stats from the most recent alerts.py run — explains "scanned
    // but never matched" cases (you can see scope size + match count).
    const scanParts = [];
    if (r.last_run_at) {
      scanParts.push(`scope ${(r.scan_scope || 0).toLocaleString()}`);
      scanParts.push(`evaluated ${(r.scan_evaluated || 0).toLocaleString()}`);
      scanParts.push(`matched ${(r.scan_matched || 0).toLocaleString()}`);
      if (r.scan_no_data)  scanParts.push(`no_data ${r.scan_no_data.toLocaleString()}`);
      if (r.scan_errors)   scanParts.push(`errors ${r.scan_errors.toLocaleString()}`);
    }
    const scanLine = r.last_run_at
      ? `Last scan: ${scanParts.join(' · ')} · ${formatTriggerTime(r.last_run_at)}`
      : 'Not scanned yet (the alert engine hasn’t run since this rule was created).';
    const row = document.createElement('div');
    row.className = 'rule-row' + (r.enabled ? '' : ' rule-off');
    row.dataset.id = r.id;
    row.innerHTML = `
      <div class="rule-head">
        <span class="rule-name">${escapeHtml(r.name)}</span>
        <span class="rule-scope">${escapeHtml(scopeTxt)}</span>
        <span class="${lastClass}">${escapeHtml(lastTxt)}</span>
        <span class="rule-spacer"></span>
        <button type="button" data-act="toggle">${r.enabled ? 'Disable' : 'Enable'}</button>
        <button type="button" data-act="update" title="Replace this rule's criteria with the filters currently set above">Update criteria</button>
        <button type="button" data-act="history" title="Show this rule's recent trigger events (date, time, match count)">History</button>
        <button type="button" class="rule-delete" data-act="delete" title="Delete rule">×</button>
      </div>
      <div class="rule-criteria">${critHtml}</div>
      <div class="rule-scan">${escapeHtml(scanLine)}</div>
      <div class="rule-history hidden"></div>
    `;
    els.rulesList.appendChild(row);
  }
}

// Format an ISO timestamp from Postgres for display in the user's locale.
function formatTriggerTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso).slice(0, 16);
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

async function ruleShowHistory(id) {
  const row = els.rulesList && els.rulesList.querySelector(`.rule-row[data-id="${id}"]`);
  if (!row) return;
  const panel = row.querySelector('.rule-history');
  const btn = row.querySelector('button[data-act="history"]');
  if (!panel) return;
  const willShow = panel.classList.contains('hidden');
  panel.classList.toggle('hidden', !willShow);
  if (btn) btn.textContent = willShow ? 'Hide history' : 'History';
  if (!willShow) return;
  // Always re-fetch on open so the latest triggers are visible.
  panel.innerHTML = '<div class="muted">Loading…</div>';
  try {
    const res = await fetch(`/api/alerts/rules/history?id=${id}&limit=15`);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const events = data.history || [];
    if (!events.length) {
      panel.innerHTML = '<div class="muted">No triggers yet for this rule.</div>';
      return;
    }
    panel.innerHTML = events.map((e) => `
      <div class="rule-event">
        <span class="rule-event-time">${escapeHtml(formatTriggerTime(e.triggered_at))}</span>
        <span class="rule-event-count">${e.match_count} ${e.match_count === 1 ? 'ticker' : 'tickers'}</span>
      </div>
    `).join('');
  } catch (err) {
    panel.innerHTML = `<div style="color:var(--red)">Failed to load: ${escapeHtml(err.message || 'error')}</div>`;
  }
}

// Human-readable summary of a rule's criteria — only the filters that
// are actually enabled (apply_* true) are listed.
function streakModeLabel(m) {
  return m === 'close' ? 'higher closes'
    : m === 'green' ? 'green bodies'
    : m === 'close_green' ? 'higher closes + green'
    : 'higher highs';
}
function summarizeRuleParams(p) {
  const out = [];
  const n = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 });
  if (p.apply_price) out.push(`Price $${n(p.price_min)}–$${n(p.price_max)}`);
  if (p.apply_high) out.push(`Streak ${p.high_lookback}d ${streakModeLabel(p.streak_mode)}`);
  if (p.apply_rsi) out.push(`RSI(14) ${n(p.rsi_min)}–${n(p.rsi_max)}`);
  if (p.apply_rsi_dev) out.push(`RSI dev ${n(p.rsi_dev_min_pct)}–${n(p.rsi_dev_max_pct)}%`);
  if (p.apply_price_dev) out.push(`vs EMA21 ${n(p.price_dev_min_pct)}–${n(p.price_dev_max_pct)}%`);
  if (p.apply_ema_dev) out.push(`EMA21 vs EMA50 ${n(p.ema_dev_min_pct)}–${n(p.ema_dev_max_pct)}%`);
  if (p.apply_macd) out.push(`MACD hist ≥ ${n(p.macd_hist_min)}${p.macd_require_rising ? ' & rising' : ''}`);
  if (p.apply_rvol) out.push(`RVol ≥ ${n(p.rvol_min)}× (${p.rvol_lookback}d)`);
  if (p.apply_avg_volume) out.push(`Avg vol ≥ ${n(p.avg_volume_min)}`);
  if (p.apply_turnover) out.push(`Turnover ${n(p.turnover_min_pct)}–${n(p.turnover_max_pct)}%`);
  return out;
}

async function loadRules() {
  if (!els.rulesList) return;
  try {
    const res = await fetch('/api/alerts/rules');
    if (!res.ok) return;
    renderRules(await res.json());
  } catch (_) { /* silent */ }
}

async function loadAlertScopes() {
  try {
    const res = await fetch('/api/alerts/scopes');
    if (!res.ok) return;
    _alertScopes = await res.json();
    populateScopeValues();
  } catch (_) { /* silent */ }
}

function populateScopeValues() {
  if (!els.ruleScopeType || !els.ruleScopeValue) return;
  const type = els.ruleScopeType.value;
  if (type === 'watchlist') {
    els.ruleScopeValue.innerHTML = '<option value="">(the watchlist)</option>';
    els.ruleScopeValue.disabled = true;
    return;
  }
  const list = type === 'sector' ? _alertScopes.sectors : _alertScopes.industries;
  els.ruleScopeValue.disabled = false;
  if (!list || !list.length) {
    els.ruleScopeValue.innerHTML = '<option value="">— run Classify universe first —</option>';
    return;
  }
  els.ruleScopeValue.innerHTML = list
    .map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)} (${s.count})</option>`)
    .join('');
}

// Feedback for the rules panel — shown inline (the topbar status line is
// off-screen when you're working down at the rules panel).
function setRulesMsg(text, kind) {
  if (!els.rulesMsg) return;
  els.rulesMsg.textContent = text || '';
  els.rulesMsg.style.color = kind === 'error' ? 'var(--red)'
    : kind === 'ok' ? 'var(--green)' : 'var(--muted)';
}

async function createRule() {
  if (!els.ruleName || !els.ruleScopeType || !els.ruleScopeValue) return;
  const name = (els.ruleName.value || '').trim();
  const scopeType = els.ruleScopeType.value;
  const scopeValue = scopeType === 'watchlist' ? '' : els.ruleScopeValue.value;
  if (!name) {
    setRulesMsg('Enter a rule name first.', 'error');
    els.ruleName.focus();
    return;
  }
  if (scopeType !== 'watchlist' && !scopeValue) {
    setRulesMsg('Pick a sector / industry for this rule — run "Classify universe" if the list is empty.', 'error');
    return;
  }
  setRulesMsg('Creating rule…');
  try {
    // Criteria come from the current screener filters (query string);
    // name + scope come in the JSON body.
    const res = await fetch('/api/alerts/rules?' + buildQuery(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, scope_type: scopeType, scope_value: scopeValue }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setRulesMsg('Create rule failed: ' + (data.error || ('HTTP ' + res.status)), 'error');
      return;
    }
    els.ruleName.value = '';
    renderRules({ enabled: true, rules: data.rules, classification: data.classification });
    loadRules();
    setRulesMsg(`Alert rule "${name}" created.`, 'ok');
  } catch (err) {
    setRulesMsg('Create rule failed: ' + (err && err.message ? err.message : 'network error'), 'error');
  }
}

async function ruleAction(id, act) {
  if (act === 'history') {
    await ruleShowHistory(id);
    return;
  }
  let url, body;
  if (act === 'delete') {
    url = '/api/alerts/rules/delete'; body = { id };
  } else if (act === 'toggle') {
    const row = els.rulesList.querySelector(`.rule-row[data-id="${id}"]`);
    const enabling = row && row.classList.contains('rule-off');
    url = '/api/alerts/rules/toggle'; body = { id, enabled: !!enabling };
  } else if (act === 'update') {
    url = '/api/alerts/rules/update-criteria?' + buildQuery(); body = { id };
  } else {
    return;
  }
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setRulesMsg('Rule update failed: ' + (data.error || ('HTTP ' + res.status)), 'error');
      return;
    }
    renderRules({ enabled: true, rules: data.rules });
    loadRules();
    if (act === 'update') setRulesMsg('Rule criteria updated to the current filters.', 'ok');
    else if (act === 'delete') setRulesMsg('Rule deleted.', 'ok');
    else setRulesMsg('Rule ' + (data.rules ? 'updated' : 'changed') + '.', 'ok');
  } catch (err) {
    setRulesMsg('Rule update failed: ' + (err && err.message ? err.message : 'network error'), 'error');
  }
}

if (els.ruleScopeType) {
  els.ruleScopeType.addEventListener('change', populateScopeValues);
}
if (els.ruleCreateBtn) els.ruleCreateBtn.addEventListener('click', createRule);
if (els.rulesList) {
  els.rulesList.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-act]');
    const row = ev.target.closest('.rule-row');
    if (btn && row) ruleAction(Number(row.dataset.id), btn.dataset.act);
  });
}
wireCollapse(els.rulesToggle, els.rulesBody, 'collapse_rules');
populateScopeValues();
loadAlertScopes();
loadRules();


// --- setups scanner ------------------------------------------------------
// Hits /api/setups, ranks tickers from the latest snapshot by the
// base-breakout / momentum-ignition score and renders the top N.

function renderSetupBar(label, value) {
  const v = Math.max(0, Math.min(1, value || 0));
  const pct = Math.round(v * 100);
  return `
    <div class="setup-bar">
      <span class="setup-bar-label">${escapeHtml(label)}</span>
      <span class="setup-bar-track"><span class="setup-bar-fill" style="width:${pct}%"></span></span>
      <span class="setup-bar-val">${pct}</span>
    </div>
  `;
}

let lastSetupResults = [];
const selectedSetupTickers = new Set();

function renderSetupCard(r) {
  const sc = r.score || 0;
  const scoreClass = sc >= 80 ? 'setup-score-hi' : sc >= 65 ? 'setup-score-mid' : 'setup-score-lo';
  const b = r.breakdown || {};
  const checked = selectedSetupTickers.has(r.ticker) ? ' checked' : '';
  const selClass = checked ? ' setup-card-selected' : '';
  // Compact key-metric chips for at-a-glance interpretation.
  const chipBits = [];
  if (b.volume_burst_x != null) chipBits.push(`vol ${b.volume_burst_x.toFixed(1)}× base`);
  if (b.range_expansion_x != null && b.range_expansion_x >= 1.5) chipBits.push(`range ${b.range_expansion_x.toFixed(1)}× expansion`);
  if (b.cross_recency_score >= 0.7) chipBits.push('fresh EMA cross');
  if (b.macd_score >= 0.7) chipBits.push('MACD ignition');
  if (b.base_flatness_score >= 0.7) chipBits.push('flat base');
  if (b.tightness_score >= 0.7) chipBits.push('tight base');
  if (b.price_ema21_pct != null) chipBits.push(`+${b.price_ema21_pct.toFixed(1)}% vs EMA21`);
  if (b.rsi_now != null) chipBits.push(`RSI ${b.rsi_now.toFixed(0)}`);
  return `
    <div class="setup-card${selClass}">
      <div class="setup-head">
        <input type="checkbox" class="setup-check" data-setup-select="${escapeHtml(r.ticker)}"${checked} />
        <span class="setup-ticker" data-ticker="${escapeHtml(r.ticker)}"><strong>${escapeHtml(r.ticker)}</strong></span>
        <span class="setup-name">${escapeHtml(r.name || '')}</span>
        <span class="setup-spacer"></span>
        <span class="setup-close">$${fmtNum(r.close)}</span>
        <span class="setup-score ${scoreClass}">${sc.toFixed(1)}</span>
      </div>
      <div class="setup-bars">
        ${renderSetupBar('Base', r.base_quality)}
        ${renderSetupBar('Ignition', r.ignition)}
        ${renderSetupBar('Earliness', r.earliness)}
      </div>
      ${chipBits.length ? `<div class="setup-chips">${chipBits.map((c) => `<span class="setup-chip">${escapeHtml(c)}</span>`).join('')}</div>` : ''}
    </div>
  `;
}

function selectedSetupRows() {
  return lastSetupResults.filter((r) => selectedSetupTickers.has(r.ticker));
}

function summariseSetup(r) {
  return [
    r.ticker,
    r.name ? `— ${r.name}` : '',
    `$${fmtNum(r.close)}`,
    `setup ${(r.score || 0).toFixed(1)}/100`,
    `base ${((r.base_quality || 0) * 100).toFixed(0)}`,
    `ign ${((r.ignition || 0) * 100).toFixed(0)}`,
    `early ${((r.earliness || 0) * 100).toFixed(0)}`,
  ].filter(Boolean).join(' ');
}

function updateSetupSelectionUI() {
  const total = lastSetupResults.length;
  const count = selectedSetupTickers.size;
  if (els.setupsSelectionToolbar) els.setupsSelectionToolbar.hidden = total === 0;
  if (els.setupsSelectionCount) els.setupsSelectionCount.textContent = `${count} selected`;
  const disabled = count === 0;
  [els.setupsAddWatchlistBtn, els.setupsExportTvBtn, els.setupsShareBtn,
   els.setupsClearSelectionBtn].forEach((b) => { if (b) b.disabled = disabled; });
  if (els.setupsSelectAll) {
    els.setupsSelectAll.checked = total > 0 && count === total;
    els.setupsSelectAll.indeterminate = count > 0 && count < total;
  }
}

function applySetupCheckboxState(ticker, on) {
  if (!els.setupsList) return;
  const cb = els.setupsList.querySelector(`[data-setup-select="${CSS.escape(ticker)}"]`);
  if (!cb) return;
  cb.checked = on;
  const card = cb.closest('.setup-card');
  if (card) card.classList.toggle('setup-card-selected', on);
}

function toggleSetupSelection(ticker, on) {
  if (on) selectedSetupTickers.add(ticker);
  else selectedSetupTickers.delete(ticker);
  applySetupCheckboxState(ticker, on);
  updateSetupSelectionUI();
}

function setAllSetupSelections(on) {
  selectedSetupTickers.clear();
  if (on) lastSetupResults.forEach((r) => selectedSetupTickers.add(r.ticker));
  lastSetupResults.forEach((r) => applySetupCheckboxState(r.ticker, on));
  updateSetupSelectionUI();
}

async function runSetupsScan() {
  if (!els.setupsRunBtn || !els.setupsList) return;
  const minScore = Number(els.setupsMinScore && els.setupsMinScore.value) || 65;
  const minPrice = Number(els.setupsMinPrice && els.setupsMinPrice.value) || 0;
  const maxPrice = Number(els.setupsMaxPrice && els.setupsMaxPrice.value) || 1000;
  const minDollarVol = Number(els.setupsMinDollarVol && els.setupsMinDollarVol.value) || 0;
  const limit = Number(els.setupsLimit && els.setupsLimit.value) || 20;
  els.setupsRunBtn.disabled = true;
  if (els.setupsStatus) els.setupsStatus.textContent = 'scanning… (5-15s)';
  // Fresh scan invalidates any prior selection — wipe before the new results render.
  selectedSetupTickers.clear();
  lastSetupResults = [];
  updateSetupSelectionUI();
  els.setupsList.innerHTML = '<p class="muted history-empty">Scanning the snapshot — base/ignition/earliness scoring across the pre-filtered candidate pool…</p>';
  try {
    const qs = new URLSearchParams({
      min_score: String(minScore),
      min_price: String(minPrice),
      max_price: String(maxPrice),
      min_dollar_vol: String(minDollarVol),
      limit: String(limit),
    });
    const res = await fetch('/api/setups?' + qs.toString());
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      els.setupsList.innerHTML = `<p class="history-empty" style="color:var(--red)">Scan failed: ${escapeHtml(data.error || ('HTTP ' + res.status))}</p>`;
      if (els.setupsStatus) els.setupsStatus.textContent = '';
      return;
    }
    const results = data.results || [];
    if (els.setupsStatus) {
      els.setupsStatus.textContent = `${results.length} setup${results.length === 1 ? '' : 's'} (score ≥ ${minScore}) · as of ${data.as_of} · ${data.elapsed_sec}s`;
    }
    if (!results.length) {
      els.setupsList.innerHTML = `<p class="muted history-empty">No tickers cleared the ${minScore} score threshold for ${escapeHtml(data.as_of)}. Try lowering Min score, or the market just didn't show this setup today.</p>`;
      return;
    }
    lastSetupResults = results;
    els.setupsList.innerHTML = results.map(renderSetupCard).join('');
    updateSetupSelectionUI();
  } catch (err) {
    els.setupsList.innerHTML = `<p class="history-empty" style="color:var(--red)">Scan failed: ${escapeHtml(err.message || 'network error')}</p>`;
    if (els.setupsStatus) els.setupsStatus.textContent = '';
  } finally {
    els.setupsRunBtn.disabled = false;
  }
}

if (els.setupsRunBtn) els.setupsRunBtn.addEventListener('click', runSetupsScan);
if (els.setupsList) {
  // Hover a setup card's ticker to open the same chart popover as the
  // matches table. Re-use the existing handlers.
  els.setupsList.addEventListener('mouseover', onTickerEnter);
  els.setupsList.addEventListener('mouseout', onTickerLeave);
  els.setupsList.addEventListener('change', (ev) => {
    const cb = ev.target.closest('[data-setup-select]');
    if (!cb) return;
    toggleSetupSelection(cb.dataset.setupSelect, cb.checked);
  });
}
if (els.setupsSelectAll) {
  els.setupsSelectAll.addEventListener('change', (ev) => setAllSetupSelections(ev.target.checked));
}
if (els.setupsClearSelectionBtn) {
  els.setupsClearSelectionBtn.addEventListener('click', () => setAllSetupSelections(false));
}
if (els.setupsAddWatchlistBtn) {
  els.setupsAddWatchlistBtn.addEventListener('click', () => addSelectedToAlerts(selectedSetupRows()));
}
if (els.setupsExportTvBtn) {
  els.setupsExportTvBtn.addEventListener('click', () => exportForTradingView(selectedSetupRows()));
}
if (els.setupsShareBtn) {
  els.setupsShareBtn.addEventListener('click', () => shareSelected(selectedSetupRows(), summariseSetup));
}
wireCollapse(els.setupsToggle, els.setupsBody, 'collapse_setups');


// --- bootstrap -------------------------------------------------------------

els.runBtn.addEventListener('click', runScreen);

Object.values(toggles).forEach((t) => t && t.addEventListener('change', syncDisabledStates));
loadFilterDefaults();  // apply the user's saved filter defaults, if any
syncDisabledStates();
if (els.saveDefaultsBtn) els.saveDefaultsBtn.addEventListener('click', saveFilterDefaults);
if (els.resetDefaultsBtn) els.resetDefaultsBtn.addEventListener('click', resetFilterDefaults);

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

// Exchange filter dropdown — toggle the checkbox popover, close on
// outside click.
if (els.exchangeDdBtn && els.exchangeDdMenu) {
  els.exchangeDdBtn.addEventListener('click', (ev) => {
    ev.stopPropagation();
    els.exchangeDdMenu.classList.toggle('hidden');
  });
  document.addEventListener('click', (ev) => {
    if (!els.exchangeDdMenu.classList.contains('hidden')
        && !ev.target.closest('.exchange-dd')) {
      els.exchangeDdMenu.classList.add('hidden');
    }
  });
}
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
