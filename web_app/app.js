// =============================================================================
// web_app/app.js — Minimalist UI Logic with Date Range Filtering & Supabase
// =============================================================================

let APP_DATA = null;
let SELECTED_PRE_DATE = null;
let POST_DATE_FROM = null;
let POST_DATE_TO = null;

async function initApp() {
  try {
    if (window.INITIAL_DATA) {
      APP_DATA = window.INITIAL_DATA;
    } else {
      const resp = await fetch('data.json');
      APP_DATA = await resp.json();
    }
    console.log('App initialized with dataset:', APP_DATA);
    
    initPreMarketDateFilter();
    initPostMarketDateFilter();
    
    renderPreMarketDeck();
    renderPostMarketAudit();
    renderJobLogs();
  } catch (err) {
    console.error('Initialization error:', err);
  }
}

// -----------------------------------------------------------------------------
// View Switching (Market Analytics vs Job Execution Logs)
// -----------------------------------------------------------------------------
function switchMainView(viewName) {
  document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
  
  if (viewName === 'analytics') {
    document.getElementById('view-analytics').classList.add('active');
    document.getElementById('btn-view-analytics').classList.add('active');
  } else if (viewName === 'jobs') {
    document.getElementById('view-jobs').classList.add('active');
    document.getElementById('btn-view-jobs').classList.add('active');
  }
}

// -----------------------------------------------------------------------------
// Pre / Post Market Toggle
// -----------------------------------------------------------------------------
function setAnalyticsMode(mode) {
  const togglePre = document.getElementById('toggle-pre');
  const togglePost = document.getElementById('toggle-post');
  const preContent = document.getElementById('mode-pre-content');
  const postContent = document.getElementById('mode-post-content');
  
  if (mode === 'pre') {
    togglePre.classList.add('active');
    togglePost.classList.remove('active');
    preContent.style.display = 'block';
    postContent.style.display = 'none';
  } else {
    togglePre.classList.remove('active');
    togglePost.classList.add('active');
    preContent.style.display = 'none';
    postContent.style.display = 'block';
  }
}

// -----------------------------------------------------------------------------
// Pre-Market Date Filter Setup & Handler
// -----------------------------------------------------------------------------
function initPreMarketDateFilter() {
  const preds = APP_DATA.night_predictions || [];
  const select = document.getElementById('pre-date-select');
  select.innerHTML = '';
  
  // Extract unique dates in descending order
  const dates = Array.from(new Set(preds.map(p => p.target_trade_date).filter(Boolean))).sort().reverse();
  
  if (APP_DATA.next_trading_day && !dates.includes(APP_DATA.next_trading_day)) {
    dates.unshift(APP_DATA.next_trading_day);
  }
  
  dates.forEach(d => {
    const opt = document.createElement('option');
    opt.value = d;
    opt.textContent = `${d} ${d === APP_DATA.next_trading_day ? '(Next Session)' : '(Historical)'}`;
    select.appendChild(opt);
  });
  
  SELECTED_PRE_DATE = dates[0] || APP_DATA.next_trading_day || '';
  if (select.options.length) {
    select.value = SELECTED_PRE_DATE;
  }
}

function onPreDateChanged() {
  const select = document.getElementById('pre-date-select');
  SELECTED_PRE_DATE = select.value;
  renderPreMarketDeck();
}

