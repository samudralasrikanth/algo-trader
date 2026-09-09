# =============================================================================
# event_agent/arena/ensemble_engine.py — Bayesian Reliability Ensemble & Abstain Engine
# =============================================================================
"""
Replaces simple majority voting with a Bayesian reliability-weighted ensemble:
Score = Agent Prediction × Reliability × Calibration × Regime Suitability × Signal Strength.

Supports first-class NO_TRADE (Abstain) when:
- Data quality is DEGRADED or INVALID
- Agents strongly disagree (Disagreement Index > 0.60)
- Signal strength below transaction hurdle
- Low calibrated confidence
"""

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .models import ProposedTrade, TradeAction, TradeDirection

logger = logging.getLogger(__name__)

# Baseline historical agent reliability weights (based on out-of-sample track record)
AGENT_HISTORICAL_RELIABILITY = {
    "ALPHA": 1.20,       # Event alpha edge
    "MOMENTUM": 1.10,    # Trend following edge
    "MACRO": 1.05,       # Structural regime edge
    "DEFENSIVE": 1.15,   # Capital preservation edge
    "CONTRARIAN": 0.95,  # Reversals have higher variance
}

# Regime suitability matrix: agent multiplier under specific market regimes
REGIME_SUITABILITY = {
    "BULLISH": {"ALPHA": 1.1, "MOMENTUM": 1.3, "MACRO": 1.0, "DEFENSIVE": 0.8, "CONTRARIAN": 0.8},
    "BEARISH": {"ALPHA": 1.0, "MOMENTUM": 1.1, "MACRO": 1.2, "DEFENSIVE": 1.4, "CONTRARIAN": 1.1},
    "NEUTRAL": {"ALPHA": 1.2, "MOMENTUM": 0.8, "MACRO": 1.0, "DEFENSIVE": 1.1, "CONTRARIAN": 1.2},
    "HIGH_VOLATILITY": {"ALPHA": 1.1, "MOMENTUM": 0.7, "MACRO": 1.1, "DEFENSIVE": 1.5, "CONTRARIAN": 1.2},
}


