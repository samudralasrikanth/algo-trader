# =============================================================================
# event_agent/arena/agents/agent_momentum.py — Trend & Breakout Agent
# =============================================================================
"""
Agent Momentum (The Trend Chaser) — Strategy Version: MOMENTUM-1.0
Philosophy: "I follow strength."
Focus: 5D/20D trend persistence, volume expansion, breakout continuation.
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


class AgentMomentum(BaseAgent):
    """
    Trend-following momentum agent.
    """

    def __init__(self):
        profile = AgentProfile(
            id="MOMENTUM",
            name="Agent Momentum",
            title="The Trend Chaser",
            personality_quote="I follow strength.",
            strategy_version="MOMENTUM-1.0",
            strategy_description="Identifies persistent price trends, breakout volume, and relative strength leaders outperforming the Nifty benchmark.",
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

            momentum_5d = float(data.get("momentum_5d_pct", data.get("predicted_1d_pct", 0.0)))
            conviction = float(data.get("conviction", 50.0))
            base_price = float(data.get("base_price", 0.0))

            if base_price <= 0:
                continue

            # Momentum threshold: Strong trend (>0.6% or <-0.6%) and conviction >= 60%
            if abs(momentum_5d) >= 0.6 and conviction >= 60.0:
                candidates.append((symbol, data, abs(momentum_5d)))

        candidates.sort(key=lambda x: x[2], reverse=True)

        if not candidates:
            return [
                self.create_no_trade_proposal(
                    reason="Market breadth is in choppy sideways consolidation. No clean breakout trends exceed momentum hurdle.",
                    snapshot_id=snapshot_id,
                    confidence=58.0,
                )
            ]

        available_slots = max(0, 10 - len(existing_symbols))
        selected = candidates[:min(available_slots, 5)]

        proposals = []
        for seq, (symbol, data, mom_val) in enumerate(selected, 1):
            base_price = float(data.get("base_price", 0.0))
            pred_pct = float(data.get("predicted_1d_pct", 0.0))
            conviction = float(data.get("conviction", 65.0))
            direction = TradeDirection.BUY if pred_pct >= 0 else TradeDirection.SELL
            action = TradeAction.BUY if pred_pct >= 0 else TradeAction.SELL

            # Stop and target for momentum (wider target, tight trailing stop)
            if direction == TradeDirection.BUY:
                target = base_price * (1.0 + (abs(pred_pct) * 1.3) / 100.0)
                stop = base_price * (1.0 - (abs(pred_pct) * 0.5) / 100.0)
            else:
                target = base_price * (1.0 - (abs(pred_pct) * 1.3) / 100.0)
                stop = base_price * (1.0 + (abs(pred_pct) * 0.5) / 100.0)

            # High momentum uses simulated futures contracts for capital efficiency
            use_futures = abs(pred_pct) >= 1.2
            inst_type = InstrumentType.FUTURE if use_futures else InstrumentType.EQUITY
            inst = Instrument(underlying=symbol, instrument_type=inst_type, expiry="NEAR")

            reason = f"5-day momentum breakout of {mom_val:+.2f}% with strong trend continuation score."
            if use_futures:
                reason += " Simulated Futures contract selected for trend gearing."

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
                    expected_move_pct=pred_pct,
                    planned_risk_amount=current_equity * 0.005,
                    hedge_decision=HedgeDecision.NO,
                    hedge_instrument=None,
                    decision_reason=reason,
                    snapshot_id=snapshot_id,
                    sequence=seq,
                )
            )

        return proposals
