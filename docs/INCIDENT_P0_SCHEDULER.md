# Incident Report: P0 Scheduler & Production Runtime Failure

## 1. Incident Diagnosis

* **Severity**: P0 (Production Automation Failure & UI False Positive)
* **Date of Occurrence**: September 10, 2026 – September 13, 2026
* **Root Causes Identified**:
  1. **Local Terminal Dependency**: Scheduled execution depended on a local Python loop in `auto_scheduler.py` running on a developer machine. When the terminal was closed, execution ceased.
  2. **Netlify Functions Misconfiguration**: Netlify had no registered scheduled functions. `scheduled_overnight.js` and `daily_report.js` were plain HTTP functions without cron registrations.
  3. **Synthetic Dashboard Claims**: The web app hardcoded `🟢 HEALTHY`, `18:00:04 IST`, and `NEXT RUN 21:00 IST` into HTML and JS fallbacks.
  4. **Unreachable Supabase Endpoint**: `SUPABASE_URL` defaulted to `https://htcgeupzkxxxplqtvxue.supabase.co` which failed DNS resolution, stranding state locally.
  5. **Frozen Dataset**: `web_app/data.json` remained frozen at `2026-09-10T08:13:45Z`.

---

## 2. Permanent Architectural Remediation

1. **Native Netlify Scheduled Function**: Registered `nexus_scheduler.js` with cron `0 13 * * 1-5` (18:30 IST / 13:00 UTC).
2. **GitHub Actions Cloud Runner**: Created `.github/workflows/daily_trade_report.yml` triggered via `workflow_dispatch` from the scheduled function.
3. **Authoritative Supabase Heartbeat**: Added `scheduler_invocations` table and sanitized credentials loading (rejecting all placeholder URLs).
4. **UI Truth Restoration**: Removed all static `HEALTHY` and synthetic timestamps. Default state is `🔴 SCHEDULER UNVERIFIED / STALE` until confirmed by live `/api/health/scheduler` API.
5. **Server-Side Missed-Run Latch**: At 18:45 IST on trading days, latches `SCHEDULER_MISSED` if no invocation occurred.
6. **Strict Paper Safety**: Verified `assert environment == "PAPER"`.
7. **Certification Boundary Preserved**: Six-month prospective certification clock remains strictly `HALTED / UNANCHORED`.
