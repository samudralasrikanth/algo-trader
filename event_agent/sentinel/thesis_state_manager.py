# =============================================================================
# event_agent/sentinel/thesis_state_manager.py — Active Thesis State Manager
# =============================================================================
"""
V4.2.1 Active Thesis State Manager:
- Manages persistent active NIFTY thesis lifecycle in SQLite & Supabase.
- Evaluates event conditions against invalidation criteria.
- Applies deterministic revisions or marks thesis INVALIDATED.
"""

from datetime import datetime, timezone, timedelta
import logging
from typing import Any, Dict, List, Optional, Tuple

from event_agent.storage.ledger import (
    get_current_active_thesis,
    save_active_thesis,
    save_thesis_revision,
    get_thesis_revisions,
)
from event_agent.storage.supabase_ledger import (
    save_active_thesis_supabase,
    save_thesis_revision_supabase,
)
from event_agent.sentinel.models import ActiveThesis, SentinelEvent, ThesisRelation, ThesisRevision, ThesisStatus
from event_agent.sentinel.thesis_adjustment_engine import ThesisAdjustmentEngine

logger = logging.getLogger(__name__)


class ThesisStateManager:
    """
    Coordinates active thesis persistence, invalidation testing, and deterministic revisions.
    """

    DEFAULT_INVALIDATION_RULES = [
        "USDINR breaks above 95.75",
        "India VIX surges > 20%",
        "Global futures reverse > 1.5%",
        "Major conflicting central bank policy decision",
    ]

    @classmethod
    def get_or_create_active_thesis(cls) -> ActiveThesis:
        """Retrieve current active thesis from DB or initialize standard baseline."""
        raw = get_current_active_thesis()
        if raw:
            return ActiveThesis(
                thesis_id=raw["thesis_id"],
                revision=raw.get("revision", 1),
                created_at=raw.get("created_at", datetime.now(timezone.utc).isoformat()),
                bias=raw.get("bias", "BEARISH"),
                confidence=float(raw.get("confidence", 70.0)),
                expected_move=float(raw.get("expected_move", -0.80)),
                valid_until=raw.get("valid_until", (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()),
                invalidation_conditions=raw.get("invalidation_conditions", cls.DEFAULT_INVALIDATION_RULES),
                last_material_event_id=raw.get("last_material_event_id"),
                status=ThesisStatus(raw.get("status", "ACTIVE")),
                volatility_regime=raw.get("volatility_regime", "NORMAL"),
                risk_multiplier=float(raw.get("risk_multiplier", 1.0)),
                stop_multiplier=float(raw.get("stop_multiplier", 1.0)),
            )

        # Create initial baseline thesis
        now = datetime.now(timezone.utc)
        ts_code = now.strftime("%Y%m%d-001")
        new_thesis = ActiveThesis(
            thesis_id=f"TH-{ts_code}",
            revision=1,
            created_at=now.isoformat(),
            bias="BEARISH",
            confidence=72.0,
            expected_move=-0.80,
            valid_until=(now + timedelta(hours=24)).isoformat(),
            invalidation_conditions=cls.DEFAULT_INVALIDATION_RULES,
            status=ThesisStatus.ACTIVE,
        )
        cls.persist_active_thesis(new_thesis)
        return new_thesis

    @classmethod
    def persist_active_thesis(cls, thesis: ActiveThesis) -> bool:
        """Persist active thesis to SQLite and cloud Supabase store."""
        t_dict = thesis.to_dict()
        ok_sqlite = save_active_thesis(t_dict)
        save_active_thesis_supabase(t_dict)
        return ok_sqlite

    @classmethod
    def evaluate_thesis_relation(
        cls,
        current_thesis: ActiveThesis,
        event: SentinelEvent,
        market_metrics: Optional[Dict[str, Any]] = None,
    ) -> Tuple[ThesisRelation, str]:
        """
        Deterministically evaluate whether an event CONFLICTS with, REINFORCES,
        or is NEUTRAL to the current active thesis.
        """
        metrics = market_metrics or event.event_data
        cat = event.category.value if hasattr(event.category, "value") else str(event.category)
        event_text = f"{event.title} {event.description}".lower()

        # 1. Macro Policy Rate Decision Direction
        rate_decision = metrics.get("rate_decision_action")  # "HIKE", "CUT", "HOLD"
        rate_bps = float(metrics.get("rate_change_bps", 0.0))

        if cat in ("FOMC", "RBI", "ECB", "BOJ") or "rate" in event_text:
            if rate_decision == "HIKE" or rate_bps > 0 or "rate hike" in event_text or "raised" in event_text:
                # Rate hike is typically tightening / liquidity-negative (bearish for equities)
                if current_thesis.bias == "BEARISH":
                    return ThesisRelation.REINFORCES, "Hawkish monetary tightening reinforces bearish setup."
                elif current_thesis.bias == "BULLISH":
                    return ThesisRelation.CONFLICTS, "Hawkish rate hike directly conflicts with bullish bias."
            elif rate_decision == "CUT" or rate_bps < 0 or "rate cut" in event_text:
                if current_thesis.bias == "BULLISH":
                    return ThesisRelation.REINFORCES, "Dovish monetary easing reinforces bullish equity bias."
                elif current_thesis.bias == "BEARISH":
                    return ThesisRelation.CONFLICTS, "Dovish rate cut directly conflicts with bearish bias."

        # 2. Check explicit invalidation conditions
        vix_chg = float(metrics.get("india_vix_change_pct", 0.0))
        usdinr_val = float(metrics.get("usdinr_price", 0.0))
        fut_chg = float(metrics.get("us_futures_change_pct", 0.0))

        if current_thesis.bias == "BEARISH":
            # If global futures recover sharply or VIX plummets, conflicts with bearish thesis
            if fut_chg >= 1.50:
                return ThesisRelation.CONFLICTS, f"Global futures surged +{fut_chg:.2f}%, violating bearish assumption."
            if vix_chg <= -15.0:
                return ThesisRelation.CONFLICTS, f"Volatility collapsed {vix_chg:.1f}%, conflicting with defensive risk thesis."
            if vix_chg >= 10.0 or fut_chg <= -0.80:
                return ThesisRelation.REINFORCES, "Elevated volatility and falling global futures reinforce bearish bias."

        elif current_thesis.bias == "BULLISH":
            if fut_chg <= -1.50:
                return ThesisRelation.CONFLICTS, f"Global futures plunged {fut_chg:.2f}%, violating bullish assumption."
            if usdinr_val >= 95.75:
                return ThesisRelation.CONFLICTS, f"USDINR at {usdinr_val} breached critical 95.75 currency threshold."
            if fut_chg >= 0.80 or vix_chg <= -5.0:
                return ThesisRelation.REINFORCES, "Positive global cues reinforce bullish bias."

        return ThesisRelation.NEUTRAL, "Event impact does not alter or conflict with core thesis trajectory."

    @classmethod
    def apply_reinforcing_update(
        cls,
        current_thesis: ActiveThesis,
        event: SentinelEvent,
        importance_score: float,
    ) -> Tuple[ActiveThesis, ThesisRevision]:
        """Apply deterministic UPDATE_THESIS and persist revision."""
        updated_thesis, rev_record = ThesisAdjustmentEngine.apply_adjustment(
            current_thesis=current_thesis,
            event=event,
            importance_score=importance_score,
        )

        # Persist updated thesis
        cls.persist_active_thesis(updated_thesis)

        # Persist revision audit trail to SQLite and Supabase
        save_thesis_revision(rev_record.to_dict())
        save_thesis_revision_supabase(rev_record.to_dict())

        return updated_thesis, rev_record

    @classmethod
    def invalidate_thesis(
        cls,
        thesis_id: str,
        reason: str,
        invalidation_event_id: str,
    ) -> bool:
        """Mark thesis as INVALIDATED in SQLite and Supabase."""
        current = cls.get_or_create_active_thesis()
        if current.thesis_id == thesis_id:
            current.status = ThesisStatus.INVALIDATED
            cls.persist_active_thesis(current)
            logger.warning(f"⚠️ ACTIVE THESIS {thesis_id} INVALIDATED by event {invalidation_event_id}: {reason}")
            return True
        return False
