# =============================================================================
# event_agent/adapters/economic_calendar.py — Timestamp-Locked Consensus
# =============================================================================
"""
Manages economic event consensus values with timestamp locking.

Key properties:
    - Consensus MUST be entered BEFORE the release timestamp
    - Rejects post-release consensus entries (prevents look-ahead)
    - Records source, source_timestamp, entered_at for auditability
    - Computes surprise = actual - consensus automatically
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CALENDAR_PATH = Path(__file__).resolve().parents[2] / "data" / "economic_calendar.json"


class ConsensusLockError(Exception):
    """Raised when consensus is entered after the release timestamp."""
    pass


class EconomicCalendar:
    """
    Manages economic event consensus and actual values.

    Flow:
        1. BEFORE release: lock_consensus(indicator, expected, release_date)
        2. AFTER release: record_actual(indicator, actual, release_date)
        3. Surprise computed automatically = actual - consensus
    """

    def __init__(self):
        self._events: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        if _CALENDAR_PATH.exists():
            try:
                with open(_CALENDAR_PATH, "r") as f:
                    self._events = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._events = {}

    def _save(self):
        _CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CALENDAR_PATH, "w") as f:
            json.dump(self._events, f, indent=2, default=str)

    def lock_consensus(
        self,
        indicator: str,
        expected_value: float,
        release_date: datetime,
        source: str = "manual",
        source_timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Lock a consensus value BEFORE the release date.
        Rejects if current time >= release_date.
        """
        now = datetime.now(timezone.utc)

        # Reject post-release consensus entries
        if now >= release_date:
            raise ConsensusLockError(
                f"Cannot enter consensus after release ({release_date.isoformat()}). "
                f"Current time: {now.isoformat()}. "
                f"This would constitute look-ahead bias."
            )

        event_key = f"{indicator}:{release_date.strftime('%Y-%m-%d')}"

        record = {
            "indicator": indicator,
            "consensus_value": expected_value,
            "source": source,
            "source_timestamp": source_timestamp or now.isoformat(),
            "entered_at": now.isoformat(),
            "release_date": release_date.isoformat(),
            "locked": True,
            "actual_value": None,
            "surprise_raw": None,
            "surprise_direction": None,
        }

        self._events[event_key] = record
        self._save()

        logger.info(
            "Consensus locked: %s = %.4f (release: %s, source: %s)",
            indicator, expected_value, release_date.isoformat(), source,
        )
        return record

    def record_actual(
        self,
        indicator: str,
        actual_value: float,
        release_date: datetime,
        source: str = "official",
    ) -> Dict[str, Any]:
        """
        Record the actual value after release.
        Computes surprise automatically if consensus exists.
        """
        event_key = f"{indicator}:{release_date.strftime('%Y-%m-%d')}"
        now = datetime.now(timezone.utc)

        record = self._events.get(event_key, {})

        record["actual_value"] = actual_value
        record["actual_recorded_at"] = now.isoformat()
        record["actual_source"] = source

        # Compute surprise if consensus was locked
        consensus = record.get("consensus_value")
        if consensus is not None:
            surprise = actual_value - consensus
            record["surprise_raw"] = round(surprise, 6)
            record["surprise_direction"] = (
                "UPSIDE" if surprise > 0
                else "DOWNSIDE" if surprise < 0
                else "INLINE"
            )
            logger.info(
                "Actual recorded: %s = %.4f (consensus: %.4f, surprise: %.4f %s)",
                indicator, actual_value, consensus, surprise,
                record["surprise_direction"],
            )
        else:
            record["surprise_raw"] = None
            record["surprise_direction"] = None
            logger.info(
                "Actual recorded: %s = %.4f (no prior consensus)",
                indicator, actual_value,
            )

        self._events[event_key] = record
        self._save()
        return record

    def get_event(
        self,
        indicator: str,
        release_date: datetime,
    ) -> Optional[Dict[str, Any]]:
        """Get a specific calendar event."""
        event_key = f"{indicator}:{release_date.strftime('%Y-%m-%d')}"
        return self._events.get(event_key)

    def get_recent_events(
        self,
        days_back: int = 30,
        indicator: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent calendar events, optionally filtered by indicator."""
        now = datetime.now(timezone.utc)
        cutoff = now.isoformat()[:10]

        results = []
        for key, event in self._events.items():
            rel_date = event.get("release_date", "")[:10]
            if indicator and event.get("indicator") != indicator:
                continue
            results.append(event)

        results.sort(key=lambda x: x.get("release_date", ""), reverse=True)
        return results[:50]

    def get_pending_releases(self) -> List[Dict[str, Any]]:
        """Get events with consensus locked but no actual recorded yet."""
        return [
            e for e in self._events.values()
            if e.get("locked") and e.get("actual_value") is None
        ]

    def get_recent_surprises(
        self,
        indicator: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get recent events that have both consensus and actual (i.e., have surprise)."""
        events = [
            e for e in self._events.values()
            if e.get("surprise_raw") is not None
        ]
        if indicator:
            events = [e for e in events if e.get("indicator") == indicator]
        events.sort(key=lambda x: x.get("release_date", ""), reverse=True)
        return events[:limit]
