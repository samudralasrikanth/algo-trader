# =============================================================================
# event_agent/arena/option_chain_provider.py — Options Chain Provider with Governance
# =============================================================================
"""
Options Chain Provider for V4.2 Institutional Multi-Asset Intelligence.
Strictly governs option market data modes:
- LIVE: Verified live exchange/broker option chain. Options may trade.
- MODELLED: Analytical Black-Scholes pricing. Permitted for PAPER RESEARCH ONLY.
- UNAVAILABLE: No option data available or data stale (>60s). Strictly NO OPTIONS TRADE.
"""

import os
import time
import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .asset_models import OptionChain, OptionStrikeData, OptionType
from .options_engine import OptionsPricingEngine

logger = logging.getLogger(__name__)


class OptionDataMode(str, Enum):
    LIVE = "LIVE"
    MODELLED = "MODELLED"
    UNAVAILABLE = "UNAVAILABLE"


class OptionChainProvider:
    """
    Central provider for options chain data with explicit operational mode governance.
    """

    def __init__(self, default_mode: Optional[OptionDataMode] = None):
        env_mode = os.getenv("OPTION_DATA_MODE", "").upper()
        if env_mode in ("LIVE", "MODELLED", "UNAVAILABLE"):
            self._mode = OptionDataMode(env_mode)
        elif default_mode is not None:
            self._mode = default_mode
        else:
            # Check if live broker credentials exist, otherwise default to MODELLED for paper research or UNAVAILABLE
            has_upstox = bool(os.getenv("UPSTOX_API_KEY") and os.getenv("UPSTOX_ACCESS_TOKEN"))
            if has_upstox:
                self._mode = OptionDataMode.LIVE
            elif os.getenv("ALLOW_MODELLED_OPTIONS", "1") == "1":
                self._mode = OptionDataMode.MODELLED
            else:
                self._mode = OptionDataMode.UNAVAILABLE

        self._last_fetch_timestamp: float = 0.0
        self._cache: Dict[str, Tuple[OptionChain, float]] = {}

    @property
    def current_mode(self) -> OptionDataMode:
        return self._mode

    def set_mode(self, mode: OptionDataMode) -> None:
        self._mode = mode
        logger.info(f"OptionDataMode set to {mode.value}")

    def is_stale(self, max_age_seconds: float = 60.0) -> bool:
        """Returns True if the last fetched option data is older than max_age_seconds."""
        if self._last_fetch_timestamp <= 0:
            return True
        return (time.time() - self._last_fetch_timestamp) > max_age_seconds

    def can_trade_options(self, execution_environment: str = "PAPER") -> bool:
        """
        Runtime TradeGuard Invariant:
        - LIVE: OPTIONS MAY TRADE
        - MODELLED: PAPER RESEARCH ONLY
        - UNAVAILABLE: NO OPTIONS TRADE
        """
        if self._mode == OptionDataMode.LIVE:
            return not self.is_stale(60.0)
        elif self._mode == OptionDataMode.MODELLED:
            return execution_environment.upper() in ("PAPER", "PAPER_RESEARCH", "BACKTEST")
        else:  # UNAVAILABLE
            return False

    def get_chain(
        self,
        underlying: str,
        spot_price: float,
        expiry: Optional[str] = None,
        days_to_expiry: int = 7,
        implied_volatility: float = 0.16,
    ) -> Tuple[Optional[OptionChain], OptionDataMode]:
        """
        Fetches or models the option chain.
        Returns (OptionChain, OptionDataMode).
        """
        if self._mode == OptionDataMode.UNAVAILABLE:
            logger.warning(f"Option data UNAVAILABLE for {underlying}. Cannot trade options.")
            return None, OptionDataMode.UNAVAILABLE

        now = time.time()
        # Check cache (15-second TTL)
        cache_key = f"{underlying}:{round(spot_price, 1)}:{days_to_expiry}"
        if cache_key in self._cache:
            chain, cached_time = self._cache[cache_key]
            if (now - cached_time) < 15.0:
                return chain, self._mode

        if self._mode == OptionDataMode.LIVE:
            # If live feed hook is configured, attempt fetch
            live_chain = self._fetch_live_chain(underlying, spot_price, expiry)
            if live_chain:
                self._last_fetch_timestamp = now
                self._cache[cache_key] = (live_chain, now)
                return live_chain, OptionDataMode.LIVE
            else:
                logger.warning(f"Live options feed failed for {underlying}. Falling back to UNAVAILABLE.")
                return None, OptionDataMode.UNAVAILABLE

        # MODELLED mode (Analytical Black-Scholes for Paper Research Only)
        modelled_chain = self._build_modelled_chain(
            underlying=underlying,
            spot_price=spot_price,
            expiry=expiry or "NEAR",
            days_to_expiry=days_to_expiry,
            iv=implied_volatility,
        )
        self._last_fetch_timestamp = now
        self._cache[cache_key] = (modelled_chain, now)
        return modelled_chain, OptionDataMode.MODELLED

    def _fetch_live_chain(
        self,
        underlying: str,
        spot_price: float,
        expiry: Optional[str] = None,
    ) -> Optional[OptionChain]:
        """Hook for connecting live broker / NSE market data provider."""
        # When live Upstox or NSE API is plugged in, parse raw option chain
        return None

    def _build_modelled_chain(
        self,
        underlying: str,
        spot_price: float,
        expiry: str,
        days_to_expiry: int,
        iv: float,
    ) -> OptionChain:
        """Constructs an analytical Black-Scholes chain around ATM +/- 6 strikes."""
        step = 50.0 if spot_price > 1000 else (20.0 if spot_price > 500 else 10.0)
        atm_strike = round(spot_price / step) * step
        t_years = max(0.001, days_to_expiry / 365.0)

        from .asset_models import OptionInstrument

        strikes_data: List[OptionStrikeData] = []
        for offset in range(-6, 7):
            k = atm_strike + (offset * step)
            if k <= 0:
                continue

            call_res = OptionsPricingEngine.calculate_price_and_greeks(
                spot=spot_price, strike=k, time_to_expiry_years=t_years, volatility=iv, is_call=True
            )
            put_res = OptionsPricingEngine.calculate_price_and_greeks(
                spot=spot_price, strike=k, time_to_expiry_years=t_years, volatility=iv, is_call=False
            )

            call_inst = OptionInstrument(
                underlying=underlying,
                strike=k,
                option_type=OptionType.CE,
                expiry=expiry,
                model_price=call_res["price"],
                implied_volatility=iv,
                delta=call_res["delta"],
                gamma=call_res["gamma"],
                theta=call_res["theta"],
                vega=call_res["vega"],
            )
            put_inst = OptionInstrument(
                underlying=underlying,
                strike=k,
                option_type=OptionType.PE,
                expiry=expiry,
                model_price=put_res["price"],
                implied_volatility=iv,
                delta=put_res["delta"],
                gamma=put_res["gamma"],
                theta=put_res["theta"],
                vega=put_res["vega"],
            )

            strikes_data.append(
                OptionStrikeData(
                    strike=k,
                    call=call_inst,
                    put=put_inst,
                    is_atm=(offset == 0),
                )
            )

        return OptionChain(
            underlying=underlying,
            underlying_price=spot_price,
            atm_strike=atm_strike,
            expiry=expiry,
            strikes=strikes_data,
            implied_volatility_pct=iv * 100.0,
            price_source="MODELLED_BLACK_SCHOLES",
        )
