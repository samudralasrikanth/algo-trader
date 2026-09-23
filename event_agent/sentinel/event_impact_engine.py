# =============================================================================
# event_agent/sentinel/event_impact_engine.py — Deterministic Impact & Verdict Engine
# =============================================================================
"""
V4.2.1 Deterministic Event Impact Engine:
- Evaluates event importance, India relevance, novelty, and market reaction.
- Compares against ActiveThesis state to route into:
    STORE_ONLY, UPDATE_THESIS, TRIGGER_RE_EVALUATION, or MARKET_SHOCK.
- Zero LLM gating to guarantee zero cost explosion.
"""

import logging
from typing import Any, Dict, Optional, Tuple

from .models import (
    ActiveThesis,
    EventCategory,
    EventImpactAssessment,
    SentinelEvent,
    ThesisRelation,
    TriggerVerdict,
)
from .thesis_state_manager import ThesisStateManager

logger = logging.getLogger(__name__)


class EventImpactEngine:
    """
    Deterministic scoring and routing engine.
    """

    BASE_IMPORTANCE: Dict[EventCategory, float] = {
        EventCategory.FOMC: 100.0,
        EventCategory.MARKET_SHOCK: 100.0,
        EventCategory.BLACK_SWAN: 100.0,
        EventCategory.RBI: 95.0,
        EventCategory.ECB: 85.0,
        EventCategory.BOJ: 85.0,
        EventCategory.INFLATION: 85.0,
        EventCategory.EMPLOYMENT: 75.0,
        EventCategory.GDP: 75.0,
        EventCategory.GEOPOLITICAL: 75.0,
        EventCategory.INTEREST_RATE: 70.0,
        EventCategory.BOND_YIELD: 70.0,
        EventCategory.CURRENCY: 65.0,
        EventCategory.COMMODITY: 65.0,
        EventCategory.INDIA_MACRO: 65.0,
        EventCategory.GLOBAL_EQUITY: 60.0,
        EventCategory.EARNINGS: 55.0,
        EventCategory.REGULATORY: 55.0,
        EventCategory.CORPORATE: 25.0,
    }

    @classmethod
    def assess_impact(
        cls,
        event: SentinelEvent,
        active_thesis: Optional[ActiveThesis] = None,
        market_reaction_score: float = 0.0,
    ) -> EventImpactAssessment:
        """
        Produce a deterministic 0-100 assessment and routing verdict.
        """
        thesis = active_thesis or ThesisStateManager.get_or_create_active_thesis()

        # 1. Base Importance
        base_imp = cls.BASE_IMPORTANCE.get(event.category, 30.0)

        # 2. India Relevance
        india_rel = cls._determine_india_relevance(event)

        # 3. Novelty
        novelty = "HIGH" if event.is_scheduled_calendar or base_imp >= 80.0 else "MEDIUM"

        # 4. Thesis Relation
        relation, rel_reason = ThesisStateManager.evaluate_thesis_relation(
            current_thesis=thesis,
            event=event,
        )

        # 5. Determine Verdict
        verdict, verdict_reason = cls._determine_verdict(
            event=event,
            importance=base_imp,
            india_relevance=india_rel,
            reaction_score=market_reaction_score,
            thesis_relation=relation,
            rel_reason=rel_reason,
        )

        assessment = EventImpactAssessment(
            event_id=event.event_id,
            importance_score=base_imp,
            india_relevance=india_rel,
            novelty=novelty,
            market_reaction_score=market_reaction_score,
            thesis_relation=relation,
            verdict=verdict,
            reasoning=verdict_reason,
        )

        logger.info(
            f"⚖️ EVENT IMPACT: [{event.category.value}] '{event.title[:50]}' -> "
            f"Imp={base_imp:.0f}, Rel={india_rel}, Verdict={verdict.value} ({verdict_reason})"
        )
        return assessment

    @classmethod
    def _determine_india_relevance(cls, event: SentinelEvent) -> str:
        cat = event.category
        text = f"{event.title} {event.description}".lower()

        if cat in (EventCategory.RBI, EventCategory.INDIA_MACRO, EventCategory.MARKET_SHOCK):
            return "HIGH"
        if any(w in text for w in ["nifty", "sensex", "india", "rupee", "usdinr"]):
            return "HIGH"
        if cat in (EventCategory.FOMC, EventCategory.INFLATION, EventCategory.COMMODITY, EventCategory.CURRENCY):
            return "HIGH"
        if cat in (EventCategory.ECB, EventCategory.BOJ, EventCategory.EMPLOYMENT, EventCategory.GLOBAL_EQUITY):
            return "MEDIUM"
        return "LOW"

    @classmethod
    def _determine_verdict(
        cls,
        event: SentinelEvent,
        importance: float,
        india_relevance: str,
        reaction_score: float,
        thesis_relation: ThesisRelation,
        rel_reason: str,
    ) -> Tuple[TriggerVerdict, str]:
        # Path 0: Independent Market Shock
        if event.category == EventCategory.MARKET_SHOCK:
            return TriggerVerdict.MARKET_SHOCK, "Severe cross-asset dislocation detected. Immediate TradeGuard emergency evaluation."

        # Path 1: Extreme Market Reaction
        if reaction_score >= 70.0:
            return TriggerVerdict.TRIGGER_RE_EVALUATION, f"Cross-market reaction score {reaction_score:.1f} >= 70.0 indicates structural macro shift."

        # Path 2: Thesis Conflict with Significant Importance
        if thesis_relation == ThesisRelation.CONFLICTS and importance >= 65.0:
            return TriggerVerdict.TRIGGER_RE_EVALUATION, f"Material conflict with active thesis: {rel_reason} (Importance {importance:.0f})."

        # Path 3: High-Impact Macro Catalyst (Scheduled FOMC / RBI / Black Swan)
        if importance >= 90.0 and india_relevance == "HIGH":
            if thesis_relation == ThesisRelation.REINFORCES:
                return TriggerVerdict.UPDATE_THESIS, f"High-impact catalyst reinforces active thesis: {rel_reason}. Calibrating conviction & parameters."
            return TriggerVerdict.TRIGGER_RE_EVALUATION, f"Major sovereign monetary release ({event.category.value}): Full 5-agent re-evaluation required."

        # Path 4: Reinforcing Event with Moderate-to-High Importance
        if thesis_relation == ThesisRelation.REINFORCES and importance >= 60.0:
            return TriggerVerdict.UPDATE_THESIS, f"Reinforcing event confirms thesis trajectory: {rel_reason}."

        # Path 5: Low-Impact / Routine Noise
        return TriggerVerdict.STORE_ONLY, f"Event impact (Importance={importance:.0f}, Relevance={india_relevance}) does not breach re-evaluation or update thresholds."