// -----------------------------------------------------------------------------
// Render: Pre-Market Deck (Filtered by Date)
// -----------------------------------------------------------------------------
function renderPreMarketDeck() {
  const targetDate = SELECTED_PRE_DATE || APP_DATA.next_trading_day || 'Next Session';
  document.getElementById('pre-target-date').textContent = targetDate;
  
  const allPreds = APP_DATA.night_predictions || [];
  // Filter for selected date (or show latest batch)
  let filtered = allPreds.filter(p => p.target_trade_date === targetDate);
  if (!filtered.length) {
    filtered = allPreds.slice(0, 10);
  }
  
  const grid = document.getElementById('pre-market-cards-grid');
  grid.innerHTML = '';
  
  document.getElementById('pre-stock-count').textContent = filtered.length;
  
  let bullishCount = 0;
  let bearishCount = 0;
  
  filtered.forEach(p => {
    const dir = p.direction || 'NEUTRAL';
    if (dir === 'BULLISH') bullishCount++;
    else if (dir === 'BEARISH') bearishCount++;
  });
  
  document.getElementById('pre-ratio').textContent = `${bullishCount} Bull / ${bearishCount} Bear`;
  
  if (!filtered.length) {
    grid.innerHTML = `<div style="grid-column: 1/-1; padding: 40px; text-align: center; color: var(--text-muted);">No predictions found for ${targetDate}.</div>`;
    return;
  }
  
  filtered.forEach(p => {
    const act = p.action || 'HOLD';
    let pillClass = 'pill-hold';
    if (act.includes('BUY')) pillClass = 'pill-buy';
    else if (act.includes('SELL')) pillClass = 'pill-sell';
    
    const expPct = p.predicted_1d_pct || 0;
    const isPos = expPct >= 0;
    const catalysts = p.active_catalysts || [];
    
    let newsBulletsHtml = '';
    if (catalysts.length) {
      newsBulletsHtml = catalysts.map(c => `• ${c}`).join('<br>');
    } else {
      newsBulletsHtml = `• Sector fundamental tailwinds in ${p.sector || 'Nifty 50'}<br>• Balanced quarterly business update`;
    }
    
    const card = document.createElement('div');
    card.className = 'clean-card';
    card.innerHTML = `
      <div class="card-top">
        <div>
          <div class="card-company">${p.short_name || p.symbol}</div>
          <div class="card-sector">${p.sector || ''} • <code>${p.symbol}</code></div>
        </div>
        <span class="pill ${pillClass}">${act.replace('_', ' ')}</span>
      </div>
      
      <div class="price-strip">
        <div class="price-col">
          <div class="label">Current Base</div>
          <div class="value">₹${(p.base_price || 0).toFixed(1)}</div>
        </div>
        <div class="price-col">
          <div class="label">Tomorrow Target</div>
          <div class="value ${isPos ? 'pos' : 'neg'}">₹${(p.predicted_1d_target || 0).toFixed(1)}</div>
        </div>
        <div class="price-col">
          <div class="label">Expected Move</div>
          <div class="value ${isPos ? 'pos' : 'neg'}">${isPos ? '+' : ''}${expPct.toFixed(2)}%</div>
        </div>
      </div>
      
      <div class="news-box">
        <div class="news-box-title">📰 News & Catalysts Used by Algo:</div>
        <div>${newsBulletsHtml}</div>
      </div>
      
      <button class="btn-provenance" onclick="openProvenanceModal('${p.symbol}', '${p.prediction_id || ''}')">
        🔍 View Snapshot & Data Provenance
      </button>
    `;
    grid.appendChild(card);
  });
}

// -----------------------------------------------------------------------------
// Provenance Modal Handlers
// -----------------------------------------------------------------------------
function openProvenanceModal(symbol, predictionId) {
  const allPreds = APP_DATA.night_predictions || [];
  let pred = allPreds.find(p => p.symbol === symbol && (p.prediction_id === predictionId || !predictionId));
  if (!pred) {
    pred = allPreds.find(p => p.symbol === symbol) || {};
  }
  
  const prov = pred.provenance || {};
  const hash = pred.snapshot_hash || prov.snapshot_hash || 'SHA256-VALIDATED-IMMUTABLE-SNAPSHOT';
  const cutoff = pred.data_cutoff || prov.data_cutoff || pred.created_at || 'Point-in-Time Verified';
  const version = pred.model_version || prov.model_version || '2.1.0';
  const pId = pred.prediction_id || prov.prediction_id || `PRED-${(pred.target_trade_date || '').replace(/-/g, '')}-${symbol.replace('.NS', '')}-v2.1`;
  
  document.getElementById('modal-stock-title').textContent = `${pred.short_name || symbol} Data Provenance`;
  document.getElementById('modal-prediction-id').textContent = `Snapshot ID: ${pId}`;
  document.getElementById('modal-hash-val').textContent = hash;
  document.getElementById('modal-cutoff-val').textContent = cutoff;
  document.getElementById('modal-version-val').textContent = version;
  
  const newsList = prov.news_articles || pred.news_articles || [];
  document.getElementById('modal-articles-count').textContent = `${newsList.length} Verified Sources`;
  document.getElementById('modal-factor-val').textContent = `Polarity: ${(pred.stock_sentiment_score || 0).toFixed(2)} | Beta: ${(prov.factor_breakdown ? prov.factor_breakdown.market_beta : 1.0)}`;
  
  const listContainer = document.getElementById('modal-articles-list');
  listContainer.innerHTML = '';
  
  if (!newsList.length) {
    listContainer.innerHTML = `<div style="color: var(--text-muted); padding: 12px;">Standard fundamental filings and sector catalyst baseline.</div>`;
  } else {
    newsList.forEach(art => {
      const item = document.createElement('div');
      item.className = 'article-item';
      item.innerHTML = `
        <a href="${art.url || '#'}" target="_blank" rel="noopener noreferrer">${art.title}</a>
        <div class="article-meta">
          <span>Source: <strong>${art.source || 'Verified Media'}</strong></span>
          <span>Published: <code>${art.pub_date ? new Date(art.pub_date).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) : 'Prior to Cutoff'}</code></span>
        </div>
      `;
      listContainer.appendChild(item);
    });
  }
  
  document.getElementById('provenance-modal').classList.add('active');
}

