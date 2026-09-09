# =============================================================================
# event_agent/engine/__init__.py
# =============================================================================

from .sentiment_analyzer import analyze_news_sentiment, analyze_text_sentiment
from .prediction_algo import generate_stock_prediction, generate_all_predictions, MODEL_VERSION
from .calibration import (
    calibrate_confidence,
    compute_brier_score,
    compute_expected_calibration_error,
    is_confidence_miscalibration,
    CALIBRATION_VERSION,
)
from .feature_engine import compute_features
from .surprise_engine import calculate_surprise
from .market_state import MarketState
from .event_engine import EventEngine
from .regime_detector import detect_regime, REGIME_WEIGHTS_V1

__all__ = [
    "analyze_news_sentiment",
    "analyze_text_sentiment",
    "generate_stock_prediction",
    "generate_all_predictions",
    "MODEL_VERSION",
    "calibrate_confidence",
    "compute_brier_score",
    "compute_expected_calibration_error",
    "is_confidence_miscalibration",
    "CALIBRATION_VERSION",
    "compute_features",
    "calculate_surprise",
    "MarketState",
    "EventEngine",
    "detect_regime",
    "REGIME_WEIGHTS_V1",
]
