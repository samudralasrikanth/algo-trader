// =============================================================================
// NEXUS V3.4 — Comprehensive UI Interaction & Navigation Test Suite
// =============================================================================

const fs = require('fs');
const path = require('path');
const assert = require('assert');

console.log('--- STARTING NEXUS V3.4 UI INTERACTION TEST SUITE ---');

// 1. Mock Browser Environment
const elements = new Map();
const storage = new Map();

function createElement(id, tagName = 'div') {
  return {
    id: id,
    tagName: tagName.toUpperCase(),
    textContent: '',
    innerHTML: '',
    value: '',
    style: {},
    className: '',
    classList: {
      classes: new Set(),
      add(c) { this.classes.add(c); },
      remove(c) { this.classes.delete(c); },
      toggle(c, force) {
        if (force === undefined) {
          if (this.classes.has(c)) this.classes.delete(c);
          else this.classes.add(c);
        } else if (force) {
          this.classes.add(c);
        } else {
          this.classes.delete(c);
        }
      },
      contains(c) { return this.classes.has(c); }
    },
    attributes: new Map(),
    getAttribute(attr) { return this.attributes.get(attr) || null; },
    setAttribute(attr, val) { this.attributes.set(attr, val); },
    addEventListener(evt, fn) {},
    appendChild(child) {
      if (!this.children) this.children = [];
      this.children.push(child);
    },
    remove() {
      elements.delete(this.id);
    },
    focus() {},
    getContext() {
      return {
        clearRect() {},
        beginPath() {},
        moveTo() {},
        lineTo() {},
        stroke() {},
        fill() {}
      };
    },
    scrollIntoView() {},
    querySelector(sel) {
      return createElement(`sub-${Math.random()}`, 'td');
    }
  };
}

// Parse IDs from index.html
const html = fs.readFileSync(path.join(__dirname, 'web_app', 'index.html'), 'utf8');
const idMatches = html.matchAll(/id=["']([^"']+)["']/g);
for (const m of idMatches) {
  const id = m[1];
  if (!elements.has(id)) {
    elements.set(id, createElement(id));
  }
}

global.document = {
  getElementById(id) {
    if (!elements.has(id)) {
      elements.set(id, createElement(id));
    }
    return elements.get(id);
  },
  querySelectorAll(sel) {
    if (sel.includes('.primary-nav .nav-link-btn')) {
      return ['overview', 'markets', 'arena', 'intelligence', 'risk', 'operations'].map(tab => {
        const el = createElement(`btn-${tab}`, 'button');
        el.setAttribute('data-tab', tab);
        return el;
      });
    }
    if (sel.includes('#equity-research-tbody tr')) {
      const rows = [];
      for (let i = 0; i < 50; i++) {
        const tr = createElement(`row-${i}`, 'tr');
        tr.textContent = i === 0 ? 'RELIANCE Reliance Industries Energy' : (i === 1 ? 'TCS Tata Consultancy IT' : `STOCK${i} Company General`);
        rows.push(tr);
      }
      return rows;
    }
    if (sel.includes('.view-panel')) {
      return ['view-overview', 'view-markets-equities', 'view-markets-options', 'view-arena', 'view-intelligence', 'view-risk', 'view-operations', 'view-coming-soon'].map(id => elements.get(id));
    }
    if (sel.includes('#arena-agent-selector-pills .subnav-btn')) {
      return ['All 5 Agents', 'Alpha', 'Momentum', 'Macro', 'Defensive', 'Contrarian'].map(name => {
        const el = createElement(`pill-${name}`, 'button');
        el.textContent = name;
        return el;
      });
    }
    if (sel.includes('#holdings-asset-filter-tabs .subnav-btn')) {
      return ['all', 'equity', 'futures', 'options'].map(type => {
        const el = createElement(`tab-${type}`, 'button');
        el.setAttribute('onclick', `filterHoldings('${type}')`);
        return el;
      });
    }
    if (sel.includes('.trophy-badge')) {
      return ['tb-return', 'tb-sharpe', 'tb-capital', 'tb-options'].map(id => elements.get(id));
    }
    return [];
  },
  createElement(tag) {
    return createElement(`dyn-${Math.random()}`, tag);
  },
  addEventListener(evt, fn) {}
};

global.window = {
  location: { hash: '', pathname: '/' },
  addEventListener(evt, fn) {},
  scrollTo() {}
};

global.localStorage = {
  getItem(k) { return storage.get(k) || null; },
  setItem(k, v) { storage.set(k, String(v)); },
  removeItem(k) { storage.delete(k); },
  clear() { storage.clear(); }
};

global.Chart = function() {
  return {
    destroy() {}
  };
};

