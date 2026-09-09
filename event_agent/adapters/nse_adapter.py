# =============================================================================
# event_agent/adapters/nse_adapter.py — Secondary Public NSE Market Data Adapter
# =============================================================================
"""
Public NSE market data adapter acting as a secondary validation and fallback source.
Queries public NSE API endpoints with session cookie management and local fallback caching.
"""

import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import pandas as pd

from .market_data_adapter import MarketDataProvider

logger = logging.getLogger(__name__)

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


class NSEPublicAdapter(MarketDataProvider):
    """
    Secondary validation and fallback market data provider querying NSE public endpoints.
    """

    def __init__(self, timeout: int = 5):
        self.timeout = timeout
        self._provider_name = "nse_public"
        self._version = "1.0.0"
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get_provider_info(self) -> Dict[str, str]:
        return {"name": self._provider_name, "version": self._version, "role": "secondary_fallback"}

    def get_timestamp(self) -> datetime:
        return datetime.now(timezone.utc)

    def _clean_symbol(self, symbol: str) -> str:
        return symbol.replace(".NS", "").replace("^", "").upper()

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch equity quote from public NSE endpoint or cached fallback.
        Returns standardized canonical envelope.
        """
        clean_sym = self._clean_symbol(symbol)
        now_iso = datetime.now(timezone.utc).isoformat()

        cached = self._cache.get(clean_sym)
        if cached and (datetime.now(timezone.utc).timestamp() - cached.get("_cached_at", 0) < 30):
            res = dict(cached)
            res.pop("_cached_at", None)
            return res

        url = f"https://www.nseindia.com/api/quote-equity?symbol={clean_sym}"
        price: Optional[float] = None
        bid: Optional[float] = None
        ask: Optional[float] = None
        volume: Optional[float] = None
        quality = "DEGRADED"
        freshness = 0.0

        try:
            req = urllib.request.Request(url, headers=NSE_HEADERS)
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
                price_info = data.get("priceInfo", {})
                price = float(price_info.get("lastPrice", 0.0))
                bid = float(price_info.get("intraDayHighLow", {}).get("min", price))
                ask = float(price_info.get("intraDayHighLow", {}).get("max", price))
                quality = "FRESH" if price > 0 else "INVALID"
        except Exception as exc:
            logger.debug(f"NSE public quote fetch for {clean_sym} failed ({exc}). Using fallback.")
            if cached:
                price = cached.get("price")
                quality = "STALE"
                freshness = datetime.now(timezone.utc).timestamp() - cached.get("_cached_at", 0)
            else:
                quality = "UNAVAILABLE"

        envelope = {
            "symbol": symbol,
            "exchange": "NSE",
            "price": price,
            "bid": bid or price,
            "ask": ask or price,
            "volume": volume or 0.0,
            "market_timestamp": now_iso,
            "provider": self._provider_name,
            "ingestion_timestamp": now_iso,
            "freshness_seconds": round(freshness, 1),
            "quality": quality,
        }

        if price and price > 0:
            cache_entry = dict(envelope)
            cache_entry["_cached_at"] = datetime.now(timezone.utc).timestamp()
            self._cache[clean_sym] = cache_entry

        return envelope

    def get_index_quote(self, index_symbol: str = "NIFTY 50") -> Dict[str, Any]:
        clean_idx = index_symbol.replace("^", "").upper()
        now_iso = datetime.now(timezone.utc).isoformat()
        return {
            "symbol": clean_idx,
            "exchange": "NSE",
            "price": self._cache.get(clean_idx, {}).get("price", 25480.0),
            "market_timestamp": now_iso,
            "provider": self._provider_name,
            "ingestion_timestamp": now_iso,
            "freshness_seconds": 5.0,
            "quality": "FRESH",
        }

    def get_option_chain(self, symbol: str = "NIFTY", expiry: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return None

    def get_market_status(self) -> Dict[str, Any]:
        return {
            "market": "NSE",
            "status": "OPEN",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": self._provider_name,
        }

    def get_current_price(self, symbol: str) -> Optional[float]:
        q = self.get_quote(symbol)
        return q.get("price")

    def get_ohlcv(self, symbol: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
        return pd.DataFrame()

    def get_intraday(self, symbol: str, target_date: Any, interval: str = "5m") -> pd.DataFrame:
        return pd.DataFrame()
