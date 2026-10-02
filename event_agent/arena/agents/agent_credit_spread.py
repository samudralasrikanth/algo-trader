# =============================================================================
# event_agent/arena/agents/agent_credit_spread.py — NIFTY 50 Credit Spread Agent
# =============================================================================
"""
Agent Credit Spread (The Hedged Income Specialist) — Strategy Version: CREDIT_SPREAD-1.0
Role & Objective:
Autonomous Quantitative Trading Agent executing Hedged Option Selling (Credit Spreads)
on the NIFTY 50 index to generate consistent alpha while strictly capping maximum loss.
Strict Invariant: Never execute naked option writing. Every short position must be paired
with a long protective leg.

Capital & Sizing Limits:
- Total Allocated Capital: ₹1,20,000 (Paper Capital).
- Margin per Hedged Lot: ~₹40,000.
- Max Lot Size: 2 Lots (Reserving ~₹40,000 as buffer capital).
- Max Risk per Trade: 2% of Total Capital (₹2,400 Max Loss Limit).

Strategy Logic:
- BEARISH or NEUTRAL-BEARISH -> Deploy Bear Call Spread (Sell Call delta ~0.25-0.30; Buy Call +100-200 pts).
- BULLISH or NEUTRAL-BULLISH -> Deploy Bull Put Spread (Sell Put delta ~ -0.25 to -0.30; Buy Put -100-200 pts).
- Net Credit Validation: Premium Collected > Premium Paid.

Risk Gates & Execution Rules:
- DTE: 3 to 7 Days to Expiry. 0 DTE (Expiry Day) strictly prohibited to prevent gamma spikes.
- Stop-Loss: 50% expansion of credit collected or ₹2,400 hard cutoff.
- Take-Profit: 80% of maximum potential profit (frees margin, protects from last-minute reversals).
- VIX Check: If India VIX > 20, widen spread width to 200 points.

Terminal Output Format:
[ACTION: EXECUTE] STRATEGY: [Bull Put / Bear Call] | SELL: [Strike] [CE/PE] @ [LTP] | BUY: [Strike] [CE/PE] @ [LTP] | NET CREDIT: [₹] | MAX PROFIT: [₹] | MAX RISK: [₹]
"""

import logging
import sys
from typing import Any, Dict, List, Optional, Tuple

