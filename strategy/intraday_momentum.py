# =============================================================================
# strategy/intraday_momentum.py — Momentum Signal Generation
# =============================================================================
"""
Signal logic:
    BUY  : price > VWAP  AND  RSI > 60  AND  volume > 1.5× avg_volume
    SELL : price < VWAP  AND  RSI < 40
    HOLD : everything else

Exit logic (call check_exit on every bar for open positions):
    - ATR-based trailing stop-loss
    - R:R target hit
    - Time exit at market close
"""

import logging
from datetime import datetime
from typing import Optional, Tuple
from config.settings import (
    TRAILING_SL_PCT,
    TARGET_MULTIPLIER,
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entry Signal
# ---------------------------------------------------------------------------

def generate_signal(
    price: float,
    vwap: float,
    rsi: float,
    volume: int,
    avg_volume: float,
) -> str:
    """
    Returns "BUY", "SELL", or "HOLD".

    Args:
        price       : Latest close/LTP
        vwap        : Current session VWAP
        rsi         : RSI value (0–100)
        volume      : Current bar volume
        avg_volume  : Rolling average volume
    """
    if any(v is None or (isinstance(v, float) and v != v) for v in [price, vwap, rsi, volume, avg_volume]):
        logger.warning("NaN/None in signal inputs — returning HOLD")
        return "HOLD"

    if avg_volume == 0:
        return "HOLD"

    above_vwap = price > vwap
    strong_rsi_long = rsi > 60
    strong_rsi_short = rsi < 40
    volume_surge = volume > 1.5 * avg_volume

    if above_vwap and strong_rsi_long and volume_surge:
        logger.info(
            "BUY signal | price=%.2f vwap=%.2f rsi=%.1f vol=%d avg_vol=%.0f",
            price, vwap, rsi, volume, avg_volume,
        )
        return "BUY"

    if not above_vwap and strong_rsi_short:
        logger.info(
            "SELL signal | price=%.2f vwap=%.2f rsi=%.1f",
            price, vwap, rsi,
        )
        return "SELL"

    return "HOLD"


# ---------------------------------------------------------------------------
# Exit Signal
# ---------------------------------------------------------------------------

def check_exit(
    position: dict,
    current_price: float,
    current_time: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """
    Evaluate whether an open position should be closed.

    Args:
        position : dict with keys:
            side        : "BUY" or "SELL"
            entry_price : float
            stop_loss   : float (initial stop; updated as trailing moves)
            target      : float
            qty         : int
        current_price : Latest market price
        current_time  : datetime (defaults to now)

    Returns:
        (should_exit: bool, reason: str)
    """
    if current_time is None:
        current_time = datetime.now()

    side = position["side"]
    entry = position["entry_price"]
    stop_loss = position["stop_loss"]
    target = position["target"]

    # --- Time exit: close 5 minutes before market close ---
    close_hour = MARKET_CLOSE_HOUR
    close_min = MARKET_CLOSE_MINUTE - 5
    if current_time.hour > close_hour or (
        current_time.hour == close_hour and current_time.minute >= close_min
    ):
        return True, "TIME_EXIT"

    if side == "BUY":
        # Trailing SL: ratchet up as price moves in favour
        new_trailing_sl = current_price * (1 - TRAILING_SL_PCT)
        if new_trailing_sl > stop_loss:
            position["stop_loss"] = new_trailing_sl  # mutates in-place

        if current_price <= position["stop_loss"]:
            return True, "STOP_LOSS"
        if current_price >= target:
            return True, "TARGET_HIT"

    elif side == "SELL":
        # Trailing SL: ratchet down as price drops
        new_trailing_sl = current_price * (1 + TRAILING_SL_PCT)
        if new_trailing_sl < stop_loss:
            position["stop_loss"] = new_trailing_sl

        if current_price >= position["stop_loss"]:
            return True, "STOP_LOSS"
        if current_price <= target:
            return True, "TARGET_HIT"

    return False, ""


# ---------------------------------------------------------------------------
# Target & Stop-Loss Initialiser
# ---------------------------------------------------------------------------

def compute_trade_levels(side: str, entry: float, atr_value: float) -> dict:
    """
    Compute initial stop-loss and target using ATR-based sizing.

    stop_loss = entry ± 1.5 × ATR
    target    = entry ± TARGET_MULTIPLIER × risk
    """
    risk = 1.5 * atr_value

    if side == "BUY":
        stop_loss = entry - risk
        target = entry + TARGET_MULTIPLIER * risk
    else:  # SELL
        stop_loss = entry + risk
        target = entry - TARGET_MULTIPLIER * risk

    return {"entry_price": entry, "stop_loss": stop_loss, "target": target, "side": side}
