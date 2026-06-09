const $ = (sel) => document.querySelector(sel);

const els = {
  runBtn: $('#run-btn'),
  warmBtn: $('#warm-btn'),
  cacheStatus: $('#cache-status'),
  prunedStatus: $('#pruned-status'),
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
  exportBtn: $('#export-btn'),
  clearSelectionBtn: $('#clear-selection-btn'),
  columnsBtn: $('#columns-btn'),
  columnMenu: $('#column-menu'),
  exchangeDdBtn: $('#exchange-dd-btn'),
  exchangeDdMenu: $('#exchange-dd-menu'),
  rulesToggle: $('#rules-toggle'),
  rulesBody: $('#rules-body'),
  rulesList: $('#rules-list'),
  rulesClassifyNote: $('#rules-classify-note'),
  ruleName: $('#rule-name'),
  ruleScopeType: $('#rule-scope-type'),
  ruleScopeValue: $('#rule-scope-value'),
  ruleCreateBtn: $('#rule-create-btn'),
  rulesMsg: $('#rules-msg'),
  // Screener-rule criteria modal — opens on "Create rule" (screener type)
  // and on "Update criteria" for an existing screener rule.
  cmModal: $('#criteria-modal'),
  cmForm: $('#criteria-form'),
  cmTitle: $('#criteria-modal-title'),
  cmSubtitle: $('#criteria-modal-subtitle'),
  cmMeta: $('#criteria-modal-meta'),
  cmContext: $('#criteria-modal-context'),
  cmName: $('#cm_rule_name'),
  cmScopeType: $('#cm_rule_scope_type'),
  cmScopeValue: $('#cm_rule_scope_value'),
  cmSubmit: $('#criteria-modal-submit'),
  cmMsg: $('#criteria-modal-msg'),
  cmSectionScreener: $('#cm-criteria-screener'),
  cmSectionSetup: $('#cm-criteria-setup'),
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
  setupsToggle: $('#setups-toggle'),
  setupsBody: $('#setups-body'),
  setupsList: $('#setups-list'),
  picksToggle: $('#picks-toggle'),
  picksBody: $('#picks-body'),
  picksList: $('#picks-list'),
  picksAsOf: $('#picks-as-of'),
  picksAlertsToggleBtn: $('#picks-alerts-toggle-btn'),
  picksTuneBtn: $('#picks-tune-btn'),
  picksRunBtn: $('#picks-run-btn'),
  picksTune: $('#picks-tune'),
  picksWvc: $('#picks-w-vc'),
  picksWrs: $('#picks-w-rs'),
  picksWva: $('#picks-w-va'),
  picksWmt: $('#picks-w-mt'),
  picksWdp: $('#picks-w-dp'),
  picksWvcOut: $('#picks-w-vc-out'),
  picksWrsOut: $('#picks-w-rs-out'),
  picksWvaOut: $('#picks-w-va-out'),
  picksWmtOut: $('#picks-w-mt-out'),
  picksWdpOut: $('#picks-w-dp-out'),
  picksPriceMin: $('#picks-price-min'),
  picksPriceMax: $('#picks-price-max'),
  momentumToggle: $('#momentum-toggle'),
  momentumBody: $('#momentum-body'),
  momentumList: $('#momentum-list'),
  momentumAsOf: $('#momentum-as-of'),
  momentumCount: $('#momentum-count'),
  momentumSelectionToolbar: $('#momentum-selection-toolbar'),
  momentumSelectAll: $('#momentum-select-all'),
  momentumSelectionCount: $('#momentum-selection-count'),
  momentumClearSelectedBtn: $('#momentum-clear-selected-btn'),
  momentumClearAllBtn: $('#momentum-clear-all-btn'),
  momentumPctChange: $('#momentum-pct-change'),
  momentumRvol: $('#momentum-rvol'),
  momentumRvolLookback: $('#momentum-rvol-lookback'),
  momentumHighLookback: $('#momentum-high-lookback'),
  momentumVolMcap: $('#momentum-vol-mcap'),
  momentumMcapMin: $('#momentum-mcap-min'),
  momentumMcapMax: $('#momentum-mcap-max'),
  momentumSaveBtn: $('#momentum-save-btn'),
  momentumSaveMsg: $('#momentum-save-msg'),
  momentumAlertsToggleBtn: $('#momentum-alerts-toggle-btn'),
  momentumDiagnoseToggle: $('#momentum-diagnose-toggle'),
  momentumDiagnoseBody: $('#momentum-diagnose-body'),
  momentumDiagnoseTicker: $('#momentum-diagnose-ticker'),
  momentumDiagnoseDate: $('#momentum-diagnose-date'),
  momentumDiagnoseBtn: $('#momentum-diagnose-btn'),
  momentumDiagnoseClearBtn: $('#momentum-diagnose-clear-btn'),
  momentumDiagnoseStatus: $('#momentum-diagnose-status'),
  momentumDiagnoseOut: $('#momentum-diagnose-out'),
  optionsTicker: $('#options-ticker'),
  optionsDteMin: $('#options-dte-min'),
  optionsDteMax: $('#options-dte-max'),
  optionsLookupBtn: $('#options-lookup-btn'),
  optionsClearBtn: $('#options-clear-btn'),
  optionsResetDteBtn: $('#options-reset-dte-btn'),
  optionsStatus: $('#options-status'),
  optionsResult: $('#options-result'),
  optionsHistoryList: $('#options-history-list'),
  optionsHistoryStatus: $('#options-history-status'),
  optionsHistoryToggle: $('#options-history-toggle'),
  optionsHistoryBody: $('#options-history-body'),
  optionsHistoryDate: $('#options-history-date'),
  optionsHistoryRefresh: $('#options-history-refresh'),
  optionsScanBtn: $('#options-scan-btn'),
  optionsScanCancelBtn: $('#options-scan-cancel-btn'),
  optionsScanTopN: $('#options-scan-topn'),
  optionsScanPanel: $('#options-scan-panel'),
  optionsScanList: $('#options-scan-list'),
  optionsScanPreviewText: $('#options-scan-preview-text'),
  optionsScanPreviewRefresh: $('#options-scan-preview-refresh'),
  optionsScanAdvToggle: $('#options-scan-advanced-toggle'),
  optionsScanAdvBody: $('#options-scan-advanced-body'),
  optionsAdvPriceFloor: $('#options-adv-price-floor'),
  optionsAdvVolFloor: $('#options-adv-vol-floor'),
  optionsAdvMinDistance: $('#options-adv-min-distance'),
  optionsAdvSave: $('#options-adv-save'),
  optionsAdvReset: $('#options-adv-reset'),
  optionsAdvStatus: $('#options-adv-status'),
  optionsScanSummary: $('#options-scan-summary'),
  optionsScanToggle: $('#options-scan-toggle'),
  optionsScanBody: $('#options-scan-body'),
  tabBtnStock: $('#tab-btn-stock'),
  tabBtnOptions: $('#tab-btn-options'),
  tabStock: $('#tab-stock'),
  tabOptions: $('#tab-options'),
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
  setupsCreateAlertBtn: $('#setups-create-alert-btn'),
  ruleType: $('#rule-type'),
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
  macd_vs_signal_pct: $('#macd_vs_signal_pct'),
  turnover_min_pct: $('#turnover_min_pct'),
  turnover_max_pct: $('#turnover_max_pct'),
  market_cap_min_m: $('#market_cap_min_m'),
  market_cap_max_m: $('#market_cap_max_m'),
  pct_change_min: $('#pct_change_min'),
  sma_cross_lookback: $('#sma_cross_lookback'),
  sma_slope_turn_lookback: $('#sma_slope_turn_lookback'),
  sma_slope_window: $('#sma_slope_window'),
  sma_min_slope_pct: $('#sma_min_slope_pct'),
  sma_long_flat_max_pct: $('#sma_long_flat_max_pct'),
  sma_volume_mult: $('#sma_volume_mult'),
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
  apply_macd_vs_signal: $('#apply_macd_vs_signal'),
  macd_within_pct: $('#macd_within_pct'),
  macd_above_signal: $('#macd_above_signal'),
  macd_line_rising: $('#macd_line_rising'),
  apply_turnover: $('#apply_turnover'),
  apply_market_cap: $('#apply_market_cap'),
  apply_pct_change: $('#apply_pct_change'),
  apply_sma_revival: $('#apply_sma_revival'),
  sma_require_long_flat: $('#sma_require_long_flat'),
  sma_require_volume: $('#sma_require_volume'),
};

// Parallel inputs/toggles for the screener-rule criteria modal — same keys
// so the same serialiser can build a query string from either set.
const modalInputs = {
  high_lookback: $('#cm_high_lookback'),
  streak_mode: $('#cm_streak_mode'),
  rsi_min: $('#cm_rsi_min'),
  rsi_max: $('#cm_rsi_max'),
  rsi_dev_min_pct: $('#cm_rsi_dev_min_pct'),
  rsi_dev_max_pct: $('#cm_rsi_dev_max_pct'),
  rvol_lookback: $('#cm_rvol_lookback'),
  rvol_min: $('#cm_rvol_min'),
  avg_volume_min: $('#cm_avg_volume_min'),
  price_min: $('#cm_price_min'),
  price_max: $('#cm_price_max'),
  price_dev_min_pct: $('#cm_price_dev_min_pct'),
  price_dev_max_pct: $('#cm_price_dev_max_pct'),
  ema_dev_min_pct: $('#cm_ema_dev_min_pct'),
  ema_dev_max_pct: $('#cm_ema_dev_max_pct'),
  macd_vs_signal_pct: $('#cm_macd_vs_signal_pct'),
  turnover_min_pct: $('#cm_turnover_min_pct'),
  turnover_max_pct: $('#cm_turnover_max_pct'),
  market_cap_min_m: $('#cm_market_cap_min_m'),
  market_cap_max_m: $('#cm_market_cap_max_m'),
  pct_change_min: $('#cm_pct_change_min'),
};
const modalToggles = {
  apply_high: $('#cm_apply_high'),
  apply_rsi: $('#cm_apply_rsi'),
  apply_rsi_dev: $('#cm_apply_rsi_dev'),
  apply_rvol: $('#cm_apply_rvol'),
  apply_avg_volume: $('#cm_apply_avg_volume'),
  apply_price: $('#cm_apply_price'),
  apply_price_dev: $('#cm_apply_price_dev'),
  apply_ema_dev: $('#cm_apply_ema_dev'),
  apply_macd_vs_signal: $('#cm_apply_macd_vs_signal'),
  macd_within_pct: $('#cm_macd_within_pct'),
  macd_above_signal: $('#cm_macd_above_signal'),
  macd_line_rising: $('#cm_macd_line_rising'),
  apply_turnover: $('#cm_apply_turnover'),
  apply_market_cap: $('#cm_apply_market_cap'),
  apply_pct_change: $('#cm_apply_pct_change'),
};

// Setup-rule criteria fields inside the same modal (shown when rule
// type = setup). Keyed to match what the backend's setup_params expects.
const setupModalInputs = {
  score_min: $('#cm_setup_score_min'),
  min_price: $('#cm_setup_min_price'),
  max_price: $('#cm_setup_max_price'),
  min_dollar_vol: $('#cm_setup_min_dollar_vol'),
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
  _cacheStatusTimer = setTimeout(() => {
    refreshCacheStatus();
    refreshPrunedStatus();
  }, delayMs);
}

// --- pruned-ticker indicator ---------------------------------------------
// The warm-cache prune logic drops tickers from the universe after they
// fail PRUNE_THRESHOLD consecutive days. Surface the count + a click
// path to restore so it's not a black-box change.

async function refreshPrunedStatus() {
  if (!els.prunedStatus) return;
  try {
    const res = await fetch('/api/admin/pruned-tickers', { cache: 'no-store' });
    if (!res.ok) return;
    const s = await res.json();
    const pruned = s.pruned || [];
    const near = s.near_prune || [];
    if (!pruned.length && !near.length) {
      els.prunedStatus.hidden = true;
      els.prunedStatus.textContent = '';
      return;
    }
    els.prunedStatus.hidden = false;
    const parts = [];
    if (pruned.length) parts.push(`${pruned.length} pruned`);
    if (near.length)   parts.push(`${near.length} near`);
    els.prunedStatus.textContent = parts.join(' · ');
    els.prunedStatus.classList.toggle('warn', pruned.length > 0);
    const sample = pruned.slice(0, 10).join(', ');
    const more = pruned.length > 10 ? `, +${pruned.length - 10} more` : '';
    const nearTxt = near.length
      ? `\n\n${near.length} ticker(s) ${'↑'} ${s.threshold} fail-days — one more failed day and they'll be pruned: ` + near.slice(0, 5).map((n) => `${n.ticker}(${n.fail_count})`).join(', ')
      : '';
    els.prunedStatus.title = pruned.length
      ? `Auto-pruned by warm-cache after ${s.threshold} consecutive failed days. Click to restore all.\n\nPruned: ${sample}${more}${nearTxt}`
      : `${near.length} ticker(s) approaching the prune threshold (${s.threshold} fail-days).${nearTxt}`;
  } catch (_) { /* silent */ }
}

async function restorePrunedAll() {
  if (!confirm('Restore all auto-pruned tickers and reset failure counters?')) return;
  try {
    const res = await fetch('/api/admin/pruned-tickers/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ all: true }),
    });
    if (!res.ok) {
      setStatus('restore failed: HTTP ' + res.status);
      return;
    }
    const data = await res.json();
    setStatus(`restored ${data.restored} ticker(s) to the universe`);
    refreshPrunedStatus();
    scheduleCacheStatus(100);
  } catch (err) {
    setStatus('restore failed: ' + (err && err.message ? err.message : 'network error'));
  }
}

