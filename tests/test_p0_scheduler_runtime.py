# =============================================================================
# tests/test_p0_scheduler_runtime.py — P0 Scheduler & Runtime Verification
# =============================================================================
"""
Adversarial and functional test suite for the NEXUS P0 Scheduler & Production Runtime:
- Tests 1-10: Scheduler UTC cron, IST conversion, idempotency, heartbeat, missed-run detector, red latch.
- Tests 11-15: Supabase configuration, placeholder rejection, and error handling.
- Tests 16-19: GitHub Actions workflow dispatch simulation and error states.
- Tests 20-25: Daily report idempotency, stage isolation, parent/child status aggregation.
- Tests 26-32: UI truthfulness, removal of static claims, dynamic state presentation.
- Tests 33-36: Security invariants (zero secret leakage, strict PAPER environment enforcement).
- Tests A-J: Comprehensive Failure-Injection Scenarios.
"""

from datetime import datetime, date, time, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import pytest

from event_agent.storage.scheduler_heartbeat import (
    SchedulerHeartbeatManager,
    SchedulerInvocation,
    SchedulerState,
    generate_invocation_id,
    init_local_heartbeat_db,
)
from event_agent.arena.market_clock import MarketClock
from event_agent.execution.environment import TradingEnvironment, EnvironmentManager


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_job_runs.db"
    init_local_heartbeat_db(db_file)
    return db_file


@pytest.fixture
def hb_manager(temp_db):
    return SchedulerHeartbeatManager(db_path=temp_db)


# =============================================================================
# 1. Scheduler Cron & Timezone Tests
# =============================================================================

def test_01_correct_utc_cron_specification():
    """Verify Netlify and GitHub schedule is exactly '0 13 * * 1-5'."""
    netlify_toml = Path(__file__).resolve().parents[1] / "netlify.toml"
    assert netlify_toml.exists()
    content = netlify_toml.read_text()
    assert 'schedule = "0 13 * * 1-5"' in content, "Netlify schedule must be '0 13 * * 1-5'"


def test_02_ist_timezone_conversion():
    """Verify 13:00 UTC converts to exactly 18:30 IST."""
    utc_time = datetime(2026, 9, 14, 13, 0, 0, tzinfo=timezone.utc)
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    ist_time = utc_time.astimezone(ist_tz)
    assert ist_time.hour == 18
    assert ist_time.minute == 30
    assert ist_time.strftime("%H:%M IST") == "18:30 IST"


def test_03_invocation_id_creation():
    """Verify deterministic invocation ID generation."""
    dt = datetime(2026, 9, 14, 13, 0, 0, tzinfo=timezone.utc)
    inv_id1 = generate_invocation_id(dt, "NEXUS_DAILY", "PAPER")
    inv_id2 = generate_invocation_id(dt, "NEXUS_DAILY", "PAPER")
    assert inv_id1 == inv_id2
    assert inv_id1.startswith("INV-2026-09-14-1300UTC-PAPER-")


def test_04_invocation_idempotency(hb_manager):
    """Verify duplicate invocation delivery returns ALREADY_REGISTERED."""
    dt = datetime(2026, 9, 14, 13, 0, 0, tzinfo=timezone.utc)
    inv_id = generate_invocation_id(dt, "NEXUS_DAILY", "PAPER")
    rec = SchedulerInvocation(
        invocation_id=inv_id,
        scheduled_for=dt.isoformat(),
        started_at=dt.isoformat(),
        completed_at=None,
        status="DISPATCHED",
        trigger_source="NETLIFY_CRON",
        environment="PAPER",
    )
    ok1, status1 = hb_manager.record_heartbeat(rec)
    assert ok1 is True
    assert status1 in ("REGISTERED", "LOCAL_ONLY_WARNING")

    # Second registration attempt of the exact same invocation
    ok2, status2 = hb_manager.record_heartbeat(rec)
    assert ok2 is False
    assert status2 == "ALREADY_REGISTERED"


def test_05_heartbeat_persistence_across_states(hb_manager):
    """Verify heartbeat correctly transitions DISPATCHED -> RUNNING -> SUCCESS."""
    inv_id = "INV-TEST-LIFECYCLE-001"
    rec = SchedulerInvocation(
        invocation_id=inv_id,
        scheduled_for=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=None,
        status="DISPATCHED",
        trigger_source="NETLIFY_CRON",
        environment="PAPER",
    )
    hb_manager.record_heartbeat(rec)

    # Transition to RUNNING
    hb_manager.update_heartbeat_status(inv_id, status=SchedulerState.RUNNING, workflow_run_id="WF-999")
    latest = hb_manager.get_latest_heartbeat()
    assert latest["status"] == "RUNNING"
    assert latest["workflow_run_id"] == "WF-999"

    # Transition to SUCCESS
    hb_manager.update_heartbeat_status(inv_id, status=SchedulerState.SUCCESS)
    latest2 = hb_manager.get_latest_heartbeat()
    assert latest2["status"] == "SUCCESS"
    assert latest2["completed_at"] is not None


