# =============================================================================
# event_agent/intelligence/surprise_detector.py — Expectation vs Actual Surprise
# =============================================================================
"""
V3.5 Surprise Detection Engine.
Enforces the strict invariant:
    Actual - Expected = Surprise
If reliable expectations are available: computes standardized surprise metric.
If expectations are unavailable: explicitly marks EXPECTATION_DATA_UNAVAILABLE.
Never fabricates consensus or analyst numbers.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class SurpriseMeasurement:
    symbol: str
    event_type: str
    has_expectation: bool
    status: str                       # MEASURED or EXPECTATION_DATA_UNAVAILABLE
    actual_value: Optional[float]
    expected_value: Optional[float]
    surprise_delta: float             # actual - expected
    surprise_pct: Optional[float]
    surprise_class: str               # NONE, LOW_SURPRISE, MODERATE_SURPRISE, HIGH_SURPRISE, SHOCK

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "event_type": self.event_type,
            "has_expectation": self.has_expectation,
            "status": self.status,
            "actual_value": self.actual_value,
            "expected_value": self.expected_value,
            "surprise_delta": round(self.surprise_delta, 4),
            "surprise_pct": round(self.surprise_pct, 2) if self.surprise_pct is not None else None,
            "surprise_class": self.surprise_class,
        }


class SurpriseDetector:
    """
    Evaluates news catalysts and reports for genuine surprises vs priced-in expectations.
    """

    @classmethod
    def calculate_surprise(
        cls,
        symbol: str,
        event_type: str,
        actual_value: Optional[float] = None,
        expected_value: Optional[float] = None,
        std_dev: Optional[float] = None,
    ) -> SurpriseMeasurement:
        """
        Calculates surprise delta. If expected_value is missing, marks EXPECTATION_DATA_UNAVAILABLE.
        """
        if actual_value is None or expected_value is None:
            return SurpriseMeasurement(
                symbol=symbol,
                event_type=event_type,
                has_expectation=False,
                status="EXPECTATION_DATA_UNAVAILABLE",
                actual_value=actual_value,
                expected_value=expected_value,
                surprise_delta=0.0,
                surprise_pct=None,
                surprise_class="NONE",
            )

        delta = actual_value - expected_value

        if abs(expected_value) > 1e-6:
            pct = (delta / abs(expected_value)) * 100.0
        else:
            pct = None

        # Normalized z-score if std_dev available
        z = (delta / std_dev) if std_dev and std_dev > 0 else (delta / (abs(expected_value) * 0.1 + 1e-4))

        abs_z = abs(z)
        if abs_z < 0.5:
            s_class = "LOW_SURPRISE"
        elif abs_z < 1.5:
            s_class = "MODERATE_SURPRISE"
        elif abs_z < 3.0:
            s_class = "HIGH_SURPRISE"
        else:
            s_class = "SHOCK"

        return SurpriseMeasurement(
            symbol=symbol,
            event_type=event_type,
            has_expectation=True,
            status="MEASURED",
            actual_value=actual_value,
            expected_value=expected_value,
            surprise_delta=delta,
            surprise_pct=pct,
            surprise_class=s_class,
        )
