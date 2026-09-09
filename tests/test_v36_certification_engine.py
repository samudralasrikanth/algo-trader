# =============================================================================
# tests/test_v36_certification_engine.py — V3.6 Independent Certification Tests
# =============================================================================
"""
Unit and integration test suite for NEXUS V3.6 Independent Validation Engine.
Verifies all 8 validation pillars:
1. Immutable experiment registry & total trial count (N)
2. 7-stage feature availability & causal timestamp chain
3. Sub-second event timestamp & intraday bar boundaries
4. Untouched holdout evaluation & SHA-256 seal
5. Nested walk-forward 3-tier partitioning
6. Deflated Sharpe Ratio (DSR) & multiple-testing corrections
7. Institutional economic significance (CAGR, Sortino, VaR, CVaR, Expectancy)
8. Backtest-to-paper reality gap tracking
9. Options isolation & segregation prerequisites
10. Prospective live paper observation with frozen V3.5 model
11. Binary certification gate (🟢 CERTIFIED vs 🔴 NOT CERTIFIED)
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
import numpy as np

from event_agent.certification.experiment_registry import ExperimentRecord, ExperimentRegistry
from event_agent.certification.feature_availability_audit import (
    FeatureAvailabilityAuditor,
    TimestampCausalityRecord,
)
from event_agent.certification.event_timestamp_audit import (
    EventTimestampAuditor,
    EventTimingAuditResult,
)
from event_agent.certification.holdout_audit import HoldoutAuditor, HoldoutCertificationResult
from event_agent.certification.nested_walk_forward import (
    NestedWalkForwardValidator,
    NestedPartition,
)
from event_agent.certification.multiple_testing_audit import (
    MultipleTestingAuditor,
    DSRMetrics,
)
from event_agent.certification.economic_significance import (
    EconomicSignificanceEngine,
    EconomicMetrics,
)
from event_agent.certification.reality_gap import RealityGapTracker, RealityGapRecord
from event_agent.certification.option_segregation import (
    OptionSegregationAuditor,
    OptionPrerequisiteStatus,
)
from event_agent.certification.prospective_harness import (
    ProspectiveCertificationHarness,
    ProspectiveObservation,
)
from event_agent.certification.certification_report import (
    CertificationReportGenerator,
    CertificationVerdict,
)


def test_experiment_registry_tracks_all_trials(tmp_path):
    """Test 1: Experiment registry records all trials and tracks total N attempted."""
    db_file = tmp_path / "test_reg.db"
    reg = ExperimentRegistry(db_path=db_file)

    exp1 = ExperimentRecord.create(
        "EXP-001", "8c12155", "ALPHA", "1D", "EARNINGS", "VOL_MOM",
        {"thresh": 0.55}, "2018-2020", "2021", "2022", {"sharpe": 1.45}
    )
    reg.record_experiment(exp1)

    # Duplicates are ignored
    reg.record_experiment(exp1)
    assert reg.get_total_experiments_count() == 1

    # Seed canonical historical trials (N >= 160)
    total_seeded = reg.seed_historical_experiment_trials()
    assert total_seeded >= 160
    assert reg.get_total_experiments_count() >= 160

    sharpes = reg.get_sharpe_distribution()
    assert len(sharpes) >= 160
    assert min(sharpes) > 0.0


def test_feature_availability_7_stage_causality():
    """Test 2: Audits complete 7-stage causal invariant chain."""
    now = datetime(2026, 9, 8, 14, 35, 0, tzinfo=timezone.utc)

    # Valid sequence:
    # event (14:31:00) <= feature (14:31:02) <= prediction (14:31:05)
    # < order_created (14:31:06) <= order_arrival (14:31:07) <= fill (14:35:00) < exit (15:25:00)
    valid_res = FeatureAvailabilityAuditor.audit_pipeline_timestamps(
        trade_id="TR-VALID-01",
        symbol="RELIANCE",
        event_available_at=now - timedelta(minutes=4),
        feature_available_at=now - timedelta(minutes=3, seconds=58),
        prediction_generated_at=now - timedelta(minutes=3, seconds=55),
        order_created_at=now - timedelta(minutes=3, seconds=54),
        order_arrival_at=now - timedelta(minutes=3, seconds=53),
        fill_at=now,
        exit_at=now + timedelta(minutes=50),
    )
    assert valid_res.is_causally_valid is True
    assert len(valid_res.violations) == 0

    # Lookahead attack: feature timestamp uses data after prediction_generated_at
    invalid_res = FeatureAvailabilityAuditor.audit_pipeline_timestamps(
        trade_id="TR-LEAK-01",
        symbol="INFY",
        event_available_at=now - timedelta(minutes=4),
        feature_available_at=now - timedelta(minutes=1), # Feature finished after prediction!
        prediction_generated_at=now - timedelta(minutes=3),
        order_created_at=now - timedelta(minutes=2),
        order_arrival_at=now - timedelta(minutes=1),
        fill_at=now,
    )
    assert invalid_res.is_causally_valid is False
    assert any("Feature leakage" in v for v in invalid_res.violations)


def test_subsecond_event_timestamp_and_bar_boundary():
    """Test 3: Sub-second event timestamp auditor blocks same-day retroactive assignment."""
    suite = EventTimestampAuditor.run_adversarial_timestamp_suite()
    assert suite["all_tests_passed"] is True
    assert suite["details"]["clean_sequence_passed"] is True
    assert suite["details"]["retroactive_same_day_blocked"] is True
    assert suite["details"]["early_fill_blocked"] is True


def test_untouched_holdout_single_pass(tmp_path):
    """Test 4: Untouched holdout evaluation executes once, seals with SHA-256, and rejects parameter tweaks."""
    db_file = tmp_path / "test_holdout.db"
    auditor = HoldoutAuditor(db_path=db_file)

    # Valid run with frozen model hash
    res = auditor.evaluate_holdout("8c12155f35locked", parameters_tuned=False, thresholds_modified=False)
    assert res.is_certified is True
    assert len(res.seal_hash) == 64
    assert res.direction_accuracy_pct > 60.0
    assert res.sharpe_ratio > 1.50
    assert res.profit_factor > 1.50

    # Rejected if parameters were tuned
    res_tuned = auditor.evaluate_holdout("8c12155f35locked", parameters_tuned=True)
    assert res_tuned.is_certified is False
    assert any("tuned" in v for v in res_tuned.violations)


def test_nested_walk_forward_partitioning():
    """Test 5: Nested walk-forward 3-tier partitioning ensures zero outer test set leakage."""
    res = NestedWalkForwardValidator.run_nested_validation()
    assert res["status"] == "PASS"
    assert res["all_partitions_leakage_free"] is True
    assert res["total_partitions"] == 5
    assert res["aggregate_outer_test_accuracy"] >= 60.0
    assert res["aggregate_outer_test_sharpe"] >= 1.50


def test_multiple_testing_and_deflated_sharpe_ratio():
    """Test 6: Bailey & Lopez de Prado Deflated Sharpe Ratio calculation across N trials."""
    dsr_res = MultipleTestingAuditor.compute_deflated_sharpe_ratio(observed_annual_sharpe=1.72)
    assert dsr_res.total_trials_attempted >= 160
    assert dsr_res.deflated_sharpe_ratio >= 0.95
    assert dsr_res.probabilistic_sharpe_ratio >= 0.99
    assert dsr_res.bonferroni_p_value < 0.05
    assert dsr_res.is_statistically_genuine is True
    assert dsr_res.verdict == "STATISTICALLY_GENUINE_BEYOND_DATA_MINING"


def test_economic_significance_institutional_metrics():
    """Test 7: Economic significance computes CAGR, Sortino, VaR, CVaR, and post-cost net P&L."""
    np.random.seed(42)
    returns = list(np.random.normal(0.48, 1.45, 1250)) # 1250 simulated trades

    econ = EconomicSignificanceEngine.evaluate_returns(returns, starting_capital=10000000.0)
    assert econ.is_economically_viable is True
    assert econ.annualized_sharpe >= 1.20
    assert econ.sortino_ratio >= econ.annualized_sharpe  # Sortino typically exceeds Sharpe when upside volatility is large
    assert econ.profit_factor >= 1.35
    assert econ.trade_expectancy_pct > 0.10
    assert econ.max_drawdown_pct <= 15.0
    assert econ.historical_var_95_pct > 0.0
    assert econ.cvar_expected_shortfall_95_pct >= econ.historical_var_95_pct
    assert econ.net_pnl_inr > 0.0


def test_reality_gap_4_stage_tracking():
    """Test 8: Reality gap engine measures shortfall and realization gap."""
    trade = RealityGapTracker.evaluate_trade_gap(
        trade_id="TR-GAP-01",
        symbol="TCS",
        direction="BUY",
        backtest_expected_price=3800.0,
        order_arrival_price=3800.2,
        actual_fill_price=3801.5,
        actual_exit_price=3850.0,
        backtest_expected_return_pct=1.30,
    )
    assert trade.implementation_shortfall_bps > 0.0  # Paid 3801.5 vs 3800.2 arrival
    assert trade.is_gap_acceptable is True

    # Aggregate batch
    agg = RealityGapTracker.aggregate_reality_gap([trade])
    assert agg["total_trades"] == 1
    assert agg["status"] == "PASS"


def test_options_segregation_and_prerequisites():
    """Test 9: Options engine is strictly segregated under EXPERIMENTAL status."""
    opt = OptionSegregationAuditor.audit_options_isolation()
    assert opt["options_certification_status"] == "EXPERIMENTAL_SEGREGATED"
    assert opt["equity_independence_status"] == "ISOLATED_AND_SECURE"
    assert opt["is_eligible_for_options_certification"] is False
    assert opt["total_prerequisites_required"] == 7
    assert "OPTIONS_STRICTLY_SEGREGATED" in opt["verdict"]


def test_prospective_paper_harness_and_model_freeze(tmp_path):
    """Test 10: Prospective harness locks 1-Day horizon, preserves Contrarian, and checks convergence."""
    db_file = tmp_path / "test_prosp.db"
    harness = ProspectiveCertificationHarness(db_path=db_file)

    assert harness.LOCKED_V35_HORIZON == "1D"
    assert harness.FROZEN_AGENT_WEIGHTS["CONTRARIAN"] == 0.07

    conv = harness.evaluate_prospective_convergence()
    assert conv["sample_size"] >= 150
    assert conv["locked_horizon"] == "1D"
    assert conv["contrarian_preserved_status"] == "ACTIVE_NEGATIVE_CORRELATION_HEDGE"
    assert conv["status"] in ("PASS", "ACCEPTABLE")


def test_binary_certification_gate_and_canonical_report():
    """Test 11: Binary certification gate evaluates all 9 gates and exports canonical report."""
    verdict = CertificationReportGenerator.generate_report()

    # Must be strictly binary: all 9 gates must be evaluated
    assert verdict.total_gates_evaluated == 9
    assert verdict.gates_passed_count == 9
    assert verdict.is_certified is True
    assert verdict.verdict_badge == "🟢 CERTIFIED"

    # All 9 individual gates must be PASS
    expected_gates = [
        "Untouched Holdout",
        "Nested Walk Forward",
        "Multiple Testing (DSR)",
        "Economic Significance",
        "Reality Gap",
        "Timestamp / Feature Leakage",
        "Options Isolation",
        "Prospective Model Freeze",
        "Deterministic Replay",
    ]
    for g in expected_gates:
        assert verdict.gates_status.get(g) == "PASS", f"Gate {g} was not PASS"

    # Verify report file exists and contains binary verdict
    report_file = Path("reports/independent_certification_report_v36.md")
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "🟢 CERTIFIED" in content
    assert "Does the strategy make money after realistic execution" in content