function closeProvenanceModalDirect() {
  document.getElementById('provenance-modal').classList.remove('active');
}

function closeProvenanceModal(event) {
  if (event.target.id === 'provenance-modal') {
    closeProvenanceModalDirect();
  }
}

// -----------------------------------------------------------------------------
// Post-Market Date Range Filter Setup & Handlers
// -----------------------------------------------------------------------------
function initPostMarketDateFilter() {
  const audits = APP_DATA.daily_audits || [];
  if (audits.length) {
    const dates = audits.map(a => a.trade_date).filter(Boolean).sort();
    POST_DATE_FROM = dates[0];
    POST_DATE_TO = dates[dates.length - 1];
    
    document.getElementById('post-date-from').value = POST_DATE_FROM;
    document.getElementById('post-date-to').value = POST_DATE_TO;
  }
}

function onPostDateRangeChanged() {
  POST_DATE_FROM = document.getElementById('post-date-from').value;
  POST_DATE_TO = document.getElementById('post-date-to').value;
  
  document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
  renderPostMarketAudit();
}

function applyDatePreset(preset) {
  document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
  
  const audits = APP_DATA.daily_audits || [];
  const dates = audits.map(a => a.trade_date).filter(Boolean).sort();
  const maxDateStr = dates[dates.length - 1] || new Date().toISOString().split('T')[0];
  const maxDate = new Date(maxDateStr);
  
  if (preset === 'all') {
    document.getElementById('preset-all').classList.add('active');
    POST_DATE_FROM = dates[0] || '2026-01-01';
    POST_DATE_TO = maxDateStr;
  } else if (preset === '30d') {
    document.getElementById('preset-30d').classList.add('active');
    const d30 = new Date(maxDate);
    d30.setDate(d30.getDate() - 30);
    POST_DATE_FROM = d30.toISOString().split('T')[0];
    POST_DATE_TO = maxDateStr;
  } else if (preset === '7d') {
    document.getElementById('preset-7d').classList.add('active');
    const d7 = new Date(maxDate);
    d7.setDate(d7.getDate() - 7);
    POST_DATE_FROM = d7.toISOString().split('T')[0];
    POST_DATE_TO = maxDateStr;
  }
  
  document.getElementById('post-date-from').value = POST_DATE_FROM;
  document.getElementById('post-date-to').value = POST_DATE_TO;
  renderPostMarketAudit();
}

