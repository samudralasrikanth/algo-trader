# =============================================================================
# event_agent/adapters/market_data_adapter.py — Market Data Provider
# =============================================================================
"""
Abstracted market data provider with swappable backend.
Current implementation: yfinance.
Can be replaced with licensed NSE feed without changing prediction engine.

Instruments tracked:
    - India: Nifty 50, India VIX, 10 stock universe
    - US: S&P 500, Nasdaq, Dow, US 10Y
    - Commodities: WTI, Brent, Gold
    - FX: USD/INR
    - FII/DII: Scraped from public NSDL provisional data
"""

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from .base_adapter import BaseAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Market instruments registry
# ---------------------------------------------------------------------------
MARKET_INSTRUMENTS: Dict[str, Dict[str, Any]] = {
    # India indices
    "^NSEI":       {"name": "Nifty 50",              "type": "index",     "country": "IN", "currency": "INR"},
    "^INDIAVIX":   {"name": "India VIX",             "type": "volatility","country": "IN", "currency": "INR"},
    # US indices
    "^GSPC":       {"name": "S&P 500",               "type": "index",     "country": "US", "currency": "USD"},
    "^IXIC":       {"name": "Nasdaq Composite",      "type": "index",     "country": "US", "currency": "USD"},
    "^DJI":        {"name": "Dow Jones Industrial",  "type": "index",     "country": "US", "currency": "USD"},
    "^TNX":        {"name": "US 10-Year Yield",      "type": "yield",     "country": "US", "currency": "USD"},
    # Commodities
    "CL=F":        {"name": "WTI Crude Futures",     "type": "commodity", "country": "US", "currency": "USD"},
    "BZ=F":        {"name": "Brent Crude Futures",   "type": "commodity", "country": "US", "currency": "USD"},
    "GC=F":        {"name": "Gold Futures",          "type": "commodity", "country": "US", "currency": "USD"},
    # FX
    "USDINR=X":    {"name": "USD/INR",               "type": "fx",        "country": "IN", "currency": "INR"},
}


class MarketDataProvider(ABC):
    """
    Abstract market data provider.
    Swappable — can replace yfinance with licensed NSE feed later.
    """

    @abstractmethod
    def get_ohlcv(
        self,
        symbol: str,
        period: str = "1mo",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch OHLCV data for a symbol."""
        ...

    @abstractmethod
    def get_intraday(
        self,
        symbol: str,
        target_date: date,
        interval: str = "5m",
    ) -> pd.DataFrame:
        """Fetch intraday candles for execution simulation."""
        ...

    @abstractmethod
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get the latest available price."""
        ...

    @abstractmethod
    def get_provider_info(self) -> Dict[str, str]:
        """Return provider name and version for execution snapshots."""
        ...

    def create_execution_snapshot(
        self,
        symbol: str,
        interval: str,
        data: pd.DataFrame,
        requested_at: str,
    ) -> Dict[str, Any]:
        """
        Create an execution_data_snapshot for reproducibility.
        Records exactly what market data the broker used.
        """
        provider = self.get_provider_info()
        data_hash = ""
        if not data.empty:
            csv_bytes = data.to_csv(index=True).encode("utf-8")
            data_hash = f"sha256:{hashlib.sha256(csv_bytes).hexdigest()[:16]}"

        return {
            "provider": provider.get("name", "unknown"),
            "provider_version": provider.get("version", "unknown"),
            "symbol": symbol,
            "interval": interval,
            "requested_at": requested_at,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "market_data_start": str(data.index[0]) if not data.empty else None,
            "market_data_end": str(data.index[-1]) if not data.empty else None,
            "row_count": len(data),
            "data_hash": data_hash,
            "timezone": "Asia/Kolkata",
        }


class YFinanceProvider(MarketDataProvider):
    """
    yfinance-backed market data provider.
    Prototype implementation — to be swapped for licensed feed later.
    """

    def __init__(self):
        try:
            import yfinance as yf
            self._yf = yf
            self._available = True
            self._version = getattr(yf, "__version__", "unknown")
        except ImportError:
            logger.error("yfinance not installed. Market data adapter unavailable.")
            self._available = False
            self._version = "not_installed"

    def get_provider_info(self) -> Dict[str, str]:
        return {"name": "yfinance", "version": self._version}

    def get_ohlcv(
        self,
        symbol: str,
        period: str = "1mo",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch OHLCV data via yfinance."""
        if not self._available:
            return pd.DataFrame()
        try:
            ticker = self._yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            if df.empty:
                logger.warning("No data returned for %s (period=%s)", symbol, period)
            return df
        except Exception as exc:
            logger.error("yfinance get_ohlcv(%s) failed: %s", symbol, exc)
            return pd.DataFrame()

    def get_intraday(
        self,
        symbol: str,
        target_date: date,
        interval: str = "5m",
    ) -> pd.DataFrame:
        """
        Fetch intraday candles for a specific date.
        yfinance requires period='1d' or start/end for intraday.
        Note: yfinance 5m data is available for last ~60 days only.
        """
        if not self._available:
            return pd.DataFrame()
        try:
            start = target_date
            end = target_date + timedelta(days=1)
            ticker = self._yf.Ticker(symbol)
            df = ticker.history(start=start, end=end, interval=interval)
            if df.empty:
                logger.warning(
                    "No intraday data for %s on %s (interval=%s). "
                    "yfinance 5m data may not be available beyond ~60 days.",
                    symbol, target_date, interval,
                )
            return df
        except Exception as exc:
            logger.error("yfinance get_intraday(%s, %s) failed: %s", symbol, target_date, exc)
            return pd.DataFrame()

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get the latest closing price."""
        if not self._available:
            return None
        try:
            ticker = self._yf.Ticker(symbol)
            hist = ticker.history(period="1d")
            if hist.empty:
                return None
            return round(float(hist["Close"].iloc[-1]), 2)
        except Exception as exc:
            logger.error("yfinance get_current_price(%s) failed: %s", symbol, exc)
            return None

    def get_multiple_prices(
        self,
        symbols: List[str],
    ) -> Dict[str, Optional[float]]:
        """Get current prices for multiple symbols."""
        results = {}
        for sym in symbols:
            results[sym] = self.get_current_price(sym)
        return results

    def get_market_snapshot(self) -> Dict[str, Any]:
        """
        Get a comprehensive market snapshot for all tracked instruments.
        Returns prices and daily changes.
        """
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instruments": {},
        }

        for symbol, meta in MARKET_INSTRUMENTS.items():
            try:
                df = self.get_ohlcv(symbol, period="5d", interval="1d")
                if df.empty or len(df) < 2:
                    snapshot["instruments"][symbol] = {
                        "name": meta["name"],
                        "price": None,
                        "change_pct": None,
                        "error": "insufficient_data",
                    }
                    continue

                current = float(df["Close"].iloc[-1])
                previous = float(df["Close"].iloc[-2])
                change_pct = round(((current - previous) / previous) * 100, 3)

                snapshot["instruments"][symbol] = {
                    "name": meta["name"],
                    "type": meta["type"],
                    "price": round(current, 2),
                    "previous_close": round(previous, 2),
                    "change_pct": change_pct,
                    "date": str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else str(df.index[-1]),
                }
            except Exception as exc:
                logger.error("Market snapshot %s failed: %s", symbol, exc)
                snapshot["instruments"][symbol] = {
                    "name": meta["name"],
                    "price": None,
                    "error": str(exc),
                }

        return snapshot

    @staticmethod
    def list_instruments() -> Dict[str, Dict[str, Any]]:
        """Return all tracked market instruments."""
        return dict(MARKET_INSTRUMENTS)
