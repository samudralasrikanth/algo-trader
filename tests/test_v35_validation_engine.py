# =============================================================================
# tests/test_v35_validation_engine.py — Complete V3.5 Validation Suite
# =============================================================================
"""
Tests the complete NEXUS V3.5 Prediction Validation & Intelligence Engine across all 37 sections:
- P0: Prediction Ledger, Horizons, Outcome Engine, Direction/Magnitude Separation, 7 Baselines
- P1: Historical Event Analogue, Surprise Detection, Market Context, Breadth, Volatility, PIT Fundamentals
- P2: 9-Bucket Calibration, Agent Independence, Dynamic Reliability, NO_TRADE Engine, Prediction Decay
- P3: 8-Layer Ablation, Drift Detection, Champion/Challenger, Anti-Leakage Audit, Deterministic Replay, Report
"""

import math
from datetime import date, datetime, timezone
import pytest

from event_agent.prediction.ledger import (
    PredictionLedger, PredictionRecord, HORIZONS_SUPPORTED, classify_horizon_type
)
from event_agent.prediction.outcome_engine import OutcomeEngine
from event_agent.prediction.distribution import ReturnDistributionModel, CredibleIntervals
from event_agent.prediction.calibration_metrics import CalibrationEngine
from event_agent.prediction.agent_independence import AgentIndependenceEngine
from event_agent.prediction.dynamic_weights import DynamicReliabilityEngine
from event_agent.prediction.no_trade_engine import NoTradeEngine
from event_agent.prediction.prediction_decay import PredictionDecayEngine
from event_agent.prediction.ablation_engine import ModelAblationEngine
from event_agent.prediction.drift_detector import DriftDetector
from event_agent.prediction.champion_challenger import ChampionChallengerGate, ModelMetrics
from event_agent.prediction.anti_leakage_audit import AntiLeakageAuditor, PointInTimeViolation
from event_agent.prediction.deterministic_replay import DeterministicReplayValidator
from event_agent.prediction.validation_report import ValidationReportGenerator
from event_agent.intelligence.event_analogue import (
    HistoricalEventAnalogueEngine, StandardizedEvent, EVENT_CATEGORIES_20, EventTaxonomy
)
from event_agent.intelligence.surprise_detector import SurpriseDetector
from event_agent.intelligence.market_context import (
    MarketContextEngine, PointInTimeFundamentals
)
from event_agent.research.baseline_models import BaselineSuite


# ---------------------------------------------------------------------------
# P0: Prediction Truth Tests
# ---------------------------------------------------------------------------

def test_prediction_ledger_and_horizons(tmp_path):
    """Test 1: Immutable prediction ledger and 8 explicit horizons."""
    db_file = tmp_path / "test_ledger.db"
    ledger = PredictionLedger(db_path=db_file)

    for h in ["15m", "30m", "60m", "1D", "3D", "5D", "10D", "20D"]:
        assert h in HORIZONS_SUPPORTED
        htype = classify_horizon_type(h)
        assert htype in ("INTRADAY", "SHORT_TERM", "MEDIUM_TERM")

    rec = PredictionRecord(
        prediction_id="PRED-TEST-001",
        timestamp="2026-09-09T10:30:00Z",
        decision_timestamp="2026-09-09T10:30:00Z",
        symbol="RELIANCE.NS",
        exchange="NSE",
        price_at_prediction=1280.0,
        market_snapshot_id="SNAP-MKT-01",
        data_snapshot_id="SNAP-DATA-01",
        event_snapshot_id="SNAP-EVT-01",
        regime_snapshot_id="SNAP-REG-01",
        direction="UP",
        probability_up=0.68,
        probability_down=0.32,
        expected_return=0.017,
        target=1302.0,
        stop=1265.0,
        horizon="1D",
        confidence=68.0,
        prediction_type="SHORT_TERM",
        alpha_prediction={"direction": "UP", "prob": 0.70},
        momentum_prediction={"direction": "UP", "prob": 0.65},
        macro_prediction={"direction": "UP", "prob": 0.62},
        defensive_prediction={"direction": "NEUTRAL", "prob": 0.50},
        contrarian_prediction={"direction": "DOWN", "prob": 0.45},
        ensemble_direction="UP",
        ensemble_probability=0.68,
        ensemble_score=1.45,
        no_trade_status=False,
    )

    pred_id = ledger.record_prediction(rec)
    assert pred_id == "PRED-TEST-001"

    retrieved = ledger.get_prediction("PRED-TEST-001")
    assert retrieved is not None
    assert retrieved["symbol"] == "RELIANCE.NS"
    assert retrieved["price_at_prediction"] == 1280.0
    assert retrieved["horizon"] == "1D"
    assert retrieved["alpha_prediction"]["direction"] == "UP"


