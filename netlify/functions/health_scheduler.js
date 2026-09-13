// =============================================================================
// netlify/functions/health_scheduler.js — Authoritative Health API Endpoint
// =============================================================================
/**
 * Institutional Health API for NEXUS Scheduler & Production Runtime.
 * Exposed at: /api/health/scheduler (via netlify.toml rewrite)
 * 
 * Architectural Responsibilities:
 * 1. Queries Supabase scheduler_invocations table using server-side service role key.
 *    (Direct public anonymous client access to scheduler_invocations is disallowed by RLS).
 * 2. Evaluates Missed-Run condition:
 *    - Expected: 18:30 IST (13:00 UTC) on trading days.
 *    - Tolerance boundary: 18:45 IST (13:15 UTC).
 *    - If >= 18:45 IST on a trading day without a valid execution, latches status to MISSED.
 * 3. Dynamically calculates next expected run based on the NSE trading calendar.
 *    (Never hardcodes 21:00 IST or static times).
 * 4. Exposes failure codes (WORKFLOW_DISPATCH_FAILED, CONFIGURATION_ERROR, etc.).
 * 
 * SECURITY INVARIANT:
 * No secrets are exposed or returned.
 */

const { createClient } = require("@supabase/supabase-js");

// NSE 2026 Official Holidays (YYYY-MM-DD)
const NSE_HOLIDAYS_2026 = new Set([
  "2026-01-26", "2026-03-03", "2026-03-25", "2026-04-03",
  "2026-04-14", "2026-05-01", "2026-05-27", "2026-08-15",
  "2026-10-02", "2026-10-20", "2026-11-08", "2026-11-10",
  "2026-11-24", "2026-12-25",
]);

function getISTDate(utcDate = new Date()) {
  const istOffsetMs = 5.5 * 60 * 60 * 1000;
  return new Date(utcDate.getTime() + istOffsetMs);
}

