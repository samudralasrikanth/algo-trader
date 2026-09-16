# =============================================================================
# event_agent/arena/agents/agent_macro.py — Macro Intelligence Agent
# =============================================================================
"""
Agent Macro (The Economist) — Strategy Version: MACRO-1.0
Philosophy: "I trade the environment."
Focus: RBI Repo, US Fed rates, CPI inflation, bond yields, USD/INR, Crude oil.
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


class AgentMacro(BaseAgent):
    """
    Top-down macroeconomic environment agent.
    """

    def __init__(self):
        profile = AgentProfile(
            id="MACRO",
            name="Agent Macro",
            title="The Economist",
            personality_quote="I trade the environment.",
            strategy_version="MACRO-1.0",
            strategy_description="Translates central bank policy rates, sovereign bond yields, currency dynamics, and crude shocks into sector asset allocation.",
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
        dims = regime.get("dimensions", {})

        monetary = dims.get("monetary", "NEUTRAL")
        inflation = dims.get("inflation", "NEUTRAL")
        risk = dims.get("risk", "NEUTRAL")

        # Macro gating: If uncertainty is severe, stay in cash
        if monetary == "HAWKISH" and inflation == "HOT" and risk == "RISK_OFF":
            return [
                self.create_no_trade_proposal(
                    reason="Conflicting macro signals and stagflationary headwind (Hawkish RBI + Hot CPI + Risk-Off). Capital preserved in cash.",
                    snapshot_id=snapshot_id,
                    confidence=62.0,
                )
            ]

        existing_symbols = {p.get("symbol") for p in current_open_positions if p.get("status") == "OPEN"}
        macro_sectors = {"Private Banking", "Oil & Gas / Conglomerate", "IT Services", "Automobile"}
        candidates = []

        for symbol, data in stocks.items():
            if symbol in existing_symbols:
                continue

            sector = data.get("sector", "")
            is_macro_sensitive = any(ms.lower() in sector.lower() for ms in macro_sectors)
            conviction = float(data.get("conviction", 50.0))
            pred_pct = float(data.get("predicted_1d_pct", 0.0))
            base_price = float(data.get("base_price", 0.0))

            if base_price <= 0:
                continue

            min_conviction = float(os.getenv("MIN_AGENT_CONVICTION", "48.0"))
            if is_macro_sensitive and conviction >= min_conviction and abs(pred_pct) >= 0.30:
                candidates.append((symbol, data, conviction))

        candidates.sort(key=lambda x: x[2], reverse=True)

        if not candidates:
            return [
                self.create_no_trade_proposal(
                    reason="Macro risk premium does not justify equity exposure across interest-rate and currency sensitive sectors.",
                    snapshot_id=snapshot_id,
                    confidence=56.0,
                )
            ]

        available_slots = max(0, 10 - len(existing_symbols))
        selected = candidates[:min(available_slots, 4)]

        proposals = []
        for seq, (symbol, data, _) in enumerate(selected, 1):
            base_price = float(data.get("base_price", 0.0))
            pred_pct = float(data.get("predicted_1d_pct", 0.0))
            conviction = float(data.get("conviction", 65.0))
            direction = TradeDirection.BUY if pred_pct >= 0 else TradeDirection.SELL
            action = TradeAction.BUY if pred_pct >= 0 else TradeAction.SELL

            if direction == TradeDirection.BUY:
                target = base_price * (1.0 + abs(pred_pct) / 100.0)
                stop = base_price * (1.0 - (abs(pred_pct) * 0.7) / 100.0)
            else:
                target = base_price * (1.0 - abs(pred_pct) / 100.0)
                stop = base_price * (1.0 + (abs(pred_pct) * 0.7) / 100.0)

            needs_hedge = risk == "RISK_OFF"
            hedge_dec = HedgeDecision.YES if needs_hedge else HedgeDecision.NO
            hedge_inst = "NIFTY-FUT-HEDGE" if needs_hedge else None

            reason = f"Macro liquidity & interest rate alignment in {data.get('sector')}. Forecast move {pred_pct:+.2f}%."
            if needs_hedge:
                reason += " NIFTY Futures hedge short overlay active due to global yield pressure."

            inst = Instrument(underlying=symbol, instrument_type=InstrumentType.EQUITY)

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