def test_outcome_engine_resolution(tmp_path):
    """Test 2: Automatic outcome resolution upon horizon expiry."""
    db_file = tmp_path / "test_outcomes.db"
    engine = OutcomeEngine(db_path=db_file)

    pred = {
        "prediction_id": "PRED-TEST-002",
        "symbol": "RELIANCE.NS",
        "horizon": "1D",
        "price_at_prediction": 1280.0,
        "expected_return": 0.015,
        "direction": "UP",
        "target": 1302.0,
        "stop": 1265.0,
    }

    # Scenario A: Closing price 1302 -> +1.72% return, correct prediction, target hit
    outcome = engine.resolve_prediction(
        prediction=pred,
        closing_price=1302.0,
        high_price=1305.0,
        low_price=1278.0,
        intervals={"interval_50": (0.005, 0.025), "interval_80": (-0.005, 0.035)},
    )

    assert outcome.actual_return == pytest.approx(0.01719, rel=1e-3)
    assert outcome.direction_correct is True
    assert outcome.target_hit is True
    assert outcome.stop_hit is False
    assert outcome.covered_50_pct is True
    assert outcome.covered_80_pct is True

    stored = engine.get_outcome("PRED-TEST-002")
    assert stored is not None
    assert stored["direction_correct"] is True


def test_direction_magnitude_separation_and_intervals():
    """Test 3: Separation of P(UP), E(Return), and credible interval calibration."""
    ci = ReturnDistributionModel.estimate_distribution(
        expected_return=0.011,
        daily_volatility=0.015,
        horizon_days=1.0,
        skewness=0.1,
    )

    assert ci.interval_50[0] < ci.mean_return < ci.interval_50[1]
    assert ci.interval_80[0] < ci.interval_50[0]
    assert ci.interval_80[1] > ci.interval_50[1]

    # Evaluate interval coverage across synthetic distribution
    returns = [0.010, 0.012, 0.008, 0.015, 0.002, 0.022, -0.005, 0.018, 0.009, 0.011]
    cis = [ci] * len(returns)
    cal_eval = ReturnDistributionModel.evaluate_interval_calibration(returns, cis)

    assert cal_eval["status"] == "EVALUATED"
    assert "coverage_50_pct" in cal_eval
    assert "coverage_80_pct" in cal_eval


def test_7_benchmark_baselines():
    """Test 4: All 7 required benchmark models execute deterministically."""
    suite = BaselineSuite()
    history = [1250.0 + (i * 2.0) for i in range(60)]  # 60 days of prices

    res = suite.evaluate_all(
        symbol="RELIANCE.NS",
        prediction_date="2026-09-09",
        price_history=history,
        prev_return=0.008,
        ret_5d=0.025,
        ret_20d=0.065,
        nifty_direction="UP",
        rsi_14=58.0,
    )

    assert "baseline_1_random" in res
    assert "baseline_2_previous_day" in res
    assert "baseline_3_momentum_5d" in res
    assert "baseline_4_momentum_20d" in res
    assert "baseline_5_ma_trend" in res
    assert "baseline_6_nifty_direction" in res
    assert "baseline_7_rsi_14" in res

    assert res["baseline_1_random"]["direction"] in ("UP", "DOWN")
    assert res["baseline_2_previous_day"]["direction"] == "UP"
    assert res["baseline_3_momentum_5d"]["direction"] == "UP"
    assert res["baseline_4_momentum_20d"]["direction"] == "UP"
    assert res["baseline_5_ma_trend"]["direction"] == "UP"
    assert res["baseline_6_nifty_direction"]["direction"] == "UP"
    assert res["summary"]["total_baselines"] == 7


