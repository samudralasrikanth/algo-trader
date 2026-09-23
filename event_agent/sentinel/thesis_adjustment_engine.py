# =============================================================================
# event_agent/sentinel/thesis_adjustment_engine.py — Deterministic UPDATE_THESIS Engine
# =============================================================================
"""
V4.2.1 Deterministic Thesis Adjustment Engine:
- Executes strict, bounded parameter adjustments when an event REINFORCES the active thesis.
- Avoids invoking expensive 5-agent LLM cycles while updating risk & targets.
- Preserves 100% forensic replayability by recording ThesisRevision state diffs.
"""

from copy import deepcopy
from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional, Tuple

from .models import ActiveThesis, SentinelEvent, ThesisRevision

logger = logging.getLogger(__name__)


class ThesisAdjustmentEngine:
    """
    Computes deterministic adjustments to an active NIFTY thesis.
    Arbitrary rules or LLM modifications to stops/targets are strictly forbidden.
    """

    MAX_CONFIDENCE_DELTA = 15.0
    MIN_CONFIDENCE_DELTA = -10.0
    MAX_MOVE_DELTA = 0.50             # Max +/- 0.50% move adjustment

    @classmethod
    def apply_adjustment(
        cls,
        current_thesis: ActiveThesis,
        event: SentinelEvent,
        importance_score: float = 75.0,
        event_sentiment: str = "CONFIRMING",
    ) -> Tuple[ActiveThesis, ThesisRevision]:
        """
        Derive deterministic delta parameters, validate bounds, and produce
        an auditable ThesisRevision record.
        """
        before_state = current_thesis.to_dict()

        # 1. Deterministic Confidence Delta
        if importance_score >= 85.0:
            conf_delta = 10.0
        elif importance_score >= 70.0:
            conf_delta = 6.0
        else:
            conf_delta = 3.0

        new_conf = max(10.0, min(100.0, current_thesis.confidence + conf_delta))
        actual_conf_delta = round(new_conf - current_thesis.confidence, 2)

        # 2. Deterministic Expected Move Delta
        # Move expands in the direction of the bias
        if current_thesis.bias == "BEARISH":
            move_delta = -0.25 if importance_score < 80.0 else -0.40
        elif current_thesis.bias == "BULLISH":
            move_delta = 0.25 if importance_score < 80.0 else 0.40
        else:
            move_delta = 0.0

        new_move = round(current_thesis.expected_move + move_delta, 2)

        # 3. Volatility Regime & Multipliers
        vix_context = event.event_data.get("india_vix_change_pct", 0.0)
        if vix_context >= 15.0 or importance_score >= 85.0:
            new_regime = "ELEVATED_VOLATILITY"
            risk_mult = 0.85        # Reduce trade sizing during elevated volatility
            stop_mult = 0.90        # Tighten stops by 10%
        elif vix_context <= -5.0:
            new_regime = "CALM_TRENDING"
            risk_mult = 1.05
            stop_mult = 1.05
        else:
            new_regime = current_thesis.volatility_regime
            risk_mult = current_thesis.risk_multiplier
            stop_mult = current_thesis.stop_multiplier

        # 4. Construct Updated ActiveThesis
        new_revision_num = current_thesis.revision + 1
        updated_thesis = deepcopy(current_thesis)
        updated_thesis.revision = new_revision_num
        updated_thesis.confidence = new_conf
        updated_thesis.expected_move = new_move
        updated_thesis.volatility_regime = new_regime
        updated_thesis.risk_multiplier = risk_mult
        updated_thesis.stop_multiplier = stop_mult
        updated_thesis.last_material_event_id = event.event_id

        after_state = updated_thesis.to_dict()

        reason = (
            f"Deterministic thesis update triggered by event '{event.title}'. "
            f"Confidence: {current_thesis.confidence:.1f}% -> {new_conf:.1f}% (+{actual_conf_delta:.1f}%). "
            f"Expected move: {current_thesis.expected_move:.2f}% -> {new_move:.2f}%. "
            f"Regime: {new_regime}."
        )

        revision_record = ThesisRevision(
            thesis_id=current_thesis.thesis_id,
            thesis_revision=new_revision_num,
            parent_thesis_id=current_thesis.thesis_id,
            event_id=event.event_id,
            adjustment_reason=reason,
            confidence_delta=actual_conf_delta,
            expected_move_delta=move_delta,
            volatility_regime=new_regime,
            risk_multiplier=risk_mult,
            stop_multiplier=stop_mult,
            before_state=before_state,
            after_state=after_state,
        )

        logger.info(f"🔄 THESIS REVISION {new_revision_num} CREATED for {current_thesis.thesis_id}: {reason}")
        return updated_thesis, revision_record
