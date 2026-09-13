# NEXUS Scheduler Architecture & State Machine

## 1. Truth States

The scheduler operates under 10 explicit operational truth states:

| State | Definition | UI Presentation |
|---|---|---|
| `UNVERIFIED` | No authoritative heartbeat exists in Supabase | 🔴 SCHEDULER UNVERIFIED / STALE |
| `HEALTHY` | Latest scheduled invocation completed within tolerance | 🟢 SCHEDULER HEALTHY |
| `RUNNING` | Invocation is actively running downstream | 🔵 SCHEDULER RUNNING |
| `SUCCESS` | Latest scheduled run succeeded completely | 🟢 SCHEDULER SUCCESS |
| `PARTIAL` | Optional child stages failed (e.g. email/YouTube), core data succeeded | 🟡 SCHEDULER PARTIAL |
| `FAILED` | Mandatory stages or dispatch failed | 🔴 SCHEDULER FAILED |
| `MISSED` | Expected cron window passed without valid invocation | 🔴 SCHEDULER MISSED (LATCHED) |
| `STALE` | Heartbeat exceeds freshness tolerance (>36h on trading days) | 🔴 SCHEDULER STALE |
| `DISABLED` | Scheduler explicitly deactivated | ⚪ SCHEDULER DISABLED |
| `CONFIGURATION_ERROR` | Missing or placeholder credentials | 🔴 CONFIGURATION ERROR |

---

## 2. Missed-Run Detector & Red-Latch Rule

* **Expected Execution**: 18:30 IST (13:00 UTC) on trading days.
* **Tolerance Boundary**: 18:45 IST (13:15 UTC).
* **Latch Mechanism**:
  If current IST time $\ge$ 18:45 on an active trading day, and no valid invocation began today:
  $$\text{Status} \longrightarrow \text{SCHEDULER\_MISSED}$$
* **Recovery Rule**:
  The red latch cannot be cleared simply because the next scheduled slot is in the future. Recovery strictly requires:
  $$\text{Valid Heartbeat} + \text{Valid Invocation Identity} + \text{Authoritative Ledger Evidence}$$

---

## 3. Strict Idempotency Design

### Canonical Invocations
```text
invocation_id = SHA-256(scheduled_for + schedule_name + environment)
```
Example: `INV-2026-09-14-1300UTC-PAPER-8b1e42f9`
Repeated delivery of the same scheduled cron window results in `ALREADY_REGISTERED` and is safely discarded without duplicate dispatch.

### Stage-Level Idempotency
* **Video Generation**: Keyed by `report_date + script_hash + template_version`. If a video was already rendered for that date, existing video URL is reused.
* **YouTube Publication**: Keyed by `report_date + video_hash`. If a video ID already exists for the date, upload is skipped.
* **Email Delivery**: Keyed by `report_date + report_hash`. Prevents duplicate daily executive broadcasts.