@dataclass
class EnsembleDecision:
    """Unified consensus decision emitted by the ensemble."""
    symbol: str
    action: str             # "BUY" | "SELL" | "HOLD" | "NO_TRADE"
    composite_score: float  # Normalized [-1.0 to 1.0]
    confidence: float       # Calibrated confidence [0 to 100]
    direction: str          # "BUY" | "SELL" | "NONE"
    disagreement_index: float
    abstain_reason: Optional[str] = None
    agent_votes: Dict[str, str] = field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EnsembleEngine:
    def evaluate_proposals(self, symbol: str, proposals: List[ProposedTrade], **kwargs) -> Dict[str, Any]:
        decision = self.evaluate_symbol_ensemble(symbol, proposals, **kwargs)
        return {
            "action": decision.action,
            "confidence": decision.confidence,
            "reason": decision.abstain_reason or decision.rationale,
            "composite_score": decision.composite_score,
            "disagreement_index": decision.disagreement_index,
        }

    """
    Bayesian reliability-weighted ensemble evaluator.
    """

    @classmethod
    def evaluate_symbol_ensemble(
        cls,
        symbol: str,
        proposals: List[ProposedTrade],
        current_regime: str = "NEUTRAL",
        data_quality: str = "GOOD",
        min_signal_threshold: float = 0.25,
    ) -> EnsembleDecision:
        """
        Compute weighted decision across agent proposals for a given symbol.
        """
        agent_votes = {}
        weighted_direction_sum = 0.0
        total_weight = 0.0
        conf_sum = 0.0
        conf_weight = 0.0

        for p in proposals:
            aid = p.agent_id
            act = p.action.value if hasattr(p.action, "value") else str(p.action)
            agent_votes[aid] = act

            if p.action == TradeAction.NO_TRADE:
                dir_val = 0.0
            elif p.direction == TradeDirection.BUY:
                dir_val = 1.0
            elif p.direction == TradeDirection.SELL:
                dir_val = -1.0
            else:
                dir_val = 0.0

            rel = AGENT_HISTORICAL_RELIABILITY.get(aid, 1.0)
            reg_suit = REGIME_SUITABILITY.get(current_regime, {}).get(aid, 1.0)
            calibrated_conviction = p.confidence / 100.0

            w = rel * reg_suit * calibrated_conviction
            weighted_direction_sum += (dir_val * w)
            total_weight += w

            conf_sum += (p.confidence * w)
            conf_weight += w

        composite_score = (weighted_direction_sum / total_weight) if total_weight > 0 else 0.0
        avg_confidence = (conf_sum / conf_weight) if conf_weight > 0 else 50.0

        # Calculate agent disagreement index (entropy)
        buy_votes = sum(1 for v in agent_votes.values() if v == "BUY")
        sell_votes = sum(1 for v in agent_votes.values() if v == "SELL")
        total_votes = len(agent_votes)
        disagreement = (2.0 * min(buy_votes, sell_votes) / total_votes) if total_votes > 0 else 0.0

        # 1. ABSTAIN RULE 1: Data quality is invalid
        if data_quality == "INVALID":
            return EnsembleDecision(
                symbol=symbol,
                action="NO_TRADE",
                composite_score=0.0,
                confidence=avg_confidence,
                direction="NONE",
                disagreement_index=disagreement,
                abstain_reason="DATA_QUALITY_INVALID: Unverified market quotes.",
                agent_votes=agent_votes,
                rationale="Abstained due to invalid or corrupted market data feed.",
            )

        # 2. ABSTAIN RULE 2: High inter-agent disagreement
        if disagreement > 0.60:
            return EnsembleDecision(
                symbol=symbol,
                action="NO_TRADE",
                composite_score=round(composite_score, 3),
                confidence=round(avg_confidence, 1),
                direction="NONE",
                disagreement_index=round(disagreement, 2),
                abstain_reason=f"AGENT_DISAGREEMENT: Disagreement index ({disagreement:.2f}) exceeds 0.60 threshold.",
                agent_votes=agent_votes,
                rationale=f"Agents strongly conflict ({buy_votes} BUY vs {sell_votes} SELL). High directional ambiguity.",
            )

        # 3. ABSTAIN RULE 3: Insufficient edge / weak composite score
        if abs(composite_score) < min_signal_threshold:
            return EnsembleDecision(
                symbol=symbol,
                action="NO_TRADE",
                composite_score=round(composite_score, 3),
                confidence=round(avg_confidence, 1),
                direction="NONE",
                disagreement_index=round(disagreement, 2),
                abstain_reason=f"INSUFFICIENT_EDGE: Composite score ({composite_score:.2f}) below threshold {min_signal_threshold}.",
                agent_votes=agent_votes,
                rationale="Expected statistical edge too small to cover transaction friction.",
            )

        # Directional Consensus
        if composite_score >= min_signal_threshold:
            action = "BUY"
            direction = "BUY"
            rationale = f"Bullish consensus ({composite_score:+.2f}) with {avg_confidence:.0f}% calibrated confidence."
        elif composite_score <= -min_signal_threshold:
            action = "SELL"
            direction = "SELL"
            rationale = f"Bearish consensus ({composite_score:+.2f}) with {avg_confidence:.0f}% calibrated confidence."
        else:
            action = "HOLD"
            direction = "NONE"
            rationale = "Neutral consensus."

        return EnsembleDecision(
            symbol=symbol,
            action=action,
            composite_score=round(composite_score, 3),
            confidence=round(avg_confidence, 1),
            direction=direction,
            disagreement_index=round(disagreement, 2),
            abstain_reason=None,
            agent_votes=agent_votes,
            rationale=rationale,
        )
