# =============================================================================
# event_agent/data/validation.py — Data Quality Validation
# =============================================================================
"""
Data quality checks for all adapter outputs.
Detects missing values, stale data, outliers, and cross-source inconsistencies.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class DataQualityWarning:
    """Structured data quality warning."""

    def __init__(self, indicator: str, issue: str, severity: str, details: str):
        self.indicator = indicator
        self.issue = issue
        self.severity = severity  # "INFO", "WARNING", "ERROR"
        self.details = details
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def __repr__(self):
        return f"[{self.severity}] {self.indicator}: {self.issue} — {self.details}"

    def to_dict(self) -> Dict[str, str]:
        return {
            "indicator": self.indicator,
            "issue": self.issue,
            "severity": self.severity,
            "details": self.details,
            "timestamp": self.timestamp,
        }


def validate_observation(
    indicator: str,
    value: Optional[float],
    observation_date: Optional[str] = None,
    history: Optional[List[float]] = None,
) -> List[DataQualityWarning]:
    """
    Validate a single observation for data quality issues.

    Checks:
        1. Missing value (None or NaN)
        2. Outlier detection (>5σ from rolling mean)
        3. Duplicate detection (same value as previous N)
    """
    warnings = []

    # 1. Missing value
    if value is None or (isinstance(value, float) and np.isnan(value)):
        warnings.append(DataQualityWarning(
            indicator=indicator,
            issue="MISSING_VALUE",
            severity="WARNING",
            details=f"No value available for {indicator} on {observation_date or 'latest'}.",
        ))
        return warnings  # Can't check further without a value

    # 2. Outlier detection
    if history and len(history) >= 20:
        mean = np.mean(history[-252:])  # 1-year lookback
        std = np.std(history[-252:])
        if std > 0:
            z_score = abs(value - mean) / std
            if z_score > 5.0:
                warnings.append(DataQualityWarning(
                    indicator=indicator,
                    issue="EXTREME_OUTLIER",
                    severity="WARNING",
                    details=f"Value {value} is {z_score:.1f}σ from rolling mean {mean:.2f}. "
                            f"Manual review recommended.",
                ))
            elif z_score > 3.0:
                warnings.append(DataQualityWarning(
                    indicator=indicator,
                    issue="POSSIBLE_OUTLIER",
                    severity="INFO",
                    details=f"Value {value} is {z_score:.1f}σ from rolling mean {mean:.2f}.",
                ))

    # 3. Duplicate/stuck detection
    if history and len(history) >= 5:
        last_5 = history[-5:]
        if len(set(last_5)) == 1 and last_5[0] == value:
            warnings.append(DataQualityWarning(
                indicator=indicator,
                issue="STUCK_VALUE",
                severity="WARNING",
                details=f"Value {value} has been unchanged for 6+ consecutive observations. "
                        f"Possible data feed issue.",
            ))

    return warnings


def validate_staleness(
    indicator: str,
    last_updated: Optional[str],
    expected_frequency: str = "daily",
) -> List[DataQualityWarning]:
    """
    Check if data is stale (older than expected update frequency).
    """
    warnings = []

    if not last_updated:
        warnings.append(DataQualityWarning(
            indicator=indicator,
            issue="NO_UPDATE_TIMESTAMP",
            severity="WARNING",
            details="No last_updated timestamp available.",
        ))
        return warnings

    try:
        last_dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return warnings

    now = datetime.now(timezone.utc)
    age = now - last_dt

    # Staleness thresholds by frequency
    thresholds = {
        "daily": timedelta(hours=36),
        "weekly": timedelta(days=10),
        "monthly": timedelta(days=45),
        "quarterly": timedelta(days=120),
        "event_driven": timedelta(days=180),
    }

    threshold = thresholds.get(expected_frequency, timedelta(days=7))

    if age > threshold:
        warnings.append(DataQualityWarning(
            indicator=indicator,
            issue="STALE_DATA",
            severity="WARNING",
            details=f"Data is {age.days}d {age.seconds//3600}h old. "
                    f"Expected update frequency: {expected_frequency}. "
                    f"Threshold: {threshold}.",
        ))

    return warnings


def validate_cross_source(
    indicator: str,
    value_a: Optional[float],
    value_b: Optional[float],
    source_a: str = "source_1",
    source_b: str = "source_2",
    tolerance_pct: float = 2.0,
) -> List[DataQualityWarning]:
    """
    Compare values from two different sources.
    Flags if they diverge beyond tolerance.
    """
    warnings = []

    if value_a is None or value_b is None:
        return warnings

    if value_a == 0 and value_b == 0:
        return warnings

    denominator = max(abs(value_a), abs(value_b), 1e-10)
    pct_diff = abs(value_a - value_b) / denominator * 100

    if pct_diff > tolerance_pct:
        warnings.append(DataQualityWarning(
            indicator=indicator,
            issue="CROSS_SOURCE_DIVERGENCE",
            severity="WARNING",
            details=f"{source_a}={value_a}, {source_b}={value_b}. "
                    f"Divergence: {pct_diff:.1f}% (threshold: {tolerance_pct}%).",
        ))

    return warnings


def run_full_validation(
    data_snapshot: Dict[str, Any],
    indicator_registry: Dict[str, Dict[str, Any]],
) -> List[DataQualityWarning]:
    """
    Run all validation checks on a complete data snapshot.
    Returns list of all warnings sorted by severity.
    """
    all_warnings = []

    for indicator_id, meta in indicator_registry.items():
        obs = data_snapshot.get(indicator_id)
        if obs is None:
            all_warnings.append(DataQualityWarning(
                indicator=indicator_id,
                issue="MISSING_INDICATOR",
                severity="WARNING",
                details=f"Indicator {indicator_id} not found in data snapshot.",
            ))
            continue

        value = obs.get("value") if isinstance(obs, dict) else obs
        obs_date = obs.get("observation_date") if isinstance(obs, dict) else None
        fetched_at = obs.get("fetched_at") if isinstance(obs, dict) else None

        # Validate observation
        all_warnings.extend(validate_observation(indicator_id, value, obs_date))

        # Validate staleness
        frequency = meta.get("frequency", "daily")
        all_warnings.extend(validate_staleness(indicator_id, fetched_at, frequency))

    # Sort by severity
    severity_order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    all_warnings.sort(key=lambda w: severity_order.get(w.severity, 3))

    return all_warnings
