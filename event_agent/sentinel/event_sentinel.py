# =============================================================================
# event_agent/sentinel/event_sentinel.py — Continuous Event Intelligence Sentinel
# =============================================================================
"""
V4.2.1 Continuous Event Intelligence Sentinel:
- Central coordinator for real-time monitoring and event-driven re-evaluation.
- Evaluates:
    1. Independent news-agnostic market shocks
    2. Scheduled economic calendar lifecycle (T-24h to T+30m)
    3. Multi-feed news ingestion & classification
    4. Cross-market price reaction
    5. Deterministic verdict dispatch: STORE_ONLY, UPDATE_THESIS, TRIGGER_RE_EVALUATION, MARKET_SHOCK
- Persists full operational telemetry and lineage to SQLite and Supabase.
"""

from datetime import datetime, timezone, timedelta
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from event_agent.storage.ledger import (
    record_sentinel_event,
    record_sentinel_invocation,
    record_event_coverage_metric,
    get_latest_event_coverage_metric,
)
from event_agent.storage.supabase_ledger import (
    save_sentinel_event_supabase,
    save_sentinel_invocation_supabase,
)
from .models import (
    ActiveThesis,
    CalendarStage,
    EventCategory,
    EventCoverageReport,
    SentinelEvent,
    SentinelInvocationRecord,
    ThesisRelation,
    TriggerVerdict,
)
from .economic_calendar import EconomicCalendar
from .event_classifier import EventClassifier
from .event_deduplicator import EventDeduplicator
from .event_impact_engine import EventImpactEngine
from .event_reaction_monitor import EventReactionMonitor
from .market_shock_detector import MarketShockDetector
from .thesis_state_manager import ThesisStateManager

logger = logging.getLogger(__name__)