if (els.prunedStatus) {
  els.prunedStatus.style.cursor = 'pointer';
  els.prunedStatus.addEventListener('click', restorePrunedAll);
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
    apply_macd_vs_signal: 'macd_vs_signal',
    apply_turnover: 'turnover',
    apply_market_cap: 'market_cap',
    apply_pct_change: 'pct_change',
    apply_sma_revival: 'sma_revival',
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
  { key: 'sma10', label: 'SMA(10)', type: 'num',
    title: '10-day simple moving average of close.',
    render: (r) => `<td class="num">${r.sma10 == null ? '—' : fmtNum(r.sma10)}</td>` },
  { key: 'sma10_slope_pct', label: '10-SMA slope', type: 'num',
    title: '10-SMA slope as %/day, measured over the slope-window bars. Positive and rising means the trend is turning up.',
    render: (r) => `<td class="num ${r.sma10_slope_pct == null ? '' : (r.sma10_slope_pct >= 0 ? 'pos' : 'neg')}">${r.sma10_slope_pct == null ? '—' : ((r.sma10_slope_pct >= 0 ? '+' : '') + fmtNum(r.sma10_slope_pct, 3) + '%/d')}</td>` },
  { key: 'cross_days_ago', label: 'Cross↑', type: 'num',
    title: 'Days since the close crossed above the 10-SMA from below. 0 = today, 1 = yesterday. Empty = no cross within the lookback window.',
    render: (r) => `<td class="num">${r.cross_days_ago == null ? '—' : (r.cross_days_ago === 0 ? 'today' : r.cross_days_ago + 'd ago')}</td>` },
  { key: 'slope_turn_days_ago', label: 'Turn↑', type: 'num',
    title: 'Days since the 10-SMA slope crossed from ≤ 0 to > 0 — the inflection where the downtrend ended. Empty = no inflection in the lookback window.',
    render: (r) => `<td class="num">${r.slope_turn_days_ago == null ? '—' : (r.slope_turn_days_ago === 0 ? 'today' : r.slope_turn_days_ago + 'd ago')}</td>` },
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
  [els.emailBtn, els.shareBtn, els.exportTvBtn, els.alertsAddBtn,
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
        // "done" counts attempts; subtract errors to get the count of
        // tickers actually written to disk (matches the cache-status
        // "warm" number the user sees next to this).
        const ok = Math.max(0, (s.done || 0) - (s.errors || 0));
        const errs = s.errors
          ? ` · ${s.errors.toLocaleString()} failed (no Yahoo data)`
          : '';
        const verb = s.cancelled ? 'cancelled' : 'warmed';
        const sample = (s.failed_samples && s.failed_samples.length)
          ? ` — sample: ${s.failed_samples.slice(0, 5).join(', ')}${s.failed_samples.length > 5 ? '…' : ''}`
          : '';
        setStatus(
          `cache ${verb}: ${ok.toLocaleString()}/${s.total.toLocaleString()} cached`
          + `${errs}${dur ? ` in ${dur}` : ''}${sample}`
        );
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
const HOVER_W = 900;
const HOVER_H = 820;
// Pane order: Price (0, remainder) → Volume (1) → MACD (2) → RSI (3).
// Volume gets its own dedicated strip so the price pane doesn't end in
// a confusing band of overlay bars (previously they bled visually into
// the MACD pane below). MACD and RSI both get enough vertical room to
// keep their lines / 30-70 bands legible.
const HOVER_PANE_VOL_H  = 70;
const HOVER_PANE_MACD_H = 180;
const HOVER_PANE_RSI_H  = 180;
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

  // Pane 0 — candles + EMA21 + EMA50. Volume gets its own dedicated
  // pane below (pane 1) — keeping it overlaid in the price pane left
  // a confusing "wall of bars" between the candles and MACD that ate
  // into the MACD pane's perceived height.
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
  candle.setData(rows.map((r) => ({
    time: r.time, open: r.open, high: r.high, low: r.low, close: r.close,
  })));
  ema21.setData(rows.filter((r) => r.ema21 != null).map((r) => ({ time: r.time, value: r.ema21 })));
  ema50.setData(rows.filter((r) => r.ema50 != null).map((r) => ({ time: r.time, value: r.ema50 })));

  // Pane 1 — Volume only. Compact strip, bars coloured by day direction.
  const vol = _hoverChart.addSeries(LightweightCharts.HistogramSeries, {
    priceFormat: { type: 'volume' },
    color: '#30363d',
    lastValueVisible: false,
    priceLineVisible: false,
  }, 1);
  vol.setData(rows.map((r) => ({
    time: r.time, value: r.volume || 0,
    color: r.close >= r.open ? 'rgba(63,185,80,0.5)' : 'rgba(248,81,73,0.5)',
  })));

  // Pane 2 — MACD(12, 26, 9): line + signal + histogram. The histogram
  // is the diff between the two lines (MACD − signal); positive bars
  // green / negative bars red. Zero line dashed grey so the
  // crossover point is visible at a glance.
  const macdHist = _hoverChart.addSeries(LightweightCharts.HistogramSeries, {
    priceLineVisible: false, lastValueVisible: false,
  }, 2);
  const macdLine = _hoverChart.addSeries(LightweightCharts.LineSeries, {
    color: '#58a6ff', lineWidth: 2, priceLineVisible: false,
  }, 2);
  const macdSignal = _hoverChart.addSeries(LightweightCharts.LineSeries, {
    color: '#f0883e', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
  }, 2);
  macdHist.setData(rows.filter((r) => r.macd_hist != null).map((r) => ({
    time: r.time, value: r.macd_hist,
    color: r.macd_hist >= 0 ? 'rgba(63,185,80,0.6)' : 'rgba(248,81,73,0.6)',
  })));
  macdLine.setData(rows.filter((r) => r.macd != null).map((r) => ({ time: r.time, value: r.macd })));
  macdSignal.setData(rows.filter((r) => r.macd_signal != null).map((r) => ({ time: r.time, value: r.macd_signal })));
  macdLine.createPriceLine({ price: 0, color: '#6e7681', lineStyle: 2, lineWidth: 1, axisLabelVisible: false });

  // Pane 3 — RSI(14) + 9d SMA of RSI.
  const rsi = _hoverChart.addSeries(LightweightCharts.LineSeries, {
    color: '#58a6ff', lineWidth: 2, priceLineVisible: false,
  }, 3);
  const rsiSma = _hoverChart.addSeries(LightweightCharts.LineSeries, {
    color: '#f0883e', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
  }, 3);
  rsi.setData(rows.filter((r) => r.rsi != null).map((r) => ({ time: r.time, value: r.rsi })));
  rsiSma.setData(rows.filter((r) => r.rsi_sma9 != null).map((r) => ({ time: r.time, value: r.rsi_sma9 })));
  rsi.createPriceLine({ price: 70, color: '#f85149', lineStyle: 2, lineWidth: 1, axisLabelVisible: false });
  rsi.createPriceLine({ price: 30, color: '#3fb950', lineStyle: 2, lineWidth: 1, axisLabelVisible: false });

  // Compress the two oscillator panes; the price pane absorbs the rest.
  // Aligning right-side scale widths keeps the time axis straight across
  // all three panes. Pane labels are absolutely positioned over the
  // chart container in CSS — their top offsets depend on these heights
  // so we recompute on each apply().
  const apply = () => {
    try {
      const panes = _hoverChart.panes() || [];
      panes.forEach((p) => {
        try { p.priceScale('right').applyOptions({ minimumWidth: 56 }); } catch (_) {}
      });
      if (panes.length >= 2 && panes[1].setHeight) panes[1].setHeight(HOVER_PANE_VOL_H);
      if (panes.length >= 3 && panes[2].setHeight) panes[2].setHeight(HOVER_PANE_MACD_H);
      if (panes.length >= 4 && panes[3].setHeight) panes[3].setHeight(HOVER_PANE_RSI_H);
    } catch (_) { /* ignore */ }
    try { _hoverChart.timeScale().fitContent(); } catch (_) {}
    positionPaneLabels();
  };
  apply();
  requestAnimationFrame(apply);
  setTimeout(apply, 80);
}

// Each pane gets a small label in its top-left corner ("Price · EMA21 ·
// EMA50", "Volume", "MACD(12, 26, 9)", "RSI(14) · 9d SMA"). Lightweight-
// charts has no native title support, and it wipes its container on
// dispose — so the spans live as siblings of #hover-chart-container
// (inside #hover-chart) and are positioned relative to the popup
// wrapper. Pane 0 (Price) sits at the top of the container; the
// remaining pane tops stack from the bottom up using the fixed pane
// heights. The container's offsetTop gives us the y origin.
function positionPaneLabels() {
  if (!els.hoverChartContainer) return;
  const containerH = els.hoverChartContainer.clientHeight;
  if (!containerH) return;
  const top = els.hoverChartContainer.offsetTop;
  const labels = [0, 1, 2, 3].map((i) => document.getElementById('hover-pane-label-' + i));
  if (labels[0]) labels[0].style.top = (top + 6) + 'px';
  if (labels[1]) labels[1].style.top = (top + containerH - HOVER_PANE_VOL_H - HOVER_PANE_MACD_H - HOVER_PANE_RSI_H + 4) + 'px';
  if (labels[2]) labels[2].style.top = (top + containerH - HOVER_PANE_MACD_H - HOVER_PANE_RSI_H + 4) + 'px';
  if (labels[3]) labels[3].style.top = (top + containerH - HOVER_PANE_RSI_H + 4) + 'px';
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
if (els.shareBtn) els.shareBtn.addEventListener('click', () => shareSelected());
if (els.exportTvBtn) els.exportTvBtn.addEventListener('click', () => exportForTradingView());
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
wireCollapse(
  els.diagnoseToggle,
  [els.diagnoseBody, els.diagnoseOutput],
  'collapse_diagnose'
);

updateSelectionUI();

// --- watchlist add ------------------------------------------------------
// The realtime alert engine (alerts.py) uses this watchlist as the scope
// for watchlist-scoped rules. The list itself isn't surfaced anywhere in
// the UI — adding feeds rules without needing a display panel.

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
    setStatus(`added ${tickers.length} to alert watchlist`);
  } catch (_) {
    setStatus('alert add failed');
  }
}

if (els.alertsAddBtn) els.alertsAddBtn.addEventListener('click', () => addSelectedToAlerts());


// --- alert rules ----------------------------------------------------------
// Each rule scans a watchlist / sector / industry against its own filter
// criteria; the alert engine (alerts.py) walks every enabled rule each run.

let _alertScopes = { sectors: [], industries: [] };
// Cache the most recently rendered rule list so the Update-criteria
// modal can look up r.params by rule id without an extra round trip.
let _alertRules = [];

function renderRules(data) {
  const rules = (data && data.rules) || [];
  _alertRules = rules;
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
    const isSetup = r.rule_type === 'setup';
    const scopeTxt = r.scope_type === 'watchlist'
      ? 'watchlist'
      : r.scope_type === 'all'
        ? 'all snapshot tickers'
        : `${r.scope_type}: ${r.scope_value}`;
    const crit = summarizeRuleParams(r.params || {}, r.rule_type);
    const critHtml = crit.length
      ? crit.map((c) => `<span class="rule-crit">${escapeHtml(c)}</span>`).join('')
      : '<span class="rule-crit-none">no filters enabled — every ticker in scope would alert</span>';
    // Header chip — most recent successful trigger (rule fired & sent
    // alerts). Reads from the alert_sent table via rules_with_last_trigger().
    const lastTxt = r.last_triggered_at
      ? `Last alert: ${formatTriggerTime(r.last_triggered_at)} · ${r.last_match_count} ${r.last_match_count === 1 ? 'ticker' : 'tickers'}`
      : 'Never triggered yet';
    const lastClass = r.last_triggered_at ? 'rule-last' : 'rule-last rule-last-none';
    // Scan stats from the most recent alerts.py run for this rule —
    // distinct from "Last alert" because alerts.py runs every ~15 min
    // during market hours but only ALERTS when there's a match. The
    // date is shown first so it's easy to compare against the header.
    const scanParts = [];
    if (r.last_run_at) {
      scanParts.push(`scope ${(r.scan_scope || 0).toLocaleString()}`);
      scanParts.push(`evaluated ${(r.scan_evaluated || 0).toLocaleString()}`);
      scanParts.push(`matched ${(r.scan_matched || 0).toLocaleString()}`);
      if (r.scan_no_data)  scanParts.push(`no_data ${r.scan_no_data.toLocaleString()}`);
      if (r.scan_errors)   scanParts.push(`errors ${r.scan_errors.toLocaleString()}`);
    }
    const scanLine = r.last_run_at
      ? `Last scan: ${formatTriggerTime(r.last_run_at)} · ${scanParts.join(' · ')}`
      : 'Not scanned yet (the alert engine hasn’t run since this rule was created).';
    const row = document.createElement('div');
    row.className = 'rule-row'
      + (r.enabled ? '' : ' rule-off')
      + (isSetup ? ' rule-setup' : '');
    row.dataset.id = r.id;
    const typeChip = isSetup
      ? '<span class="rule-type-chip rule-type-setup">Setup</span>'
      : '<span class="rule-type-chip rule-type-screener">Screener</span>';
    row.innerHTML = `
      <div class="rule-head">
        ${typeChip}
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
    const res = await fetch(`/api/alerts/rules/history?id=${id}&limit=15`, { cache: 'no-store' });
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
    // Sync the row header to the freshest event in case the cached
    // /api/alerts/rules response (which seeded "Last alert") is behind.
    syncLastAlertFromHistory(row, events[0]);
  } catch (err) {
    panel.innerHTML = `<div style="color:var(--red)">Failed to load: ${escapeHtml(err.message || 'error')}</div>`;
  }
}

// Update the row's "Last alert" chip in-place if the freshest history
// event is newer than what the chip currently shows. Avoids waiting
// for the next poll to see today's triggers reflected in the header.
function syncLastAlertFromHistory(row, latestEvent) {
  if (!row || !latestEvent || !latestEvent.triggered_at) return;
  const chip = row.querySelector('.rule-last');
  if (!chip) return;
  const cached = _alertRules.find((r) => String(r.id) === row.dataset.id);
  const prevIso = cached && cached.last_triggered_at;
  if (prevIso && new Date(prevIso).getTime() >= new Date(latestEvent.triggered_at).getTime()) {
    return;  // header already up to date
  }
  const n = latestEvent.match_count;
  chip.textContent = `Last alert: ${formatTriggerTime(latestEvent.triggered_at)} · ${n} ${n === 1 ? 'ticker' : 'tickers'}`;
  chip.classList.remove('rule-last-none');
  if (cached) {
    cached.last_triggered_at = latestEvent.triggered_at;
    cached.last_match_count = n;
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
function summarizeRuleParams(p, ruleType) {
  const n = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 });
  if (ruleType === 'setup') {
    const out = [`Setup score ≥ ${n(p.score_min)}`];
    if (p.min_price != null && p.max_price != null) {
      out.push(`Price $${n(p.min_price)}–$${n(p.max_price)}`);
    }
    if (p.min_dollar_vol != null) out.push(`$-vol/day ≥ $${n(p.min_dollar_vol)}`);
    return out;
  }
  const out = [];
  if (p.apply_price) out.push(`Price $${n(p.price_min)}–$${n(p.price_max)}`);
  if (p.apply_high) out.push(`Streak ${p.high_lookback}d ${streakModeLabel(p.streak_mode)}`);
  if (p.apply_rsi) out.push(`RSI(14) ${n(p.rsi_min)}–${n(p.rsi_max)}`);
  if (p.apply_rsi_dev) out.push(`RSI dev ${n(p.rsi_dev_min_pct)}–${n(p.rsi_dev_max_pct)}%`);
  if (p.apply_price_dev) out.push(`vs EMA21 ${n(p.price_dev_min_pct)}–${n(p.price_dev_max_pct)}%`);
  if (p.apply_ema_dev) out.push(`EMA21 vs EMA50 ${n(p.ema_dev_min_pct)}–${n(p.ema_dev_max_pct)}%`);
  if (p.apply_macd_vs_signal) {
    const parts = [];
    if (p.macd_within_pct) parts.push(`within ${n(p.macd_vs_signal_pct)}% of signal`);
    if (p.macd_above_signal) parts.push('≥ signal');
    if (p.macd_line_rising) parts.push('rising');
    out.push('MACD ' + (parts.join(' + ') || '(no condition)'));
  }
  if (p.apply_rvol) out.push(`RVol ≥ ${n(p.rvol_min)}× (${p.rvol_lookback}d)`);
  if (p.apply_avg_volume) out.push(`Avg vol ≥ ${n(p.avg_volume_min)}`);
  if (p.apply_turnover) out.push(`Turnover ${n(p.turnover_min_pct)}–${n(p.turnover_max_pct)}%`);
  if (p.apply_market_cap) out.push(`Mcap $${n(p.market_cap_min_m)}M–$${n(p.market_cap_max_m)}M`);
  if (p.apply_pct_change) out.push(`Latest % change ≥ ${n(p.pct_change_min)}%`);
  return out;
}

async function loadRules() {
  if (!els.rulesList) return;
  try {
    // cache: 'no-store' guarantees a fresh response — without it some
    // browsers will serve a stale cached body and the row "Last alert"
    // field drifts behind the actual trigger history.
    const res = await fetch('/api/alerts/rules', { cache: 'no-store' });
    if (!res.ok) return;
    renderRules(await res.json());
  } catch (_) { /* silent */ }
}

// Auto-refresh the rule list every 60s so the "Last alert" and "Last
// scan" fields don't go stale between the alert engine runs (which
// happen every ~15 min in market hours). Pauses when the tab is
// hidden, and runs immediately when it becomes visible again.
let _rulesPollTimer = null;
function startRulesPolling() {
  if (_rulesPollTimer) return;
  _rulesPollTimer = setInterval(() => {
    if (document.visibilityState === 'visible') loadRules();
  }, 60_000);
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') loadRules();
});

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
  if (type === 'all') {
    els.ruleScopeValue.innerHTML = '<option value="">(every snapshot ticker)</option>';
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
  // Both screener AND setup rules go through the same criteria modal.
  // The modal handles validation + the POST itself, and picks the
  // type-appropriate default scope when no seed is supplied.
  const ruleType = (els.ruleType && els.ruleType.value) || 'screener';
  openCriteriaModal({
    mode: 'create',
    ruleType,
    seedName: (els.ruleName && els.ruleName.value || '').trim(),
  });
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
    // Both screener and setup rules use the criteria modal for updates.
    // The modal pre-fills from rule.params and POSTs on submit.
    const row = els.rulesList && els.rulesList.querySelector(`.rule-row[data-id="${id}"]`);
    const isSetup = row && row.classList.contains('rule-setup');
    const rule = _alertRules.find((r) => r.id === id) || {};
    const scopeText = rule.scope_type === 'watchlist'
      ? 'Watchlist'
      : rule.scope_type === 'all'
      ? 'All snapshot tickers'
      : (rule.scope_type
          ? rule.scope_type[0].toUpperCase() + rule.scope_type.slice(1)
            + (rule.scope_value ? ': ' + rule.scope_value : '')
          : '');
    openCriteriaModal({
      mode: 'update',
      ruleType: isSetup ? 'setup' : 'screener',
      ruleId: id,
      ruleName: rule.name || `#${id}`,
      scopeText,
      prefill: rule.params || {},
    });
    return;
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

