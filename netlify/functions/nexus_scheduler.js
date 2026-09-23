// =============================================================================
// netlify/functions/nexus_scheduler.js — Canonical Production Scheduler Trigger
// =============================================================================
/**
 * Netlify Scheduled Function (Cron Trigger).
 * 
 * Schedule: "0 13 * * 1-5"
 *   13:00 UTC
 *   18:30 IST (UTC + 5:30)
 *   Monday through Friday
 * 
 * Architectural Responsibilities:
 * 1. Receive Netlify cron invocation.
 * 2. Evaluate NSE trading calendar (Trading Day vs Non-Trading Day).
 * 3. Generate deterministic invocation_id (scheduled_for + schedule_name + environment).
 * 4. Record authoritative heartbeat to Supabase scheduler_invocations table (DISPATCHED).
 * 5. Enforce strict idempotency: identical scheduled execution will never dispatch twice.
 * 6. Dispatch GitHub Actions cloud runner (daily_trade_report.yml) via workflow_dispatch.
 * 7. Return concise JSON distinguishing Netlify invocation success from downstream status.
 * 
 * SECURITY INVARIANT:
 * Uses server-side service role credentials. No secrets returned or logged.
 */

// Node.js 20 compatibility shim for Supabase Realtime WebSocket check
if (typeof WebSocket === "undefined") {
  global.WebSocket = class DummyWebSocket {};
}

const { schedule } = require("@netlify/functions");
const { createClient } = require("@supabase/supabase-js");
const crypto = require("crypto");

// NSE 2026 Official Holidays (YYYY-MM-DD)
const NSE_HOLIDAYS_2026 = new Set([
  "2026-01-26", // Republic Day
  "2026-03-03", // Holi
  "2026-03-25", // Holi / Dhulandi
  "2026-04-03", // Good Friday
  "2026-04-14", // Dr. Ambedkar Jayanti
  "2026-05-01", // Maharashtra Day
  "2026-05-27", // Bakri Id / Eid-ul-Adha
  "2026-08-15", // Independence Day
  "2026-10-02", // Mahatma Gandhi Jayanti
  "2026-10-20", // Dussehra
  "2026-11-08", // Diwali Laxmi Pujan
  "2026-11-10", // Diwali Balipratipada
  "2026-11-24", // Gurunanak Jayanti
  "2026-12-25", // Christmas
]);

function getISTDate(utcDate = new Date()) {
  const istOffsetMs = 5.5 * 60 * 60 * 1000;
  return new Date(utcDate.getTime() + istOffsetMs);
}

function isTradingDay(utcDate = new Date()) {
  const istDate = getISTDate(utcDate);
  const dayOfWeek = istDate.getUTCDay(); // 0 = Sun, 6 = Sat in offset Date
  if (dayOfWeek === 0 || dayOfWeek === 6) {
    return false;
  }
  const yyyy = istDate.getUTCFullYear();
  const mm = String(istDate.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(istDate.getUTCDate()).padStart(2, "0");
  const dateStr = `${yyyy}-${mm}-${dd}`;
  return !NSE_HOLIDAYS_2026.has(dateStr);
}

function generateDeterministicInvocationId(scheduledForUtc, scheduleName = "NEXUS_DAILY", environment = "PAPER") {
  const dateStr = scheduledForUtc.toISOString().slice(0, 10);
  const timeStr = scheduledForUtc.toISOString().slice(11, 16).replace(":", "");
  const raw = `${scheduledForUtc.toISOString()}:${scheduleName}:${environment}`;
  const hash = crypto.createHash("sha256").update(raw).digest("hex").slice(0, 8);
  return `INV-${dateStr}-${timeStr}UTC-${environment}-${hash}`;
}

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

async function dispatchGitHubWorkflow({ owner, repo, token, workflowFileName, ref = "main", inputs = {} }) {
  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowFileName}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Accept": "application/vnd.github.v3+json",
      "User-Agent": "NEXUS-Netlify-Scheduler/4.0",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ref,
      inputs,
    }),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`GitHub dispatch failed with HTTP ${res.status}: ${errText.slice(0, 200)}`);
  }
  return true;
}

