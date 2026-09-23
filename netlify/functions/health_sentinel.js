// =============================================================================
// netlify/functions/health_sentinel.js — Continuous Event Intelligence Sentinel API
// =============================================================================
/**
 * Institutional HTTP API for NEXUS Continuous Event Sentinel.
 * Exposed at: /api/health/sentinel (GET) and /api/sentinel/tick (POST)
 * 
 * Architectural Responsibilities:
 * 1. HTTP Endpoint (not blocked by Netlify scheduled function 403 rule).
 * 2. GET: Queries Supabase for latest sentinel invocation telemetry, active thesis,
 *    and reports honest HEALTHY/DEGRADED status with config-derived next invocation.
 * 3. POST: On-demand Sentinel invocation trigger, recording full lineage in Supabase.
 */

const sentinel = require("./sentinel_tick");

exports.handler = async (event, context) => {
  return sentinel.handler(event, context);
};
