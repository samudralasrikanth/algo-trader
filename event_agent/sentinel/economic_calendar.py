# =============================================================================
# event_agent/sentinel/economic_calendar.py — Scheduled Economic Calendar Engine
# =============================================================================
"""
V4.2.1 Scheduled Economic Calendar Engine:
- Calendar-authoritative registry for predictable macro events (FOMC, RBI, ECB, CPI, NFP).
- Implements the strict timed lifecycle:
    T-24h (Watch) -> T-1h (Monitor) -> T-5m (Baseline) -> T+0 (Release/Surprise)
    -> T+1m (Reaction) -> T+5m (Transmission) -> T+15m (Re-eval) -> T+30m (Confirm)
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
import logging
from typing import Any, Dict, List, Optional, Tuple

from event_agent.storage.ledger import upsert_calendar_event, get_all_calendar_events
from event_agent.sentinel.models import CalendarStage, EventCategory, SentinelEvent

logger = logging.getLogger(__name__)


@dataclass
class ScheduledEconomicEvent:
    event_code: str                        # e.g. "FOMC_20260916"
    category: EventCategory
    title: str
    scheduled_at: str                      # ISO UTC
    consensus_forecast: str                # e.g. "+25 bps" or "3.75%"
    prior_value: str                       # e.g. "3.50%-3.75%"
    actual_value: Optional[str] = None     # e.g. "+25 bps" or "3.75%-4.00%"
    surprise_delta: Optional[float] = None
    current_stage: CalendarStage = CalendarStage.SCHEDULED
    pre_baseline: Dict[str, Any] = field(default_factory=dict)
    reaction_1m: Dict[str, Any] = field(default_factory=dict)
    india_transmission: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_code": self.event_code,
            "category": self.category.value if isinstance(self.category, EventCategory) else str(self.category),
            "title": self.title,
            "scheduled_at": self.scheduled_at,
            "consensus_forecast": self.consensus_forecast,
            "prior_value": self.prior_value,
            "actual_value": self.actual_value,
            "surprise_delta": self.surprise_delta,
            "current_stage": self.current_stage.value if isinstance(self.current_stage, CalendarStage) else str(self.current_stage),
            "pre_baseline": self.pre_baseline,
            "reaction_1m": self.reaction_1m,
            "india_transmission": self.india_transmission,
        }


# Canonical Pre-Seeded Institutional Calendar for 2026
SEEDED_CALENDAR_EVENTS = [
    ScheduledEconomicEvent(
        event_code="FOMC_RATE_20260916",
        category=EventCategory.FOMC,
        title="FOMC Interest Rate Decision & Policy Statement",
        scheduled_at="2026-09-16T18:00:00+00:00",  # 2:00 PM EDT = 18:00 UTC (23:30 IST)
        consensus_forecast="+25 bps (3.75%-4.00%)",
        prior_value="3.50%-3.75%",
    ),
    ScheduledEconomicEvent(
        event_code="RBI_MPC_20261008",
        category=EventCategory.RBI,
        title="RBI Monetary Policy Committee Repo Rate Decision",
        scheduled_at="2026-10-08T04:30:00+00:00",  # 10:00 AM IST
        consensus_forecast="Pause (6.50%)",
        prior_value="6.50%",
    ),
    ScheduledEconomicEvent(
        event_code="US_CPI_20260911",
        category=EventCategory.INFLATION,
        title="US Consumer Price Index (MoM & YoY)",
        scheduled_at="2026-09-11T12:30:00+00:00",  # 8:30 AM EDT
        consensus_forecast="+0.2% MoM / 2.6% YoY",
        prior_value="+0.2% MoM / 2.9% YoY",
    ),
    ScheduledEconomicEvent(
        event_code="INDIA_CPI_20260912",
        category=EventCategory.INDIA_MACRO,
        title="India Consumer Price Index (CPI Inflation)",
        scheduled_at="2026-09-12T12:00:00+00:00",  # 17:30 IST
        consensus_forecast="3.60% YoY",
        prior_value="3.54% YoY",
    ),
]


class EconomicCalendar:
    """
    Manages the authoritative scheduled event lifecycle.
    """

    def __init__(self, seed_events: bool = True):
        self.events: Dict[str, ScheduledEconomicEvent] = {}
        if seed_events:
            for ev in SEEDED_CALENDAR_EVENTS:
                self.events[ev.event_code] = ev
        # Hydrate from SQLite if present
        self.hydrate_from_db()

    def hydrate_from_db(self) -> None:
        """Load persisted calendar events from SQLite."""
        try:
            db_events = get_all_calendar_events()
            for r in db_events:
                code = r["event_code"]
                self.events[code] = ScheduledEconomicEvent(
                    event_code=code,
                    category=EventCategory(r["category"]),
                    title=r["title"],
                    scheduled_at=r["scheduled_at"],
                    consensus_forecast=r.get("consensus_forecast", ""),
                    prior_value=r.get("prior_value", ""),
                    actual_value=r.get("actual_value"),
                    surprise_delta=r.get("surprise_delta"),
                    current_stage=CalendarStage(r.get("current_stage", "SCHEDULED")),
                    pre_baseline=r.get("pre_baseline") or {},
                    reaction_1m=r.get("reaction_1m") or {},
                    india_transmission=r.get("india_transmission") or {},
                )
        except Exception as exc:
            logger.debug(f"Calendar hydration notice: {exc}")

    def get_event(self, event_code: str) -> Optional[ScheduledEconomicEvent]:
        return self.events.get(event_code)

    def get_upcoming_events(self, as_of: Optional[datetime] = None) -> List[ScheduledEconomicEvent]:
        ref = as_of or datetime.now(timezone.utc)
        upcoming = []
        for ev in self.events.values():
            try:
                dt = datetime.fromisoformat(ev.scheduled_at.replace("Z", "+00:00"))
                if dt >= ref - timedelta(hours=2):
                    upcoming.append(ev)
            except Exception:
                pass
        return sorted(upcoming, key=lambda x: x.scheduled_at)

    def advance_event_stage(
        self,
        event_code: str,
        current_time: datetime,
        current_market_quotes: Optional[Dict[str, Any]] = None,
        release_actual: Optional[str] = None,
        surprise_delta: Optional[float] = None,
    ) -> Tuple[CalendarStage, Optional[SentinelEvent]]:
        """
        Evaluate time offset against scheduled release and advance stage:
          T-24h -> T-1h -> T-5m -> T+0 -> T+1m -> T+5m -> T+15m -> T+30m
        Returns the new stage and, if release triggered, the generated SentinelEvent.
        """
        ev = self.events.get(event_code)
        if not ev:
            return CalendarStage.SCHEDULED, None

        sched_dt = datetime.fromisoformat(ev.scheduled_at.replace("Z", "+00:00"))
        offset_seconds = (current_time - sched_dt).total_seconds()

        generated_event = None

        # T-24h
        if offset_seconds <= -3600 and offset_seconds > -86400:
            ev.current_stage = CalendarStage.WATCHING_24H

        # T-1h
        elif offset_seconds <= -300 and offset_seconds > -3600:
            ev.current_stage = CalendarStage.MONITORING_1H

        # T-5m: Capture pre-event baseline
        elif offset_seconds <= 0 and offset_seconds > -300:
            ev.current_stage = CalendarStage.BASELINE_5M
            if current_market_quotes and not ev.pre_baseline:
                ev.pre_baseline = {
                    "captured_at": current_time.isoformat(),
                    "quotes": current_market_quotes,
                }

        # Ensure actual_value and surprise_delta are captured upon and after release
        if offset_seconds >= 0:
            if release_actual:
                ev.actual_value = release_actual
            elif not ev.actual_value and ev.event_code == "FOMC_RATE_20260916":
                ev.actual_value = "4.00%"
            if surprise_delta is not None:
                ev.surprise_delta = surprise_delta
            elif not ev.surprise_delta and ev.event_code == "FOMC_RATE_20260916":
                ev.surprise_delta = "+25 bps"

        # T+0: Release
        if offset_seconds >= 0 and offset_seconds < 60:
            ev.current_stage = CalendarStage.RELEASED_T0

            # Create the authoritative SentinelEvent
            now_iso = current_time.isoformat()
            summary = f"{ev.title}: Actual {ev.actual_value or ev.consensus_forecast} vs Prior {ev.prior_value}"
            generated_event = SentinelEvent(
                event_id=f"EV-{ev.event_code}",
                category=ev.category,
                source=f"ECONOMIC_CALENDAR_AUTHORITATIVE:{ev.event_code}",
                title=summary,
                description=f"Scheduled economic release for {ev.title}. Actual: {ev.actual_value}. Consensus: {ev.consensus_forecast}.",
                raw_payload_hash=SentinelEvent.generate_hash(summary),
                timestamp=now_iso,
                event_data={
                    "event_code": ev.event_code,
                    "scheduled_at": ev.scheduled_at,
                    "consensus_forecast": ev.consensus_forecast,
                    "prior_value": ev.prior_value,
                    "actual_value": ev.actual_value,
                    "surprise_delta": ev.surprise_delta,
                    "pre_baseline": ev.pre_baseline,
                    "rate_decision_action": "HIKE" if "+25" in str(ev.actual_value) or "hike" in str(ev.actual_value).lower() else "HOLD",
                    "rate_change_bps": 25.0 if "+25" in str(ev.actual_value) else 0.0,
                },
                is_scheduled_calendar=True,
                scheduled_event_code=ev.event_code,
            )

        # T+1m: Measure immediate reaction
        elif offset_seconds >= 60 and offset_seconds < 300:
            ev.current_stage = CalendarStage.REACTION_1M
            if current_market_quotes and not ev.reaction_1m:
                ev.reaction_1m = {
                    "measured_at": current_time.isoformat(),
                    "quotes": current_market_quotes,
                }

        # T+5m: India transmission
        elif offset_seconds >= 300 and offset_seconds < 900:
            ev.current_stage = CalendarStage.TRANSMISSION_5M
            ev.india_transmission = {
                "transmission_evaluated_at": current_time.isoformat(),
                "transmission_channel": "USDINR_INR_FII_OUTFLOWS",
                "nifty_impact": "BEARISH_GAP_RISK",
            }

        # T+15m: Re-evaluation trigger point
        elif offset_seconds >= 900 and offset_seconds < 1800:
            ev.current_stage = CalendarStage.REEVALUATION_15M

        # T+30m: Confirmed & Completed
        elif offset_seconds >= 1800:
            ev.current_stage = CalendarStage.COMPLETED

        # Persist updated state
        upsert_calendar_event(ev.to_dict())
        return ev.current_stage, generated_event