// --- criteria modal (screener rule create / update) ----------------------
// Same shape on both create and update — only the meta block (name +
// scope) differs. Backed by the parallel modalInputs / modalToggles
// maps so the same query-string serialiser fits the existing screener
// rule endpoints (POST /api/alerts/rules?<query> and POST
// /api/alerts/rules/update-criteria?<query>).

let _criteriaModalState = { mode: 'create', ruleId: null, ruleType: 'screener' };

function openCriteriaModal({ mode, ruleType, ruleId, ruleName, scopeText,
                              seedName, seedScopeType, seedScopeValue, prefill }) {
  if (!els.cmModal) return;
  ruleType = ruleType || 'screener';
  _criteriaModalState = { mode, ruleId: ruleId || null, ruleType };

  // Show only the criteria section that matches the rule type. Both
  // sections live in the DOM so we can toggle without rebuilding.
  if (els.cmSectionScreener) els.cmSectionScreener.hidden = ruleType !== 'screener';
  if (els.cmSectionSetup) els.cmSectionSetup.hidden = ruleType !== 'setup';

  // Pre-fill criteria. CREATE seeds from the relevant live form (main
  // filter form for screener, Setups toolbar for setup) so the popup
  // opens close to what the user was just looking at. UPDATE uses the
  // rule's stored params.
  if (ruleType === 'setup') {
    applySetupParamsToModal(prefill || readSetupToolbarAsParams());
  } else {
    applyParamsToModal(prefill || readMainFormAsParams());
  }

  // The "All snapshot tickers" scope option is only meaningful for
  // setup rules (alert engine has no efficient way to scan it for the
  // intraday screener path).
  if (els.cmScopeType) {
    const allOpt = els.cmScopeType.querySelector('option[value="all"]');
    if (allOpt) allOpt.hidden = ruleType !== 'setup';
  }

  if (mode === 'create') {
    const ruleLabel = ruleType === 'setup' ? 'setup' : 'screener';
    if (els.cmTitle) els.cmTitle.textContent = `Create ${ruleLabel} alert rule`;
    if (els.cmSubtitle) {
      els.cmSubtitle.textContent = ruleType === 'setup'
        ? 'Setup rules rank the latest EOD snapshot. Pick a scope and set min-score + price / dollar-volume thresholds.'
        : 'Pick a scope and adjust filter criteria. The realtime engine checks these every ~15 min in market hours.';
    }
    if (els.cmMeta) els.cmMeta.hidden = false;
    if (els.cmContext) { els.cmContext.textContent = ''; els.cmContext.hidden = true; }
    if (els.cmName) {
      els.cmName.value = seedName || '';
      els.cmName.disabled = false;
    }
    if (els.cmScopeType) {
      // Default scope per rule type: setup -> 'all', screener -> 'watchlist'.
      const defaultScope = ruleType === 'setup' ? 'all' : 'watchlist';
      const seed = seedScopeType && (ruleType === 'setup' || seedScopeType !== 'all')
        ? seedScopeType : defaultScope;
      els.cmScopeType.value = seed;
      els.cmScopeType.disabled = false;
    }
    populateModalScopeValues();
    if (els.cmScopeValue && seedScopeValue) {
      const opt = Array.from(els.cmScopeValue.options).find((o) => o.value === seedScopeValue);
      if (opt) els.cmScopeValue.value = seedScopeValue;
    }
    if (els.cmSubmit) els.cmSubmit.textContent = 'Create rule';
  } else {
    if (els.cmTitle) els.cmTitle.textContent = `Update criteria — ${ruleName || '(rule)'}`;
    if (els.cmSubtitle) {
      els.cmSubtitle.textContent = "Adjust the criteria for this rule. Name and scope can't be edited here — delete and recreate to change them.";
    }
    if (els.cmMeta) els.cmMeta.hidden = true;
    if (els.cmContext) {
      els.cmContext.textContent = scopeText ? `Scope: ${scopeText}` : '';
      els.cmContext.hidden = !scopeText;
    }
    if (els.cmSubmit) els.cmSubmit.textContent = 'Save criteria';
  }

  setModalMsg('');
  syncModalDisabled();
  try { els.cmModal.showModal(); }
  catch (_) { /* dialog already open or unsupported */ }
}

function closeCriteriaModal() {
  if (els.cmModal && els.cmModal.open) els.cmModal.close();
}

function setModalMsg(text, kind) {
  if (!els.cmMsg) return;
  els.cmMsg.textContent = text || '';
  els.cmMsg.style.color = kind === 'error' ? 'var(--red)'
    : kind === 'ok' ? 'var(--green)' : 'var(--muted)';
}

// Push a params dict (same shape as rule.params) into the modal form.
function applyParamsToModal(p) {
  p = p || {};
  for (const [k, el] of Object.entries(modalInputs)) {
    if (!el) continue;
    if (p[k] !== undefined && p[k] !== null) el.value = String(p[k]);
  }
  for (const [k, el] of Object.entries(modalToggles)) {
    if (!el) continue;
    if (p[k] !== undefined && p[k] !== null) {
      const v = p[k];
      el.checked = !(v === false || v === 0 || v === '0' || v === 'false');
    }
  }
}

// Snapshot the main screener form's values into a params dict — used as
// the default seed for the Create flow so users don't lose what they
// were just tuning.
function readMainFormAsParams() {
  const out = {};
  for (const [k, el] of Object.entries(inputs)) if (el) out[k] = el.value;
  for (const [k, el] of Object.entries(toggles)) if (el) out[k] = !!el.checked;
  return out;
}

// Build a query string from the modal's filter form — matches what
// /api/screen and the alert-rule endpoints expect.
function buildModalQuery() {
  const params = new URLSearchParams();
  for (const [k, el] of Object.entries(modalInputs)) if (el) params.set(k, el.value);
  for (const [k, el] of Object.entries(modalToggles)) if (el) params.set(k, el.checked ? '1' : '0');
  return params.toString();
}

// --- setup-rule criteria helpers (same modal, different section) ---

function applySetupParamsToModal(p) {
  p = p || {};
  for (const [k, el] of Object.entries(setupModalInputs)) {
    if (!el) continue;
    if (p[k] !== undefined && p[k] !== null) el.value = String(p[k]);
  }
}

function readSetupToolbarAsParams() {
  return {
    score_min: Number(els.setupsMinScore && els.setupsMinScore.value) || 65,
    min_price: Number(els.setupsMinPrice && els.setupsMinPrice.value) || 0,
    max_price: Number(els.setupsMaxPrice && els.setupsMaxPrice.value) || 1000,
    min_dollar_vol: Number(els.setupsMinDollarVol && els.setupsMinDollarVol.value) || 0,
  };
}

function buildSetupParamsFromModal() {
  const out = {};
  for (const [k, el] of Object.entries(setupModalInputs)) {
    if (el) out[k] = Number(el.value);
  }
  return out;
}

