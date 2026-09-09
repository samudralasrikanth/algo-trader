# =============================================================================
# event_agent/arena/agents/agent_alpha.py — Event Intelligence Agent
# =============================================================================
"""
Agent Alpha (The Event Hunter) — Strategy Version: ALPHA-1.0
Philosophy: "I trade what changed."
Focus: Corporate earnings, news catalysts, regulatory filings, causal factors.
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

            # Alpha requires news/catalysts and conviction >= 60%
            has_catalysts = len(catalysts) > 0 or abs(sentiment) >= 0.15
            if has_catalysts and conviction >= 60.0 and abs(pred_pct) >= 0.4:
                candidates.append((symbol, data, abs(sentiment) * conviction))

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

        # Select at most 0 to 10 opportunities (limit to open slots)
        available_slots = max(0, 10 - len(existing_symbols))
        selected = candidates[:min(available_slots, 6)]

        proposals = []
        for seq, (symbol, data, _) in enumerate(selected, 1):
            base_price = float(data.get("base_price", 0.0))
            pred_pct = float(data.get("predicted_1d_pct", 0.0))
            conviction = float(data.get("conviction", 65.0))
            direction = TradeDirection.BUY if pred_pct >= 0 else TradeDirection.SELL
            action = TradeAction.BUY if pred_pct >= 0 else TradeAction.SELL

            # Calculate levels
            if direction == TradeDirection.BUY:
                target = base_price * (1.0 + abs(pred_pct) / 100.0)
                stop = base_price * (1.0 - (abs(pred_pct) * 0.6) / 100.0)
            else:
                target = base_price * (1.0 - abs(pred_pct) / 100.0)
                stop = base_price * (1.0 + (abs(pred_pct) * 0.6) / 100.0)

            # Optional Hedge Decision
            needs_hedge = macro_risk in ("RISK_OFF", "HOT", "HIGH_VOLATILITY")
            hedge_dec = HedgeDecision.YES if needs_hedge else HedgeDecision.NO
            hedge_inst = "NIFTY-PE-24500" if needs_hedge else None

            catalyst_summary = ", ".join(data.get("catalysts", [])[:2]) or "Fundamental sentiment catalyst"
            reason = f"Event catalyst confirmed: {catalyst_summary}. Predicted move {pred_pct:+.2f}% with {conviction:.0f}% conviction."
            if needs_hedge:
                reason += " Elevated macro risk detected; NIFTY PUT hedge attached."

            inst_type = InstrumentType.EQUITY
            inst = Instrument(underlying=symbol, instrument_type=inst_type)

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
                    hedge_decision=hedge_dec,
                    hedge_instrument=hedge_inst,
                    decision_reason=reason,
                    snapshot_id=snapshot_id,
                    sequence=seq,
                )
            )

        return proposals