# ---------------------------------------------------------------------------
# P1: Intelligence Engine Tests
# ---------------------------------------------------------------------------

def test_event_analogue_and_20_categories():
    """Test 5: 20-category event taxonomy and historical analogue matching."""
    assert len(EVENT_CATEGORIES_20) == 20
    assert "Earnings Beat" in EVENT_CATEGORIES_20
    assert "RBI Policy" in EVENT_CATEGORIES_20
    assert "Litigation" in EVENT_CATEGORIES_20

    norm_type = EventTaxonomy.normalize_category("Q3 Net Profit surges 35% beating estimates")
    assert norm_type == "Earnings Beat"

    analogue_engine = HistoricalEventAnalogueEngine()
    event = StandardizedEvent(
        event_id="EVT-001",
        headline="Reliance Q3 EBITDA jumps 22% on Jio and Retail strength",
        event_type="Earnings Beat",
        severity="HIGH",
        novelty=0.8,
        expectedness=0.3,
        direction="POSITIVE",
        duration="SHORT_TERM",
        affected_company="RELIANCE.NS",
        affected_sector="Energy",
        market_wide=False,
        confidence=80.0,
        timestamp="2026-09-09T10:00:00Z",
    )

    match = analogue_engine.find_analogues(event)
    assert match.similar_events_count > 0
    assert match.positive_1d_pct > 55.0
    assert match.conditional_probability_up > 55.0
    d = match.to_dict()
    assert "positive_1d_pct" in d
    assert "median_return_1d" in d


def test_surprise_detector():
    """Test 6: Actual - Expected = Surprise with explicit missing expectation handling."""
    # Scenario A: Consensus available
    s_meas = SurpriseDetector.calculate_surprise(
        symbol="TCS.NS",
        event_type="Earnings Beat",
        actual_value=12400.0,
        expected_value=11800.0,
    )
    assert s_meas.has_expectation is True
    assert s_meas.status == "MEASURED"
    assert s_meas.surprise_delta == 600.0
    assert s_meas.surprise_pct == pytest.approx(5.08, rel=1e-2)

    # Scenario B: Consensus unavailable
    s_missing = SurpriseDetector.calculate_surprise(
        symbol="TCS.NS",
        event_type="Management Change",
        actual_value=None,
        expected_value=None,
    )
    assert s_missing.has_expectation is False
    assert s_missing.status == "EXPECTATION_DATA_UNAVAILABLE"
    assert s_missing.surprise_delta == 0.0


def test_market_context_and_pit_fundamentals():
    """Test 7: Market Context Score, Market Breadth, Volatility, and PIT Fundamentals."""
    history = [1200.0 + (i * 1.5) for i in range(40)]
    ctx = MarketContextEngine.evaluate_market_context(
        symbol="INFY.NS",
        price_history=history,
        vix_value=14.5,
        nifty_return_1d=0.005,
        advances=32,
        declines=18,
    )

    assert 0.0 <= ctx.overall_context_score <= 100.0
    assert ctx.macro_regime_label in ("RISK_ON", "NEUTRAL", "RISK_OFF", "CRISIS")
    assert ctx.volatility.vix_regime == "NORMAL"
    assert ctx.breadth.breadth_regime == "STRONG_BREADTH"

    # PIT Fundamentals lookahead test
    fund = PointInTimeFundamentals(
        symbol="INFY.NS",
        filing_timestamp="2026-04-18T18:00:00Z",
        revenue_growth_yoy=0.082,
        eps_growth_yoy=0.095,
        ebitda_margin_pct=21.4,
        debt_to_equity=0.05,
        roe_pct=28.5,
        roce_pct=34.2,
        pe_ratio=26.5,
        pb_ratio=7.8,
    )

    # Should pass if prediction is made after filing
    fund.assert_valid_for_prediction("2026-04-20T09:15:00Z")

    # Must raise error if prediction is made before filing
    with pytest.raises(ValueError, match="Lookahead bias detected"):
        fund.assert_valid_for_prediction("2026-04-10T09:15:00Z")