function populateModalScopeValues() {
  if (!els.cmScopeType || !els.cmScopeValue) return;
  const type = els.cmScopeType.value;
  if (type === 'watchlist') {
    els.cmScopeValue.innerHTML = '<option value="">(the watchlist)</option>';
    els.cmScopeValue.disabled = true;
    return;
  }
  if (type === 'all') {
    els.cmScopeValue.innerHTML = '<option value="">(every snapshot ticker)</option>';
    els.cmScopeValue.disabled = true;
    return;
  }
  const list = type === 'sector' ? _alertScopes.sectors : _alertScopes.industries;
  els.cmScopeValue.disabled = false;
  if (!list || !list.length) {
    els.cmScopeValue.innerHTML = '<option value="">— run Classify universe first —</option>';
    return;
  }
  els.cmScopeValue.innerHTML = list
    .map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)} (${s.count})</option>`)
    .join('');
}

// Visually grey out a filter group whose apply-toggle is off — mirrors
// the syncDisabledStates() behaviour on the main form.
function syncModalDisabled() {
  const map = {
    apply_high: 'cm_high',
    apply_rsi: 'cm_rsi',
    apply_rsi_dev: 'cm_rsi_dev',
    apply_rvol: 'cm_rvol',
    apply_avg_volume: 'cm_avg_volume',
    apply_price: 'cm_price',
    apply_price_dev: 'cm_price_dev',
    apply_ema_dev: 'cm_ema_dev',
    apply_macd_vs_signal: 'cm_macd_vs_signal',
    apply_turnover: 'cm_turnover',
    apply_market_cap: 'cm_market_cap',
    apply_pct_change: 'cm_pct_change',
  };
  for (const [toggleKey, groupKey] of Object.entries(map)) {
    const t = modalToggles[toggleKey];
    const g = els.cmModal && els.cmModal.querySelector(`[data-group="${groupKey}"]`);
    if (t && g) g.classList.toggle('disabled', !t.checked);
  }
}

async function submitCriteriaModal() {
  const ruleType = _criteriaModalState.ruleType || 'screener';
  if (_criteriaModalState.mode === 'create') {
    const name = (els.cmName && els.cmName.value || '').trim();
    const scopeType = (els.cmScopeType && els.cmScopeType.value)
      || (ruleType === 'setup' ? 'all' : 'watchlist');
    const scopeValue = (scopeType === 'watchlist' || scopeType === 'all')
      ? '' : (els.cmScopeValue && els.cmScopeValue.value) || '';
    if (!name) {
      setModalMsg('Enter a rule name.', 'error');
      if (els.cmName) els.cmName.focus();
      return;
    }
    if (scopeType === 'all' && ruleType !== 'setup') {
      setModalMsg('"All snapshot tickers" is only valid for setup rules.', 'error');
      return;
    }
    if (scopeType !== 'watchlist' && scopeType !== 'all' && !scopeValue) {
      setModalMsg('Pick a sector / industry — run "Classify universe" if the list is empty.', 'error');
      return;
    }
    setModalMsg('Creating rule…');
    if (els.cmSubmit) els.cmSubmit.disabled = true;
    try {
      let url, body;
      if (ruleType === 'setup') {
        url = '/api/alerts/rules';
        body = {
          name, scope_type: scopeType, scope_value: scopeValue,
          rule_type: 'setup',
          setup_params: buildSetupParamsFromModal(),
        };
      } else {
        url = '/api/alerts/rules?' + buildModalQuery();
        body = { name, scope_type: scopeType, scope_value: scopeValue, rule_type: 'screener' };
      }
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setModalMsg('Create rule failed: ' + (data.error || ('HTTP ' + res.status)), 'error');
        return;
      }
      if (els.ruleName) els.ruleName.value = '';
      renderRules({ enabled: true, rules: data.rules, classification: data.classification });
      loadRules();
      setRulesMsg(`Alert rule "${name}" created.`, 'ok');
      closeCriteriaModal();
    } catch (err) {
      setModalMsg('Create rule failed: ' + (err && err.message ? err.message : 'network error'), 'error');
    } finally {
      if (els.cmSubmit) els.cmSubmit.disabled = false;
    }
    return;
  }

  // UPDATE
  const ruleId = _criteriaModalState.ruleId;
  if (!ruleId) {
    setModalMsg('Internal error: rule id missing.', 'error');
    return;
  }
  setModalMsg('Saving criteria…');
  if (els.cmSubmit) els.cmSubmit.disabled = true;
  try {
    const url = ruleType === 'setup'
      ? '/api/alerts/rules/update-criteria'
      : '/api/alerts/rules/update-criteria?' + buildModalQuery();
    const reqBody = ruleType === 'setup'
      ? { id: ruleId, setup_params: buildSetupParamsFromModal() }
      : { id: ruleId };
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reqBody),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setModalMsg('Update failed: ' + (data.error || ('HTTP ' + res.status)), 'error');
      return;
    }
    renderRules({ enabled: true, rules: data.rules });
    loadRules();
    setRulesMsg('Rule criteria updated.', 'ok');
    closeCriteriaModal();
  } catch (err) {
    setModalMsg('Update failed: ' + (err && err.message ? err.message : 'network error'), 'error');
  } finally {
    if (els.cmSubmit) els.cmSubmit.disabled = false;
  }
}

// Modal wiring — submit, close (×, Cancel), scope-type change, group disable.
if (els.cmForm) {
  els.cmForm.addEventListener('submit', (ev) => {
    ev.preventDefault();
    submitCriteriaModal();
  });
}
if (els.cmModal) {
  els.cmModal.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-act="close"]')) {
      ev.preventDefault();
      closeCriteriaModal();
    }
  });
  // ESC -> dialog.close() — re-route through our msg-clearing close to
  // keep state consistent if the user re-opens it.
  els.cmModal.addEventListener('close', () => setModalMsg(''));
}
if (els.cmScopeType) {
  els.cmScopeType.addEventListener('change', populateModalScopeValues);
}
Object.values(modalToggles).forEach((t) => t && t.addEventListener('change', syncModalDisabled));


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
startRulesPolling();


// --- nightly watchlist picker --------------------------------------------
// Reads /api/picks for the latest persisted ranking, lets the user adjust
// weights + price range, and re-ranks live via /api/picks/run. Saved
// settings are picked up by the nightly cron at close+1hr.

const _PICKS_WEIGHT_KEYS = ['vc', 'rs', 'va', 'mt', 'dp'];

function picksWeightFromUI() {
  const out = {};
  for (const k of _PICKS_WEIGHT_KEYS) {
    const el = els['picksW' + k];
    out[k] = el ? Number(el.value) : 0;
  }
  return out;
}

function picksApplyWeightsToUI(weights) {
  weights = weights || {};
  for (const k of _PICKS_WEIGHT_KEYS) {
    const el = els['picksW' + k];
    const out = els['picksW' + k + 'Out'];
    if (el && weights[k] !== undefined) el.value = String(weights[k]);
    if (out && el) out.textContent = el.value;
  }
}

function picksMiniBar(label, value) {
  // Compact 0-100 bar used inline next to each picked ticker.
  const v = Math.max(0, Math.min(100, Math.round(value || 0)));
  return `
    <span class="pick-bar" title="${escapeHtml(label)}: ${v}">
      <span class="pick-bar-label">${escapeHtml(label)}</span>
      <span class="pick-bar-track"><span class="pick-bar-fill" style="width:${v}%"></span></span>
      <span class="pick-bar-val">${v}</span>
    </span>
  `;
}

// Per-ticker intraday-trigger badges. Populated from /api/picks/intraday-alerts
// when the panel renders and updated alongside loadPicks polls.
let _picksIntradayByTicker = {};

const _PICK_TRIGGER_LABELS = {
  pivot_breakout: { glyph: '🎯', name: '20-day pivot breakout' },
  orb:            { glyph: '🚀', name: 'Opening range breakout' },
  // Kept for legacy alerts already in the DB from the prior trigger.
  vwap_reclaim:   { glyph: '⚡', name: 'VWAP reclaim' },
};

function renderPickTriggerBadges(ticker) {
  const fired = _picksIntradayByTicker[ticker];
  if (!fired || !fired.length) return '';
  return fired.map((evt) => {
    const meta = _PICK_TRIGGER_LABELS[evt.trigger_type] || { glyph: '⚡', name: evt.trigger_type };
    const ts = evt.fired_at ? formatTriggerTime(evt.fired_at) : '';
    const tip = `${meta.name} at ${ts}` + (evt.details ? ' — ' + evt.details : '');
    return `<span class="pick-trigger" title="${escapeHtml(tip)}">${meta.glyph} ${escapeHtml(meta.name)}</span>`;
  }).join('');
}

// Hydration latch — the tuning inputs (weight sliders, price band)
// must only be set from the server response on the FIRST render.
// Subsequent polls re-render the rows and leave the inputs alone,
// otherwise the 60s loadPicks tick wipes in-progress edits before
// the user can click Re-rank.
let _picksTuningHydrated = false;

function renderPicks(data) {
  const picks = (data && data.picks) || [];
  const cfg = (data && data.config) || null;
  if (cfg && !_picksTuningHydrated) {
    picksApplyWeightsToUI(cfg.weights);
    if (els.picksPriceMin && cfg.price_min != null) els.picksPriceMin.value = String(cfg.price_min);
    if (els.picksPriceMax && cfg.price_max != null) els.picksPriceMax.value = String(cfg.price_max);
    _picksTuningHydrated = true;
  }
  if (!els.picksList) return;
  if (!picks.length) {
    if (els.picksAsOf) els.picksAsOf.textContent = '';
    els.picksList.innerHTML = '<p class="muted history-empty">No picks yet — the nightly job hasn\'t run, or click "Re-rank now" to compute them on demand.</p>';
    return;
  }
  if (els.picksAsOf) {
    els.picksAsOf.textContent = `as of ${picks[0].pick_date || '?'}`;
  }
  const rows = picks.map((p) => {
    const close = p.close != null ? `$${Number(p.close).toFixed(2)}` : '';
    const ret = p.ret_20d != null ? `${(p.ret_20d * 100).toFixed(1)}%` : '';
    const dist = p.dist_pivot != null ? `${p.dist_pivot.toFixed(1)}% from pivot` : '';
    const atr = p.atr_ratio != null ? `ATR20/60 ${p.atr_ratio.toFixed(2)}` : '';
    const dvol = p.dvol_ratio != null ? `dvol 10/60 ${p.dvol_ratio.toFixed(2)}` : '';
    const metaParts = [ret, dist, atr, dvol].filter(Boolean);
    const badges = renderPickTriggerBadges(p.ticker);
    return `
      <div class="pick-row">
        <span class="pick-rank">${p.rank}</span>
        <span class="pick-ticker" data-ticker="${escapeHtml(p.ticker)}">${escapeHtml(p.ticker)}</span>
        <span class="pick-close">${escapeHtml(close)}</span>
        <span class="pick-composite" title="Composite — weighted sum of the 5 sub-scores">${Math.round(p.composite)}</span>
        <span class="pick-bars">
          ${picksMiniBar('VC', p.vc_score)}
          ${picksMiniBar('RS', p.rs_score)}
          ${picksMiniBar('VA', p.va_score)}
          ${picksMiniBar('MT', p.mt_score)}
          ${picksMiniBar('DP', p.dp_score)}
        </span>
        <span class="pick-meta muted">${escapeHtml(metaParts.join(' · '))}</span>
        ${badges ? `<span class="pick-triggers">${badges}</span>` : ''}
      </div>
    `;
  });
  els.picksList.innerHTML = rows.join('');
}

async function loadIntradayAlerts() {
  try {
    const res = await fetch('/api/picks/intraday-alerts', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    const byTicker = {};
    for (const evt of (data.alerts || [])) {
      if (!byTicker[evt.ticker]) byTicker[evt.ticker] = [];
      byTicker[evt.ticker].push(evt);
    }
    _picksIntradayByTicker = byTicker;
  } catch (_) { /* silent */ }
}

// Update an "Alerts: ON/OFF" toggle button — shared by the picks panel
// and the momentum scanner panel. Uses the existing `button.warn` red
// style for the OFF state so it's hard to miss when alerts are paused.
function applyAlertsToggleBtn(btn, enabled) {
  if (!btn) return;
  btn.textContent = enabled ? 'Alerts: ON' : 'Alerts: OFF';
  btn.classList.toggle('warn', !enabled);
}

async function loadPicks() {
  if (!els.picksList) return;
  try {
    // Pull intraday triggers first so the renderer can badge each
    // row in a single pass.
    await loadIntradayAlerts();
    const res = await fetch('/api/picks', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    renderPicks(data);
    if (data && data.config) {
      applyAlertsToggleBtn(
        els.picksAlertsToggleBtn,
        data.config.intraday_alerts_enabled !== false,
      );
    }
  } catch (_) { /* silent */ }
}

async function togglePicksIntradayAlerts() {
  if (!els.picksAlertsToggleBtn) return;
  const next = !els.picksAlertsToggleBtn.textContent.includes('ON');
  els.picksAlertsToggleBtn.disabled = true;
  try {
    const res = await fetch('/api/picks/intraday-alerts/enabled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: next }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus('Toggle failed: ' + (data.error || ('HTTP ' + res.status)));
      return;
    }
    applyAlertsToggleBtn(els.picksAlertsToggleBtn, !!data.enabled);
  } catch (err) {
    setStatus('Toggle failed: ' + (err && err.message ? err.message : 'network error'));
  } finally {
    els.picksAlertsToggleBtn.disabled = false;
  }
}

// Auto-refresh picks every 60s. The intraday cron fires at 5-min
// cadence so anything faster is wasted work; anything slower means
// triggers don't appear in the UI for too long.
let _picksPollTimer = null;
function startPicksPolling() {
  if (_picksPollTimer) return;
  _picksPollTimer = setInterval(() => {
    if (document.visibilityState === 'visible') loadPicks();
  }, 60_000);
}

async function runPicks() {
  if (!els.picksRunBtn) return;
  els.picksRunBtn.disabled = true;
  const prevTxt = els.picksRunBtn.textContent;
  els.picksRunBtn.textContent = 'Ranking…';
  setStatus('Re-ranking watchlist — this may take 5-30s…');
  try {
    const body = {
      weights:   picksWeightFromUI(),
      price_min: Number(els.picksPriceMin && els.picksPriceMin.value) || 0,
      price_max: Number(els.picksPriceMax && els.picksPriceMax.value) || 1000,
      save: true,
    };
    const res = await fetch('/api/picks/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus('Re-rank failed: ' + (data.error || ('HTTP ' + res.status)));
      return;
    }
    renderPicks(data);
    setStatus(`Re-ranked ${data.picks ? data.picks.length : 0} picks for ${data.as_of || '?'}`);
  } catch (err) {
    setStatus('Re-rank failed: ' + (err && err.message ? err.message : 'network error'));
  } finally {
    els.picksRunBtn.disabled = false;
    els.picksRunBtn.textContent = prevTxt;
  }
}

// Update the slider readouts as the user drags.
for (const k of _PICKS_WEIGHT_KEYS) {
  const el = els['picksW' + k];
  const out = els['picksW' + k + 'Out'];
  if (el && out) el.addEventListener('input', () => { out.textContent = el.value; });
}
if (els.picksTuneBtn && els.picksTune) {
  els.picksTuneBtn.addEventListener('click', () => {
    els.picksTune.classList.toggle('hidden');
    els.picksTuneBtn.textContent = els.picksTune.classList.contains('hidden') ? 'Tune…' : 'Hide tuning';
  });
}
if (els.picksRunBtn) els.picksRunBtn.addEventListener('click', runPicks);
if (els.picksAlertsToggleBtn) els.picksAlertsToggleBtn.addEventListener('click', togglePicksIntradayAlerts);
// Click a pick row → open the hover chart for that ticker. The hover
// trigger is narrowed to the ticker span only (data-ticker lives on
// .pick-ticker), but clicking anywhere on the row still works.
if (els.picksList) {
  els.picksList.addEventListener('click', (ev) => {
    const row = ev.target.closest('.pick-row');
    const tickerEl = row && row.querySelector('[data-ticker]');
    if (tickerEl) showHoverChart(tickerEl.dataset.ticker, tickerEl);
  });
  // Same mouseover/mouseout pattern the scanner table uses — the
  // shared onTickerEnter/Leave handlers key off any [data-ticker]
  // ancestor, and .pick-row carries that attribute.
  els.picksList.addEventListener('mouseover', onTickerEnter);
  els.picksList.addEventListener('mouseout', onTickerLeave);
}
wireCollapse(els.picksToggle, els.picksBody, 'collapse_picks');
loadPicks();
startPicksPolling();


// --- real-time momentum scanner ------------------------------------------
// Reads /api/momentum/alerts for today's hits and renders them; persists
// threshold changes via /api/momentum/config. The cron worker
// (scanner_momentum.py) reads the same config and fires Telegram +
// inserts a row here, which the panel picks up on the next poll.

function momentumApplyConfigToUI(cfg) {
  if (!cfg) return;
  if (els.momentumPctChange && cfg.pct_change_min != null)
    els.momentumPctChange.value = String(cfg.pct_change_min);
  if (els.momentumRvol && cfg.rvol_min != null)
    els.momentumRvol.value = String(cfg.rvol_min);
  if (els.momentumRvolLookback && cfg.rvol_lookback != null)
    els.momentumRvolLookback.value = String(cfg.rvol_lookback);
  if (els.momentumHighLookback && cfg.high_lookback != null)
    els.momentumHighLookback.value = String(cfg.high_lookback);
  if (els.momentumVolMcap && cfg.vol_mcap_min != null)
    els.momentumVolMcap.value = String(cfg.vol_mcap_min);
  if (els.momentumMcapMin && cfg.mcap_min_m != null)
    els.momentumMcapMin.value = String(cfg.mcap_min_m);
  if (els.momentumMcapMax && cfg.mcap_max_m != null)
    els.momentumMcapMax.value = String(cfg.mcap_max_m);
}

function momentumConfigFromUI() {
  return {
    pct_change_min: Number(els.momentumPctChange && els.momentumPctChange.value) || 0,
    rvol_min:       Number(els.momentumRvol && els.momentumRvol.value) || 0,
    rvol_lookback:  Number(els.momentumRvolLookback && els.momentumRvolLookback.value) || 0,
    high_lookback:  Number(els.momentumHighLookback && els.momentumHighLookback.value) || 0,
    vol_mcap_min:   Number(els.momentumVolMcap && els.momentumVolMcap.value) || 0,
    mcap_min_m:     Number(els.momentumMcapMin && els.momentumMcapMin.value) || 0,
    mcap_max_m:     Number(els.momentumMcapMax && els.momentumMcapMax.value) || 0,
  };
}

// Per-panel selection state — kept separate from the screener's
// selectedTickers so the two don't trample each other.
let momentumLastAlerts = [];
const momentumSelected = new Set();
let momentumLastDate = null;

function renderMomentumAlerts(alerts) {
  if (!els.momentumList) return;
  alerts = alerts || [];
  momentumLastAlerts = alerts;
  momentumLastDate = alerts.length ? alerts[0].alert_date || null : null;
  // Drop stale picks the server no longer has (e.g., they were
  // cleared in another tab or the day rolled over).
  const visible = new Set(alerts.map((a) => a.ticker));
  for (const t of [...momentumSelected]) {
    if (!visible.has(t)) momentumSelected.delete(t);
  }

  if (els.momentumAsOf) {
    els.momentumAsOf.textContent = alerts.length
      ? `as of ${alerts[0].alert_date || '?'}`
      : '';
  }
  if (els.momentumCount) {
    els.momentumCount.textContent = alerts.length
      ? `${alerts.length} alert${alerts.length === 1 ? '' : 's'} today`
      : '';
  }
  if (!alerts.length) {
    els.momentumList.innerHTML = '<p class="muted history-empty">No alerts yet today. The scanner runs every ~5 min during US market hours.</p>';
    momentumUpdateSelectionUI();
    return;
  }
  const rows = alerts.map((a) => {
    const t   = a.ticker || '';
    const px  = a.price != null ? `$${Number(a.price).toFixed(2)}` : '';
    const pct = a.pct_change != null ? `+${Number(a.pct_change).toFixed(1)}%` : '';
    const rv  = a.rvol != null ? `${Number(a.rvol).toFixed(1)}×` : '';
    const vf  = a.vol_mcap_pct != null ? `${Number(a.vol_mcap_pct).toFixed(2)}%` : '';
    const nh  = a.new_high != null ? `> $${Number(a.new_high).toFixed(2)}` : '';
    const fired = a.fired_at ? formatTriggerTime(a.fired_at) : '';
    const checked = momentumSelected.has(t) ? ' checked' : '';
    return `
      <div class="momentum-row" data-row-ticker="${escapeHtml(t)}">
        <label class="momentum-row-select" title="Select this alert">
          <input type="checkbox" class="momentum-row-cb" data-ticker-select="${escapeHtml(t)}"${checked} />
        </label>
        <span class="momentum-time">${escapeHtml(fired)}</span>
        <span class="momentum-ticker" data-ticker="${escapeHtml(t)}">${escapeHtml(t)}</span>
        <span class="momentum-price">${escapeHtml(px)}</span>
        <span class="momentum-metric momentum-pct" title="% change vs prior trading day's close">${escapeHtml(pct)}</span>
        <span class="momentum-metric" title="Relative volume — today's volume / prior N-day avg">${escapeHtml(rv)} RVOL</span>
        <span class="momentum-metric" title="Today's intraday high broke the prior N-day high">new high ${escapeHtml(nh)}</span>
        <span class="momentum-metric" title="Today's volume / shares outstanding">${escapeHtml(vf)} float</span>
      </div>
    `;
  });
  els.momentumList.innerHTML = rows.join('');
  momentumUpdateSelectionUI();
}

function momentumUpdateSelectionUI() {
  const total = momentumLastAlerts.length;
  const count = momentumSelected.size;
  if (els.momentumSelectionToolbar)
    els.momentumSelectionToolbar.classList.toggle('hidden', total === 0);
  if (els.momentumSelectionCount)
    els.momentumSelectionCount.textContent =
      count === 1 ? '1 selected' : `${count} selected`;
  if (els.momentumClearSelectedBtn)
    els.momentumClearSelectedBtn.disabled = count === 0;
  if (els.momentumClearAllBtn)
    els.momentumClearAllBtn.disabled = total === 0;
  if (els.momentumSelectAll) {
    if (!total) {
      els.momentumSelectAll.checked = false;
      els.momentumSelectAll.indeterminate = false;
    } else {
      const allChecked = momentumLastAlerts.every((a) => momentumSelected.has(a.ticker));
      els.momentumSelectAll.checked = allChecked && count > 0;
      els.momentumSelectAll.indeterminate = count > 0 && !allChecked;
    }
  }
}

async function momentumHide(tickers) {
  try {
    const body = { tickers };
    if (momentumLastDate) body.date = momentumLastDate;
    const res = await fetch('/api/momentum/alerts/hide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setStatus('Clear failed: ' + (data.error || ('HTTP ' + res.status)));
      return;
    }
    // Drop the cleared tickers from the selection set so the next
    // render doesn't try to keep them checked.
    if (tickers && tickers.length) {
      tickers.forEach((t) => momentumSelected.delete(t));
    } else {
      momentumSelected.clear();
    }
    await loadMomentumAlerts();
  } catch (err) {
    setStatus('Clear failed: ' + (err && err.message ? err.message : 'network error'));
  }
}

function momentumClearSelected() {
  if (momentumSelected.size === 0) return;
  momentumHide([...momentumSelected]);
}

function momentumClearAll() {
  if (momentumLastAlerts.length === 0) return;
  if (!window.confirm(`Clear all ${momentumLastAlerts.length} alert(s) for ${momentumLastDate || 'today'}?`)) return;
  // Empty list = "all" on the server side. We still pass the date
  // explicitly so a slow refresh between confirm and POST doesn't
  // accidentally clear a different day's rows.
  momentumHide([]);
}

async function loadMomentumConfig() {
  try {
    const res = await fetch('/api/momentum/config', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    momentumApplyConfigToUI(data.config);
    if (data && data.config) {
      applyAlertsToggleBtn(
        els.momentumAlertsToggleBtn,
        data.config.enabled !== false,
      );
    }
  } catch (_) { /* silent */ }
}

async function toggleMomentumAlerts() {
  if (!els.momentumAlertsToggleBtn) return;
  const next = !els.momentumAlertsToggleBtn.textContent.includes('ON');
  els.momentumAlertsToggleBtn.disabled = true;
  try {
    const res = await fetch('/api/momentum/enabled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: next }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus('Toggle failed: ' + (data.error || ('HTTP ' + res.status)));
      return;
    }
    applyAlertsToggleBtn(els.momentumAlertsToggleBtn, !!data.enabled);
  } catch (err) {
    setStatus('Toggle failed: ' + (err && err.message ? err.message : 'network error'));
  } finally {
    els.momentumAlertsToggleBtn.disabled = false;
  }
}

async function loadMomentumAlerts() {
  if (!els.momentumList) return;
  try {
    const res = await fetch('/api/momentum/alerts', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    renderMomentumAlerts(data.alerts || []);
  } catch (_) { /* silent */ }
}

async function saveMomentumConfig() {
  if (!els.momentumSaveBtn) return;
  const prevTxt = els.momentumSaveBtn.textContent;
  els.momentumSaveBtn.disabled = true;
  els.momentumSaveBtn.textContent = 'Saving…';
  if (els.momentumSaveMsg) els.momentumSaveMsg.textContent = '';
  try {
    const res = await fetch('/api/momentum/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(momentumConfigFromUI()),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (els.momentumSaveMsg) els.momentumSaveMsg.textContent = 'Save failed: ' + (data.error || ('HTTP ' + res.status));
      return;
    }
    momentumApplyConfigToUI(data.config);
    if (els.momentumSaveMsg) {
      els.momentumSaveMsg.textContent = 'Saved.';
      setTimeout(() => { if (els.momentumSaveMsg) els.momentumSaveMsg.textContent = ''; }, 2500);
    }
  } catch (err) {
    if (els.momentumSaveMsg) els.momentumSaveMsg.textContent = 'Save failed: ' + (err && err.message ? err.message : 'network error');
  } finally {
    els.momentumSaveBtn.disabled = false;
    els.momentumSaveBtn.textContent = prevTxt;
  }
}

// Auto-refresh alerts every 60s — cron fires at 5-min cadence so
// anything faster is wasted work.
let _momentumPollTimer = null;
function startMomentumPolling() {
  if (_momentumPollTimer) return;
  _momentumPollTimer = setInterval(() => {
    if (document.visibilityState === 'visible') loadMomentumAlerts();
  }, 60_000);
}

if (els.momentumSaveBtn) els.momentumSaveBtn.addEventListener('click', saveMomentumConfig);
if (els.momentumAlertsToggleBtn) els.momentumAlertsToggleBtn.addEventListener('click', toggleMomentumAlerts);

function refreshMomentumDiagnoseDates(dates, keepSelected) {
  const sel = els.momentumDiagnoseDate;
  if (!sel || !Array.isArray(dates)) return;
  const want = keepSelected != null ? String(keepSelected) : sel.value;
  // Always keep "Today (live)" as the first option; replace the rest.
  while (sel.options.length > 1) sel.remove(1);
  for (const d of dates) {
    const o = document.createElement('option');
    o.value = d;
    o.textContent = d;
    sel.appendChild(o);
  }
  if (want && Array.from(sel.options).some(o => o.value === want)) {
    sel.value = want;
  }
}

function renderMomentumDiagnose(r) {
  if (!els.momentumDiagnoseOut) return;
  if (els.momentumDiagnoseClearBtn) els.momentumDiagnoseClearBtn.disabled = false;
  if (!r || r.error) {
    els.momentumDiagnoseOut.classList.remove('hidden');
    els.momentumDiagnoseOut.innerHTML =
      `<p class="muted">${escapeHtml((r && r.error) || 'Diagnose failed.')}</p>`;
    return;
  }
  if (Array.isArray(r.available_dates) && r.available_dates.length) {
    refreshMomentumDiagnoseDates(r.available_dates);
  }
  const fmt = (v, unit, digits) => {
    if (v === null || v === undefined || !Number.isFinite(v)) return '—';
    if (unit === 'M$') {
      // Compact dollar formatter for market-cap values stored in $M.
      const dollars = Number(v) * 1e6;
      const a = Math.abs(dollars);
      if (a >= 1e12) return '$' + (dollars / 1e12).toFixed(2) + 'T';
      if (a >= 1e9)  return '$' + (dollars / 1e9).toFixed(2)  + 'B';
      if (a >= 1e6)  return '$' + (dollars / 1e6).toFixed(0)  + 'M';
      return '$' + Math.round(dollars).toLocaleString();
    }
    return unit === '$' ? '$' + Number(v).toFixed(digits ?? 2)
         : unit === 'x' ? Number(v).toFixed(digits ?? 2) + '×'
         : unit === '%' ? Number(v).toFixed(digits ?? 2) + '%'
         : String(v);
  };
  const headerCls = r.passes_all
    ? (r.already_fired ? 'momentum-diag-header muted' : 'momentum-diag-header pass')
    : 'momentum-diag-header fail';
  // Four states worth distinguishing in the badge — source matters
  // because Alpaca-IEX intraday volume is a tiny fraction of SIP, so
  // a "live (Alpaca-IEX)" RVOL number is not directly comparable to
  // the snapshot's EOD value.
  let modeLabel = 'live';
  if (r.mode === 'historical') modeLabel = 'historical EOD';
  else if (r.source === 'snapshot') modeLabel = 'today EOD';
  else if (r.source === 'yahoo') modeLabel = 'live (Yahoo)';
  else if (r.source === 'alpaca-iex') modeLabel = 'live (Alpaca-IEX)';
  const modeBadge = ` <span class="muted">· ${modeLabel} · ${escapeHtml(r.today || '')}</span>`;
  const header = `
    <div class="${headerCls}">
      <strong>${escapeHtml(r.ticker)}</strong>${modeBadge}<br>
      ${escapeHtml(r.reason || '')}
    </div>`;

  const ctxRows = [];
  if (r.as_of_baseline)
    ctxRows.push(`Baseline from snapshot: <code>${escapeHtml(r.as_of_baseline)}</code>`);
  if (r.baseline) {
    ctxRows.push(
      `Prior close <code>${fmt(r.baseline.prior_close, '$')}</code> · ` +
      `avg vol <code>${Math.round(r.baseline.avg_vol).toLocaleString()}</code> · ` +
      `${r.config.high_lookback}-day high <code>${fmt(r.baseline.high_n, '$')}</code> · ` +
      `shares <code>${Math.round(r.baseline.shares).toLocaleString()}</code>`
    );
  }
  if (r.today_bar) {
    ctxRows.push(
      `Today price <code>${fmt(r.today_bar.price, '$')}</code> · ` +
      `today high <code>${fmt(r.today_bar.today_high, '$')}</code> · ` +
      `today vol <code>${Math.round(r.today_bar.today_vol).toLocaleString()}</code>`
    );
  }
  if (r.already_fired)
    ctxRows.push(`<strong>Already fired today</strong> — dedupe blocks a second alert.`);
  const ctx = ctxRows.length
    ? `<div class="momentum-diag-context">${ctxRows.map(s => `<div>${s}</div>`).join('')}</div>`
    : '';

  const rows = (r.filters || []).map((f) => {
    const tick = f.passes ? '✓' : '✗';
    const cls = f.passes ? 'pass' : 'fail';
    const measured = fmt(f.measured, f.unit);
    let threshold;
    if (f.name === 'new_high') threshold = `> ${fmt(f.threshold, f.unit)}`;
    else if (f.name === 'mcap_band')
      threshold = `${fmt(f.threshold, f.unit)} – ${fmt(f.threshold_max, f.unit)}`;
    else threshold = `≥ ${fmt(f.threshold, f.unit)}`;
    // Show the raw inputs to each ratio so the reader doesn't have to
    // back-solve them from the context block. Only render if we have
    // both today_bar and baseline (i.e. we got past every eligibility
    // gate); otherwise leave blank.
    let detail = '';
    if (r.today_bar && r.baseline) {
      const tb = r.today_bar, bl = r.baseline;
      const px = (v) => '$' + Number(v).toFixed(2);
      const vol = (v) => Math.round(v).toLocaleString();
      if (f.name === 'pct_change') {
        detail = `current price ${px(tb.price)} vs prior close ${px(bl.prior_close)}`;
      } else if (f.name === 'rvol') {
        detail = `today's vol ${vol(tb.today_vol)} ÷ ${r.config.rvol_lookback}-day avg ${vol(bl.avg_vol)}`;
      } else if (f.name === 'new_high') {
        detail = `today's high ${px(tb.today_high)} vs prior ${r.config.high_lookback}-day max ${px(bl.high_n)}`;
      } else if (f.name === 'vol_mcap') {
        detail = `today's vol ${vol(tb.today_vol)} ÷ shares outstanding ${vol(bl.shares)}`;
      } else if (f.name === 'mcap_band') {
        detail = `shares ${vol(bl.shares)} × current price ${px(tb.price)}`;
      }
    }
    const detailHtml = detail
      ? `<div class="momentum-diag-detail muted">${escapeHtml(detail)}</div>`
      : '';
    return `
      <div class="momentum-diag-row ${cls}">
        <span class="momentum-diag-tick">${tick}</span>
        <span class="momentum-diag-label">${escapeHtml(f.label)}${detailHtml}</span>
        <span class="momentum-diag-measured">${measured}</span>
        <span class="momentum-diag-threshold muted">${threshold}</span>
      </div>`;
  }).join('');

  els.momentumDiagnoseOut.classList.remove('hidden');
  els.momentumDiagnoseOut.innerHTML = header + ctx + (rows
    ? `<div class="momentum-diag-grid">${rows}</div>`
    : '');
}

