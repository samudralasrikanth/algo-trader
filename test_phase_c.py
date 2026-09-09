# =============================================================================
# test_phase_c.py — Test Suite for Phase C: Prediction v3 + Baselines + Snapshots
# =============================================================================

import sys
import os
from datetime import datetime, timezone, date

# 1. Model Versioning & Governance Tests
print("--- Testing 1: Model Versioning & Approval Gate ---")
from event_agent.research.model_versioning import (
    VERSION_RECORD,
    ModelVersionManager,
    ApprovalGateError,
    get_current_version_record,
    get_model_version,
)

assert VERSION_RECORD["model_version"] == "3.0.0", "Model version must be 3.0.0"
assert VERSION_RECORD["feature_version"] == "F1", "Feature version must be F1"
assert VERSION_RECORD["regime_version"] == "R1", "Regime version must be R1"
assert VERSION_RECORD["calibration_version"] == "C1", "Calibration version must be C1"
assert VERSION_RECORD["weights_version"] == "W1.0", "Weights version must be W1.0"
assert "data_snapshot_id" in VERSION_RECORD, "data_snapshot_id must be in VERSION_RECORD"

assert get_model_version() == "3.0.0", "get_model_version() must return 3.0.0"
assert ModelVersionManager.is_learning_loop_auto_update_allowed() is False, "Kill switch must block auto-updates"

# Test proposal & approval gate
proposal_id = ModelVersionManager.propose_candidate_version(
    candidate_weights={"risk": {"vix_weight": 0.45}},
    oos_validation_results={"sharpe": 1.45, "p_value": 0.02},
    proposer="TEST_RUNNER",
    description="Test candidate with higher vix weight",
)
assert proposal_id.startswith("PROP-"), "Proposal ID must start with PROP-"

# Automated or empty approval must be rejected
try:
    ModelVersionManager.approve_candidate_version(
        proposal_id=proposal_id,
        approver_token="",
        approved_by="LEARNING_LOOP",
    )
    assert False, "Should have raised ApprovalGateError"
except ApprovalGateError:
    pass

print("✅ Model versioning, immutability & approval gate passed.")

# 2. 5 Benchmark Baselines Tests
print("\n--- Testing 2: 5 Benchmark Baselines ---")
from event_agent.research.baseline_models import (
    RandomBaseline,
    PreviousDayBaseline,
    MomentumBaseline,
    MeanReversionBaseline,
    BuyAndHoldBaseline,
    BaselineSuite,
)

# Baseline 0: Deterministic SHA-256 Random
b0 = RandomBaseline()
pred1 = b0.predict("RELIANCE.NS", "2026-09-09")
pred2 = b0.predict("RELIANCE.NS", "2026-09-09")
assert pred1["seed"] == pred2["seed"], "Seeds must match for same symbol & date"
assert pred1["direction"] == pred2["direction"], "Direction must be strictly deterministic across calls"

pred_diff_date = b0.predict("RELIANCE.NS", "2026-09-10")
assert "seed" in pred_diff_date, "Seed must be present"

# Baseline 1: Previous Day
b1 = PreviousDayBaseline()
res_up = b1.predict("TCS.NS", prev_return=0.015)
assert res_up["direction"] == "UP", "Positive return must predict UP"
res_down = b1.predict("TCS.NS", prev_return=-0.012)
assert res_down["direction"] == "DOWN", "Negative return must predict DOWN"

# Baseline 2: Momentum 5D
b2 = MomentumBaseline()
res_mom_up = b2.predict("INFY.NS", ret_5d=0.03)
assert res_mom_up["direction"] == "UP", "Positive 5d return must predict UP"
res_mom_down = b2.predict("INFY.NS", ret_5d=-0.02)
assert res_mom_down["direction"] == "DOWN", "Negative 5d return must predict DOWN"

# Baseline 3: Mean Reversion
b3 = MeanReversionBaseline()
res_overbought = b3.predict("SBIN.NS", ret_5d=0.035)  # > +2%
assert res_overbought["direction"] == "DOWN", "Overbought (>2%) must trigger mean reversion DOWN"
res_oversold = b3.predict("SBIN.NS", ret_5d=-0.035)    # < -2%
assert res_oversold["direction"] == "UP", "Oversold (<-2%) must trigger mean reversion UP"

# Baseline 4: Buy and Hold
b4 = BuyAndHoldBaseline()
res_bh = b4.predict("HDFCBANK.NS")
assert res_bh["direction"] == "UP" and res_bh["action"] == "BUY", "Buy and hold must always be LONG"
assert b4.get_return(100.0, 110.0) == 0.10, "Benchmark return must be +10%"

# Baseline Suite
suite = BaselineSuite()
all_baselines = suite.evaluate_all("RELIANCE.NS", "2026-09-09", price_history=[1250.0, 1260.0, 1270.0, 1280.0, 1287.0])
assert len(all_baselines) == 6, "Must contain 5 baselines + summary"
assert "random" in all_baselines
assert "previous_day" in all_baselines
assert "momentum_5d" in all_baselines
assert "mean_reversion" in all_baselines
assert "buy_and_hold" in all_baselines
print("✅ All 5 benchmark baselines passed.")

# 3. Calibration Engine Tests
print("\n--- Testing 3: Calibration Engine ---")
from event_agent.engine.calibration import (
    calibrate_confidence,
    compute_brier_score,
    compute_expected_calibration_error,
    is_confidence_miscalibration,
    CALIBRATION_VERSION,
)

assert CALIBRATION_VERSION == "C1"
cal_normal = calibrate_confidence(85.0, regime_state="NEUTRAL")
cal_crisis = calibrate_confidence(85.0, regime_state="CRISIS")
assert cal_crisis < cal_normal, f"Crisis regime must penalize confidence: crisis {cal_crisis} vs normal {cal_normal}"
assert 30.0 <= cal_normal <= 88.0, "Calibrated confidence must respect guardrails"

