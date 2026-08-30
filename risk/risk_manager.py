# =============================================================================
# risk/risk_manager.py — Position Sizing & Portfolio Guard Rails
# =============================================================================

import logging
from config.settings import CAPITAL, RISK_PER_TRADE, MAX_OPEN_POSITIONS, BROKERAGE

logger = logging.getLogger(__name__)


def calculate_position_size(entry: float, stop_loss: float) -> int:
    """
    Fixed-fractional position sizing.

    risk_amount     = CAPITAL × RISK_PER_TRADE
    risk_per_share  = |entry - stop_loss|
    qty             = floor(risk_amount / risk_per_share)

    Returns at least 1 share if risk_per_share > 0.
    """
    if stop_loss <= 0 or entry <= 0:
        logger.warning("Invalid entry=%.2f or stop_loss=%.2f — returning 0", entry, stop_loss)
        return 0

    risk_per_share = abs(entry - stop_loss)
    if risk_per_share == 0:
        logger.warning("Stop-loss equals entry price — returning 0")
        return 0

    risk_amount = CAPITAL * RISK_PER_TRADE
    qty = int(risk_amount / risk_per_share)
    qty = max(qty, 1)

    notional = qty * entry
    logger.info(
        "Position size: qty=%d @ ₹%.2f | notional=₹%.0f | risk=₹%.0f",
        qty, entry, notional, qty * risk_per_share,
    )
    return qty


def can_open_position(open_positions: dict) -> bool:
    """
    Return True only if we have room for one more position.
    Enforces MAX_OPEN_POSITIONS guard rail.
    """
    count = len(open_positions)
    if count >= MAX_OPEN_POSITIONS:
        logger.warning(
            "Max open positions reached (%d/%d) — skipping new entry",
            count, MAX_OPEN_POSITIONS,
        )
        return False
    return True


def net_pnl(trades: list[dict]) -> float:
    """
    Calculate net PnL across all closed trades (after brokerage).

    Each trade dict must have:
        side, entry_price, exit_price, qty
    """
    total = 0.0
    for t in trades:
        side = t.get("side")
        entry = t.get("entry_price", 0)
        exit_p = t.get("exit_price", 0)
        qty = t.get("qty", 0)

        if side == "BUY":
            gross = (exit_p - entry) * qty
        elif side == "SELL":
            gross = (entry - exit_p) * qty
        else:
            gross = 0.0

        net = gross - (2 * BROKERAGE)  # entry + exit brokerage
        total += net

    return round(total, 2)
