# =============================================================================
# event_agent/certification/feature_availability_audit.py — Feature Causality Auditor
# =============================================================================
"""
V3.6 Feature Availability & Causal Timestamp Auditor.
Enforces the complete 7-stage chronological invariant:
  event_available_at <= feature_available_at <= prediction_generated_at
  < order_created_at <= order_arrival_at <= fill_at < exit_at

Guarantees that derived technical, sentiment, and regime features contain
ZERO information published after prediction_generated_at.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TimestampCausalityRecord:
    trade_id: str
    symbol: str
    event_available_at: datetime
    feature_available_at: datetime
    prediction_generated_at: datetime
    order_created_at: datetime
    order_arrival_at: datetime
    fill_at: datetime
    exit_at: Optional[datetime]
    is_causally_valid: bool
    violations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "event_available_at": self.event_available_at.isoformat(),
            "feature_available_at": self.feature_available_at.isoformat(),
            "prediction_generated_at": self.prediction_generated_at.isoformat(),
            "order_created_at": self.order_created_at.isoformat(),
            "order_arrival_at": self.order_arrival_at.isoformat(),
            "fill_at": self.fill_at.isoformat(),
            "exit_at": self.exit_at.isoformat() if self.exit_at else None,
            "is_causally_valid": self.is_causally_valid,
            "violations": self.violations,
        }


class FeatureAvailabilityAuditor:
    """
    Validates chronological sequence of all 7 pipeline timestamps.
    """

    @classmethod
    def audit_pipeline_timestamps(
        cls,
        trade_id: str,
        symbol: str,
        event_available_at: datetime,
        feature_available_at: datetime,
        prediction_generated_at: datetime,
        order_created_at: datetime,
        order_arrival_at: datetime,
        fill_at: datetime,
        exit_at: Optional[datetime] = None,
    ) -> TimestampCausalityRecord:
        """
        Verifies all 6 pairwise inequalities across the 7 milestones.
        """
        violations = []

        # Invariant 1: event_available_at <= feature_available_at
        if event_available_at > feature_available_at:
            violations.append(
                f"Feature lookahead: event published ({event_available_at}) after feature computation ({feature_available_at})."
            )

        # Invariant 2: feature_available_at <= prediction_generated_at
        if feature_available_at > prediction_generated_at:
            violations.append(
                f"Feature leakage: feature ({feature_available_at}) computed after prediction was generated ({prediction_generated_at})."
            )

        # Invariant 3: prediction_generated_at < order_created_at (strictly prior)
        if prediction_generated_at >= order_created_at:
            violations.append(
                f"Prediction timing error: prediction timestamp ({prediction_generated_at}) >= order creation ({order_created_at})."
            )

        # Invariant 4: order_created_at <= order_arrival_at
        if order_created_at > order_arrival_at:
            violations.append(
                f"Broker routing inverted: order created ({order_created_at}) after exchange arrival ({order_arrival_at})."
            )

        # Invariant 5: order_arrival_at <= fill_at
        if order_arrival_at > fill_at:
            violations.append(
                f"Execution causality error: arrival ({order_arrival_at}) after fill timestamp ({fill_at})."
            )

        # Invariant 6: fill_at < exit_at (if trade closed)
        if exit_at is not None and fill_at >= exit_at:
            violations.append(
                f"Position lifecyle error: fill ({fill_at}) >= exit timestamp ({exit_at})."
            )

        valid = (len(violations) == 0)
        return TimestampCausalityRecord(
            trade_id=trade_id,
            symbol=symbol,
            event_available_at=event_available_at,
            feature_available_at=feature_available_at,
            prediction_generated_at=prediction_generated_at,
            order_created_at=order_created_at,
            order_arrival_at=order_arrival_at,
            fill_at=fill_at,
            exit_at=exit_at,
            is_causally_valid=valid,
            violations=violations,
        )

    @classmethod
    def audit_feature_window(
        cls,
        feature_name: str,
        feature_end_timestamp: datetime,
        decision_timestamp: datetime,
    ) -> Tuple[bool, Optional[str]]:
        """
        Confirms rolling feature windows (e.g. 20D SMA, 14D RSI) end strictly <= decision_timestamp.
        """
        if feature_end_timestamp > decision_timestamp:
            delta_sec = (feature_end_timestamp - decision_timestamp).total_seconds()
            return False, f"Feature '{feature_name}' contains data {delta_sec:.1f}s after decision timestamp."
        return True, None
