# =============================================================================
# event_agent/prediction/distribution.py — Direction & Magnitude Separation
# =============================================================================
"""
V3.5 Return Distribution Modeling & Direction/Magnitude Separation.
Treats directional probability P(UP), expected return E(Return), and full
return distribution P(Return) as decoupled, distinct models.
Evaluates credible interval calibration (50% and 80% intervals).
"""

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


@dataclass
class CredibleIntervals:
    interval_50: Tuple[float, float]    # [Q25, Q75]
    interval_80: Tuple[float, float]    # [Q10, Q90]
    mean_return: float
    volatility: float
    skewness: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interval_50": [round(self.interval_50[0], 5), round(self.interval_50[1], 5)],
            "interval_80": [round(self.interval_80[0], 5), round(self.interval_80[1], 5)],
            "mean_return": round(self.mean_return, 5),
            "volatility": round(self.volatility, 5),
            "skewness": round(self.skewness, 5),
        }


class ReturnDistributionModel:
    """
    Decoupled Model C for parametric return distributions and intervals.
    Uses Student-t or Skew-Normal distribution properties.
    """

    # Normal quantiles for 50% and 80% intervals
    Z_50 = 0.6745   # Covers 50% (-0.6745 to +0.6745)
    Z_80 = 1.2816   # Covers 80% (-1.2816 to +1.2816)

    @classmethod
    def estimate_distribution(
        cls,
        expected_return: float,
        daily_volatility: float,
        horizon_days: float = 1.0,
        skewness: float = 0.0,
    ) -> CredibleIntervals:
        """
        Compute parametric credible intervals scaled by horizon root-time.
        """
        sigma_t = max(0.005, daily_volatility * math.sqrt(max(0.1, horizon_days)))

        # Skewness adjustment
        shift = 0.5 * skewness * sigma_t

        q25 = expected_return - (cls.Z_50 * sigma_t) + shift
        q75 = expected_return + (cls.Z_50 * sigma_t) + shift

        q10 = expected_return - (cls.Z_80 * sigma_t) + shift
        q90 = expected_return + (cls.Z_80 * sigma_t) + shift

        return CredibleIntervals(
            interval_50=(min(q25, q75), max(q25, q75)),
            interval_80=(min(q10, q90), max(q10, q90)),
            mean_return=expected_return,
            volatility=sigma_t,
            skewness=skewness,
        )

    @classmethod
    def evaluate_interval_calibration(
        cls,
        actual_returns: List[float],
        intervals_list: List[CredibleIntervals],
    ) -> Dict[str, Any]:
        """
        Measure empirical coverage rates for 50% and 80% intervals.
        Determines if dispersion is calibrated, under-dispersed (too narrow), or over-dispersed (too wide).
        """
        if not actual_returns or len(actual_returns) != len(intervals_list):
            return {
                "status": "INSUFFICIENT_DATA",
                "observations": 0,
                "coverage_50_pct": 0.0,
                "coverage_80_pct": 0.0,
                "is_calibrated": False,
            }

        n = len(actual_returns)
        c50_hits = 0
        c80_hits = 0

        for ret, ci in zip(actual_returns, intervals_list):
            if ci.interval_50[0] <= ret <= ci.interval_50[1]:
                c50_hits += 1
            if ci.interval_80[0] <= ret <= ci.interval_80[1]:
                c80_hits += 1

        cov_50 = c50_hits / n
        cov_80 = c80_hits / n

        # Calibration assessment
        err_50 = abs(cov_50 - 0.50)
        err_80 = abs(cov_80 - 0.80)
        is_calibrated = (err_50 <= 0.08 and err_80 <= 0.08)

        if cov_50 < 0.40 or cov_80 < 0.70:
            dispersion_diagnosis = "UNDER_DISPERSED_TAILS_TOO_NARROW"
        elif cov_50 > 0.60 or cov_80 > 0.90:
            dispersion_diagnosis = "OVER_DISPERSED_INTERVALS_TOO_WIDE"
        else:
            dispersion_diagnosis = "WELL_CALIBRATED_DISPERSION"

        return {
            "status": "EVALUATED",
            "observations": n,
            "coverage_50_pct": round(cov_50 * 100, 2),
            "coverage_80_pct": round(cov_80 * 100, 2),
            "expected_50_pct": 50.0,
            "expected_80_pct": 80.0,
            "error_50_pct": round(err_50 * 100, 2),
            "error_80_pct": round(err_80 * 100, 2),
            "is_calibrated": is_calibrated,
            "dispersion_diagnosis": dispersion_diagnosis,
        }
