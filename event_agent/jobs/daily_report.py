# =============================================================================
# event_agent/jobs/daily_report.py — Cloud Execution Entrypoint for Daily Report
# =============================================================================
"""
Cloud Orchestrator Entrypoint for NEXUS Daily Trade Report:
- Validates environment: strictly asserts PAPER environment.
- Validates production secrets with structured diagnostics (no secret leakage).
- Updates durable scheduler heartbeat in Supabase (`scheduler_invocations`).
- Executes the 7-stage post-market reporting pipeline:
  Data Collection -> AI Analysis -> Voice Narration -> Video Render ->
  YouTube Upload -> Email Dispatch -> Deterministic Provenance.
- Reflects truthful parent/child status aggregation and persists to Supabase.
"""

import argparse
from datetime import datetime, timezone
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from ..reporting.daily_trade_pipeline import DailyTradeReportPipeline, PipelineExecutionReport
from ..storage.scheduler_heartbeat import (
    SchedulerHeartbeatManager,
    SchedulerInvocation,
    SchedulerState,
    generate_invocation_id,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("event_agent.jobs.daily_report")


def validate_required_secrets() -> Dict[str, str]:
    """
    Produces structured diagnostics of required API credentials.
    Zero-secret leak: values are NEVER printed or logged.
    """
    secrets = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "OPENROUTER_API_KEY",
        "UPSTOX_API_KEY",
        "UPSTOX_API_SECRET",
        "UPSTOX_ACCESS_TOKEN",
        "ELEVENLABS_API_KEY",
        "CREATOMATE_API_KEY",
        "YOUTUBE_CLIENT_ID",
        "YOUTUBE_CLIENT_SECRET",
        "YOUTUBE_REFRESH_TOKEN",
        "EMAIL_PROVIDER_API_KEY",
        "REPORT_EMAIL_TO",
    ]
    audit = {}
    for s in secrets:
        val = os.environ.get(s, "").strip()
        is_placeholder = "placeholder" in val.lower() or "htcgeupzkxxxplqtvxue" in val
        audit[s] = "PRESENT" if (bool(val) and not is_placeholder) else "MISSING"

    logger.info("=== NEXUS SECRETS DIAGNOSTIC AUDIT ===")
    for k, v in audit.items():
        logger.info("  %-28s: %s", k, v)
    logger.info("=======================================")
    return audit


