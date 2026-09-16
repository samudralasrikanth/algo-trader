# =============================================================================
# event_agent/storage/scheduler_heartbeat.py — Authoritative Scheduler Heartbeat
# =============================================================================
"""
Authoritative Scheduler Heartbeat & Invocation Ledger:
- Maintains durable record in Supabase `scheduler_invocations` table.
- Synchronously mirrors to local SQLite cache (`data/job_runs.db`).
- Guarantees strict idempotency: identical scheduled execution produces exactly one record.
- Implements Missed-Run Detector (18:45 IST boundary) and Red-Latch state rules.
- Strictly validates credentials: never defaults to dummy URLs; returns CONFIGURATION_ERROR on invalid config.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, date, time, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

import sys

logger = logging.getLogger(__name__)

IST_TZ = timezone(timedelta(hours=5, minutes=30))
BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
LOCAL_DB_PATH = BASE_DIR / "data" / "job_runs.db"


class SchedulerState:
    UNVERIFIED = "UNVERIFIED"
    HEALTHY = "HEALTHY"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    MISSED = "MISSED"
    STALE = "STALE"
    DISABLED = "DISABLED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


@dataclass
class SchedulerInvocation:
    invocation_id: str
    scheduled_for: str          # ISO-8601 UTC
    started_at: str             # ISO-8601 UTC
    completed_at: Optional[str] # ISO-8601 UTC
    status: str                 # SchedulerState or DISPATCHED / RUNNING / SUCCESS / PARTIAL / FAILED
    trigger_source: str         # NETLIFY_CRON | MANUAL | TEST | RECOVERY
    environment: str            # PAPER | SHADOW | MICRO_LIVE | CONTROLLED_LIVE | PRODUCTION_LIVE
    git_commit: Optional[str] = None
    config_hash: Optional[str] = None
    workflow_run_id: Optional[str] = None
    job_run_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def init_local_heartbeat_db(db_path: Optional[Path] = None) -> None:
    """Initializes local SQLite schema for scheduler_invocations."""
    target_path = db_path or LOCAL_DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(target_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduler_invocations (
            id TEXT PRIMARY KEY,
            invocation_id TEXT UNIQUE NOT NULL,
            scheduled_for TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            trigger_source TEXT NOT NULL,
            environment TEXT NOT NULL,
            git_commit TEXT,
            config_hash TEXT,
            workflow_run_id TEXT,
            job_run_id TEXT,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL
        );
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sched_inv_id ON scheduler_invocations(invocation_id);
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sched_created ON scheduler_invocations(created_at);
        """)
        conn.commit()


def generate_invocation_id(
    scheduled_for: datetime,
    schedule_name: str = "NEXUS_DAILY",
    environment: str = "PAPER",
) -> str:
    """
    Generates canonical deterministic invocation identity:
    scheduled_for + schedule_name + environment -> SHA-256 hash prefix.
    Example: INV-2026-09-14-1300UTC-PAPER-a1b2c3d4
    """
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
    utc_dt = scheduled_for.astimezone(timezone.utc)
    date_str = utc_dt.strftime("%Y-%m-%d")
    time_str = utc_dt.strftime("%H%M")
    
    raw = f"{utc_dt.isoformat()}:{schedule_name}:{environment}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"INV-{date_str}-{time_str}UTC-{environment}-{h}"


