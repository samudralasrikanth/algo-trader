# =============================================================================
# event_agent/fundamentals/fundamental_cache.py — Periodic Refresh Fundamental Cache
# =============================================================================
"""
Cache for point-in-time fundamental snapshots.
Enforces the fundamental refresh architecture:
- Financial statements / Profitability: Quarterly
- Valuation multiples: Daily EOD
- Corporate actions / Earnings: Event-driven
Prevents wasteful polling every 5 minutes during intraday trading.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional
from .fundamental_snapshot import FundamentalSnapshot

logger = logging.getLogger(__name__)


class FundamentalCache:
    """
    In-memory and persistent cache for FundamentalSnapshot records.
    """

    DEFAULT_CACHE_TTL_HOURS: float = 24.0  # Daily refresh by default

    def __init__(self, ttl_hours: float = DEFAULT_CACHE_TTL_HOURS):
        self.ttl_hours = ttl_hours
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get(self, symbol: str, as_of_dt: Optional[datetime] = None) -> Optional[FundamentalSnapshot]:
        """
        Retrieves snapshot if present and fresh relative to as_of_dt.
        """
        entry = self._cache.get(symbol)
        if not entry:
            return None

        cached_snapshot: FundamentalSnapshot = entry["snapshot"]
        cached_at: datetime = entry["cached_at"]

        now_ref = as_of_dt or datetime.now(timezone.utc)
        if now_ref.tzinfo is None and cached_at.tzinfo is not None:
            now_ref = now_ref.replace(tzinfo=timezone.utc)
        elif now_ref.tzinfo is not None and cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)

        age_hours = (now_ref - cached_at).total_seconds() / 3600.0
        if age_hours > self.ttl_hours:
            logger.debug(f"Cache expired for {symbol} (age: {age_hours:.1f}h > {self.ttl_hours}h).")
            return None

        return cached_snapshot

    def put(self, symbol: str, snapshot: FundamentalSnapshot, cached_at: Optional[datetime] = None) -> None:
        """
        Stores snapshot in cache.
        """
        ts = cached_at or datetime.now(timezone.utc)
        self._cache[symbol] = {
            "snapshot": snapshot,
            "cached_at": ts,
        }

    def clear(self) -> None:
        self._cache.clear()

    def size(self) -> int:
        return len(self._cache)
