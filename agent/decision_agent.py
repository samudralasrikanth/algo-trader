# =============================================================================
# agent/decision_agent.py — AI Gate for Signal Filtering
# =============================================================================
"""
Lightweight confidence-based filter that sits between the strategy signal
and order execution. Designed to be swapped out for an ML model later.

Currently implements:
    1. Raw confidence threshold filter
    2. Regime filter — suppress SELL signals in a strong uptrend
    3. Cooldown filter — skip re-entry within N minutes of a loss
"""

import logging
from datetime import datetime, timedelta
from config.settings import CAPITAL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_last_loss_time: dict[str, datetime] = {}   # symbol -> timestamp of last losing trade
COOLDOWN_MINUTES = 15                        # wait N minutes after a loss before re-entering


# ---------------------------------------------------------------------------
# Main filter
# ---------------------------------------------------------------------------

def filter_signal(
    signal: str,
    symbol: str,
    confidence: float = 0.7,
    price: float = 0.0,
    ema_trend: float = 0.0,
) -> str:
    """
    Gate the raw strategy signal before sending to the executor.

    Args:
        signal      : "BUY", "SELL", or "HOLD" from strategy layer
        symbol      : Ticker — used for cooldown tracking
        confidence  : Model/heuristic confidence in [0, 1]
        price       : Current LTP (for regime filter)
        ema_trend   : Long EMA value (e.g. 50-period EMA)

    Returns:
        Filtered signal: "BUY", "SELL", or "HOLD"
    """
    if signal == "HOLD":
        return "HOLD"

    # Gate 1: Low confidence
    if confidence < 0.6:
        logger.debug("Signal %s filtered — low confidence %.2f", signal, confidence)
        return "HOLD"

    # Gate 2: Regime filter (don't short in a strong uptrend)
    if signal == "SELL" and ema_trend > 0 and price > ema_trend * 1.01:
        logger.debug("SELL filtered — price %.2f is >1%% above EMA %.2f", price, ema_trend)
        return "HOLD"

    # Gate 3: Cooldown after a loss
    if symbol in _last_loss_time:
        elapsed = datetime.now() - _last_loss_time[symbol]
        if elapsed < timedelta(minutes=COOLDOWN_MINUTES):
            remaining = COOLDOWN_MINUTES - int(elapsed.total_seconds() / 60)
            logger.debug(
                "Signal %s filtered — %s in cooldown for %d more min", signal, symbol, remaining
            )
            return "HOLD"

    logger.info("Signal APPROVED: %s | symbol=%s confidence=%.2f", signal, symbol, confidence)
    return signal


# ---------------------------------------------------------------------------
# Feedback (called by runner after a trade closes)
# ---------------------------------------------------------------------------

def record_trade_outcome(symbol: str, pnl: float) -> None:
    """
    Called after a position closes. If the trade was a loss, start cooldown.
    """
    if pnl < 0:
        _last_loss_time[symbol] = datetime.now()
        logger.info("Cooldown started for %s after loss of ₹%.2f", symbol, abs(pnl))
    else:
        # Clear any stale cooldown on a win
        _last_loss_time.pop(symbol, None)


# ---------------------------------------------------------------------------
# Confidence estimator (placeholder — wire ML model here)
# ---------------------------------------------------------------------------

def estimate_confidence(rsi: float, volume_ratio: float, price_vs_vwap: float) -> float:
    """
    Simple heuristic confidence in [0, 1].
    Replace with a calibrated ML classifier output (e.g. XGBoost predict_proba).

    Inputs:
        rsi             : RSI value
        volume_ratio    : current_volume / avg_volume
        price_vs_vwap   : (price - vwap) / vwap  — signed %
    """
    score = 0.5  # base

    # RSI conviction
    if rsi > 65 or rsi < 35:
        score += 0.15
    elif rsi > 55 or rsi < 45:
        score += 0.05

    # Volume conviction
    if volume_ratio > 2.0:
        score += 0.2
    elif volume_ratio > 1.5:
        score += 0.1

    # Price-VWAP alignment
    if abs(price_vs_vwap) > 0.005:
        score += 0.15

    return min(score, 1.0)
