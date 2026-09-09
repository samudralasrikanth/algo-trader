# =============================================================================
# event_agent/data/point_in_time_store.py — Immutable Point-in-Time Data Store
# =============================================================================
"""
Point-in-time aware data store that prevents look-ahead bias.

Core guarantee:
    get_as_of(indicator, datetime) returns ONLY data whose
    release_date <= datetime. No future data ever leaks.

Stores observations in Supabase 'macro_observations' table with:
    indicator, value, observation_date, release_date, vintage, source, locked_at
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LookaheadError(Exception):
    """Raised when data from the future would be used in a prediction."""
    pass


class PointInTimeStore:
    """
    Immutable, vintage-aware data store.

    Data flows:
        Adapter → store() → DB
        Prediction engine → get_as_of() → only PIT-safe data

    Every observation is stored with:
        - observation_date: when the economic event occurred
        - release_date: when the data was first publicly available
        - vintage: the as-of date for the query (FRED vintages)
        - locked_at: when this record was written to the store
    """

    def __init__(self):
        self._local_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._supabase_available = False
        self._init_supabase()

    def _init_supabase(self):
        """Attempt to connect to Supabase for persistent storage."""
        try:
            from ..storage.supabase_ledger import is_supabase_configured, SUPABASE_URL, get_headers
            self._supabase_available = is_supabase_configured()
            if self._supabase_available:
                self._supabase_url = SUPABASE_URL
                self._get_headers = get_headers
        except ImportError:
            self._supabase_available = False

    def store(
        self,
        indicator: str,
        value: float,
        observation_date: str,
        release_date: str,
        source: str = "FRED",
        vintage: Optional[str] = None,
        expected: Optional[float] = None,
        surprise_raw: Optional[float] = None,
        surprise_normalized: Optional[float] = None,
    ) -> bool:
        """
        Store an observation immutably.
        Once stored, records cannot be modified — only new vintages added.
        """
        now = datetime.now(timezone.utc).isoformat()

        record = {
            "indicator": indicator,
            "value": value,
            "observation_date": observation_date,
            "release_date": release_date,
            "source": source,
            "vintage": vintage or release_date,
            "locked_at": now,
            "expected": expected,
            "surprise_raw": surprise_raw,
            "surprise_normalized": surprise_normalized,
        }

        # Store locally
        if indicator not in self._local_cache:
            self._local_cache[indicator] = []
        self._local_cache[indicator].append(record)

        # Store to Supabase
        if self._supabase_available:
            try:
                import requests
                url = f"{self._supabase_url}/rest/v1/macro_observations"
                resp = requests.post(
                    url,
                    headers=self._get_headers(True),
                    json=record,
                    timeout=10,
                )
                if resp.status_code not in [200, 201, 409]:
                    logger.warning(
                        "Supabase store(%s) returned %s: %s",
                        indicator, resp.status_code, resp.text[:200],
                    )
            except Exception as exc:
                logger.error("Supabase store(%s) failed: %s", indicator, exc)

        return True

    def get_as_of(
        self,
        indicator: str,
        as_of_datetime: datetime,
    ) -> Optional[Dict[str, Any]]:
        """
        Return the latest observation whose release_date <= as_of_datetime.
        This is the core anti-look-ahead mechanism.
        """
        as_of_str = as_of_datetime.strftime("%Y-%m-%dT%H:%M:%S")

        # Check local cache first
        observations = self._local_cache.get(indicator, [])
        available = [
            obs for obs in observations
            if obs.get("release_date", "") <= as_of_str
        ]

        if available:
            # Return the most recent available observation
            available.sort(key=lambda x: x.get("release_date", ""))
            return available[-1]

        # Check Supabase
        if self._supabase_available:
            try:
                import requests
                as_of_date = as_of_datetime.strftime("%Y-%m-%d")
                url = (
                    f"{self._supabase_url}/rest/v1/macro_observations"
                    f"?indicator=eq.{indicator}"
                    f"&release_date=lte.{as_of_date}"
                    f"&order=release_date.desc"
                    f"&limit=1"
                )
                resp = requests.get(url, headers=self._get_headers(False), timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if data:
                        return data[0]
            except Exception as exc:
                logger.error("Supabase get_as_of(%s) failed: %s", indicator, exc)

        return None

    def get_latest(self, indicator: str) -> Optional[Dict[str, Any]]:
        """Get the latest observation (no PIT restriction)."""
        observations = self._local_cache.get(indicator, [])
        if observations:
            return observations[-1]

        if self._supabase_available:
            try:
                import requests
                url = (
                    f"{self._supabase_url}/rest/v1/macro_observations"
                    f"?indicator=eq.{indicator}"
                    f"&order=release_date.desc"
                    f"&limit=1"
                )
                resp = requests.get(url, headers=self._get_headers(False), timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if data:
                        return data[0]
            except Exception as exc:
                logger.error("Supabase get_latest(%s) failed: %s", indicator, exc)

        return None

    def get_history(
        self,
        indicator: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get full history for an indicator, optionally filtered by date range."""
        observations = self._local_cache.get(indicator, [])
        if start_date:
            observations = [o for o in observations if o.get("observation_date", "") >= start_date]
        if end_date:
            observations = [o for o in observations if o.get("observation_date", "") <= end_date]
        return observations

    def validate_no_lookahead(
        self,
        prediction_timestamp: datetime,
        data_timestamps: List[datetime],
    ) -> bool:
        """
        Verify that NO data used in a prediction was released after
        the prediction was locked. Raises LookaheadError if violated.

        This is the enforcer of the central invariant:
            Every prediction must be reproducible from exactly the
            information that existed at the moment the prediction was locked.
        """
        for ts in data_timestamps:
            if ts > prediction_timestamp:
                raise LookaheadError(
                    f"LOOK-AHEAD VIOLATION: Data released at {ts.isoformat()} "
                    f"was used in prediction locked at {prediction_timestamp.isoformat()}. "
                    f"This invalidates the prediction's reproducibility."
                )
        return True
