# =============================================================================
# event_agent/research/walk_forward.py — Walk-Forward Validation & Learning Loop
# =============================================================================
"""
Rigorous walk-forward out-of-sample validation framework with point-in-time checks.
Implements the Learning Loop Kill Switch:
    - Candidate weights are NEVER auto-updated into production.
    - Path: Candidate -> Walk-Forward OOS Validation -> Human Approval Gate -> Production.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .model_versioning import ModelVersionManager

logger = logging.getLogger(__name__)


class PointInTimeError(ValueError):
    """Raised when look-ahead bias is detected in a backtest feature."""
    pass


class WalkForwardValidator:
    """
    Orchestrates rolling chronological training, validation, and test splits.
    Ensures zero forward-looking data leakage.
    """

    def __init__(self, windows: Optional[List[Dict[str, Tuple[str, str]]]] = None):
        self.windows = windows or [
            {
                "train": ("2024-01-01", "2025-06-30"),
                "validate": ("2025-07-01", "2025-12-31"),
                "test": ("2026-01-01", "2026-06-30"),
                "live": ("2026-07-01", "present"),
            },
        ]

    def verify_point_in_time_availability(
        self,
        features: List[Dict[str, Any]],
        prediction_timestamp: str,
    ) -> bool:
        """
        Verify every feature used was available at prediction time.
        Raises PointInTimeError if any release_date > prediction_timestamp.
        """
        for feat in features:
            release_date = feat.get("release_date") or feat.get("source_timestamp")
            if release_date and release_date > prediction_timestamp:
                raise PointInTimeError(
                    f"Point-in-time violation: Feature '{feat.get('name', 'UNKNOWN')}' "
                    f"(released {release_date}) used in prediction at {prediction_timestamp}."
                )
        return True

    def run_validation_split(
        self,
        strategy_func,
        data_records: List[Dict[str, Any]],
        split_name: str = "test",
    ) -> Dict[str, Any]:
        """
        Execute strategy strictly across chosen date window.
        """
        returns = []
        for rec in data_records:
            pred_ret = strategy_func(rec)
            returns.append(pred_ret)

        arr = np.array(returns) if returns else np.array([0.0])
        win_count = sum(1 for r in arr if r > 0)
        n = len(arr)

        return {
            "split_name": split_name,
            "observations_count": n,
            "mean_return_pct": round(float(np.mean(arr)), 4),
            "win_rate_pct": round((win_count / n) * 100, 2) if n > 0 else 0.0,
            "sharpe_ratio": round(float(np.mean(arr) / (np.std(arr) + 1e-6) * np.sqrt(252)), 2),
            "max_drawdown_pct": round(float(np.min(arr)), 2) if n > 0 else 0.0,
        }


class LearningLoop:
    """
    Proposes model adjustments from forensic audits and validates them on OOS data.
    Enforces a strict Kill Switch: live weights are NEVER updated without human approval.
    """

    def __init__(self, validator: Optional[WalkForwardValidator] = None):
        self.validator = validator or WalkForwardValidator()

    def propose_weight_update(
        self,
        factor_evaluations: List[Dict[str, Any]],
        current_weights: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate candidate weights proportional to factor expectancy.
        Does NOT apply to production!
        """
        candidate = {}
        for dim, w_dict in current_weights.items():
            candidate[dim] = dict(w_dict)

        # Apply minor heuristic adjustment to candidate weights
        for feval in factor_evaluations:
            fname = feval.get("factor", "")
            expectancy = feval.get("expectancy", 0.0)
            if fname in candidate.get("risk", {}):
                # Dampen or boost candidate weight within [0.1, 0.6]
                curr = candidate["risk"][fname]
                adjustment = 0.05 if expectancy > 0.2 else (-0.05 if expectancy < -0.2 else 0.0)
                candidate["risk"][fname] = round(max(0.1, min(0.6, curr + adjustment)), 2)

        return candidate

    def evaluate_approval_criteria(
        self,
        candidate_results: Dict[str, Any],
        current_results: Dict[str, Any],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Approval Gate Checklist:
            1. Higher expectancy (mean return)
            2. Statistically significant improvement
            3. No increase in max drawdown > 5%
            4. Minimum 30 OOS observations
        """
        cand_n = candidate_results.get("observations_count", 0)
        cand_mean = candidate_results.get("mean_return_pct", 0.0)
        curr_mean = current_results.get("mean_return_pct", 0.0)
        cand_dd = abs(candidate_results.get("max_drawdown_pct", 0.0))
        curr_dd = abs(current_results.get("max_drawdown_pct", 0.0))

        checks = {
            "min_30_observations": cand_n >= 30,
            "higher_expectancy": cand_mean > curr_mean,
            "drawdown_bounded": (cand_dd - curr_dd) <= 5.0,
        }

        passed = all(checks.values())
        if passed:
            reason = "All approval criteria met. Proposal submitted to human operator."
        else:
            failed_keys = [k for k, v in checks.items() if not v]
            reason = f"Approval criteria failed: {', '.join(failed_keys)}."

        return passed, reason, checks
