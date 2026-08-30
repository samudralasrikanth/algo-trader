# =============================================================================
# data/adapters/kite_adapter.py — Zerodha Kite Connect Adapter
# =============================================================================

import logging
from datetime import datetime, timedelta
from typing import Optional

from kiteconnect import KiteConnect, KiteTicker
from data.adapters.base import BrokerAdapter
from config.settings import EXCHANGE, TIMEFRAME

logger = logging.getLogger(__name__)

# Kite interval → seconds
_INTERVAL_SECONDS = {
    "minute": 60, "3minute": 180, "5minute": 300,
    "15minute": 900, "30minute": 1800, "60minute": 3600,
}


class KiteAdapter(BrokerAdapter):

    def __init__(self, api_key: str, access_token: str):
        self._kite = KiteConnect(api_key=api_key)
        self._kite.set_access_token(access_token)
        self._api_key = api_key
        self._access_token = access_token

        # WebSocket state
        self._ticker: Optional[KiteTicker] = None
        self._tick_store: dict[int, dict] = {}
        self._token_map: dict[str, int] = {}
        self._rev_map:   dict[int, str] = {}

        import threading
        self._lock = threading.Lock()

    # ── Market data ──────────────────────────────────────────────────────────

    def get_ltp(self, symbol: str) -> float:
        key  = f"{EXCHANGE}:{symbol}"
        data = self._kite.ltp(key)
        return data[key]["last_price"]

    def get_historical_candles(
        self, symbol: str, interval: str, lookback_days: int = 5
    ) -> list[dict]:
        instruments = self._kite.instruments(EXCHANGE)
        inst = next((i for i in instruments if i["tradingsymbol"] == symbol), None)
        if not inst:
            raise ValueError(f"Instrument not found: {symbol}")
        to_date   = datetime.now()
        from_date = to_date - timedelta(days=lookback_days)
        return self._kite.historical_data(
            instrument_token=inst["instrument_token"],
            from_date=from_date,
            to_date=to_date,
            interval=interval,
            continuous=False,
            oi=False,
        )

    # ── WebSocket ─────────────────────────────────────────────────────────────

    def start_ticker(self, symbols: list[str]) -> None:
        import threading
        instruments = self._kite.instruments(EXCHANGE)
        for inst in instruments:
            if inst["tradingsymbol"] in symbols:
                t = inst["instrument_token"]
                self._token_map[inst["tradingsymbol"]] = t
                self._rev_map[t] = inst["tradingsymbol"]

        self._ticker = KiteTicker(self._api_key, self._access_token)
        self._ticker.on_ticks   = self._on_ticks
        self._ticker.on_connect = self._on_connect
        threading.Thread(
            target=self._ticker.connect, kwargs={"threaded": False}, daemon=True
        ).start()
        logger.info("KiteAdapter: ticker started for %s", symbols)

    def _on_connect(self, ws, _):
        tokens = list(self._rev_map.keys())
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_QUOTE, tokens)

    def _on_ticks(self, ws, ticks):
        for tick in ticks:
            self._tick_store[tick["instrument_token"]] = tick

    def stop_ticker(self) -> None:
        if self._ticker:
            self._ticker.close()

    def get_latest_tick(self, symbol: str) -> Optional[dict]:
        token = self._token_map.get(symbol)
        return self._tick_store.get(token) if token else None

    # ── Account ───────────────────────────────────────────────────────────────

    def get_profile(self) -> dict:
        p = self._kite.profile()
        return {"user_id": p["user_id"], "user_name": p["user_name"], "email": p["email"]}

    def get_margins(self) -> dict:
        m = self._kite.margins().get("equity", {})
        return {"net": m.get("net", 0), "available": m.get("available", {}).get("live_balance", 0)}
