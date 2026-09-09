# =============================================================================
# event_agent/prediction/__init__.py — NEXUS V3.5 Prediction Validation Engine
# =============================================================================
"""
NEXUS V3.5 Prediction Validation & Intelligence Engine.
Provides immutable prediction ledgers, outcome resolution, calibration metrics,
baselines comparison, agent independence, walk-forward evaluation, and
anti-leakage validation.
"""

from .ledger import PredictionLedger, PredictionRecord, HORIZONS_SUPPORTED
from .outcome_engine import OutcomeEngine, PredictionOutcome
from .distribution import ReturnDistributionModel, CredibleIntervals
from .calibration_metrics import CalibrationEngine, CalibrationResult
from .no_trade_engine import NoTradeEngine, NoTradeDecision

__all__ = [
    "PredictionLedger",
    "PredictionRecord",
    "HORIZONS_SUPPORTED",
    "OutcomeEngine",
    "PredictionOutcome",
    "ReturnDistributionModel",
    "CredibleIntervals",
    "CalibrationEngine",
    "CalibrationResult",
    "NoTradeEngine",
    "NoTradeDecision",
]
