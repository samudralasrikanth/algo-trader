def _is_dir_match(d1: str, d2: str) -> bool:
    def norm(d):
        u = str(d).upper()
        if u in ('UP', 'BULLISH', 'BUY', 'STRONG_BUY'): return 'UP'
        if u in ('DOWN', 'BEARISH', 'SELL', 'STRONG_SELL'): return 'DOWN'
        return 'NEUTRAL'
    return norm(d1) == norm(d2)

# =============================================================================
# event_agent/audit/prediction_audit.py — Comprehensive Forensic Prediction Audit
# =============================================================================
"""
Constructs an immutable forensic audit record for every trade outcome.
Stores signed and absolute prediction errors, full 3-level attribution,
18-code failure taxonomy classifications, and comparisons against all 5 baselines.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .attribution_engine import FactorAttributionEngine
from .failure_classifier import FailureClassifier
from .residual_analyzer import ResidualAnalyzer

logger = logging.getLogger(__name__)


def create_prediction_audit(
    prediction: Dict[str, Any],
    outcome: Dict[str, Any],
    attribution: Dict[str, Any],
    failure_codes: Dict[str, Any],
    baselines: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Constructs the canonical audit dictionary as specified in V3.1.1.
    """
    pred_pct = float(prediction.get("expected_1d_pct", 0.0))
    act_pct = float(outcome.get("actual_change_pct", 0.0))
    signed_error = round(act_pct - pred_pct, 4)
    abs_error = round(abs(signed_error), 4)

    return {
        "prediction_id": prediction.get("prediction_id", "UNKNOWN"),
        "model_version": prediction.get("model_version", "3.0.0"),
        "feature_version": prediction.get("feature_version", "F1"),
        "regime_version": prediction.get("regime_version", "R1"),
        "calibration_version": prediction.get("calibration_version", "C1"),
        "weights_version": prediction.get("weights_version", "W1.0"),
        "symbol": prediction.get("symbol", ""),
        "short_name": prediction.get("short_name", ""),
        "trade_date": outcome.get("trade_date", datetime.now().strftime("%Y-%m-%d")),

        "predicted_direction": prediction.get("direction", "NEUTRAL"),
        "actual_direction": outcome.get("actual_direction", "NEUTRAL"),
        "predicted_return_pct": pred_pct,
        "actual_return_pct": act_pct,
        "prediction_error_pct": signed_error,                  # Signed error
        "absolute_prediction_error_pct": abs_error,             # Absolute error

        "target_hit": bool(outcome.get("target_hit", False)),
        "stop_hit": bool(outcome.get("stop_hit", False)),
        "fill_was_ambiguous": bool(outcome.get("is_ambiguous", False)),
        "ambiguity_note": outcome.get("ambiguity_note", ""),

        "expected_regime_json": prediction.get("regime", {}),
        "actual_regime_json": outcome.get("post_regime", {}),

        "primary_failure_code": failure_codes.get("primary_failure_code", "NONE"),
        "primary_category": failure_codes.get("primary_category", "NONE"),
        "secondary_failure_codes": failure_codes.get("secondary_failure_codes", []),
        "diagnostic_explanation": failure_codes.get("diagnostic_explanation", ""),

        "attribution_json": attribution,
        "explained_move_pct": attribution.get("explained_move_pct", 0.0),
        "unexplained_move_pct": attribution.get("unexplained_move_pct", 0.0),

        "model_confidence": float(prediction.get("conviction", 50.0)),
        "confidence_was_correct": bool(outcome.get("direction_correct", False)),

        # 5 baselines evaluation
        "baseline_0_correct": bool(baselines.get("random", {}).get("correct", False)),
        "baseline_1_correct": bool(baselines.get("previous_day", {}).get("correct", False)),
        "baseline_2_correct": bool(baselines.get("momentum_5d", {}).get("correct", False)),
        "baseline_3_correct": bool(baselines.get("mean_reversion", {}).get("correct", False)),
        "baseline_4_return": float(baselines.get("buy_and_hold", {}).get("return_pct", act_pct)),

        "direction_correct": bool(outcome.get("direction_correct", False)),
        "model_correct": bool(outcome.get("direction_correct", False)),
        "audited_at": datetime.now(timezone.utc).isoformat(),
    }


