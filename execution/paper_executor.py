# =============================================================================
# execution/paper_executor.py — Paper Trading Execution Engine
# =============================================================================
"""
Maintains a live state of:
    open_positions  : {symbol -> position_dict}
    closed_trades   : [trade_dict, ...]

position_dict keys:
    symbol, side, entry_price, exit_price, qty,
    stop_loss, target, opened_at, closed_at, exit_reason, pnl
"""

import logging
from datetime import datetime
from typing import Optional
from config.settings import SLIPPAGE, BROKERAGE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State (in-memory; persisted separately via storage/db.py)
# ---------------------------------------------------------------------------
open_positions: dict[str, dict] = {}
closed_trades: list[dict] = []


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def execute_trade(
    symbol: str,
    side: str,
    price: float,
    qty: int,
    stop_loss: float,
    target: float,
) -> dict:
    """
    Simulate order execution with slippage.
    Raises ValueError if qty <= 0 or a position already exists.
    """
    if qty <= 0:
        raise ValueError(f"Invalid qty={qty} for {symbol}")
    if symbol in open_positions:
        raise ValueError(f"Position already open for {symbol} — no pyramiding")

    slippage_factor = 1 + SLIPPAGE if side == "BUY" else 1 - SLIPPAGE
    executed_price = round(price * slippage_factor, 2)

    position = {
        "symbol": symbol,
        "side": side,
        "entry_price": executed_price,
        "exit_price": None,
        "qty": qty,
        "stop_loss": stop_loss,
        "target": target,
        "opened_at": datetime.now().isoformat(),
        "closed_at": None,
        "exit_reason": None,
        "pnl": None,
    }

    open_positions[symbol] = position
    logger.info(
        "OPEN  %-10s %-4s qty=%4d @ ₹%.2f | SL=₹%.2f TGT=₹%.2f",
        symbol, side, qty, executed_price, stop_loss, target,
    )
    return position


# ---------------------------------------------------------------------------
# Exit
# ---------------------------------------------------------------------------

def close_position(symbol: str, exit_price: float, reason: str) -> dict:
    """
    Close an open position and compute PnL (net of brokerage).
    Moves position from open_positions → closed_trades.
    """
    if symbol not in open_positions:
        raise KeyError(f"No open position to close for {symbol}")

    pos = open_positions.pop(symbol)
    slippage_factor = 1 - SLIPPAGE if pos["side"] == "BUY" else 1 + SLIPPAGE
    executed_exit = round(exit_price * slippage_factor, 2)

    if pos["side"] == "BUY":
        gross_pnl = (executed_exit - pos["entry_price"]) * pos["qty"]
    else:
        gross_pnl = (pos["entry_price"] - executed_exit) * pos["qty"]

    net = round(gross_pnl - 2 * BROKERAGE, 2)

    pos.update(
        exit_price=executed_exit,
        closed_at=datetime.now().isoformat(),
        exit_reason=reason,
        pnl=net,
    )
    closed_trades.append(pos)

    emoji = "✅" if net >= 0 else "❌"
    logger.info(
        "CLOSE %s %-10s %-4s qty=%4d @ ₹%.2f | PnL=₹%.2f [%s]",
        emoji, symbol, pos["side"], pos["qty"], executed_exit, net, reason,
    )
    return pos


# ---------------------------------------------------------------------------
# Multi-Leg (Straddle) Execution
# ---------------------------------------------------------------------------

def execute_straddle(
    spot_symbol: str,
    ce_symbol: str,
    pe_symbol: str,
    ce_price: float,
    pe_price: float,
    qty: int,
    sl_pct: float = 0.20,
    tgt_pct: float = 0.40,
) -> dict:
    """
    Simulate a Long Straddle entry (Buy ATM CE + Buy ATM PE).
    Tracks COMBINED premium for stop loss and target.
    """
    if qty <= 0:
        raise ValueError(f"Invalid qty={qty} for {spot_symbol} straddle")
    if spot_symbol in open_positions:
        raise ValueError(f"Position already open for {spot_symbol}")

    slippage_factor = 1 + SLIPPAGE
    ce_exec = round(ce_price * slippage_factor, 2)
    pe_exec = round(pe_price * slippage_factor, 2)
    combined_entry = ce_exec + pe_exec

    position = {
        "symbol": spot_symbol,
        "side": "STRADDLE",
        "ce_symbol": ce_symbol,
        "pe_symbol": pe_symbol,
        "ce_entry": ce_exec,
        "pe_entry": pe_exec,
        "entry_price": combined_entry,
        "exit_price": None,
        "qty": qty,
        "stop_loss": round(combined_entry * (1 - sl_pct), 2),
        "target": round(combined_entry * (1 + tgt_pct), 2),
        "opened_at": datetime.now().isoformat(),
        "closed_at": None,
        "exit_reason": None,
        "pnl": None,
    }

    open_positions[spot_symbol] = position
    logger.info(
        "OPEN  %-10s STRD qty=%4d | CE=₹%.2f PE=₹%.2f | Combined=₹%.2f SL=₹%.2f TGT=₹%.2f",
        spot_symbol, qty, ce_exec, pe_exec, combined_entry, position["stop_loss"], position["target"],
    )
    return position


def close_straddle(spot_symbol: str, ce_exit: float, pe_exit: float, reason: str) -> dict:
    """
    Close both legs of a Straddle. PnL is based on combined premium difference.
    """
    if spot_symbol not in open_positions:
        raise KeyError(f"No open straddle to close for {spot_symbol}")

    pos = open_positions.pop(spot_symbol)
    if pos["side"] != "STRADDLE":
        raise ValueError(f"Position {spot_symbol} is not a STRADDLE")

    slippage_factor = 1 - SLIPPAGE
    ce_exec = round(ce_exit * slippage_factor, 2)
    pe_exec = round(pe_exit * slippage_factor, 2)
    combined_exit = ce_exec + pe_exec

    # Buy premium (entry) vs Sell premium (exit)
    gross_pnl = (combined_exit - pos["entry_price"]) * pos["qty"]
    
    # 2 legs = 4 orders total (Buy CE, Buy PE, Sell CE, Sell PE)
    net = round(gross_pnl - (4 * BROKERAGE), 2)

    pos.update(
        exit_price=combined_exit,
        ce_exit=ce_exec,
        pe_exit=pe_exec,
        closed_at=datetime.now().isoformat(),
        exit_reason=reason,
        pnl=net,
    )
    closed_trades.append(pos)

    emoji = "✅" if net >= 0 else "❌"
    logger.info(
        "CLOSE %s %-10s STRD qty=%4d | Exit CE=₹%.2f PE=₹%.2f | Comb=₹%.2f | PnL=₹%.2f [%s]",
        emoji, spot_symbol, pos["qty"], ce_exec, pe_exec, combined_exit, net, reason,
    )
    return pos

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_open_position(symbol: str) -> Optional[dict]:
    return open_positions.get(symbol)


def summary() -> dict:
    total_pnl = sum(t["pnl"] for t in closed_trades if t["pnl"] is not None)
    wins = sum(1 for t in closed_trades if (t["pnl"] or 0) > 0)
    losses = sum(1 for t in closed_trades if (t["pnl"] or 0) <= 0)
    return {
        "open": len(open_positions),
        "closed": len(closed_trades),
        "total_pnl": round(total_pnl, 2),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / max(len(closed_trades), 1) * 100, 1),
    }