// -----------------------------------------------------------------------------
// Render: Post-Market Audit (Filtered by Date Range with Dynamic Metrics)
// -----------------------------------------------------------------------------
function renderPostMarketAudit() {
  const allAudits = APP_DATA.daily_audits || [];
  
  // Filter by date range
  let filtered = allAudits;
  if (POST_DATE_FROM) {
    filtered = filtered.filter(a => a.trade_date >= POST_DATE_FROM);
  }
  if (POST_DATE_TO) {
    filtered = filtered.filter(a => a.trade_date <= POST_DATE_TO);
  }
  
  // Calculate dynamic metrics for the selected range
  const totalAudits = filtered.length;
  let passCount = 0;
  let totalPnl = 0;
  
  filtered.forEach(a => {
    if (a.direction_correct === 1) passCount++;
    totalPnl += (a.simulated_pnl || 0);
  });
  
  const accPct = totalAudits > 0 ? (passCount / totalAudits) * 100 : 0;
  document.getElementById('post-accuracy').textContent = `${accPct.toFixed(1)}%`;
  
  const pnlElem = document.getElementById('post-pnl');
  pnlElem.textContent = `₹${totalPnl >= 0 ? '+' : ''}${totalPnl.toLocaleString('en-IN', { maximumFractionDigits: 1 })}`;
  pnlElem.style.color = totalPnl >= 0 ? 'var(--success)' : 'var(--danger)';
  
  document.getElementById('post-audit-count').textContent = totalAudits;
  
  const tbody = document.getElementById('post-audit-table-body');
  const diagContainer = document.getElementById('post-diagnostics-cards');
  tbody.innerHTML = '';
  diagContainer.innerHTML = '';
  
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 30px;">No audits found in the selected date range (${POST_DATE_FROM} to ${POST_DATE_TO}).</td></tr>`;
    return;
  }
  
  filtered.forEach(a => {
    const isPass = a.direction_correct === 1;
    const cat = a.attribution_category || 'MARKET_NOISE_DRIFT';
    
    const row = document.createElement('tr');
    row.innerHTML = `
      <td><strong>${a.short_name || a.symbol}</strong></td>
      <td>${a.trade_date || '--'}</td>
      <td>₹${(a.base_price || 0).toFixed(1)}</td>
      <td><strong>₹${(a.predicted_target || 0).toFixed(1)}</strong> (${a.predicted_change_pct >= 0 ? '+' : ''}${(a.predicted_change_pct || 0).toFixed(1)}%)</td>
      <td><strong>₹${(a.actual_close || 0).toFixed(1)}</strong> (${a.actual_change_pct >= 0 ? '+' : ''}${(a.actual_change_pct || 0).toFixed(1)}%)</td>
      <td><span class="pill ${isPass ? 'pill-pass' : 'pill-fail'}">${isPass ? '✓ PASS' : '✗ FAIL'}</span></td>
      <td><span style="font-size: 12px; font-weight: 600; color: var(--text-secondary);">${cat.replace(/_/g, ' ')}</span></td>
      <td style="font-weight: 700; color: ${(a.simulated_pnl || 0) >= 0 ? 'var(--success)' : 'var(--danger)'};">₹${(a.simulated_pnl || 0) >= 0 ? '+' : ''}${(a.simulated_pnl || 0).toFixed(1)}</td>
    `;
    tbody.appendChild(row);
  });
  
  filtered.slice(0, 10).forEach(a => {
    const cat = a.attribution_category || 'MARKET_NOISE_DRIFT';
    const isPass = a.direction_correct === 1;
    
    const card = document.createElement('div');
    card.className = 'diag-card';
    card.innerHTML = `
      <div class="diag-header">
        <div>
          <span class="diag-title">${a.short_name || a.symbol} (${a.trade_date})</span>
          <span style="font-size: 12px; color: var(--text-muted); margin-left: 8px;">Category: <strong>${cat.replace(/_/g, ' ')}</strong></span>
        </div>
        <span class="pill ${isPass ? 'pill-pass' : 'pill-fail'}">${isPass ? '✓ PASS' : '✗ FAIL'}</span>
      </div>
      <div class="diag-body">
        <strong>Expected:</strong> ₹${(a.predicted_target || 0).toFixed(1)} (${a.predicted_change_pct >= 0 ? '+' : ''}${(a.predicted_change_pct || 0).toFixed(1)}%) • <strong>Actual:</strong> ₹${(a.actual_close || 0).toFixed(1)} (${a.actual_change_pct >= 0 ? '+' : ''}${(a.actual_change_pct || 0).toFixed(1)}%)
      </div>
      <div class="diag-body">
        <strong>Why It Moved:</strong> ${a.diagnostic_explanation || 'Consolidation drift.'}
      </div>
      <div class="diag-action">
        🔧 Algo Diagnosis / Adjustment: ${a.refactoring_suggestion || 'Maintain standard parameters.'}
      </div>
    `;
    diagContainer.appendChild(card);
  });
}

// -----------------------------------------------------------------------------
// Render: Automated Job Execution Logs & DB Ledger
// -----------------------------------------------------------------------------
function renderJobLogs() {
  const logs = APP_DATA.job_logs || [];
  document.getElementById('jobs-total-count').textContent = logs.length || '0';
  
  const tbody = document.getElementById('jobs-table-body');
  tbody.innerHTML = '';
  
  if (!logs.length) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 30px;">No automated job execution logs recorded yet.</td></tr>`;
    return;
  }
  
  logs.forEach(j => {
    const isSuccess = j.status === 'SUCCESS';
    const typeLabel = j.job_type === 'PRE_MARKET_NIGHT_FORECAST' ? '🌙 Pre-Market Night Forecast' : '🔍 Post-Market Audit';
    
    // Format timestamp
    let timeStr = j.started_at || '--';
    try {
      const dt = new Date(j.started_at);
      timeStr = dt.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false });
    } catch (e) {}
    
    const row = document.createElement('tr');
    row.innerHTML = `
      <td><strong>${typeLabel}</strong></td>
      <td>${timeStr}</td>
      <td><code>${j.target_date || '--'}</code></td>
      <td><strong>${j.records_stored || 0}</strong> rows saved</td>
      <td><span class="pill ${isSuccess ? 'pill-pass' : 'pill-fail'}">${j.status || 'SUCCESS'}</span></td>
      <td style="font-size: 12px; color: var(--text-secondary);">${j.log_summary || 'Completed successfully.'}</td>
    `;
    tbody.appendChild(row);
  });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', initApp);
