# =============================================================================
# event_agent/broker/cost_model.py — Indian Market Transaction Cost Model
# =============================================================================
"""
Accurate transaction cost modeling for Indian stock markets (NSE).
Features:
    - Separate entry and exit cost calculations
    - Granular side-specific rules (BUY vs SELL)
    - Schedule support for:
        1. equity_delivery (Cash positional / swing)
        2. equity_intraday (Day trading)
        3. index_futures (Nifty 50 Futures)
    - Real-world slippage estimation
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Standard statutory rates for Indian capital markets
COST_SCHEDULES: Dict[str, Dict[str, float]] = {
    "equity_delivery": {
        "brokerage_rate_buy": 0.0,            # Zero brokerage delivery
        "brokerage_rate_sell": 0.0,
        "brokerage_flat_cap": 0.0,
        "stt_buy": 0.001,                     # 0.1% on buy turnover
        "stt_sell": 0.001,                    # 0.1% on sell turnover
        "exchange_turnover_fee": 0.0000345,   # NSE cash 0.00345%
        "gst_rate": 0.18,                     # 18% on (brokerage + exchange charges)
        "stamp_duty_buy": 0.00015,            # 0.015% on buy
        "stamp_duty_sell": 0.0,               # Nil on sell
        "sebi_turnover_fee": 0.000001,        # ₹10 per crore (0.0001%)
    },
    "equity_intraday": {
        "brokerage_rate_buy": 0.0003,         # 0.03% or flat ₹20
        "brokerage_rate_sell": 0.0003,
        "brokerage_flat_cap": 20.0,
        "stt_buy": 0.0,                       # Nil on buy
        "stt_sell": 0.00025,                  # 0.025% on sell
        "exchange_turnover_fee": 0.0000345,
        "gst_rate": 0.18,
        "stamp_duty_buy": 0.00003,            # 0.003% on buy
        "stamp_duty_sell": 0.0,
        "sebi_turnover_fee": 0.000001,
    },
    "index_futures": {
        "brokerage_rate_buy": 0.0003,
        "brokerage_rate_sell": 0.0003,
        "brokerage_flat_cap": 20.0,
        "stt_buy": 0.0,
        "stt_sell": 0.000125,                 # 0.0125% on sell
        "exchange_turnover_fee": 0.000019,
        "gst_rate": 0.18,
        "stamp_duty_buy": 0.00002,            # 0.002% on buy
        "stamp_duty_sell": 0.0,
        "sebi_turnover_fee": 0.000001,
    },
}


class CostModel:
    """
    Computes all exchange, government, and broker fees for a trade.
    """

    def __init__(self, default_schedule: str = "equity_intraday"):
        self.default_schedule = default_schedule

    def calculate_entry_cost(
        self,
        instrument_type: str,
        side: str,
        price: float,
        quantity: int,
    ) -> Dict[str, float]:
        """
        Compute transaction cost at trade entry.
        """
        return self._compute_leg_cost(instrument_type, side.upper(), price, quantity, is_entry=True)

    def calculate_exit_cost(
        self,
        instrument_type: str,
        side: str,
        price: float,
        quantity: int,
    ) -> Dict[str, float]:
        """
        Compute transaction cost at trade exit.
        """
        return self._compute_leg_cost(instrument_type, side.upper(), price, quantity, is_entry=False)

    def _compute_leg_cost(
        self,
        instrument_type: str,
        action: str,  # "BUY" or "SELL"
        price: float,
        quantity: int,
        is_entry: bool,
    ) -> Dict[str, float]:
        sched = COST_SCHEDULES.get(instrument_type, COST_SCHEDULES[self.default_schedule])
        turnover = max(0.0, float(price) * int(quantity))
        if turnover <= 0:
            return {"total": 0.0, "brokerage": 0.0, "stt": 0.0, "exchange": 0.0, "gst": 0.0, "stamp_duty": 0.0, "sebi": 0.0}

        # 1. Brokerage
        if action == "BUY":
            raw_brok = turnover * sched.get("brokerage_rate_buy", 0.0)
        else:
            raw_brok = turnover * sched.get("brokerage_rate_sell", 0.0)
        cap = sched.get("brokerage_flat_cap", 0.0)
        brokerage = min(raw_brok, cap) if cap > 0 else raw_brok

        # 2. STT
        stt_rate = sched.get("stt_buy", 0.0) if action == "BUY" else sched.get("stt_sell", 0.0)
        stt = turnover * stt_rate

        # 3. Exchange turnover charges
        exch_rate = sched.get("exchange_turnover_fee", 0.0000345)
        exchange_charges = turnover * exch_rate

        # 4. GST (18% on Brokerage + Exchange)
        gst = (brokerage + exchange_charges) * sched.get("gst_rate", 0.18)

        # 5. Stamp duty (State levy, usually only on BUY)
        stamp_rate = sched.get("stamp_duty_buy", 0.0) if action == "BUY" else sched.get("stamp_duty_sell", 0.0)
        stamp_duty = turnover * stamp_rate

        # 6. SEBI turnover fee
        sebi = turnover * sched.get("sebi_turnover_fee", 0.000001)

        total = brokerage + stt + exchange_charges + gst + stamp_duty + sebi

        return {
            "turnover": round(turnover, 2),
            "brokerage": round(brokerage, 2),
            "stt": round(stt, 2),
            "exchange_charges": round(exchange_charges, 2),
            "gst": round(gst, 2),
            "stamp_duty": round(stamp_duty, 2),
            "sebi_fee": round(sebi, 2),
            "total": round(total, 2),
        }

    def estimate_slippage(
        self,
        price: float,
        quantity: int,
        side: str,
        bps: float = 3.0,
    ) -> float:
        """
        Estimate slippage cost in rupees based on basis points.
        Default: 3 bps for liquid Nifty 50 large-caps.
        """
        turnover = price * quantity
        slippage_rupees = turnover * (bps / 10000.0)
        return round(slippage_rupees, 2)

    def calculate_total_trade_costs(
        self,
        entry_price: float,
        exit_price: float,
        quantity: int,
        position_side: str = "LONG",  # LONG: Buy to open, Sell to close. SHORT: Sell to open, Buy to close.
        instrument_type: str = "equity_intraday",
        slippage_bps: float = 3.0,
    ) -> Dict[str, Any]:
        """
        Full round-trip transaction and friction cost analysis.
        """
        if position_side.upper() == "LONG":
            entry_action = "BUY"
            exit_action = "SELL"
        else:
            entry_action = "SELL"
            exit_action = "BUY"

        entry_costs = self.calculate_entry_cost(instrument_type, entry_action, entry_price, quantity)
        exit_costs = self.calculate_exit_cost(instrument_type, exit_action, exit_price, quantity)

        entry_slip = self.estimate_slippage(entry_price, quantity, entry_action, bps=slippage_bps)
        exit_slip = self.estimate_slippage(exit_price, quantity, exit_action, bps=slippage_bps)
        total_slippage = round(entry_slip + exit_slip, 2)

        statutory_costs = round(entry_costs["total"] + exit_costs["total"], 2)
        grand_total = round(statutory_costs + total_slippage, 2)

        total_turnover = entry_costs["turnover"] + exit_costs["turnover"]
        drag_pct = round((grand_total / total_turnover) * 100, 4) if total_turnover > 0 else 0.0

        return {
            "instrument_type": instrument_type,
            "position_side": position_side.upper(),
            "quantity": quantity,
            "entry_costs": entry_costs,
            "exit_costs": exit_costs,
            "statutory_costs": statutory_costs,
            "slippage_cost": total_slippage,
            "total_friction_cost": grand_total,
            "turnover": round(total_turnover, 2),
            "cost_drag_pct": drag_pct,
        }
