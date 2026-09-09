# =============================================================================
# event_agent/adapters/base_adapter.py — Abstract Data Adapter Interface
# =============================================================================
"""
All data adapters must implement this interface.
Provides point-in-time aware data access to prevent look-ahead bias.
"""

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd


class BaseAdapter(ABC):
    """Abstract base class for all data adapters."""

    @abstractmethod
    def fetch_series(
        self,
        series_id: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Fetch a time series of observations.

        Returns DataFrame with columns:
            observation_date, value, release_date, vintage
        """
        ...

    @abstractmethod
    def get_latest(self, series_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the most recent observation for a series.

        Returns:
            {
                "series_id": str,
                "observation_date": str,
                "value": float,
                "release_date": str,
                "fetched_at": str (ISO timestamp),
            }
        """
        ...

    @abstractmethod
    def get_as_of(
        self,
        series_id: str,
        as_of_datetime: datetime,
    ) -> Optional[Dict[str, Any]]:
        """
        Return the value that was known at *as_of_datetime* (point-in-time).
        Only returns data whose release_date <= as_of_datetime.
        This is the core anti-look-ahead mechanism.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this adapter is currently functional."""
        ...

    # --------------------------------------------------------------------- #
    # Shared helpers
    # --------------------------------------------------------------------- #
    def validate_response(self, data: Any) -> bool:
        """Basic data-quality check: non-null, non-empty, plausible."""
        if data is None:
            return False
        if isinstance(data, pd.DataFrame) and data.empty:
            return False
        if isinstance(data, dict) and data.get("value") is None:
            return False
        return True
