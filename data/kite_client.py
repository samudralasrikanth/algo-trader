# =============================================================================
# data/kite_client.py — Kite Connect Data Layer
# =============================================================================

import logging
from datetime import datetime, timedelta

from kiteconnect import KiteConnect
from config.settings import API_KEY, ACCESS_TOKEN, EXCHANGE

logger = logging.getLogger(__name__)

# --- Singleton Kite client ---
kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)


def get_ltp(symbol: str) -> float:
    """Return last traded price for a symbol on NSE."""
    key = f"{EXCHANGE}:{symbol}"
    data = kite.ltp(key)
    return data[key]["last_price"]


def get_historical_candles(
    symbol: str,
    interval: str,
    lookback_days: int = 5,
) -> list[dict]:
    """
    Fetch OHLCV candles from Kite historical API.

    Returns a list of dicts:
        [{"date": datetime, "open": float, "high": float,
          "low": float, "close": float, "volume": int}, ...]
    """
    instruments = kite.instruments("NSE")
    instrument = next(
        (i for i in instruments if i["tradingsymbol"] == symbol), None
    )
    if instrument is None:
        raise ValueError(f"Instrument not found for symbol: {symbol}")

    instrument_token = instrument["instrument_token"]
    to_date = datetime.now()
    from_date = to_date - timedelta(days=lookback_days)

    candles = kite.historical_data(
        instrument_token=instrument_token,
        from_date=from_date,
        to_date=to_date,
        interval=interval,
        continuous=False,
        oi=False,
    )
    logger.debug("Fetched %d candles for %s [%s]", len(candles), symbol, interval)
    return candles
