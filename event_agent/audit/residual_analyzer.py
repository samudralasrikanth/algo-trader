# =============================================================================
# event_agent/audit/residual_analyzer.py — Residual & Error Diagnostics
# =============================================================================
"""
Analyzes prediction residuals (actual return minus predicted return).
Detects systematic bias, autocorrelation, volatility clustering, and regime skew.
"""

import logging
import math
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class ResidualAnalyzer:
    """
    Evaluates error patterns across prediction sequences.
    """

    def analyze_single(
        self,
        predicted_pct: float,
        actual_pct: float,
    ) -> Dict[str, Any]:
        """Compute point-in-time signed and absolute prediction error."""
        signed_error = round(actual_pct - predicted_pct, 4)
        abs_error = round(abs(signed_error), 4)

        return {
            "predicted_pct": round(predicted_pct, 4),
            "actual_pct": round(actual_pct, 4),
            "signed_prediction_error_pct": signed_error,
            "absolute_prediction_error_pct": abs_error,
            "error_direction": "OVER_PREDICTED" if signed_error < 0 else "UNDER_PREDICTED",
        }

    def analyze_sequence(
        self,
        residuals: List[float],
        regimes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate statistical properties of a historical residual sequence.
        """
        if not residuals:
            return {"sample_size": 0, "mean_error": 0.0, "mae": 0.0, "rmse": 0.0}

        arr = np.array(residuals, dtype=float)
        n = len(arr)
        mean_err = float(np.mean(arr))
        mae = float(np.mean(np.abs(arr)))
        rmse = float(np.sqrt(np.mean(arr ** 2)))
        std_err = float(np.std(arr)) if n > 1 else 0.0

        # Autocorrelation (lag 1) to test for persistent bias
        autocorr_lag1 = 0.0
        if n >= 5 and std_err > 1e-6:
            c0 = np.var(arr)
            c1 = np.mean((arr[:-1] - mean_err) * (arr[1:] - mean_err))
            autocorr_lag1 = float(c1 / c0) if c0 > 0 else 0.0

        # Regime-grouped error breakdown
        regime_breakdown = {}
        if regimes and len(regimes) == n:
            unique_regimes = set(regimes)
            for reg in unique_regimes:
                reg_mask = [r == reg for r in regimes]
                reg_res = arr[reg_mask]
                if len(reg_res) > 0:
                    regime_breakdown[reg] = {
                        "count": int(len(reg_res)),
                        "mean_error": round(float(np.mean(reg_res)), 3),
                        "mae": round(float(np.mean(np.abs(reg_res))), 3),
                    }

        return {
            "sample_size": n,
            "mean_signed_error": round(mean_err, 4),
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "error_std": round(std_err, 4),
            "autocorrelation_lag1": round(autocorr_lag1, 4),
            "has_systematic_bias": abs(mean_err) > 0.35,
            "has_persistent_autocorrelation": abs(autocorr_lag1) > 0.25,
            "regime_breakdown": regime_breakdown,
        }