# Brier score test
bs_perfect = compute_brier_score([1.0, 0.0], [1, 0])
assert bs_perfect == 0.0, "Perfect predictions must yield Brier score 0.0"
bs_coinflip = compute_brier_score([0.5, 0.5], [1, 0])
assert bs_coinflip == 0.25, "50/50 predictions must yield Brier score 0.25"

# Expected Calibration Error
ece_res = compute_expected_calibration_error(
    probabilities=[0.9, 0.8, 0.7, 0.6, 0.5],
    outcomes=[1, 1, 1, 0, 0],
    n_bins=5,
)
assert "ece" in ece_res and "mce" in ece_res, "ECE result must include ece and mce"
assert ece_res["sample_size"] == 5

# Miscalibration check (F17)
assert is_confidence_miscalibration(78.0, trade_pnl=-500.0) is True, "High confidence loser must be flagged F17"
assert is_confidence_miscalibration(55.0, trade_pnl=-500.0) is False, "Low confidence loser should not be flagged F17"
assert is_confidence_miscalibration(80.0, trade_pnl=1200.0) is False, "High confidence winner should not be flagged F17"
print("✅ Calibration engine & F17 failure detection passed.")

# 4. Prediction Engine v3.0 Tests
print("\n--- Testing 4: Prediction Engine v3.0 Multi-Factor & Snapshot ---")
from event_agent.engine.prediction_algo import (
    generate_stock_prediction,
    fetch_stock_market_context,
    MODEL_VERSION,
    DEFAULT_PRICES,
)

assert MODEL_VERSION == "3.0.0"
assert DEFAULT_PRICES["RELIANCE.NS"] == 1287.0, "Post-bonus Reliance price must be 1287.0"

# Mock inputs for deterministic verification
mock_market_state = {
    "snapshot_timestamp": "2026-09-09T10:00:00+00:00",
    "volatility": {"india_vix": 14.5},
}
mock_regime = {
    "composite_regime": "RISK_ON",
    "composite_score": 0.45,
    "confidence": 75.0,
}
mock_features = {
    "momentum": {"nifty_return_5d": 0.015},
}
mock_surprises = [
    {
        "indicator": "US CPI",
        "raw_surprise": -0.1,
        "normalized_surprise_sigma": -0.8,
    }
]
mock_news = [
    {
        "title": "Reliance announces major green hydrogen order and strong telecom numbers",
        "source": "Economic Times",
        "pub_date": "2026-09-09T08:00:00+05:30",
        "url": "https://example.com/ril-news",
    }
]

pred = generate_stock_prediction(
    symbol="RELIANCE.NS",
    news_articles=mock_news,
    reference_date=date(2026, 9, 9),
    market_state=mock_market_state,
    regime=mock_regime,
    features=mock_features,
    surprises=mock_surprises,
    portfolio_capital=10_00_000.0,
    risk_per_trade_pct=0.5,
)

# Verify v3 outputs
assert pred["model_version"] == "3.0.0"
assert pred["symbol"] == "RELIANCE.NS"
assert pred["entry_price"] > 0, "Entry price must be positive"
assert pred["target_price"] > 0, "Target price must be positive"
assert pred["stop_loss"] > 0, "Stop loss must be positive"
assert pred["stop_distance"] > 0, "Stop distance must be positive"
assert pred["risk_per_trade_pct"] == 0.5, "Risk per trade must be 0.5%"
assert pred["suggested_quantity"] > 0, "Suggested quantity must be positive"
assert pred["suggested_position_value"] <= 100000.0, "Exposure must respect 10% portfolio cap"

# Check 5 baselines included
assert "baselines" in pred, "Baselines must be attached"
assert "random" in pred["baselines"]
assert "previous_day" in pred["baselines"]
assert "momentum_5d" in pred["baselines"]
assert "mean_reversion" in pred["baselines"]
assert "buy_and_hold" in pred["baselines"]

# Check Prediction Snapshot
snap = pred["prediction_snapshot"]
assert snap["model_version"] == "3.0.0"
assert snap["feature_version"] == "F1"
assert snap["regime_version"] == "R1"
assert snap["calibration_version"] == "C1"
assert snap["weights_version"] == "W1.0"
assert "market_state_json" in snap
assert "regime_json" in snap
assert "features_json" in snap
assert "surprises_json" in snap
assert "factor_weights_json" in snap
assert "prediction_json" in snap
assert "baselines_json" in snap
assert "snapshot_hash" in snap and len(snap["snapshot_hash"]) == 64

# Test Central Invariant (Strict Reproducibility)
pred_repeat = generate_stock_prediction(
    symbol="RELIANCE.NS",
    news_articles=mock_news,
    reference_date=date(2026, 9, 9),
    market_state=mock_market_state,
    regime=mock_regime,
    features=mock_features,
    surprises=mock_surprises,
    portfolio_capital=10_00_000.0,
    risk_per_trade_pct=0.5,
)

assert pred["entry_price"] == pred_repeat["entry_price"]
assert pred["target_price"] == pred_repeat["target_price"]
assert pred["stop_loss"] == pred_repeat["stop_loss"]
assert pred["suggested_quantity"] == pred_repeat["suggested_quantity"]
assert pred["expected_1d_pct"] == pred_repeat["expected_1d_pct"]
assert pred["baselines"]["random"]["direction"] == pred_repeat["baselines"]["random"]["direction"]

print("✅ Prediction Engine v3.0, risk-based sizing, 5 baselines & reproducibility invariant passed.")
print("\n🎉 ALL PHASE C TESTS PASSED SUCCESSFULLY! (4/4 test groups)")