async function runMomentumDiagnose() {
  if (!els.momentumDiagnoseBtn || !els.momentumDiagnoseTicker) return;
  const ticker = (els.momentumDiagnoseTicker.value || '').trim().toUpperCase();
  if (!ticker) {
    if (els.momentumDiagnoseStatus) els.momentumDiagnoseStatus.textContent = 'Enter a ticker first.';
    return;
  }
  const date = els.momentumDiagnoseDate ? (els.momentumDiagnoseDate.value || '').trim() : '';
  const prevTxt = els.momentumDiagnoseBtn.textContent;
  els.momentumDiagnoseBtn.disabled = true;
  els.momentumDiagnoseBtn.textContent = 'Checking…';
  if (els.momentumDiagnoseStatus) els.momentumDiagnoseStatus.textContent = '';
  try {
    let url = '/api/momentum/diagnose?ticker=' + encodeURIComponent(ticker);
    if (date) url += '&date=' + encodeURIComponent(date);
    const res = await fetch(url, { cache: 'no-store' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      renderMomentumDiagnose({ error: data.error || ('HTTP ' + res.status) });
      return;
    }
    renderMomentumDiagnose(data);
  } catch (err) {
    renderMomentumDiagnose({ error: (err && err.message) || 'network error' });
  } finally {
    els.momentumDiagnoseBtn.disabled = false;
    els.momentumDiagnoseBtn.textContent = prevTxt;
  }
}

function clearMomentumDiagnose() {
  if (els.momentumDiagnoseOut) {
    els.momentumDiagnoseOut.classList.add('hidden');
    els.momentumDiagnoseOut.innerHTML = '';
  }
  if (els.momentumDiagnoseStatus) els.momentumDiagnoseStatus.textContent = '';
  if (els.momentumDiagnoseTicker) els.momentumDiagnoseTicker.value = '';
  if (els.momentumDiagnoseDate) els.momentumDiagnoseDate.value = '';
  refreshMomentumDiagnoseDates([]);
  if (els.momentumDiagnoseClearBtn) els.momentumDiagnoseClearBtn.disabled = true;
}

if (els.momentumDiagnoseBtn) els.momentumDiagnoseBtn.addEventListener('click', runMomentumDiagnose);
if (els.momentumDiagnoseClearBtn) els.momentumDiagnoseClearBtn.addEventListener('click', clearMomentumDiagnose);
if (els.momentumDiagnoseTicker) {
  els.momentumDiagnoseTicker.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); runMomentumDiagnose(); }
  });
}
if (els.momentumDiagnoseDate) {
  els.momentumDiagnoseDate.addEventListener('change', () => {
    const t = (els.momentumDiagnoseTicker && els.momentumDiagnoseTicker.value || '').trim();
    if (t) runMomentumDiagnose();
  });
}
wireCollapse(
  els.momentumDiagnoseToggle,
  [els.momentumDiagnoseBody, els.momentumDiagnoseOut],
  'collapse_momentum_diagnose',
);

if (els.momentumList) {
  els.momentumList.addEventListener('click', (ev) => {
    // Checkbox interactions update the selection set instead of
    // opening the chart.
    const cb = ev.target.closest('input.momentum-row-cb');
    if (cb) {
      const t = cb.dataset.tickerSelect;
      if (t) {
        if (cb.checked) momentumSelected.add(t);
        else momentumSelected.delete(t);
        momentumUpdateSelectionUI();
      }
      return;
    }
    // Click anywhere else on the row opens the chart, but the hover
    // trigger is narrowed to the ticker span only (so passing the
    // mouse over the metrics doesn't pop the chart).
    const row = ev.target.closest('.momentum-row');
    const tickerEl = row && row.querySelector('[data-ticker]');
    if (tickerEl) showHoverChart(tickerEl.dataset.ticker, tickerEl);
  });
  els.momentumList.addEventListener('mouseover', onTickerEnter);
  els.momentumList.addEventListener('mouseout', onTickerLeave);
}
if (els.momentumSelectAll) {
  els.momentumSelectAll.addEventListener('change', () => {
    if (els.momentumSelectAll.checked) {
      momentumLastAlerts.forEach((a) => momentumSelected.add(a.ticker));
    } else {
      momentumSelected.clear();
    }
    renderMomentumAlerts(momentumLastAlerts);
  });
}
if (els.momentumClearSelectedBtn)
  els.momentumClearSelectedBtn.addEventListener('click', momentumClearSelected);
