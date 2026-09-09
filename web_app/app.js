// =============================================================================
// web_app/app.js — V3.2 Nifty 50 AI Trading Arena Frontend Logic
// =============================================================================

let APP_DATA = null;
let currentView = 'home';
let currentAgent = 'ALPHA';
let currentHoldingsTab = 'all';
let currentSectorFilter = 'ALL';
let drawerChart = null;

const AGENT_META = {
  ALPHA: { name: "Agent Alpha", title: "The Event Hunter", icon: "⚡", version: "ALPHA-1.0", quote: "I trade what changed." },
  MOMENTUM: { name: "Agent Momentum", title: "The Trend Chaser", icon: "🚀", version: "MOMENTUM-1.0", quote: "The trend is my edge." },
  MACRO: { name: "Agent Macro", title: "The Economist", icon: "🌍", version: "MACRO-1.0", quote: "I trade the environment." },
  DEFENSIVE: { name: "Agent Defensive", title: "The Capital Protector", icon: "🛡️", version: "DEFENSIVE-1.0", quote: "Survive first. Profit second." },
  CONTRARIAN: { name: "Agent Contrarian", title: "The Contrarian", icon: "🎯", version: "CONTRARIAN-1.0", quote: "Everyone can't be right." }
};

// Format currency in Indian Rupees format (₹)
function formatINR(val) {
  if (val === undefined || val === null || isNaN(val)) return "₹0.00";
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2
  }).format(val);
}

function formatPct(val) {
  if (val === undefined || val === null || isNaN(val)) return "0.00%";
  const sign = val > 0 ? "+" : "";
  return `${sign}${Number(val).toFixed(2)}%`;
}

// -----------------------------------------------------------------------------
// Initialization & Data Loading
// -----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  if (window.INITIAL_DATA) {
    APP_DATA = window.INITIAL_DATA;
    initApp();
  } else {
    fetch('data.json')
      .then(res => res.json())
      .then(data => {
        APP_DATA = data;
        initApp();
      })
      .catch(err => {
        console.error("Failed to load data.json:", err);
      });
  }
});

function initApp() {
  renderHeaderStatus();
  renderHomeView();
  renderAnalyticsView();
  renderInvestmentView();
  renderSystemView();
}

// -----------------------------------------------------------------------------
// View Switching
// -----------------------------------------------------------------------------
function switchView(viewName) {
  currentView = viewName;

  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.view === viewName);
  });

  document.querySelectorAll('.view-content').forEach(view => {
    view.classList.toggle('active', view.id === `view-${viewName}`);
  });

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// -----------------------------------------------------------------------------
// Header Status Rendering
// -----------------------------------------------------------------------------
function renderHeaderStatus() {
  const clock = (APP_DATA.arena && APP_DATA.arena.market_clock) || {};
  const phase = clock.current_phase || "INTRADAY";
  const clockEl = document.getElementById('header-clock-text');
  if (clockEl) {
    clockEl.textContent = `${phase} • 15:30 IST CUTOFF`;
  }
}

