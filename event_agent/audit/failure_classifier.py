# =============================================================================
# event_agent/audit/failure_classifier.py — 18-Code Failure Taxonomy
# =============================================================================
"""
Rigorous forensic failure classification for trading losses and prediction errors.
Implements the full 18-code failure taxonomy from the V3.1.1 specification.

Every loss is systematically diagnosed with a primary code and secondary codes
to build an actionable forensic record for model governance.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 18-CODE FORENSIC FAILURE TAXONOMY
# ---------------------------------------------------------------------------
FAILURE_TAXONOMY: Dict[str, Dict[str, str]] = {
    "F01": {
        "code": "F01",
        "category": "MAGNITUDE_ERROR",
        "description": "Correct direction, wrong magnitude",
        "actionable_guidance": "Calibrate volatility scaling or multiplier sensitivity.",
    },
    "F02": {
        "code": "F02",
        "category": "MISSING_FACTOR",
        "description": "Unknown catalyst not in model",
        "actionable_guidance": "Expand event calendar or news search keywords for unmodeled catalyst.",
    },
    "F03": {
        "code": "F03",
        "category": "PRICED_IN",
        "description": "Sell-the-news / buy-the-rumor",
        "actionable_guidance": "Inspect pre-event run-up window to detect priced-in consensus.",
    },
    "F04": {
        "code": "F04",
        "category": "REGIME_SHIFT",
        "description": "Regime changed intra-day",
        "actionable_guidance": "Review transition probability and tighten stops during regime boundaries.",
    },
    "F05": {
        "code": "F05",
        "category": "GAP_THROUGH",
        "description": "Price gapped beyond stop",
        "actionable_guidance": "Evaluate overnight gap risk and reduce position size in high-volatility environments.",
    },
    "F06": {
        "code": "F06",
        "category": "WRONG_INTERPRETATION",
        "description": "Event was bullish, model read bearish",
        "actionable_guidance": "Audit news LLM prompt or sentiment parser polarity inversion.",
    },
    "F07": {
        "code": "F07",
        "category": "WRONG_REGIME",
        "description": "Regime classification was incorrect",
        "actionable_guidance": "Check underlying factor weights in regime detector.",
    },
    "F08": {
        "code": "F08",
        "category": "FACTOR_OVERWEIGHT",
        "description": "Over-weighted a factor",
        "actionable_guidance": "Candidate weight dampening in walk-forward evaluation.",
    },
    "F09": {
        "code": "F09",
        "category": "FACTOR_UNDERWEIGHT",
        "description": "Under-weighted a factor",
        "actionable_guidance": "Candidate weight increase in walk-forward evaluation.",
    },
    "F10": {
        "code": "F10",
        "category": "TIMING_ERROR",
        "description": "Right prediction, wrong day",
        "actionable_guidance": "Widen evaluation horizon or check event lag decay parameter.",
    },
    "F11": {
        "code": "F11",
        "category": "CONSENSUS_ERROR",
        "description": "Consensus value was wrong/stale",
        "actionable_guidance": "Audit consensus source timestamp and locking verification.",
    },
    "F12": {
        "code": "F12",
        "category": "DATA_QUALITY",
        "description": "Missing/stale/erroneous input data",
        "actionable_guidance": "Audit point-in-time adapter feeds for stuck values or >5σ outliers.",
    },
    "F13": {
        "code": "F13",
        "category": "CORRELATION_BREAKDOWN",
        "description": "Historical correlation broke down",
        "actionable_guidance": "Recompute rolling 20d correlation matrix.",
    },
    "F14": {
        "code": "F14",
        "category": "GEOPOLITICAL_SHOCK",
        "description": "Unexpected geopolitical event",
        "actionable_guidance": "Ensure emergency circuit breakers are triggered on sudden news bursts.",
    },
    "F15": {
        "code": "F15",
        "category": "MACRO_SHOCK",
        "description": "Unexpected macro event",
        "actionable_guidance": "Verify surprise engine normalization and release timestamps.",
    },
    "F16": {
        "code": "F16",
        "category": "MULTIPLE_CATALYSTS",
        "description": "Simultaneous conflicting catalysts",
        "actionable_guidance": "Increase uncertainty buffer and reduce trade size when conflicting news occurs.",
    },
    "F17": {
        "code": "F17",
        "category": "CONFIDENCE_MISCALIBRATION",
        "description": "High confidence was wrong",
        "actionable_guidance": "Re-run calibration engine temperature scaling and Platt contraction.",
    },
    "F18": {
        "code": "F18",
        "category": "UNEXPLAINED_RESIDUAL",
        "description": "Cannot attribute to known factor",
        "actionable_guidance": "Log residual for econometric review.",
    },
}


class FailureClassifier:
    """
    Automated diagnostic engine assigning taxonomy codes to imperfect predictions.
    """

    def classify(
        self,
        prediction: Dict[str, Any],
        actual_change_pct: float,
        actual_direction: str,
        fill_reason: Optional[str] = None,
        gap_through: bool = False,
        is_ambiguous: bool = False,
        regime_shift_occurred: bool = False,
        unexplained_move_pct: Optional[float] = None,
        data_warnings_count: int = 0,
    ) -> Dict[str, Any]:
        """
        Classifies errors and assigns primary and secondary failure codes.
        """
        pred_dir = prediction.get("direction", "NEUTRAL")
        pred_pct = prediction.get("expected_1d_pct", 0.0)
        confidence = float(prediction.get("conviction", 50.0))

        dir_correct = (pred_dir == actual_direction)
        if pred_dir == "BULLISH" and actual_change_pct > 0:
            dir_correct = True
        elif pred_dir == "BEARISH" and actual_change_pct < 0:
            dir_correct = True
        elif pred_dir == "NEUTRAL" and abs(actual_change_pct) <= 0.6:
            dir_correct = True

        secondary_codes: List[str] = []

        # Check for F17 (CONFIDENCE_MISCALIBRATION)
        is_miscalibrated = (confidence >= 65.0) and (not dir_correct)
        if is_miscalibrated:
            secondary_codes.append("F17")

        # Check for F05 (GAP_THROUGH)
        if gap_through:
            secondary_codes.append("F05")

        # Check for F04 (REGIME_SHIFT)
        if regime_shift_occurred:
            secondary_codes.append("F04")

        # Check for F12 (DATA_QUALITY)
        if data_warnings_count > 0:
            secondary_codes.append("F12")

        # Determine Primary Code
        primary_code = "F18"  # Default unexplained residual

        if dir_correct:
            # Direction was right, but maybe magnitude error
            mag_error = abs(pred_pct - actual_change_pct)
            if mag_error > 1.2:
                primary_code = "F01"
            else:
                primary_code = "NONE"  # No meaningful failure
        else:
            # Direction was wrong
            if is_miscalibrated:
                primary_code = "F17"
            elif gap_through:
                primary_code = "F05"
            elif regime_shift_occurred:
                primary_code = "F04"
            elif (pred_pct * actual_change_pct < -0.005):
                # Major opposite move
                if unexplained_move_pct is not None and abs(unexplained_move_pct) > 1.5:
                    primary_code = "F02"  # Missing factor
                else:
                    primary_code = "F06"  # Wrong interpretation
            else:
                primary_code = "F18"

        # Deduplicate secondary codes and exclude primary
        secondary_codes = [c for c in list(set(secondary_codes)) if c != primary_code]

        tax_entry = FAILURE_TAXONOMY.get(primary_code, {
            "code": primary_code,
            "category": "SUCCESS" if primary_code == "NONE" else "UNKNOWN",
            "description": "Prediction matched market outcome within acceptable tolerance." if primary_code == "NONE" else "Unclassified outcome",
            "actionable_guidance": "Maintain current parameters." if primary_code == "NONE" else "Inspect diagnostics.",
        })

        explanation = (
            f"Prediction was {pred_dir} ({pred_pct:+.2f}%, conf {confidence:.1f}%), "
            f"actual market move was {actual_direction} ({actual_change_pct:+.2f}%). "
            f"Primary diagnostic: {tax_entry['category']} ({tax_entry['description']})."
        )

        return {
            "primary_failure_code": primary_code,
            "primary_category": tax_entry["category"],
            "primary_description": tax_entry["description"],
            "actionable_guidance": tax_entry.get("actionable_guidance", ""),
            "secondary_failure_codes": secondary_codes,
            "diagnostic_explanation": explanation,
            "direction_correct": dir_correct,
            "is_failure": (primary_code != "NONE"),
        }
