# =============================================================================
# event_agent/research/__init__.py — Quantitative Research & Model Evaluation
# =============================================================================

from .model_versioning import (
    VERSION_RECORD,
    CURRENT_VERSION,
    ModelVersionManager,
    get_current_version_record,
    get_model_version,
)
from .baseline_models import (
    RandomBaseline,
    PreviousDayBaseline,
    MomentumBaseline,
    MeanReversionBaseline,
    BuyAndHoldBaseline,
    BaselineSuite,
)
from .factor_evaluation import evaluate_factor, FactorEvaluator
from .walk_forward import WalkForwardValidator, LearningLoop, PointInTimeError
from .backtester import BacktestEngine

__all__ = [
    "VERSION_RECORD",
    "CURRENT_VERSION",
    "ModelVersionManager",
    "get_current_version_record",
    "get_model_version",
    "RandomBaseline",
    "PreviousDayBaseline",
    "MomentumBaseline",
    "MeanReversionBaseline",
    "BuyAndHoldBaseline",
    "BaselineSuite",
    "evaluate_factor",
    "FactorEvaluator",
    "WalkForwardValidator",
    "LearningLoop",
    "PointInTimeError",
    "BacktestEngine",
]
