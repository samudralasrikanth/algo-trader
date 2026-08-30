# =============================================================================
# data/provider.py — Broker Adapter Factory
# =============================================================================
"""
Single import point for the rest of the system.

Usage (anywhere in the codebase):
    from data.provider import get_broker

    broker = get_broker()
    ltp = broker.get_ltp("RELIANCE")
    candles = broker.get_historical_candles("RELIANCE", "minute", 5)

Switch broker by setting BROKER=shoonya (or kite) in .env.
"""

import os
import logging
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data.adapters.base import BrokerAdapter

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass


@lru_cache(maxsize=1)
def get_broker() -> "BrokerAdapter":
    """
    Returns a singleton broker adapter based on the BROKER env var.
    Defaults to 'kite' if not set.

    Supported values:
        BROKER=kite     → KiteAdapter   (Zerodha Kite Connect, ₹2,360/mo)
        BROKER=shoonya  → ShoonyaAdapter (Finvasia, free)
    """
    broker = os.getenv("BROKER", "kite").lower().strip()
    logger.info("Initialising broker adapter: %s", broker)

    if broker == "shoonya":
        return _build_shoonya()
    elif broker == "yfinance":
        return _build_yfinance()
    else:
        return _build_kite()

def _build_yfinance():
    from data.adapters.yfinance_adapter import YFinanceAdapter
    return YFinanceAdapter()

def _build_kite():
    from data.adapters.kite_adapter import KiteAdapter
    api_key      = os.getenv("KITE_API_KEY", "")
    access_token = os.getenv("KITE_ACCESS_TOKEN", "")
    if not api_key or not access_token:
        raise EnvironmentError(
            "KITE_API_KEY and KITE_ACCESS_TOKEN must be set in .env"
        )
    return KiteAdapter(api_key=api_key, access_token=access_token)


def _build_shoonya():
    from data.adapters.shoonya_adapter import ShoonyaAdapter

    required = {
        "SHOONYA_USER_ID":     os.getenv("SHOONYA_USER_ID", ""),
        "SHOONYA_PASSWORD":    os.getenv("SHOONYA_PASSWORD", ""),
        "SHOONYA_TOTP_SECRET": os.getenv("SHOONYA_TOTP_SECRET", ""),
        "SHOONYA_VENDOR_CODE": os.getenv("SHOONYA_VENDOR_CODE", ""),
        "SHOONYA_API_SECRET":  os.getenv("SHOONYA_API_SECRET", ""),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(
            f"Missing Shoonya credentials in .env: {missing}\n"
            "Run: python3 auth/shoonya_login.py to set them up."
        )

    return ShoonyaAdapter(
        user_id=required["SHOONYA_USER_ID"],
        password=required["SHOONYA_PASSWORD"],
        totp_secret=required["SHOONYA_TOTP_SECRET"],
        vendor_code=required["SHOONYA_VENDOR_CODE"],
        api_secret=required["SHOONYA_API_SECRET"],
        imei=os.getenv("SHOONYA_IMEI", "algo-trader-1.0"),
    )
