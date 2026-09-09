# =============================================================================
# event_agent/prediction/champion_challenger.py — Champion vs Challenger Engine
# =============================================================================
"""
V3.5 Champion / Challenger Model Promotion Gate.
Tracks active production Champion against experimental Challenger candidates.
Enforces rigorous out-of-sample statistical promotion rules before any
model can supersede the production Champion.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


@dataclass
class ModelMetrics:
    version: str
    sample_size: int
    out_of_sample: bool
    accuracy_pct: float
    sharpe_ratio: float
    brier_score: float
    max_drawdown_pct: float
    profit_factor: float


@dataclass
class PromotionEvaluation:
    champion_version: str
    challenger_version: str
    eligible_for_promotion: bool
    decision: str                      # PROMOTED, REJECTED, INSUFFICIENT_EVALUATION
    p_value: float
    accuracy_improvement_pct: float
    sharpe_improvement: float
    drawdown_increase_pct: float
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "champion_version": self.champion_version,
            "challenger_version": self.challenger_version,
            "eligible_for_promotion": self.eligible_for_promotion,
            "decision": self.decision,
            "p_value": round(self.p_value, 4),
            "accuracy_improvement_pct": round(self.accuracy_improvement_pct, 2),
            "sharpe_improvement": round(self.sharpe_improvement, 2),
            "drawdown_increase_pct": round(self.drawdown_increase_pct, 2),
            "reasons": self.reasons,
        }


class ChampionChallengerGate:
    """
    Evaluates Challenger against Champion for production promotion.
    """

    MIN_OOS_SAMPLES = 50
    MAX_DRAWDOWN_TOLERANCE_PCT = 2.5
    SIGNIFICANCE_ALPHA = 0.05

    @classmethod
    def evaluate_promotion(
        cls,
        champion: ModelMetrics,
        challenger: ModelMetrics,
        paired_returns_champ: Optional[List[float]] = None,
        paired_returns_chall: Optional[List[float]] = None,
    ) -> PromotionEvaluation:
        """
        Evaluate if Challenger satisfies all strict OOS promotion gates.
        """
        reasons = []

        # Gate 1: Must be Out-of-Sample
        if not challenger.out_of_sample:
            reasons.append("Challenger evaluation was not strictly out-of-sample.")
            return PromotionEvaluation(
                champion.version, challenger.version, False, "REJECTED", 1.0, 0.0, 0.0, 0.0, reasons
            )

        # Gate 2: Sufficient Sample Size
        if challenger.sample_size < cls.MIN_OOS_SAMPLES:
            reasons.append(f"Insufficient OOS samples ({challenger.sample_size} < {cls.MIN_OOS_SAMPLES}).")
            return PromotionEvaluation(
                champion.version, challenger.version, False, "INSUFFICIENT_EVALUATION", 1.0, 0.0, 0.0, 0.0, reasons
            )

        # Accuracy and Sharpe Improvement
        acc_diff = challenger.accuracy_pct - champion.accuracy_pct
        sharpe_diff = challenger.sharpe_ratio - champion.sharpe_ratio
        dd_increase = challenger.max_drawdown_pct - champion.max_drawdown_pct

        # Statistical significance test (paired t-test on returns)
        p_val = 0.50
        if paired_returns_champ and paired_returns_chall and len(paired_returns_champ) == len(paired_returns_chall):
            diffs = np.array(paired_returns_chall) - np.array(paired_returns_champ)
            m_diff = np.mean(diffs)
            s_diff = np.std(diffs) + 1e-6
            t_stat = (m_diff / s_diff) * np.sqrt(len(diffs))
            # Approximate two-tailed p-value
            p_val = float(max(0.001, np.exp(-0.717 * abs(t_stat) - 0.416 * (t_stat ** 2))))
        else:
            # Statistical significance based on Sharpe improvement and accuracy difference
            import math
            se_acc = np.sqrt(2 * 0.5 * 0.5 / challenger.sample_size)
            z_acc = (acc_diff / 100.0) / se_acc if se_acc > 0 else 0.0
            
            se_sharpe = np.sqrt((1.0 + 0.5 * (champion.sharpe_ratio ** 2)) / challenger.sample_size)
            z_sharpe = sharpe_diff / se_sharpe if se_sharpe > 0 else 0.0
            
            z = max(z_acc, z_sharpe)
            p_val = float(max(0.001, 1.0 - math.erf(max(0.0, z) / math.sqrt(2.0)))) if z > 0 else 0.80

        # Gate 3: Drawdown tolerance
        if dd_increase > cls.MAX_DRAWDOWN_TOLERANCE_PCT:
            reasons.append(f"Drawdown worsened by {dd_increase:.1f}% (tolerance: {cls.MAX_DRAWDOWN_TOLERANCE_PCT}%).")

        # Gate 4: Must have positive improvements
        if acc_diff <= 0.0 and sharpe_diff <= 0.0:
            reasons.append(f"Challenger did not improve accuracy ({acc_diff:+.1f}%) or Sharpe ({sharpe_diff:+.2f}).")

        # Gate 5: Statistical significance
        if p_val > cls.SIGNIFICANCE_ALPHA:
            reasons.append(f"Improvement not statistically significant (p={p_val:.3f} >= {cls.SIGNIFICANCE_ALPHA}).")

        eligible = (len(reasons) == 0)
        decision = "PROMOTED" if eligible else "REJECTED"
        if eligible:
            reasons.append(f"Challenger demonstrated statistically significant edge (+{acc_diff:.1f}% acc, p={p_val:.3f}).")

        return PromotionEvaluation(
            champion_version=champion.version,
            challenger_version=challenger.version,
            eligible_for_promotion=eligible,
            decision=decision,
            p_value=round(p_val, 4),
            accuracy_improvement_pct=round(acc_diff, 2),
            sharpe_improvement=round(sharpe_diff, 2),
            drawdown_increase_pct=round(dd_increase, 2),
            reasons=reasons,
        )
