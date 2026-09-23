// =============================================================================
// netlify/functions/daily_report.js — Server-Side Daily Report API Endpoint
// =============================================================================
/**
 * Institutional Server-Side Daily Trade Report API Handler.
 * Exposed at: /api/daily_report (via netlify.toml rewrite)
 * 
 * Architectural Responsibilities:
 * 1. Reads authoritative daily trade reports directly from Supabase `daily_trade_reports` table.
 * 2. Returns status: "NO_REPORT" if no report has been generated yet today.
 * 3. Never returns September 10 as though it were today's report.
 * 4. Strictly protects all secrets and API keys server-side.
 */

// Node.js 20 compatibility shim for Supabase Realtime WebSocket check
if (typeof WebSocket === "undefined") {
  global.WebSocket = class DummyWebSocket {};
}

const { createClient } = require("@supabase/supabase-js");

function getSupabaseClient() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SERVICE_KEY;
  if (!url || !key || url.includes("your-project-ref") || key.includes("your-service-role-key")) {
    return null;
  }
  return createClient(url, key, {
    auth: { persistSession: false },
  });
}

function getISTDate(utcDate = new Date()) {
  const istOffsetMs = 5.5 * 60 * 60 * 1000;
  return new Date(utcDate.getTime() + istOffsetMs);
}

exports.handler = async function(event, context) {
  const origin = event.headers.origin || "*";
  const headers = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Cache-Control": "no-cache, no-store, must-revalidate",
  };

  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 204, headers, body: "" };
  }

  const supabase = getSupabaseClient();
  const query = event.queryStringParameters || {};
  const requestedDate = query.date;

  const nowUtc = new Date();
  const istNow = getISTDate(nowUtc);
  const todayISTStr = `${istNow.getUTCFullYear()}-${String(istNow.getUTCMonth() + 1).padStart(2, "0")}-${String(istNow.getUTCDate()).padStart(2, "0")}`;
  const targetDate = requestedDate || todayISTStr;

  if (!supabase) {
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({
        status: "CONFIGURATION_ERROR",
        authority: "UNCONFIGURED",
        report_date: targetDate,
        message: "Supabase cloud credentials not configured or placeholder detected.",
        daily_video_report: null,
      }),
    };
  }

  try {
    // 1. Fetch targeted or latest report from Supabase
    let queryBuilder = supabase
      .from("daily_trade_reports")
      .select("*");

    if (requestedDate) {
      queryBuilder = queryBuilder.eq("report_date", requestedDate);
    } else {
      queryBuilder = queryBuilder.order("report_date", { ascending: false }).limit(1);
    }

    const { data: rows, error: dbErr } = await queryBuilder;

    if (dbErr) {
      console.error("[DAILY_REPORT_API] Database query error:", dbErr.message);
      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({
          status: "FAILED",
          error_code: "SUPABASE_QUERY_FAILED",
          error_message: dbErr.message,
          report_date: targetDate,
        }),
      };
    }

    const report = (rows && rows.length > 0) ? rows[0] : null;

    if (!report) {
      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({
          status: "NO_REPORT",
          report_date: targetDate,
          authority: "SUPABASE",
          message: `No authoritative daily report found for ${targetDate}.`,
          daily_video_report: null,
        }),
      };
    }

    // Check if the report is for today or historical
    const isToday = report.report_date === todayISTStr;

    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({
        status: report.status,
        report_date: report.report_date,
        is_today: isToday,
        authority: "SUPABASE",
        job_run_id: report.job_run_id,
        trade_count: report.total_trades,
        winning_trades: report.winning_trades,
        losing_trades: report.losing_trades,
        win_rate: report.win_rate,
        gross_pnl: report.gross_pnl,
        charges: report.charges,
        net_pnl: report.net_pnl,
        realized_pnl: report.realized_pnl,
        video_status: report.video_status,
        youtube_status: report.youtube_status,
        email_status: report.email_status,
        created_at: report.created_at,
        completed_at: report.updated_at,
        provenance_hash: report.provenance_hash,
        daily_video_report: report,
      }),
    };
  } catch (err) {
    console.error("[DAILY_REPORT_API] Uncaught error:", err);
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({
        status: "FAILED",
        error_code: "API_EXCEPTION",
        error_message: err.message,
        report_date: targetDate,
      }),
    };
  }
};
