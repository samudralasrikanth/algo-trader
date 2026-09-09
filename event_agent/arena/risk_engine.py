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
            can_trade, clock_reason = MarketClock.can_accept_new_orders()
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
