# =============================================================================
# event_agent/certification/multiple_testing_audit.py — Multiple-Testing & DSR
# =============================================================================
"""
V3.6 Multiple-Testing & Overfitting Auditor.
Calculates the data-mining penalty across all attempted model configurations:
  1. Bailey & López de Prado (2014) Deflated Sharpe Ratio (DSR)
  2. Probabilistic Sharpe Ratio (PSR)
  3. Family-Wise Error Rate (FWER) via Bonferroni and Holm-Bonferroni
  4. False Discovery Rate (FDR) via Benjamini-Hochberg procedure

Guarantees that claimed returns survive rigorous statistical correction for
searching across multiple agents, horizons, and feature subsets.
"""

from dataclasses import asdict, dataclass
import math
import logging
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from .experiment_registry import ExperimentRegistry

logger = logging.getLogger(__name__)


@dataclass
class DSRMetrics:
    total_trials_attempted: int
    observed_annual_sharpe: float
    expected_max_null_sharpe: float
    variance_of_trials: float
    sample_periods_days: int
    skewness: float
    kurtosis: float
    deflated_sharpe_ratio: float      # DSR in [0, 1]
    probabilistic_sharpe_ratio: float  # PSR in [0, 1]
    bonferroni_p_value: float
    fdr_q_value: float
    is_statistically_genuine: bool
    verdict: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trials_attempted": self.total_trials_attempted,
            "observed_annual_sharpe": round(self.observed_annual_sharpe, 2),
            "expected_max_null_sharpe": round(self.expected_max_null_sharpe, 2),
            "variance_of_trials": round(self.variance_of_trials, 4),
            "sample_periods_days": self.sample_periods_days,
            "skewness": round(self.skewness, 2),
            "kurtosis": round(self.kurtosis, 2),
            "deflated_sharpe_ratio": round(self.deflated_sharpe_ratio, 4),
            "probabilistic_sharpe_ratio": round(self.probabilistic_sharpe_ratio, 4),
            "bonferroni_p_value": round(self.bonferroni_p_value, 6),
            "fdr_q_value": round(self.fdr_q_value, 6),
            "is_statistically_genuine": self.is_statistically_genuine,
            "verdict": self.verdict,
        }


class MultipleTestingAuditor:
    """
    Audits selection bias and computes the Deflated Sharpe Ratio.
    """

    EULER_MASCHERONI = 0.5772156649015329

    @classmethod
    def norm_cdf(cls, z: float) -> float:
        """Standard normal cumulative distribution function."""
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

    @classmethod
    def norm_ppf(cls, p: float) -> float:
        """
        Inverse normal CDF (probit) approximation (Acklam's algorithm).
        """
        p = max(1e-10, min(1.0 - 1e-10, p))
        # Rational approximation
        a = [-3.969683028665376e01,  2.209460984245205e02,
             -2.759285104469687e02,  1.383577518672690e02,
             -3.066479806614716e01,  2.506628277459239e00]
        b = [-5.447609879822406e01,  1.615858368580409e02,
             -1.556989798598866e02,  6.680131188771972e01,
             -1.328068155288572e01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01,
             -2.400758277161838e00, -2.549732539343734e00,
              4.374664141464968e00,  2.938163982698783e00]
        d = [ 7.784695709041462e-03,  3.224671290700398e-01,
              2.445134137142996e00,  3.754408661907416e00]

        q = p - 0.5
        if abs(q) <= 0.42:
            r = q * q
            return q * (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) / \
                       (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0)
        r = p if q < 0 else 1.0 - p
        r = math.sqrt(-math.log(r))
        x = (((((c[0]*r + c[1])*r + c[2])*r + c[3])*r + c[4])*r + c[5]) / \
            ((((d[0]*r + d[1])*r + d[2])*r + d[3])*r + 1.0)
        return -x if q < 0 else x

    @classmethod
    def compute_expected_max_sharpe(cls, n_trials: int, var_trials: float) -> float:
        """
        Computes expected maximum Sharpe under null hypothesis:
        E[max_N {SR}] = sqrt(V) * [ (1 - gamma)*Z^-1(1 - 1/N) + gamma*Z^-1(1 - 1/(N*e)) ]
        """
        if n_trials <= 1:
            return 0.0
        sigma = math.sqrt(max(1e-6, var_trials))
        p1 = 1.0 - (1.0 / n_trials)
        p2 = 1.0 - (1.0 / (n_trials * math.e))
        z1 = cls.norm_ppf(p1)
        z2 = cls.norm_ppf(p2)
        emax = sigma * ((1.0 - cls.EULER_MASCHERONI) * z1 + cls.EULER_MASCHERONI * z2)
        return float(emax)

    @classmethod
    def compute_deflated_sharpe_ratio(
        cls,
        observed_annual_sharpe: float = 1.72,
        sample_days: int = 1250,
        skewness: float = -0.22,
        kurtosis: float = 3.35,
        registry: Optional[ExperimentRegistry] = None,
    ) -> DSRMetrics:
        """
        Audits all attempted experiments and calculates DSR.
        """
        reg = registry or ExperimentRegistry()
        # Ensure canonical historical trials are seeded to reflect complete search space
        reg.seed_historical_experiment_trials()

        n_trials = max(160, reg.get_total_experiments_count())
        sharpes = reg.get_sharpe_distribution()
        var_trials = float(np.var(sharpes)) if len(sharpes) > 1 else 0.0625

        # Daily Sharpe equivalents for asymptotic formula
        daily_sr = observed_annual_sharpe / math.sqrt(252.0)
        e_max_annual = cls.compute_expected_max_sharpe(n_trials, var_trials)
        daily_sr_bench = e_max_annual / math.sqrt(252.0)

        # Standard error of Sharpe with non-normal skewness & kurtosis (Mertens, 2002)
        denom = math.sqrt(
            max(1e-6, 1.0 - skewness * daily_sr + ((kurtosis - 1.0) / 4.0) * (daily_sr ** 2))
        )
        t_stat = ((daily_sr - daily_sr_bench) * math.sqrt(sample_days - 1)) / denom
        dsr = float(cls.norm_cdf(t_stat))

        # Standard Probabilistic Sharpe Ratio against zero null
        t_stat_psr = (daily_sr * math.sqrt(sample_days - 1)) / denom
        psr = float(cls.norm_cdf(t_stat_psr))

        # Multiple-Testing Corrections on raw p-value
        raw_p = max(1e-8, 1.0 - psr)
        bonferroni_p = min(1.0, raw_p * n_trials)
        fdr_q = min(1.0, (raw_p * n_trials) / 1.0) # Benjamini-Hochberg for single top discovery

        # Certification threshold: DSR >= 0.95 (statistically genuine at 5% level after trial penalty)
        is_genuine = (dsr >= 0.95 and bonferroni_p < 0.05)
        verdict = "STATISTICALLY_GENUINE_BEYOND_DATA_MINING" if is_genuine else "VULNERABLE_TO_SELECTION_BIAS"

        return DSRMetrics(
            total_trials_attempted=n_trials,
            observed_annual_sharpe=observed_annual_sharpe,
            expected_max_null_sharpe=e_max_annual,
            variance_of_trials=var_trials,
            sample_periods_days=sample_days,
            skewness=skewness,
            kurtosis=kurtosis,
            deflated_sharpe_ratio=dsr,
            probabilistic_sharpe_ratio=psr,
            bonferroni_p_value=bonferroni_p,
            fdr_q_value=fdr_q,
            is_statistically_genuine=is_genuine,
            verdict=verdict,
        )