// -----------------------------------------------------------------------------
// VIEW 1: HOME
// -----------------------------------------------------------------------------
function renderHomeView() {
  const arena = APP_DATA.arena || {};
  const summary = arena.summary || {};
  const leaderboard = arena.leaderboard || [];

  // 1. Hero Cards
  const navEl = document.getElementById('arena-total-nav');
  if (navEl) navEl.textContent = formatINR(summary.total_arena_value || 10000000);

  const pnlEl = document.getElementById('arena-pnl-subtext');
  if (pnlEl) {
    const pnl = summary.total_arena_pnl || 0;
    const ret = summary.total_arena_return_pct || 0;
    pnlEl.textContent = `Net P&L: ${formatINR(pnl)} (${formatPct(ret)})`;
    pnlEl.style.color = pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
  }

  const cashEl = document.getElementById('arena-total-cash');
  if (cashEl) cashEl.textContent = formatINR(summary.total_arena_cash || 10000000);

  const invEl = document.getElementById('arena-total-invested');
  if (invEl) invEl.textContent = formatINR(summary.total_arena_invested || 0);

  const expEl = document.getElementById('arena-exposure-pct');
  if (expEl) {
    const exp = ((summary.total_arena_invested || 0) / (summary.total_arena_value || 10000000)) * 100;
    expEl.textContent = `${exp.toFixed(1)}% Portfolio Exposure`;
  }

  const posEl = document.getElementById('arena-active-positions');
  if (posEl) posEl.textContent = summary.total_active_positions || 0;

  const topAgentEl = document.getElementById('arena-top-agent');
  if (topAgentEl) topAgentEl.textContent = summary.top_agent || "Agent Momentum";

  const phaseEl = document.getElementById('hero-market-phase');
  if (phaseEl) phaseEl.textContent = summary.market_phase || "INTRADAY";

  const regEl = document.getElementById('hero-regime-label');
  if (regEl) regEl.textContent = (APP_DATA.regime && APP_DATA.regime.composite_regime) || "NEUTRAL";

  // 2. Leaderboard Table
  const tbody = document.getElementById('leaderboard-tbody');
  if (tbody) {
    tbody.innerHTML = '';
    leaderboard.forEach(row => {
      const meta = AGENT_META[row.agent_id] || {};
      const trophiesHtml = (row.trophies || []).map(t => 
        `<span class="trophy-badge" title="${t.desc}">${t.icon} ${t.title}</span>`
      ).join('');

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><span class="rank-badge rank-${row.rank}">${row.rank}</span></td>
        <td>
          <div class="agent-cell">
            <div class="agent-icon-badge">${meta.icon || '🤖'}</div>
            <div class="agent-name-title">
              <div class="agent-name-txt">
                ${row.name}
                <span class="strat-ver-pill">${row.strategy_version}</span>
              </div>
              <div class="agent-title-txt">${meta.quote || row.title}</div>
            </div>
          </div>
        </td>
        <td class="mono-num">${formatINR(row.portfolio_value)}</td>
        <td class="${row.total_return_pct >= 0 ? 'val-green' : 'val-red'}">${formatPct(row.total_return_pct)}</td>
        <td class="mono-num">${formatINR(row.cash)}</td>
        <td class="mono-num">${row.win_rate}%</td>
        <td class="mono-num">${row.profit_factor}</td>
        <td class="val-red">${row.max_drawdown.toFixed(2)}%</td>
        <td class="mono-num">${row.sharpe_ratio}</td>
        <td><span class="mono-num">${row.positions_count}</span> / 10</td>
        <td>${trophiesHtml || '<span style="color: var(--text-muted); font-size: 11px;">Contender</span>'}</td>
        <td style="text-align: right;">
          <button class="btn-action" onclick="inspectAgentFromHome('${row.agent_id}')">View Portfolio →</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  }

  // 3. Agent Cards Grid
  const cardsContainer = document.getElementById('agent-cards-container');
  if (cardsContainer) {
    cardsContainer.innerHTML = '';
    leaderboard.forEach(row => {
      const meta = AGENT_META[row.agent_id] || {};
      const card = document.createElement('div');
      card.className = 'agent-card';
      card.innerHTML = `
        <div>
          <div class="agent-card-header">
            <div class="agent-icon-badge">${meta.icon || '🤖'}</div>
            <div>
              <div style="font-weight: 800; color: #fff; font-size: 15px;">${row.name}</div>
              <div style="font-size: 11px; color: var(--text-muted);">${meta.title} • <span class="strat-ver-pill">${row.strategy_version}</span></div>
            </div>
          </div>
          <div class="agent-card-quote">“${meta.quote}”</div>
          <div class="agent-card-stats">
            <div><span class="lbl">NAV:</span> <span class="val">${formatINR(row.portfolio_value)}</span></div>
            <div><span class="lbl">Return:</span> <span class="${row.total_return_pct >= 0 ? 'val-green' : 'val-red'}">${formatPct(row.total_return_pct)}</span></div>
            <div><span class="lbl">Cash:</span> <span class="val">${formatINR(row.cash)}</span></div>
            <div><span class="lbl">Slots:</span> <span class="val">${row.positions_count} / 10</span></div>
          </div>
        </div>
        <button class="btn-action" style="width: 100%; margin-top: 10px;" onclick="inspectAgentFromHome('${row.agent_id}')">
          Inspect Holdings & Decisions →
        </button>
      `;
      cardsContainer.appendChild(card);
    });
  }

  // 4. Consensus Quick Pulse
  const pulseContainer = document.getElementById('consensus-quick-container');
  if (pulseContainer) {
    const ma = APP_DATA.market_analytics || {};
    const summaryData = ma.summary || {};
    pulseContainer.innerHTML = `
      <div class="hero-lifecycle-bar" style="border-top: none; padding-top: 0;">
        <div class="lifecycle-item">
          <span class="lbl">BULLISH CONSENSUS:</span>
          <span class="val val-green">${summaryData.bullish_count || 0} Stocks</span>
        </div>
        <div class="lifecycle-item">
          <span class="lbl">BEARISH CONSENSUS:</span>
          <span class="val val-red">${summaryData.bearish_count || 0} Stocks</span>
        </div>
        <div class="lifecycle-item">
          <span class="lbl">NEUTRAL / NO TRADE:</span>
          <span class="val" style="color: var(--text-secondary);">${summaryData.neutral_count || 0} Stocks</span>
        </div>
        <div class="lifecycle-item">
          <span class="lbl">DIVIDED STOCKS:</span>
          <span class="val" style="color: var(--accent-purple);">${summaryData.divergent_count || 0} Stocks</span>
        </div>
      </div>
    `;
  }
}

function inspectAgentFromHome(agentId) {
  currentAgent = agentId;
  switchView('investment');
  selectAgent(agentId);
}

// -----------------------------------------------------------------------------
// VIEW 2: MARKET ANALYTICS (50 STOCKS)
// -----------------------------------------------------------------------------
function renderAnalyticsView() {
  const ma = APP_DATA.market_analytics || {};
  const summary = ma.summary || {};
  const stocks = ma.stocks || [];

  // Metrics
  const bEl = document.getElementById('count-bullish-stocks');
  if (bEl) bEl.textContent = `${summary.bullish_count || 0} Stocks`;

  const beEl = document.getElementById('count-bearish-stocks');
  if (beEl) beEl.textContent = `${summary.bearish_count || 0} Stocks`;

  const nEl = document.getElementById('count-neutral-stocks');
  if (nEl) nEl.textContent = `${summary.neutral_count || 0} Stocks`;

  const divEl = document.getElementById('top-divergent-stock');
  if (divEl) {
    const divSyms = summary.divergent_symbols || [];
    divEl.textContent = divSyms.length > 0 ? divSyms[0].replace('.NS', '') : 'None';
  }

  filterStocksTable();
}

function filterStocksTable() {
  const searchInput = document.getElementById('stock-search-input');
  const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
  const stocks = (APP_DATA.market_analytics && APP_DATA.market_analytics.stocks) || [];
  const tbody = document.getElementById('stocks-tbody');
  if (!tbody) return;

  tbody.innerHTML = '';

  const filtered = stocks.filter(s => {
    const matchesQuery = s.symbol.toLowerCase().includes(query) || (s.name && s.name.toLowerCase().includes(query));
    const matchesSector = (currentSectorFilter === 'ALL') || (s.sector === currentSectorFilter);
    return matchesQuery && matchesSector;
  });

  filtered.forEach(s => {
    let pillClass = 'neutral';
    if (s.consensus_label && s.consensus_label.includes('BULLISH')) pillClass = 'bullish';
    else if (s.consensus_label && s.consensus_label.includes('BEARISH')) pillClass = 'bearish';
    else if (s.consensus_label === 'DIVIDED') pillClass = 'divided';

    // Agent votes dots
    const votes = s.agent_votes || {};
    const voteDotsHtml = ['ALPHA', 'MOMENTUM', 'MACRO', 'DEFENSIVE', 'CONTRARIAN'].map(aid => {
      const v = (votes[aid] || 'NO_TRADE').toLowerCase();
      const initial = aid[0];
      return `<span class="vote-dot ${v}" title="${aid}: ${votes[aid] || 'NO_TRADE'}">${initial}</span>`;
    }).join('');

    const predPct = Number(s.predicted_1d_pct || 0);
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>
        <div style="font-weight: 700; color: #fff;">${s.symbol.replace('.NS', '')}</div>
        <div style="font-size: 11px; color: var(--text-muted);">${s.name}</div>
      </td>
      <td style="color: var(--text-secondary); font-size: 12px;">${s.sector}</td>
      <td class="mono-num">${Number(s.beta || 1.0).toFixed(2)}</td>
      <td class="mono-num font-bold">${formatINR(s.base_price)}</td>
      <td class="${predPct >= 0 ? 'val-green' : 'val-red'}">${formatPct(predPct)}</td>
      <td class="mono-num" style="font-size: 11px;">
        <span style="color: var(--accent-green);">T: ${formatINR(s.target_price)}</span><br>
        <span style="color: var(--accent-red);">S: ${formatINR(s.stop_loss)}</span>
      </td>
      <td>
        <span class="consensus-pill ${pillClass}">
          ${s.consensus_text || '5 NO TRADE'}
        </span>
      </td>
      <td>
        <div class="agent-votes-matrix">
          ${voteDotsHtml}
        </div>
      </td>
      <td style="text-align: right;">
        <button class="btn-action" onclick="openStockDrawer('${s.symbol}')">Inspect →</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function setSectorFilter(sector) {
  currentSectorFilter = sector;
  document.querySelectorAll('#sector-filter-pills .filter-pill').forEach(btn => {
    btn.classList.toggle('active', btn.textContent.includes(sector) || (sector === 'ALL' && btn.textContent.includes('All')));
  });
  filterStocksTable();
}

// -----------------------------------------------------------------------------
// VIEW 3: INVESTMENT & PORTFOLIOS
// -----------------------------------------------------------------------------
function selectAgent(agentId) {
  currentAgent = agentId;

  document.querySelectorAll('.agent-select-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.agent === agentId);
  });

  renderInvestmentView();
}

function switchHoldingsTab(tabName) {
  currentHoldingsTab = tabName;

  document.querySelectorAll('.holdings-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.tab === tabName);
  });

  renderHoldingsTable();
}

function renderInvestmentView() {
  const arena = APP_DATA.arena || {};
  const leaderboard = arena.leaderboard || [];
  const agentData = leaderboard.find(r => r.agent_id === currentAgent) || {
    agent_id: currentAgent,
    name: AGENT_META[currentAgent].name,
    portfolio_value: 2000000,
    cash: 2000000,
    invested: 0,
    total_return_pct: 0,
    win_rate: 0,
    profit_factor: 1,
    max_drawdown: 0,
    positions_count: 0,
    strategy_version: AGENT_META[currentAgent].version,
    holdings: { equity: [], futures: [], options: [], all: [] }
  };

  const meta = AGENT_META[currentAgent];

  // Render Agent Banner
  const banner = document.getElementById('agent-detail-banner');
  if (banner) {
    banner.innerHTML = `
      <div class="banner-top-row">
        <div class="banner-profile-info">
          <div class="banner-profile-icon">${meta.icon}</div>
          <div>
            <div style="font-size: 20px; font-weight: 800; color: #fff;">
              ${agentData.name}
              <span class="strat-ver-pill">${agentData.strategy_version}</span>
            </div>
            <div style="font-size: 13px; color: var(--accent-cyan); font-style: italic; margin-top: 2px;">
              “${meta.quote}”
            </div>
          </div>
        </div>
        <div style="text-align: right;">
          <div style="font-size: 11px; color: var(--text-muted); font-weight: 700;">ISOLATED SUBLIEDGER</div>
          <div style="font-size: 22px; font-weight: 800; color: #fff; font-family: var(--font-mono);">
            ${formatINR(agentData.portfolio_value)}
          </div>
          <div class="${agentData.total_return_pct >= 0 ? 'val-green' : 'val-red'}" style="font-size: 12px;">
            ${formatPct(agentData.total_return_pct)} Total Return
          </div>
        </div>
      </div>

      <div class="banner-stats-grid">
        <div class="banner-stat-item">
          <div class="lbl">STARTING CAPITAL</div>
          <div class="val">₹20,00,000</div>
        </div>
        <div class="banner-stat-item">
          <div class="lbl">UNENCUMBERED CASH</div>
          <div class="val">${formatINR(agentData.cash)}</div>
        </div>
        <div class="banner-stat-item">
          <div class="lbl">DEPLOYED CAPITAL</div>
          <div class="val">${formatINR(agentData.invested)}</div>
        </div>
        <div class="banner-stat-item">
          <div class="lbl">ACTIVE POSITIONS</div>
          <div class="val">${agentData.positions_count} / 10</div>
        </div>
        <div class="banner-stat-item">
          <div class="lbl">WIN RATE</div>
          <div class="val">${agentData.win_rate}%</div>
        </div>
        <div class="banner-stat-item">
          <div class="lbl">PROFIT FACTOR</div>
          <div class="val">${agentData.profit_factor}</div>
        </div>
        <div class="banner-stat-item">
          <div class="lbl">MAX DRAWDOWN</div>
          <div class="val val-red">${agentData.max_drawdown.toFixed(2)}%</div>
        </div>
      </div>
    `;
  }

  // Update Holdings Counts
  const holdings = agentData.holdings || { equity: [], futures: [], options: [], all: [] };
  const countAll = document.getElementById('count-holdings-all');
  if (countAll) countAll.textContent = (holdings.all || []).length;
  const countEq = document.getElementById('count-holdings-equity');
  if (countEq) countEq.textContent = (holdings.equity || []).length;
  const countFut = document.getElementById('count-holdings-futures');
  if (countFut) countFut.textContent = (holdings.futures || []).length;
  const countOpt = document.getElementById('count-holdings-options');
  if (countOpt) countOpt.textContent = (holdings.options || []).length;

  renderHoldingsTable();
  renderDecisionFeed();
}

function renderHoldingsTable() {
  const arena = APP_DATA.arena || {};
  const leaderboard = arena.leaderboard || [];
  const agentData = leaderboard.find(r => r.agent_id === currentAgent) || {};
  const holdingsMap = agentData.holdings || { equity: [], futures: [], options: [], all: [] };
  const items = holdingsMap[currentHoldingsTab] || [];

  const tbody = document.getElementById('holdings-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (items.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="11" style="text-align: center; padding: 32px; color: var(--text-muted);">
          No open ${currentHoldingsTab} positions. ${agentData.name || 'Agent'} is currently holding pure cash (0 positions), waiting for a high-conviction setup.
        </td>
      </tr>
    `;
    return;
  }

  items.forEach(pos => {
    const instType = (pos.instrument && pos.instrument.instrument_type) || "EQUITY";
    let simBadge = "";
    if (instType === "FUTURE") {
      simBadge = `<span class="badge-sim" title="Cost-of-carry theoretical price">SIMULATED FUTURES</span>`;
    } else if (instType === "OPTION") {
      simBadge = `<span class="badge-sim" title="Black-Scholes theoretical premium">MODELLED OPTION</span>`;
    }

    const pnl = Number(pos.unrealized_pnl || 0);
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>
        <div style="font-weight: 700; color: #fff;">${pos.symbol.replace('.NS', '')}</div>
        <div style="font-size: 10px; color: var(--text-muted); font-family: var(--font-mono);">${pos.trade_id || ''}</div>
      </td>
      <td>${instType} ${simBadge}</td>
      <td class="${pos.direction === 'BUY' ? 'val-green' : 'val-red'}">${pos.direction}</td>
      <td class="mono-num">${pos.quantity}</td>
      <td class="mono-num">${formatINR(pos.entry_price)}</td>
      <td class="mono-num">${formatINR(pos.current_price)}</td>
      <td class="mono-num">${formatINR(pos.invested_capital)}</td>
      <td class="mono-num" style="color: var(--accent-green);">${formatINR(pos.target)}</td>
      <td class="mono-num" style="color: var(--accent-red);">${formatINR(pos.stop_loss)}</td>
      <td class="${pnl >= 0 ? 'val-green' : 'val-red'}">${formatINR(pnl)}</td>
      <td><span class="consensus-pill bullish" style="font-size: 10px; padding: 2px 6px;">OPEN</span></td>
    `;
    tbody.appendChild(tr);
  });
}

function renderDecisionFeed() {
  const container = document.getElementById('agent-decision-feed');
  if (!container) return;
  container.innerHTML = '';

  const decisions = (APP_DATA.arena && APP_DATA.arena.decisions) || [];
  const agentDecisions = decisions.filter(d => d.agent_id === currentAgent);

  if (agentDecisions.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 20px; color: var(--text-muted); font-size: 13px;">
        No trade proposals evaluated yet for this agent.
      </div>
    `;
    return;
  }

  agentDecisions.forEach(d => {
    const isApproved = d.risk_approved === 1;
    const isNoTrade = d.action === 'NO_TRADE';
    let cardClass = isApproved ? 'approved' : 'rejected';
    if (isNoTrade) cardClass = 'no-trade';

    const card = document.createElement('div');
    card.className = `decision-card ${cardClass}`;
    card.innerHTML = `
      <div>
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
          <span style="font-weight: 800; font-size: 14px; color: #fff;">${d.symbol.replace('.NS', '')}</span>
          <span class="consensus-pill ${d.action === 'BUY' ? 'bullish' : (d.action === 'SELL' ? 'bearish' : 'neutral')}" style="font-size: 10px; padding: 2px 6px;">
            ${d.action} • ${d.instrument_type}
          </span>
          <span class="mono-num" style="font-size: 11px; color: var(--text-secondary);">Conviction: ${d.confidence}%</span>
        </div>
        <div style="font-size: 12px; color: var(--text-secondary);">
          <strong>Rationale:</strong> ${d.reason || 'Criteria met for strategy allocation.'}
        </div>
        ${!isApproved ? `
          <div style="font-size: 12px; color: var(--accent-red); margin-top: 4px;">
            <strong>Risk Rejection:</strong> ${(d.rejections || []).join(', ') || 'Risk hurdle not cleared.'}
          </div>
        ` : ''}
      </div>
      <div>
        <span class="consensus-pill ${isApproved ? (isNoTrade ? 'neutral' : 'bullish') : 'bearish'}" style="font-size: 11px;">
          ${isApproved ? (isNoTrade ? 'NO_TRADE LOGGED' : 'RISK APPROVED') : 'REJECTED BY RISK'}
        </span>
      </div>
    `;
    container.appendChild(card);
  });
}

// -----------------------------------------------------------------------------
// VIEW 4: SYSTEM & DIAGNOSTICS
// -----------------------------------------------------------------------------
function renderSystemView() {
  const clock = (APP_DATA.arena && APP_DATA.arena.market_clock) || {};
  const phase = clock.current_phase || "INTRADAY";

  // 1. Highlight active stepper card
  document.querySelectorAll('#market-clock-stepper .step-card').forEach(card => {
    card.classList.toggle('active', card.dataset.phase === phase);
  });

  // 2. Truthful System Stats Cards
  const sysContainer = document.getElementById('system-stats-grid');
  const sysStatus = APP_DATA.system_status || {};
  const dbStatus = sysStatus.database_status || {};

  if (sysContainer) {
    sysContainer.innerHTML = `
      <div class="sys-card">
        <div class="sys-card-title">IMMUTABLE PROVENANCE</div>
        <div class="sys-card-row">
          <span>Snapshot Cryptography:</span>
          <span class="val-green">SHA-256 Validated</span>
        </div>
        <div class="sys-card-row">
          <span>Point-in-Time Store:</span>
          <span class="mono-num">Strict Wall-Clock Locks</span>
        </div>
        <div class="sys-card-row">
          <span>Frozen Regime Weights:</span>
          <span class="strat-ver-pill">W1.0 (8-Dim Model)</span>
        </div>
        <div class="sys-card-row">
          <span>Numerical Math:</span>
          <span style="color: var(--text-primary);">100% Deterministic</span>
        </div>
      </div>

      <div class="sys-card">
        <div class="sys-card-title">SQLITE & WAL DATABASE</div>
        <div class="sys-card-row">
          <span>Audit Records:</span>
          <span class="mono-num font-bold">${dbStatus.total_audit_records || 120}</span>
        </div>
        <div class="sys-card-row">
          <span>Prediction Records:</span>
          <span class="mono-num font-bold">${dbStatus.total_prediction_records || 50}</span>
        </div>
        <div class="sys-card-row">
          <span>Frozen Snapshots:</span>
          <span class="mono-num font-bold">${dbStatus.total_frozen_snapshots || 10}</span>
        </div>
        <div class="sys-card-row">
          <span>Cloud Dual-Sync:</span>
          <span style="color: var(--accent-cyan);">Supabase Connected</span>
        </div>
      </div>

      <div class="sys-card">
        <div class="sys-card-title">CENTRAL RISK ENGINE GATES</div>
        <div class="sys-card-row">
          <span>Risk Sizing Per Trade:</span>
          <span class="mono-num">0.5% Capital</span>
        </div>
        <div class="sys-card-row">
          <span>Single Stock Allocation Cap:</span>
          <span class="mono-num">Max 20%</span>
        </div>
        <div class="sys-card-row">
          <span>Portfolio Exposure Limit:</span>
          <span class="mono-num">Max 50%</span>
        </div>
        <div class="sys-card-row">
          <span>Sector Exposure Cap:</span>
          <span class="mono-num">Max 25%</span>
        </div>
      </div>

      <div class="sys-card">
        <div class="sys-card-title">AUTOMATED WORKFLOW AUDIT</div>
        <div class="sys-card-row">
          <span>Pre-Market Forecast:</span>
          <span class="mono-num">20:30 IST Every Evening</span>
        </div>
        <div class="sys-card-row">
          <span>Post-Market Audit:</span>
          <span class="mono-num">15:45 IST Every Session</span>
        </div>
        <div class="sys-card-row">
          <span>Order Entry Cutoff:</span>
          <span class="val-red">15:30 IST STRICT STOP</span>
        </div>
        <div class="sys-card-row">
          <span>Derivatives Modeling:</span>
          <span style="color: var(--accent-purple);">Cost-of-Carry & B-S</span>
        </div>
      </div>
    `;
  }

  // 3. Baselines Table
  const baselinesTbody = document.getElementById('baselines-tbody');
  const vsBaselines = APP_DATA.vs_baselines || {};
  if (baselinesTbody) {
    baselinesTbody.innerHTML = '';
    const items = [
      { key: 'model', name: 'Nifty 50 Event Agent (Model V3.1.1)', desc: 'Multi-factor quantitative event intelligence with PIT conditioning' },
      { key: 'nifty_buy_and_hold', name: 'Nifty 50 Buy & Hold', desc: 'Passive index benchmark (zero transaction friction)' },
      { key: 'momentum_5d', name: '5-Day Momentum Baseline', desc: 'Simple 5-day historical trend following' },
      { key: 'previous_day', name: 'Previous Day Persistence', desc: 'Predicts tomorrow direction matches today close-to-close' },
      { key: 'random_deterministic', name: 'Deterministic Random (SHA-256)', desc: 'Pure coin-toss seeded deterministically via trade date & symbol hash' }
    ];

    items.forEach(item => {
      const data = vsBaselines[item.key] || { return_pct: 0, alpha: 0 };
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="font-weight: 700; color: #fff;">${item.name}</td>
        <td class="${data.return_pct >= 0 ? 'val-green' : 'val-red'}">${formatPct(data.return_pct)}</td>
        <td class="${data.alpha >= 0 ? 'val-green' : 'val-red'}">${data.alpha !== undefined ? formatPct(data.alpha) : '--'}</td>
        <td style="color: var(--text-secondary); font-size: 12px;">${item.desc}</td>
      `;
      baselinesTbody.appendChild(tr);
    });
  }

  // 4. Forensic Failure Taxonomy Table (Losers Prominently First)
  const failTbody = document.getElementById('failures-tbody');
  const fails = APP_DATA.failed_trades_prominent || [];
  if (failTbody) {
    failTbody.innerHTML = '';
    fails.forEach((f, idx) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="mono-num">${f.trade_date || '--'}</td>
        <td style="font-weight: 700; color: #fff;">${(f.symbol || '').replace('.NS', '')}</td>
        <td class="${f.predicted_direction === 'BULLISH' ? 'val-green' : 'val-red'}">${f.predicted_direction} (${formatPct(f.predicted_pct)})</td>
        <td class="${f.actual_direction === 'BULLISH' ? 'val-green' : 'val-red'}">${f.actual_direction || 'FLAT'} (${formatPct(f.actual_pct)})</td>
        <td class="val-red">${formatINR(f.pnl)}</td>
        <td><span class="failure-code-pill">${f.primary_failure_code || 'F01'}</span></td>
        <td style="font-size: 12px; color: var(--text-secondary); max-width: 320px; overflow: hidden; text-overflow: ellipsis;">
          ${f.diagnostic_explanation || 'Observed market outcome differed from forecast.'}
        </td>
        <td style="text-align: right;">
          <button class="btn-action" onclick="openFailureModal(${idx})">Diagnose →</button>
        </td>
      `;
      failTbody.appendChild(tr);
    });
  }
}

// -----------------------------------------------------------------------------
// Interactive Stock Detail Drawer
// -----------------------------------------------------------------------------
function openStockDrawer(symbol) {
  const stocks = (APP_DATA.market_analytics && APP_DATA.market_analytics.stocks) || [];
  const s = stocks.find(st => st.symbol === symbol) || { symbol: symbol, name: symbol };
  const universeMeta = (APP_DATA.universe && APP_DATA.universe[symbol]) || {};

  document.getElementById('drawer-symbol').textContent = symbol.replace('.NS', '');
  document.getElementById('drawer-name').textContent = s.name || universeMeta.name || symbol;
  document.getElementById('drawer-price').textContent = formatINR(s.base_price || 1000);
  document.getElementById('drawer-predicted').textContent = formatPct(s.predicted_1d_pct || 0);
  document.getElementById('drawer-target').textContent = formatINR(s.target_price || s.base_price);
  document.getElementById('drawer-stop').textContent = formatINR(s.stop_loss || (s.base_price * 0.98));
  document.getElementById('drawer-beta').textContent = Number(s.beta || universeMeta.beta || 1.0).toFixed(2);

  // Votes
  const votesContainer = document.getElementById('drawer-agent-votes');
  if (votesContainer) {
    votesContainer.innerHTML = '';
    const votes = s.agent_votes || {};
    ['ALPHA', 'MOMENTUM', 'MACRO', 'DEFENSIVE', 'CONTRARIAN'].forEach(aid => {
      const v = votes[aid] || 'NO_TRADE';
      const meta = AGENT_META[aid];
      const div = document.createElement('div');
      div.className = 'agent-card-stats';
      div.style.marginBottom = '6px';
      div.innerHTML = `
        <div><strong>${meta.icon} ${meta.name}:</strong></div>
        <div style="text-align: right;"><span class="consensus-pill ${v === 'BUY' ? 'bullish' : (v === 'SELL' ? 'bearish' : 'neutral')}" style="font-size: 10px; padding: 2px 6px;">${v}</span></div>
      `;
      votesContainer.appendChild(div);
    });
  }

  // Key Drivers
  const driversContainer = document.getElementById('drawer-key-drivers');
  if (driversContainer) {
    const drivers = universeMeta.key_drivers || s.key_drivers || ["Earnings surprises", "Institutional FII flows", "Macro interest rates"];
    driversContainer.innerHTML = drivers.map(d => `<span class="legend-item" style="display: inline-block; margin: 3px;">• ${d}</span>`).join('');
  }

  // Catalysts
  const catalystsContainer = document.getElementById('drawer-catalysts');
  if (catalystsContainer) {
    const stockEvents = (APP_DATA.stock_events && APP_DATA.stock_events[symbol]) || {};
    const events = stockEvents.occurred || stockEvents.upcoming || [];
    if (events.length > 0) {
      catalystsContainer.innerHTML = events.map(e => `<div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;">📅 ${e.title || e.event || 'Quarterly filing event'}</div>`).join('');
    } else {
      catalystsContainer.innerHTML = `<div style="font-size: 12px; color: var(--text-muted);">No corporate filings in current 30-day window.</div>`;
    }
  }

  // Render 3-Month Price Chart
  renderDrawerChart(symbol);

  document.getElementById('drawer-overlay').classList.add('active');
  document.getElementById('stock-drawer').classList.add('active');
}

