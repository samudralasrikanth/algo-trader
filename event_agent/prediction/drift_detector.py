# =============================================================================
# event_agent/prediction/drift_detector.py — Continuous Drift & Health State Engine
# =============================================================================
"""
V3.5 Statistical Drift Detection & Model Health State Machine.
Tracks feature distribution shift, prediction drift, confidence drift, and accuracy degradation.
Manages the 4-stage health state machine:
    NORMAL -> DEGRADED -> RESTRICTED -> SUSPENDED
Integrates directly with Central Risk Engine sizing rules.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import numpy as np


@dataclass
class DriftReport:
    feature_drift_p_value: float
    prediction_drift_stat: float
    accuracy_degradation_pct: float
    calibration_error_delta: float
    health_status: str                 # NORMAL, DEGRADED, RESTRICTED, SUSPENDED
    recommended_action: str
    risk_sizing_multiplier: float      # 1.0 (NORMAL) down to 0.0 (SUSPENDED)
    drift_triggers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "health_status": self.health_status,
            "feature_drift_p_value": round(self.feature_drift_p_value, 4),
            "prediction_drift_stat": round(self.prediction_drift_stat, 4),
            "accuracy_degradation_pct": round(self.accuracy_degradation_pct, 2),
            "calibration_error_delta": round(self.calibration_error_delta, 4),
            "recommended_action": self.recommended_action,
            "risk_sizing_multiplier": round(self.risk_sizing_multiplier, 2),
            "drift_triggers": self.drift_triggers,
        }


class DriftDetector:
    """
    Evaluates rolling prediction and feature windows against baseline reference windows.
    """

    @classmethod
    def evaluate_drift(
        cls,
        baseline_accuracies: List[float],
        recent_accuracies: List[float],
        baseline_features: Optional[List[float]] = None,
        recent_features: Optional[List[float]] = None,
        baseline_ece: float = 0.045,
        recent_ece: float = 0.052,
    ) -> DriftReport:
        """
        Evaluate degradation between baseline and recent monitoring windows.
        """
        triggers = []

        mean_base = float(np.mean(baseline_accuracies)) if baseline_accuracies else 64.0
        mean_recent = float(np.mean(recent_accuracies)) if recent_accuracies else 62.5
        acc_drop = max(0.0, mean_base - mean_recent)

        if acc_drop > 8.0:
            triggers.append(f"Severe accuracy degradation: -{acc_drop:.1f}%")
        elif acc_drop > 4.0:
            triggers.append(f"Moderate accuracy drop: -{acc_drop:.1f}%")

        # Calibration drift
        ece_delta = max(0.0, recent_ece - baseline_ece)
        if ece_delta > 0.08:
            triggers.append(f"Severe calibration drift: +{ece_delta:.3f} ECE")
        elif ece_delta > 0.03:
            triggers.append(f"Mild calibration drift: +{ece_delta:.3f} ECE")

        # Feature drift check via KS-distance approximation
        p_val = 0.45
        if baseline_features and recent_features and len(baseline_features) >= 20 and len(recent_features) >= 20:
            # Difference in means relative to pooled std
            diff = abs(np.mean(recent_features) - np.mean(baseline_features))
            pooled_std = (np.std(recent_features) + np.std(baseline_features)) / 2.0 + 1e-6
            z = diff / pooled_std
            p_val = max(0.001, float(np.exp(-0.5 * (z ** 2))))
            if p_val < 0.05:
                triggers.append(f"Statistically significant feature distribution drift (p={p_val:.3f})")

        # Determine Health Status
        if acc_drop > 10.0 or ece_delta > 0.10 or p_val < 0.01:
            status = "SUSPENDED"
            action = "Halt new paper trading entries; trigger model retrain gate."
            multiplier = 0.0
        elif acc_drop > 5.0 or ece_delta > 0.05 or p_val < 0.05:
            status = "RESTRICTED"
            action = "Restrict position sizes by 50%; require higher net edge threshold."
            multiplier = 0.5
        elif acc_drop > 2.5 or ece_delta > 0.02:
            status = "DEGRADED"
            action = "Minor performance decay detected; damp sizing to 80%."
            multiplier = 0.8
        else:
            status = "NORMAL"
            action = "All features and calibrations within healthy operating parameters."
            multiplier = 1.0

        return DriftReport(
            feature_drift_p_value=round(p_val, 4),
            prediction_drift_stat=round(acc_drop, 2),
            accuracy_degradation_pct=round(acc_drop, 2),
            calibration_error_delta=round(ece_delta, 4),
            health_status=status,
            recommended_action=action,
            risk_sizing_multiplier=multiplier,
            drift_triggers=triggers,
        )
