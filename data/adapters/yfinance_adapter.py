# =============================================================================
# data/adapters/yfinance_adapter.py — Yahoo Finance Adapter (Free, Simulated Live)
# =============================================================================
"""
Free alternative to Kite/Shoonya for testing the pipeline.
No API keys required. Note that Indian market data on Yahoo is usually delayed by 15 mins.

Simulates the WebSocket by polling Yahoo Finance in a background thread.
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf
from data.adapters.base import BrokerAdapter

logger = logging.getLogger(__name__)

# Map internal intervals to yfinance intervals
_INTERVAL_MAP = {
    "minute": "1m",
    "3minute": "2m", # yfinance doesn't have 3m, fallback to 2m or 5m
    "5minute": "5m",
    "15minute": "15m",
    "30minute": "30m",
    "60minute": "60m",
}


class YFinanceAdapter(BrokerAdapter):

    def __init__(self):
        self._tick_store: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._ws_running = False
        self._polling_thread: Optional[threading.Thread] = None

    def _resolve_symbol(self, symbol: str) -> str:
        """Map Indian symbols to Yahoo Finance format (e.g. RELIANCE.NS)"""
        if not symbol.endswith(".NS") and not symbol.endswith(".BO"):
            return f"{symbol}.NS"
        return symbol

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_ltp(self, symbol: str) -> float:
        yf_sym = self._resolve_symbol(symbol)
        ticker = yf.Ticker(yf_sym)
        # Fast way to get latest price
        info = ticker.fast_info
        try:
            return info.last_price
        except Exception:
            # Fallback to history
            hist = ticker.history(period="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
            return 0.0

    def get_historical_candles(
        self, symbol: str, interval: str, lookback_days: int = 5
    ) -> list[dict]:
        yf_sym = self._resolve_symbol(symbol)
        yf_interval = _INTERVAL_MAP.get(interval, "1m")
        
        # Yahoo only allows 1m data for the last 7 days
        if yf_interval == "1m" and lookback_days > 7:
            lookback_days = 7

        period = f"{lookback_days}d"
        
        # Suppress yfinance logging
        yf.logger.setLevel(logging.ERROR)
        
        df = yf.download(yf_sym, period=period, interval=yf_interval, progress=False)
        
        if df.empty:
            logger.warning("Empty historical response for %s", symbol)
            return []

        # Flatten multi-index columns if present (yfinance >= 0.2.0)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        candles = []
        for index, row in df.iterrows():
            candles.append({
                "date": index.to_pydatetime() if hasattr(index, "to_pydatetime") else index,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })
            
        return candles

    # ── WebSocket (Simulated via Polling) ─────────────────────────────────────

    def start_ticker(self, symbols: list[str]) -> None:
        self._ws_running = True
        logger.info("YFinanceAdapter: Starting simulated ticker for %s", symbols)
        
        def _poll_loop():
            yf_symbols = [self._resolve_symbol(s) for s in symbols]
            # Download string like "RELIANCE.NS HDFCBANK.NS"
            tickers_str = " ".join(yf_symbols)
            
            while self._ws_running:
                try:
                    df = yf.download(tickers_str, period="1d", interval="1m", progress=False)
                    if not df.empty:
                        with self._lock:
                            for sym in symbols:
                                yf_sym = self._resolve_symbol(sym)
                                
                                # Handle single vs multi-ticker dataframe
                                if len(symbols) == 1:
                                    close_col = "Close"
                                    vol_col = "Volume"
                                else:
                                    close_col = ("Close", yf_sym)
                                    vol_col = ("Volume", yf_sym)
                                    
                                if close_col in df:
                                    # Get the last non-NaN row
                                    series = df[close_col].dropna()
                                    vol_series = df[vol_col].dropna() if vol_col in df else None
                                    
                                    if not series.empty:
                                        last_price = float(series.iloc[-1])
                                        volume = int(vol_series.iloc[-1]) if vol_series is not None and not vol_series.empty else 0
                                        
                                        self._tick_store[sym] = {
                                            "instrument_token": sym,
                                            "last_price": last_price,
                                            "volume_traded": volume,
                                            "symbol": sym,
                                            "raw": {},
                                        }
                except Exception as e:
                    logger.error("YFinance poll error: %s", e)
                
                # Poll every 5 seconds to simulate live feed
                time.sleep(5)

        self._polling_thread = threading.Thread(target=_poll_loop, daemon=True)
        self._polling_thread.start()

    def stop_ticker(self) -> None:
        self._ws_running = False
        logger.info("YFinanceAdapter: Ticker stopped")

    def get_latest_tick(self, symbol: str) -> Optional[dict]:
        with self._lock:
            return self._tick_store.get(symbol)

    # ── Account ───────────────────────────────────────────────────────────────

    def get_profile(self) -> dict:
        return {
            "user_id": "FREE_TIER",
            "user_name": "YFinance User",
            "email": "none@yahoo.com",
            "broker": "Yahoo Finance (Simulated)"
        }

    def get_margins(self) -> dict:
        return {"net": 1000000.0, "available": 1000000.0}

import pandas as pd
