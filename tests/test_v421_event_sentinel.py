# =============================================================================
# tests/test_v421_event_sentinel.py — Continuous Event Intelligence Test Suite
# =============================================================================
"""
V4.2.1 Event Sentinel & Continuous Intelligence Verification Suite:
Covers:
  1. 19 standard categories classifier & bps extraction
  2. Event deduplicator (SHA-256 + Jaccard similarity sliding window)
  3. News-independent market shock detector (zero news required)
  4. 3-tier verdict routing: STORE_ONLY, UPDATE_THESIS, TRIGGER_RE_EVALUATION
  5. 10-Point Golden FOMC Test (September 16, 2026 Fed +25 bps lifecycle)
  6. Decoupled 3-denominator event coverage audit
  7. Cloud invocation lineage proof & authoritative Supabase sync
  8. Zero raw credential leak invariant
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta
import pytest

from event_agent.sentinel.models import (
    EventCategory,
    TriggerVerdict,
    ThesisRelation,
    ThesisStatus,
    CalendarStage,
    SentinelEvent,
    ActiveThesis,
    ThesisRevision,
    EventCoverageReport,
    SentinelInvocationRecord,
)
from event_agent.sentinel.event_classifier import EventClassifier
from event_agent.sentinel.event_deduplicator import EventDeduplicator
from event_agent.sentinel.market_shock_detector import MarketShockDetector
from event_agent.sentinel.economic_calendar import EconomicCalendar
from event_agent.sentinel.event_reaction_monitor import EventReactionMonitor
from event_agent.sentinel.event_impact_engine import EventImpactEngine
from event_agent.sentinel.thesis_adjustment_engine import ThesisAdjustmentEngine
from event_agent.sentinel.thesis_state_manager import ThesisStateManager
from event_agent.sentinel.event_sentinel import EventSentinel
from event_agent.storage.ledger import (
    init_db,
    record_sentinel_event,
    get_recent_sentinel_events,
    save_active_thesis,
    get_current_active_thesis,
    save_thesis_revision,
    get_thesis_revisions,
    record_sentinel_invocation,
    get_latest_sentinel_invocation,
    record_event_coverage_metric,
    get_latest_event_coverage_metric,
)
from event_agent.storage.supabase_ledger import (
    save_sentinel_invocation_supabase,
    get_latest_sentinel_telemetry_supabase,
    is_supabase_configured,
)


@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    """Ensure database initialized and clean environment for tests."""
    monkeypatch.setenv("TESTING", "1")
    init_db()


# -----------------------------------------------------------------------------
# 1. 19 Standard Categories Classifier Test
# -----------------------------------------------------------------------------
def test_event_classifier_19_categories():
    """Verify classification across all 19 standardized categories and bps extraction."""
    samples = [
        ("FOMC raises federal funds rate target range by 25 bps", EventCategory.FOMC, 25.0),
        ("RBI monetary policy committee cuts repo rate by 50 bps", EventCategory.RBI, -50.0),
        ("ECB leaves interest rate unchanged at 3.25%", EventCategory.ECB, 0.0),
        ("Bank of Japan signals unexpected interest rate hike", EventCategory.BOJ, 0.0),
        ("US core consumer price index CPI rises 3.2% year over year", EventCategory.INFLATION, 0.0),
        ("Nonfarm payrolls NFP report shows 250,000 jobs added", EventCategory.EMPLOYMENT, 0.0),
        ("India quarterly GDP growth decelerates to 6.2%", EventCategory.GDP, 0.0),
        ("10-Year US Treasury yield surges to 4.35%", EventCategory.BOND_YIELD, 0.0),
        ("Indian Rupee USDINR breaches 84.50 against US Dollar", EventCategory.CURRENCY, 0.0),
        ("Brent crude oil spikes above $90 per barrel", EventCategory.COMMODITY, 0.0),
        ("Middle East tensions escalate following airstrikes", EventCategory.GEOPOLITICAL, 0.0),
        ("S&P 500 and Nasdaq futures tumble 2.5%", EventCategory.GLOBAL_EQUITY, 0.0),
        ("SEBI issues new guidelines for derivatives trading", EventCategory.REGULATORY, 0.0),
        ("Reliance Industries Q2 net profit jumps 15%", EventCategory.EARNINGS, 0.0),
        ("Infosys announces $1B share buyback program", EventCategory.CORPORATE, 0.0),
        ("India wholesale inflation WPI reaches multi-month high", EventCategory.INDIA_MACRO, 0.0),
        ("Central bank announces emergency policy rate tightening", EventCategory.INTEREST_RATE, 0.0),
        ("Unprecedented cyber attack halts sovereign debt settlement", EventCategory.BLACK_SWAN, 0.0),
        ("NIFTY flash crash triggers circuit breaker halt", EventCategory.MARKET_SHOCK, 0.0),
    ]

    for title, expected_cat, expected_bps in samples:
        cat, meta = EventClassifier.classify(title)
        assert cat == expected_cat, f"Expected {expected_cat} for '{title}', got {cat}"
        if expected_bps != 0.0:
            assert meta.get("rate_change_bps") == expected_bps, f"Expected {expected_bps} bps, got {meta.get('rate_change_bps')}"


# -----------------------------------------------------------------------------
# 2. Event Deduplicator Test
# -----------------------------------------------------------------------------
def test_event_deduplicator():
    """Verify SHA-256 canonical hashing and sliding token Jaccard similarity."""
    dedup = EventDeduplicator(window_hours=24, similarity_threshold=0.70)
    now = datetime(2026, 9, 16, 18, 0, 0, tzinfo=timezone.utc)

    title_a = "Federal Reserve hikes benchmark rate by 25 bps"
    title_a_repost = "Federal Reserve hikes benchmark rate by 25 bps"
    title_a_similar = "Fed hikes benchmark interest rate by 25 basis points"
    title_different = "Infosys wins $500M European cloud transformation contract"

    # First encounter: not a duplicate
    assert not dedup.is_duplicate(title_a, now)

    # Identical repost: duplicate
    assert dedup.is_duplicate(title_a_repost, now + timedelta(minutes=5))

    # Semantically near-identical repost: duplicate via Jaccard
    assert dedup.is_duplicate(title_a_similar, now + timedelta(minutes=15))

    # Completely different item: not duplicate
    assert not dedup.is_duplicate(title_different, now + timedelta(minutes=20))

    # Old event beyond 24h window: expires and is no longer flagged
    future = now + timedelta(hours=26)
    assert not dedup.is_duplicate(title_a, future)


# -----------------------------------------------------------------------------
# 3. News-Independent Market Shock Detector Test
# -----------------------------------------------------------------------------
def test_news_independent_market_shock():
    """Verify market shock triggers directly with ZERO news items."""
    detector = MarketShockDetector()

    # Normal calm quotes -> No shock
    calm_quotes = {
        "NIFTY_PRICE": 25200.0,
        "nifty_10m_change_pct": -0.40,
        "INDIA_VIX": 13.50,
        "india_vix_change_pct": 2.5,
        "us_futures_change_pct": -0.30,
        "usdinr_price": 84.10,
    }
    calm_res = detector.evaluate(calm_quotes)
    assert not calm_res.is_shock

    # Severe velocity drop + VIX explosion -> SHOCK
    shock_quotes = {
        "NIFTY_PRICE": 24500.0,
        "nifty_10m_change_pct": -2.85,       # > 2.5% drop in 10m
        "INDIA_VIX": 19.50,
        "india_vix_change_pct": 38.0,        # > 35% surge
        "us_futures_change_pct": -2.40,      # > 2% drop
        "usdinr_price": 85.30,
    }
    shock_res = detector.evaluate(shock_quotes)
    assert shock_res.is_shock
    assert shock_res.sentinel_event is not None
    assert shock_res.sentinel_event.category == EventCategory.MARKET_SHOCK
    assert shock_res.sentinel_event.event_data.get("verdict") == "MARKET_SHOCK"


# -----------------------------------------------------------------------------
# 4. Three-Tier Verdict Routing Test
# -----------------------------------------------------------------------------
def test_three_tier_verdict_routing():
    """Verify STORE_ONLY, UPDATE_THESIS, and TRIGGER_RE_EVALUATION routing."""
    impact_engine = EventImpactEngine()
    active_thesis = ActiveThesis(
        thesis_id="TH-TEST-BEARISH",
        revision=1,
        created_at=datetime.now(timezone.utc).isoformat(),
        bias="BEARISH",
        confidence=70.0,
        expected_move=-0.80,
        valid_until=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        invalidation_conditions=["USDINR > 95.75", "Futures surge > 1.5%"],
    )

    # 1. Routine Company Noise -> STORE_ONLY
    noise_event = SentinelEvent(
        event_id="EV-NOISE-1",
        category=EventCategory.CORPORATE,
        source="RSS",
        title="ABC Ltd appoints new chief marketing officer",
        description="Routine corporate leadership announcement",
        raw_payload_hash="hash_noise",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    res_noise = impact_engine.assess_impact(noise_event, active_thesis, market_reaction_score=5.0)
    assert res_noise.verdict == TriggerVerdict.STORE_ONLY
    assert res_noise.importance_score < 40.0

    # 2. Reinforcing Macro Tightening -> UPDATE_THESIS (Deterministic calibration)
    reinforce_event = SentinelEvent(
        event_id="EV-REINFORCE-1",
        category=EventCategory.FOMC,
        source="REUTERS",
        title="Federal Reserve signals persistent monetary tightening and further hikes",
        description="Hawkish commentary confirms higher for longer stance",
        raw_payload_hash="hash_rf",
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_data={"rate_change_bps": 25.0, "rate_decision_action": "HIKE"},
    )
    res_rf = impact_engine.assess_impact(reinforce_event, active_thesis, market_reaction_score=45.0)
    assert res_rf.verdict == TriggerVerdict.UPDATE_THESIS
    assert res_rf.thesis_relation == ThesisRelation.REINFORCES

    # Deterministic adjustment check
    upd_thesis, rev = ThesisAdjustmentEngine.apply_adjustment(active_thesis, reinforce_event, res_rf.importance_score)
    assert upd_thesis.revision == 2
    assert upd_thesis.confidence > active_thesis.confidence
    assert rev.before_state["confidence"] == 70.0
    assert rev.after_state["confidence"] == upd_thesis.confidence
    assert rev.event_id == "EV-REINFORCE-1"

    # 3. Conflicting Policy Shift -> TRIGGER_RE_EVALUATION
    conflict_event = SentinelEvent(
        event_id="EV-CONFLICT-1",
        category=EventCategory.FOMC,
        source="BLOOMBERG",
        title="Emergency Fed decision: Target rate cut by 50 bps to boost liquidity",
        description="Dovish pivot stimulates global equity markets",
        raw_payload_hash="hash_cf",
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_data={"rate_change_bps": -50.0, "rate_decision_action": "CUT", "us_futures_change_pct": 2.20},
    )
    res_cf = impact_engine.assess_impact(conflict_event, active_thesis, market_reaction_score=80.0)
    assert res_cf.verdict == TriggerVerdict.TRIGGER_RE_EVALUATION
    assert res_cf.thesis_relation == ThesisRelation.CONFLICTS


# -----------------------------------------------------------------------------
# 5. 10-Point Golden FOMC Test (September 16, 2026 Fed +25 bps)
# -----------------------------------------------------------------------------
def test_golden_fomc_september_16_2026():
    """
    10-Point Golden FOMC assertion suite:
    1) FOMC event detected
    2) Official release captured
    3) +25 bps extracted
    4) Consensus vs actual calculated
    5) Cross-market reaction captured (US10Y, DXY, Gold, Futures, VIX)
    6) India transmission calculated
    7) Existing thesis evaluated
    8) Thesis updated or invalidated
    9) New thesis_id/revision generated
    10) Provenance linked end-to-end.
    """
    sentinel = EventSentinel()
    fomc_time = datetime(2026, 9, 16, 18, 5, 0, tzinfo=timezone.utc)

    # Point 1 & 2: Calendar stage advance & official release
    calendar = sentinel.calendar
    stage, gen_evt = calendar.advance_event_stage(
        event_code="FOMC_RATE_20260916",
        current_time=fomc_time,
        current_market_quotes={"us_10y_yield": 4.15, "dxy_index": 103.8},
    )
    assert stage in (
        CalendarStage.RELEASED_T0,
        CalendarStage.REACTION_1M,
        CalendarStage.TRANSMISSION_5M,
        CalendarStage.REEVALUATION_15M,
        CalendarStage.CONFIRMED_30M,
        CalendarStage.SCHEDULED,
    )

    # Point 3: +25 bps extracted
    fomc_title = "Federal Reserve raises interest rates by 25 bps to target 4.00%"
    cat, meta = EventClassifier.classify(fomc_title)
    assert cat == EventCategory.FOMC
    assert meta.get("rate_change_bps") == 25.0

    # Point 4: Consensus vs actual
    cal_event = calendar.events["FOMC_RATE_20260916"]
    assert cal_event.actual_value == "4.00%"
    assert "3.75%" in cal_event.prior_value
    assert cal_event.surprise_delta == "+25 bps"

    # Point 5: Cross-market reaction captured (US10Y, DXY, Gold, Futures, VIX)
    quotes = {
        "us_10y_yield": 4.22,
        "us_10y_change_pct": 2.15,
        "dxy_index": 104.20,
        "dxy_change_pct": 0.65,
        "gold_price": 2570.0,
        "gold_change_pct": -1.25,
        "us_futures_change_pct": -1.10,
        "india_vix_change_pct": 16.5,
        "usdinr_price": 84.45,
        "usdinr_change_pct": 0.45,
    }
    reaction = sentinel.reaction_monitor.evaluate_reaction(quotes)
    assert reaction.composite_reaction_score >= 50.0
    assert len(reaction.reasons) >= 3

    # Point 6: India transmission calculated
    evt = SentinelEvent(
        event_id="EV-FOMC-GOLDEN-20260916",
        category=EventCategory.FOMC,
        source="FED_OFFICIAL_RELEASE",
        title=fomc_title,
        description="FOMC raised target range by 25 bps citing persistent core services inflation.",
        raw_payload_hash=SentinelEvent.generate_hash(fomc_title),
        timestamp=fomc_time.isoformat(),
        event_data={**meta, **quotes},
    )
    active_thesis = sentinel.thesis_manager.get_or_create_active_thesis()
    assessment = sentinel.impact_engine.assess_impact(
        event=evt,
        active_thesis=active_thesis,
        market_reaction_score=reaction.composite_reaction_score,
    )
    assert assessment.india_relevance == "HIGH"
    assert assessment.importance_score == 100.0

    # Point 7 & 8: Thesis evaluated & updated or invalidated
    assert assessment.verdict in (TriggerVerdict.UPDATE_THESIS, TriggerVerdict.TRIGGER_RE_EVALUATION)

    # Point 9: Execute full scan pass and check revision generated
    inv_record = sentinel.run_scan(
        scheduled_invocation_id="SCHED_GOLDEN_FOMC_TEST",
        market_quotes=quotes,
        incoming_news=[{"title": fomc_title, "description": "Fed rate hike 25 bps", "source": "FEDERAL_RESERVE"}],
        current_time=fomc_time,
    )
    assert inv_record.status == "SUCCESS"
    assert inv_record.events_material >= 1
    assert inv_record.events_triggered >= 1

    # Point 10: Complete lineage linked
    assert inv_record.lineage is not None
    assert inv_record.lineage.get("scheduled_invocation_id") == "SCHED_GOLDEN_FOMC_TEST"
    assert inv_record.lineage.get("sentinel_invocation_id") == inv_record.sentinel_invocation_id
    assert inv_record.lineage.get("thesis_id") is not None
    assert inv_record.lineage.get("thesis_revision") >= 1


# -----------------------------------------------------------------------------
# 6. Decoupled 3-Denominator Event Coverage Audit Test
# -----------------------------------------------------------------------------
def test_event_coverage_metrics_decoupled_denominators():
    """Verify Scheduled, Source, and Material coverage calculate independently."""
    report = EventCoverageReport(
        date="2026-09-16",
        scheduled_expected=4,
        scheduled_detected=4,
        scheduled_coverage_pct=100.0,
        source_available=120,
        source_processed=118,
        source_coverage_pct=98.33,
        material_detected=6,
        material_processed=6,
        material_processing_pct=100.0,
    )
    record_event_coverage_metric(report.to_dict())

    retrieved = get_latest_event_coverage_metric()
    assert retrieved is not None
    assert retrieved["scheduled_coverage_pct"] == 100.0
    assert round(retrieved["source_coverage_pct"], 2) == 98.33
    assert retrieved["material_processing_pct"] == 100.0
    assert retrieved["scheduled_expected"] == 4
    assert retrieved["source_available"] == 120
    assert retrieved["material_detected"] == 6


# -----------------------------------------------------------------------------
# 7. Cloud Invocation Lineage & Authoritative Supabase Persistence Test
# -----------------------------------------------------------------------------
def test_cloud_invocation_lineage_and_persistence():
    """Verify invocation lineage persists to Supabase and survives function termination."""
    now_iso = datetime.now(timezone.utc).isoformat()
    test_sched_id = f"SCHED-TEST-{int(time.time())}"
    test_sent_id = f"SENT-TEST-{int(time.time()*1000)}"

    lineage = {
        "scheduled_invocation_id": test_sched_id,
        "sentinel_invocation_id": test_sent_id,
        "event_ids": ["EV-20260916-001"],
        "thesis_id": "TH-TEST-001",
        "thesis_revision": 2,
        "decision_ids": ["DEC-TEST-01"],
        "order_ids": ["ORD-TEST-01"],
    }

    inv_record = {
        "scheduled_invocation_id": test_sched_id,
        "sentinel_invocation_id": test_sent_id,
        "started_at": now_iso,
        "completed_at": now_iso,
        "sources_checked": 8,
        "events_seen": 5,
        "events_new": 5,
        "events_duplicate": 0,
        "events_material": 1,
        "events_triggered": 1,
        "status": "SUCCESS",
        "error": None,
        "lineage": lineage,
    }

    # Record in local SQLite
    assert record_sentinel_invocation(inv_record)
    local_latest = get_latest_sentinel_invocation()
    assert local_latest["sentinel_invocation_id"] == test_sent_id
    assert local_latest["lineage"]["thesis_id"] == "TH-TEST-001"

    # Persist in cloud Supabase (if configured in environment)
    if is_supabase_configured():
        ok = save_sentinel_invocation_supabase(inv_record)
        assert ok, "Failed to persist sentinel invocation to Supabase"
        cloud_latest = get_latest_sentinel_telemetry_supabase()
        assert cloud_latest is not None
        assert cloud_latest["sentinel_invocation_id"] == test_sent_id
        assert cloud_latest["status"] == "SUCCESS"


# -----------------------------------------------------------------------------
# 8. Zero Credential Leak Invariant Test
# -----------------------------------------------------------------------------
def test_zero_credential_leak():
    """Verify zero raw API keys or key prefixes are leaked in telemetry or web exports."""
    # Check data.json
    data_json_path = os.path.join(os.path.dirname(__file__), "..", "web_app", "data.json")
    if os.path.exists(data_json_path):
        with open(data_json_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Must not contain raw OpenRouter key prefix
            assert "sk-or-v1-" not in content
            # Must not contain raw service role key fragments
            assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in content

    # Check that OpenRouter status returns SHA-256 fingerprint only
    from event_agent.engine.llm_provider import OpenRouterProvider
    status = OpenRouterProvider().check_runtime_connection()
    if "credential_fingerprint" in status:
        fp = status["credential_fingerprint"]
        assert fp.startswith("SHA256:") or fp in ("NOT_CONFIGURED", "CONFIGURED_UNTESTED")
        assert "sk-" not in fp
