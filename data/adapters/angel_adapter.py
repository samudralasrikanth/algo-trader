# =============================================================================
# data/adapters/angel_adapter.py — Angel One SmartAPI Broker Adapter
# =============================================================================
"""
Official Angel One SmartAPI Adapter.
Uses the smartapi-python SDK and pyotp for automated session management.

Angel One Developer Portal: https://smartapi.angelone.in
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import pyotp
import requests

from data.adapters.base import BrokerAdapter

logger = logging.getLogger(__name__)

# Interval mapping from algo-trader intervals to Angel One API intervals
_INTERVAL_MAP = {
    "minute": "ONE_MINUTE",
    "3minute": "THREE_MINUTE",
    "5minute": "FIVE_MINUTE",
    "10minute": "TEN_MINUTE",
    "15minute": "FIFTEEN_MINUTE",
    "30minute": "THIRTY_MINUTE",
    "60minute": "ONE_HOUR",
    "day": "ONE_DAY",
}

# Known common Nifty 50 tokens on NSE Cash segment
_KNOWN_TOKENS = {
    "RELIANCE": "2885",
    "TCS": "11536",
    "HDFCBANK": "1333",
    "ICICIBANK": "4963",
    "INFY": "1594",
    "SBIN": "3045",
    "BHARTIARTL": "10604",
    "ITC": "1660",
    "KOTAKBANK": "1922",
    "LT": "11483",
    "AXISBANK": "5900",
}


class AngelAdapter(BrokerAdapter):
    """
    Angel One SmartAPI Broker Adapter.
    Automates login session generation using Client Code, MPIN, and TOTP Secret.
    """

    def __init__(
        self,
        api_key: str,
        client_code: str,
        pin: str,
        totp_secret: str,
    ):
        try:
            from SmartApi import SmartConnect
        except ImportError:
            raise ImportError("smartapi-python not installed. Run: pip install smartapi-python logzero")

        self.api_key = api_key
        self.client_code = client_code
        self.pin = pin
        self.totp_secret = totp_secret

        self._api = SmartConnect(api_key=self.api_key)
        self._auth_data: Dict[str, Any] = {}
        self._jwt_token = ""
        self._refresh_token = ""
        self._feed_token = ""

        self._sym_to_token: Dict[str, str] = dict(_KNOWN_TOKENS)
        self._token_to_sym: Dict[str, str] = {v: k for k, v in _KNOWN_TOKENS.items()}
        self._tick_store: Dict[str, dict] = {}
        self._lock = threading.Lock()

        # Connect on initialization if credentials present
        if all([self.api_key, self.client_code, self.pin, self.totp_secret]):
            self._login()
            threading.Thread(target=self._load_scrip_master, daemon=True).start()

    def _login(self) -> None:
        """Generate JWT auth token using Client Code, MPIN, and TOTP."""
        logger.info("Logging into Angel One SmartAPI for user %s...", self.client_code)
        totp = pyotp.TOTP(self.totp_secret).now()
        data = self._api.generateSession(self.client_code, self.pin, totp)

        if not data or not data.get("status"):
            msg = data.get("message", "Unknown error") if data else "No response"
            raise ConnectionError(f"Angel One SmartAPI login failed: {msg}")

        self._auth_data = data.get("data", {})
        self._jwt_token = self._auth_data.get("jwtToken", "")
        self._refresh_token = self._auth_data.get("refreshToken", "")
        self._feed_token = self._api.getfeedToken()
        logger.info("Angel One SmartAPI login successful! User: %s", self.client_code)

    def _load_scrip_master(self) -> None:
        """Download and cache the Angel One OpenAPIScripMaster instrument tokens."""
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                scrips = resp.json()
                for s in scrips:
                    if s.get("exch_seg") == "NSE" and s.get("symbol", "").endswith("-EQ"):
                        clean_sym = s["symbol"].replace("-EQ", "")
                        token = s.get("token")
                        if token and clean_sym:
                            self._sym_to_token[clean_sym] = token
                            self._token_to_sym[token] = clean_sym
                logger.info("Loaded %d NSE tokens from Angel One scrip master.", len(self._sym_to_token))
        except Exception as e:
            logger.warning("Could not download Angel One scrip master (%s). Using fallback tokens.", e)

    def _get_token(self, symbol: str) -> str:
        sym = symbol.upper().replace(".NS", "").replace("-EQ", "")
        token = self._sym_to_token.get(sym)
        if not token:
            raise KeyError(f"Angel One token not found for symbol: {symbol}")
        return token

    # ── Market Data ──────────────────────────────────────────────────────────

    def get_ltp(self, symbol: str) -> float:
        """Return last traded price for a symbol."""
        sym = symbol.upper().replace(".NS", "").replace("-EQ", "")
        token = self._get_token(sym)
        trading_symbol = f"{sym}-EQ"
        res = self._api.ltpData("NSE", trading_symbol, token)
        if res and res.get("status") and res.get("data"):
            return float(res["data"].get("ltp", 0.0))
        raise RuntimeError(f"Failed to fetch LTP for {symbol}: {res}")

    def get_historical_candles(
        self,
        symbol: str,
        interval: str,
        lookback_days: int = 5,
    ) -> List[dict]:
        """Return OHLCV candles as list of dicts."""
        token = self._get_token(symbol)
        angel_interval = _INTERVAL_MAP.get(interval, "ONE_MINUTE")

        now = datetime.now()
        from_date = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d 09:15")
        to_date = now.strftime("%Y-%m-%d 15:30")

        params = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": angel_interval,
            "fromdate": from_date,
            "todate": to_date,
        }

        res = self._api.getCandleData(params)
        if not res or not res.get("status") or not res.get("data"):
            return []

        candles = []
        for row in res["data"]:
            # Angel candle format: [timestamp_str, open, high, low, close, volume]
            dt = datetime.fromisoformat(row[0]) if "T" in row[0] else datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            candles.append({
                "date": dt,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": int(row[5]),
            })
        return candles

    # ── WebSocket / Live Feed ────────────────────────────────────────────────

    def start_ticker(self, symbols: List[str]) -> None:
        """Start streaming ticks (placeholder for WebSocket streamer)."""
        logger.info("Angel One ticker started for symbols: %s", symbols)

    def stop_ticker(self) -> None:
        logger.info("Angel One ticker stopped.")

    def get_latest_tick(self, symbol: str) -> Optional[dict]:
        sym = symbol.upper().replace(".NS", "").replace("-EQ", "")
        return self._tick_store.get(sym)

    # ── Account Info ─────────────────────────────────────────────────────────

    def get_profile(self) -> dict:
        """Return user profile."""
        res = self._api.getProfile(self._refresh_token)
        if res and res.get("status") and res.get("data"):
            d = res["data"]
            return {
                "user_id": d.get("clientcode", self.client_code),
                "user_name": d.get("name", ""),
                "email": d.get("email", ""),
            }
        return {"user_id": self.client_code, "user_name": "", "email": ""}

    def get_margins(self) -> dict:
        """Return margin limits."""
        res = self._api.rmsLimit()
        if res and res.get("status") and res.get("data"):
            d = res["data"]
            net = float(d.get("net", 0.0))
            avail = float(d.get("availablecash", net))
            return {"net": net, "available": avail}
        return {"net": 0.0, "available": 0.0}
