# =============================================================================
# strategy/options_straddle.py — Delta-Neutral Long Straddle
# =============================================================================
"""
Options Strategy: Intraday Long Straddle
Goal: Profit from high volatility (big moves in EITHER direction).
Risk: Limited to premium paid. (Theta decay hurts if market stays flat).

Logic:
1. At a specific time (e.g., 10:00 AM after morning chop, or before a news event).
2. Fetch the current Spot Price of the index (e.g., NIFTY 50).
3. Round to the nearest strike price (ATM - At The Money).
4. BUY 1 lot of ATM Call (CE).
5. BUY 1 lot of ATM Put (PE).
6. Exit: If combined premium increases by X% (Target) or drops by Y% (Stop Loss).

Note: This requires an options symbol builder based on your broker's format.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

@dataclass
class StraddleSignal:
    spot_symbol: str
    atm_strike: int
    ce_symbol: str
    pe_symbol: str
    action: str  # "ENTER", "EXIT", "HOLD"
    reason: str


class LongStraddleStrategy:
    
    def __init__(self, index_symbol: str, expiry_date: str, step: int = 50):
        """
        :param index_symbol: e.g. "NIFTY" or "BANKNIFTY"
        :param expiry_date:  e.g. "24MAY" (broker specific format)
        :param step:         e.g. 50 for NIFTY, 100 for BANKNIFTY
        """
        self.index_symbol = index_symbol
        self.expiry_date = expiry_date
        self.step = step
        self.is_active = False

    def _get_atm_strike(self, spot_price: float) -> int:
        """Rounds spot price to the nearest option strike."""
        return int(round(spot_price / self.step) * self.step)

    def _build_option_symbol(self, strike: int, option_type: str) -> str:
        """
        Builds the broker-specific symbol. 
        Example Shoonya/Kite format: NIFTY24MAY22000CE
        """
        return f"{self.index_symbol}{self.expiry_date}{strike}{option_type}"

    def analyze(self, current_spot_price: float, current_time) -> StraddleSignal:
        """
        Evaluates whether to enter or exit the straddle.
        """
        # ── 1. Entry Condition (e.g., exactly at 10:00 AM)
        if not self.is_active and current_time.hour == 10 and current_time.minute == 0:
            atm = self._get_atm_strike(current_spot_price)
            ce = self._build_option_symbol(atm, "CE")
            pe = self._build_option_symbol(atm, "PE")
            
            logger.info("STRADDLE ENTRY: Spot=%.2f, ATM=%d", current_spot_price, atm)
            self.is_active = True
            
            return StraddleSignal(
                spot_symbol=self.index_symbol,
                atm_strike=atm,
                ce_symbol=ce,
                pe_symbol=pe,
                action="ENTER",
                reason="Time-based volatility entry"
            )

        # ── 2. Exit Condition (e.g., at 3:15 PM to avoid physical settlement / margin)
        if self.is_active and current_time.hour == 15 and current_time.minute >= 15:
            self.is_active = False
            return StraddleSignal(
                spot_symbol=self.index_symbol,
                atm_strike=0, ce_symbol="", pe_symbol="",
                action="EXIT",
                reason="Intraday Square-off Time"
            )

        # ── 3. Hold
        return StraddleSignal(
            spot_symbol=self.index_symbol,
            atm_strike=0, ce_symbol="", pe_symbol="",
            action="HOLD",
            reason="Waiting for conditions"
        )