function isTradingDay(utcDate = new Date()) {
  const istDate = getISTDate(utcDate);
  const dayOfWeek = istDate.getUTCDay();
  if (dayOfWeek === 0 || dayOfWeek === 6) return false;
  const yyyy = istDate.getUTCFullYear();
  const mm = String(istDate.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(istDate.getUTCDate()).padStart(2, "0");
  return !NSE_HOLIDAYS_2026.has(`${yyyy}-${mm}-${dd}`);
}

function calculateNextExpectedRun(utcNow = new Date()) {
  const istNow = getISTDate(utcNow);
  const targetHour = 18;
  const targetMinute = 30;

  // Check today if current IST time < 18:30 and today is a trading day
  const isTodayTrading = isTradingDay(utcNow);
  const currentHour = istNow.getUTCHours();
  const currentMin = istNow.getUTCMinutes();

  if (isTodayTrading && (currentHour < targetHour || (currentHour === targetHour && currentMin < targetMinute))) {
    const yyyy = istNow.getUTCFullYear();
    const mm = String(istNow.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(istNow.getUTCDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} 18:30:00 IST`;
  }

  // Look up to 14 days ahead for next trading day
  const checkDate = new Date(utcNow);
  for (let i = 1; i <= 14; i++) {
    checkDate.setUTCDate(checkDate.getUTCDate() + 1);
    if (isTradingDay(checkDate)) {
      const checkIST = getISTDate(checkDate);
      const yyyy = checkIST.getUTCFullYear();
      const mm = String(checkIST.getUTCMonth() + 1).padStart(2, "0");
      const dd = String(checkIST.getUTCDate()).padStart(2, "0");
      return `${yyyy}-${mm}-${dd} 18:30:00 IST`;
    }
  }
  return "--";
}

function getSupabaseClient() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SERVICE_KEY;
  if (!url || !key || url.includes("htcgeupzkxxxplqtvxue")) {
    return null;
  }
  return createClient(url, key, {
    auth: { persistSession: false },
  });
}

exports.handler = async function(event, context) {
  const origin = event.headers.origin || "*";
  const headers = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Cache-Control": "no-cache, no-store, must-revalidate",
  };

  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 204, headers, body: "" };
  }

  const nowUtc = new Date();
  const istNow = getISTDate(nowUtc);
  const nextExpectedRun = calculateNextExpectedRun(nowUtc);

  const supabase = getSupabaseClient();
  if (!supabase) {
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({
        status: "CONFIGURATION_ERROR",
        authority: "UNCONFIGURED",
        environment: "PAPER",
        schedule: "0 13 * * 1-5",
        timezone: "UTC",
        local_schedule: "18:30 IST (Mon-Fri)",
        last_invocation: null,
        last_success: null,
        next_expected_run: nextExpectedRun,
        missed_runs: 0,
        consecutive_failures: 0,
        error_code: "CONFIGURATION_ERROR",
        error_message: "Supabase cloud credentials not configured or placeholder detected.",
      }),
    };
  }

  try {
    // Query latest invocation from Supabase
    const { data: invocations, error: dbErr } = await supabase
      .from("scheduler_invocations")
      .select("*")
      .order("started_at", { ascending: false })
      .limit(1);

    if (dbErr) {
      console.error("[HEALTH_SCHEDULER] Supabase query error:", dbErr.message);
      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({
          status: "FAILED",
          authority: "SUPABASE",
          environment: "PAPER",
          schedule: "0 13 * * 1-5",
          timezone: "UTC",
          local_schedule: "18:30 IST (Mon-Fri)",
          last_invocation: null,
          last_success: null,
          next_expected_run: nextExpectedRun,
          error_code: "SUPABASE_QUERY_FAILED",
          error_message: dbErr.message,
        }),
      };
    }

    const latest = (invocations && invocations.length > 0) ? invocations[0] : null;

    // If no record ever exists in Supabase: UNVERIFIED
    if (!latest) {
      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({
          status: "UNVERIFIED",
          authority: "SUPABASE",
          environment: "PAPER",
          schedule: "0 13 * * 1-5",
          timezone: "UTC",
          local_schedule: "18:30 IST (Mon-Fri)",
          last_invocation: null,
          last_success: null,
          next_expected_run: nextExpectedRun,
          missed_runs: 0,
          consecutive_failures: 0,
        }),
      };
    }

    // Missed-Run Detection:
    // Today is trading day, IST >= 18:45, and no invocation ran today
    const isTodayTrading = isTradingDay(nowUtc);
    const istHours = istNow.getUTCHours();
    const istMinutes = istNow.getUTCMinutes();
    const isPastTolerance = (istHours > 18) || (istHours === 18 && istMinutes >= 45);

    let ranToday = false;
    if (latest.started_at) {
      const lastStartedIST = getISTDate(new Date(latest.started_at));
      ranToday = (
        lastStartedIST.getUTCFullYear() === istNow.getUTCFullYear() &&
        lastStartedIST.getUTCMonth() === istNow.getUTCMonth() &&
        lastStartedIST.getUTCDate() === istNow.getUTCDate()
      );
    }

    if (isTodayTrading && isPastTolerance && !ranToday) {
      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({
          status: "MISSED",
          authority: "SUPABASE",
          environment: latest.environment || "PAPER",
          schedule: "0 13 * * 1-5",
          timezone: "UTC",
          local_schedule: "18:30 IST (Mon-Fri)",
          last_invocation: latest,
          last_success: latest.status === "SUCCESS" ? latest.completed_at : null,
          next_expected_run: nextExpectedRun,
          missed_runs: 1,
          consecutive_failures: latest.status === "FAILED" ? 1 : 0,
          workflow_run_id: latest.workflow_run_id,
          git_commit: latest.git_commit,
          error_code: "SCHEDULER_MISSED",
          error_message: `Expected 18:30 IST execution did not occur before 18:45 IST tolerance boundary.`,
        }),
      };
    }

    // Status mapping based on latest record
    let resolvedStatus = latest.status;
    if (latest.status === "SUCCESS") {
      resolvedStatus = "HEALTHY";
    } else if (latest.status === "DISPATCHED" || latest.status === "RUNNING") {
      const ageMinutes = (nowUtc - new Date(latest.started_at)) / 60000;
      if (ageMinutes > 45) {
        resolvedStatus = "FAILED";
      } else {
        resolvedStatus = "RUNNING";
      }
    }

    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({
        status: resolvedStatus,
        authority: "SUPABASE",
        environment: latest.environment || "PAPER",
        schedule: "0 13 * * 1-5",
        timezone: "UTC",
        local_schedule: "18:30 IST (Mon-Fri)",
        last_invocation: latest,
        last_success: (latest.status === "SUCCESS" || latest.status === "PARTIAL") ? latest.completed_at : null,
        next_expected_run: nextExpectedRun,
        missed_runs: 0,
        consecutive_failures: resolvedStatus === "FAILED" ? 1 : 0,
        workflow_run_id: latest.workflow_run_id,
        git_commit: latest.git_commit,
        config_hash: latest.config_hash,
        error_code: latest.error_code || null,
        error_message: latest.error_message || null,
      }),
    };
  } catch (err) {
    console.error("[HEALTH_SCHEDULER] Uncaught error:", err);
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({
        status: "FAILED",
        authority: "SUPABASE",
        environment: "PAPER",
        last_invocation: null,
        next_expected_run: nextExpectedRun,
        error_code: "HEALTH_CHECK_EXCEPTION",
        error_message: err.message,
      }),
    };
  }
};
