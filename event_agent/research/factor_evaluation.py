# =============================================================================
# event_agent/research/factor_evaluation.py — Statistical Factor Evaluation
# =============================================================================
"""
Rigorous statistical evaluation of prediction factors and features.
Key principle (Review Point #1-6 fix):
    Never evaluate factors solely on win rate (>50%).
    Evaluate on expectancy, profit factor, t-statistic, p-value, sample size,
    and 95% confidence intervals.
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def _compute_t_and_p_value(returns: List[float]) -> Tuple[float, float, Tuple[float, float]]:
    """
    Compute 1-sample t-statistic, two-tailed p-value, and 95% confidence interval
    using pure numpy/math with optional scipy enhancement.
    """
    n = len(returns)
    if n < 3:
        return 0.0, 1.0, (0.0, 0.0)

    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))
    if std < 1e-8:
        return 0.0, 1.0, (mean, mean)

    sem = std / math.sqrt(n)
    t_stat = mean / sem

    try:
        import scipy.stats as stats
        p_val = float(stats.ttest_1samp(returns, 0.0)[1])
        ci = stats.t.interval(0.95, df=n - 1, loc=mean, scale=sem)
        ci_95 = (round(float(ci[0]), 4), round(float(ci[1]), 4))
    except Exception:
        # High-accuracy numerical approximation without scipy
        # Two-tailed p-value via normal approximation (erfc)
        z = abs(t_stat)
        p_val = math.erfc(z / math.sqrt(2.0))
        # 1.96 critical value for 95% CI
        crit = 1.96 if n > 30 else 2.0 + (3.0 / n)
        ci_95 = (round(mean - crit * sem, 4), round(mean + crit * sem, 4))

    return round(t_stat, 3), round(p_val, 4), ci_95


def evaluate_factor(
    factor_name: str,
    regime: str,
    observations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    A factor is evaluated by expectancy, not just hit rate.
    A 48% hit rate with large winners can beat a 67% hit rate with tiny winners.
    """
    returns = [float(obs.get("actual_impact_pct", 0.0)) for obs in observations]
    n = len(returns)

    winners = [r for r in returns if r > 0]
    losers = [r for r in returns if r <= 0]

    hit_rate = len(winners) / n if n > 0 else 0.0
    avg_win = float(np.mean(winners)) if winners else 0.0
    avg_loss = abs(float(np.mean(losers))) if losers else 0.0

    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 2)
    else:
        profit_factor = 99.0 if gross_profit > 0 else 1.0

    expectancy = (hit_rate * avg_win) - ((1.0 - hit_rate) * avg_loss)
    t_stat, p_val, ci_95 = _compute_t_and_p_value(returns)

    is_significant = (p_val < 0.05) and (n >= 15) and (expectancy > 0)

    return {
        "factor": factor_name,
        "regime": regime,
        "sample_count": n,
        "hit_rate": round(hit_rate, 4),
        "avg_win_pct": round(avg_win, 4),
        "avg_loss_pct": round(avg_loss, 4),
        "profit_factor": profit_factor,
        "expectancy": round(expectancy, 4),
        "t_statistic": t_stat,
        "p_value": p_val,
        "confidence_interval_95": ci_95,
        "median_return": round(float(np.median(returns)), 4) if n > 0 else 0.0,
        "max_drawdown_contribution": round(float(min(returns)), 4) if n > 0 else 0.0,
        "is_statistically_significant": is_significant,
    }


class FactorEvaluator:
    """
    Aggregates factor evaluations across multiple regime dimensions.
    """

    def __init__(self):
        self._history: Dict[str, List[Dict[str, Any]]] = {}

    def record_observation(
        self,
        factor_name: str,
        regime: str,
        predicted_impact: float,
        actual_impact: float,
    ):
        key = f"{factor_name}:{regime}"
        if key not in self._history:
            self._history[key] = []
        self._history[key].append({
            "predicted_impact_pct": predicted_impact,
            "actual_impact_pct": actual_impact,
        })

    def get_summary(self) -> List[Dict[str, Any]]:
        results = []
        for key, obs in self._history.items():
            fname, regime = key.split(":", 1)
            eval_res = evaluate_factor(fname, regime, obs)
            results.append(eval_res)
        return results
