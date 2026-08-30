# =============================================================================
# data/websocket.py — KiteTicker Live Feed + Candle Builder
# =============================================================================
"""
Two responsibilities:
    1. Stream live ticks via KiteTicker (daemon thread)
    2. Aggregate ticks → completed OHLCV minute candles (CandleBuilder)

Public API:
    start_ticker(symbols)           — start streaming
    stop_ticker()                   — graceful shutdown
    get_latest_tick(symbol)         — latest raw tick dict
    get_completed_candles(symbol)   — deque of completed OHLCV bars
    get_live_bar(symbol)            — current (incomplete) bar
"""

import logging
import threading
from collections import defaultdict, deque
from datetime import datetime
from typing import Optional

from kiteconnect import KiteTicker
from config.settings import API_KEY, ACCESS_TOKEN, EXCHANGE, TIMEFRAME
from data.kite_client import kite

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
_tick_store: dict[int, dict] = {}               # token → latest tick
_token_to_symbol: dict[int, str] = {}
_symbol_to_token: dict[str, int] = {}

# Completed candles per symbol: deque capped at 500 bars
_completed_candles: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
# In-progress bar per symbol
_live_bar: dict[str, dict] = {}

_ticker: Optional[KiteTicker] = None
_ticker_thread: Optional[threading.Thread] = None
_lock = threading.Lock()

# Map Kite interval string → seconds per bar
_INTERVAL_SECONDS = {
    "minute":   60,
    "3minute":  180,
    "5minute":  300,
    "15minute": 900,
    "30minute": 1800,
    "60minute": 3600,
}


# ---------------------------------------------------------------------------
# Candle Builder
# ---------------------------------------------------------------------------

def _bar_key(ts: datetime, interval_secs: int) -> datetime:
    """Floor a timestamp to the start of the current bar."""
    epoch = int(ts.timestamp())
    floored = (epoch // interval_secs) * interval_secs
    return datetime.fromtimestamp(floored)


def _update_candle(symbol: str, ltp: float, volume: int, ts: datetime) -> None:
    """
    Update the live bar with a new tick.
    If the bar's minute has rolled over, finalize and store the old bar.
    """
    interval_secs = _INTERVAL_SECONDS.get(TIMEFRAME, 60)
    current_key = _bar_key(ts, interval_secs)

    with _lock:
        bar = _live_bar.get(symbol)

        if bar is None:
            # First tick ever for this symbol
            _live_bar[symbol] = {
                "date":   current_key,
                "open":   ltp,
                "high":   ltp,
                "low":    ltp,
                "close":  ltp,
                "volume": volume,
            }
            return

        if current_key > bar["date"]:
            # New bar started — finalise old bar
            completed = dict(bar)
            _completed_candles[symbol].append(completed)
            logger.debug(
                "Candle closed: %-10s  %s  O=%.2f H=%.2f L=%.2f C=%.2f V=%d",
                symbol, bar["date"], bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"],
            )
            # Open fresh bar
            _live_bar[symbol] = {
                "date":   current_key,
                "open":   ltp,
                "high":   ltp,
                "low":    ltp,
                "close":  ltp,
                "volume": volume,
            }
        else:
            # Same bar — update OHLCV
            bar["high"]   = max(bar["high"], ltp)
            bar["low"]    = min(bar["low"], ltp)
            bar["close"]  = ltp
            bar["volume"] += volume


# ---------------------------------------------------------------------------
# KiteTicker callbacks
# ---------------------------------------------------------------------------

def _on_ticks(ws, ticks):
    now = datetime.now()
    for tick in ticks:
        token  = tick["instrument_token"]
        ltp    = tick.get("last_price", 0)
        volume = tick.get("volume_traded", 0)
        symbol = _token_to_symbol.get(token)

        _tick_store[token] = tick

        if symbol:
            _update_candle(symbol, ltp, volume, now)


def _on_connect(ws, response):
    tokens = list(_token_to_symbol.keys())
    ws.subscribe(tokens)
    ws.set_mode(ws.MODE_QUOTE, tokens)
    logger.info("WebSocket connected — subscribed %d instruments", len(tokens))


def _on_close(ws, code, reason):
    logger.warning("WebSocket closed: code=%s reason=%s", code, reason)


def _on_error(ws, code, reason):
    logger.error("WebSocket error: code=%s reason=%s", code, reason)


def _on_reconnect(ws, attempts_count):
    logger.info("WebSocket reconnecting... attempt %d", attempts_count)


def _on_noreconnect(ws):
    logger.critical("WebSocket gave up reconnecting!")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_ticker(symbols: list[str]) -> None:
    """Resolve tokens for symbols and start KiteTicker in a daemon thread."""
    global _ticker, _ticker_thread

    instruments = kite.instruments(EXCHANGE)
    for inst in instruments:
        if inst["tradingsymbol"] in symbols:
            token = inst["instrument_token"]
            _token_to_symbol[token] = inst["tradingsymbol"]
            _symbol_to_token[inst["tradingsymbol"]] = token

    missing = [s for s in symbols if s not in _symbol_to_token]
    if missing:
        logger.warning("Could not resolve tokens for: %s", missing)

    _ticker = KiteTicker(API_KEY, ACCESS_TOKEN)
    _ticker.on_ticks      = _on_ticks
    _ticker.on_connect    = _on_connect
    _ticker.on_close      = _on_close
    _ticker.on_error      = _on_error
    _ticker.on_reconnect  = _on_reconnect
    _ticker.on_noreconnect = _on_noreconnect

    _ticker_thread = threading.Thread(
        target=_ticker.connect,
        kwargs={"threaded": False},
        daemon=True,
    )
    _ticker_thread.start()
    logger.info("KiteTicker started in background thread")


def stop_ticker() -> None:
    if _ticker:
        _ticker.close()
        logger.info("KiteTicker stopped")


def get_latest_tick(symbol: str) -> Optional[dict]:
    token = _symbol_to_token.get(symbol)
    return _tick_store.get(token) if token else None


def get_completed_candles(symbol: str) -> list[dict]:
    """Return a snapshot list of completed OHLCV bars (newest last)."""
    with _lock:
        return list(_completed_candles[symbol])


def get_live_bar(symbol: str) -> Optional[dict]:
    """Return the current (still open) bar for a symbol."""
    with _lock:
        bar = _live_bar.get(symbol)
        return dict(bar) if bar else None


def candles_ready(symbol: str, min_bars: int = 20) -> bool:
    """True once we have enough bars to compute indicators."""
    return len(_completed_candles[symbol]) >= min_bars
