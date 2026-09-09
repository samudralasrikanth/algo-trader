// =============================================================================
// netlify/functions/health_ai.js — Server-Side OpenRouter Connectivity Diagnostic
// =============================================================================
/**
 * Institutional Server-Side AI Health & Connectivity Proxy.
 * 
 * SECURITY INVARIANT:
 * OPENROUTER_API_KEY is accessed EXCLUSIVELY within this serverless environment
 * via process.env.OPENROUTER_API_KEY.
 * The API key is NEVER exposed, returned, or leaked to client bundles, HTTP responses,
 * DOM trees, or web storage.
 * 
 * Routes:
 * GET  /api/health/ai              -> Safe operational status summary (no secrets)
 * POST /api/health/ai?action=test  -> Live diagnostic ping to OpenRouter with latency/token telemetry
 */

const https = require("https");

// In-memory process execution cache for operational health summary
let lastDiagnosticResult = null;

function performOpenRouterPing(apiKey, model) {
  return new Promise((resolve) => {
    const startTime = Date.now();
    const payload = JSON.stringify({
      model: model || "openai/gpt-4o-mini",
      messages: [{ role: "user", content: "PING" }],
      max_tokens: 5,
    });

    const options = {
      hostname: "openrouter.ai",
      port: 443,
      path: "/api/v1/chat/completions",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${apiKey}`,
        "HTTP-Referer": "https://nifty50-event-agent.netlify.app",
        "X-Title": "NEXUS Nifty 50 Event Agent",
        "Content-Length": Buffer.byteLength(payload),
      },
      timeout: 8000,
    };

    const req = https.request(options, (res) => {
      let body = "";
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => {
        const latencyMs = Date.now() - startTime;
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            const data = JSON.parse(body);
            const usage = data.usage || {};
            resolve({
              status: "SUCCESS",
              provider: "openrouter",
              model: model || "openai/gpt-4o-mini",
              request_id: data.id || null,
              latency_ms: latencyMs,
              input_tokens: usage.prompt_tokens || 0,
              output_tokens: usage.completion_tokens || 0,
              total_tokens: usage.total_tokens || 0,
              timestamp: new Date().toISOString(),
            });
          } catch (err) {
            resolve({
              status: "FAILED",
              provider: "openrouter",
              model: model || "openai/gpt-4o-mini",
              request_id: null,
              latency_ms: latencyMs,
              input_tokens: 0,
              output_tokens: 0,
              total_tokens: 0,
              error_reason: `JSON parse error: ${err.message}`,
              timestamp: new Date().toISOString(),
            });
          }
        } else {
          let errMsg = `HTTP ${res.statusCode}`;
          try {
            const errData = JSON.parse(body);
            if (errData.error && errData.error.message) {
              errMsg += `: ${errData.error.message}`;
            }
          } catch (_) {
            errMsg += `: ${body.slice(0, 100)}`;
          }
          resolve({
            status: "FAILED",
            provider: "openrouter",
            model: model || "openai/gpt-4o-mini",
            request_id: null,
            latency_ms: latencyMs,
            input_tokens: 0,
            output_tokens: 0,
            total_tokens: 0,
            error_reason: errMsg,
            timestamp: new Date().toISOString(),
          });
        }
      });
    });

    req.on("error", (err) => {
      const latencyMs = Date.now() - startTime;
      resolve({
        status: "FAILED",
        provider: "openrouter",
        model: model || "openai/gpt-4o-mini",
        request_id: null,
        latency_ms: latencyMs,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        error_reason: err.message,
        timestamp: new Date().toISOString(),
      });
    });

    req.on("timeout", () => {
      req.destroy();
      resolve({
        status: "FAILED",
        provider: "openrouter",
        model: model || "openai/gpt-4o-mini",
        request_id: null,
        latency_ms: 8000,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        error_reason: "Connection timed out (8000ms)",
        timestamp: new Date().toISOString(),
      });
    });

    req.write(payload);
    req.end();
  });
}

exports.handler = async function (event, context) {
  const method = (event.httpMethod || "GET").toUpperCase();
  const apiKey = process.env.OPENROUTER_API_KEY || process.env.OPENAI_API_KEY;
  const model = process.env.OPENROUTER_MODEL || "openai/gpt-4o-mini";

  const corsHeaders = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
  };

  if (method === "OPTIONS") {
    return { statusCode: 204, headers: corsHeaders, body: "" };
  }

  // GET: Safe operational summary (zero secret exposure)
  if (method === "GET") {
    const isConfigured = Boolean(apiKey && apiKey.length > 5);
    const summary = {
      provider: "openrouter",
      configured: isConfigured,
      status: !isConfigured ? "NOT_CONFIGURED" : (lastDiagnosticResult?.status === "SUCCESS" ? "HEALTHY" : (lastDiagnosticResult ? "DEGRADED" : "UNTESTED")),
      model: model,
      last_success: lastDiagnosticResult?.status === "SUCCESS" ? lastDiagnosticResult.timestamp : null,
      last_failure: lastDiagnosticResult?.status === "FAILED" ? lastDiagnosticResult.timestamp : null,
    };
    return {
      statusCode: 200,
      headers: corsHeaders,
      body: JSON.stringify(summary, null, 2),
    };
  }

  // POST: Live diagnostic test execution
  if (method === "POST") {
    if (!apiKey) {
      const unconfigured = {
        status: "NOT_CONFIGURED",
        provider: "openrouter",
        model: model,
        request_id: null,
        latency_ms: 0,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        error_reason: "OPENROUTER_API_KEY is not configured in server environment",
        timestamp: new Date().toISOString(),
      };
      lastDiagnosticResult = unconfigured;
      return {
        statusCode: 200,
        headers: corsHeaders,
        body: JSON.stringify(unconfigured, null, 2),
      };
    }

    const diag = await performOpenRouterPing(apiKey, model);
    lastDiagnosticResult = diag;

    return {
      statusCode: 200,
      headers: corsHeaders,
      body: JSON.stringify(diag, null, 2),
    };
  }

  return {
    statusCode: 405,
    headers: corsHeaders,
    body: JSON.stringify({ error: `Method ${method} Not Allowed` }),
  };
};