const schedulerHandler = async function(event, context) {
  const startedAt = new Date();
  const istDate = getISTDate(startedAt);
  const scheduledFor = new Date(startedAt);
  // Canonical slot: 13:00 UTC
  scheduledFor.setUTCMinutes(0, 0, 0);

  const yyyy = istDate.getUTCFullYear();
  const mm = String(istDate.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(istDate.getUTCDate()).padStart(2, "0");
  const tradeDateStr = `${yyyy}-${mm}-${dd}`;

  const environment = "PAPER";
  const invocationId = generateDeterministicInvocationId(scheduledFor, "NEXUS_DAILY", environment);

  console.log(`[NEXUS_SCHEDULER] Invocation ${invocationId} triggered at ${startedAt.toISOString()} (${istDate.toISOString()} IST)`);

  const supabase = getSupabaseClient();
  const ghToken = process.env.GH_DISPATCH_TOKEN || process.env.GITHUB_TOKEN;
  const ghRepoFull = process.env.GITHUB_REPOSITORY || "samudralasrikanth/algo-trader";
  const [owner, repo] = ghRepoFull.split("/");

  // 1. Trading Day Evaluation
  if (!isTradingDay(startedAt)) {
    console.log(`[NEXUS_SCHEDULER] Date ${tradeDateStr} is a Non-Trading Day (Weekend/Holiday). Recording SKIPPED.`);
    if (supabase) {
      await supabase.from("scheduler_invocations").upsert({
        invocation_id: invocationId,
        scheduled_for: scheduledFor.toISOString(),
        started_at: startedAt.toISOString(),
        completed_at: new Date().toISOString(),
        status: "SKIPPED_NON_TRADING_DAY",
        trigger_source: "NETLIFY_CRON",
        environment,
        error_code: null,
        error_message: `Skipped non-trading day (${tradeDateStr})`,
      }, { onConflict: "invocation_id" });
    }
    return {
      statusCode: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: "SKIPPED_NON_TRADING_DAY",
        invocation_id: invocationId,
        trade_date: tradeDateStr,
        environment,
        message: "Market closed for weekend or official NSE holiday.",
      }),
    };
  }

  // 2. Idempotency Check in Supabase
  if (supabase) {
    const { data: existing, error: selectErr } = await supabase
      .from("scheduler_invocations")
      .select("status, workflow_run_id")
      .eq("invocation_id", invocationId)
      .maybeSingle();

    if (existing && ["DISPATCHED", "RUNNING", "SUCCESS", "PARTIAL"].includes(existing.status)) {
      console.log(`[NEXUS_SCHEDULER] Invocation ${invocationId} already registered with status ${existing.status}.`);
      return {
        statusCode: 200,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status: "ALREADY_REGISTERED",
          invocation_id: invocationId,
          scheduled_for: scheduledFor.toISOString(),
          environment,
          downstream_status: existing.status,
          message: "Skipping duplicate execution; invocation already in progress or completed.",
        }),
      };
    }
  }

  // 3. Record Initial Heartbeat (DISPATCHED)
  if (supabase) {
    const { error: insertErr } = await supabase
      .from("scheduler_invocations")
      .upsert({
        invocation_id: invocationId,
        scheduled_for: scheduledFor.toISOString(),
        started_at: startedAt.toISOString(),
        status: "DISPATCHED",
        trigger_source: "NETLIFY_CRON",
        environment,
        git_commit: process.env.COMMIT_REF || null,
        config_hash: "p0_prod_runtime_v40",
      }, { onConflict: "invocation_id" });

    if (insertErr) {
      console.error(`[NEXUS_SCHEDULER] Failed persisting heartbeat to Supabase: ${insertErr.message}`);
    }
  }

  // 4. Trigger GitHub Actions Cloud Runner
  if (!ghToken) {
    const errCode = "CONFIGURATION_ERROR";
    const errMsg = "GH_DISPATCH_TOKEN is not configured in Netlify environment variables.";
    console.error(`[NEXUS_SCHEDULER] ${errCode}: ${errMsg}`);

    if (supabase) {
      await supabase.from("scheduler_invocations").update({
        status: "FAILED",
        completed_at: new Date().toISOString(),
        error_code: errCode,
        error_message: errMsg,
      }).eq("invocation_id", invocationId);
    }

    return {
      statusCode: 500,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: "FAILED",
        failure_code: errCode,
        failure_message: errMsg,
        invocation_id: invocationId,
      }),
    };
  }

  try {
    await dispatchGitHubWorkflow({
      owner,
      repo,
      token: ghToken,
      workflowFileName: "daily_trade_report.yml",
      ref: "main",
      inputs: {
        scheduled_date: tradeDateStr,
        invocation_id: invocationId,
        environment,
        trigger_source: "NETLIFY_CRON",
      },
    });

    console.log(`[NEXUS_SCHEDULER] Successfully dispatched daily_trade_report.yml on ${owner}/${repo}`);

    return {
      statusCode: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: "DISPATCHED",
        invocation_id: invocationId,
        scheduled_for: scheduledFor.toISOString(),
        workflow: "daily_trade_report.yml",
        environment,
        downstream_status: "PENDING",
      }),
    };
  } catch (dispatchErr) {
    const errCode = "WORKFLOW_DISPATCH_FAILED";
    const errMsg = dispatchErr.message;
    console.error(`[NEXUS_SCHEDULER] ${errCode}: ${errMsg}`);

    if (supabase) {
      await supabase.from("scheduler_invocations").update({
        status: "FAILED",
        completed_at: new Date().toISOString(),
        error_code: errCode,
        error_message: errMsg,
      }).eq("invocation_id", invocationId);
    }

    return {
      statusCode: 502,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: "FAILED",
        failure_code: errCode,
        failure_message: errMsg,
        invocation_id: invocationId,
      }),
    };
  }
};

// Registered with Netlify Scheduled Functions:
// "0 13 * * 1-5" = 13:00 UTC / 18:30 IST, Monday-Friday
exports.handler = schedule("0 13 * * 1-5", schedulerHandler);
exports._internalHandler = schedulerHandler; // Export raw handler for direct unit testing