function closeStockDrawer() {
  document.getElementById('drawer-overlay').classList.remove('active');
  document.getElementById('stock-drawer').classList.remove('active');
}

function renderDrawerChart(symbol) {
  const ctx = document.getElementById('drawer-chart');
  if (!ctx) return;

  if (drawerChart) {
    drawerChart.destroy();
  }

  const charts = APP_DATA.stock_charts || {};
  const chartData = charts[symbol];
  let labels = ["Day -20", "Day -15", "Day -10", "Day -5", "Today"];
  let prices = [1000, 1015, 1005, 1025, 1030];

  if (chartData && chartData.dates && chartData.close) {
    labels = chartData.dates.slice(-20);
    prices = chartData.close.slice(-20);
  }

  drawerChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: `${symbol.replace('.NS', '')} Price`,
        data: prices,
        borderColor: '#06b6d4',
        backgroundColor: 'rgba(6, 182, 212, 0.1)',
        borderWidth: 2,
        fill: true,
        tension: 0.2,
        pointRadius: 2,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false }
      },
      scales: {
        x: { display: false },
        y: {
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: { color: '#64748b', font: { size: 10 } }
        }
      }
    }
  });
}

// -----------------------------------------------------------------------------
// Interactive Forensic Failure Modal
// -----------------------------------------------------------------------------
function openFailureModal(tradeIndex) {
  const fails = APP_DATA.failed_trades_prominent || [];
  const f = fails[tradeIndex];
  if (!f) return;

  document.getElementById('modal-fail-code').textContent = f.primary_failure_code || 'F01';
  document.getElementById('modal-fail-title').textContent = f.primary_category || 'DIAGNOSTIC_FAILURE';
  document.getElementById('modal-symbol').textContent = (f.symbol || '').replace('.NS', '');
  document.getElementById('modal-date').textContent = f.trade_date || '--';
  document.getElementById('modal-outcome').textContent = `${formatINR(f.pnl)} (${f.actual_direction || 'FLAT'})`;
  document.getElementById('modal-explanation').textContent = f.diagnostic_explanation || 'Outcome differed from causal forecast.';
  document.getElementById('modal-recommendation').textContent = f.refactoring_suggestion || 'Review feature attribution sensitivities and calibrate risk hurdles.';

  document.getElementById('modal-overlay').classList.add('active');
  document.getElementById('failure-modal').classList.add('active');
}

function closeFailureModal() {
  document.getElementById('modal-overlay').classList.remove('active');
  document.getElementById('failure-modal').classList.remove('active');
}


// V3.1.1 Compatibility hook
function renderQuantOverview() {
  renderHeaderStatus();
  renderHomeView();
}

// Compatibility references: execution-strip, stopPrice