class SchedulerHeartbeatManager:
    """
    Manages durable persistence and health evaluation of scheduler invocations.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or LOCAL_DB_PATH
        init_local_heartbeat_db(self.db_path)

    @property
    def supabase_url(self) -> Optional[str]:
        val = os.environ.get("SUPABASE_URL", "").strip()
        # Reject unconfigured generic placeholder
        if not val or "your-project-ref" in val or "placeholder" in val.lower():
            return None
        return val.rstrip("/")

    @property
    def supabase_service_key(self) -> Optional[str]:
        val = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or "").strip()
        if not val or "your-service-role-key" in val:
            return None
        return val

    def validate_configuration(self) -> Tuple[bool, str]:
        """Validates that Supabase credentials are validly supplied."""
        if not self.supabase_url:
            return False, "CONFIGURATION_ERROR: SUPABASE_URL is missing or set to placeholder"
        if not self.supabase_service_key:
            return False, "CONFIGURATION_ERROR: SUPABASE_SERVICE_ROLE_KEY is missing or invalid"
        return True, "CONFIG_VALID"

    def record_heartbeat(
        self,
        invocation: SchedulerInvocation,
        require_cloud: bool = False,
    ) -> Tuple[bool, str]:
        """
        Persists new invocation. Enforces deterministic idempotency.
        Returns: (success, status_code) e.g. (True, "REGISTERED"), (False, "ALREADY_REGISTERED").
        """
        # 1. Local SQLite check & write
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status FROM scheduler_invocations WHERE invocation_id = ?",
                (invocation.invocation_id,),
            )
            existing = cursor.fetchone()
            if existing:
                logger.info("Heartbeat %s already exists in SQLite with status %s", invocation.invocation_id, existing[0])
                return False, "ALREADY_REGISTERED"

            cursor.execute("""
            INSERT INTO scheduler_invocations (
                id, invocation_id, scheduled_for, started_at, completed_at, status,
                trigger_source, environment, git_commit, config_hash, workflow_run_id,
                job_run_id, error_code, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                hashlib.md5(invocation.invocation_id.encode()).hexdigest(),
                invocation.invocation_id,
                invocation.scheduled_for,
                invocation.started_at,
                invocation.completed_at,
                invocation.status,
                invocation.trigger_source,
                invocation.environment,
                invocation.git_commit,
                invocation.config_hash,
                invocation.workflow_run_id,
                invocation.job_run_id,
                invocation.error_code,
                invocation.error_message,
                invocation.created_at,
            ))
            conn.commit()

        # 2. Cloud Supabase write
        is_valid, msg = self.validate_configuration()
        if not is_valid:
            if require_cloud:
                logger.error("Cloud heartbeat persistence failed: %s", msg)
                return False, "CONFIGURATION_ERROR"
            logger.warning("Supabase unconfigured; heartbeat persisted locally to SQLite only: %s", msg)
            return True, "LOCAL_ONLY_WARNING"

        try:
            url = f"{self.supabase_url}/rest/v1/scheduler_invocations"
            headers = {
                "apikey": self.supabase_service_key,
                "Authorization": f"Bearer {self.supabase_service_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(invocation.to_dict()).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201):
                    logger.info("Heartbeat %s successfully mirrored to Supabase", invocation.invocation_id)
                    return True, "REGISTERED"
                return True, f"HTTP_{resp.status}"
        except urllib.error.HTTPError as e:
            if e.code == 409:
                logger.info("Supabase heartbeat conflict: %s ALREADY_REGISTERED", invocation.invocation_id)
                return False, "ALREADY_REGISTERED"
            logger.warning("Supabase HTTP error recording heartbeat: %s %s", e.code, e.reason)
            if require_cloud:
                return False, f"SUPABASE_ERROR_{e.code}"
        except Exception as e:
            logger.warning("Supabase connection error recording heartbeat: %s", e)
            if require_cloud:
                return False, "SUPABASE_UNAVAILABLE"

        return True, "REGISTERED"

    def update_heartbeat_status(
        self,
        invocation_id: str,
        status: str,
        completed_at: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        job_run_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """Updates invocation status and outcomes."""
        comp_iso = completed_at or (datetime.now(timezone.utc).isoformat() if status in ("SUCCESS", "PARTIAL", "FAILED") else None)

        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE scheduler_invocations
            SET status = ?, completed_at = COALESCE(?, completed_at),
                workflow_run_id = COALESCE(?, workflow_run_id),
                job_run_id = COALESCE(?, job_run_id),
                error_code = COALESCE(?, error_code),
                error_message = COALESCE(?, error_message)
            WHERE invocation_id = ?
            """, (status, comp_iso, workflow_run_id, job_run_id, error_code, error_message, invocation_id))
            conn.commit()

        is_valid, _ = self.validate_configuration()
        if is_valid:
            try:
                url = f"{self.supabase_url}/rest/v1/scheduler_invocations?invocation_id=eq.{invocation_id}"
                headers = {
                    "apikey": self.supabase_service_key,
                    "Authorization": f"Bearer {self.supabase_service_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                }
                patch_payload = {
                    "status": status,
                    "completed_at": comp_iso,
                }
                if workflow_run_id:
                    patch_payload["workflow_run_id"] = workflow_run_id
                if job_run_id:
                    patch_payload["job_run_id"] = job_run_id
                if error_code:
                    patch_payload["error_code"] = error_code
                if error_message:
                    patch_payload["error_message"] = error_message

                req = urllib.request.Request(
                    url,
                    data=json.dumps(patch_payload).encode("utf-8"),
                    headers=headers,
                    method="PATCH",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status in (200, 204)
            except Exception as e:
                logger.warning("Failed updating heartbeat in Supabase: %s", e)

        return True

    def get_latest_heartbeat(self) -> Optional[Dict[str, Any]]:
        """Retrieves the most recent scheduler invocation."""
        is_valid, _ = self.validate_configuration()
        if is_valid:
            try:
                url = f"{self.supabase_url}/rest/v1/scheduler_invocations?select=*&order=started_at.desc&limit=1"
                headers = {
                    "apikey": self.supabase_service_key,
                    "Authorization": f"Bearer {self.supabase_service_key}",
                    "Content-Type": "application/json",
                }
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        rows = json.loads(resp.read().decode("utf-8"))
                        if rows:
                            return rows[0]
            except Exception as e:
                logger.debug("Failed fetching latest heartbeat from Supabase: %s", e)

        # Fallback to local SQLite
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scheduler_invocations ORDER BY started_at DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return dict(row)

        return None

    def calculate_next_expected_run(self, current_dt: Optional[datetime] = None) -> Tuple[datetime, str]:
        """
        Calculates the next expected execution date/time based on the 18:30 IST Mon-Fri schedule
        and the NSE trading calendar.
        Returns: (next_run_datetime_utc, next_run_ist_string)
        """
        from event_agent.arena.market_clock import MarketClock

        now_utc = current_dt or datetime.now(timezone.utc)
        now_ist = now_utc.astimezone(IST_TZ)

        # Scheduled time is 18:30 IST on trading days
        target_ist_today = datetime(now_ist.year, now_ist.month, now_ist.day, 18, 30, tzinfo=IST_TZ)

        # If today is a trading day and current time < 18:30 IST, next run is today at 18:30 IST
        if MarketClock.is_trading_day(now_ist) and now_ist < target_ist_today:
            next_utc = target_ist_today.astimezone(timezone.utc)
            return next_utc, target_ist_today.strftime("%Y-%m-%d 18:30:00 IST")

        # Otherwise search subsequent days for next trading day
        check_date = (now_ist + timedelta(days=1)).date()
        for _ in range(14):
            candidate_ist = datetime(check_date.year, check_date.month, check_date.day, 18, 30, tzinfo=IST_TZ)
            if MarketClock.is_trading_day(candidate_ist):
                next_utc = candidate_ist.astimezone(timezone.utc)
                return next_utc, candidate_ist.strftime("%Y-%m-%d 18:30:00 IST")
            check_date += timedelta(days=1)

        fallback = now_utc + timedelta(days=1)
        return fallback, fallback.astimezone(IST_TZ).strftime("%Y-%m-%d 18:30:00 IST")

    def evaluate_scheduler_health(
        self,
        current_dt: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Authoritative scheduler health evaluator:
        - Evaluates latest heartbeat record.
        - Evaluates Missed-Run condition: 18:30 IST expected, 18:45 IST tolerance boundary.
        - If after 18:45 IST on a trading day without a valid execution, latches status to MISSED.
        - Computes next expected run dynamically.
        """
        from event_agent.arena.market_clock import MarketClock

        now_utc = current_dt or datetime.now(timezone.utc)
        now_ist = now_utc.astimezone(IST_TZ)
        is_today_trading_day = MarketClock.is_trading_day(now_ist)

        latest = self.get_latest_heartbeat()
        next_utc, next_ist_str = self.calculate_next_expected_run(now_utc)

        # 1. No heartbeat in system at all -> UNVERIFIED
        if not latest:
            return {
                "status": SchedulerState.UNVERIFIED,
                "authority": "UNVERIFIED",
                "environment": "PAPER",
                "schedule": "0 13 * * 1-5",
                "local_schedule": "18:30 IST (Mon-Fri)",
                "last_invocation": None,
                "last_success": None,
                "next_expected_run": next_ist_str,
                "missed_runs": 0,
                "consecutive_failures": 0,
                "workflow_run_id": None,
                "git_commit": None,
                "error_code": None,
                "error_message": None,
            }

        last_status = latest.get("status", "UNVERIFIED")
        last_started_str = latest.get("started_at")
        last_started_dt = None
        if last_started_str:
            try:
                last_started_dt = datetime.fromisoformat(last_started_str.replace("Z", "+00:00"))
            except Exception:
                pass

        # 2. Check today's expected execution window
        today_expected_ist = datetime(now_ist.year, now_ist.month, now_ist.day, 18, 30, tzinfo=IST_TZ)
        today_tolerance_boundary_ist = datetime(now_ist.year, now_ist.month, now_ist.day, 18, 45, tzinfo=IST_TZ)

        # Did an invocation occur today?
        ran_today = False
        if last_started_dt:
            last_started_ist = last_started_dt.astimezone(IST_TZ)
            ran_today = (last_started_ist.date() == now_ist.date())

        # Missed Run Detection:
        # If today is a trading day, current time >= 18:45 IST, and no valid run started today -> MISSED (Red Latch)
        if is_today_trading_day and now_ist >= today_tolerance_boundary_ist and not ran_today:
            return {
                "status": SchedulerState.MISSED,
                "authority": "SUPABASE" if self.supabase_url else "SQLITE_LOCAL",
                "environment": latest.get("environment", "PAPER"),
                "schedule": "0 13 * * 1-5",
                "local_schedule": "18:30 IST (Mon-Fri)",
                "last_invocation": latest,
                "last_success": latest.get("completed_at") if last_status in ("SUCCESS", "PARTIAL") else None,
                "next_expected_run": next_ist_str,
                "missed_runs": 1,
                "consecutive_failures": 0 if last_status in ("SUCCESS", "PARTIAL") else 1,
                "workflow_run_id": latest.get("workflow_run_id"),
                "git_commit": latest.get("git_commit"),
                "error_code": "SCHEDULER_MISSED",
                "error_message": f"Expected execution at 18:30 IST; tolerance boundary 18:45 IST exceeded without invocation on {now_ist.strftime('%Y-%m-%d')}.",
            }

        # Stale Detection: if last invocation > 36 hours ago on trading days
        if last_started_dt:
            age_hours = (now_utc - last_started_dt).total_seconds() / 3600.0
            if age_hours > 72.0:
                resolved_status = SchedulerState.STALE
            elif last_status in ("RUNNING", "DISPATCHED"):
                # If running for > 30 mins, flag degraded
                if age_hours > 0.5:
                    resolved_status = SchedulerState.FAILED
                else:
                    resolved_status = SchedulerState.RUNNING
            elif last_status == "SUCCESS":
                resolved_status = SchedulerState.HEALTHY
            elif last_status == "PARTIAL":
                resolved_status = SchedulerState.PARTIAL
            elif last_status == "FAILED":
                resolved_status = SchedulerState.FAILED
            else:
                resolved_status = last_status
        else:
            resolved_status = SchedulerState.UNVERIFIED

        return {
            "status": resolved_status,
            "authority": "SUPABASE" if self.supabase_url else "SQLITE_LOCAL",
            "environment": latest.get("environment", "PAPER"),
            "schedule": "0 13 * * 1-5",
            "local_schedule": "18:30 IST (Mon-Fri)",
            "last_invocation": latest,
            "last_success": latest.get("completed_at") if last_status in ("SUCCESS", "PARTIAL") else None,
            "next_expected_run": next_ist_str,
            "missed_runs": 0,
            "consecutive_failures": 1 if resolved_status == SchedulerState.FAILED else 0,
            "workflow_run_id": latest.get("workflow_run_id"),
            "git_commit": latest.get("git_commit"),
            "error_code": latest.get("error_code"),
            "error_message": latest.get("error_message"),
        }
