# =============================================================================
# event_agent/arena/agents/agent_alpha.py — Event Intelligence Agent
# =============================================================================
"""
Agent Alpha (The Event Hunter) — Strategy Version: ALPHA-1.0
Philosophy: "I trade what changed."
Focus: Corporate earnings, news catalysts, regulatory filings, causal factors.
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
from ..asset_models import MultiLegStrategy, OptionInstrument, StrategyType
from ..options_engine import OptionsStrategyBuilder, OptionsStrategySelector
from .base_agent import BaseAgent


class AgentAlpha(BaseAgent):
    """
    Event-driven autonomous trading agent.
    """

    def __init__(self):
        profile = AgentProfile(
            id="ALPHA",
            name="Agent Alpha",
            title="The Event Hunter",
            personality_quote="I trade what changed.",
            strategy_version="ALPHA-1.0",
            strategy_description="Analyzes breaking news, quarterly earnings surprises, corporate actions, and regulatory announcements for asymmetric event alpha.",
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
        macro_risk = regime.get("dimensions", {}).get("risk", "NEUTRAL")

        existing_symbols = {p.get("symbol") for p in current_open_positions if p.get("status") == "OPEN"}
        candidates = []

        for symbol, data in stocks.items():
            if symbol in existing_symbols:
                continue

            catalysts = data.get("catalysts", [])
            sentiment = float(data.get("stock_sentiment", 0.0))
            conviction = float(data.get("conviction", 50.0))
            pred_pct = float(data.get("predicted_1d_pct", 0.0))
            base_price = float(data.get("base_price", 0.0))

            if base_price <= 0:
                continue

            # Alpha requires news/catalysts and conviction >= min_conviction (default 48.0% for paper trading)
            min_conviction = float(os.getenv("MIN_AGENT_CONVICTION", "48.0"))
            has_catalysts = len(catalysts) > 0 or abs(sentiment) >= 0.10
            if (has_catalysts or conviction >= min_conviction) and conviction >= min_conviction and abs(pred_pct) >= 0.35:
                candidates.append((symbol, data, max(abs(sentiment), 0.15) * conviction))

        # Sort candidates by news impact score descending
        candidates.sort(key=lambda x: x[2], reverse=True)

        if not candidates:
            return [
                self.create_no_trade_proposal(
                    reason="No high-conviction corporate news or earnings catalysts detected in current market cutoff.",
                    snapshot_id=snapshot_id,
                    confidence=55.0,
                )
            ]

        # Select top opportunities (limit to open slots)
        available_slots = max(0, 10 - len(existing_symbols))
        selected = candidates[:min(available_slots, 3)]

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
                reason="All event candidates failed quality, risk hurdle, or portfolio exposure checks.",
                snapshot_id=snapshot_id,
                confidence=55.0,
            )
        ]
