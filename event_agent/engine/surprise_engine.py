# =============================================================================
# event_agent/engine/surprise_engine.py — Robust Normalized Surprise Calculator
# =============================================================================
"""
Computes normalized economic surprises using a robust hierarchy:

    1. Historical surprise σ (if >= 20 observations)
    2. MAD-based robust dispersion (if >= 5 observations)
    3. Indicator-specific configured fallback (typical_surprise_std)
    4. NEVER uses abs(consensus * 0.01) — that is statistically meaningless.
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def calculate_surprise(
    actual: float,
    consensus: float,
    historical_surprises: List[float],
    indicator_config: Dict[str, Any],
    consensus_metadata: Dict[str, Any],
    previous_value: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Calculate a robust normalized surprise for a macro release.

    Args:
        actual: Released actual value
        consensus: Pre-locked consensus expectation
        historical_surprises: List of past raw surprises (actual - consensus)
        indicator_config: From indicator_registry (has typical_surprise_std)
        consensus_metadata: source, entered_at, release_date
        previous_value: Previous observation value

    Returns:
        Structured surprise record with normalization metadata
    """
    raw_surprise = actual - consensus

    # ---------------------------------------------------------------
    # Robust normalization hierarchy
    # ---------------------------------------------------------------
    normalization_method = None
    surprise_std = None

    if len(historical_surprises) >= 20:
        # Best: historical surprise standard deviation
        surprise_std = float(np.std(historical_surprises))
        normalization_method = "historical_std"

    elif len(historical_surprises) >= 5:
        # Good: MAD-based robust dispersion
        median = np.median(historical_surprises)
        mad = float(np.median(np.abs(
            np.array(historical_surprises) - median
        )))
        surprise_std = mad * 1.4826  # MAD to σ conversion
        normalization_method = "MAD_robust"

    else:
        # Fallback: indicator-specific configured value
        surprise_std = indicator_config.get("typical_surprise_std", 0.2)
        normalization_method = "configured_fallback"

    # Guard against zero/tiny std
    surprise_std = max(surprise_std, 1e-6)
    normalized_surprise = raw_surprise / surprise_std

    # Magnitude classification
    abs_norm = abs(normalized_surprise)
    if abs_norm > 2.0:
        magnitude = "EXTREME"
    elif abs_norm > 1.0:
        magnitude = "LARGE"
    elif abs_norm > 0.5:
        magnitude = "MODERATE"
    else:
        magnitude = "INLINE"

    return {
        "indicator": indicator_config.get("semantic_name", "unknown"),
        "indicator_id": indicator_config.get("indicator_id", ""),
        "actual": round(actual, 6),
        "consensus": round(consensus, 6),
        "previous": previous_value,
        "raw_surprise": round(raw_surprise, 6),
        "surprise_std_used": round(surprise_std, 6),
        "normalized_surprise_sigma": round(normalized_surprise, 2),
        "normalization_method": normalization_method,
        "historical_sample_count": len(historical_surprises),
        "surprise_direction": "UPSIDE" if raw_surprise > 0 else "DOWNSIDE" if raw_surprise < 0 else "INLINE",
        "magnitude": magnitude,
        "release_timestamp": consensus_metadata.get("release_date"),
        "consensus_source": consensus_metadata.get("source", "manual"),
        "consensus_locked_at": consensus_metadata.get("entered_at"),
    }


def aggregate_surprises(
    surprises: List[Dict[str, Any]],
    lookback_days: int = 30,
) -> Dict[str, Any]:
    """
    Aggregate multiple surprises into a composite macro surprise score.
    Used as a feature in the regime engine.
    """
    if not surprises:
        return {
            "composite_surprise_sigma": 0.0,
            "direction": "NEUTRAL",
            "count": 0,
            "extreme_count": 0,
        }

    normalized = [s["normalized_surprise_sigma"] for s in surprises]
    composite = float(np.mean(normalized))
    extreme_count = sum(1 for s in surprises if s["magnitude"] == "EXTREME")

    return {
        "composite_surprise_sigma": round(composite, 2),
        "direction": "HAWKISH" if composite > 0.5 else "DOVISH" if composite < -0.5 else "NEUTRAL",
        "count": len(surprises),
        "extreme_count": extreme_count,
        "max_surprise": round(float(max(normalized)), 2) if normalized else 0,
        "min_surprise": round(float(min(normalized)), 2) if normalized else 0,
    }
