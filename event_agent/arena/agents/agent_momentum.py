# =============================================================================
# event_agent/arena/agents/agent_momentum.py — Trend & Breakout Agent
# =============================================================================
"""
Agent Momentum (The Trend Chaser) — Strategy Version: MOMENTUM-1.0
Philosophy: "I follow strength."
Focus: 5D/20D trend persistence, volume expansion, breakout continuation.
"""

import os
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

            # Momentum threshold: Strong trend (>0.5% or <-0.5%) and conviction >= min_conviction (default 48.0% for paper trading)
            min_conviction = float(os.getenv("MIN_AGENT_CONVICTION", "60.0"))
            if abs(momentum_5d) >= 0.5 and conviction >= min_conviction:
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
        selected = candidates[:min(available_slots, 3)]

        proposals = []
        for seq, (symbol, data, mom_val) in enumerate(selected, 1):
            # 1. Real Decision-Time AI inference & deterministic thesis validation
            thesis = self.generate_and_validate_thesis(
                symbol=symbol,
                stock_data=data,
                market_snapshot=market_snapshot,
            )

            # Fundamentals as context modifier (never destroying valid short-term momentum)
            if thesis.fundamental_context:
                if thesis.fundamental_context.confirmation:
                    thesis.reasoning += " [Fundamentals: Strong quality confirms momentum persistence]"
                elif thesis.fundamental_context.contradiction:
                    thesis.reasoning += " [Fundamentals: Caution noted on balance sheet; tactical trend momentum preserved]"

            # 2. Route thesis through Central Deterministic Instrument Selector
            proposal = self.instrument_selector.select_instrument(
                thesis=thesis,
                stock_data=data,
                portfolio_equity=current_equity,
                current_open_positions=current_open_positions,
                snapshot_id=snapshot_id,
                sequence=seq,
            )
            proposals.append(proposal)

        return proposals if proposals else [
            self.create_no_trade_proposal(
                reason="All momentum breakout setups failed net edge hurdle, risk/reward, or portfolio risk limits.",
                snapshot_id=snapshot_id,
                confidence=58.0,
            )
        ]