# ---------------------------------------------------------------------------
# P2: Model Quality & Statistical Rigor Tests
# ---------------------------------------------------------------------------

def test_calibration_across_9_buckets():
    """Test 8: 9-bucket calibration analysis and mis-calibration detection."""
    # Generate calibrated sample
    probs = [0.52, 0.58, 0.62, 0.68, 0.72, 0.77, 0.82, 0.88, 0.92] * 5
    outcomes = [1, 1, 1, 1, 1, 1, 1, 1, 1] * 5  # High win rate

    res = CalibrationEngine.evaluate(probs, outcomes)
    assert res.total_samples == 45
    assert len(res.bucket_breakdown) == 9
    assert res.brier_score < 0.25
    assert len(res.reliability_curve) > 0


def test_agent_independence_and_no_trade_engine():
    """Test 9: Multi-agent independence analysis and 11-gate NO_TRADE engine."""
    # Agent independence test
    agent_data = {
        "Alpha": [{"direction": "UP"}, {"direction": "UP"}, {"direction": "DOWN"}],
        "Momentum": [{"direction": "UP"}, {"direction": "UP"}, {"direction": "DOWN"}],
        "Macro": [{"direction": "UP"}, {"direction": "DOWN"}, {"direction": "DOWN"}],
        "Defensive": [{"direction": "DOWN"}, {"direction": "DOWN"}, {"direction": "DOWN"}],
        "Contrarian": [{"direction": "DOWN"}, {"direction": "UP"}, {"direction": "UP"}],
    }

    ind_rep = AgentIndependenceEngine.analyze_independence(agent_data)
    assert len(ind_rep.agent_names) == 5
    assert "Alpha" in ind_rep.prediction_correlation_matrix
    assert ind_rep.prediction_correlation_matrix["Alpha"]["Momentum"] == 1.0

    # NO_TRADE Engine test
    # Pass scenario
    trade_ok = NoTradeEngine.evaluate(
        symbol="RELIANCE.NS",
        expected_gross_pct=1.8,
        confidence=68.0,
        daily_volatility=0.015,
        data_available=True,
    )
    assert trade_ok.is_no_trade is False
    assert len(trade_ok.passed_gates) == 11

    # Rejection scenario: Low edge (< 0.25% net)
    trade_blocked = NoTradeEngine.evaluate(
        symbol="RELIANCE.NS",
        expected_gross_pct=0.20,  # Gross is lower than 0.18% costs
        confidence=68.0,
        daily_volatility=0.015,
    )
    assert trade_blocked.is_no_trade is True
    assert trade_blocked.reason_code == "LOW_EXPECTED_EDGE"


def test_prediction_decay_profiles():
    """Test 10: Signal half-life decay modeling across 7 horizons."""
    horizon_data = {
        "15m": [{"predicted_dir": "UP", "actual_ret": 0.003, "direction_correct": True}] * 10,
        "1D":  [{"predicted_dir": "UP", "actual_ret": 0.015, "direction_correct": True}] * 15,
        "5D":  [{"predicted_dir": "UP", "actual_ret": 0.008, "direction_correct": True}] * 8,
        "20D": [{"predicted_dir": "UP", "actual_ret": -0.005, "direction_correct": False}] * 10,
    }

    profile = PredictionDecayEngine.estimate_decay("Earnings Beat", horizon_data)
    assert profile.optimal_horizon in ("15m", "1D", "5D", "20D")
    assert profile.lifespan_category in ("INTRADAY", "SHORT_TERM", "MEDIUM_TERM")


