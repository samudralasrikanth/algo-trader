# =============================================================================
# event_agent/execution/capital_allocator.py — Independent Capital Allocator
# =============================================================================
"""
NEXUS V4.0 Independent Capital Allocator:
- Strictly separates alpha prediction from capital sizing.
- AI models provide ONLY direction, probability, conviction, and strategy.
- Risk engine determines approval and maximum risk budget.
- CapitalAllocator determines rupee exposure, lot sizing, and drawdown haircuts.
- Enforces strict environment limits and prohibits automatic escalation without human authorization.
"""

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .environment import EnvironmentManager, TradingEnvironment

logger = logging.getLogger(__name__)


@dataclass
class CapitalAllocationPlan:
    is_approved: bool
    allocated_capital_inr: float
    allocated_quantity: int
    entry_price: float
    stop_loss_price: float
    max_loss_inr: float
    risk_pct_of_capital: float
    drawdown_haircut_pct: float
    environment: str
    rejection_reason: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CapitalAllocator:
    """
    Independent capital allocation engine enforcing risk-budgeted position sizing.
    """

    DEFAULT_RISK_PER_TRADE_PCT = 0.005  # 0.5% risk per trade
    DEFAULT_MAX_POSITION_ALLOC_PCT = 0.10  # 10% max allocation per single position
    DEFAULT_MAX_PORTFOLIO_EXPOSURE_PCT = 0.50  # 50% max portfolio exposure

    def __init__(
        self,
        risk_per_trade_pct: float = DEFAULT_RISK_PER_TRADE_PCT,
        max_position_alloc_pct: float = DEFAULT_MAX_POSITION_ALLOC_PCT,
        max_portfolio_exposure_pct: float = DEFAULT_MAX_PORTFOLIO_EXPOSURE_PCT,
    ):
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_position_alloc_pct = max_position_alloc_pct
        self.max_portfolio_exposure_pct = max_portfolio_exposure_pct

    def allocate(
        self,
        symbol: str,
        entry_price: float,
        stop_loss_price: float,
        conviction: float,  # 0.0 to 1.0 (or 0 to 100)
        portfolio_capital: float,
        current_drawdown_pct: float = 0.0,
        current_portfolio_exposure: float = 0.0,
        active_symbol_exposure: float = 0.0,
        environment: Optional[TradingEnvironment] = None,
        requested_capital_from_ai: Optional[float] = None,
    ) -> CapitalAllocationPlan:
        """
        Calculates mathematical capital allocation and share count.
        Rejects any direct capital dictate from AI models.
        """
        env = environment or EnvironmentManager.get_configured_environment()

        # Invariant 10: AI must never directly dictate unrestricted capital
        if requested_capital_from_ai is not None and requested_capital_from_ai > 0:
            logger.warning("AI attempted to request direct capital. Ignoring AI requested amount.")

        if entry_price <= 0 or stop_loss_price <= 0:
            return self._reject("Invalid entry price or stop loss price (must be positive).", env)

        price_risk = abs(entry_price - stop_loss_price)
        if price_risk <= 0:
            return self._reject("Stop loss price cannot be identical to entry price.", env)

        # 1. Base Capital Pool bounded by Environment ceiling
        effective_capital = min(portfolio_capital, env.max_capital_cap)
        if effective_capital <= 0:
            return self._reject(f"Available capital is zero for environment {env.value}.", env)

        # 2. Drawdown Haircut (Reduces position sizes when in drawdown)
        # E.g. at 5% drawdown, haircut is 25%; at 10% drawdown, haircut is 75%
        haircut_pct = 0.0
        if current_drawdown_pct > 2.0:
            haircut_pct = min(0.80, (current_drawdown_pct - 2.0) * 0.10)
        usable_capital = effective_capital * (1.0 - haircut_pct)

        # 3. Maximum Allowed Allocation per Position
        max_alloc_inr = usable_capital * self.max_position_alloc_pct
        if env == TradingEnvironment.MICRO_LIVE:
            max_alloc_inr = min(max_alloc_inr, 5_000.0)  # Strict ₹5,000 cap in Micro-Live!

        # 4. Check Portfolio & Instrument Capacity
        avail_portfolio_capacity = (usable_capital * self.max_portfolio_exposure_pct) - current_portfolio_exposure
        avail_symbol_capacity = max_alloc_inr - active_symbol_exposure

        if avail_portfolio_capacity <= 0:
            return self._reject("Portfolio exposure capacity exhausted.", env)
        if avail_symbol_capacity <= 0:
            return self._reject(f"Symbol {symbol} exposure capacity exhausted.", env)

        # 5. Risk-Budget Sizing: (Capital * 0.5% risk) / (Entry - Stop)
        # Scaled slightly by conviction (between 0.60x and 1.0x)
        conviction_factor = min(1.0, max(0.60, float(conviction) / 100.0 if conviction > 1.0 else float(conviction)))
        max_risk_budget_inr = usable_capital * self.risk_per_trade_pct * conviction_factor

        shares_by_risk = math.floor(max_risk_budget_inr / price_risk)
        shares_by_capital = math.floor(min(max_alloc_inr, avail_portfolio_capacity, avail_symbol_capacity) / entry_price)

        final_quantity = max(0, min(shares_by_risk, shares_by_capital))

        # In Micro-Live, allow at least 1 share if risk is acceptable
        if final_quantity == 0 and env == TradingEnvironment.MICRO_LIVE:
            if price_risk <= (max_risk_budget_inr * 1.5) and entry_price <= max_alloc_inr:
                final_quantity = 1

        if final_quantity <= 0:
            return self._reject(
                f"Calculated quantity is 0 (price risk ₹{price_risk:.2f} too large for risk budget ₹{max_risk_budget_inr:.2f}).",
                env,
            )

        allocated_capital = final_quantity * entry_price
        actual_risk_inr = final_quantity * price_risk

        return CapitalAllocationPlan(
            is_approved=True,
            allocated_capital_inr=allocated_capital,
            allocated_quantity=final_quantity,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            max_loss_inr=actual_risk_inr,
            risk_pct_of_capital=(actual_risk_inr / usable_capital) * 100.0,
            drawdown_haircut_pct=haircut_pct * 100.0,
            environment=env.value,
        )

    def _reject(self, reason: str, env: TradingEnvironment) -> CapitalAllocationPlan:
        logger.warning(f"Capital allocation rejected: {reason}")
        return CapitalAllocationPlan(
            is_approved=False,
            allocated_capital_inr=0.0,
            allocated_quantity=0,
            entry_price=0.0,
            stop_loss_price=0.0,
            max_loss_inr=0.0,
            risk_pct_of_capital=0.0,
            drawdown_haircut_pct=0.0,
            environment=env.value,
            rejection_reason=reason,
        )
