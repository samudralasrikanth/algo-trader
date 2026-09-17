// =============================================================================
// netlify/functions/live_ticker.js — Live Market Quotes Serverless API
// =============================================================================
/**
 * Serves real-time streaming quotes for Top Market Ribbon:
 * - NIFTY 50 (^NSEI)
 * - BANK NIFTY (^NSEBANK)
 * - INDIA VIX (^INDIAVIX)
 * - USD/INR (USDINR=X)
 * - BRENT CRUDE (BZ=F)
 * - GOLD (GC=F)
 *
 * Implements in-memory 10-second cache to optimize performance and prevent rate limiting.
 */

let cachedData = null;
let lastCacheTime = 0;
const CACHE_TTL_MS = 5000; // 5 seconds

const MACRO_SYMBOLS = {
  'NIFTY 50': '^NSEI',
  'BANK NIFTY': '^NSEBANK',
  'INDIA VIX': '^INDIAVIX',
  'USD/INR': 'USDINR=X',
  'BRENT': 'BZ=F',
  'GOLD': 'GC=F'
};

const DEFAULT_ACTIVE_STOCKS = [
  'LT.NS', 'APOLLOHOSP.NS', 'M&M.NS', 'BAJAJ-AUTO.NS', 'NESTLEIND.NS', 'TITAN.NS', 'TRENT.NS'
];

async function fetchQuote(sym) {
  try {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=1d&range=1d`;
    const res = await fetch(url, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)' },
      signal: AbortSignal.timeout(4500)
    });
    if (!res.ok) return null;
    const d = await res.json();
    const meta = d?.chart?.result?.[0]?.meta;
    if (!meta || meta.regularMarketPrice === undefined) return null;
    const price = meta.regularMarketPrice;
    const prev = meta.chartPreviousClose || meta.previousClose || price;
    const chg = price - prev;
    const chg_pct = prev ? (chg / prev) * 100 : 0;
    return {
      symbol: sym,
      price: Math.round(price * 100) / 100,
      previous_close: Math.round(prev * 100) / 100,
      change: Math.round(chg * 100) / 100,
      change_pct: Math.round(chg_pct * 100) / 100,
      isPositive: chg >= 0,
      timestamp: new Date().toISOString()
    };
  } catch (err) {
    return null;
  }
}

exports.handler = async function(event, context) {
  const origin = event.headers.origin || "*";
  const headers = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "public, max-age=5, stale-while-revalidate=15",
  };

  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 204, headers, body: "" };
  }

  // Parse any requested symbols from query params: ?symbols=LT.NS,APOLLOHOSP.NS
  const requestedSymbols = event.queryStringParameters?.symbols
    ? event.queryStringParameters.symbols.split(',').map(s => s.trim()).filter(Boolean)
    : [];

  const targetStocks = Array.from(new Set([...DEFAULT_ACTIVE_STOCKS, ...requestedSymbols]));

  const now = Date.now();
  if (cachedData && (now - lastCacheTime < CACHE_TTL_MS) && requestedSymbols.length === 0) {
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify(cachedData)
    };
  }

  try {
    // 1. Fetch Macro Indices
    const macroEntries = Object.entries(MACRO_SYMBOLS);
    const macroFetches = macroEntries.map(async ([name, sym]) => {
      const q = await fetchQuote(sym);
      return [name, q];
    });

    // 2. Fetch Active Stock Symbols
    const stockFetches = targetStocks.map(async (sym) => {
      const q = await fetchQuote(sym);
      return [sym, q];
    });

    const [macroResults, stockResults] = await Promise.all([
      Promise.all(macroFetches),
      Promise.all(stockFetches)
    ]);

    const quotes = {};
    for (const [name, q] of macroResults) {
      if (q) quotes[name] = q;
    }
    for (const [sym, q] of stockResults) {
      if (q) quotes[sym] = q;
    }

    // Add Domestic INR Gold Calculation
    if (quotes['GOLD']) {
      const usdRate = quotes['USD/INR']?.price || 95.15;
      const goldUsd = quotes['GOLD'].price;
      const inrPer10g = Math.round((goldUsd * usdRate / 31.1035) * 10);
      quotes['GOLD'].price_inr_10g = inrPer10g;
    }

    const payload = {
      status: "LIVE",
      source: "Yahoo Finance Live Feed",
      timestamp: new Date().toISOString(),
      quotes
    };

    if (requestedSymbols.length === 0) {
      cachedData = payload;
      lastCacheTime = now;
    }

    return {
      statusCode: 200,
      headers,
      body: JSON.stringify(payload)
    };
  } catch (e) {
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({
        status: "ERROR",
        message: e.message,
        timestamp: new Date().toISOString()
      })
    };
  }
};