from ..asset_models import StrategyType
from ..models import (
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
from ..option_chain_provider import OptionChainProvider
from ..options_engine import DEFAULT_LOT_SIZE, OptionsStrategyBuilder
from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class AgentCreditSpread(BaseAgent):
    """
    Autonomous NIFTY 50 Credit Spread Quantitative Agent.
    """

    TOTAL_ALLOCATED_CAPITAL: float = 120_000.0
    MARGIN_PER_HEDGED_LOT: float = 40_000.0
    MAX_LOT_SIZE: int = 2
    BUFFER_CAPITAL: float = 40_000.0
    MAX_RISK_PER_TRADE: float = 2_400.0
    TARGET_PROFIT_RATIO: float = 0.80
    STOP_LOSS_RATIO: float = 0.50
    MIN_DTE: int = 3
    MAX_DTE: int = 7

    def __init__(self, option_provider: Optional[OptionChainProvider] = None):
        profile = AgentProfile(
            id="CREDIT_SPREAD",
            name="Agent Credit Spread",
            title="NIFTY 50 Credit Spread Specialist",
            personality_quote="Hedged option selling generates consistent alpha; strictly capped risk, never naked.",
            strategy_version="CREDIT_SPREAD-1.0",
            strategy_description=(
                "Executes hedged Bear Call Spreads and Bull Put Spreads on NIFTY 50 "
                "with delta ~0.25 strike selection, strict 2% risk gating, and systematic profit-taking at 80%."
            ),
            starting_capital=120_000.0,
        )
        super().__init__(profile)
        self.option_provider = option_provider or OptionChainProvider()

    def format_execution_log(
        self,
        strategy_name: str,
        sell_strike: float,
        sell_type: str,
        sell_ltp: float,
        buy_strike: float,
        buy_type: str,
        buy_ltp: float,
        net_credit: float,
        max_profit: float,
        max_risk: float,
    ) -> str:
        """
        Exact Terminal Execution Logging Format:
        [ACTION: EXECUTE] STRATEGY: [Bull Put / Bear Call] | SELL: [Strike] [CE/PE] @ [LTP] | BUY: [Strike] [CE/PE] @ [LTP] | NET CREDIT: [₹] | MAX PROFIT: [₹] | MAX RISK: [₹]
        """
        return (
            f"[ACTION: EXECUTE] STRATEGY: {strategy_name} | "
            f"SELL: {int(sell_strike)} {sell_type} @ {sell_ltp:.2f} | "
            f"BUY: {int(buy_strike)} {buy_type} @ {buy_ltp:.2f} | "
            f"NET CREDIT: ₹{net_credit:.2f} | "
            f"MAX PROFIT: ₹{max_profit:.2f} | "
            f"MAX RISK: ₹{max_risk:.2f}"
        )

    def extract_market_view(self, market_snapshot: Dict[str, Any]) -> Tuple[str, str]:
        """
        Ingests the Central AI Market View:
        Returns: (market_view_label, detailed_reason)
        Possible views: BEARISH, NEUTRAL-BEARISH, BULLISH, NEUTRAL-BULLISH, NEUTRAL
        """
        # 1. Direct explicit market view key
        explicit_view = market_snapshot.get("market_view") or market_snapshot.get("central_ai_view")
        if explicit_view:
            v_upper = str(explicit_view).upper()
            if "BEAR" in v_upper:
                return ("BEARISH" if "NEUTRAL" not in v_upper else "NEUTRAL-BEARISH"), f"Explicit Central AI View: {explicit_view}"
            if "BULL" in v_upper:
                return ("BULLISH" if "NEUTRAL" not in v_upper else "NEUTRAL-BULLISH"), f"Explicit Central AI View: {explicit_view}"

        # 2. Index specific forecast (e.g. ^NSEI or NIFTY50)
        stocks = market_snapshot.get("stocks", {})
        index_data = stocks.get("^NSEI") or stocks.get("NIFTY50")
        if index_data:
            dir_str = str(index_data.get("direction", "")).upper()
            pred_pct = float(index_data.get("predicted_1d_pct", 0.0))
            if "BEAR" in dir_str or pred_pct < -0.30:
                view = "BEARISH" if pred_pct < -0.80 else "NEUTRAL-BEARISH"
                return view, f"Index forecast: {dir_str} ({pred_pct:+.2f}%)"
            elif "BULL" in dir_str or pred_pct > 0.30:
                view = "BULLISH" if pred_pct > 0.80 else "NEUTRAL-BULLISH"
                return view, f"Index forecast: {dir_str} ({pred_pct:+.2f}%)"

        # 3. Macro / Composite regime
        regime = market_snapshot.get("regime", {})
        regime_label = str(regime.get("label", "NEUTRAL")).upper()
        composite = float(regime.get("composite", 0.0))
        risk_dim = str(regime.get("dimensions", {}).get("risk", "NEUTRAL")).upper()

        if "BEAR" in regime_label or risk_dim in ("RISK_OFF", "HIGH_RISK") or composite < -0.15:
            view = "BEARISH" if composite < -0.30 else "NEUTRAL-BEARISH"
            return view, f"Macro Regime: {regime_label} (composite: {composite:.2f}, risk: {risk_dim})"

        if "BULL" in regime_label or risk_dim in ("RISK_ON", "LOW_RISK") or composite > 0.15:
            view = "BULLISH" if composite > 0.30 else "NEUTRAL-BULLISH"
            return view, f"Macro Regime: {regime_label} (composite: {composite:.2f}, risk: {risk_dim})"

        # 4. Aggregated market breadth across NIFTY 50 universe
        if stocks:
            bullish_count = sum(1 for s in stocks.values() if float(s.get("predicted_1d_pct", 0.0)) > 0.10)
            bearish_count = sum(1 for s in stocks.values() if float(s.get("predicted_1d_pct", 0.0)) < -0.10)
            if bearish_count > bullish_count * 1.3:
                return "NEUTRAL-BEARISH", f"Universe breadth: {bearish_count} bearish vs {bullish_count} bullish"
            elif bullish_count > bearish_count * 1.3:
                return "NEUTRAL-BULLISH", f"Universe breadth: {bullish_count} bullish vs {bearish_count} bearish"

        return "NEUTRAL", "Balanced neutral market regime without directional conviction"

    def evaluate_market(
        self,
        market_snapshot: Dict[str, Any],
        current_open_positions: List[Dict[str, Any]],
        current_equity: float,
        current_cash: float,
    ) -> List[ProposedTrade]:
        """
        Evaluates market regime, selects delta ~0.25 strikes, validates net credit,
        and constructs hedged Bull Put or Bear Call Spreads.
        """
        snapshot_id = market_snapshot.get("snapshot_id", "")
        regime = market_snapshot.get("regime", {})
        stocks = market_snapshot.get("stocks", {})

        # 1. Existing Position and Capital Gates
        # Reserving ~₹40,000 as buffer capital from ₹1,20,000 total capital
        open_credit_spreads = [
            p for p in current_open_positions
            if p.get("status") == "OPEN" and "SPREAD" in str(p.get("strategy_type", ""))
        ]
        if len(open_credit_spreads) >= 1:
            return [
                self.create_no_trade_proposal(
                    reason="Max 2-lot spread allocation active. ₹40,000 buffer capital reserved.",
                    snapshot_id=snapshot_id,
                    confidence=70.0,
                )
            ]

        # Minimum required margin for 2 lots = ₹80,000
        min_required_margin = self.MARGIN_PER_HEDGED_LOT * self.MAX_LOT_SIZE
        if current_cash < min_required_margin:
            return [
                self.create_no_trade_proposal(
                    reason=f"Insufficient margin cash (₹{current_cash:,.2f} < ₹{min_required_margin:,.2f} required for 2 lots)",
                    snapshot_id=snapshot_id,
                    confidence=60.0,
                )
            ]

        # 2. DTE Gate: 3 to 7 Days to Expiry (Prohibit 0 DTE / Expiry Day)
        dte = int(market_snapshot.get("days_to_expiry", 7))
        if dte == 0:
            return [
                self.create_no_trade_proposal(
                    reason="DTE Gate: Expiry Day (0 DTE) trading prohibited to avoid gamma spikes.",
                    snapshot_id=snapshot_id,
                    confidence=90.0,
                )
            ]
        if dte < self.MIN_DTE or dte > self.MAX_DTE:
            return [
                self.create_no_trade_proposal(
                    reason=f"DTE Gate: {dte} DTE is outside approved {self.MIN_DTE}-{self.MAX_DTE} days weekly window.",
                    snapshot_id=snapshot_id,
                    confidence=75.0,
                )
            ]

        # 3. India VIX Gate
        # If India VIX > 20, widen spread width to 200 points to account for higher volatility
        vix = float(
            regime.get("india_vix")
            or market_snapshot.get("india_vix")
            or market_snapshot.get("vix")
            or 15.0
        )
        spread_width = 200.0 if vix > 20.0 else 100.0

        # 4. Central AI Market View Ingestion
        market_view, view_reason = self.extract_market_view(market_snapshot)

        if market_view == "NEUTRAL":
            return [
                self.create_no_trade_proposal(
                    reason=f"Market View is neutral without directional edge ({view_reason}). Preserving capital.",
                    snapshot_id=snapshot_id,
                    confidence=65.0,
                )
            ]

        # 5. Underlying NIFTY Spot Price & Option Chain
        index_data = stocks.get("^NSEI") or stocks.get("NIFTY50")
        if index_data:
            nifty_spot = float(index_data.get("base_price", 25000.0))
        else:
            nifty_spot = 25000.0

        iv = float(regime.get("implied_volatility", vix / 100.0 if vix > 0 else 0.15))
        chain, _ = self.option_provider.get_chain(
            underlying="^NSEI",
            spot_price=nifty_spot,
            expiry=f"{dte}D",
            days_to_expiry=dte,
            implied_volatility=iv,
        )

        total_quantity = DEFAULT_LOT_SIZE * self.MAX_LOT_SIZE  # 2 lots = 100 shares

        # 6. Condition A: BEARISH or NEUTRAL-BEARISH -> Deploy Bear Call Spread
        if market_view in ("BEARISH", "NEUTRAL-BEARISH"):
            sell_k, buy_k, _ = OptionsStrategyBuilder.select_credit_spread_strikes(
                chain=chain,
                is_call=True,
                spot_price=nifty_spot,
                vix=vix,
                target_delta=0.275,
            )

            try:
                strategy = OptionsStrategyBuilder.create_bear_call_spread(
                    underlying="^NSEI",
                    spot_price=nifty_spot,
                    sell_strike=sell_k,
                    buy_strike=buy_k,
                    expiry_days=dte,
                    volatility=iv,
                    lot_size=DEFAULT_LOT_SIZE,
                    quantity=total_quantity,
                    agent_id="CREDIT_SPREAD",
                    snapshot_id=snapshot_id,
                )
            except ValueError as val_err:
                return [
                    self.create_no_trade_proposal(
                        reason=f"Bear Call Spread validation error: {val_err}",
                        snapshot_id=snapshot_id,
                        confidence=60.0,
                    )
                ]

            sell_leg = next(leg for leg in strategy.legs if leg.side.value == "SELL")
            buy_leg = next(leg for leg in strategy.legs if leg.side.value == "BUY")

            # Exact Terminal Format Logging
            exec_log = self.format_execution_log(
                strategy_name="Bear Call",
                sell_strike=sell_leg.instrument.strike,
                sell_type="CE",
                sell_ltp=sell_leg.entry_price,
                buy_strike=buy_leg.instrument.strike,
                buy_type="CE",
                buy_ltp=buy_leg.entry_price,
                net_credit=strategy.net_credit,
                max_profit=strategy.max_profit,
                max_risk=strategy.max_loss,
            )
            logger.info(exec_log)
            print(exec_log, file=sys.stdout, flush=True)

            inst = Instrument(
                underlying="^NSEI",
                instrument_type=InstrumentType.OPTION,
                expiry=f"{dte}D",
                strike=sell_leg.instrument.strike,
                option_type=OptionType.CE,
                contract_name=f"NIFTY-BEAR-CALL-{int(sell_k)}-{int(buy_k)}",
                lot_size=DEFAULT_LOT_SIZE,
            )

            proposal = ProposedTrade(
                agent_id="CREDIT_SPREAD",
                strategy_version=self.profile.strategy_version,
                symbol="^NSEI",
                action=TradeAction.BUY,  # Enters multi-leg package
                instrument=inst,
                direction=TradeDirection.SELL,
                entry_price=round(strategy.net_debit, 2),
                stop_loss=round(strategy.stop_loss_amount, 2),
                target=round(strategy.target_profit_amount, 2),
                confidence=78.0,
                expected_move_pct=-1.5,
                planned_risk_amount=strategy.max_loss,
                hedge_decision=HedgeDecision.YES,
                decision_reason=exec_log,
                snapshot_id=snapshot_id,
                sequence=1,
                strategy=strategy,
                thesis=f"Bear Call Spread deployed on {market_view} view. {view_reason}. Delta 0.25 sell leg at {sell_k}.",
                evidence=[view_reason, f"India VIX: {vix:.1f}", f"Spread width: {spread_width} pts"],
                horizon=f"{dte}D",
                expected_return=round(strategy.max_profit / strategy.net_debit * 100.0, 2),
                position_side=PositionSide.SHORT,
                order_action=TradeAction.BUY,
                order_intent=OrderIntent.OPEN,
            )
            return [proposal]

        # 7. Condition B: BULLISH or NEUTRAL-BULLISH -> Deploy Bull Put Spread
        elif market_view in ("BULLISH", "NEUTRAL-BULLISH"):
            sell_k, buy_k, _ = OptionsStrategyBuilder.select_credit_spread_strikes(
                chain=chain,
                is_call=False,
                spot_price=nifty_spot,
                vix=vix,
                target_delta=0.275,
            )

            try:
                strategy = OptionsStrategyBuilder.create_bull_put_spread(
                    underlying="^NSEI",
                    spot_price=nifty_spot,
                    sell_strike=sell_k,
                    buy_strike=buy_k,
                    expiry_days=dte,
                    volatility=iv,
                    lot_size=DEFAULT_LOT_SIZE,
                    quantity=total_quantity,
                    agent_id="CREDIT_SPREAD",
                    snapshot_id=snapshot_id,
                )
            except ValueError as val_err:
                return [
                    self.create_no_trade_proposal(
                        reason=f"Bull Put Spread validation error: {val_err}",
                        snapshot_id=snapshot_id,
                        confidence=60.0,
                    )
                ]

            sell_leg = next(leg for leg in strategy.legs if leg.side.value == "SELL")
            buy_leg = next(leg for leg in strategy.legs if leg.side.value == "BUY")

            # Exact Terminal Format Logging
            exec_log = self.format_execution_log(
                strategy_name="Bull Put",
                sell_strike=sell_leg.instrument.strike,
                sell_type="PE",
                sell_ltp=sell_leg.entry_price,
                buy_strike=buy_leg.instrument.strike,
                buy_type="PE",
                buy_ltp=buy_leg.entry_price,
                net_credit=strategy.net_credit,
                max_profit=strategy.max_profit,
                max_risk=strategy.max_loss,
            )
            logger.info(exec_log)
            print(exec_log, file=sys.stdout, flush=True)

            inst = Instrument(
                underlying="^NSEI",
                instrument_type=InstrumentType.OPTION,
                expiry=f"{dte}D",
                strike=sell_leg.instrument.strike,
                option_type=OptionType.PE,
                contract_name=f"NIFTY-BULL-PUT-{int(sell_k)}-{int(buy_k)}",
                lot_size=DEFAULT_LOT_SIZE,
            )

            proposal = ProposedTrade(
                agent_id="CREDIT_SPREAD",
                strategy_version=self.profile.strategy_version,
                symbol="^NSEI",
                action=TradeAction.BUY,
                instrument=inst,
                direction=TradeDirection.BUY,
                entry_price=round(strategy.net_debit, 2),
                stop_loss=round(strategy.stop_loss_amount, 2),
                target=round(strategy.target_profit_amount, 2),
                confidence=78.0,
                expected_move_pct=1.5,
                planned_risk_amount=strategy.max_loss,
                hedge_decision=HedgeDecision.YES,
                decision_reason=exec_log,
                snapshot_id=snapshot_id,
                sequence=1,
                strategy=strategy,
                thesis=f"Bull Put Spread deployed on {market_view} view. {view_reason}. Delta -0.25 sell leg at {sell_k}.",
                evidence=[view_reason, f"India VIX: {vix:.1f}", f"Spread width: {spread_width} pts"],
                horizon=f"{dte}D",
                expected_return=round(strategy.max_profit / strategy.net_debit * 100.0, 2),
                position_side=PositionSide.LONG,
                order_action=TradeAction.BUY,
                order_intent=OrderIntent.OPEN,
            )
            return [proposal]

        return [
            self.create_no_trade_proposal(
                reason=f"Unrecognized market view: {market_view}",
                snapshot_id=snapshot_id,
                confidence=50.0,
            )
        ]
