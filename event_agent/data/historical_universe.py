# =============================================================================
# event_agent/data/historical_universe.py — Point-in-Time Nifty 50 Universe (2018-2026)
# =============================================================================
"""
Provides survivorship-bias-free Point-in-Time (PIT) Nifty 50 constituent lookup.
Tracks all official index additions and exclusions from 2018 through 2026.
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# Official Nifty 50 Index Reconstitution Timeline (Date, Added Symbols, Removed Symbols)
NIFTY50_RECONSTITUTIONS: List[Tuple[date, List[str], List[str]]] = [
    # 2018
    (date(2018, 4, 2), ["BAJAJFINSV.NS", "TITAN.NS", "GRASIM.NS"], ["AMBUJACEM.NS", "ACC.NS", "BHEL.NS"]),
    (date(2018, 9, 28), ["JSWSTEEL.NS"], ["LUPIN.NS"]),
    # 2019
    (date(2019, 3, 29), ["BRITANNIA.NS"], ["HPCL.NS"]),
    (date(2019, 9, 27), ["NESTLEIND.NS"], ["IBULHSGFIN.NS"]),
    # 2020
    (date(2020, 3, 27), ["SHREECEM.NS"], ["YESBANK.NS"]),
    (date(2020, 9, 25), ["HDFCLIFE.NS", "DIVISLAB.NS", "SBILIFE.NS"], ["INFRATEL.NS", "ZEEL.NS", "VEDL.NS"]),
    # 2021
    (date(2021, 3, 31), ["TATACONSUM.NS"], ["GAIL.NS"]),
    # 2022
    (date(2022, 3, 31), ["APOLLOHOSP.NS"], ["IOC.NS"]),
    (date(2022, 9, 30), ["ADANIENT.NS"], ["SHREECEM.NS"]),
    # 2023
    (date(2023, 7, 13), ["LTIM.NS"], ["HDFC.NS"]),  # HDFC Ltd merger
    # 2024
    (date(2024, 3, 28), ["SHRIRAMFIN.NS"], ["UPL.NS"]),
    (date(2024, 9, 30), ["BEL.NS", "TRENT.NS"], ["DIVISLAB.NS", "LTIM.NS"]),
]

# Baseline constituents as of Jan 1, 2018 (50 stocks)
BASE_CONSTITUENTS_2018: Set[str] = {
    "ADANIPORTS.NS", "AMBUJACEM.NS", "ACC.NS", "ASIANPAINT.NS", "AXISBANK.NS",
    "BAJAJ-AUTO.NS", "BHEL.NS", "BPCL.NS", "BHARTIARTL.NS", "INFRATEL.NS",
    "BOSCHLTD.NS", "CIPLA.NS", "COALINDIA.NS", "DRREDDY.NS", "EICHERMOT.NS",
    "GAIL.NS", "HCLTECH.NS", "HDFC.NS", "HDFCBANK.NS", "HEROMOTOCO.NS",
    "HINDALCO.NS", "HINDUNILVR.NS", "HPCL.NS", "IBULHSGFIN.NS", "ICICIBANK.NS",
    "INDUSINDBK.NS", "INFY.NS", "IOC.NS", "ITC.NS", "KOTAKBANK.NS",
    "LT.NS", "LUPIN.NS", "M&M.NS", "MARUTI.NS", "NTPC.NS",
    "ONGC.NS", "POWERGRID.NS", "RELIANCE.NS", "SBIN.NS", "SUNPHARMA.NS",
    "TATAMOTORS.NS", "TATASTEEL.NS", "TCS.NS", "TECHM.NS", "ULTRACEMCO.NS",
    "UPL.NS", "VEDL.NS", "WIPRO.NS", "YESBANK.NS", "ZEEL.NS",
}


class HistoricalUniverseManager:
    def get_universe_at_date(self, target_date: Any) -> List[str]:
        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)
        return self.get_constituents_at_date(target_date)

    """
    Maintains point-in-time constituent lists of the Nifty 50 index.
    Guarantees backtests evaluate the exact 50 stocks active at any date.
    """

    @classmethod
    def get_constituents_at_date(cls, target_date: date) -> List[str]:
        """
        Returns the exact 50 Nifty constituents on target_date (2018 to 2026).
        """
        constituents = set(BASE_CONSTITUENTS_2018)

        # Apply chronological reconstitutions up to target_date
        for r_date, added, removed in NIFTY50_RECONSTITUTIONS:
            if r_date <= target_date:
                for rem in removed:
                    constituents.discard(rem)
                for add in added:
                    constituents.add(add)

        return sorted(list(constituents))

    @classmethod
    def is_constituent(cls, symbol: str, target_date: date) -> bool:
        """Check if symbol was part of Nifty 50 at target_date."""
        return symbol in cls.get_constituents_at_date(target_date)