def run_cloud_daily_report(
    scheduled_date: Optional[str] = None,
    invocation_id: Optional[str] = None,
    workflow_run_id: Optional[str] = None,
    environment: str = "PAPER",
    trigger_source: str = "WORKFLOW_DISPATCH",
    force_regenerate: bool = False,
    custom_trades_fixture: Optional[List[Dict[str, Any]]] = None,
) -> PipelineExecutionReport:
    """
    Main cloud orchestrator execution sequence.
    """
    start_time = datetime.now(timezone.utc)
    target_date = scheduled_date or start_time.strftime("%Y-%m-%d")

    # 1. Hard Environmental Safety Assertion (Section 35)
    env_clean = (environment or os.environ.get("NEXUS_ENVIRONMENT", "PAPER")).strip().upper()
    if env_clean != "PAPER":
        err_msg = (
            f"EXECUTION_BLOCKED: Environment is '{env_clean}'. "
            "Production live trading is blocked! Only PAPER is certified."
        )
        logger.critical(err_msg)
        raise RuntimeError(err_msg)

    logger.info("[✓] Environmental Assertion Confirmed: Environment = %s", env_clean)

    # 2. Secret Diagnostics
    validate_required_secrets()

    # 3. Heartbeat Initialization / Update
    hb_manager = SchedulerHeartbeatManager()
    canonical_inv_id = invocation_id or generate_invocation_id(
        scheduled_for=start_time,
        schedule_name="NEXUS_DAILY",
        environment=env_clean,
    )

    logger.info("Binding execution to canonical invocation: %s", canonical_inv_id)

    # Record or update status to RUNNING in Supabase
    existing_hb = hb_manager.get_latest_heartbeat()
    if existing_hb and existing_hb.get("invocation_id") == canonical_inv_id:
        hb_manager.update_heartbeat_status(
            invocation_id=canonical_inv_id,
            status=SchedulerState.RUNNING,
            workflow_run_id=workflow_run_id,
        )
    else:
        inv_record = SchedulerInvocation(
            invocation_id=canonical_inv_id,
            scheduled_for=start_time.isoformat(),
            started_at=start_time.isoformat(),
            completed_at=None,
            status=SchedulerState.RUNNING,
            trigger_source=trigger_source,
            environment=env_clean,
            git_commit=os.environ.get("GITHUB_COMMIT") or os.environ.get("COMMIT_REF"),
            config_hash="p0_runtime_cfg_v40",
            workflow_run_id=workflow_run_id,
        )
        hb_manager.record_heartbeat(inv_record)

    # 4. Execute Pipeline
    pipeline = DailyTradeReportPipeline()
    try:
        res = pipeline.run_pipeline(
            report_date=target_date,
            force_regenerate=force_regenerate,
            custom_trades_fixture=custom_trades_fixture,
            trigger_type="SCHEDULED" if not (force_regenerate or custom_trades_fixture) else "MANUAL",
        )
    except Exception as exc:
        logger.error("Daily report pipeline failed with uncaught exception: %s", exc, exc_info=True)
        hb_manager.update_heartbeat_status(
            invocation_id=canonical_inv_id,
            status=SchedulerState.FAILED,
            completed_at=datetime.now(timezone.utc).isoformat(),
            workflow_run_id=workflow_run_id,
            error_code="WORKFLOW_FAILED",
            error_message=str(exc)[:250],
        )
        raise

    # 5. Authoritative Parent Heartbeat Finalization
    final_status = res.overall_status  # 'SUCCESS' | 'PARTIAL_SUCCESS' | 'FAILED' | 'SKIPPED'
    hb_status_map = {
        "SUCCESS": SchedulerState.SUCCESS,
        "PARTIAL_SUCCESS": SchedulerState.PARTIAL,
        "FAILED": SchedulerState.FAILED,
        "SKIPPED": SchedulerState.SUCCESS,
    }
    resolved_hb_status = hb_status_map.get(final_status, SchedulerState.FAILED)

    hb_manager.update_heartbeat_status(
        invocation_id=canonical_inv_id,
        status=resolved_hb_status,
        completed_at=datetime.now(timezone.utc).isoformat(),
        workflow_run_id=workflow_run_id,
        job_run_id=res.reconciliation.get("job_run_id") if isinstance(res.reconciliation, dict) else None,
        error_code=None if resolved_hb_status in (SchedulerState.SUCCESS, SchedulerState.PARTIAL) else "STAGE_FAILURE",
        error_message=None if resolved_hb_status in (SchedulerState.SUCCESS, SchedulerState.PARTIAL) else f"Stages: {res.stage_statuses}",
    )

    logger.info("===========================================================")
    logger.info("NEXUS DAILY TRADE REPORT COMPLETED: Status = %s", final_status)
    logger.info("Invocation ID : %s", canonical_inv_id)
    logger.info("Workflow Run  : %s", workflow_run_id)
    logger.info("Stages        : %s", json.dumps(res.stage_statuses))
    logger.info("Provenance    : %s", res.provenance.get("provenance_hash"))
    logger.info("===========================================================")

    return res


def main():
    parser = argparse.ArgumentParser(description="NEXUS Cloud Daily Report Orchestrator")
    parser.add_argument("--scheduled-date", help="Report date (YYYY-MM-DD)", default=None)
    parser.add_argument("--invocation-id", help="Canonical invocation identity", default=None)
    parser.add_argument("--workflow-run-id", help="GitHub Actions workflow run ID", default=None)
    parser.add_argument("--environment", help="Execution environment", default="PAPER")
    parser.add_argument("--trigger-source", help="Trigger source", default="WORKFLOW_DISPATCH")
    parser.add_argument("--force", action="store_true", help="Force regenerate")
    parser.add_argument("--test-fixture", action="store_true", help="Run with test fixture")
    args = parser.parse_args()

    fixture = None
    if args.test_fixture:
        fixture = [
            {
                "trade_id": "TRD-P0-RELIANCE",
                "symbol": "RELIANCE.NS",
                "side": "BUY",
                "entry_price": 2510.0,
                "exit_price": 2562.0,
                "quantity": 80,
                "gross_pnl": 4160.0,
                "net_pnl": 3980.0,
                "charges": 180.0,
                "agent_id": "ALPHA",
                "strategy_version": "Event_Arbitrage_V1",
                "decision_reason": "P0 runtime test verification",
            }
        ]

    try:
        report = run_cloud_daily_report(
            scheduled_date=args.scheduled_date,
            invocation_id=args.invocation_id,
            workflow_run_id=args.workflow_run_id,
            environment=args.environment,
            trigger_source=args.trigger_source,
            force_regenerate=args.force,
            custom_trades_fixture=fixture,
        )
        if report.overall_status in ("SUCCESS", "PARTIAL_SUCCESS", "SKIPPED"):
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        logger.critical("Fatal orchestrator failure: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
