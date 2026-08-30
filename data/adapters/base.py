# =============================================================================
# data/adapters/base.py — Abstract Broker Adapter Interface
# =============================================================================
"""
Every broker adapter must implement this interface.
The rest of the system only ever calls these methods — never broker-specific code.
"""

from abc import ABC, abstractmethod
from typing import Optional


class BrokerAdapter(ABC):

    # ── Market data ──────────────────────────────────────────────────────────

    @abstractmethod
    def get_ltp(self, symbol: str) -> float:
        """Return last traded price for a symbol."""

    @abstractmethod
    def get_historical_candles(
        self,
        symbol: str,
        interval: str,
        lookback_days: int = 5,
    ) -> list[dict]:
        """
        Return OHLCV candles as a list of dicts with keys:
            date (datetime), open, high, low, close, volume
        """

    # ── WebSocket / live feed ────────────────────────────────────────────────

    @abstractmethod
    def start_ticker(self, symbols: list[str]) -> None:
        """Start live tick streaming for a list of symbols."""

    @abstractmethod
    def stop_ticker(self) -> None:
        """Stop the live tick stream."""

    @abstractmethod
    def get_latest_tick(self, symbol: str) -> Optional[dict]:
        """Return the latest tick dict for a symbol, or None."""

    # ── Account info ─────────────────────────────────────────────────────────

    @abstractmethod
    def get_profile(self) -> dict:
        """Return user profile dict with at least: user_id, user_name, email."""

    @abstractmethod
    def get_margins(self) -> dict:
        """Return margin dict with at least: net, available."""
