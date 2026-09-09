# =============================================================================
# event_agent/prediction/calibration_metrics.py — 9-Bucket Calibration & Reliability
# =============================================================================
"""
V3.5 Confidence Calibration Engine across 9 Discrete Probability Buckets.
Computes Brier score, Log Loss, Expected Calibration Error (ECE),
Maximum Calibration Error (MCE), and marks models MIS-CALIBRATED if confidence
exceeds empirical accuracy.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class BucketStats:
    bucket_label: str                  # e.g. "50-55%"
    min_prob: float
    max_prob: float
    count: int
    mean_predicted_prob: float
    actual_win_rate: float
    calibration_error: float           # abs(mean_predicted_prob - actual_win_rate)


@dataclass
class CalibrationResult:
    brier_score: float
    log_loss: float
    expected_calibration_error: float  # ECE
    maximum_calibration_error: float   # MCE
    total_samples: int
    status: str                        # WELL_CALIBRATED, MIS-CALIBRATED, INSUFFICIENT_DATA
    reliability_curve: List[Tuple[float, float]] # [(pred_prob, actual_win_rate), ...]
    bucket_breakdown: List[BucketStats] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "brier_score": round(self.brier_score, 4),
            "log_loss": round(self.log_loss, 4),
            "expected_calibration_error": round(self.expected_calibration_error, 4),
            "maximum_calibration_error": round(self.maximum_calibration_error, 4),
            "total_samples": self.total_samples,
            "status": self.status,
            "reliability_curve": [[round(p, 3), round(w, 3)] for p, w in self.reliability_curve],
            "bucket_breakdown": [
                {
                    "bucket": b.bucket_label,
                    "count": b.count,
                    "mean_pred": round(b.mean_predicted_prob * 100, 1),
                    "actual_win_rate": round(b.actual_win_rate * 100, 1),
                    "error": round(b.calibration_error * 100, 1),
                }
                for b in self.bucket_breakdown
            ],
        }


class CalibrationEngine:
    """
    Evaluates confidence calibration across 9 discrete buckets specified in Section 18:
    50–55%, 55–60%, 60–65%, 65–70%, 70–75%, 75–80%, 80–85%, 85–90%, 90%+
    """

    BUCKET_RANGES = [
        ("50-55%", 0.50, 0.55),
        ("55-60%", 0.55, 0.60),
        ("60-65%", 0.60, 0.65),
        ("65-70%", 0.65, 0.70),
        ("70-75%", 0.70, 0.75),
        ("75-80%", 0.75, 0.80),
        ("80-85%", 0.80, 0.85),
        ("85-90%", 0.85, 0.90),
        ("90%+",   0.90, 1.001),
    ]

    @classmethod
    def evaluate(
        cls,
        predicted_probabilities: List[float],
        actual_outcomes: List[int],     # 1 for correct/win, 0 for incorrect/loss
        min_sample_size: int = 30,
    ) -> CalibrationResult:
        """
        Evaluate full calibration metrics and reliability curve.
        """
        if not predicted_probabilities or not actual_outcomes or len(predicted_probabilities) != len(actual_outcomes):
            return CalibrationResult(
                brier_score=0.25,
                log_loss=0.693,
                expected_calibration_error=0.0,
                maximum_calibration_error=0.0,
                total_samples=0,
                status="INSUFFICIENT_DATA",
                reliability_curve=[],
            )

        n = len(predicted_probabilities)

        # Normalize probabilities into [0.5, 1.0] conviction space if passed as directional P(UP)
        probs = []
        outcomes = []
        for p, o in zip(predicted_probabilities, actual_outcomes):
            prob = float(p)
            out = int(o)
            # Ensure prob is in [0.5, 1.0] for confidence evaluation
            if prob < 0.5:
                prob = 1.0 - prob
            probs.append(min(1.0, max(0.5, prob)))
            outcomes.append(out)

        # 1. Brier Score
        brier = sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / n

        # 2. Log Loss
        log_losses = []
        for p, o in zip(probs, outcomes):
            clamped_p = min(0.9999, max(0.0001, p))
            ll = -(o * math.log(clamped_p) + (1 - o) * math.log(1 - clamped_p))
            log_losses.append(ll)
        avg_ll = sum(log_losses) / n

        # 3. 9-Bucket Binning
        bucket_stats_list = []
        ece_acc = 0.0
        mce_val = 0.0
        curve = []

        for label, low, high in cls.BUCKET_RANGES:
            bin_indices = [i for i, p in enumerate(probs) if low <= p < high]
            count = len(bin_indices)
            if count > 0:
                bin_probs = [probs[i] for i in bin_indices]
                bin_outs = [outcomes[i] for i in bin_indices]
                mean_p = sum(bin_probs) / count
                win_rate = sum(bin_outs) / count
                cal_err = abs(mean_p - win_rate)

                ece_acc += (count / n) * cal_err
                mce_val = max(mce_val, cal_err)
                curve.append((mean_p, win_rate))

                bucket_stats_list.append(BucketStats(
                    bucket_label=label,
                    min_prob=low,
                    max_prob=high,
                    count=count,
                    mean_predicted_prob=mean_p,
                    actual_win_rate=win_rate,
                    calibration_error=cal_err,
                ))
            else:
                bucket_stats_list.append(BucketStats(
                    bucket_label=label,
                    min_prob=low,
                    max_prob=high,
                    count=0,
                    mean_predicted_prob=(low + high) / 2.0,
                    actual_win_rate=0.0,
                    calibration_error=0.0,
                ))

        # Calibration Diagnosis
        if n < min_sample_size:
            status = "INSUFFICIENT_DATA"
        elif ece_acc > 0.12 or mce_val > 0.22:
            status = "MIS-CALIBRATED"
        else:
            status = "WELL_CALIBRATED"

        return CalibrationResult(
            brier_score=round(brier, 5),
            log_loss=round(avg_ll, 5),
            expected_calibration_error=round(ece_acc, 5),
            maximum_calibration_error=round(mce_val, 5),
            total_samples=n,
            status=status,
            reliability_curve=curve,
            bucket_breakdown=bucket_stats_list,
        )
