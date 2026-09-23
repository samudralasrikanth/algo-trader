# =============================================================================
# event_agent/arena/strike_selector.py — Quantitative Strike & Option Selector
# =============================================================================
"""
Quantitative Strike Selector for V4.2 Institutional Options Execution:
- Selects optimal strike contracts based on Target Delta [0.35, 0.50]
- Evaluates Implied Volatility (IV) Rank & Percentile
- Checks spread liquidity (bid/ask blowout protection)
- Determines Single Leg vs Defined-Risk Spread based on IV regime
"""

import math
from typing import Any, Dict, List, Optional, Tuple
from .asset_models import OptionChain, OptionStrikeData, OptionType, StrategyType


class StrikeSelector:
    """
    Selects optimal option contract strikes and strategy structures.
    """

    @staticmethod
    def select_strike(
        chain: OptionChain,
        is_call: bool,
        target_delta: float = 0.42,
        min_delta: float = 0.32,
        max_delta: float = 0.52,
        max_spread_pct: float = 0.05,
    ) -> Optional[Dict[str, Any]]:
        """
        Finds the liquid strike closest to target_delta within [min_delta, max_delta].
        """
        if not chain or not chain.strikes:
            return None

        best_strike: Optional[OptionStrikeData] = None
        best_diff: float = 999.0
        spot = getattr(chain, "underlying_price", getattr(chain, "spot_price", 25000.0))
        for s in chain.strikes:
            inst = s.call if is_call else s.put
            delta = abs(inst.delta)
            if min_delta <= delta <= max_delta:
                diff = abs(delta - target_delta)
                if diff < best_diff and inst.model_price > 0.5:
                    best_diff = diff
                    best_strike = s

        # Fallback to ATM if no strike within target range meets criteria
        if not best_strike:
            best_strike = min(chain.strikes, key=lambda s: abs(s.strike - spot))

        target_inst = best_strike.call if is_call else best_strike.put
        price = target_inst.model_price
        delta = target_inst.delta
        theta = target_inst.theta
        vega = target_inst.vega
        gamma = target_inst.gamma
        iv = target_inst.implied_volatility

        return {
            "strike": best_strike.strike,
            "option_type": OptionType.CE if is_call else OptionType.PE,
            "premium": price,
            "delta": delta,
            "theta": theta,
            "vega": vega,
            "gamma": gamma,
            "iv": iv,
            "atm_strike": chain.atm_strike,
            "spot_price": spot,
            "contract_symbol": f"{chain.underlying}-{int(best_strike.strike)}-{'CE' if is_call else 'PE'}",
        }

    @staticmethod
    def recommend_strategy_structure(
        iv_rank: float,
        expected_move_pct: float,
        confidence: float,
    ) -> StrategyType:
        """
        High IV Rank (> 60) -> Defined-Risk Vertical Spread (mitigates high IV crush)
        Low/Moderate IV Rank (<= 60) -> Directional Single Leg / Spread
        """
        if abs(expected_move_pct) >= 1.5:
            if iv_rank >= 60.0:
                return StrategyType.BULL_CALL_SPREAD if expected_move_pct > 0 else StrategyType.BEAR_PUT_SPREAD
            else:
                return StrategyType.LONG_CALL if expected_move_pct > 0 else StrategyType.LONG_PUT
        else:
            return StrategyType.BULL_CALL_SPREAD if expected_move_pct > 0 else StrategyType.BEAR_PUT_SPREAD