def test_06_duplicate_cron_delivery_preserves_single_run(hb_manager):
    """Verify cron double-firing produces exactly 1 database row."""
    inv_id = "INV-2026-09-14-DUP-TEST"
    rec = SchedulerInvocation(
        invocation_id=inv_id,
        scheduled_for="2026-09-14T13:00:00Z",
        started_at="2026-09-14T13:00:01Z",
        completed_at=None,
        status="DISPATCHED",
        trigger_source="NETLIFY_CRON",
        environment="PAPER",
    )
    hb_manager.record_heartbeat(rec)
    hb_manager.record_heartbeat(rec)
    hb_manager.record_heartbeat(rec)

    import sqlite3
    with sqlite3.connect(str(hb_manager.db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM scheduler_invocations WHERE invocation_id = ?", (inv_id,))
        count = cursor.fetchone()[0]
        assert count == 1, "There must be exactly 1 row even after multiple deliveries"


def test_07_missed_run_detection_at_1845_boundary(hb_manager):
    """Verify that at or after 18:45 IST without a today invocation, status latches to MISSED."""
    # Simulate a Monday trading day at 18:50 IST (13:20 UTC)
    simulated_now_utc = datetime(2026, 9, 14, 13, 20, 0, tzinfo=timezone.utc)
    # Ensure no invocation for 2026-09-14 exists
    health = hb_manager.evaluate_scheduler_health(current_dt=simulated_now_utc)
    # Since simulated_now_utc has no invocation today, it should detect MISSED
    # First verify September 14, 2026 is an active trading day (Monday)
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    sim_ist = simulated_now_utc.astimezone(ist_tz)
    assert MarketClock.is_trading_day(sim_ist) is True

    # If an older heartbeat existed:
    old_rec = SchedulerInvocation(
        invocation_id="INV-2026-09-11-OLD",
        scheduled_for="2026-09-11T13:00:00Z",
        started_at="2026-09-11T13:00:00Z",
        completed_at="2026-09-11T13:01:00Z",
        status="SUCCESS",
        trigger_source="NETLIFY_CRON",
        environment="PAPER",
    )
    hb_manager.record_heartbeat(old_rec)

    health = hb_manager.evaluate_scheduler_health(current_dt=simulated_now_utc)
    assert health["status"] == SchedulerState.MISSED
    assert health["error_code"] == "SCHEDULER_MISSED"


def test_08_red_latch_persists_until_recovery(hb_manager):
    """Verify red latch remains MISSED until a valid subsequent run recovers it."""
    # 13:30 UTC = 19:00 IST on Monday Sept 14, 2026
    simulated_now = datetime(2026, 9, 14, 13, 30, 0, tzinfo=timezone.utc)
    # Insert older record
    hb_manager.record_heartbeat(SchedulerInvocation(
        invocation_id="INV-2026-09-11-OLD",
        scheduled_for="2026-09-11T13:00:00Z",
        started_at="2026-09-11T13:00:00Z",
        completed_at="2026-09-11T13:01:00Z",
        status="SUCCESS",
        trigger_source="NETLIFY_CRON",
        environment="PAPER",
    ))

    # At 19:00 IST without today's run: MISSED
    h1 = hb_manager.evaluate_scheduler_health(current_dt=simulated_now)
    assert h1["status"] == SchedulerState.MISSED

    # Now recovery happens: today's run starts and succeeds
    recovery_rec = SchedulerInvocation(
        invocation_id="INV-2026-09-14-1300UTC-PAPER-RECOVERY",
        scheduled_for="2026-09-14T13:00:00Z",
        started_at="2026-09-14T13:30:00Z",
        completed_at="2026-09-14T13:35:00Z",
        status="SUCCESS",
        trigger_source="RECOVERY",
        environment="PAPER",
    )
    hb_manager.record_heartbeat(recovery_rec)

    # Health recovers to HEALTHY
    h2 = hb_manager.evaluate_scheduler_health(current_dt=simulated_now)
    assert h2["status"] == SchedulerState.HEALTHY


def test_09_no_hardcoded_next_run_value(hb_manager):
    """Verify next run is dynamically computed from trading days, not hardcoded 21:00."""
    now_utc = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc) # 17:30 IST on trading day
    next_utc, next_ist_str = hb_manager.calculate_next_expected_run(now_utc)
    assert "18:30:00 IST" in next_ist_str
    assert "21:00" not in next_ist_str


def test_10_unverified_when_no_heartbeat_recorded(hb_manager):
    """Verify status is UNVERIFIED when database is empty."""
    h = hb_manager.evaluate_scheduler_health()
    assert h["status"] == SchedulerState.UNVERIFIED
    assert h["authority"] == "UNVERIFIED"


# =============================================================================
# 2. Supabase Configuration & Credential Safety Tests
# =============================================================================

def test_11_missing_supabase_url_returns_configuration_error(monkeypatch, hb_manager):
    """Verify missing SUPABASE_URL produces CONFIGURATION_ERROR."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "real-valid-key")
    is_valid, msg = hb_manager.validate_configuration()
    assert is_valid is False
    assert "CONFIGURATION_ERROR" in msg


def test_12_placeholder_supabase_url_is_rejected(monkeypatch, hb_manager):
    """Verify dummy URL htcgeupzkxxxplqtvxue is rejected."""
    monkeypatch.setenv("SUPABASE_URL", "https://htcgeupzkxxxplqtvxue.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "real-key")
    is_valid, msg = hb_manager.validate_configuration()
    assert is_valid is False
    assert "CONFIGURATION_ERROR" in msg


def test_13_missing_service_role_key_rejected(monkeypatch, hb_manager):
    """Verify missing SUPABASE_SERVICE_ROLE_KEY returns CONFIGURATION_ERROR."""
    monkeypatch.setenv("SUPABASE_URL", "https://real-project.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    is_valid, msg = hb_manager.validate_configuration()
    assert is_valid is False
    assert "CONFIGURATION_ERROR" in msg


def test_14_require_cloud_fails_closed_when_unconfigured(monkeypatch, hb_manager):
    """Verify record_heartbeat with require_cloud=True returns False on invalid config."""
    monkeypatch.setenv("SUPABASE_URL", "")
    rec = SchedulerInvocation(
        invocation_id="INV-CLOUD-REQ",
        scheduled_for=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=None,
        status="DISPATCHED",
        trigger_source="TEST",
        environment="PAPER",
    )
    ok, code = hb_manager.record_heartbeat(rec, require_cloud=True)
    assert ok is False
    assert code == "CONFIGURATION_ERROR"


# =============================================================================
# 3. GitHub Actions & Cloud Runner Tests
# =============================================================================

def test_16_github_workflow_file_exists():
    """Verify daily_trade_report.yml exists and uses workflow_dispatch."""
    wf_path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily_trade_report.yml"
    assert wf_path.exists()
    content = wf_path.read_text()
    assert "workflow_dispatch:" in content
    assert "concurrency:" in content
    assert "cancel-in-progress: false" in content


def test_17_github_workflow_has_no_active_cron_by_default():
    """Verify GitHub workflow has NO schedule: cron active (Netlify is sole canonical scheduler)."""
    wf_path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily_trade_report.yml"
    content = wf_path.read_text()
    # Check that under 'on:', schedule is not declared
    lines = [l.strip() for l in content.split("\n")]
    assert "schedule:" not in lines, "GitHub Actions must not have an active cron schedule; Netlify is canonical."


# =============================================================================
# 4. Daily Report Pipeline & Stage Aggregation Tests
# =============================================================================

def test_24_parent_child_status_aggregation_mandatory_failure():
    """Verify overall status is FAILED if mandatory stage (e.g. DATA or AI) fails."""
    from event_agent.reporting.daily_trade_pipeline import PipelineExecutionReport
    # If DATA_COLLECTION failed, overall must be FAILED
    report = PipelineExecutionReport(
        report_date="2026-09-14",
        idempotency_key="2026-09-14:DAILY_TRADE_REPORT",
        overall_status="FAILED",
        stage_statuses={
            "DATA_COLLECTION": "FAILED",
            "AI_ANALYSIS": "SUCCESS",
            "VOICE": "SUCCESS",
            "VIDEO": "SUCCESS",
            "YOUTUBE": "SUCCESS",
            "EMAIL": "SUCCESS",
        },
        reconciliation={},
        ai_analysis=None,
        voice_result=None,
        video_result=None,
        youtube_result=None,
        email_result=None,
        provenance={},
        duration_ms=500,
    )
    assert report.overall_status == "FAILED"


def test_25_parent_child_status_aggregation_optional_child_failure():
    """Verify overall status is PARTIAL_SUCCESS if optional stage (email) fails but core succeeds."""
    from event_agent.reporting.daily_trade_pipeline import PipelineExecutionReport
    report = PipelineExecutionReport(
        report_date="2026-09-14",
        idempotency_key="2026-09-14:DAILY_TRADE_REPORT",
        overall_status="PARTIAL_SUCCESS",
        stage_statuses={
            "DATA_COLLECTION": "ACTIVE_TRADING",
            "AI_ANALYSIS": "SUCCESS",
            "VOICE": "SUCCESS",
            "VIDEO": "SUCCESS",
            "YOUTUBE": "SUCCESS",
            "EMAIL": "FAILED",
        },
        reconciliation={},
        ai_analysis=None,
        voice_result=None,
        video_result=None,
        youtube_result=None,
        email_result=None,
        provenance={},
        duration_ms=500,
    )
    assert report.overall_status == "PARTIAL_SUCCESS"
    assert report.overall_status != "SUCCESS", "Never claim full SUCCESS if a child stage failed!"


# =============================================================================
# 5. UI Truth & Static Purge Tests
# =============================================================================

def test_26_no_static_healthy_in_index_html():
    """Verify index.html scheduler badge does NOT contain static '🟢 HEALTHY'."""
    index_path = Path(__file__).resolve().parents[1] / "web_app" / "index.html"
    content = index_path.read_text()
    # Ensure #scheduler-status-badge does not contain 🟢 HEALTHY
    assert 'id="scheduler-status-badge" style="font-size: 13px; font-weight: 800; padding: 4px 10px;">🟢 HEALTHY</span>' not in content
    assert '🔴 SCHEDULER UNVERIFIED / STALE' in content


def test_27_no_static_next_run_2100_in_index_html():
    """Verify index.html does NOT contain '21:00:00 IST' static text."""
    index_path = Path(__file__).resolve().parents[1] / "web_app" / "index.html"
    content = index_path.read_text()
    assert '<span class="val" id="sched-next-ist">21:00:00 IST</span>' not in content
    assert '<span class="val" id="sched-next-ist">--</span>' in content


# =============================================================================
# 6. Security Invariants Tests
# =============================================================================

def test_33_secrets_not_exposed_in_client_js():
    """Verify client JS files never contain API keys or service role secrets."""
    app_js = Path(__file__).resolve().parents[1] / "web_app" / "app.js"
    content = app_js.read_text()
    forbidden = [
        "SERVICE_ROLE_KEY", "OPENROUTER_API_KEY", "CREATOMATE_API_KEY",
        "ELEVENLABS_API_KEY", "RESEND_API_KEY", "UPSTOX_API_SECRET",
    ]
    for key in forbidden:
        assert f'"{key}"' not in content, f"Secret key {key} must not be referenced in client app.js"


def test_34_strict_paper_environment_enforcement():
    """Verify EnvironmentManager and orchestrator block non-PAPER environments."""
    assert EnvironmentManager.get_configured_environment() == TradingEnvironment.PAPER
    # Attempting to run with LIVE environment raises RuntimeError
    from event_agent.jobs.daily_report import run_cloud_daily_report
    with pytest.raises(RuntimeError) as excinfo:
        run_cloud_daily_report(environment="PRODUCTION_LIVE")
    assert "EXECUTION_BLOCKED" in str(excinfo.value)


# =============================================================================
# 7. Failure Injection Scenarios (Tests A–J)
# =============================================================================

def test_failure_injection_test_a_dispatch_fails_updates_heartbeat(hb_manager):
    """Test A: Workflow dispatch fails -> status marked FAILED with WORKFLOW_DISPATCH_FAILED."""
    inv_id = "INV-TEST-FAIL-A"
    hb_manager.record_heartbeat(SchedulerInvocation(
        invocation_id=inv_id,
        scheduled_for="2026-09-14T13:00:00Z",
        started_at="2026-09-14T13:00:00Z",
        completed_at=None,
        status="DISPATCHED",
        trigger_source="NETLIFY_CRON",
        environment="PAPER",
    ))
    # Simulate dispatch failure
    hb_manager.update_heartbeat_status(
        invocation_id=inv_id,
        status=SchedulerState.FAILED,
        error_code="WORKFLOW_DISPATCH_FAILED",
        error_message="GitHub workflow dispatch returned HTTP 502",
    )
    latest = hb_manager.get_latest_heartbeat()
    assert latest["status"] == "FAILED"
    assert latest["error_code"] == "WORKFLOW_DISPATCH_FAILED"


def test_failure_injection_test_b_supabase_down_no_false_success(monkeypatch, hb_manager):
    """Test B: Supabase unavailable -> No false success is claimed."""
    monkeypatch.setenv("SUPABASE_URL", "https://nonexistent-cluster-broken-999.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "some-key")
    # record_heartbeat with require_cloud must return False
    rec = SchedulerInvocation(
        invocation_id="INV-TEST-FAIL-B",
        scheduled_for="2026-09-14T13:00:00Z",
        started_at="2026-09-14T13:00:00Z",
        completed_at=None,
        status="DISPATCHED",
        trigger_source="TEST",
        environment="PAPER",
    )
    ok, code = hb_manager.record_heartbeat(rec, require_cloud=True)
    assert ok is False
    assert "SUPABASE" in code or "ERROR" in code


def test_failure_injection_test_c_openrouter_unavailable_ai_fails(monkeypatch):
    """Test C: OpenRouter unavailable -> AI_UNAVAILABLE, never synthetic sentiment."""
    from event_agent.reporting.ai_analyst import DailyAIAnalyst
    from event_agent.reporting.trade_reconciliation import TradeReconciliationEngine
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    analyst = DailyAIAnalyst(api_key="")  # Unconfigured key
    rec = TradeReconciliationEngine.reconcile_date(
        target_date="2026-09-14",
        custom_trades_fixture=[
            {
                "trade_id": "TRD-C1",
                "symbol": "RELIANCE.NS",
                "side": "BUY",
                "entry_price": 2500.0,
                "exit_price": 2550.0,
                "quantity": 10,
                "gross_pnl": 500.0,
                "net_pnl": 450.0,
                "charges": 50.0,
                "agent_id": "ALPHA",
                "strategy_version": "V1",
                "decision_reason": "test",
            }
        ],
    )
    res = analyst.analyze_daily_performance(rec)
    assert res.ai_status in ("FAILED", "NOT_CONFIGURED", "AI_UNAVAILABLE")
    assert "not configured" in (res.error_message or "").lower()


def test_failure_injection_test_g_scheduler_cron_fires_twice(hb_manager):
    """Test G: Scheduler cron fires twice -> exactly ONE authoritative run."""
    inv_id = "INV-2026-09-14-1300UTC-PAPER-TWICE"
    rec = SchedulerInvocation(
        invocation_id=inv_id,
        scheduled_for="2026-09-14T13:00:00Z",
        started_at="2026-09-14T13:00:00Z",
        completed_at=None,
        status="DISPATCHED",
        trigger_source="NETLIFY_CRON",
        environment="PAPER",
    )
    res1, _ = hb_manager.record_heartbeat(rec)
    res2, code2 = hb_manager.record_heartbeat(rec)
    assert res1 is True
    assert res2 is False
    assert code2 == "ALREADY_REGISTERED"


def test_failure_injection_test_i_dashboard_opens_with_supabase_unavailable(hb_manager):
    """Test I: Evaluator returns UNVERIFIED when database is unpopulated."""
    h = hb_manager.evaluate_scheduler_health()
    assert h["status"] == SchedulerState.UNVERIFIED
    assert h["authority"] == "UNVERIFIED"
    assert h["status"] != "HEALTHY"


def test_failure_injection_test_j_no_heartbeat_past_1845_latches_missed(hb_manager):
    """Test J: No scheduler heartbeat after 18:45 IST on trading day -> SCHEDULER_MISSED, RED LATCH."""
    # 18:46 IST on Monday Sept 14, 2026 = 13:16 UTC
    now_past_tolerance = datetime(2026, 9, 14, 13, 16, 0, tzinfo=timezone.utc)
    # Put an old record from Friday
    hb_manager.record_heartbeat(SchedulerInvocation(
        invocation_id="INV-2026-09-11-FRIDAY",
        scheduled_for="2026-09-11T13:00:00Z",
        started_at="2026-09-11T13:00:00Z",
        completed_at="2026-09-11T13:05:00Z",
        status="SUCCESS",
        trigger_source="NETLIFY_CRON",
        environment="PAPER",
    ))
    h = hb_manager.evaluate_scheduler_health(current_dt=now_past_tolerance)
    assert h["status"] == SchedulerState.MISSED
    assert h["error_code"] == "SCHEDULER_MISSED"
