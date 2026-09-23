# =============================================================================
# event_agent/arena/thesis_validator.py — Deterministic Market Thesis Validator
# =============================================================================
"""
Validates AI agent market theses strictly before routing to the Central Instrument Selector.
Enforces:
1. Canonical schema validation (confidence in [0, 100], valid horizons, expected moves in bounds).
2. Detection of AI-output / structured market data inconsistencies (THESIS_CONFLICT).
3. Non-empty invalidating conditions.
"""

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional

from event_agent.fundamentals.fundamental_snapshot import FundamentalContext

logger = logging.getLogger(__name__)

CANONICAL_HORIZONS = {"1D", "3D", "7D"}
CANONICAL_DIRECTIONS = {"BULLISH", "BEARISH"}


@dataclass
class MarketThesis:
    """Standardized thesis produced by an autonomous agent."""
    agent_id: str
    symbol: str
    direction: str                     # "BULLISH" or "BEARISH"
    expected_move_pct: float           # e.g. +1.2%
    horizon: str                       # "1D", "3D", "7D"
    confidence: float                  # 0.0 to 100.0
    catalysts: List[str]               # Specific driving news/events
    invalidating_conditions: List[str] # Specific market conditions that cancel this thesis
    reasoning: str                     # Economic thesis justification
    ai_request_id: Optional[str] = None
    model: Optional[str] = None
    actual_provider: Optional[str] = None
    thesis_conflict: bool = False
    conflict_reasons: List[str] = field(default_factory=list)
    is_valid: bool = True
    validation_errors: List[str] = field(default_factory=list)
    fundamental_context: Optional[FundamentalContext] = None

    @property
    def is_conflicted(self) -> bool:
        return self.thesis_conflict

    @property
    def conflict_reason(self) -> str:
        return "; ".join(self.conflict_reasons) if self.conflict_reasons else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "expected_move_pct": round(self.expected_move_pct, 2),
            "horizon": self.horizon,
            "confidence": round(self.confidence, 1),
            "catalysts": self.catalysts,
            "invalidating_conditions": self.invalidating_conditions,
            "reasoning": self.reasoning,
            "ai_request_id": self.ai_request_id,
            "model": self.model,
            "actual_provider": self.actual_provider,
            "thesis_conflict": self.thesis_conflict,
            "conflict_reasons": self.conflict_reasons,
            "is_valid": self.is_valid,
            "validation_errors": self.validation_errors,
            "fundamental_context": self.fundamental_context.to_dict() if self.fundamental_context else None,
        }


