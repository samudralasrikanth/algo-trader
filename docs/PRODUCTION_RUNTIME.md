# NEXUS Production Runtime Architecture (V4.0 P0 Fix)

## 1. Overview & Cloud Orchestration Architecture

The production execution of NEXUS operates entirely within serverless cloud runners, completely decoupled from local developer terminals or laptops:

```text
NETLIFY SCHEDULED FUNCTION (nexus_scheduler.js)
        │
        │ 13:00 UTC / 18:30 IST (Mon-Fri)
        ▼
SUPABASE AUTHORITATIVE HEARTBEAT (scheduler_invocations)
        │
        ▼
GITHUB ACTIONS CLOUD RUNNER (daily_trade_report.yml)
        │
        ▼
PYTHON NEXUS ORCHESTRATOR (event_agent.jobs.daily_report)
        │
        ├── Market / Data Collection & Upstox Sandbox Reconciliation
        ├── OpenRouter AI Financial Analyst
        ├── ElevenLabs Voice Narration
        ├── Creatomate 9-Scene Video Render
        ├── YouTube Publication (Private Mode)
        ├── Email Dispatch (Executive Report)
        └── Deterministic SHA-256 Provenance
        │
        ▼
SUPABASE AUTHORITATIVE LEDGER
        │
        ├── scheduler_invocations
        ├── job_runs
        ├── daily_trade_reports
        └── provenance
        │
        ▼
SERVERLESS HEALTH APIs
        │
        ├── /api/health/scheduler
        └── /api/daily_report
        │
        ▼
LIVE DASHBOARD (web_app)
```

---

## 2. Canonical Trigger & Timezone Conversion

* **Schedule (Cron)**: `0 13 * * 1-5`
* **UTC Schedule**: 13:00 UTC
* **IST Schedule**: 18:30 IST (UTC + 5:30)
* **Cadence**: Monday through Friday (NSE Trading Days)
* **Holiday Evaluation**: Evaluated against the official NSE 2026 trading holiday calendar. If a scheduled trigger fires on a holiday or weekend, the function records `SKIPPED_NON_TRADING_DAY` in Supabase and terminates without starting downstream pipelines.

---

## 3. Strict Execution Decoupling & Invariants

1. **Lightweight Netlify Trigger**: Netlify functions operate with a 10–26s execution ceiling. The Netlify Scheduled Function (`nexus_scheduler.js`) does NOT run heavy jobs (video/AI/P&L). It acts strictly as an authoritative heartbeat recorder and GitHub Actions `workflow_dispatch` trigger.
2. **GitHub Actions Heavy Runner**: All heavy tasks (Upstox reconciliation, AI analysis, ElevenLabs voice, Creatomate video render, YouTube upload) run on GitHub Actions Ubuntu runners.
3. **Strict PAPER Environment**: The runtime asserts:
   ```python
   assert environment == "PAPER"
   ```
   No real-money trading is enabled. Live trading attempts are rejected with `EXECUTION_BLOCKED`.
4. **V4.0 Prospective Certification Boundary**: The six-month prospective certification clock remains strictly **`HALTED / UNANCHORED`** until six full months of continuous prospective production evidence are recorded.
5. **Prediction Engine Freeze**: `event_agent/engine/prediction_algo.py` and strategy parameters remain 100% frozen.

---

## 4. Authoritative Ledger & Schema

* **Supabase Table**: `public.scheduler_invocations`
* **Access Control**: Row Level Security (RLS) is enabled. Direct anonymous public read access is disabled. The ledger is accessible exclusively via server-side service role credentials.
* **Controlled Public Projection**: `/api/health/scheduler` projects the sanitized, controlled public view.

---

## 5. Emergency Manual Execution Runbook

If manual recovery or an off-cycle run is required:
1. Navigate to GitHub Actions:
   `https://github.com/samudralasrikanth/algo-trader/actions/workflows/daily_trade_report.yml`
2. Click **Run workflow**:
   - `scheduled_date`: (leave blank for today, or specify `YYYY-MM-DD`)
   - `environment`: `PAPER`
   - `trigger_source`: `MANUAL`
3. Click **Run workflow**.
4. The manual run is explicitly recorded in Supabase with `trigger_source = MANUAL` and will never masquerade as an automated scheduled run.
