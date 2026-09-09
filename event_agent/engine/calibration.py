# =============================================================================
# event_agent/engine/calibration.py — Confidence Calibration & Reliability
# =============================================================================
"""
Calibrates model confidence scores and evaluates probability reliability.

Key capabilities:
    1. Regime-aware confidence calibration (temperature scaling + dampening)
    2. Expected Calibration Error (ECE) and Brier score evaluation
    3. Reliability diagram binning
    4. Detection of F17 (CONFIDENCE_MISCALIBRATION) failure events
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CALIBRATION_VERSION = "C1"


def calibrate_confidence(
    raw_confidence: float,
    regime_state: Optional[str] = None,
    volatility_sigma: Optional[float] = None,
) -> float:
    """
    Calibrates raw conviction/confidence (scale 0 to 100).
    
    Adjustments:
        1. Compresses extreme overconfidence toward realistic bounds (rarely > 85%)
        2. Applies regime uncertainty penalties (e.g. CRISIS, STAGFLATION, HIGH_VOL)
        3. Scales with volatility dispersion
    """
    # Clamp raw confidence to valid range
    raw = max(0.0, min(100.0, float(raw_confidence)))

    # 1. Soft compression to prevent unwarranted >90% conviction
    # Uses a sigmoid-based contraction centered at 55.0 with gentle slope
    norm = (raw - 50.0) / 25.0
    compressed = 50.0 + (35.0 * math.tanh(norm * 0.8))

    # 2. Regime-based penalty
    regime_multiplier = 1.0
    if regime_state:
        state_upper = regime_state.upper()
        if "CRISIS" in state_upper or "PANIC" in state_upper:
            regime_multiplier = 0.75  # 25% conviction cut
        elif "STAGFLATION" in state_upper or "RECESSION" in state_upper:
            regime_multiplier = 0.82
        elif "RISK_OFF" in state_upper:
            regime_multiplier = 0.88
        elif "VOLATILE" in state_upper:
            regime_multiplier = 0.90
        elif "RISK_ON" in state_upper or "EXPANSION" in state_upper:
            regime_multiplier = 1.02  # Slight tailwind

    # 3. Volatility penalty if sigma > 1.5
    vol_multiplier = 1.0
    if volatility_sigma is not None and volatility_sigma > 1.5:
        vol_multiplier = max(0.80, 1.0 - ((volatility_sigma - 1.5) * 0.08))

    calibrated = compressed * regime_multiplier * vol_multiplier
    # Absolute guardrails: minimum 30.0, maximum 88.0 in real-world paper trading
    calibrated = max(30.0, min(88.0, calibrated))

    return round(calibrated, 1)


def compute_brier_score(
    probabilities: List[float],
    outcomes: List[int],
) -> float:
    """
    Compute Brier score: MSE between predicted probability (0 to 1) and outcome (0 or 1).
    Lower is better (0.0 = perfect, 0.25 = uninformative 50/50, >0.25 = worse than coin flip).
    """
    if not probabilities or not outcomes or len(probabilities) != len(outcomes):
        return 0.25

    n = len(probabilities)
    sq_errs = [
        (float(p) - float(o)) ** 2
        for p, o in zip(probabilities, outcomes)
    ]
    return round(sum(sq_errs) / n, 5)


def compute_expected_calibration_error(
    probabilities: List[float],
    outcomes: List[int],
    n_bins: int = 10,
) -> Dict[str, Any]:
    """
    Computes Expected Calibration Error (ECE) and Maximum Calibration Error (MCE).
    
    Args:
        probabilities: Predicted probabilities in range [0.0, 1.0] (or [0, 100])
        outcomes: Binary outcomes (1 = success/win, 0 = loss)
        n_bins: Number of equal-width bins between 0 and 1
    """
    if not probabilities or not outcomes or len(probabilities) != len(outcomes):
        return {
            "ece": 0.0,
            "mce": 0.0,
            "sample_size": 0,
            "brier_score": 0.25,
            "bins": [],
        }

    # Normalize to [0.0, 1.0] if provided as [0, 100]
    probs = [
        p / 100.0 if p > 1.0 else max(0.0, min(1.0, float(p)))
        for p in probabilities
    ]
    outs = [1 if int(o) == 1 else 0 for o in outcomes]

    n = len(probs)
    bin_boundaries = [i / n_bins for i in range(n_bins + 1)]
    bins_data = []

    total_ece = 0.0
    max_ce = 0.0

    for b in range(n_bins):
        low = bin_boundaries[b]
        high = bin_boundaries[b + 1]

        # Select items falling into this bin
        bin_indices = [
            i for i, p in enumerate(probs)
            if (low <= p < high) or (b == n_bins - 1 and low <= p <= high)
        ]

        bin_count = len(bin_indices)
        if bin_count > 0:
            bin_conf = sum(probs[i] for i in bin_indices) / bin_count
            bin_acc = sum(outs[i] for i in bin_indices) / bin_count
            gap = abs(bin_acc - bin_conf)

            total_ece += (bin_count / n) * gap
            max_ce = max(max_ce, gap)

            bins_data.append({
                "bin_range": f"{low:.1f}-{high:.1f}",
                "count": bin_count,
                "avg_confidence": round(bin_conf, 4),
                "accuracy": round(bin_acc, 4),
                "calibration_gap": round(gap, 4),
            })
        else:
            bins_data.append({
                "bin_range": f"{low:.1f}-{high:.1f}",
                "count": 0,
                "avg_confidence": round((low + high) / 2, 2),
                "accuracy": 0.0,
                "calibration_gap": 0.0,
            })

    brier = compute_brier_score(probs, outs)

    return {
        "calibration_version": CALIBRATION_VERSION,
        "sample_size": n,
        "ece": round(total_ece, 4),
        "mce": round(max_ce, 4),
        "brier_score": brier,
        "is_well_calibrated": total_ece < 0.10,
        "bins": bins_data,
    }


def is_confidence_miscalibration(
    confidence: float,
    trade_pnl: float,
    high_conviction_threshold: float = 72.0,
) -> bool:
    """
    Detects Failure Code F17: CONFIDENCE_MISCALIBRATION.
    Triggered when model had high conviction (>= threshold) but the trade lost money.
    """
    return (float(confidence) >= high_conviction_threshold) and (float(trade_pnl) < 0)
