# =============================================================================
# event_agent/arena/agents/agent_defensive.py — Capital Preservation Agent
# =============================================================================
"""
Agent Defensive (The Capital Protector) — Strategy Version: DEFENSIVE-1.0
Philosophy: "Survive first. Profit second."
Focus: Low beta, FMCG/Pharma dividend stability, conservative sizing, Put hedging.
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


class AgentDefensive(BaseAgent):
    """
    Capital-preservation and drawdown-minimizing agent.
    """

    def __init__(self):
        profile = AgentProfile(
            id="DEFENSIVE",
            name="Agent Defensive",
            title="The Capital Protector",
            personality_quote="Survive first. Profit second.",
            strategy_version="DEFENSIVE-1.0",
            strategy_description="Prioritizes capital protection, low-beta blue chips, high cash allocation, and systematic downside Put options protection.",
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
        regime = market_snapshot.get("regime", {})
        volatility = regime.get("dimensions", {}).get("volatility", "NORMAL")

        # In elevated volatility environments, Defensive stays 100% in cash
        if volatility in ("HIGH", "EXTREME"):
            return [
                self.create_no_trade_proposal(
                    reason="Volatility spike detected in India VIX. 100% cash preservation protocol triggered.",
                    snapshot_id=snapshot_id,
                    confidence=75.0,
                )
            ]

        existing_symbols = {p.get("symbol") for p in current_open_positions if p.get("status") == "OPEN"}
        defensive_sectors = {"FMCG", "Pharmaceuticals", "Power Transmission"}
        candidates = []

        for symbol, data in stocks.items():
            if symbol in existing_symbols:
                continue

            beta = float(data.get("beta", 1.0))
            sector = data.get("sector", "")
            conviction = float(data.get("conviction", 50.0))
            pred_pct = float(data.get("predicted_1d_pct", 0.0))
            base_price = float(data.get("base_price", 0.0))

            if base_price <= 0:
                continue

            # Defensive requires low beta (<0.90) or defensive sector, and conviction >= min_conviction
            min_conviction = float(os.getenv("MIN_AGENT_CONVICTION", "48.0"))
            is_low_beta = beta < 0.90 or any(ds.lower() in sector.lower() for ds in defensive_sectors)
            if is_low_beta and conviction >= min_conviction and pred_pct > 0.15:
                # Defensive primarily trades long high-quality stocks
                candidates.append((symbol, data, conviction / beta))

        candidates.sort(key=lambda x: x[2], reverse=True)

        if not candidates:
            return [
                self.create_no_trade_proposal(
                    reason="No low-beta defensive assets meet minimum risk-adjusted margin of safety.",
                    snapshot_id=snapshot_id,
                    confidence=60.0,
                )
            ]

        # Defensive holds at most 4 positions at a time to keep cash > 60%
        available_slots = max(0, 4 - len(existing_symbols))
        selected = candidates[:min(available_slots, 3)]

        if not selected:
            return [
                self.create_no_trade_proposal(
                    reason="Maximum defensive exposure ceiling reached. Preserving healthy cash reserves.",
                    snapshot_id=snapshot_id,
                    confidence=68.0,
                )
            ]

        proposals = []
        for seq, (symbol, data, _) in enumerate(selected, 1):
            # 1. Real Decision-Time AI inference & deterministic thesis validation
            thesis = self.generate_and_validate_thesis(
                symbol=symbol,
                stock_data=data,
                market_snapshot=market_snapshot,
            )

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
                reason="All defensive setups failed quality, risk hurdle, or portfolio exposure checks.",
                snapshot_id=snapshot_id,
                confidence=60.0,
            )
        ]
