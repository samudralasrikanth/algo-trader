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
const CACHE_TTL_MS = 10000; // 10 seconds

const SYMBOLS = {
  'NIFTY 50': '^NSEI',
  'BANK NIFTY': '^NSEBANK',
  'INDIA VIX': '^INDIAVIX',
  'USD/INR': 'USDINR=X',
  'BRENT': 'BZ=F',
  'GOLD': 'GC=F'
};

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
      price,
      previous_close: prev,
      change: chg,
      change_pct: chg_pct,
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
    "Cache-Control": "public, max-age=10, stale-while-revalidate=30",
  };

  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 204, headers, body: "" };
  }

  const now = Date.now();
  if (cachedData && (now - lastCacheTime < CACHE_TTL_MS)) {
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify(cachedData)
    };
  }

  try {
    const entries = Object.entries(SYMBOLS);
    const results = await Promise.all(
      entries.map(async ([name, sym]) => {
        const q = await fetchQuote(sym);
        return [name, q];
      })
    );

    const quotes = {};
    for (const [name, q] of results) {
      if (q) quotes[name] = q;
    }

    // Add Domestic INR Gold Calculation
    if (quotes['GOLD']) {
      const usdRate = quotes['USD/INR']?.price || 95.15;
      const goldUsd = quotes['GOLD'].price;
      const inrPer10g = Math.round((goldUsd * usdRate / 31.1035) * 10);
      quotes['GOLD'].price_inr_10g = inrPer10g;
    }

    cachedData = {
      status: "LIVE",
      source: "Yahoo Finance Live Feed",
      timestamp: new Date().toISOString(),
      quotes
    };
    lastCacheTime = now;

    return {
      statusCode: 200,
      headers,
      body: JSON.stringify(cachedData)
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
