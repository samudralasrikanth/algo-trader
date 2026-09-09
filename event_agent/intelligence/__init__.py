# =============================================================================
# event_agent/intelligence/__init__.py — Intelligence & Analogue Engine
# =============================================================================
"""
V3.5 Intelligence Engine providing historical event analogues, surprise detection,
market context scoring, market breadth, volatility regime conditioning,
and point-in-time fundamentals.
"""

from .event_analogue import HistoricalEventAnalogueEngine, EventTaxonomy, StandardizedEvent
from .surprise_detector import SurpriseDetector, SurpriseMeasurement
from .market_context import MarketContextEngine, MarketContextScore, VolatilityMetrics, BreadthMetrics

__all__ = [
    "HistoricalEventAnalogueEngine",
    "EventTaxonomy",
    "StandardizedEvent",
    "SurpriseDetector",
    "SurpriseMeasurement",
    "MarketContextEngine",
    "MarketContextScore",
    "VolatilityMetrics",
    "BreadthMetrics",
]