class PredictionAuditor:
    """
    Unified forensic audit orchestrator running attribution, failure classification,
    and baseline comparison in a single call.
    """

    def __init__(self):
        self.attribution_engine = FactorAttributionEngine()
        self.failure_classifier = FailureClassifier()
        self.residual_analyzer = ResidualAnalyzer()

    def audit_trade(
        self,
        prediction: Dict[str, Any],
        actual_close: float,
        actual_open: Optional[float] = None,
        actual_high: Optional[float] = None,
        actual_low: Optional[float] = None,
        fill_reason: Optional[str] = None,
        is_ambiguous: bool = False,
        ambiguity_note: str = "",
        post_market_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Produce a full audit record given prediction and realized market prices.
        """
        base_price = float(prediction.get("entry_price", prediction.get("base_price", actual_close)))
        actual_change_pct = round(((actual_close - base_price) / base_price) * 100, 2) if base_price > 0 else 0.0
        
        actual_dir = "BULLISH" if actual_change_pct > 0.3 else ("BEARISH" if actual_change_pct < -0.3 else "NEUTRAL")
        pred_dir = prediction.get("direction", "NEUTRAL")

        dir_correct = _is_dir_match(pred_dir, actual_dir)

        pred_target = float(prediction.get("target_price", prediction.get("target_1d", base_price)))
        pred_stop = float(prediction.get("stop_loss", base_price * 0.98))

        target_hit = (fill_reason == "TARGET_HIT") or (actual_high is not None and actual_high >= pred_target if pred_dir == "BULLISH" else actual_low is not None and actual_low <= pred_target)
        stop_hit = (fill_reason == "STOP_HIT") or (actual_low is not None and actual_low <= pred_stop if pred_dir == "BULLISH" else actual_high is not None and actual_high >= pred_stop)

        outcome = {
            "trade_date": prediction.get("target_trade_date", datetime.now().strftime("%Y-%m-%d")),
            "actual_close": actual_close,
            "actual_change_pct": actual_change_pct,
            "actual_direction": actual_dir,
            "direction_correct": dir_correct,
            "target_hit": target_hit,
            "stop_hit": stop_hit,
            "is_ambiguous": is_ambiguous,
            "ambiguity_note": ambiguity_note,
            "post_regime": post_market_state or {},
        }

        # 1. 3-Level Factor Attribution
        attrib = self.attribution_engine.attribute(
            symbol=prediction.get("symbol", ""),
            predicted_move_pct=float(prediction.get("expected_1d_pct", 0.0)),
            actual_move_pct=actual_change_pct,
            state_before=prediction.get("market_state_json", {}),
            state_after=post_market_state or {},
        )

        # 2. 18-Code Failure Classification
        failure = self.failure_classifier.classify(
            prediction=prediction,
            actual_change_pct=actual_change_pct,
            actual_direction=actual_dir,
            fill_reason=fill_reason,
            is_ambiguous=is_ambiguous,
            unexplained_move_pct=attrib.get("unexplained_move_pct", 0.0),
        )

        # 3. Evaluate 5 Baselines against actual outcome
        baselines_input = prediction.get("baselines", {})
        baselines_eval = {}
        for b_key in ["random", "previous_day", "momentum_5d", "mean_reversion"]:
            b_dir = baselines_input.get(b_key, {}).get("direction", "NEUTRAL")
            b_correct = _is_dir_match(b_dir, actual_dir)
            baselines_eval[b_key] = {"direction": b_dir, "correct": b_correct}

        baselines_eval["buy_and_hold"] = {
            "direction": "UP",
            "return_pct": actual_change_pct,
            "correct": (actual_change_pct > 0),
        }

        # 4. Construct unified audit
        return create_prediction_audit(
            prediction=prediction,
            outcome=outcome,
            attribution=attrib,
            failure_codes=failure,
            baselines=baselines_eval,
        )