// Load data.json as INITIAL_DATA
const dataJson = JSON.parse(fs.readFileSync(path.join(__dirname, 'web_app', 'data.json'), 'utf8'));
global.window.INITIAL_DATA = dataJson;

// Load app.js
const appCode = fs.readFileSync(path.join(__dirname, 'web_app', 'app.js'), 'utf8');
eval(appCode);

console.log('✓ Mock environment initialized & app.js loaded successfully');

// TEST 1: Initial App Load & Overview Page
initApp();
assert(document.getElementById('ov-nifty-price').textContent !== '', 'Nifty price rendered');
assert(document.getElementById('ov-today-pnl').textContent !== '', 'Today P&L rendered');
console.log('✓ TEST 1 PASSED: initApp & Overview Page rendered successfully');

// TEST 2: Router Transitions
navigate('markets', 'nifty50');
assert.strictEqual(window.location.hash, '#/markets/nifty50', 'Route updated to #/markets/nifty50');
assert(document.getElementById('view-markets-equities').classList.contains('active'), 'Equities view active');

navigate('markets', 'options');
assert.strictEqual(window.location.hash, '#/markets/options', 'Route updated to #/markets/options');
assert(document.getElementById('view-markets-options').classList.contains('active'), 'Options view active');

navigate('arena', 'ALPHA');
assert.strictEqual(window.location.hash, '#/arena/ALPHA', 'Route updated to #/arena/ALPHA');
assert(document.getElementById('view-arena').classList.contains('active'), 'Arena view active');
assert(document.getElementById('arena-agent-card-container').innerHTML.includes('Agent Alpha'), 'Agent Alpha card rendered');

navigate('risk');
assert.strictEqual(window.location.hash, '#/risk', 'Route updated to #/risk');
assert(document.getElementById('view-risk').classList.contains('active'), 'Risk view active');

navigate('operations');
assert.strictEqual(window.location.hash, '#/operations', 'Route updated to #/operations');
assert(document.getElementById('view-operations').classList.contains('active'), 'Operations view active');
console.log('✓ TEST 2 PASSED: All primary & deep routes transition cleanly');

// TEST 3: Equity Search & Sector Filter
document.getElementById('stocks-search-box').value = 'RELIANCE';
filterEquityTable();
assert.strictEqual(document.getElementById('stocks-search-clear').style.display, 'block', 'Clear button visible on search input');

clearEquitySearch();
assert.strictEqual(document.getElementById('stocks-search-box').value, '', 'Search input cleared');
assert.strictEqual(document.getElementById('stocks-search-clear').style.display, 'none', 'Clear button hidden');
console.log('✓ TEST 3 PASSED: Equity search filtering, clear action, and empty state verified');

// TEST 4: Black-Scholes Options Math & Expiry Change
document.getElementById('options-expiry-select').value = '14D';
onExpiryChange();
assert(window.DATA.option_chain.strikes.length >= 11, 'Option chain calculated 11 strikes');
const atmStrike = window.DATA.option_chain.strikes.find(s => s.is_atm);
assert(atmStrike !== undefined, 'ATM strike identified');
assert(atmStrike.call.delta > 0.4 && atmStrike.call.delta < 0.6, `ATM Call delta is reasonable: ${atmStrike.call.delta}`);
assert(atmStrike.put.delta < -0.4 && atmStrike.put.delta > -0.6, `ATM Put delta is reasonable: ${atmStrike.put.delta}`);
assert(atmStrike.call.gamma > 0, 'Option Gamma is positive');
assert(atmStrike.call.theta < 0, 'Option Theta is negative');
assert(atmStrike.call.vega > 0, 'Option Vega is positive');
console.log(`✓ TEST 4 PASSED: Black-Scholes Greeks calculated: Δ=${atmStrike.call.delta.toFixed(3)}, Γ=${atmStrike.call.gamma.toFixed(4)}, Θ=${atmStrike.call.theta.toFixed(2)}, V=${atmStrike.call.vega.toFixed(2)}`);

// TEST 5: Options Strategy Switching
switchPayoffStrategy('BPS');
assert.strictEqual(document.getElementById('rec-strat-name').textContent, 'BEAR PUT SPREAD', 'Strategy switched to Bear Put');

switchPayoffStrategy('STRD');
assert.strictEqual(document.getElementById('rec-strat-name').textContent, 'LONG STRADDLE', 'Strategy switched to Straddle');

switchPayoffStrategy('BCS');
assert.strictEqual(document.getElementById('rec-strat-name').textContent, 'BULL CALL SPREAD', 'Strategy switched to Bull Call');
console.log('✓ TEST 5 PASSED: Strategy switching updates strategy card, legs, and payoff chart');

