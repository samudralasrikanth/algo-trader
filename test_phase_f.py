# =============================================================================
# test_phase_f.py — Test Suite for Phase F: Research Layer & Walk-Forward
# =============================================================================

import sys
from datetime import datetime

# 1. Statistical Factor Evaluation Tests
print("--- Testing 1: Statistical Factor Evaluation ---")
from event_agent.research.factor_evaluation import evaluate_factor, FactorEvaluator

# Case A: Low win rate (40%) but large winners (+3.0%) vs small losers (-1.0%)
# Expectancy = (0.4 * 3.0) - (0.6 * 1.0) = 1.2 - 0.6 = +0.60% (Positive Expectancy!)
obs_skewed = (
    [{"actual_impact_pct": 3.0} for _ in range(8)] +
    [{"actual_impact_pct": -1.0} for _ in range(12)]
)
res_skewed = evaluate_factor("skewed_factor", "RISK_ON", obs_skewed)
assert res_skewed["hit_rate"] == 0.40
assert res_skewed["expectancy"] > 0, "Factor must have positive expectancy despite 40% hit rate"
assert res_skewed["profit_factor"] == 2.0  # 24.0 / 12.0 = 2.0
assert "t_statistic" in res_skewed
assert "confidence_interval_95" in res_skewed

# Evaluator accumulator
evaluator = FactorEvaluator()
evaluator.record_observation("sentiment", "EXPANSION", 1.0, 1.2)
evaluator.record_observation("sentiment", "EXPANSION", 1.0, 0.8)
evaluator.record_observation("sentiment", "EXPANSION", 1.0, -0.2)
summary = evaluator.get_summary()
assert len(summary) == 1
assert summary[0]["sample_count"] == 3

print("✅ Statistical factor evaluation & expectancy metrics passed.")

# 2. Walk-Forward Validation & Learning Loop Kill Switch Tests
print("\n--- Testing 2: Walk-Forward Validation & Learning Loop Kill Switch ---")
from event_agent.research.walk_forward import WalkForwardValidator, LearningLoop, PointInTimeError

wfv = WalkForwardValidator()

# Test Point-in-Time check (Look-Ahead Guard)
valid_features = [{"name": "CPI", "release_date": "2026-09-08T12:00:00Z"}]
assert wfv.verify_point_in_time_availability(valid_features, "2026-09-09T08:00:00Z") is True

invalid_features = [{"name": "CPI", "release_date": "2026-09-09T14:00:00Z"}]
try:
    wfv.verify_point_in_time_availability(invalid_features, "2026-09-09T08:00:00Z")
    assert False, "Must raise PointInTimeError on forward-looking data"
except PointInTimeError as e:
    assert "Point-in-time violation" in str(e)

# Learning loop approval gate test
ll = LearningLoop(validator=wfv)
curr_weights = {"risk": {"vix_weight": 0.4, "fii_weight": 0.3}}
cand_weights = ll.propose_weight_update([{"factor": "vix_weight", "expectancy": 0.35}], curr_weights)
assert cand_weights["risk"]["vix_weight"] == 0.45, "Candidate weight should adjust upwards"

# Check approval gate with insufficient observations (< 30)
fail_eval, fail_reason, checks = ll.evaluate_approval_criteria(
    candidate_results={"observations_count": 20, "mean_return_pct": 1.2, "max_drawdown_pct": -4.0},
    current_results={"observations_count": 20, "mean_return_pct": 0.8, "max_drawdown_pct": -3.5},
)
assert fail_eval is False
assert "min_30_observations" in fail_reason

# Check approval gate passing all criteria
pass_eval, pass_reason, checks_pass = ll.evaluate_approval_criteria(
    candidate_results={"observations_count": 45, "mean_return_pct": 1.4, "max_drawdown_pct": -4.0},
    current_results={"observations_count": 45, "mean_return_pct": 0.8, "max_drawdown_pct": -3.5},
)
assert pass_eval is True
assert "All approval criteria met" in pass_reason

print("✅ Walk-forward validation, look-ahead detection & approval gate passed.")

# 3. Point-in-Time Quantitative Backtester Tests
print("\n--- Testing 3: Point-in-Time Backtester ---")
from event_agent.research.backtester import BacktestEngine
from event_agent.broker.execution_simulator import Candle5M

backtester = BacktestEngine(initial_capital=10_00_000.0, risk_per_trade_pct=0.5)

mock_hist_preds = [
    {
        "prediction_id": "BT-001",
        "symbol": "RELIANCE.NS",
        "action": "BUY",
        "entry_price": 1287.0,
        "target_price": 1315.0,
        "stop_loss": 1261.26,
        "timestamp": "2026-09-08T09:15:00Z",
        "features_provenance": [{"name": "NEWS", "release_date": "2026-09-08T08:00:00Z"}],
    },
    {
        "prediction_id": "BT-002",
        "symbol": "TCS.NS",
        "action": "BUY",
        "entry_price": 4100.0,
        "target_price": 4180.0,
        "stop_loss": 4020.0,
        "timestamp": "2026-09-08T09:15:00Z",
        "features_provenance": [{"name": "EVENTS", "release_date": "2026-09-08T08:00:00Z"}],
    },
]

mock_candles_map = {
    "BT-001": [
        Candle5M("09:15", 1287.0, 1290.0, 1285.0, 1288.0),
        Candle5M("09:20", 1288.0, 1320.0, 1286.0, 1318.0), # Hits target 1315
    ],
    "BT-002": [
        Candle5M("09:15", 4100.0, 4110.0, 4090.0, 4095.0),
        Candle5M("09:20", 4095.0, 4100.0, 4010.0, 4015.0), # Hits stop 4020
    ],
}

bt_results = backtester.run_backtest(mock_hist_preds, mock_candles_map)
assert bt_results["total_trades"] == 2
assert "total_net_pnl" in bt_results
assert "total_friction_costs" in bt_results
assert "sharpe_ratio" in bt_results
assert "max_drawdown_pct" in bt_results
assert bt_results["win_rate_pct"] == 50.0  # 1 win, 1 loss

print(f"✅ Point-in-time backtester passed. 2 trades simulated, Net P&L: ₹{bt_results['total_net_pnl']:.2f}, Friction: ₹{bt_results['total_friction_costs']:.2f}")
print("\n🎉 ALL PHASE F TESTS PASSED SUCCESSFULLY! (3/3 test groups)")