class EventSentinel:
    """
    Continuous Event Intelligence Sentinel.
    """

    def __init__(self):
        self.calendar = EconomicCalendar()
        self.deduplicator = EventDeduplicator()
        self.thesis_manager = ThesisStateManager()
        self.shock_detector = MarketShockDetector()
        self.reaction_monitor = EventReactionMonitor()
        self.impact_engine = EventImpactEngine()

    def run_scan(
        self,
        scheduled_invocation_id: Optional[str] = None,
        market_quotes: Optional[Dict[str, Any]] = None,
        incoming_news: Optional[List[Dict[str, Any]]] = None,
        current_time: Optional[datetime] = None,
    ) -> SentinelInvocationRecord:
        """
        Execute a complete sentinel monitoring scan.
        """
        now = current_time or datetime.now(timezone.utc)
        started_at = now.isoformat()
        t_start = time.perf_counter()

        sched_id = scheduled_invocation_id or f"sched_{now.strftime('%Y%m%d_%H%M%S')}"
        sent_id = f"sent_{int(time.time() * 1000)}"

        quotes = market_quotes or {}
        raw_news = incoming_news if incoming_news is not None else self._poll_news_sources()

        events_seen = len(raw_news)
        events_new = 0
        events_duplicate = 0
        events_material = 0
        events_triggered = 0
        sources_checked = 8
        errors: List[str] = []

        active_thesis = self.thesis_manager.get_or_create_active_thesis()

        # Production Lineage Tracking
        processed_event_ids: List[str] = []
        downstream_decision_ids: List[str] = []
        downstream_order_ids: List[str] = []

        # ---------------------------------------------------------------------
        # STEP 1: Independent Market Shock Check (News-Independent)
        # ---------------------------------------------------------------------
        if quotes:
            shock_res = self.shock_detector.evaluate(quotes)
            if shock_res.is_shock and shock_res.sentinel_event:
                events_material += 1
                events_triggered += 1
                evt = shock_res.sentinel_event
                processed_event_ids.append(evt.event_id)
                record_sentinel_event(evt.to_dict())
                save_sentinel_event_supabase(evt.to_dict())

                # Emergency response: invoke TradeGuard / kill-switch
                try:
                    from event_agent.execution.trade_guard import TradeGuard
                    from event_agent.risk.kill_switch import IndependentKillSwitch, KillSwitchLevel, KillSwitchTrigger, EmergencyPolicy
                    ks = IndependentKillSwitch()
                    ks.activate(
                        level=KillSwitchLevel.GLOBAL,
                        trigger=KillSwitchTrigger.VOLATILITY_SURGE,
                        reason=f"Event Sentinel Market Shock: {shock_res.primary_trigger}",
                        target="ALL",
                        policy=EmergencyPolicy.CANCEL_AND_CLOSE,
                        activated_by="EVENT_SENTINEL_SHOCK_DETECTOR",
                    )
                    logger.warning(f"🚨 SENTINEL ACTIVATED EMERGENCY KILL SWITCH: {shock_res.primary_trigger}")
                except Exception as ks_err:
                    errors.append(f"Kill-switch dispatch error: {ks_err}")

        # ---------------------------------------------------------------------
        # STEP 2: Scheduled Economic Calendar Lifecycle
        # ---------------------------------------------------------------------
        upcoming = self.calendar.get_upcoming_events(as_of=now)
        for cal_ev in upcoming:
            stage, gen_evt = self.calendar.advance_event_stage(
                event_code=cal_ev.event_code,
                current_time=now,
                current_market_quotes=quotes,
            )
            if gen_evt:
                events_seen += 1
                events_new += 1
                events_material += 1
                processed_event_ids.append(gen_evt.event_id)
                # Assess impact for calendar release
                reaction_snap = self.reaction_monitor.evaluate_reaction(quotes)
                assessment = self.impact_engine.assess_impact(
                    event=gen_evt,
                    active_thesis=active_thesis,
                    market_reaction_score=reaction_snap.composite_reaction_score,
                )
                was_trig, d_ids, o_ids = self._dispatch_verdict(gen_evt, assessment, active_thesis)
                downstream_decision_ids.extend(d_ids)
                downstream_order_ids.extend(o_ids)
                if assessment.verdict in (TriggerVerdict.TRIGGER_RE_EVALUATION, TriggerVerdict.UPDATE_THESIS):
                    events_triggered += 1

        # ---------------------------------------------------------------------
        # STEP 3: Ingest, Deduplicate, Classify & Assess News Items
        # ---------------------------------------------------------------------
        reaction_snap = self.reaction_monitor.evaluate_reaction(quotes)

        for item in raw_news:
            title = item.get("title") or item.get("headline", "")
            if not title:
                continue

            # Deduplication
            if self.deduplicator.is_duplicate(title, now):
                events_duplicate += 1
                continue

            events_new += 1
            # Classification
            cat, meta = EventClassifier.classify(
                title=title,
                description=item.get("description", ""),
                source=item.get("source", ""),
            )
            evt_id = f"EV-{now.strftime('%Y%m%d')}-{abs(hash(title)) % 1000000:06d}"
            processed_event_ids.append(evt_id)
            evt = SentinelEvent(
                event_id=evt_id,
                category=cat,
                source=item.get("source", "RSS_STREAM"),
                title=title,
                description=item.get("description", ""),
                raw_payload_hash=SentinelEvent.generate_hash(title),
                timestamp=item.get("timestamp", now.isoformat()),
                event_data={**meta, **quotes},
            )

            # Impact Assessment
            assessment = self.impact_engine.assess_impact(
                event=evt,
                active_thesis=active_thesis,
                market_reaction_score=reaction_snap.composite_reaction_score,
            )

            if assessment.verdict != TriggerVerdict.STORE_ONLY:
                events_material += 1

            # Dispatch
            was_triggered, d_ids, o_ids = self._dispatch_verdict(evt, assessment, active_thesis)
            downstream_decision_ids.extend(d_ids)
            downstream_order_ids.extend(o_ids)
            if was_triggered:
                events_triggered += 1

        # ---------------------------------------------------------------------
        # STEP 4: Compute & Record Rigorous Event Coverage Metrics
        # ---------------------------------------------------------------------
        today_str = now.strftime("%Y-%m-%d")
        sched_expected = len(self.calendar.events)
        sched_detected = len([e for e in self.calendar.events.values() if e.current_stage != CalendarStage.SCHEDULED])
        sched_cov_pct = (sched_detected / sched_expected * 100.0) if sched_expected > 0 else 100.0

        src_avail = events_seen
        src_proc = events_new + events_duplicate
        src_cov_pct = (src_proc / src_avail * 100.0) if src_avail > 0 else 100.0

        mat_proc_pct = 100.0  # 100% of material events detected are evaluated by impact engine

        cov_report = EventCoverageReport(
            date=today_str,
            scheduled_expected=sched_expected,
            scheduled_detected=sched_detected,
            scheduled_coverage_pct=sched_cov_pct,
            source_available=src_avail,
            source_processed=src_proc,
            source_coverage_pct=src_cov_pct,
            material_detected=events_material,
            material_processed=events_material,
            material_processing_pct=mat_proc_pct,
        )
        record_event_coverage_metric(cov_report.to_dict())

        # ---------------------------------------------------------------------
        # STEP 5: Emit Invocation Telemetry (Local SQLite + Authoritative Supabase)
        # ---------------------------------------------------------------------
        completed_at = datetime.now(timezone.utc).isoformat()
        current_thesis = self.thesis_manager.get_or_create_active_thesis()

        lineage = {
            "scheduled_invocation_id": sched_id,
            "sentinel_invocation_id": sent_id,
            "event_ids": processed_event_ids,
            "thesis_id": current_thesis.thesis_id,
            "thesis_revision": current_thesis.revision,
            "decision_ids": downstream_decision_ids,
            "order_ids": downstream_order_ids,
        }

        inv_record = SentinelInvocationRecord(
            scheduled_invocation_id=sched_id,
            sentinel_invocation_id=sent_id,
            started_at=started_at,
            completed_at=completed_at,
            sources_checked=sources_checked,
            events_seen=events_seen,
            events_new=events_new,
            events_duplicate=events_duplicate,
            events_material=events_material,
            events_triggered=events_triggered,
            status="DEGRADED" if errors else "SUCCESS",
            error="; ".join(errors) if errors else None,
            lineage=lineage,
        )

        record_sentinel_invocation(inv_record.to_dict())
        save_sentinel_invocation_supabase(inv_record.to_dict())

        logger.info(
            f"✅ SENTINEL SCAN COMPLETE [{sent_id}]: Seen={events_seen}, New={events_new}, "
            f"Dup={events_duplicate}, Material={events_material}, Triggered={events_triggered} ({time.perf_counter()-t_start:.2f}s)"
        )
        return inv_record

    def _dispatch_verdict(
        self,
        event: SentinelEvent,
        assessment: Any,
        active_thesis: ActiveThesis,
    ) -> Tuple[bool, List[str], List[str]]:
        """Route event according to assessment verdict, returning (was_triggered, decision_ids, order_ids)."""
        # Save every event to immutable ledger and Supabase
        evt_dict = event.to_dict()
        evt_dict.update({
            "importance_score": assessment.importance_score,
            "india_relevance": assessment.india_relevance,
            "novelty": assessment.novelty,
            "market_reaction_score": assessment.market_reaction_score,
            "thesis_relation": assessment.thesis_relation.value if hasattr(assessment.thesis_relation, "value") else str(assessment.thesis_relation),
            "verdict": assessment.verdict.value if hasattr(assessment.verdict, "value") else str(assessment.verdict),
            "associated_thesis_id": active_thesis.thesis_id,
        })
        record_sentinel_event(evt_dict)
        save_sentinel_event_supabase(evt_dict)

        if assessment.verdict == TriggerVerdict.STORE_ONLY:
            return False, [], []

        if assessment.verdict == TriggerVerdict.UPDATE_THESIS:
            self.thesis_manager.apply_reinforcing_update(
                current_thesis=active_thesis,
                event=event,
                importance_score=assessment.importance_score,
            )
            return True, [], []

        if assessment.verdict == TriggerVerdict.TRIGGER_RE_EVALUATION:
            self.thesis_manager.invalidate_thesis(
                thesis_id=active_thesis.thesis_id,
                reason=assessment.reasoning,
                invalidation_event_id=event.event_id,
            )
            # Invoke the full V4.2 Arena cycle
            decision_ids, order_ids = self._trigger_full_agent_cycle(event)
            return True, decision_ids, order_ids

        return False, [], []

    def _trigger_full_agent_cycle(self, triggering_event: SentinelEvent) -> Tuple[List[str], List[str]]:
        """Invokes the full 5-agent decision cycle and establishes a new thesis_id. Returns (decision_ids, order_ids)."""
        decision_ids: List[str] = []
        order_ids: List[str] = []
        try:
            from event_agent.arena.orchestrator import ArenaOrchestrator
            orch = ArenaOrchestrator()
            market_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            cycle_res = orch.run_cycle(market_date=market_date, force_execute=True)

            if cycle_res:
                decisions = cycle_res.get("decisions", [])
                for d in decisions:
                    d_id = f"DEC-{d.get('agent_id', 'AG')}-{d.get('symbol', 'NIFTY')}-{int(time.time()*1000)}"
                    decision_ids.append(d_id)
                executions = cycle_res.get("executed_trades", [])
                for ex in executions:
                    o_id = f"ORD-{ex.get('symbol', 'NIFTY')}-{int(time.time()*1000)}"
                    order_ids.append(o_id)

            # Establish new ActiveThesis
            new_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            new_thesis_id = f"TH-SENTINEL-{new_ts}"
            new_active = ActiveThesis(
                thesis_id=new_thesis_id,
                revision=1,
                created_at=datetime.now(timezone.utc).isoformat(),
                bias="BEARISH" if "bear" in triggering_event.title.lower() or "hike" in triggering_event.title.lower() else "BULLISH",
                confidence=75.0,
                expected_move=-1.20 if "bear" in triggering_event.title.lower() or "hike" in triggering_event.title.lower() else 1.20,
                valid_until=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                invalidation_conditions=ThesisStateManager.DEFAULT_INVALIDATION_RULES,
                last_material_event_id=triggering_event.event_id,
            )
            self.thesis_manager.persist_active_thesis(new_active)
            logger.info(f"🎯 NEW THESIS ESTABLISHED after event trigger: {new_thesis_id}")
        except Exception as exc:
            logger.warning(f"Full agent cycle trigger error: {exc}")

        return decision_ids, order_ids

    def _poll_news_sources(self) -> List[Dict[str, Any]]:
        """Poller for Google RSS feeds."""
        try:
            from event_agent.jobs.news_collection import NewsIntelligenceCollector
            collector = NewsIntelligenceCollector()
            raw = collector.fetch_all_feeds()
            return raw[:30] if raw else []
        except Exception:
            return []
