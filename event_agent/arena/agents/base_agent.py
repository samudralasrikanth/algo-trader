# =============================================================================
# event_agent/arena/agents/base_agent.py — Abstract Base Strategy Agent
# =============================================================================
"""
Base class defining standard behavior for all 5 Arena Strategy Agents:
- Identical immutable market snapshot input for all 50 stocks
- 0 to 10 dynamic active allocations
- Explicit NO_TRADE emission when criteria are unfulfilled
- Frozen strategy versioning
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..models import (
    AgentProfile,
    HedgeDecision,
    Instrument,
    InstrumentType,
    OptionType,
    ProposedTrade,
    TradeAction,
    TradeDirection,
)


class BaseAgent(ABC):
    """
    Abstract Strategy Agent participating in the Nifty 50 AI Trading Arena.
    """

    def __init__(self, profile: AgentProfile):
        self.profile = profile

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
        )
