# =============================================================================
# config/settings.py — Single Source of Truth
# =============================================================================

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # dotenv optional; fall back to real env vars or defaults

# --- Kite Connect Credentials (set in .env, never hardcode here) ---
API_KEY      = os.getenv("KITE_API_KEY", "")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN", "")

# --- Capital & Risk ---
CAPITAL = 100_000          # Total paper-trading capital (INR)
RISK_PER_TRADE = 0.01      # 1% risk per trade

# --- Execution Costs ---
SLIPPAGE = 0.001           # 0.1% slippage model
BROKERAGE = 20             # Flat ₹20 per order (Zerodha style)

# --- Universe ---
SYMBOLS = ["RELIANCE", "HDFCBANK", "ICICIBANK"]
EXCHANGE = "NSE"
TIMEFRAME = "minute"       # Kite interval: minute | 3minute | 5minute | 15minute

# --- Indicator Params ---
RSI_PERIOD = 14
VWAP_WINDOW = "day"        # Reset VWAP at market open each day

# --- Risk Guard Rails ---
MAX_OPEN_POSITIONS = 3     # Never hold more than N concurrent positions
TRAILING_SL_PCT = 0.005    # 0.5% trailing stop-loss
TARGET_MULTIPLIER = 2.0    # R:R target = 2x the risk taken

# --- Market Hours (IST) ---
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30

# --- Scheduler ---
LOOP_INTERVAL_SECONDS = 60  # How often the main loop ticks
