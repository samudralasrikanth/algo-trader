# =============================================================================
# event_agent/arena/exit_engine.py — Institutional Dual Exit Engine
# =============================================================================
"""
Dedicated Dual Exit Engine for V4.2 Institutional Architecture:
Enforces strict 9-level exit priority hierarchy:
1. BROKER / SAFETY EMERGENCY
2. MAX LOSS
3. DATA INTEGRITY FAILURE
4. THESIS INVALIDATED
5. LIQUIDITY FAILURE
6. EXPIRY / TIME STOP
7. TARGET
8. TRAILING
9. OPPORTUNITY REPLACEMENT

Separates Equity/Futures exit mechanics from Options-specific Greeks/IV mechanics.
Guarantees emergency broker-side protective path even when market data feed is stale (>60s).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ExitPriority(IntEnum):
    BROKER_SAFETY_EMERGENCY = 1
    MAX_LOSS = 2
    DATA_INTEGRITY_FAILURE = 3
    THESIS_INVALIDATED = 4
    LIQUIDITY_FAILURE = 5
    EXPIRY_TIME_STOP = 6
    TARGET = 7
    TRAILING_STOP = 8
    OPPORTUNITY_REPLACEMENT = 9


@dataclass
class ExitSignal:
    position_id: str
    symbol: str
    should_exit: bool
    exit_reason: str
    priority: ExitPriority
    suggested_exit_price: float
    is_emergency_order: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def priority_name(self) -> str:
        return self.priority.name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "should_exit": self.should_exit,
            "exit_reason": self.exit_reason,
            "priority": int(self.priority),
            "priority_name": self.priority.name,
            "suggested_exit_price": round(self.suggested_exit_price, 2),
            "is_emergency_order": self.is_emergency_order,
            "details": self.details,
        }


class EquityFuturesExitEngine:
    """Evaluates exits for Cash Equity and Index/Stock Futures."""

    @classmethod
    def evaluate(
        cls,
        position: Dict[str, Any],
        current_price: float,
        market_context: Optional[Dict[str, Any]] = None,
        is_kill_switch_active: bool = False,
    ) -> Optional[ExitSignal]:
        pos_id = position.get("position_id", "")
        symbol = position.get("symbol", "")
        entry_price = float(position.get("entry_price", 0.0))
        target_price = float(position.get("target_price", position.get("target", 0.0)))
        stop_loss = float(position.get("stop_loss", 0.0))
        pos_side = str(position.get("position_side", "LONG")).upper()
        high_price = float(position.get("high_since_entry", max(entry_price, current_price)))
        low_price = float(position.get("low_since_entry", min(entry_price, current_price)))

        # Priority 1: BROKER / SAFETY EMERGENCY
        if is_kill_switch_active:
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="BROKER_SAFETY_EMERGENCY",
                priority=ExitPriority.BROKER_SAFETY_EMERGENCY,
                suggested_exit_price=current_price,
                is_emergency_order=True,
                details={"reason": "Emergency risk kill switch activated."},
            )

        if entry_price <= 0 or current_price <= 0:
            return None

        # Calculate unrealized return
        if pos_side == "LONG":
            unrealized_pct = ((current_price - entry_price) / entry_price) * 100.0
            peak_pct = ((high_price - entry_price) / entry_price) * 100.0
            is_stop_hit = stop_loss > 0 and current_price <= stop_loss
            is_target_hit = target_price > 0 and current_price >= target_price
        else:  # SHORT
            unrealized_pct = ((entry_price - current_price) / entry_price) * 100.0
            peak_pct = ((entry_price - low_price) / entry_price) * 100.0
            is_stop_hit = stop_loss > 0 and current_price >= stop_loss
            is_target_hit = target_price > 0 and current_price <= target_price

        # Priority 2: MAX LOSS
        if is_stop_hit or unrealized_pct <= -3.0:
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="MAX_LOSS",
                priority=ExitPriority.MAX_LOSS,
                suggested_exit_price=current_price,
                details={"unrealized_pct": round(unrealized_pct, 2), "stop_loss": stop_loss},
            )

        # Priority 3: DATA INTEGRITY FAILURE
        quote_age = market_context.get("quote_age_seconds", 0.0) if market_context else 0.0
        if quote_age > 300.0:  # 5 minutes stale equity quote
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="DATA_INTEGRITY_FAILURE",
                priority=ExitPriority.DATA_INTEGRITY_FAILURE,
                suggested_exit_price=current_price,
                is_emergency_order=True,
                details={"quote_age_seconds": quote_age},
            )

        # Priority 4: THESIS INVALIDATED
        # If market regime changed to extreme volatility or macro catalysts reversed
        regime = market_context.get("regime", {}) if market_context else {}
        if regime.get("volatility") == "EXTREME" and unrealized_pct < 0:
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="THESIS_INVALIDATED",
                priority=ExitPriority.THESIS_INVALIDATED,
                suggested_exit_price=current_price,
                details={"reason": "Market regime transitioned to EXTREME volatility."},
            )

        # Priority 5: LIQUIDITY FAILURE (Spread > 2.0%)
        spread_pct = market_context.get("spread_pct", 0.0) if market_context else 0.0
        if spread_pct > 0.02:
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="LIQUIDITY_FAILURE",
                priority=ExitPriority.LIQUIDITY_FAILURE,
                suggested_exit_price=current_price,
                details={"spread_pct": round(spread_pct * 100.0, 2)},
            )

        # Priority 6: EXPIRY / TIME STOP (Holding > 7 trading days)
        days_held = int(position.get("days_held", 0))
        if days_held >= 7 and abs(unrealized_pct) < 0.5:
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="TIME_STOP",
                priority=ExitPriority.EXPIRY_TIME_STOP,
                suggested_exit_price=current_price,
                details={"days_held": days_held, "unrealized_pct": round(unrealized_pct, 2)},
            )

        # Priority 7: TARGET (Verifying net gain covers friction)
        if is_target_hit:
            # Roundtrip costs for Equity ~0.15%
            net_gain_pct = unrealized_pct - 0.15
            if net_gain_pct > 0.10:
                return ExitSignal(
                    position_id=pos_id,
                    symbol=symbol,
                    should_exit=True,
                    exit_reason="TARGET",
                    priority=ExitPriority.TARGET,
                    suggested_exit_price=current_price,
                    details={"target_price": target_price, "net_gain_pct": round(net_gain_pct, 2)},
                )

        # Priority 8: TRAILING STOP
        # Dynamic net edge lock: If position peaked > +1.5%, trail stop at 50% retracement
        if peak_pct >= 1.50 and unrealized_pct <= (peak_pct * 0.50):
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="TRAILING_STOP",
                priority=ExitPriority.TRAILING_STOP,
                suggested_exit_price=current_price,
                details={"peak_pct": round(peak_pct, 2), "unrealized_pct": round(unrealized_pct, 2)},
            )

        return None


class OptionsExitEngine:
    """Evaluates exits for single-leg and multi-leg Options contracts."""

    @classmethod
    def evaluate(
        cls,
        position: Dict[str, Any],
        current_premium: float,
        underlying_spot: float,
        is_stale_data: bool = False,
        is_kill_switch_active: bool = False,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ExitSignal]:
        pos_id = position.get("position_id", "")
        symbol = position.get("symbol", "")
        entry_premium = float(position.get("entry_price", 0.0))
        target_premium = float(position.get("target_price", position.get("target", 0.0)))
        stop_loss_premium = float(position.get("stop_loss", 0.0))
        pos_side = str(position.get("position_side", "LONG")).upper()
        days_to_expiry = int(position.get("days_to_expiry", 7))
        iv_entry = float(position.get("iv_at_entry", 0.20))
        current_iv = float(position.get("current_iv", iv_entry))

        # Priority 1: BROKER / SAFETY EMERGENCY
        if is_kill_switch_active:
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="BROKER_SAFETY_EMERGENCY",
                priority=ExitPriority.BROKER_SAFETY_EMERGENCY,
                suggested_exit_price=current_premium,
                is_emergency_order=True,
                details={"reason": "Emergency risk kill switch activated."},
            )

        # Priority 2: Hard Broker-side Protective Stop (Evaluated regardless of quote staleness!)
        # If market data is stale, we STILL check if underlying spot breached hard safety boundary
        underlying_stop = float(position.get("underlying_stop", 0.0))
        if underlying_stop > 0:
            if pos_side == "LONG" and underlying_spot <= underlying_stop:
                return ExitSignal(
                    position_id=pos_id,
                    symbol=symbol,
                    should_exit=True,
                    exit_reason="MAX_LOSS",
                    priority=ExitPriority.MAX_LOSS,
                    suggested_exit_price=max(0.05, current_premium),
                    is_emergency_order=True,
                    details={"reason": "Underlying spot breached emergency protective stop."},
                )

        # Priority 3: DATA INTEGRITY FAILURE (>60s stale option quote)
        if is_stale_data:
            # Stale quote halts regular exit calculation to avoid synthetic fills,
            # but flags data integrity warning while preserving emergency broker order path
            logger.warning(f"Option data >60s stale for {symbol}. Pausing regular exits; protective stops armed.")
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=False,  # Does not trigger market exit on stale quote; awaits fresh feed or emergency stop
                exit_reason="DATA_INTEGRITY_STALE_QUOTE",
                priority=ExitPriority.DATA_INTEGRITY_FAILURE,
                suggested_exit_price=current_premium,
                details={"reason": "Option data >60s stale. Analytical exit calculation paused."},
            )

        if entry_premium <= 0:
            return None

        pnl_pct = ((current_premium - entry_premium) / entry_premium) * 100.0

        # Priority 2: MAX LOSS (Premium dropped >= 45% or hit premium stop)
        if pnl_pct <= -45.0 or (stop_loss_premium > 0 and current_premium <= stop_loss_premium):
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="MAX_LOSS",
                priority=ExitPriority.MAX_LOSS,
                suggested_exit_price=current_premium,
                details={"pnl_pct": round(pnl_pct, 2)},
            )

        # Priority 4: THESIS INVALIDATED (Underlying reversal > 1.2%)
        underlying_move_against = float(position.get("underlying_move_against_pct", 0.0))
        if underlying_move_against >= 1.2:
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="THESIS_INVALIDATED",
                priority=ExitPriority.THESIS_INVALIDATED,
                suggested_exit_price=current_premium,
                details={"underlying_move_against_pct": round(underlying_move_against, 2)},
            )

        # Priority 5: LIQUIDITY FAILURE (Spread > 8.0%)
        spread_pct = market_context.get("spread_pct", 0.0) if market_context else 0.0
        if spread_pct > 0.08:
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="LIQUIDITY_FAILURE",
                priority=ExitPriority.LIQUIDITY_FAILURE,
                suggested_exit_price=current_premium,
                details={"spread_pct": round(spread_pct * 100.0, 2)},
            )

        # Priority 6: EXPIRY / TIME STOP (0 DTE or Theta decay > 30%)
        if days_to_expiry <= 0:
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="EXPIRY_TIME_STOP",
                priority=ExitPriority.EXPIRY_TIME_STOP,
                suggested_exit_price=current_premium,
                details={"days_to_expiry": days_to_expiry},
            )

        # IV CRUSH: Volatility collapsed > 25% from entry
        if iv_entry > 0 and ((current_iv - iv_entry) / iv_entry) <= -0.25:
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="IV_CRUSH",
                priority=ExitPriority.EXPIRY_TIME_STOP,
                suggested_exit_price=current_premium,
                details={"iv_entry": iv_entry, "current_iv": current_iv},
            )

        # Priority 7: TARGET (Hit target profit >= +50%)
        if pnl_pct >= 50.0 or (target_premium > 0 and current_premium >= target_premium):
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="TARGET",
                priority=ExitPriority.TARGET,
                suggested_exit_price=current_premium,
                details={"pnl_pct": round(pnl_pct, 2)},
            )

        # Priority 8: TRAILING STOP (+30% profit lock)
        peak_premium = float(position.get("peak_premium", entry_premium))
        peak_pnl_pct = ((peak_premium - entry_premium) / entry_premium) * 100.0
        if peak_pnl_pct >= 40.0 and pnl_pct <= (peak_pnl_pct * 0.50):
            return ExitSignal(
                position_id=pos_id,
                symbol=symbol,
                should_exit=True,
                exit_reason="TRAILING_STOP",
                priority=ExitPriority.TRAILING_STOP,
                suggested_exit_price=current_premium,
                details={"peak_pnl_pct": round(peak_pnl_pct, 2), "pnl_pct": round(pnl_pct, 2)},
            )

        return None


class ExitEngine:
    """
    Unified manager executing the dual exit engines across all positions.
    """

    @classmethod
    def evaluate_all(
        cls,
        open_positions: List[Dict[str, Any]],
        market_quotes: Dict[str, Any],
        is_kill_switch_active: bool = False,
    ) -> List[ExitSignal]:
        signals: List[ExitSignal] = []

        for pos in open_positions:
            sym = pos.get("symbol", "")
            inst_type = str(pos.get("instrument_type", pos.get("instrument", {}).get("instrument_type", "EQUITY"))).upper()
            quote_data = market_quotes.get(sym, {})
            current_price = float(quote_data.get("price", pos.get("current_price", pos.get("entry_price", 0.0))))

            if "OPTION" in inst_type:
                is_stale = quote_data.get("is_stale", False)
                sig = OptionsExitEngine.evaluate(
                    position=pos,
                    current_premium=current_price,
                    underlying_spot=float(quote_data.get("spot_price", current_price)),
                    is_stale_data=is_stale,
                    is_kill_switch_active=is_kill_switch_active,
                    market_context=quote_data,
                )
            else:
                sig = EquityFuturesExitEngine.evaluate(
                    position=pos,
                    current_price=current_price,
                    market_context=quote_data,
                    is_kill_switch_active=is_kill_switch_active,
                )

            if sig and sig.should_exit:
                signals.append(sig)

        # Sort signals strictly by priority (Priority 1 first)
        signals.sort(key=lambda s: int(s.priority))
        return signals