if (els.momentumClearAllBtn)
  els.momentumClearAllBtn.addEventListener('click', momentumClearAll);
wireCollapse(els.momentumToggle, els.momentumBody, 'collapse_momentum');
loadMomentumConfig();
loadMomentumAlerts();
startMomentumPolling();


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
if (els.setupsCreateAlertBtn) {
  els.setupsCreateAlertBtn.addEventListener('click', () => {
    // Pre-populate the rule-create row with setup type + 'all' scope, then
    // scroll the user to it so they can name the rule and submit.
    if (els.ruleType) els.ruleType.value = 'setup';
    if (els.ruleScopeType) {
      els.ruleScopeType.value = 'all';
      populateScopeValues();
    }
    syncRuleTypeUI();
    if (els.ruleName) {
      els.ruleName.focus();
      els.ruleName.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    setRulesMsg('Name this setup alert, then click "Create rule".');
  });
}

// 'All' scope is setup-only — toggle its visibility, default the scope to
// the most useful value for the chosen rule type ('all' for Setup, since
// setups are EOD and the snapshot pre-filter keeps it cheap; 'watchlist'
// Both rule types now route their Create flow through the criteria
// modal, so the inline name + scope inputs are unused. The rule-type
// selector remains as a quick toggle for which modal mode to open.
function syncRuleTypeUI() {
  const isSetup = els.ruleType && els.ruleType.value === 'setup';
  if (els.ruleCreateBtn) {
    els.ruleCreateBtn.textContent = isSetup
      ? 'Create setup rule…'
      : 'Create screener rule…';
    els.ruleCreateBtn.title = isSetup
      ? 'Open the dialog to pick scope and setup score / price / volume thresholds'
      : 'Open the dialog to pick scope and screener filter criteria';
  }
  // Inline name + scope inputs are now redundant — the modal collects
  // them for both rule types. Keep them in the DOM for back-compat with
  // anything that reads their values, but hide them visually.
  if (els.ruleName) els.ruleName.style.display = 'none';
  if (els.ruleScopeType) els.ruleScopeType.style.display = 'none';
  if (els.ruleScopeValue) els.ruleScopeValue.style.display = 'none';
}
if (els.ruleType) els.ruleType.addEventListener('change', syncRuleTypeUI);
syncRuleTypeUI();

wireCollapse(els.setupsToggle, els.setupsBody, 'collapse_setups');


// --- options recommender (composite-score) -------------------------------
// Type a ticker (and optional DTE range), get a weighted-composite-score
// recommendation: 5 layers × weights → 0-100 → verdict + contract + prose.

const _OPTIONS_VERDICT_GLYPH = { BUY: '🟢', WATCH: '🟡', PASS: '🔴' };
const _OPTIONS_DIR_GLYPH     = { call: '📈', put: '📉' };
const _LAYER_LABELS = {
  price:         { label: 'Price Trajectory', desc: 'RSI · MACD · EMA stack · volume spike' },
  catalyst:      { label: 'Catalyst Events',  desc: 'earnings timing · analyst actions · news' },
  institutional: { label: 'Institutional',    desc: 'insider Form 4 · analyst sentiment' },
  fundamentals:  { label: 'Fundamentals',     desc: 'revenue growth · P/E reasonableness' },
  sector:        { label: 'Sector Trend',     desc: 'sector ETF 5d vs SPY 5d' },
};

function compositeColorClass(score) {
  if (score == null) return 'composite-neutral';
  if (score >= 75) return 'composite-strong-bull';
  if (score >= 65) return 'composite-bull';
  if (score >= 50) return 'composite-mild-bull';
  if (score > 35)  return 'composite-mild-bear';
  if (score > 25)  return 'composite-bear';
  return 'composite-strong-bear';
}

function renderCompositeBar(score, verdict) {
  if (score == null) return '';
  const pct = Math.max(0, Math.min(100, score));
  const cls = compositeColorClass(score);
  return `
    <div class="composite-bar-wrap">
      <div class="composite-bar ${cls}">
        <div class="composite-fill" style="width:${pct}%"></div>
        <div class="composite-thresh thresh-put"  style="left:35%" title="≤ 35 → BUY PUT"></div>
        <div class="composite-thresh thresh-call" style="left:65%" title="≥ 65 → BUY CALL"></div>
        <div class="composite-marker" style="left:${pct}%"></div>
      </div>
      <div class="composite-bar-labels muted">
        <span>0</span><span>35 (put)</span><span>50</span><span>65 (call)</span><span>100</span>
      </div>
    </div>`;
}

function renderLayerBreakdown(layers) {
  if (!layers || typeof layers !== 'object') return '';
  const rows = Object.entries(_LAYER_LABELS).map(([key, meta]) => {
    const layer = layers[key];
    if (!layer) return '';
    const score = Number(layer.score);
    const weight = Math.round((layer.weight ?? 0) * 100);
    const pct = Math.max(0, Math.min(100, score));
    const cls = compositeColorClass(score);
    const partial = layer.partial ? ' <span class="layer-partial-badge" title="Some sub-signals require paid data feeds we don\'t have access to (dark pool prints, unusual options flow, 13F).">partial data</span>' : '';
    const subs = layer.sub_scores
      ? Object.entries(layer.sub_scores).map(([k, v]) => `${k.replace(/_/g, ' ')} ${Math.round(v)}`).join(' · ')
      : '';
    return `
      <div class="layer-row">
        <div class="layer-row-head">
          <span class="layer-name"><b>${escapeHtml(meta.label)}</b> ${partial}<br><span class="muted">${escapeHtml(meta.desc)}</span></span>
          <span class="layer-score"><b>${Math.round(score)}</b><span class="muted"> / 100 · ${weight}%</span></span>
        </div>
        <div class="layer-bar ${cls}"><div class="layer-fill" style="width:${pct}%"></div></div>
        <div class="layer-subs muted">${escapeHtml(subs)}</div>
      </div>`;
  }).join('');
  return `<div class="layer-breakdown">${rows}</div>`;
}

function renderOptionsResult(rec) {
  if (!els.optionsResult) return;
  if (els.optionsClearBtn) els.optionsClearBtn.disabled = false;
  els.optionsResult.classList.remove('hidden');
  if (!rec || rec.error) {
    els.optionsResult.innerHTML = `<p class="muted">${escapeHtml((rec && rec.error) || 'Analysis failed.')}</p>`;
    return;
  }

  const verdict = rec.verdict || 'PASS';
  const verdictGlyph = _OPTIONS_VERDICT_GLYPH[verdict] || '⚪';
  const dirGlyph = _OPTIONS_DIR_GLYPH[rec.direction] || '·';
  const conviction = rec.conviction || 'none';
  const score = rec.composite_score;

  const header = `
    <div class="options-result-header verdict-${verdict.toLowerCase()}">
      <span class="options-verdict">${verdictGlyph} <b>${verdict}</b></span>
      ${rec.direction ? `<span class="options-direction">${dirGlyph} <b>${rec.direction.toUpperCase()}</b></span>` : ''}
      <span class="options-ticker-name"><b>${escapeHtml(rec.ticker)}</b></span>
      <span class="muted">· composite <b>${score != null ? Math.round(score) : '—'}</b>/100</span>
      ${conviction !== 'none' ? `<span class="muted">· ${escapeHtml(conviction)} conviction</span>` : ''}
      ${rec.post_earnings_override ? '<span class="badge-override" title="Expiry shifted to 7-10 days after the next earnings date to avoid IV crush.">post-earnings expiry</span>' : ''}
    </div>`;

  const compositeBar = renderCompositeBar(score, verdict);

  const prose = rec.prose_rationale
    ? `<div class="options-prose">${escapeHtml(rec.prose_rationale)}</div>`
    : '';

  let contractCard = '';
  if (rec.contract) {
    const c = rec.contract;
    contractCard = `
      <div class="options-contract-card">
        <div class="options-contract-line">
          <span class="muted">Suggested contract:</span>
          <span><b>${escapeHtml(c.contract_symbol || '')}</b></span>
        </div>
        <div class="options-contract-grid">
          <div><span class="muted">Strike</span><span>$${fmtNum(c.strike, 2)}</span></div>
          <div><span class="muted">Expiration</span><span>${escapeHtml(c.expiration || '')}</span></div>
          <div><span class="muted">DTE</span><span>${c.dte ?? '—'}d</span></div>
          <div><span class="muted">Delta</span><span>${c.delta != null ? (c.delta >= 0 ? '+' : '') + fmtNum(c.delta, 3) : '—'}</span></div>
          <div><span class="muted">Mid</span><span>$${fmtNum(c.mid, 2)}</span></div>
          <div><span class="muted">IV</span><span>${c.iv != null ? fmtNum(c.iv * 100, 1) + '%' : '—'}</span></div>
          <div><span class="muted">OI</span><span>${c.open_interest != null ? Math.round(c.open_interest).toLocaleString() : '—'}</span></div>
        </div>
        ${rec.earnings_spans_expiration ? '<div class="options-warn">⚠ Contract spans the next earnings date — IV crush risk after the announcement; consider closing before.</div>' : ''}
      </div>`;
  } else if (rec.reason) {
    contractCard = `<div class="options-reason muted">${escapeHtml(rec.reason)}</div>`;
  }

  const layerBreakdown = renderLayerBreakdown(rec.layers);

  const ivc = rec.iv_context || {};
  const ivLine = ivc.regime && ivc.regime !== 'unknown'
    ? `<div class="options-iv-context muted">
         IV regime: <b>${escapeHtml(ivc.regime)}</b>
         · ATM IV ${ivc.atm_iv != null ? fmtNum(ivc.atm_iv * 100, 1) + '%' : '—'}
         · 20d realized ${ivc.realized_vol_20d != null ? fmtNum(ivc.realized_vol_20d * 100, 1) + '%' : '—'}
         · ratio ${ivc.ratio != null ? fmtNum(ivc.ratio, 2) : '—'}
       </div>`
    : '';

  const earningsLine = rec.earnings_date
    ? `<div class="options-earnings muted">Next earnings: <b>${escapeHtml(rec.earnings_date)}</b>${rec.post_earnings_override ? ' (expiry adjusted)' : ''}</div>`
    : '';

  const reasons = Array.isArray(rec.reasons) && rec.reasons.length
    ? `<details class="options-reasons">
         <summary class="muted">Signal-level reasons (${rec.reasons.length})</summary>
         <ul>${rec.reasons.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul>
       </details>`
    : '';

  const partialNote = rec.partial_data_note
    ? `<div class="options-partial-note muted"><i>${escapeHtml(rec.partial_data_note)}</i></div>`
    : '';

  const disclaimer = rec.disclaimer
    ? `<div class="options-disclaimer-inline muted"><i>${escapeHtml(rec.disclaimer)}</i></div>`
    : '';

  els.optionsResult.innerHTML =
    header + compositeBar + prose + contractCard + layerBreakdown + ivLine + earningsLine + reasons + partialNote + disclaimer;
}

// Pinned recs index keyed by `${ticker}|${as_of}` so the row renderer
// can decorate pinned entries with the filled button + note input. Also
// stores the pin id, needed for PATCH/DELETE. Rebuilt on every poll of
// /api/options/pinned.
const _pinnedIndex = new Map();

// Currently-selected view ("all" | "pinned") for the history panel.
// Driven by the radio buttons; persisted to localStorage so it survives
// reloads.
const _OH_VIEW_KEY = 'options_history_view';
let _ohView = (() => {
  try { return localStorage.getItem(_OH_VIEW_KEY) || 'all'; }
  catch (_) { return 'all'; }
})();

function _ohPinKey(ticker, as_of) {
  return `${(ticker || '').toUpperCase()}|${as_of || ''}`;
}

function _renderOptionsHistoryRow(r, opts) {
  opts = opts || {};
  const verdict = r.verdict || 'PASS';
  const glyph = _OPTIONS_VERDICT_GLYPH[verdict] || '⚪';
  const dir = (r.direction || '').toUpperCase();
  const dirGlyph = _OPTIONS_DIR_GLYPH[r.direction] || '·';
  const strikeStr = r.strike != null ? `$${fmtNum(r.strike, 2)}` : '';
  const midStr = r.mid_price != null ? `mid $${fmtNum(r.mid_price, 2)}` : '';
  const compositeStr = r.composite_score != null
    ? `composite ${Math.round(r.composite_score)}` : '';
  const ticker = r.ticker || '';
  const as_of = r.as_of || '';
  const pinKey = _ohPinKey(ticker, as_of);
  const pin = _pinnedIndex.get(pinKey);
  const isPinned = !!pin;
  // Always include the date alongside the rec — when viewing pinned-only
  // (which spans dates), the date is the main thing telling rows apart.
  const dateStr = as_of ? `<span class="muted">${escapeHtml(as_of)}</span>` : '';
  const pinBtn = `<button type="button" class="pin-btn ${isPinned ? 'pinned' : ''}" data-action="pin" data-ticker="${escapeHtml(ticker)}" data-as-of="${escapeHtml(as_of)}" data-pin-id="${pin ? pin.id : ''}" title="${isPinned ? 'Unpin this recommendation' : 'Pin so it stays accessible across days'}">📌${isPinned ? ' Pinned' : ' Pin'}</button>`;
  const pinnedMeta = isPinned && pin && pin.pinned_at
    ? `<span class="pinned-meta">📌 pinned ${escapeHtml(pin.pinned_at.slice(0, 16).replace('T', ' '))}</span>`
    : '';
  const noteInput = isPinned
    ? `<input type="text" class="pin-note" data-action="note" data-pin-id="${pin.id}" placeholder="Add a note…" value="${escapeHtml(pin.note || '')}" />`
    : '';
  return `
    <div class="options-history-row verdict-${verdict.toLowerCase()}" data-ticker="${escapeHtml(ticker)}" data-as-of="${escapeHtml(as_of)}">
      <span class="options-history-verdict">${glyph} <b>${verdict}</b></span>
      <span class="options-history-dir">${dirGlyph} ${dir}</span>
      <span class="options-history-ticker"><b>${escapeHtml(ticker)}</b></span>
      ${dateStr}
      <span class="muted">${escapeHtml(r.expiration || '')} ${strikeStr}</span>
      <span class="muted">${midStr}</span>
      <span class="muted">${compositeStr}</span>
      ${pinBtn}
      ${pinnedMeta}
      ${noteInput}
    </div>`;
}

function renderOptionsHistory(items, opts) {
  if (!els.optionsHistoryList) return;
  items = items || [];
  opts = opts || {};
  const view = opts.view || _ohView;
  const dateLabel = opts.dateLabel || (items.length ? items[0].as_of : '?');
  if (els.optionsHistoryStatus) {
    els.optionsHistoryStatus.textContent = items.length
      ? (view === 'pinned'
          ? `(${items.length} pinned)`
          : `(${items.length} for ${dateLabel})`)
      : (view === 'pinned'
          ? '(no pinned recs yet — click 📌 on any row to keep it here)'
          : '(none yet — run a scan or analyze a ticker)');
  }
  els.optionsHistoryList.innerHTML = items.map((r) => _renderOptionsHistoryRow(r)).join('');
}

function _readDteRange() {
  const min = parseInt((els.optionsDteMin && els.optionsDteMin.value) || '15', 10);
  const max = parseInt((els.optionsDteMax && els.optionsDteMax.value) || '60', 10);
  if (!Number.isFinite(min) || min < 1) return [15, 60];
  if (!Number.isFinite(max) || max <= min) return [min, min + 1];
  return [min, max];
}

async function runOptionsLookup() {
  if (!els.optionsLookupBtn || !els.optionsTicker) return;
  const ticker = (els.optionsTicker.value || '').trim().toUpperCase();
  if (!ticker) {
    if (els.optionsStatus) els.optionsStatus.textContent = 'Enter a ticker first.';
    return;
  }
  const [dteMin, dteMax] = _readDteRange();
  const prevTxt = els.optionsLookupBtn.textContent;
  els.optionsLookupBtn.disabled = true;
  els.optionsLookupBtn.textContent = 'Analyzing…';
  if (els.optionsStatus) els.optionsStatus.textContent = '';
  try {
    const url = `/api/options/lookup?ticker=${encodeURIComponent(ticker)}&dte_min=${dteMin}&dte_max=${dteMax}`;
    const res = await fetch(url, { cache: 'no-store' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      renderOptionsResult({ error: data.error || ('HTTP ' + res.status), ticker });
      return;
    }
    renderOptionsResult(data);
    loadOptionsHistory();
  } catch (err) {
    renderOptionsResult({ error: (err && err.message) || 'network error', ticker });
  } finally {
    els.optionsLookupBtn.disabled = false;
    els.optionsLookupBtn.textContent = prevTxt;
  }
}

function clearOptionsResult() {
  if (els.optionsResult) {
    els.optionsResult.classList.add('hidden');
    els.optionsResult.innerHTML = '';
  }
  if (els.optionsTicker) els.optionsTicker.value = '';
  if (els.optionsStatus) els.optionsStatus.textContent = '';
  if (els.optionsClearBtn) els.optionsClearBtn.disabled = true;
}

function resetDteRange() {
  if (els.optionsDteMin) els.optionsDteMin.value = '15';
  if (els.optionsDteMax) els.optionsDteMax.value = '60';
}

async function _fetchPinned() {
  // Refreshes _pinnedIndex from the server. Always called before
  // rendering so pin button state + note values stay in sync.
  try {
    const res = await fetch('/api/options/pinned', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    _pinnedIndex.clear();
    for (const pin of data.pinned || []) {
      // Each pin's full snapshot is also a complete rec dict — index
      // by (ticker, as_of) so we can decorate matching rows in the
      // by-date view AND list them in the pinned-only view.
      _pinnedIndex.set(_ohPinKey(pin.ticker, pin.as_of), pin);
    }
  } catch (_) { /* silent */ }
}

async function _fetchDates() {
  try {
    const res = await fetch('/api/options/recommendation_dates', { cache: 'no-store' });
    if (!res.ok) return [];
    const data = await res.json();
    return data.dates || [];
  } catch (_) { return []; }
}

function _populateDatePicker(dates, selectedDate) {
  if (!els.optionsHistoryDate) return;
  const prev = selectedDate || els.optionsHistoryDate.value;
  els.optionsHistoryDate.innerHTML = dates.map(
    (d) => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`
  ).join('') || `<option value="">(no dates)</option>`;
  // Restore selection if still present; else fall back to most recent.
  if (prev && dates.indexOf(prev) >= 0) {
    els.optionsHistoryDate.value = prev;
  } else if (dates.length) {
    els.optionsHistoryDate.value = dates[0];
  }
}

async function loadOptionsHistory(opts) {
  // Two-mode loader. View "all": pull recs for the selected date and
  // render with the pinned overlay. View "pinned": render directly
  // from _pinnedIndex (no date fetch — pins span dates).
  opts = opts || {};
  await _fetchPinned();   // always — so pin decorations stay fresh
  if (_ohView === 'pinned') {
    // List the frozen snapshots in pinned_at-desc order (server already
    // returns them that way). Show the date column so cross-date pins
    // are easy to tell apart.
    const items = Array.from(_pinnedIndex.values())
      .sort((a, b) => (b.pinned_at || '').localeCompare(a.pinned_at || ''))
      .map((pin) => ({ ...pin.snapshot, as_of: pin.as_of, ticker: pin.ticker }));
    renderOptionsHistory(items, { view: 'pinned' });
    return;
  }
  // View "all": refresh date list (cheap), pick a date, fetch its recs.
  const dates = await _fetchDates();
  _populateDatePicker(dates, opts.selectDate);
  const picked = (els.optionsHistoryDate && els.optionsHistoryDate.value) || '';
  if (!picked) {
    renderOptionsHistory([], { view: 'all', dateLabel: '?' });
    return;
  }
  try {
    const res = await fetch(`/api/options/recommendations?date=${encodeURIComponent(picked)}`,
                            { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    renderOptionsHistory(data.recommendations || [], { view: 'all', dateLabel: picked });
  } catch (_) { /* silent */ }
}

// --- tab switching --------------------------------------------------------
function activateTab(name, persist = true) {
  const isOptions = name === 'options';
  if (els.tabStock)       els.tabStock.classList.toggle('hidden', isOptions);
  if (els.tabOptions)     els.tabOptions.classList.toggle('hidden', !isOptions);
  if (els.tabBtnStock) {
    els.tabBtnStock.classList.toggle('active', !isOptions);
    els.tabBtnStock.setAttribute('aria-selected', !isOptions);
  }
  if (els.tabBtnOptions) {
    els.tabBtnOptions.classList.toggle('active', isOptions);
    els.tabBtnOptions.setAttribute('aria-selected', isOptions);
  }
  // Hide the global "Run screen" + Warm cache buttons on the options tab —
  // they belong to the stock-screener pipeline. Status text stays visible.
  const runBtn  = document.getElementById('run-btn');
  const warmBtn = document.getElementById('warm-btn');
  if (runBtn)  runBtn.classList.toggle('hidden', isOptions);
  if (warmBtn) warmBtn.classList.toggle('hidden', isOptions);
  if (persist) {
    try { localStorage.setItem('app_tab', name); } catch (_) {}
    if (history && history.replaceState) {
      const hash = isOptions ? '#options' : '#stock';
      if (location.hash !== hash) history.replaceState(null, '', hash);
    }
  }
}

function _initialTab() {
  const fromHash = (location.hash || '').replace('#', '');
  if (fromHash === 'options' || fromHash === 'stock') return fromHash;
  try { return localStorage.getItem('app_tab') || 'stock'; } catch (_) { return 'stock'; }
}

if (els.tabBtnStock)   els.tabBtnStock  .addEventListener('click', () => activateTab('stock'));
if (els.tabBtnOptions) els.tabBtnOptions.addEventListener('click', () => activateTab('options'));
activateTab(_initialTab(), false);

if (els.optionsLookupBtn)   els.optionsLookupBtn  .addEventListener('click', runOptionsLookup);
if (els.optionsClearBtn)    els.optionsClearBtn   .addEventListener('click', clearOptionsResult);
if (els.optionsResetDteBtn) els.optionsResetDteBtn.addEventListener('click', resetDteRange);
if (els.optionsTicker) {
  els.optionsTicker.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); runOptionsLookup(); }
  });
}
if (els.optionsDteMin) {
  els.optionsDteMin.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); runOptionsLookup(); }
  });
}
if (els.optionsDteMax) {
  els.optionsDteMax.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); runOptionsLookup(); }
  });
}
async function _togglePin(ticker, as_of, currentPinId) {
  if (currentPinId) {
    // Unpin
    try {
      await fetch(`/api/options/pinned/${currentPinId}`, { method: 'DELETE' });
    } catch (_) { /* silent */ }
  } else {
    // Pin (snapshot the rec server-side)
    try {
      await fetch('/api/options/pinned', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, as_of }),
      });
    } catch (_) { /* silent */ }
  }
  await loadOptionsHistory();   // refresh both index + render
}

// Debounce note updates so we PATCH once after the user stops typing.
const _noteDebounces = new Map();
function _savePinNote(pinId, note) {
  clearTimeout(_noteDebounces.get(pinId));
  _noteDebounces.set(pinId, setTimeout(async () => {
    try {
      await fetch(`/api/options/pinned/${pinId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note }),
      });
      // Refresh the index so a subsequent re-render keeps the value.
      // No re-render needed — the input the user is typing in stays as-is.
      await _fetchPinned();
    } catch (_) { /* silent */ }
  }, 600));
}

