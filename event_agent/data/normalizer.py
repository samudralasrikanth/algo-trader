# =============================================================================
# event_agent/data/normalizer.py — Data Normalization Utilities
# =============================================================================
"""
Unit/scale normalization for macroeconomic and market data.

All normalization uses ONLY data available before the observation date
to prevent look-ahead bias in feature calculations.
"""

import logging
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def normalize_z_score(
    value: float,
    history: List[float],
    lookback_window: int = 252,
) -> float:
    """
    Z-score normalization using ONLY data available before the observation.

    Args:
        value: Current observation value
        history: List of historical values (chronological, EXCLUDING current)
        lookback_window: Number of historical observations to use

    Returns:
        Z-score of the current value relative to recent history
    """
    if not history:
        return 0.0

    # Use only the most recent lookback_window observations
    window = history[-lookback_window:]

    mean = np.mean(window)
    std = np.std(window)

    if std == 0 or np.isnan(std):
        return 0.0

    return float((value - mean) / std)


def normalize_percent_change(
    current: float,
    previous: float,
) -> float:
    """Calculate percentage change from previous to current."""
    if previous == 0 or np.isnan(previous):
        return 0.0
    return round(((current - previous) / abs(previous)) * 100, 4)


def normalize_basis_point_change(
    current: float,
    previous: float,
) -> float:
    """Calculate basis point change (for yields/rates)."""
    return round((current - previous) * 100, 2)  # 1bp = 0.01%


def rolling_mean(
    values: List[float],
    window: int = 20,
) -> Optional[float]:
    """Calculate rolling mean of the last `window` values."""
    if len(values) < window:
        return None
    return float(np.mean(values[-window:]))


def rolling_std(
    values: List[float],
    window: int = 20,
) -> Optional[float]:
    """Calculate rolling standard deviation of the last `window` values."""
    if len(values) < window:
        return None
    return float(np.std(values[-window:]))


def rolling_return(
    prices: List[float],
    lookback_days: int = 5,
) -> Optional[float]:
    """Calculate return over last `lookback_days`."""
    if len(prices) < lookback_days + 1:
        return None
    current = prices[-1]
    past = prices[-(lookback_days + 1)]
    if past == 0:
        return None
    return round(((current - past) / abs(past)) * 100, 4)


def realized_volatility(
    returns: List[float],
    window: int = 20,
    annualize_factor: int = 252,
) -> Optional[float]:
    """
    Calculate realized (historical) volatility.
    Returns annualized volatility as percentage.
    """
    if len(returns) < window:
        return None
    recent = returns[-window:]
    daily_vol = np.std(recent)
    annualized = daily_vol * np.sqrt(annualize_factor)
    return round(float(annualized) * 100, 2)


def safe_divide(
    numerator: float,
    denominator: float,
    default: float = 0.0,
) -> float:
    """Division with zero/NaN protection."""
    if denominator == 0 or np.isnan(denominator) or np.isnan(numerator):
        return default
    return numerator / denominator