class MarketThesisValidator:
    """
    Deterministic validator sitting between OpenRouter decision-time AI and the Instrument Selector.
    """

    @classmethod
    def validate(
        cls,
        thesis: MarketThesis,
        structured_evidence: Optional[Dict[str, Any]] = None,
    ) -> MarketThesis:
        """
        Validates schema bounds and checks consistency against quantitative evidence.
        """
        errors: List[str] = []
        conflicts: List[str] = []

        # 1. Direction check
        clean_dir = str(thesis.direction or "").strip().upper()
        if clean_dir not in CANONICAL_DIRECTIONS:
            errors.append(f"Invalid direction '{thesis.direction}'. Must be 'BULLISH' or 'BEARISH'.")
            thesis.direction = "NEUTRAL"
        else:
            thesis.direction = clean_dir

        # 2. Confidence bounds
        try:
            conf = float(thesis.confidence)
            if conf < 0.0 or conf > 100.0:
                errors.append(f"Confidence {conf} out of bounds [0, 100].")
                thesis.confidence = max(0.0, min(100.0, conf))
            else:
                thesis.confidence = conf
        except (ValueError, TypeError):
            errors.append(f"Non-numeric confidence '{thesis.confidence}'.")
            thesis.confidence = 50.0

        # 3. Expected move bounds (-20% to +20%)
        try:
            exp_move = float(thesis.expected_move_pct)
            if abs(exp_move) > 20.0:
                errors.append(f"Expected move {exp_move:+.2f}% exceeds sanity limit (±20.0%).")
                thesis.expected_move_pct = 0.0
            else:
                thesis.expected_move_pct = exp_move
        except (ValueError, TypeError):
            errors.append(f"Non-numeric expected move '{thesis.expected_move_pct}'.")
            thesis.expected_move_pct = 0.0

        # Sign consistency check
        if thesis.direction == "BULLISH" and thesis.expected_move_pct < 0:
            errors.append(f"Direction is BULLISH but expected move is negative ({thesis.expected_move_pct:+.2f}%).")
        elif thesis.direction == "BEARISH" and thesis.expected_move_pct > 0:
            errors.append(f"Direction is BEARISH but expected move is positive ({thesis.expected_move_pct:+.2f}%).")

        # 4. Canonical Horizon
        clean_horizon = str(thesis.horizon or "").strip().upper()
        if clean_horizon not in CANONICAL_HORIZONS:
            errors.append(f"Invalid horizon '{thesis.horizon}'. Must be one of {sorted(CANONICAL_HORIZONS)}.")
            thesis.horizon = "1D"
        else:
            thesis.horizon = clean_horizon

        # 5. Invalidating conditions check
        if not thesis.invalidating_conditions or len(thesis.invalidating_conditions) == 0:
            errors.append("Missing invalidating conditions. Thesis must declare conditions under which it fails.")
            thesis.invalidating_conditions = ["Adverse price movement exceeding stop-loss"]

        # 6. Quantitative Evidence / Thesis Conflict Check
        if structured_evidence and thesis.direction in CANONICAL_DIRECTIONS:
            vix_change = float(structured_evidence.get("vix_change_pct", 0.0))
            usdinr_change = float(structured_evidence.get("usdinr_change_pct", 0.0))
            global_futures_chg = float(structured_evidence.get("global_futures_pct", 0.0))
            adv_dec_ratio = float(structured_evidence.get("adv_dec_ratio", 1.0))

            if thesis.direction == "BULLISH":
                # Macro headwinds check
                if vix_change >= 4.0:
                    conflicts.append(f"Macro volatility surging: India VIX shifted {vix_change:+.1f}%.")
                if usdinr_change >= 0.25:
                    conflicts.append(f"Currency weakening: USDINR rose {usdinr_change:+.2f}%.")
                if global_futures_chg <= -0.60:
                    conflicts.append(f"Global equity selloff: Futures down {global_futures_chg:+.2f}%.")
                if adv_dec_ratio <= 0.50:
                    conflicts.append(f"Weak domestic breadth: Advance-Decline ratio is {adv_dec_ratio:.2f}.")

            elif thesis.direction == "BEARISH":
                # Macro tailwinds check
                if vix_change <= -4.0:
                    conflicts.append(f"Volatility collapsing: India VIX shifted {vix_change:+.1f}%.")
                if usdinr_change <= -0.25:
                    conflicts.append(f"Currency strengthening: USDINR dropped {usdinr_change:+.2f}%.")
                if global_futures_chg >= 0.60:
                    conflicts.append(f"Global equity rally: Futures up {global_futures_chg:+.2f}%.")
                if adv_dec_ratio >= 2.0:
                    conflicts.append(f"Strong domestic breadth: Advance-Decline ratio is {adv_dec_ratio:.2f}.")

        # 7. Fundamental Evidence Contradiction Check (Context modifier for Momentum, conflict for others)
        if thesis.fundamental_context and thesis.fundamental_context.contradiction:
            fc_reason = thesis.fundamental_context.reasoning or "Fundamental profile strongly contradicts short-term directional thesis."
            if thesis.agent_id.upper() != "MOMENTUM":
                conflicts.append(f"Fundamental contradiction: {fc_reason}")

        thesis.is_valid = (len(errors) == 0)
        thesis.validation_errors = errors
        thesis.thesis_conflict = (len(conflicts) > 0)
        thesis.conflict_reasons = conflicts

        if thesis.thesis_conflict:
            logger.info(
                f"⚠️ THESIS_CONFLICT detected for {thesis.agent_id} on {thesis.symbol}: "
                f"{'; '.join(conflicts)}"
            )

        if not thesis.is_valid:
            logger.warning(
                f"❌ THESIS_INVALID for {thesis.agent_id} on {thesis.symbol}: "
                f"{'; '.join(errors)}"
            )

        return thesis
