# =============================================================================
# event_agent/engine/event_engine.py — Macro Event Classification
# =============================================================================
"""
Classifies economic events and tracks their impact windows.
Wraps the existing event_calendar with first-class macro event types.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# First-class macro event types
MACRO_EVENT_TYPES = {
    "US_CPI_RELEASE":       {"impact_window_days": 3, "pre_anticipation_days": 5, "weight": 0.9},
    "US_NFP_RELEASE":       {"impact_window_days": 3, "pre_anticipation_days": 5, "weight": 0.8},
    "US_ISM_MFG":           {"impact_window_days": 2, "pre_anticipation_days": 3, "weight": 0.6},
    "US_ISM_SVC":           {"impact_window_days": 2, "pre_anticipation_days": 3, "weight": 0.6},
    "US_RETAIL_SALES":      {"impact_window_days": 2, "pre_anticipation_days": 3, "weight": 0.5},
    "FED_RATE_DECISION":    {"impact_window_days": 5, "pre_anticipation_days": 7, "weight": 1.0},
    "FED_MINUTES":          {"impact_window_days": 3, "pre_anticipation_days": 2, "weight": 0.7},
    "RBI_POLICY":           {"impact_window_days": 3, "pre_anticipation_days": 5, "weight": 0.9},
    "INDIA_CPI":            {"impact_window_days": 2, "pre_anticipation_days": 3, "weight": 0.7},
    "INDIA_GDP":            {"impact_window_days": 3, "pre_anticipation_days": 5, "weight": 0.8},
    "INDIA_PMI":            {"impact_window_days": 1, "pre_anticipation_days": 1, "weight": 0.5},
    "EARNINGS_SEASON_START":{"impact_window_days": 14, "pre_anticipation_days": 7, "weight": 0.7},
}


class EventEngine:
    """
    Tracks macro events and computes their impact on market state.

    Impact windows:
        - Pre-event anticipation: -Nd to -1d
        - Event day: 0d
        - Post-event reaction: +1d to +Md
        - Decay: exponential from +Md
    """

    def __init__(self, economic_calendar=None):
        self._calendar = economic_calendar

    def classify_event(
        self,
        event_type: str,
        release_date: datetime,
        surprise_magnitude: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Classify an event and determine its impact parameters."""
        config = MACRO_EVENT_TYPES.get(event_type, {
            "impact_window_days": 2,
            "pre_anticipation_days": 3,
            "weight": 0.5,
        })

        now = datetime.now(timezone.utc)
        days_to_event = (release_date - now).days

        # Determine event phase
        if days_to_event > config["pre_anticipation_days"]:
            phase = "PRE_ANTICIPATION_FAR"
            decay_factor = 0.1
        elif days_to_event > 0:
            phase = "PRE_ANTICIPATION"
            decay_factor = 1.0 - (days_to_event / (config["pre_anticipation_days"] + 1))
        elif days_to_event == 0:
            phase = "EVENT_DAY"
            decay_factor = 1.0
        elif abs(days_to_event) <= config["impact_window_days"]:
            phase = "POST_EVENT_REACTION"
            decay_factor = max(0.2, 1.0 - (abs(days_to_event) / (config["impact_window_days"] + 1)))
        else:
            phase = "DECAYED"
            decay_factor = max(0.0, 0.2 * (0.5 ** (abs(days_to_event) - config["impact_window_days"])))

        # Amplify for surprise magnitude
        surprise_amplifier = 1.0
        if surprise_magnitude is not None:
            if abs(surprise_magnitude) > 2.0:
                surprise_amplifier = 2.0
            elif abs(surprise_magnitude) > 1.0:
                surprise_amplifier = 1.5

        impact_score = round(config["weight"] * decay_factor * surprise_amplifier, 3)

        return {
            "event_type": event_type,
            "release_date": release_date.isoformat(),
            "phase": phase,
            "days_to_event": days_to_event,
            "base_weight": config["weight"],
            "decay_factor": round(decay_factor, 3),
            "surprise_amplifier": surprise_amplifier,
            "impact_score": impact_score,
            "impact_window_days": config["impact_window_days"],
        }

    def get_active_events(
        self,
        current_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Get all events currently in their impact window."""
        if not self._calendar:
            return []

        recent = self._calendar.get_recent_events(days_back=30)
        active = []

        for event in recent:
            try:
                rel_date_str = event.get("release_date", "")
                if "T" in rel_date_str:
                    rel_date = datetime.fromisoformat(rel_date_str)
                else:
                    rel_date = datetime.strptime(rel_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

                indicator = event.get("indicator", "")
                surprise = event.get("surprise_raw")

                classified = self.classify_event(
                    event_type=indicator,
                    release_date=rel_date,
                    surprise_magnitude=surprise,
                )

                if classified["phase"] not in ["DECAYED", "PRE_ANTICIPATION_FAR"]:
                    classified["event_data"] = event
                    active.append(classified)
            except (ValueError, TypeError):
                continue

        active.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
        return active

    def compute_composite_event_impact(
        self,
        active_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Compute aggregate event impact score."""
        events = active_events or self.get_active_events()

        if not events:
            return {
                "composite_impact": 0.0,
                "dominant_event": None,
                "active_event_count": 0,
                "phase": "QUIET",
            }

        scores = [e.get("impact_score", 0) for e in events]
        dominant = events[0] if events else None

        return {
            "composite_impact": round(sum(scores), 3),
            "dominant_event": dominant.get("event_type") if dominant else None,
            "dominant_phase": dominant.get("phase") if dominant else None,
            "active_event_count": len(events),
            "phase": "HIGH_IMPACT" if sum(scores) > 2.0 else "MODERATE" if sum(scores) > 0.5 else "LOW",
        }