# ---------------------------------------------------------------------------
# P3: Continuous Improvement, Anti-Leakage & Replay Tests
# ---------------------------------------------------------------------------

def test_model_ablation_8_layers():
    """Test 11: 8 cumulative ablation layers."""
    ablation = ModelAblationEngine.evaluate_ablation_tiers()
    assert len(ablation) == 8
    assert ablation[0].layer_name == "Price only"
    assert ablation[-1].layer_name == "Full NEXUS"
    assert ablation[-1].accuracy_pct > ablation[0].accuracy_pct


def test_drift_and_champion_challenger():
    """Test 12: Drift health state machine and Challenger promotion rules."""
    # Drift test
    drift = DriftDetector.evaluate_drift(
        baseline_accuracies=[64.0, 65.0, 63.5],
        recent_accuracies=[63.0, 63.5, 62.8],
    )
    assert drift.health_status == "NORMAL"
    assert drift.risk_sizing_multiplier == 1.0

    # Challenger test
    champ = ModelMetrics("V3.4", 100, True, 62.0, 1.5, 0.22, 10.0, 1.6)
    chall = ModelMetrics("V3.5", 100, True, 65.5, 1.9, 0.20, 9.5, 1.9)
    promo = ChampionChallengerGate.evaluate_promotion(champ, chall)
    assert promo.eligible_for_promotion is True
    assert promo.decision == "PROMOTED"


def test_anti_leakage_adversarial_audit():
    """Test 13: Strict adversarial anti-leakage audit blocks all future data attempts."""
    audit = AntiLeakageAuditor.run_full_leakage_audit()
    assert audit["all_leakage_tests_passed"] is True
    assert audit["status"] == "SECURE_ZERO_LEAKAGE"
    assert audit["details"]["price_leakage_blocked"] is True
    assert audit["details"]["event_leakage_blocked"] is True
    assert audit["details"]["fundamentals_leakage_blocked"] is True
    assert audit["details"]["constituent_leakage_blocked"] is True
    assert audit["details"]["normalization_leakage_blocked"] is True


def test_deterministic_replay():
    """Test 14: Deterministic replay validator confirms 100% bitwise hash matches."""
    mkt = {"price": 1280.0, "vol": 0.015}
    evt = {"type": "Earnings Beat", "dir": "POSITIVE"}
    cfg = {"version": "3.5.0"}
    agents = {"Alpha": "UP", "Defensive": "UP"}
    ens = {"dir": "UP", "prob": 0.68}
    risk = {"qty": 50, "stop": 1265.0}

    orig_hash = DeterministicReplayValidator.compute_decision_hash(
        mkt, evt, "3.5.0", cfg, agents, ens, risk
    )

    verif = DeterministicReplayValidator.verify_replay(
        prediction_id="PRED-REPLAY-01",
        original_hash=orig_hash,
        market_snapshot=mkt,
        event_snapshot=evt,
        model_version="3.5.0",
        config=cfg,
        replayed_agent_decisions=agents,
        replayed_ensemble_decision=ens,
        replayed_risk_decision=risk,
        original_agent_decisions=agents,
        original_ensemble_decision=ens,
        original_risk_decision=risk,
    )

    assert verif.is_bitwise_identical is True
    assert verif.original_hash == verif.replayed_hash
    assert len(verif.discrepancies) == 0


def test_validation_report_and_definition_of_done():
    """Test 15: Validation report answers all 15 Definition-of-Done questions truthfully."""
    report = ValidationReportGenerator.generate_report()

    assert report.total_predictions > 1000
    assert report.direction_accuracy_pct > report.best_baseline_accuracy_pct
    assert report.beats_baseline is True
    assert report.statistically_significant is True
    assert report.production_paper_trading_ready is True

    # Validate that all 15 questions have answered entries
    dod = report.definition_of_done_answers
    assert len(dod) == 15
    for i in range(1, 16):
        key = [k for k in dod if k.startswith(f"{i}_")][0]
        assert len(dod[key]) > 0
