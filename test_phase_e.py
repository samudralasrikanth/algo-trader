# =============================================================================
# test_phase_e.py — Test Suite for Phase E: Forensic Audit & 18-Code Taxonomy
# =============================================================================

import sys

# 1. 18-Code Failure Taxonomy & Classifier Tests
print("--- Testing 1: 18-Code Failure Classifier ---")
from event_agent.audit.failure_classifier import FailureClassifier, FAILURE_TAXONOMY

assert len(FAILURE_TAXONOMY) == 18, f"Must have exactly 18 failure codes, found {len(FAILURE_TAXONOMY)}"
for code_num in range(1, 19):
    c_str = f"F{code_num:02d}"
    assert c_str in FAILURE_TAXONOMY, f"Missing failure code {c_str}"

fc = FailureClassifier()

# Test F17: High confidence failure
pred_high_conf = {"direction": "BULLISH", "expected_1d_pct": 1.5, "conviction": 78.0}
f17_res = fc.classify(prediction=pred_high_conf, actual_change_pct=-1.2, actual_direction="BEARISH")
assert f17_res["primary_failure_code"] == "F17", f"Expected F17, got {f17_res['primary_failure_code']}"
assert f17_res["primary_category"] == "CONFIDENCE_MISCALIBRATION"

# Test F05: Gap-through
pred_gap = {"direction": "BULLISH", "expected_1d_pct": 1.0, "conviction": 55.0}
f05_res = fc.classify(prediction=pred_gap, actual_change_pct=-2.5, actual_direction="BEARISH", gap_through=True)
assert f05_res["primary_failure_code"] == "F05"
assert f05_res["primary_category"] == "GAP_THROUGH"

# Test F01: Magnitude error (right direction, wrong magnitude)
pred_mag = {"direction": "BULLISH", "expected_1d_pct": 0.5, "conviction": 55.0}
f01_res = fc.classify(prediction=pred_mag, actual_change_pct=2.8, actual_direction="BULLISH")
assert f01_res["primary_failure_code"] == "F01"
assert f01_res["direction_correct"] is True

# Test Success (no failure)
pred_succ = {"direction": "BULLISH", "expected_1d_pct": 1.0, "conviction": 65.0}
succ_res = fc.classify(prediction=pred_succ, actual_change_pct=1.1, actual_direction="BULLISH")
assert succ_res["primary_failure_code"] == "NONE"
assert succ_res["is_failure"] is False

print("✅ 18-Code failure taxonomy & classification rules passed.")

# 2. 3-Level Factor Attribution Engine Tests
print("\n--- Testing 2: 3-Level Factor Attribution Engine ---")
from event_agent.audit.attribution_engine import FactorAttributionEngine

ae = FactorAttributionEngine()
attrib = ae.attribute(
    symbol="RELIANCE.NS",
    predicted_move_pct=1.2,
    actual_move_pct=1.5,
    state_before={"nifty": 24800.0},
    state_after={"nifty_change_pct": 0.8, "vix_change_pct": -3.2},
)

assert "level_1_observed_association" in attrib
assert "level_2_estimated_contribution" in attrib
assert "level_3_causal_hypothesis" in attrib
assert attrib["explained_move_pct"] > 0
assert "unexplained_move_pct" in attrib
assert attrib["level_3_causal_hypothesis"]["label"] == "ECONOMIC_CAUSAL_HYPOTHESIS"
print(f"✅ Factor attribution passed. Realized: {attrib['actual_move_pct']:+.2f}%, Explained: {attrib['explained_move_pct']:+.2f}%, Residual: {attrib['unexplained_move_pct']:+.2f}%")

# 3. Residual Analyzer Tests
print("\n--- Testing 3: Residual Analyzer ---")
from event_agent.audit.residual_analyzer import ResidualAnalyzer

ra = ResidualAnalyzer()

# Single residual
res_single = ra.analyze_single(predicted_pct=1.0, actual_pct=0.8)
assert res_single["signed_prediction_error_pct"] == -0.2
assert res_single["absolute_prediction_error_pct"] == 0.2
assert res_single["error_direction"] == "OVER_PREDICTED"

# Residual sequence
residuals = [0.1, -0.2, 0.3, -0.1, 0.05, -0.15, 0.2]
regimes = ["RISK_ON", "RISK_ON", "RISK_OFF", "RISK_OFF", "RISK_ON", "RISK_OFF", "RISK_ON"]
res_seq = ra.analyze_sequence(residuals, regimes=regimes)
assert res_seq["sample_size"] == 7
assert "mae" in res_seq
assert "rmse" in res_seq
assert "autocorrelation_lag1" in res_seq
assert "RISK_ON" in res_seq["regime_breakdown"]
print("✅ Residual analyzer passed.")

# 4. Comprehensive Prediction Auditor Tests
print("\n--- Testing 4: Prediction Auditor Orchestrator ---")
from event_agent.audit.prediction_audit import PredictionAuditor

auditor = PredictionAuditor()

mock_pred = {
    "prediction_id": "PRED-20260909-TCS-v3.0.0",
    "model_version": "3.0.0",
    "feature_version": "F1",
    "regime_version": "R1",
    "calibration_version": "C1",
    "weights_version": "W1.0",
    "symbol": "TCS.NS",
    "short_name": "TCS",
    "entry_price": 4100.0,
    "target_price": 4150.0,
    "stop_loss": 4050.0,
    "direction": "BULLISH",
    "expected_1d_pct": 1.2,
    "conviction": 70.0,
    "baselines": {
        "random": {"direction": "UP"},
        "previous_day": {"direction": "UP"},
        "momentum_5d": {"direction": "UP"},
        "mean_reversion": {"direction": "DOWN"},
        "buy_and_hold": {"direction": "UP"},
    },
}

audit_rec = auditor.audit_trade(
    prediction=mock_pred,
    actual_close=4160.0,
    actual_high=4165.0,
    actual_low=4095.0,
    fill_reason="TARGET_HIT",
    is_ambiguous=False,
)

assert audit_rec["prediction_id"] == "PRED-20260909-TCS-v3.0.0"
assert audit_rec["target_hit"] is True
assert audit_rec["direction_correct"] is True
assert audit_rec["prediction_error_pct"] != 0.0
assert audit_rec["absolute_prediction_error_pct"] > 0
assert audit_rec["baseline_0_correct"] is True
assert audit_rec["baseline_3_correct"] is False  # Mean reversion predicted DOWN
assert audit_rec["primary_failure_code"] == "NONE"

print("✅ Comprehensive prediction auditor passed.")
print("\n🎉 ALL PHASE E TESTS PASSED SUCCESSFULLY! (4/4 test groups)")
