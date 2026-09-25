# =============================================================================
# event_agent/arena/agents/base_agent.py — Abstract Base Strategy Agent
# =============================================================================
"""
Base class defining standard behavior for all 5 Arena Strategy Agents:
- Identical immutable market snapshot input for all 50 stocks
- Real OpenRouter Decision-Time AI inference execution
- Deterministic MarketThesisValidator schema & data conflict enforcement
- Central Instrument Selector funnel routing
- 0 to 10 dynamic active allocations
- Explicit NO_TRADE emission when criteria are unfulfilled
- Frozen strategy versioning
"""

from abc import ABC, abstractmethod
import logging
from typing import Any, Dict, List, Optional

from event_agent.engine.llm_provider import OpenRouterProvider
from event_agent.arena.thesis_validator import MarketThesis, MarketThesisValidator
from event_agent.arena.instrument_selector import InstrumentSelector
from event_agent.arena.models import (
    AgentProfile,
    HedgeDecision,
    Instrument,
    InstrumentType,
    OptionType,
    OrderIntent,
    PositionSide,
    ProposedTrade,
    TradeAction,
    TradeDirection,
)

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract Strategy Agent participating in the Nifty 50 AI Trading Arena.
    """

    def __init__(self, profile: AgentProfile):
        self.profile = profile
        self.llm_provider = OpenRouterProvider()
        self.thesis_validator = MarketThesisValidator()
        self.instrument_selector = InstrumentSelector()

    @property
    def agent_id(self) -> str:
        return self.profile.id

    @property
    def strategy_version(self) -> str:
        return self.profile.strategy_version

    @abstractmethod
    def evaluate_market(
        self,
        market_snapshot: Dict[str, Any],
        current_open_positions: List[Dict[str, Any]],
        current_equity: float,
        current_cash: float,
    ) -> List[ProposedTrade]:
        """
        Evaluate the 50-stock shared market snapshot and return 0 to 10 proposals
        or a single NO_TRADE proposal with structured rationale.
        """
        pass

    def generate_and_validate_thesis(
        self,
        symbol: str,
        stock_data: Dict[str, Any],
        market_snapshot: Dict[str, Any],
    ) -> MarketThesis:
        """
        Executes real OpenRouter decision-time AI inference and passes the raw
        output through the deterministic MarketThesisValidator.
        """
        regime = market_snapshot.get("regime", {})
        macro_evidence = {
            "vix_change_pct": float(regime.get("vix_change_pct", 0.0)),
            "usdinr_change_pct": float(regime.get("usdinr_change_pct", 0.0)),
            "global_futures_pct": float(regime.get("global_futures_pct", 0.0)),
            "adv_dec_ratio": float(regime.get("adv_dec_ratio", 1.0)),
        }

        # 1. Real OpenRouter Inference
        ai_resp = self.llm_provider.generate_decision_thesis(
            agent_id=self.agent_id,
            symbol=symbol,
            stock_data=stock_data,
            market_context=regime,
        )

        ai_status = ai_resp.get("ai_status") or ai_resp.get("status") or "UNAVAILABLE"
        if ai_status not in ("INFERENCE_SUCCESS", "SUCCESS"):
            # FAIL-CLOSED INVARIANT:
            # Under AI failure (credit exhausted, unavailable, rate limited, error),
            # DO NOT fabricate an AI decision from stock_data!
            # Emit explicit NO_TRADE thesis tagged with error and excluded from accuracy.
            prov_model = getattr(self.llm_provider, "model", "unknown")
            prov_name = getattr(self.llm_provider, "provider_name", "openrouter")
            error_reason = ai_resp.get("fallback_reason") or ai_resp.get("error") or "Inference failed"
            thesis = MarketThesis(
                agent_id=self.agent_id,
                symbol=symbol,
                direction="NO_TRADE",
                expected_move_pct=0.0,
                horizon="1D",
                confidence=0.0,
                catalysts=[],
                invalidating_conditions=["AI inference failure / credit exhausted"],
                reasoning=f"AGENT AI STATUS: UNAVAILABLE | AI THESIS: NOT GENERATED | DETERMINISTIC SCREEN: NO_TRADE ({error_reason})",
                ai_request_id=None,
                model=prov_model,
                actual_provider=prov_name,
                decision_model=ai_resp.get("decision_model") or f"{prov_name.upper()}:{prov_model}",
                model_provider=prov_name,
                model_version=prov_model,
                decision_mode="AI_UNAVAILABLE",
                ai_status=ai_status,
                fallback_reason=error_reason,
                evaluation_status="EXCLUDED_FROM_ACCURACY",
                is_valid=False,
                validation_errors=[f"AI_UNAVAILABLE: {ai_status} ({error_reason})"],
                diagnostic_type="DETERMINISTIC_DIAGNOSTIC",
                agent_ai_status="UNAVAILABLE",
                ai_thesis="NOT_GENERATED",
                deterministic_screen="NO_TRADE",
            )
            return self.thesis_validator.validate(thesis, structured_evidence=macro_evidence)

        # 2. Build initial MarketThesis from genuine AI output
        direction = ai_resp.get("direction", "NEUTRAL")
        expected_move = float(ai_resp.get("expected_move_pct", 0.0))
        horizon = ai_resp.get("horizon", "1D")
        confidence = float(ai_resp.get("confidence", 50.0))
        catalysts = ai_resp.get("catalysts") or ["Fundamental event driver"]
        invalidating_conditions = ai_resp.get("invalidating_conditions") or [
            "Unexpected policy rate hike",
            "Severe intraday gap-down against thesis",
            "Broad market risk-off selloff"
        ]
        reasoning = ai_resp.get("reasoning") or f"AI thesis for {symbol} under {self.strategy_version}"
        prov_model = getattr(self.llm_provider, "model", "openai/gpt-4o-mini")
        decision_model = ai_resp.get("decision_model") or f"OPENROUTER:{prov_model}"
        model_provider = ai_resp.get("model_provider") or "openrouter"
        model_version = ai_resp.get("model_version") or prov_model
        decision_mode = ai_resp.get("decision_mode") or "AI_INFERENCE"
        ai_status = "INFERENCE_SUCCESS"
        fallback_reason = None
        evaluation_status = "EVALUABLE"

        # 3. Extract and construct deterministic FundamentalContext
        from event_agent.fundamentals.fundamental_snapshot import FundamentalContext, FundamentalRole
        fund_snap = stock_data.get("fundamental_snapshot") or stock_data.get("fundamentals")
        fundamental_context = None

        if fund_snap is not None:
            if hasattr(fund_snap, "quality_score"):
                q_score = fund_snap.quality_score
                v_score = fund_snap.valuation_score
                g_score = fund_snap.growth_score
                bs_score = fund_snap.balance_sheet_score
                f_regime = fund_snap.fundamental_regime
                f_as_of = fund_snap.as_of.isoformat() if hasattr(fund_snap.as_of, "isoformat") else str(fund_snap.as_of)
                f_source = fund_snap.source
            else:
                q_score = fund_snap.get("quality_score")
                v_score = fund_snap.get("valuation_score")
                g_score = fund_snap.growth_score if hasattr(fund_snap, "growth_score") else fund_snap.get("growth_score")
                bs_score = fund_snap.get("balance_sheet_score")
                f_regime = fund_snap.get("fundamental_regime", "MIXED")
                f_as_of = str(fund_snap.get("as_of", ""))
                f_source = fund_snap.get("source", "UNKNOWN")

            # Determine confirmation vs contradiction deterministically
            is_bull = (direction == "BULLISH")
            confirmation = False
            contradiction = False
            fc_reason = ""

            if is_bull:
                if (q_score is not None and q_score >= 60.0) and f_regime != "STRESSED":
                    confirmation = True
                    fc_reason = "High quality score confirms bullish event continuation."
                elif f_regime == "STRESSED" or (q_score is not None and q_score < 35.0):
                    contradiction = True
                    fc_reason = f"Fundamental regime is {f_regime} (Quality: {q_score}); opposes bullish stance."
            else:
                if f_regime in ("STRESSED", "WEAKENING") or (q_score is not None and q_score < 40.0):
                    confirmation = True
                    fc_reason = f"Deteriorating fundamentals ({f_regime}) confirm bearish thesis."
                elif (q_score is not None and q_score >= 70.0) and (v_score is not None and v_score >= 60.0):
                    contradiction = True
                    fc_reason = f"High quality ({q_score}) and attractive valuation ({v_score}) contradict bearish thesis."

            fundamental_context = FundamentalContext(
                quality_score=q_score,
                valuation_score=v_score,
                growth_score=g_score,
                balance_sheet_score=bs_score,
                fundamental_regime=f_regime,
                confirmation=confirmation,
                contradiction=contradiction,
                data_as_of=f_as_of,
                source=f_source,
                role=FundamentalRole.VALUATION_CONTEXT.value,
                reasoning=fc_reason,
            )

        thesis = MarketThesis(
            agent_id=self.agent_id,
            symbol=symbol,
            direction=direction,
            expected_move_pct=expected_move,
            horizon=horizon,
            confidence=confidence,
            catalysts=catalysts,
            invalidating_conditions=invalidating_conditions,
            reasoning=reasoning,
            ai_request_id=ai_resp.get("ai_request_id"),
            model=prov_model,
            actual_provider="openrouter",
            fundamental_context=fundamental_context,
            decision_model=decision_model,
            model_provider=model_provider,
            model_version=model_version,
            decision_mode=decision_mode,
            ai_status=ai_status,
            fallback_reason=fallback_reason,
            evaluation_status=evaluation_status,
        )

        # 4. Deterministic Validation & Data Inconsistency Check
        validated_thesis = self.thesis_validator.validate(thesis, structured_evidence=macro_evidence)
        return validated_thesis

    def create_no_trade_proposal(
        self,
        reason: str,
        snapshot_id: str = "",
        confidence: float = 50.0,
    ) -> ProposedTrade:
        """Helper to create a structured NO_TRADE record."""
        return ProposedTrade(
            agent_id=self.agent_id,
            strategy_version=self.strategy_version,
            symbol="NIFTY50",
            action=TradeAction.NO_TRADE,
            instrument=Instrument(underlying="NIFTY50", instrument_type=InstrumentType.EQUITY),
            direction=TradeDirection.NONE,
            entry_price=0.0,
            stop_loss=0.0,
            target=0.0,
            confidence=confidence,
            expected_move_pct=0.0,
            planned_risk_amount=0.0,
            hedge_decision=HedgeDecision.NO,
            decision_reason=reason,
            snapshot_id=snapshot_id,
            sequence=1,
            position_side=PositionSide.LONG,
            order_action=TradeAction.NO_TRADE,
            order_intent=OrderIntent.OPEN,
        )
