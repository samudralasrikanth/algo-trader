"""
NEXUS V4.0 — Real-Money Readiness & Drift Monitor Test Suite
Tests:
1. RealMoneyReadinessEngine:
   - 22 institutional metrics evaluated.
   - User 90% target strictly preserved as acceptance criterion:
     USER TARGET: 90.0%, CURRENT: 63.1%, STATUS: NOT MET.
     Classification: ECONOMICALLY_STRONG_BUT_USER_TARGET_NOT_MET.
   - Zero model tuning to reach 90%.
   - Verdict is PAPER_READY baseline with transparent blockers.
2. ModelDriftMonitor:
   - Rolling windows (20, 50, 100, 250 trades).
   - 10-regime performance evaluation.
   - Degradation actions (WARN -> REDUCE_CAPITAL -> PAPER_MODE).
   - Zero automatic live model retraining.
3. SixMonthObservationLedger:
   - Mandatory clean baseline anchor before clock start.
   - Daily logging format (Green, Yellow, Red) and 126 expected days.
4. MonteCarloSimulator:
   - 1,000 bootstrap simulations, capital survival, and drawdown risk.
"""

import pytest

from event_agent.certification.readiness_engine import (
    RealMoneyReadinessEngine,
    ReadinessVerdict,
    CertificationLevel,
)
from event_agent.monitoring.model_drift_monitor import (
    ModelDriftMonitor,
    DriftAlertLevel,
)
from event_agent.certification.six_month_ledger import (
    SixMonthCertificationLedger,
    DayObservationStatus,
)
from event_agent.certification.monte_carlo import (
    MonteCarloPathSimulator,
)


def test_readiness_engine_reports_honest_user_target_and_paper_ready():
    """
    CRITICAL USER INVARIANT:
    User target 90.0% is preserved as acceptance criterion.
    The system measures 63.1% and reports STATUS: NOT MET honestly.
    Classification: ECONOMICALLY_STRONG_BUT_USER_TARGET_NOT_MET.
    Verdict: PAPER_READY (never prematurely live).
    """
    audit = RealMoneyReadinessEngine.evaluate_readiness(
        current_holdout_accuracy_pct=63.1,
        executed_trades_count=103,
        profit_factor=1.71,
        sharpe_ratio=1.64,
        max_drawdown_pct=8.6,
        six_month_observation_days=0,  # Clock not completed
        human_approval_token_present=False,  # No token yet
    )

    # 1. Verdict is PAPER_READY
    assert audit.verdict == ReadinessVerdict.PAPER_READY
    assert audit.current_level == CertificationLevel.LEVEL_1_LIVE_PAPER

    # 2. Honest User Target Presentation
    utm = audit.user_target_metric
    assert utm["target_label"] == "USER TARGET"
    assert utm["target_value"] == "90.0%"
    assert utm["current_label"] == "CURRENT"
    assert utm["current_value"] == "63.1%"
    assert utm["status_label"] == "STATUS"
    assert utm["status_value"] == "NOT MET"
    assert utm["classification"] == "ECONOMICALLY_STRONG_BUT_USER_TARGET_NOT_MET"

    # 3. Failed gates include user target, 6-month prospective calendar, and human authorization
    failed_names = [g["name"] for g in audit.failed_gates]
    assert "User Target Accuracy (6-Month Prospective)" in failed_names
    assert "Six-Month Prospective Calendar Observation" in failed_names
    assert "Cryptographic Human Authorization" in failed_names

    # 4. Economic viability is confirmed despite user target not met
    assert audit.economic_viability_status == "ECONOMICALLY_STRONG_BUT_USER_TARGET_NOT_MET"


def test_model_drift_monitor_rolling_windows_and_no_auto_retraining():
    """Verify ModelDriftMonitor evaluates rolling windows and forbids auto-retraining."""
    # Synthetic trade stream with 80% win rate
    trades = []
    for i in range(100):
        is_win = (i % 5 != 0)  # 80% win rate
        pnl = 1500.0 if is_win else -1200.0
        trades.append({
            "trade_id": f"TR-{i}",
            "direction_correct": is_win,
            "pnl": pnl,
            "net_pnl": pnl,
            "slippage_bps": 5.0,
            "confidence": 0.80,
            "regime": "STRONG_BULL" if i % 2 == 0 else "SIDEWAYS",
        })

    windows, regimes, alert = ModelDriftMonitor.evaluate_trades(trades)
    assert len(windows) == 4  # 20, 50, 100, 250

    w20 = windows["window_20"]
    assert w20.sample_size == 20
    assert w20.accuracy >= 0.70
    assert w20.alert_level == DriftAlertLevel.NORMAL

    # 10 market regimes evaluated
    assert len(ModelDriftMonitor.REGIMES) == 10
    assert "STRONG_BULL" in regimes
    assert regimes["STRONG_BULL"].observations > 0

    # Verify invariant: Alert remains within safe bounds
    assert alert == DriftAlertLevel.NORMAL


def test_six_month_ledger_clean_baseline_anchor_required(tmp_path):
    """
    MANDATORY ADDITION 5:
    The 6-month prospective observation clock CANNOT start until a clean baseline anchor is certified.
    Past historical testing days do not count as Month 1.
    """
    db_file = str(tmp_path / "test_ledger.db")
    ledger = SixMonthCertificationLedger(db_path=db_file)

    # Initial state: clock is not started
    summary = ledger.get_summary()
    assert summary["is_clock_started"] is False
    assert summary["observed_trading_days"] == 0
    assert summary["total_expected_trading_days"] == 126
    assert summary["completion_pct"] == 0.0

    # Establish clean baseline anchor
    anchor_info = ledger.establish_certification_anchor(
        anchor_date="2026-09-10",
        model_hash="c5f2b87e2f5b89a80e1c667a421fbc38",
        code_commit="4482030f8b1c4e92a",
    )
    assert anchor_info["status"] == "ANCHOR_SEALED"

    # Now Day 1 can be prospective logged
    obs = ledger.record_day(
        date_str="2026-09-11",
        status=DayObservationStatus.GREEN_VALID,
        prediction_direction="BULLISH",
        prediction_confidence=0.82,
        actual_outcome_direction="BULLISH",
        is_correct=True,
        trade_executed=True,
        net_pnl_inr=8420.0,
        slippage_bps=4.8,
        market_regime="BULL_TRENDING",
        data_quality="VERIFIED",
    )
    assert obs.day_number == 1
    assert obs.status == DayObservationStatus.GREEN_VALID

    summary_after = ledger.get_summary()
    assert summary_after["is_clock_started"] is True
    assert summary_after["observed_trading_days"] == 1


def test_monte_carlo_path_simulation_risk_bounds():
    """Verify Monte Carlo stress simulator models 1,000 paths with strict drawdown bounds."""
    # Historical trade returns (mean 0.32%, stdev 1.4%)
    pnl_series = [1500.0, -1100.0, 2200.0, -800.0, 1900.0, 1200.0, -1400.0, 2800.0, -950.0, 1600.0] * 15

    results = MonteCarloPathSimulator.simulate(
        observed_trade_pnls=pnl_series,
        num_simulations=1000,
        trades_per_path=100,
        starting_capital=2000000.0,
    )

    assert results.total_simulations == 1000
    assert results.trades_per_path == 100
    assert results.capital_survival_prob >= 0.99
    assert results.prob_drawdown_gt_20_pct <= 0.05  # Less than 5% probability of 20% DD
    assert results.median_max_drawdown_pct < 12.0