if (els.optionsHistoryList) {
  els.optionsHistoryList.addEventListener('click', (ev) => {
    // Pin/unpin button — handle before the row-click → analyze path.
    const pinBtn = ev.target.closest('button[data-action="pin"]');
    if (pinBtn) {
      ev.stopPropagation();
      const id = pinBtn.dataset.pinId ? parseInt(pinBtn.dataset.pinId, 10) : null;
      _togglePin(pinBtn.dataset.ticker, pinBtn.dataset.asOf, id);
      return;
    }
    // Clicking the note input shouldn't trigger the row-level analyze.
    if (ev.target.closest('input.pin-note')) return;
    const row = ev.target.closest('.options-history-row');
    if (row && row.dataset.ticker && els.optionsTicker) {
      els.optionsTicker.value = row.dataset.ticker;
      runOptionsLookup();
    }
  });
  // Debounced note PATCH on input.
  els.optionsHistoryList.addEventListener('input', (ev) => {
    const inp = ev.target.closest('input.pin-note');
    if (!inp) return;
    const id = parseInt(inp.dataset.pinId, 10);
    if (Number.isFinite(id)) _savePinNote(id, inp.value);
  });
}

if (els.optionsHistoryDate) {
  els.optionsHistoryDate.addEventListener('change', () => loadOptionsHistory());
}
if (els.optionsHistoryRefresh) {
  els.optionsHistoryRefresh.addEventListener('click', () => loadOptionsHistory());
}
document.querySelectorAll('input[name="options-history-view"]').forEach((r) => {
  // Initialise from persisted state.
  if (r.value === _ohView) r.checked = true;
  r.addEventListener('change', () => {
    if (!r.checked) return;
    _ohView = r.value;
    try { localStorage.setItem(_OH_VIEW_KEY, _ohView); } catch (_) {}
    // Date picker is only relevant in "all" view.
    if (els.optionsHistoryDate) els.optionsHistoryDate.disabled = (_ohView === 'pinned');
    loadOptionsHistory();
  });
});
if (els.optionsHistoryDate) {
  els.optionsHistoryDate.disabled = (_ohView === 'pinned');
}

wireCollapse(els.optionsHistoryToggle, els.optionsHistoryBody, 'collapse_options_history');
loadOptionsHistory();

// --- options universe scanner (manual trigger) ---------------------------
function renderScanCard(rec) {
  const verdict = rec.verdict || 'PASS';
  const verdictGlyph = _OPTIONS_VERDICT_GLYPH[verdict] || '⚪';
  const dirGlyph = _OPTIONS_DIR_GLYPH[rec.direction] || '·';
  const score = rec.composite_score;
  const c = rec.contract || {};
  const contractLine = c.contract_symbol
    ? `<div class="scan-card-contract">
         ${escapeHtml(c.expiration || '')}
         <b>$${fmtNum(c.strike, 2)}</b>
         ${(rec.direction || '').toUpperCase()} ·
         Δ ${c.delta != null ? (c.delta >= 0 ? '+' : '') + fmtNum(c.delta, 2) : '—'} ·
         mid $${fmtNum(c.mid, 2)} ·
         OI ${c.open_interest != null ? Math.round(c.open_interest).toLocaleString() : '—'}
       </div>`
    : `<div class="scan-card-contract muted">${escapeHtml(rec.reason || '')}</div>`;
  const prose = rec.prose_rationale
    ? `<div class="scan-card-prose">${escapeHtml(rec.prose_rationale)}</div>`
    : '';
  const badges = [];
  if (rec.conviction && rec.conviction !== 'none')
    badges.push(`<span class="scan-badge">${escapeHtml(rec.conviction)} conv</span>`);
  if (rec.post_earnings_override)
    badges.push('<span class="scan-badge badge-override">post-earn expiry</span>');
  if (rec.earnings_spans_expiration)
    badges.push('<span class="scan-badge badge-warn">spans earnings</span>');
  return `
    <div class="scan-card verdict-${verdict.toLowerCase()}" data-ticker="${escapeHtml(rec.ticker)}">
      <div class="scan-card-head">
        <span class="scan-verdict">${verdictGlyph} <b>${verdict}</b></span>
        <span class="scan-direction">${dirGlyph} <b>${(rec.direction || '').toUpperCase()}</b></span>
        <span class="scan-ticker"><b>${escapeHtml(rec.ticker)}</b></span>
        <span class="muted">· composite <b>${score != null ? Math.round(score) : '—'}</b>/100</span>
        ${badges.join(' ')}
      </div>
      ${contractLine}
      ${prose}
    </div>`;
}

function renderScanResults(result) {
  if (!els.optionsScanPanel || !els.optionsScanList) return;
  els.optionsScanPanel.classList.remove('hidden');
  const digest = (result && result.digest) || [];
  const all = (result && result.recommendations) || [];
  const passCount = all.length - digest.length;
  if (els.optionsScanSummary) {
    els.optionsScanSummary.textContent = digest.length
      ? `(${digest.length} BUY/WATCH-high of ${all.length} scanned — ${passCount} other results omitted)`
      : `(${all.length} scanned, none cleared BUY or high-conviction WATCH)`;
  }
  if (!digest.length) {
    if (all.length) {
      // Empty digest doesn't mean the scan found nothing — every
      // ticker that ran the full pipeline produced a composite. Show
      // the top 10 by |composite − 50| so the user sees what almost
      // crossed the BUY / high-WATCH thresholds. Helpful for tuning
      // (e.g. "everything clustered at 60-64 — gates may be too
      // strict") and for spotting setups that fell just short.
      const top = all.slice(0, 10);
      const banner = `<div class="muted scan-empty">
        No BUY or high-conviction WATCH today.
        Highest composites scanned (informational — not actionable signals):
      </div>`;
      els.optionsScanList.innerHTML = banner + top.map(renderScanCard).join('');
    } else {
      els.optionsScanList.innerHTML = `<div class="muted scan-empty">
        No setups stacked enough across the 5 layers — sit out, or relax the DTE window and re-scan.
      </div>`;
    }
    return;
  }
  els.optionsScanList.innerHTML = digest.map(renderScanCard).join('');
}

// The scan runs server-side in a background thread; the UI kicks it
// off then polls /api/options/scan/status every few seconds for
// progress and a final result. Top 200 can run ~40 min, so the page
// stays usable throughout (you can navigate away and come back; the
// poll picks up wherever the server is).

const SCAN_POLL_MS = 2500;
let _scanPollTimer = null;
let _scanRunPrevBtnTxt = null;

function _setScanRunning(running) {
  if (els.optionsScanBtn) els.optionsScanBtn.disabled = running;
  if (els.optionsScanTopN) els.optionsScanTopN.disabled = running;
  if (els.optionsLookupBtn) els.optionsLookupBtn.disabled = running;
  if (els.optionsScanCancelBtn) els.optionsScanCancelBtn.classList.toggle('hidden', !running);
}

