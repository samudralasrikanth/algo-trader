# =============================================================================
# event_agent/arena/agents/agent_contrarian.py — Mean Reversion Agent
# =============================================================================
"""
Agent Contrarian (The Contrarian) — Strategy Version: CONTRARIAN-1.0
Philosophy: "Everyone can't be right."
Focus: Overbought/oversold RSI extremes, panic dip buying, priced-in reversals.
"""

from typing import Any, Dict, List
from ..models import (
    AgentProfile,
    HedgeDecision,
    Instrument,
    InstrumentType,
    ProposedTrade,
    TradeAction,
    TradeDirection,
)
from .base_agent import BaseAgent


class AgentContrarian(BaseAgent):
    """
    Mean-reversion and sentiment exhaustion contrarian agent.
    """

    def __init__(self):
        profile = AgentProfile(
            id="CONTRARIAN",
            name="Agent Contrarian",
            title="The Contrarian",
            personality_quote="Everyone can't be right.",
            strategy_version="CONTRARIAN-1.0",
            strategy_description="Identifies sentiment overreaction, oversold panic dips, and faded consensus expectations for sharp mean reversion.",
            starting_capital=20_00_000.0,
        )
        super().__init__(profile)

    def evaluate_market(
        self,
        market_snapshot: Dict[str, Any],
        current_open_positions: List[Dict[str, Any]],
        current_equity: float,
        current_cash: float,
    ) -> List[ProposedTrade]:
        stocks = market_snapshot.get("stocks", {})
        snapshot_id = market_snapshot.get("snapshot_id", "")
        existing_symbols = {p.get("symbol") for p in current_open_positions if p.get("status") == "OPEN"}
        candidates = []

        for symbol, data in stocks.items():
            if symbol in existing_symbols:
                continue

            momentum_5d = float(data.get("momentum_5d_pct", 0.0))
            sentiment = float(data.get("stock_sentiment", 0.0))
            conviction = float(data.get("conviction", 50.0))
            base_price = float(data.get("base_price", 0.0))

            if base_price <= 0:
                continue

            # Contrarian triggers on extreme move (>2.0% or <-2.0%) or extreme negative sentiment (< -0.30)
            is_oversold_dip = (momentum_5d <= -1.8 or sentiment <= -0.30) and conviction >= 60.0
            is_overbought_exhaustion = (momentum_5d >= 2.2 and sentiment >= 0.40) and conviction >= 60.0

            if is_oversold_dip:
                candidates.append((symbol, data, TradeDirection.BUY, abs(momentum_5d), "Oversold panic dip mean-reversion"))
            elif is_overbought_exhaustion:
                candidates.append((symbol, data, TradeDirection.SELL, abs(momentum_5d), "Overbought consensus exhaustion fade"))

        candidates.sort(key=lambda x: x[3], reverse=True)

        if not candidates:
            return [
                self.create_no_trade_proposal(
                    reason="Market prices in equilibrium. No extreme panic selloffs or manic overextensions detected.",
                    snapshot_id=snapshot_id,
                    confidence=58.0,
                )
            ]

        available_slots = max(0, 10 - len(existing_symbols))
        selected = candidates[:min(available_slots, 4)]

        proposals = []
        for seq, (symbol, data, direction, _, rationale) in enumerate(selected, 1):
            base_price = float(data.get("base_price", 0.0))
            action = TradeAction.BUY if direction == TradeDirection.BUY else TradeAction.SELL
            conviction = float(data.get("conviction", 64.0))

            # Mean-reversion target
            if direction == TradeDirection.BUY:
                target = base_price * 1.018
                stop = base_price * 0.988
                exp_pct = 1.8
            else:
                target = base_price * 0.982
                stop = base_price * 1.012
                exp_pct = -1.8

            inst = Instrument(underlying=symbol, instrument_type=InstrumentType.EQUITY)
            reason = f"{rationale}. Fading consensus expecting swift reversion toward 20-day mean."

            proposals.append(
                ProposedTrade(
                    agent_id=self.agent_id,
                    strategy_version=self.strategy_version,
                    symbol=symbol,
                    action=action,
                    instrument=inst,
                    direction=direction,
                    entry_price=base_price,
                    stop_loss=stop,
                    target=target,
                    confidence=conviction,
                    expected_move_pct=exp_pct,
                    planned_risk_amount=current_equity * 0.005,
                    hedge_decision=HedgeDecision.NO,
                    hedge_instrument=None,
                    decision_reason=reason,
                    snapshot_id=snapshot_id,
                    sequence=seq,
                )
            )

        return proposals
