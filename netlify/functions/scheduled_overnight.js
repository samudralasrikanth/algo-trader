// =============================================================================
// netlify/functions/scheduled_overnight.js — Netlify Scheduled Cron Trigger
// =============================================================================
/**
 * Netlify Scheduled Function (Cron Trigger).
 * Runs every 3 hours during the overnight collection window:
 * 18:00, 21:00, 00:00, 03:00, 06:00 IST <=> 12:30, 15:30, 18:30, 21:30, 00:30 UTC
 * 
 * Cron: "30 0,12,15,18,21 * * *"
 * 
 * Acts as a serverless orchestrator trigger without exceeding serverless execution limits.
 */

exports.handler = async function(event, context) {
  const timestamp = new Date().toISOString();
  console.log(`[${timestamp}] NEXUS Overnight Collection Trigger Activated.`);

  // Return orchestrator telemetry response
  return {
    statusCode: 200,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
    body: JSON.stringify({
      status: "TRIGGER_ACTIVE",
      job_name: "OVERNIGHT_DATA_ACQUISITION",
      triggered_at_utc: timestamp,
      cron_schedule_utc: "30 0,12,15,18,21 * * *",
      window_ist: "18:00 to 06:00 IST (every 3 hours)",
      orchestrator: "Netlify Scheduled Functions",
      execution_mode: "ASYNC_TRIGGER",
    }),
  };
};