function _renderScanProgress(state) {
  const { done = 0, total = 0, current_ticker, started_at, phase,
          rate_limited_count = 0 } = state || {};
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const elapsed = started_at ? Math.max(0, Date.now() / 1000 - started_at) : 0;
  const elapsedTxt = elapsed >= 60
    ? `${Math.floor(elapsed / 60)}m ${Math.floor(elapsed % 60)}s`
    : `${Math.floor(elapsed)}s`;
  let etaTxt = '';
  if (done > 0 && total > done && elapsed > 0) {
    const remainingSec = (elapsed / done) * (total - done);
    etaTxt = remainingSec >= 60
      ? ` · ~${Math.ceil(remainingSec / 60)}m remaining`
      : ` · ~${Math.ceil(remainingSec)}s remaining`;
  }
  const isPreflight = phase === 'preflight' || (!current_ticker && done === 0);
  let statusLine, listMsg;
  if (isPreflight) {
    statusLine = `Pre-scoring universe · elapsed ${elapsedTxt}`;
    listMsg = `Pre-scoring the liquid snapshot universe. The per-ticker pipeline starts once this finishes (usually a few seconds; can take longer if Yahoo is throttling). Page updates every ${SCAN_POLL_MS / 1000}s.`;
  } else {
    statusLine = `Scanning ${done}/${total} (${pct}%) · elapsed ${elapsedTxt}${etaTxt}`;
    const ticker = current_ticker ? ` <strong>${escapeHtml(current_ticker)}</strong>` : '';
    listMsg = `Running the 5-layer pipeline on${ticker}. Page updates every ${SCAN_POLL_MS / 1000}s.`;
  }
  // Show a prominent banner when Yahoo is throttling us — surfaces the
  // root cause when the scan would otherwise look mysteriously slow
  // (each rate-limited ticker either times out at 60s or fails fast,
  // both of which produce no useful recommendation).
  if (rate_limited_count > 0) {
    listMsg = `<div class="scan-ratelimit-banner"><strong>⚠️ Yahoo Finance is rate-limiting us</strong> — ${rate_limited_count} ticker${rate_limited_count === 1 ? '' : 's'} affected so far. The scan will continue but most tickers will be skipped. Try again in 5-10 minutes, or run after market close when traffic is lower.</div>` + listMsg;
  }
  if (els.optionsStatus) els.optionsStatus.innerHTML = statusLine;
  if (els.optionsScanList)
    els.optionsScanList.innerHTML = `<div class="muted scan-running">${listMsg}</div>`;
}

async function _pollScanStatus() {
  try {
    const res = await fetch('/api/options/scan/status');
    const state = await res.json().catch(() => ({}));
    if (state.running) {
      _renderScanProgress(state);
      _scanPollTimer = setTimeout(_pollScanStatus, SCAN_POLL_MS);
      return;
    }
    // Finished. Render whatever the server has — last_result if the
    // scan completed (or was cancelled mid-flight with partial recs),
    // last_error if it crashed, or an empty-state message otherwise.
    _setScanRunning(false);
    if (els.optionsScanBtn && _scanRunPrevBtnTxt != null) {
      els.optionsScanBtn.textContent = _scanRunPrevBtnTxt;
    }
    if (state.last_error) {
      if (els.optionsStatus) els.optionsStatus.textContent = state.last_error;
      if (els.optionsScanList)
        els.optionsScanList.innerHTML = `<div class="muted">Scan failed: ${escapeHtml(state.last_error)}</div>`;
      return;
    }
    if (state.last_result) {
      renderScanResults(state.last_result);
      if (els.optionsStatus) {
        const cancelled = state.cancelled ? ' (cancelled — partial results)' : '';
        els.optionsStatus.textContent = `Done · ${state.done}/${state.total} tickers${cancelled}`;
      }
      loadOptionsHistory();
    }
  } catch (err) {
    _setScanRunning(false);
    if (els.optionsScanBtn && _scanRunPrevBtnTxt != null) {
      els.optionsScanBtn.textContent = _scanRunPrevBtnTxt;
    }
    if (els.optionsStatus) els.optionsStatus.textContent = (err && err.message) || 'network error';
  }
}

async function runOptionsScan() {
  if (!els.optionsScanBtn) return;
  const topN = parseInt((els.optionsScanTopN && els.optionsScanTopN.value) || '25', 10);
  const [dteMin, dteMax] = _readDteRange();
  if (_scanRunPrevBtnTxt == null) _scanRunPrevBtnTxt = els.optionsScanBtn.textContent;
  _setScanRunning(true);
  els.optionsScanBtn.textContent = `Scanning ${topN}…`;
  if (els.optionsScanPanel) els.optionsScanPanel.classList.remove('hidden');
  if (els.optionsStatus) els.optionsStatus.textContent = 'Starting scan…';
  try {
    const res = await fetch('/api/options/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        top_n: topN, dte_min: dteMin, dte_max: dteMax,
        ..._readAdvancedFilters(),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      _setScanRunning(false);
      els.optionsScanBtn.textContent = _scanRunPrevBtnTxt;
      if (els.optionsStatus) els.optionsStatus.textContent = data.error || ('HTTP ' + res.status);
      return;
    }
    if (data.started === false && !data.running) {
      // Server refused but state is also "not running". With the
      // zombie-thread recovery in start_scan, this should only happen
      // in genuinely unexpected cases — surface the response so it's
      // debuggable rather than silently retrying.
      _setScanRunning(false);
      els.optionsScanBtn.textContent = _scanRunPrevBtnTxt;
      if (els.optionsStatus) {
        els.optionsStatus.textContent = data.thread_alive
          ? 'Previous scan still finishing — try again in a few seconds.'
          : 'Scan did not start (server refused). Check the server log.';
      }
      return;
    }
    // started=true OR another scan was already in flight — either
    // way, poll for progress.
    if (_scanPollTimer) clearTimeout(_scanPollTimer);
    _pollScanStatus();
  } catch (err) {
    _setScanRunning(false);
    els.optionsScanBtn.textContent = _scanRunPrevBtnTxt;
    if (els.optionsStatus) els.optionsStatus.textContent = (err && err.message) || 'network error';
  }
}

async function cancelOptionsScan() {
  if (els.optionsScanCancelBtn) els.optionsScanCancelBtn.disabled = true;
  try {
    await fetch('/api/options/scan/cancel', { method: 'POST' });
    if (els.optionsStatus) els.optionsStatus.textContent = 'Cancelling…';
  } catch (_) { /* poll will surface the next state */ }
  finally {
    if (els.optionsScanCancelBtn) els.optionsScanCancelBtn.disabled = false;
  }
}

if (els.optionsScanBtn) els.optionsScanBtn.addEventListener('click', runOptionsScan);
if (els.optionsScanCancelBtn) els.optionsScanCancelBtn.addEventListener('click', cancelOptionsScan);

// On page load, ask the server if a scan is already running (e.g. the
// user kicked one off and reloaded). If so, jump straight to polling
// so progress picks up where they left it.
(async () => {
  try {
    const res = await fetch('/api/options/scan/status');
    const state = await res.json();
    if (state && state.running) {
      if (els.optionsScanPanel) els.optionsScanPanel.classList.remove('hidden');
      _setScanRunning(true);
      _scanRunPrevBtnTxt = els.optionsScanBtn ? els.optionsScanBtn.textContent : 'Scan universe';
      if (els.optionsScanBtn) els.optionsScanBtn.textContent = `Scanning ${state.top_n}…`;
      _pollScanStatus();
    }
  } catch (_) { /* idle — ignore */ }
})();
if (els.optionsScanList) {
  els.optionsScanList.addEventListener('click', (ev) => {
    const card = ev.target.closest('.scan-card');
    if (card && card.dataset.ticker && els.optionsTicker) {
      els.optionsTicker.value = card.dataset.ticker;
      runOptionsLookup();
      // The result panel renders ABOVE the scan list and is tall (prose,
      // layer breakdown, IV context). Without this scroll the scan list
      // gets pushed below the fold and the user thinks the other cards
      // disappeared. Scroll the result into view so the click visibly
      // does something — the scan list stays mounted, just scroll back
      // down to see it.
      if (els.optionsResult) {
        // Wait a tick so the panel has rendered and has a height.
        setTimeout(() => els.optionsResult.scrollIntoView({
          behavior: 'smooth', block: 'start',
        }), 50);
      }
    }
  });
}
wireCollapse(els.optionsScanToggle, els.optionsScanBody, 'collapse_options_scan');


// --- Advanced filters + pool preview --------------------------------------

function _readAdvancedFilters() {
  // Read current values from the Advanced filter dropdowns. Returns
  // an object suitable for spreading into the scan POST body.
  const out = {};
  if (els.optionsAdvPriceFloor && els.optionsAdvPriceFloor.value)
    out.price_floor = parseFloat(els.optionsAdvPriceFloor.value);
  if (els.optionsAdvVolFloor && els.optionsAdvVolFloor.value)
    out.volume_floor = parseFloat(els.optionsAdvVolFloor.value);
  if (els.optionsAdvMinDistance && els.optionsAdvMinDistance.value)
    out.min_directional_distance = parseFloat(els.optionsAdvMinDistance.value);
  return out;
}

function _applySettingsToUI(settings) {
  // Sync the dropdowns + top_n select to the supplied settings dict
  // (typically the GET /settings response). For each select, pick the
  // option whose value matches; if none, leave the current selection.
  if (!settings) return;
  const pickClosest = (sel, target) => {
    if (!sel || target == null) return;
    let best = null, bestDiff = Infinity;
    for (const opt of sel.options) {
      const v = parseFloat(opt.value);
      if (Number.isNaN(v)) continue;
      const d = Math.abs(v - target);
      if (d < bestDiff) { best = opt; bestDiff = d; }
    }
    if (best) sel.value = best.value;
  };
  pickClosest(els.optionsAdvPriceFloor, settings.price_floor);
  pickClosest(els.optionsAdvVolFloor,   settings.volume_floor);
  pickClosest(els.optionsAdvMinDistance, settings.min_directional_distance);
  pickClosest(els.optionsScanTopN,      settings.top_n);
}

function _renderPreview(data) {
  if (!els.optionsScanPreviewText) return;
  if (!data || data.scanned === 0) {
    els.optionsScanPreviewText.textContent = 'Pool preview unavailable (no snapshot loaded yet).';
    return;
  }
  const topNVal = parseInt((els.optionsScanTopN && els.optionsScanTopN.value) || '25', 10);
  const pct = data.qualifying > 0
    ? Math.round((Math.min(topNVal, data.qualifying) / data.qualifying) * 100)
    : 0;
  const dateTxt = data.snap_date ? ` (${data.snap_date})` : '';
  const cached = data.cached ? ' · cached' : '';
  els.optionsScanPreviewText.innerHTML =
    `<strong>${data.qualifying}</strong> stocks qualify${dateTxt} ` +
    `· <strong>${data.call_bias}</strong> bull / <strong>${data.put_bias}</strong> bear ` +
    `· Top ${topNVal} captures ${pct}%${cached}`;
}

async function refreshPreview(force = false) {
  if (!els.optionsScanPreviewText) return;
  if (els.optionsScanPreviewRefresh) els.optionsScanPreviewRefresh.disabled = true;
  if (force) els.optionsScanPreviewText.textContent = 'Re-running pre-score…';
  try {
    const qs = new URLSearchParams(_readAdvancedFilters());
    if (force) qs.set('force', '1');
    const res = await fetch('/api/options/scan/preview?' + qs.toString());
    const data = await res.json();
    _renderPreview(data);
  } catch (err) {
    els.optionsScanPreviewText.textContent =
      'Preview failed: ' + ((err && err.message) || 'network error');
  } finally {
    if (els.optionsScanPreviewRefresh) els.optionsScanPreviewRefresh.disabled = false;
  }
}

async function loadSavedSettings() {
  try {
    const res = await fetch('/api/options/scan/settings');
    const data = await res.json();
    _applySettingsToUI(data.settings);
  } catch (_) { /* ignore — defaults already in DOM */ }
}

async function saveAdvSettings() {
  if (!els.optionsAdvSave) return;
  const payload = {
    ..._readAdvancedFilters(),
    top_n: parseInt(els.optionsScanTopN.value, 10),
    ...(_readDteRangePayload()),
  };
  els.optionsAdvSave.disabled = true;
  if (els.optionsAdvStatus) els.optionsAdvStatus.textContent = 'Saving…';
  try {
    const res = await fetch('/api/options/scan/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    _applySettingsToUI(data.settings);
    if (els.optionsAdvStatus) els.optionsAdvStatus.textContent = 'Saved · alerts will use these';
    refreshPreview(false);  // gates may have changed → cache key differs; will recompute
  } catch (err) {
    if (els.optionsAdvStatus) els.optionsAdvStatus.textContent = 'Save failed';
  } finally {
    els.optionsAdvSave.disabled = false;
    setTimeout(() => {
      if (els.optionsAdvStatus && els.optionsAdvStatus.textContent.startsWith('Saved'))
        els.optionsAdvStatus.textContent = '';
    }, 4000);
  }
}

async function resetAdvSettings() {
  // Send an empty body — the server clamps missing fields to its
  // DEFAULT_SETTINGS, so this is the canonical "go back to factory"
  // operation regardless of what the UI currently shows. Whatever the
  // server returns becomes the new UI state.
  if (els.optionsAdvStatus) els.optionsAdvStatus.textContent = 'Reverting…';
  try {
    const res = await fetch('/api/options/scan/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    _applySettingsToUI(data.settings);
    if (els.optionsAdvStatus) els.optionsAdvStatus.textContent = 'Reset to defaults';
    refreshPreview(false);
  } catch (_) {
    if (els.optionsAdvStatus) els.optionsAdvStatus.textContent = 'Reset failed';
  }
  setTimeout(() => {
    if (els.optionsAdvStatus && els.optionsAdvStatus.textContent === 'Reset to defaults')
      els.optionsAdvStatus.textContent = '';
  }, 4000);
}

function _readDteRangePayload() {
  // Same as _readDteRange but as an object so it can be spread into payloads.
  const [dte_min, dte_max] = _readDteRange();
  return { dte_min, dte_max };
}

// Advanced filters collapsible toggle (independent of wireCollapse since it
// doesn't persist — power-user feature, default collapsed).
if (els.optionsScanAdvToggle && els.optionsScanAdvBody) {
  els.optionsScanAdvToggle.addEventListener('click', () => {
    const isHidden = els.optionsScanAdvBody.classList.toggle('hidden');
    els.optionsScanAdvToggle.setAttribute('aria-expanded', String(!isHidden));
    const chev = els.optionsScanAdvToggle.querySelector('.chevron');
    if (chev) chev.textContent = isHidden ? '▸' : '▾';
  });
}

// Wire the Save / Reset buttons and the dropdown change handlers.
// Changing a dropdown immediately refreshes the preview (so the user
// sees the impact of relaxing/tightening before committing to Save).
if (els.optionsAdvSave) els.optionsAdvSave.addEventListener('click', saveAdvSettings);
if (els.optionsAdvReset) els.optionsAdvReset.addEventListener('click', resetAdvSettings);
['optionsAdvPriceFloor', 'optionsAdvVolFloor', 'optionsAdvMinDistance', 'optionsScanTopN']
  .forEach((k) => {
    const el = els[k];
    if (el) el.addEventListener('change', () => refreshPreview(false));
  });
if (els.optionsScanPreviewRefresh)
  els.optionsScanPreviewRefresh.addEventListener('click', () => refreshPreview(true));

// On page load: pull saved settings, populate the UI, then fetch the
// preview. Both calls are cheap (settings is a single DB read, preview
// is server-side cached). If the scan-running bootstrap below also
// kicks in, that's fine — they run in parallel.
(async () => {
  await loadSavedSettings();
  refreshPreview(false);
})();


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