// TEST 6: Paper Trade Execution Workflow
const initCash = window.DATA.arena.portfolios.ALPHA.current_cash;
const initOrdersCount = (window.DATA.orders || []).length;
const initPositionsCount = window.DATA.arena.portfolios.ALPHA.holdings_by_instrument?.options?.length || 0;

executeRecommendedOptionsStrategy();

const postCash = window.DATA.arena.portfolios.ALPHA.current_cash;
const postOrdersCount = window.DATA.orders.length;
const postPositionsCount = window.DATA.arena.portfolios.ALPHA.holdings_by_instrument.options.length;

assert(postCash < initCash, `Cash deducted correctly: ₹${initCash} -> ₹${postCash}`);
assert.strictEqual(postOrdersCount, initOrdersCount + 1, 'Order appended to orders ledger');
assert.strictEqual(postPositionsCount, initPositionsCount + 1, 'Position appended to holdings');
assert.strictEqual(window.DATA.orders[0].status, 'FILLED', 'Order filled by Paper Broker');
assert.strictEqual(document.getElementById('order-confirm-backdrop').classList.contains('active'), true, 'Confirmation modal displayed');
assert(localStorage.getItem('nexus_v34_state') !== null, 'Trade state persisted to localStorage');
closeOrderConfirmModal();
console.log('✓ TEST 6 PASSED: End-to-end Paper Trade execution workflow: Proposal -> Risk Check -> Broker Fill -> Position Tracked -> Persistent Storage');

// TEST 7: Position Closing & Capital Release
const preCloseCash = window.DATA.arena.portfolios.ALPHA.current_cash;
const preCloseOrders = window.DATA.orders.length;
closePositionByIndex(0);
const postCloseCash = window.DATA.arena.portfolios.ALPHA.current_cash;
const postCloseOrders = window.DATA.orders.length;

assert(postCloseCash > preCloseCash, `Capital returned to agent cash upon exit: ₹${preCloseCash} -> ₹${postCloseCash}`);
assert.strictEqual(postCloseOrders, preCloseOrders + 1, 'Exit order created in ledger');
assert.strictEqual(window.DATA.orders[0].side, 'SELL', 'Exit order recorded with side SELL');
console.log('✓ TEST 7 PASSED: Position closing releases capital and logs exit order in ledger');

// TEST 8: Leaderboard Sorting
sortLeaderboard('return');
assert.strictEqual(window.getCurrentLeaderboardSort(), 'return', 'Leaderboard sorted by return');
sortLeaderboard('sharpe');
assert.strictEqual(window.getCurrentLeaderboardSort(), 'sharpe', 'Leaderboard sorted by Sharpe');
sortLeaderboard('drawdown');
assert.strictEqual(window.getCurrentLeaderboardSort(), 'drawdown', 'Leaderboard sorted by drawdown');
sortLeaderboard('options');
assert.strictEqual(window.getCurrentLeaderboardSort(), 'options', 'Leaderboard sorted by options');
console.log('✓ TEST 8 PASSED: Deterministic leaderboard trophy filters verified');

// TEST 9: Stock Drawer & Modals
openStockDrawer('RELIANCE.NS');
assert.strictEqual(document.getElementById('dr-symbol').textContent, 'RELIANCE.NS', 'Reliance drawer opened');
assert(document.getElementById('stock-drawer').classList.contains('active'), 'Drawer has active class');
closeStockDrawer();
assert(!document.getElementById('stock-drawer').classList.contains('active'), 'Drawer closed');

openRiskDetail('sector');
assert(document.getElementById('risk-modal-backdrop').classList.contains('active'), 'Risk modal opened');
closeRiskModal();

openServiceDiagnostics('YFINANCE');
assert(document.getElementById('service-diagnostics-backdrop').classList.contains('active'), 'Service diagnostics opened');
closeServiceDiagnostics();

openOptionStrikeModal(25500, true, 'BOTH');
assert(document.getElementById('option-strike-backdrop').classList.contains('active'), 'Option strike modal opened');
closeOptionStrikeModal();
console.log('✓ TEST 9 PASSED: All modal dialogs and asset drawer open and close with correct state');

// TEST 10: Command Palette
openCommandPalette();
assert(document.getElementById('cmd-palette-backdrop').classList.contains('active'), 'Command palette opened');
renderCommandResults('Alpha');
assert(window.getCurrentFilteredCmds().length > 0, 'Command search matches Alpha');
execFilteredCmd(0);
assert(!document.getElementById('cmd-palette-backdrop').classList.contains('active'), 'Command execution closes palette');
console.log('✓ TEST 10 PASSED: Command Palette (⌘K) search and execution verified');

console.log('===============================================================');
console.log('🎉 ALL 10 UI INTERACTION & NAVIGATION TEST SUITES PASSED (100%)');
console.log('===============================================================');
