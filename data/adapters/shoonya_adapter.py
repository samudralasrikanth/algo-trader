# =============================================================================
# data/adapters/shoonya_adapter.py — Finvasia / Shoonya Broker Adapter
# =============================================================================
"""
Uses the official NorenRestApiPy client (free, open source).
Install: pip install NorenRestApiPy

Finvasia account: https://finvasia.com  (free account, free API)
API docs: https://github.com/Shoonya-Dev/ShoonyaApi-py

How Shoonya differs from Kite:
    - Uses numeric scrip tokens (e.g. NSE|22) not symbol names
    - Historical data via get_time_price_series() with epoch timestamps
    - WebSocket subscribe format: ['NSE|22', 'NSE|1594']
    - No separate API key/secret rotation — session token from login lasts the day
"""

import json
import logging
import hashlib
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional

import pyotp

from data.adapters.base import BrokerAdapter

logger = logging.getLogger(__name__)

# Shoonya interval map → their API string
_INTERVAL_MAP = {
    "minute":   "1",
    "3minute":  "3",
    "5minute":  "5",
    "10minute": "10",
    "15minute": "15",
    "30minute": "30",
    "60minute": "60",
}


class ShoonyaAdapter(BrokerAdapter):
    """
    Full Finvasia/Shoonya adapter.

    Args:
        user_id     : Your Finvasia client ID (e.g. FA12345)
        password    : Your login password
        totp_secret : Base32 TOTP secret from Finvasia 2FA setup
        vendor_code : From your API app (same as user_id for personal apps)
        api_secret  : SHA-256 of (user_id + password)  — see login docs
        imei        : Any string, e.g. "algo-trader-1.0"
    """

    def __init__(
        self,
        user_id: str,
        password: str,
        totp_secret: str,
        vendor_code: str,
        api_secret: str,
        imei: str = "algo-trader-1.0",
    ):
        try:
            from NorenRestApiPy.NorenApi import NorenApi
        except ImportError:
            raise ImportError(
                "NorenRestApiPy not installed. Run: pip install NorenRestApiPy"
            )

        class _ShoonyaApi(NorenApi):
            def __init__(self):
                super().__init__(
                    host="https://api.shoonya.com/NorenWClientTP/",
                    websocket="wss://api.shoonya.com/NorenWSTP/",
                )

        self._api = _ShoonyaApi()
        self._user_id    = user_id
        self._password   = password
        self._totp_secret = totp_secret
        self._vendor_code = vendor_code
        self._api_secret  = api_secret
        self._imei        = imei

        # Symbol ↔ token mapping (loaded from scrip master)
        self._sym_to_token: dict[str, str] = {}  # "RELIANCE" → "NSE|2885"
        self._token_to_sym: dict[str, str] = {}  # "NSE|2885" → "RELIANCE"

        # Live tick store
        self._tick_store: dict[str, dict] = {}   # "NSE|2885" → tick dict

        self._ws_running = False
        self._lock = threading.Lock()

        # Login on construction
        self._login()
        self._load_scrip_master()

    # ── Login ─────────────────────────────────────────────────────────────────

    def _login(self) -> None:
        totp = pyotp.TOTP(self._totp_secret).now()
        pwd_hash = hashlib.sha256(self._password.encode()).hexdigest()

        resp = self._api.login(
            userid=self._user_id,
            password=pwd_hash,
            twoFA=totp,
            vendor_code=self._vendor_code,
            api_secret=self._api_secret,
            imei=self._imei,
        )
        if resp is None or resp.get("stat") != "Ok":
            raise ConnectionError(f"Shoonya login failed: {resp}")

        logger.info("Shoonya login OK — user=%s", self._user_id)

    # ── Scrip master (symbol → token mapping) ────────────────────────────────

    def _load_scrip_master(self) -> None:
        """
        Load NSE scrip master to map symbol names to Shoonya tokens.
        Shoonya provides a CSV at a predictable URL — we download and cache it.
        """
        import csv
        import urllib.request
        import io

        url = "https://api.shoonya.com/NSE_symbols.txt.gz"
        logger.info("Loading Shoonya NSE scrip master...")
        try:
            import gzip
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = gzip.decompress(resp.read()).decode("utf-8")

            reader = csv.DictReader(io.StringIO(data))
            for row in reader:
                sym   = row.get("Symbol", "").strip()
                token = row.get("Token", "").strip()
                exch  = row.get("Exchange", "NSE").strip()
                if sym and token:
                    key = f"{exch}|{token}"
                    self._sym_to_token[sym] = key
                    self._token_to_sym[key] = sym

            logger.info("Scrip master loaded — %d symbols", len(self._sym_to_token))
        except Exception as e:
            logger.warning("Could not load scrip master: %s — using fallback lookup", e)

    def _resolve_token(self, symbol: str) -> str:
        """Return Shoonya exchange|token string for a symbol."""
        if symbol in self._sym_to_token:
            return self._sym_to_token[symbol]

        # Fallback: query API directly
        resp = self._api.searchscrip(exchange="NSE", searchtext=symbol)
        if resp and resp.get("stat") == "Ok":
            for scrip in resp.get("values", []):
                if scrip.get("tsym") == symbol:
                    key = f"NSE|{scrip['token']}"
                    self._sym_to_token[symbol] = key
                    self._token_to_sym[key] = symbol
                    return key

        raise ValueError(f"Could not resolve Shoonya token for: {symbol}")

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_ltp(self, symbol: str) -> float:
        token = self._resolve_token(symbol)
        exch, tok = token.split("|")
        resp = self._api.get_quotes(exchange=exch, token=tok)
        if resp and resp.get("stat") == "Ok":
            return float(resp.get("lp", 0))
        raise ValueError(f"LTP fetch failed for {symbol}: {resp}")

    def get_historical_candles(
        self, symbol: str, interval: str, lookback_days: int = 5
    ) -> list[dict]:
        token    = self._resolve_token(symbol)
        exch, tok = token.split("|")
        sh_interval = _INTERVAL_MAP.get(interval, "1")

        to_dt   = datetime.now()
        fr_dt   = to_dt - timedelta(days=lookback_days)

        # Shoonya expects epoch timestamps as strings
        resp = self._api.get_time_price_series(
            exchange=exch,
            token=tok,
            starttime=str(int(fr_dt.timestamp())),
            endtime=str(int(to_dt.timestamp())),
            interval=sh_interval,
        )

        if not resp:
            logger.warning("Empty historical response for %s", symbol)
            return []

        candles = []
        for bar in reversed(resp):   # Shoonya returns newest-first
            try:
                candles.append({
                    "date":   datetime.fromtimestamp(int(bar["ssboe"])),
                    "open":   float(bar["into"]),
                    "high":   float(bar["inth"]),
                    "low":    float(bar["intl"]),
                    "close":  float(bar["intc"]),
                    "volume": int(bar["intv"]),
                })
            except (KeyError, ValueError) as e:
                logger.debug("Skipping malformed bar: %s — %s", bar, e)

        return candles

    # ── WebSocket ─────────────────────────────────────────────────────────────

    def start_ticker(self, symbols: list[str]) -> None:
        tokens = [self._resolve_token(s) for s in symbols]

        def _open_callback():
            logger.info("Shoonya WebSocket connected — subscribing %d symbols", len(tokens))
            self._api.subscribe(tokens)
            self._ws_running = True

        def _tick_callback(tick):
            if not tick:
                return
            key = f"{tick.get('e','NSE')}|{tick.get('tk','')}"
            with self._lock:
                self._tick_store[key] = {
                    "instrument_token": key,
                    "last_price": float(tick.get("lp", 0)),
                    "volume_traded": int(tick.get("v", 0)),
                    "symbol": self._token_to_sym.get(key, key),
                    "raw": tick,
                }

        def _order_callback(msg):
            logger.debug("Order update: %s", msg)

        def _close_callback():
            logger.warning("Shoonya WebSocket closed")
            self._ws_running = False

        threading.Thread(
            target=self._api.start_websocket,
            kwargs=dict(
                subscribe_callback=_tick_callback,
                order_update_callback=_order_callback,
                socket_open_callback=_open_callback,
                socket_close_callback=_close_callback,
            ),
            daemon=True,
        ).start()
        logger.info("Shoonya ticker thread started")

    def stop_ticker(self) -> None:
        try:
            self._api.close_websocket()
        except Exception:
            pass
        self._ws_running = False
        logger.info("Shoonya ticker stopped")

    def get_latest_tick(self, symbol: str) -> Optional[dict]:
        token = self._sym_to_token.get(symbol)
        if not token:
            return None
        with self._lock:
            return self._tick_store.get(token)

    # ── Account ───────────────────────────────────────────────────────────────

    def get_profile(self) -> dict:
        resp = self._api.get_user_details()
        if resp and resp.get("stat") == "Ok":
            return {
                "user_id":   resp.get("actid", self._user_id),
                "user_name": resp.get("uname", ""),
                "email":     resp.get("emali", ""),
                "broker":    "Finvasia/Shoonya",
            }
        return {"user_id": self._user_id, "user_name": "", "email": "", "broker": "Finvasia/Shoonya"}

    def get_margins(self) -> dict:
        resp = self._api.get_limits()
        if resp and resp.get("stat") == "Ok":
            cash = float(resp.get("cash", 0))
            return {"net": cash, "available": cash}
        return {"net": 0, "available": 0}
