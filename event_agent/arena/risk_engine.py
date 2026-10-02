# =============================================================================
# event_agent/arena/risk_engine.py — Central Risk Gate & Exposure Engine
# =============================================================================
"""
Central Risk Engine enforcing V3.2 Research Risk Parameters:
- 0.5% risk-based position sizing per trade
- 20% single position capital allocation cap
- 50% max portfolio exposure limit
- 25% max sector/correlated exposure limit
- 60% minimum calibrated conviction hurdle
- 1.5% daily loss limit circuit breaker
- 20% drawdown warning, 30% drawdown trading suspension
- 15:30 IST strict cutoff via MarketClock
- First-class NO_TRADE acknowledgement
- Hedge validation
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..config import (
    DAILY_LOSS_LIMIT_PCT,
    DRAWDOWN_SUSPEND_PCT,
    DRAWDOWN_WARNING_PCT,
    MAX_ACTIVE_POSITIONS_PER_AGENT,
    MAX_CORRELATED_EXPOSURE_PCT,
    MAX_PORTFOLIO_EXPOSURE_PCT,
    MAX_RISK_PER_TRADE_PCT,
    MAX_SINGLE_POSITION_ALLOCATION_PCT,
    MIN_CONFIDENCE_PCT,
    NIFTY50_UNIVERSE,
)
from .market_clock import MarketClock, MarketPhase
from .asset_models import MultiLegStrategy, LegSide, StrategyStatus, StrategyType
from .models import (
    HedgeDecision,
    InstrumentType,
    ProposedTrade,
    RiskEvaluation,
    TradeAction,
    TradeDirection,
)

logger = logging.getLogger(__name__)


class RiskEngine:
    """
    Independent risk gate through which all agent proposals must pass
    before reaching the Paper Broker.
    """

    def __init__(
        self,
        risk_per_trade_pct: float = MAX_RISK_PER_TRADE_PCT,
        max_single_alloc_pct: float = MAX_SINGLE_POSITION_ALLOCATION_PCT,
        max_portfolio_exposure_pct: float = MAX_PORTFOLIO_EXPOSURE_PCT,
        max_sector_exposure_pct: float = MAX_CORRELATED_EXPOSURE_PCT,
        min_confidence_pct: float = MIN_CONFIDENCE_PCT,
        daily_loss_limit_pct: float = DAILY_LOSS_LIMIT_PCT,
        drawdown_suspend_pct: float = DRAWDOWN_SUSPEND_PCT,
    ):
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_single_alloc_pct = max_single_alloc_pct
        self.max_portfolio_exposure_pct = max_portfolio_exposure_pct
        self.max_sector_exposure_pct = max_sector_exposure_pct
        self.min_confidence_pct = min_confidence_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.drawdown_suspend_pct = drawdown_suspend_pct

    def evaluate_proposal(
        self,
        proposal: ProposedTrade,
        agent_equity: float,
        agent_cash: float,
        current_open_positions: List[Dict[str, Any]],
        daily_starting_equity: float,
        check_market_clock: bool = True,
        current_time: Optional[datetime] = None,
    ) -> RiskEvaluation:
        """
        Evaluate a single agent proposed trade against all risk invariants.
        """
        checks_passed: List[str] = []

        # 1. NO_TRADE and HOLD handling (Zero risk consumption)
        if proposal.action in (TradeAction.NO_TRADE, TradeAction.HOLD):
            return RiskEvaluation(
                is_approved=True,
                rejection_reason=f"{proposal.action.value}_ACCEPTED",
                adjusted_quantity=0,
                max_loss=0.0,
                risk_reward_ratio=0.0,
                checks_passed=["NO_RISK_ACTION"],
            )

        # 2. Market Clock Gating (Strict 15:30 Cutoff)
        if check_market_clock:
            can_trade, clock_reason = MarketClock.can_accept_new_orders(current_time)
            if not can_trade:
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason=f"MARKET_CLOCK_REJECT: {clock_reason}",
                    checks_passed=checks_passed,
                )
            checks_passed.append("MARKET_CLOCK_ACTIVE")

        # 3. Drawdown Suspension Circuit Breaker (30%)
        # Note: Avoid division by zero
        drawdown_pct = 0.0
        if daily_starting_equity > 0 and agent_equity < daily_starting_equity:
            drawdown_pct = ((daily_starting_equity - agent_equity) / daily_starting_equity) * 100.0
        if drawdown_pct >= self.drawdown_suspend_pct:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason=f"CIRCUIT_BREAKER_SUSPEND: Agent drawdown ({drawdown_pct:.1f}%) exceeds limit ({self.drawdown_suspend_pct}%)",
                checks_passed=checks_passed,
            )
        checks_passed.append("DRAWDOWN_WITHIN_LIMIT")

        # 4. Daily Loss Limit Circuit Breaker (1.5%)
        daily_loss_pct = 0.0
        if daily_starting_equity > 0:
            daily_loss = daily_starting_equity - agent_equity
            daily_loss_pct = max(0.0, (daily_loss / daily_starting_equity) * 100.0)
        if daily_loss_pct >= self.daily_loss_limit_pct:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason=f"CIRCUIT_BREAKER_DAILY_LOSS: Daily loss ({daily_loss_pct:.2f}%) exceeds limit ({self.daily_loss_limit_pct}%)",
                checks_passed=checks_passed,
            )
        checks_passed.append("DAILY_LOSS_WITHIN_LIMIT")

        # 5. Minimum Calibrated Confidence Hurdle (60%)
        if proposal.confidence < self.min_confidence_pct:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason=f"LOW_CONFIDENCE: Conviction {proposal.confidence:.1f}% below minimum {self.min_confidence_pct}%",
                checks_passed=checks_passed,
            )
        checks_passed.append("CONFIDENCE_SUFFICIENT")

        # 6. Stop Loss Requirement & Distance Verification
        entry = proposal.entry_price
        stop = proposal.stop_loss
        target = proposal.target

        if entry <= 0:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason="INVALID_ENTRY_PRICE: Entry price must be > 0",
                checks_passed=checks_passed,
            )

        if stop <= 0:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason="MISSING_STOP_LOSS: Every directional trade must have a positive stop loss",
                checks_passed=checks_passed,
            )

        stop_distance = abs(entry - stop)
        if stop_distance <= 0:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason="INVALID_STOP_DISTANCE: Stop loss cannot equal entry price",
                checks_passed=checks_passed,
            )

        # Directional alignment of stop
        if proposal.direction == TradeDirection.BUY and stop >= entry:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason="INVALID_STOP_ALIGNMENT: BUY stop loss must be below entry price",
                checks_passed=checks_passed,
            )
        elif proposal.direction == TradeDirection.SELL and stop <= entry:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason="INVALID_STOP_ALIGNMENT: SELL stop loss must be above entry price",
                checks_passed=checks_passed,
            )
        checks_passed.append("STOP_LOSS_VALID")

        # 7. Maximum Active Allocations (0–10 Positions)
        # Count existing positions for this agent excluding this symbol if it's an update
        existing_symbols = {p.get("symbol") for p in current_open_positions if p.get("status", "OPEN") == "OPEN"}
        if proposal.symbol not in existing_symbols and len(existing_symbols) >= MAX_ACTIVE_POSITIONS_PER_AGENT:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason=f"MAX_POSITIONS_REACHED: Agent already has {len(existing_symbols)} active allocations (limit: {MAX_ACTIVE_POSITIONS_PER_AGENT})",
                checks_passed=checks_passed,
            )
        checks_passed.append("POSITION_COUNT_WITHIN_LIMIT")

        # 8. Sizing Calculation: Exactly 0.5% Capital Risk per Trade
        risk_capital = agent_equity * (self.risk_per_trade_pct / 100.0)
        raw_quantity = int(risk_capital / stop_distance)

        # Single position capital cap (20%)
        max_single_capital = agent_equity * (self.max_single_alloc_pct / 100.0)
        if raw_quantity * entry > max_single_capital:
            raw_quantity = int(max_single_capital / entry)

        # Cash check
        if raw_quantity * entry > agent_cash:
            raw_quantity = int(agent_cash / entry)

        if raw_quantity <= 0:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason="INSUFFICIENT_CAPITAL_FOR_SIZE: Risk sizing resulted in 0 shares",
                checks_passed=checks_passed,
            )
        checks_passed.append("RISK_SIZING_CALCULATED")

        # 9. Portfolio Exposure Limit (50%)
        current_exposure = sum(
            float(p.get("entry_price", 0.0)) * int(p.get("quantity", 0))
            for p in current_open_positions if p.get("status", "OPEN") == "OPEN"
        )
        trade_capital = raw_quantity * entry
        projected_exposure = current_exposure + trade_capital
        max_exposure = agent_equity * (self.max_portfolio_exposure_pct / 100.0)

        if projected_exposure > max_exposure:
            # Try to scale down quantity to fit within exposure limit
            remaining_cap = max(0.0, max_exposure - current_exposure)
            scaled_quantity = int(remaining_cap / entry)
            if scaled_quantity <= 0:
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason=f"PORTFOLIO_EXPOSURE_LIMIT: Total exposure ({projected_exposure:,.0f}) exceeds 50% limit ({max_exposure:,.0f})",
                    checks_passed=checks_passed,
                )
            raw_quantity = scaled_quantity
        checks_passed.append("PORTFOLIO_EXPOSURE_WITHIN_LIMIT")

        # 10. Sector Correlation Ceiling (25%)
        symbol_info = NIFTY50_UNIVERSE.get(proposal.symbol, {})
        sector = symbol_info.get("sector", "Other")
        current_sector_exposure = sum(
            float(p.get("entry_price", 0.0)) * int(p.get("quantity", 0))
            for p in current_open_positions
            if p.get("status", "OPEN") == "OPEN" and NIFTY50_UNIVERSE.get(p.get("symbol", ""), {}).get("sector") == sector
        )
        projected_sector_exposure = current_sector_exposure + (raw_quantity * entry)
        max_sector_cap = agent_equity * (self.max_sector_exposure_pct / 100.0)

        if projected_sector_exposure > max_sector_cap:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason=f"SECTOR_CORRELATION_LIMIT: Sector '{sector}' exposure ({projected_sector_exposure:,.0f}) exceeds 25% limit ({max_sector_cap:,.0f})",
                checks_passed=checks_passed,
            )
        checks_passed.append("SECTOR_EXPOSURE_WITHIN_LIMIT")

        # 11. Optional Hedge Validation
        if proposal.hedge_decision == HedgeDecision.YES:
            if not proposal.hedge_instrument:
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason="INVALID_HEDGE_SPEC: Hedge specified as YES but no hedge instrument provided",
                    checks_passed=checks_passed,
                )
            checks_passed.append("HEDGE_VALIDATED")

        # Compute max loss & risk-reward
        target_distance = abs(target - entry)
        rr_ratio = round(target_distance / stop_distance, 2) if stop_distance > 0 else 1.0
        max_loss = round(raw_quantity * stop_distance, 2)

        return RiskEvaluation(
            is_approved=True,
            rejection_reason="APPROVED",
            adjusted_quantity=raw_quantity,
            max_loss=max_loss,
            risk_reward_ratio=rr_ratio,
            checks_passed=checks_passed,
        )

    def evaluate_strategy(
        self,
        strategy: MultiLegStrategy,
        agent_equity: float,
        agent_cash: float,
        current_open_strategies: List[MultiLegStrategy],
        daily_starting_equity: float,
        check_market_clock: bool = True,
        current_time: Optional[datetime] = None,
    ) -> RiskEvaluation:
        """
        Evaluate a multi-leg options strategy against risk limits:
        1. Market clock (15:30 IST cutoff)
        2. Drawdown circuit breaker (30%)
        3. Daily loss limit (1.5%)
        4. Max strategy loss (0.5% capital cap = ₹10,000)
        5. Cash sufficiency for net debit
        6. Liquidity checks on each option leg
        7. Net Delta exposure limit
        8. Active options strategy count (max 3 concurrent per agent)
        """
        checks_passed: List[str] = []

        # 1. Market Clock verification
        if check_market_clock:
            can_trade, clock_reason = MarketClock.can_accept_new_orders(current_time)
            if not can_trade:
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason=f"MARKET_CLOCK_REJECT: {clock_reason}",
                    checks_passed=checks_passed,
                )
            checks_passed.append("MARKET_CLOCK_ACTIVE")

        # 2. Drawdown Circuit Breaker
        drawdown_pct = 0.0
        if daily_starting_equity > 0 and agent_equity < daily_starting_equity:
            drawdown_pct = ((daily_starting_equity - agent_equity) / daily_starting_equity) * 100.0
        if drawdown_pct >= self.drawdown_suspend_pct:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason=f"CIRCUIT_BREAKER_SUSPEND: Drawdown ({drawdown_pct:.1f}%) exceeds limit",
                checks_passed=checks_passed,
            )
        checks_passed.append("DRAWDOWN_WITHIN_LIMIT")

        # 3. Daily Loss Limit
        daily_loss_pct = 0.0
        if daily_starting_equity > 0:
            daily_loss = daily_starting_equity - agent_equity
            daily_loss_pct = max(0.0, (daily_loss / daily_starting_equity) * 100.0)
        if daily_loss_pct >= self.daily_loss_limit_pct:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason=f"CIRCUIT_BREAKER_DAILY_LOSS: Daily loss ({daily_loss_pct:.2f}%) exceeds 1.5% limit",
                checks_passed=checks_passed,
            )
        checks_passed.append("DAILY_LOSS_WITHIN_LIMIT")

        # 4. Active options strategies limit (max 3 per agent)
        active_strats = [s for s in current_open_strategies if s.status == StrategyStatus.OPEN]
        existing_unds = {s.underlying for s in active_strats}
        if strategy.underlying in existing_unds:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason=f"STRATEGY_ALREADY_OPEN: Agent already has an active options strategy on {strategy.underlying}",
                checks_passed=checks_passed,
            )
        if len(active_strats) >= 3:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason=f"MAX_OPTIONS_STRATEGIES_REACHED: Agent already has {len(active_strats)} active options strategies (limit: 3)",
                checks_passed=checks_passed,
            )
        checks_passed.append("OPTIONS_COUNT_WITHIN_LIMIT")

        # 4b. Institutional Credit Spread & DTE Gating
        if strategy.agent_id == "CREDIT_SPREAD" or strategy.strategy_type in (StrategyType.BULL_PUT_SPREAD, StrategyType.BEAR_CALL_SPREAD):
            # DTE Gate: 3 to 7 DTE weekly expiries, strictly prohibit 0 DTE
            try:
                dte = int("".join(c for c in strategy.expiry if c.isdigit()) or "7")
            except Exception:
                dte = 7
            if dte == 0:
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason="DTE_GATE_REJECT: 0 DTE / Expiry Day trades prohibited to prevent gamma spikes",
                    checks_passed=checks_passed,
                )
            if dte < 3 or dte > 7:
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason=f"DTE_GATE_REJECT: DTE ({dte}D) outside approved 3-7 DTE weekly window",
                    checks_passed=checks_passed,
                )
            checks_passed.append("DTE_WINDOW_APPROVED")

            # Naked Option Writing Prevention: Short leg MUST be paired with protective long leg
            sell_legs = [leg for leg in strategy.legs if leg.side == LegSide.SELL]
            buy_legs = [leg for leg in strategy.legs if leg.side == LegSide.BUY]
            if not sell_legs or not buy_legs:
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason="NAKED_OPTION_PROHIBITED: Every short leg must be paired with a protective long leg",
                    checks_passed=checks_passed,
                )
            if sell_legs[0].instrument.option_type != buy_legs[0].instrument.option_type:
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason="INVALID_SPREAD_STRUCTURE: Credit spread legs must share the same option type",
                    checks_passed=checks_passed,
                )
            checks_passed.append("HEDGED_PROTECTION_VERIFIED")

            # Net Credit Verification
            if getattr(strategy, "net_credit", 0.0) <= 0:
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason="NEGATIVE_NET_CREDIT: Credit spread must produce positive net credit",
                    checks_passed=checks_passed,
                )
            checks_passed.append("NET_CREDIT_VERIFIED")

            # Lot size gate: Max 2 lots
            total_sell_qty = sum(leg.quantity for leg in sell_legs)
            lot_size = strategy.legs[0].instrument.lot_size if strategy.legs else 50
            if total_sell_qty > 2 * lot_size:
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason=f"MAX_LOT_SIZE_EXCEEDED: Quantity {total_sell_qty} exceeds 2-lot ceiling ({2 * lot_size})",
                    checks_passed=checks_passed,
                )
            checks_passed.append("LOT_SIZE_WITHIN_LIMIT")

        # 5. Maximum Strategy Loss Limit (₹2,400 cap for CREDIT_SPREAD; 0.5% risk capital on others)
        if strategy.agent_id == "CREDIT_SPREAD":
            max_allowed_risk = 2400.0  # 2% of ₹1,20,000 capital
            if strategy.max_loss > max_allowed_risk or strategy.stop_loss_amount > max_allowed_risk:
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason=f"STRATEGY_MAX_LOSS_EXCEEDED: Defined max loss ₹{strategy.max_loss:,.2f} exceeds ₹{max_allowed_risk:,.2f} (2% capital cap)",
                    checks_passed=checks_passed,
                )
            checks_passed.append("STRATEGY_MAX_LOSS_APPROVED")
        else:
            max_allowed_risk = agent_equity * (self.risk_per_trade_pct / 100.0)
            if strategy.max_loss > max_allowed_risk * 1.5:  # Allow 1.5x tolerance for predefined spreads (e.g. ₹15,000)
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason=f"STRATEGY_MAX_LOSS_EXCEEDED: Defined max loss ₹{strategy.max_loss:,.2f} exceeds risk cap ₹{max_allowed_risk * 1.5:,.2f}",
                    checks_passed=checks_passed,
                )
            checks_passed.append("STRATEGY_MAX_LOSS_APPROVED")

        # 6. Cash Sufficiency for Net Debit
        if strategy.net_debit > agent_cash:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason=f"INSUFFICIENT_CASH_FOR_DEBIT: Requires ₹{strategy.net_debit:,.2f}, has ₹{agent_cash:,.2f}",
                checks_passed=checks_passed,
            )
        checks_passed.append("CASH_SUFFICIENT_FOR_DEBIT")

        # 7. Liquidity Check for each Option Leg
        for leg in strategy.legs:
            inst = leg.instrument
            if inst.bid <= 0 or inst.ask <= 0:
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason=f"INSUFFICIENT_LIQUIDITY: Leg {inst.symbol} lacks valid bid/ask quotes",
                    checks_passed=checks_passed,
                )
            spread = inst.ask - inst.bid
            mid = (inst.ask + inst.bid) / 2.0
            if mid > 1.0 and (spread / mid) > 0.15:  # Max 15% bid-ask spread width
                return RiskEvaluation(
                    is_approved=False,
                    rejection_reason=f"EXCESSIVE_SPREAD_WIDTH: Leg {inst.symbol} spread width ({spread/mid*100:.1f}%) exceeds 15%",
                    checks_passed=checks_passed,
                )
        checks_passed.append("OPTIONS_LIQUIDITY_VERIFIED")

        # 8. Net Delta Exposure Limit (25% for equity-sized options, 1.5x for defined-risk index spreads)
        delta_exposure = abs(strategy.net_delta) * strategy.entry_underlying_price
        if strategy.agent_id == "CREDIT_SPREAD" or strategy.strategy_type in (StrategyType.BULL_PUT_SPREAD, StrategyType.BEAR_CALL_SPREAD):
            max_delta_cap = agent_equity * 1.5
        else:
            max_delta_cap = agent_equity * 0.25
        if delta_exposure > max_delta_cap:
            return RiskEvaluation(
                is_approved=False,
                rejection_reason=f"NET_DELTA_EXPOSURE_EXCEEDED: Delta exposure ₹{delta_exposure:,.2f} exceeds cap ₹{max_delta_cap:,.2f}",
                checks_passed=checks_passed,
            )
        checks_passed.append("NET_DELTA_WITHIN_LIMIT")

        return RiskEvaluation(
            is_approved=True,
            rejection_reason="APPROVED",
            adjusted_quantity=strategy.legs[0].quantity if strategy.legs else 50,
            max_loss=strategy.max_loss,
            risk_reward_ratio=strategy.risk_reward_ratio,
            checks_passed=checks_passed,
        )
